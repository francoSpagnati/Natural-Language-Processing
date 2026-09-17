"""Traduzione di una menzione nel codice della knowledge base, condivisa dalle tre pipeline.

Una sola codifica per A, B e C, cosi' il confronto misura la sola estrazione.
Nessun codice nasce qui: ATC dalla mappatura AIFA dello step 2, ICD-10
dall'indice del volume ufficiale; cio' che non e' coperto resta NIL.
"""

from __future__ import annotations

import json
import re
import threading
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from explore_dataset import radice_nome_commerciale
from context_it import soggetto_familiare
from schema import Soggetto, StatoNormalizzazione

RADICE = Path(__file__).resolve().parent.parent
PERCORSO_MAPPATURA_ATC = RADICE / "data" / "interim" / "mappatura_atc.json"
PERCORSO_TERMINOLOGIA_ICD = RADICE / "data" / "interim" / "terminologia_icd10.json"

_SPAZI = re.compile(r"\s+")
_PUNTEGGIATURA_ESTERNA = re.compile(r"^[\s\-–—•.,;:()\"']+|[\s\-–—•.,;:()\"']+$")


def normalizza(testo: str) -> str:
    """Forma comparabile: minuscola e spazi ripuliti, niente accenti tolti ne' stemming (conservativa di proposito)."""
    return _SPAZI.sub(" ", _PUNTEGGIATURA_ESTERNA.sub("", testo)).lower()


class RisolutoreATC:
    """Forma testuale di farmaco -> codice ATC, dalla mappatura dello step 2."""

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
        """Come `risolvi`, ma su una menzione composta ("Furosemide (Lasix cpr. 25 mg)", "Medrol: 4 mg ...").

        Prova la menzione intera, il nome prima dei due punti, il principio
        prima della parentesi, il commerciale dentro la parentesi; dice quale
        forma ha risolto. Se due vie danno codici diversi: AMBIGUO.
        """
        codice, stato, fonte = self.risolvi(menzione)
        if stato is not StatoNormalizzazione.NIL:
            return codice, stato, fonte, menzione.strip()

        varianti: list[str] = []
        prima_dei_due_punti = menzione.split(":", 1)[0].strip()
        if prima_dei_due_punti and prima_dei_due_punti != menzione.strip():
            varianti.append(prima_dei_due_punti)

        principio, _, resto = menzione.partition("(")
        if resto:
            principio = principio.strip()
            if principio and principio not in varianti:
                varianti.append(principio)
            commerciale = radice_nome_commerciale(resto.rstrip(") "))
            if commerciale:
                varianti.append(commerciale)

        risolti = []
        for forma in varianti:
            esito = self.risolvi(forma)
            if esito[1] is not StatoNormalizzazione.NIL:
                risolti.append((esito, forma))
        if not risolti:
            return None, StatoNormalizzazione.NIL, None, menzione.strip()

        codici = {esito[0] for esito, _ in risolti if esito[0]}
        if len(codici) > 1:
            return None, StatoNormalizzazione.AMBIGUO, None, menzione.strip()

        (codice, stato, fonte), forma = risolti[0]
        return codice, stato, fonte, forma


@dataclass(frozen=True)
class EsitoICD:
    """Esito di un collegamento a ICD-10, con il metodo che l'ha prodotto."""

    codice: str | None
    stato: StatoNormalizzazione
    concetto: str | None
    candidati: tuple[str, ...]
    metodo: str


class RisolutoreICD:
    """Menzione di condizione -> codice ICD-10, in tre passaggi sull'indice ufficiale.

    1. termine esatto; 2. generalizzazione alla categoria a 3 caratteri, se
    tutte le forme qualificate che estendono la menzione stanno in una sola
    categoria ("fibrillazione atriale" -> I48), altrimenti AMBIGUO; 3. il
    termine piu' lungo contenuto nella menzione (gazetteer). Mai un codice a
    caso fra piu' categorie. Vedi docs/02_terminologia_icd10.md.
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
        # Indice per primo token, per la generalizzazione.
        self._per_primo_token: dict[str, list[str]] = defaultdict(list)
        for termine in self.indice:
            primo = termine.split(" ", 1)[0]
            self._per_primo_token[primo].append(termine)

        self.gazetteer = gazetteer
        # spaCy non e' sicura fra thread: il ripiego sul gazetteer e' serializzato.
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
        """(categoria, codici delle forme qualificate) che estendono la menzione a confine di parola."""
        prefisso = chiave + " "
        forme: list[str] = []
        codici: list[str] = []
        for termine in self._per_primo_token.get(chiave.split(" ", 1)[0], ()):
            if termine.startswith(prefisso):
                forme.append(termine)
                codici.extend(self.indice[termine])
        if not codici:
            return None, ()
        # Serve piu' di una forma qualificata: con una sola, "insufficienza
        # mitralica" finirebbe in Q23.3 (congenita).
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
            # Forme qualificate sparse su piu' categorie: candidati visibili, nessuna scelta.
            return EsitoICD(
                None, StatoNormalizzazione.AMBIGUO, chiave, qualificate, "generalizzazione_ambigua"
            )

        return EsitoICD(None, StatoNormalizzazione.NIL, None, (), "non_risolto")


def soggetto_della_menzione(
    testo_campo: str, inizio: int | None, fine: int | None
) -> tuple[Soggetto, str | None]:
    """Paziente o familiare? Regola unica per le tre pipeline; restituisce anche la nota per la provenienza."""
    ambito = soggetto_familiare(testo_campo, inizio, fine)
    if ambito is None:
        return Soggetto.PAZIENTE, None
    return Soggetto.FAMILIARE, f"experiencer:{ambito.espressione.lower()}"
