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


class RisolutoreICD:
    """Traduce una menzione di condizione in un codice ICD-10.

    Due passaggi, entrambi ancorati all'indice estratto dal volume ufficiale:

    1. corrispondenza esatta della menzione normalizzata con un termine
       dell'indice;
    2. se fallisce e si dispone di un gazetteer, ricerca del termine piu' lungo
       contenuto nella menzione -- lo stesso meccanismo della pipeline A, cosi'
       che una menzione come "ipertensione arteriosa in trattamento" trovi
       "ipertensione arteriosa".

    Una menzione compatibile con piu' codici non viene decisa: resta `AMBIGUO`
    con i candidati in vista. Sceglierne uno a caso darebbe una copertura piu'
    alta e una codifica meno affidabile, che e' il compromesso sbagliato in un
    sistema che deve poi ragionare sulla sicurezza di una terapia.
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
        self.gazetteer = gazetteer
        # Il ripiego sul gazetteer attraversa la pipeline spaCy, che non e'
        # garantita sicura da piu' thread contemporaneamente. Le pipeline
        # girano in parallelo per ragioni di tempo, quindi qui l'accesso e'
        # serializzato: e' un ripiego e non il percorso principale, quindi
        # la contesa resta bassa.
        self._lucchetto = threading.Lock()

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

    def risolvi(
        self, testo: str
    ) -> tuple[str | None, StatoNormalizzazione, str | None, list[str]]:
        """(codice, stato, concetto, candidati) per una menzione di condizione."""
        chiave = normalizza(testo)
        codici = self.indice.get(chiave)
        concetto = chiave if codici else None

        if codici is None:
            esito = self._per_gazetteer(testo)
            if esito is not None:
                concetto, codici = esito

        if not codici:
            return None, StatoNormalizzazione.NIL, None, []
        if len(codici) == 1:
            return codici[0], StatoNormalizzazione.RISOLTO, concetto, codici
        return None, StatoNormalizzazione.AMBIGUO, concetto, codici
