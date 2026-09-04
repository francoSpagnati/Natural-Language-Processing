"""Traduzione di una menzione testuale nel codice della knowledge base.

Questo modulo esiste per una ragione precisa: le tre pipeline di estrazione
(deterministica, LLM, NER+EL) devono normalizzare *allo stesso modo*. Se ognuna
avesse la sua logica di codifica, il confronto dello step 6 misurerebbe la somma
di due differenze -- estrazione e codifica -- senza poterle separare. Qui la
codifica e' una sola, condivisa, e la sola variabile che resta e' quella che si
vuole misurare.

Vale inoltre il vincolo di provenienza del progetto: nessun codice nasce qui.
ATC viene dalla mappatura su AIFA prodotta dallo step 2, ICD-10 dall'indice
estratto dal volume ufficiale italiano nello step 2. Le menzioni che nessuna
delle due fonti copre restano `NIL`, segnalate e non indovinate.
"""

from __future__ import annotations

import json
import re
import threading
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from explore_dataset import radice_nome_commerciale
from schema import StatoNormalizzazione

RADICE = Path(__file__).resolve().parent.parent
PERCORSO_MAPPATURA_ATC = RADICE / "data" / "interim" / "mappatura_atc.json"
PERCORSO_TERMINOLOGIA_ICD = RADICE / "data" / "interim" / "terminologia_icd10.json"

_SPAZI = re.compile(r"\s+")
_PUNTEGGIATURA_ESTERNA = re.compile(r"^[\s\-–—•.,;:()\"']+|[\s\-–—•.,;:()\"']+$")


def normalizza(testo: str) -> str:
    """Forma comparabile di una menzione: minuscola, spazi e bordi ripuliti.

    Deliberatamente conservativa. Non toglie accenti ne' applica stemming: una
    normalizzazione aggressiva farebbe collimare termini clinicamente distinti
    (per esempio singolare e plurale di sedi anatomiche diverse) e trasformerebbe
    un collegamento mancato -- visibile e misurabile -- in uno sbagliato e muto.
    """
    return _SPAZI.sub(" ", _PUNTEGGIATURA_ESTERNA.sub("", testo)).lower()


class RisolutoreATC:
    """Traduce una forma testuale di farmaco nel suo codice ATC.

    Legge la mappatura prodotta dallo step 2 invece di ricalcolarla: la
    risoluzione e' gia' stata fatta, verificata e documentata, e rifarla qui
    significherebbe avere due verita' possibili sullo stesso dato.
    """

    def __init__(self, percorso: Path = PERCORSO_MAPPATURA_ATC) -> None:
        dati = json.loads(percorso.read_text(encoding="utf-8"))
        self.per_forma = {v["forma_grezza"].lower(): v for v in dati["voci"]}

    def risolvi(self, nome: str) -> tuple[str | None, StatoNormalizzazione, str | None]:
        """(codice ATC, stato, fonte) per una forma testuale."""
        voce = self.per_forma.get(nome.strip().lower())
        if voce is None:
            return None, StatoNormalizzazione.NIL, None
        return voce["codice_atc"], StatoNormalizzazione(voce["stato"]), voce["fonte"]

    def risolvi_menzione(
        self, menzione: str
    ) -> tuple[str | None, StatoNormalizzazione, str | None, str]:
        """Come `risolvi`, ma accetta anche una menzione composta.

        Nel referto di dimissione un farmaco e' scritto per esteso, per esempio
        "Furosemide (Lasix cpr. 25 mg)": principio attivo, nome commerciale,
        forma e dose in una stringa sola. Il vocabolario ATC ha invece una voce
        per "Furosemide" e una per "Lasix", quindi la stringa intera non risolve
        mai. La pipeline A non incontra il problema perche' il suo parser separa
        i tre pezzi prima di cercarli; qui la scomposizione va fatta a valle,
        sulla menzione che il modello ha citato alla lettera.

        L'ordine e': prima la menzione intera, poi il principio attivo che la
        precede, poi il nome commerciale fra parentesi (ripulito da forma e dose
        con la funzione gia' usata nello step 0). Il quarto valore restituito
        dice quale forma ha prodotto il collegamento, perche' la provenienza
        deve restare vera anche quando il codice e' corretto.

        Se principio attivo e nome commerciale portano a codici diversi il
        risultato e' AMBIGUO e nessuno dei due viene scelto: un disaccordo fra
        due vie che dovrebbero concordare e' un dato da guardare, non da
        risolvere in silenzio.
        """
        codice, stato, fonte = self.risolvi(menzione)
        if stato is not StatoNormalizzazione.NIL:
            return codice, stato, fonte, menzione.strip()

        principio, _, resto = menzione.partition("(")
        if not resto:
            return None, StatoNormalizzazione.NIL, None, menzione.strip()
        commerciale = radice_nome_commerciale(resto.rstrip(") "))

        da_principio = self.risolvi(principio.strip())
        da_commerciale = self.risolvi(commerciale) if commerciale else (
            None,
            StatoNormalizzazione.NIL,
            None,
        )

        risolti = [
            (esito, forma)
            for esito, forma in (
                (da_principio, principio.strip()),
                (da_commerciale, commerciale),
            )
            if esito[1] is not StatoNormalizzazione.NIL
        ]
        if not risolti:
            return None, StatoNormalizzazione.NIL, None, menzione.strip()

        codici = {esito[0] for esito, _ in risolti if esito[0]}
        if len(codici) > 1:
            return None, StatoNormalizzazione.AMBIGUO, None, menzione.strip()

        (codice, stato, fonte), forma = risolti[0]
        return codice, stato, fonte, forma


@dataclass(frozen=True)
class EsitoICD:
    """Esito di un collegamento a ICD-10, con il metodo che l'ha prodotto.

    Il metodo viaggia insieme al codice perche' un codice di categoria e uno di
    sottocategoria non valgono la stessa cosa: il primo dice "fibrillazione
    atriale", il secondo dice quale. Chi legge lo stato paziente deve poterli
    distinguere senza risalire al testo.
    """

    codice: str | None
    stato: StatoNormalizzazione
    concetto: str | None
    candidati: tuple[str, ...]
    metodo: str


class RisolutoreICD:
    """Traduce una menzione di condizione in un codice ICD-10.

    Tre passaggi, tutti ancorati all'indice estratto dal volume ufficiale.

    1. **Termine esatto.** La menzione normalizzata compare nell'indice.

    2. **Generalizzazione a categoria.** Il lessico clinico e quello del volume
       divergono: "fibrillazione atriale" non e' un termine indicizzato, perche'
       l'ICD elenca solo le forme qualificate -- parossistica (I48.0),
       persistente (I48.1), cronica (I48.2) -- e la categoria che le raccoglie.
       Quando *tutti* i termini dell'indice che cominciano con la menzione
       ricadono in un'unica categoria a 3 caratteri, quella categoria e' cio'
       che la menzione denota, e il suo codice e' la risposta corretta: un
       codice a 3 caratteri e' una codifica ICD-10 valida, non un ripiego
       inventato. Se invece i termini si distribuiscono su categorie diverse --
       "insufficienza mitralica" sta sia fra le forme reumatiche sia fra quelle
       non reumatiche -- la menzione resta AMBIGUO: distinguerle richiede il
       contesto clinico, che e' il compito dello step 5.

       La regola non contiene alcuna conoscenza medica scritta a mano: deriva
       per intero dalla gerarchia del volume.

    3. **Ripiego sul gazetteer.** Il termine piu' lungo dell'indice contenuto
       nella menzione, con lo stesso meccanismo della pipeline A, cosi' che
       "ipertensione arteriosa in trattamento" trovi "ipertensione arteriosa".

    In nessun caso una menzione compatibile con piu' categorie riceve un codice
    scelto a caso: una copertura piu' alta pagata con una codifica meno
    affidabile e' il compromesso sbagliato in un sistema che deve poi ragionare
    sulla sicurezza di una terapia.
    """

    def __init__(
        self,
        percorso: Path = PERCORSO_TERMINOLOGIA_ICD,
        gazetteer=None,
    ) -> None:
        dati = json.loads(percorso.read_text(encoding="utf-8"))
        self.indice: dict[str, list[str]] = {
            normalizza(termine): codici
            for termine, codici in dati["indice_termini"].items()
        }
        # Indice per primo token: la generalizzazione deve poter trovare tutti i
        # termini che cominciano con una data menzione senza scorrere ogni volta
        # le 13.642 voci.
        self._per_primo_token: dict[str, list[str]] = defaultdict(list)
        for termine in self.indice:
            primo = termine.split(" ", 1)[0]
            self._per_primo_token[primo].append(termine)

        self.gazetteer = gazetteer
        # Il ripiego sul gazetteer attraversa la pipeline spaCy, che non e'
        # garantita sicura da piu' thread contemporaneamente. Le pipeline
        # girano in parallelo per ragioni di tempo, quindi qui l'accesso e'
        # serializzato: e' un ripiego e non il percorso principale, quindi
        # la contesa resta bassa.
        self._lucchetto = threading.Lock()

    # -- passaggi ----------------------------------------------------------

    @staticmethod
    def categoria(codice: str) -> str:
        """La categoria a 3 caratteri di un codice ICD-10 (I48.0 -> I48)."""
        return codice.split(".", 1)[0]

    def _categoria_comune(self, codici) -> str | None:
        """La categoria condivisa da tutti i codici, se ce n'e' una sola."""
        categorie = {self.categoria(codice) for codice in codici}
        return categorie.pop() if len(categorie) == 1 else None

    def _generalizza(self, chiave: str) -> tuple[str | None, tuple[str, ...]]:
        """(categoria, codici delle forme qualificate) per una menzione generica.

        Considera solo i termini che *estendono* la menzione a confine di
        parola: "fibrillazione atriale" raccoglie "fibrillazione atriale
        parossistica" ma non "fibrillazione atriale" stessa (gia' cercata) ne'
        parole che iniziano allo stesso modo per caso.
        """
        prefisso = chiave + " "
        forme: list[str] = []
        codici: list[str] = []
        for termine in self._per_primo_token.get(chiave.split(" ", 1)[0], ()):
            if termine.startswith(prefisso):
                forme.append(termine)
                codici.extend(self.indice[termine])
        if not codici:
            return None, ()
        # Serve piu' di una forma qualificata. Con una sola non si distingue un
        # concetto padre da un fratello piu' specifico, e l'errore che ne segue
        # e' del tipo peggiore: plausibile. Il caso reale che ha imposto il
        # vincolo e' "insufficienza mitralica", la cui unica forma indicizzata
        # che la estende e' "insufficienza mitralica congenita" (Q23.3,
        # malformazioni congenite): generalizzare avrebbe attribuito a una
        # valvulopatia acquisita un codice di cardiopatia congenita.
        if len(forme) < 2:
            return None, tuple(sorted(set(codici)))
        return self._categoria_comune(codici), tuple(sorted(set(codici)))

    def _per_gazetteer(self, testo: str) -> tuple[str, list[str]] | None:
        """Termine piu' lungo dell'indice contenuto nella menzione, se esiste."""
        if self.gazetteer is None or not testo.strip():
            return None
        migliore = None
        with self._lucchetto:
            menzioni = list(self.gazetteer.trova(self.gazetteer.nlp(testo)))
        for menzione in menzioni:
            if not menzione.codici:
                continue
            if migliore is None or len(menzione.testo) > len(migliore.testo):
                migliore = menzione
        if migliore is None:
            return None
        return migliore.forma_vocabolario, migliore.codici

    # -- risoluzione -------------------------------------------------------

    def _esito(self, codici, concetto: str, metodo: str) -> EsitoICD:
        """Un insieme di codici candidati diventa un esito, senza forzature."""
        candidati = tuple(sorted(set(codici)))
        if len(candidati) == 1:
            return EsitoICD(
                candidati[0], StatoNormalizzazione.RISOLTO, concetto, candidati, metodo
            )
        categoria = self._categoria_comune(candidati)
        if categoria is not None:
            return EsitoICD(
                categoria,
                StatoNormalizzazione.RISOLTO,
                concetto,
                candidati,
                f"{metodo}+categoria",
            )
        return EsitoICD(None, StatoNormalizzazione.AMBIGUO, concetto, candidati, metodo)

    def risolvi(self, testo: str) -> EsitoICD:
        """Collega una menzione di condizione a ICD-10."""
        chiave = normalizza(testo)
        if not chiave:
            return EsitoICD(None, StatoNormalizzazione.NIL, None, (), "non_risolto")

        codici = self.indice.get(chiave)
        if codici:
            return self._esito(codici, chiave, "termine_esatto")

        categoria, qualificate = self._generalizza(chiave)
        if categoria is not None:
            return EsitoICD(
                categoria,
                StatoNormalizzazione.RISOLTO,
                chiave,
                qualificate,
                "generalizzazione_a_categoria",
            )

        esito = self._per_gazetteer(testo)
        if esito is not None:
            forma, codici = esito
            return self._esito(codici, forma, "gazetteer")

        if qualificate:
            # Forme qualificate esistono, ma sparse su categorie diverse (o una
            # sola, troppo poco per generalizzare). Sceglierne una richiede il
            # contesto clinico, che e' il compito dello step 5: i candidati
            # restano visibili e la decisione no.
            return EsitoICD(
                None, StatoNormalizzazione.AMBIGUO, chiave, qualificate, "generalizzazione_ambigua"
            )

        return EsitoICD(None, StatoNormalizzazione.NIL, None, (), "non_risolto")
