"""Step 3 - Negazione, incertezza, storicita' e soggetto per l'italiano clinico.

Adattamento dell'algoritmo ConText (Harkema et al.): ogni marcatore apre un
ambito che si propaga fino a un terminatore, a fine frase o al limite di
ampiezza; le entita' nell'ambito ereditano l'attributo. I marcatori vengono
dal conteggio sul corpus, non dalla traduzione di medspaCy. Conteggi e
decisioni: docs/03_pipeline_estrazione_A.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Attributo(str, Enum):
    """L'attributo che un marcatore assegna alle entita' nel suo ambito."""

    NEGAZIONE = "negazione"
    INCERTEZZA = "incertezza"
    STORICITA = "storicita"


class Direzione(str, Enum):
    """Da che parte si propaga l'ambito di un marcatore."""

    AVANTI = "avanti"      # "nega DIABETE"
    INDIETRO = "indietro"  # "DIABETE assente"


@dataclass(frozen=True)
class Marcatore:
    """Un'espressione che apre un ambito, con la regola che la governa."""

    espressione: str
    attributo: Attributo
    direzione: Direzione
    # Ampiezza massima dell'ambito in token.
    ampiezza: int = 8


# --- Marcatori di negazione ---
# Per frequenza nel corpus; le espressioni composte precedono le semplici.
MARCATORI_NEGAZIONE = [
    Marcatore("negativo per", Attributo.NEGAZIONE, Direzione.AVANTI, 10),
    Marcatore("in assenza di", Attributo.NEGAZIONE, Direzione.AVANTI, 10),
    Marcatore("assenza di", Attributo.NEGAZIONE, Direzione.AVANTI, 10),
    Marcatore("non evidenza di", Attributo.NEGAZIONE, Direzione.AVANTI, 10),
    Marcatore("si esclude", Attributo.NEGAZIONE, Direzione.AVANTI, 8),
    Marcatore("esclusa", Attributo.NEGAZIONE, Direzione.AVANTI, 8),
    Marcatore("escluso", Attributo.NEGAZIONE, Direzione.AVANTI, 8),
    Marcatore("esclude", Attributo.NEGAZIONE, Direzione.AVANTI, 8),
    # "nega" introduce quasi sempre un elenco: ampiezza generosa.
    Marcatore("nega", Attributo.NEGAZIONE, Direzione.AVANTI, 14),
    Marcatore("negati", Attributo.NEGAZIONE, Direzione.AVANTI, 14),
    Marcatore("senza", Attributo.NEGAZIONE, Direzione.AVANTI, 6),
    Marcatore("mai", Attributo.NEGAZIONE, Direzione.AVANTI, 6),
    # "non riferit*" come espressione composta, prima di "non": `riferisce` e'
    # un terminatore e chiuderebbe subito l'ambito del solo "non" (docs/09b).
    Marcatore("non riferisce", Attributo.NEGAZIONE, Direzione.AVANTI, 8),
    Marcatore("non riferiti", Attributo.NEGAZIONE, Direzione.AVANTI, 8),
    Marcatore("non riferita", Attributo.NEGAZIONE, Direzione.AVANTI, 8),
    Marcatore("non riferito", Attributo.NEGAZIONE, Direzione.AVANTI, 8),
    # "non": il piu' frequente e il piu' rischioso, quindi ambito stretto.
    Marcatore("non", Attributo.NEGAZIONE, Direzione.AVANTI, 4),
    Marcatore("assente", Attributo.NEGAZIONE, Direzione.INDIETRO, 4),
    Marcatore("assenti", Attributo.NEGAZIONE, Direzione.INDIETRO, 4),
]

# --- Marcatori di incertezza ------------------------------------------------
MARCATORI_INCERTEZZA = [
    Marcatore("non escludibile", Attributo.INCERTEZZA, Direzione.AVANTI, 8),
    Marcatore("verosimilmente", Attributo.INCERTEZZA, Direzione.AVANTI, 6),
    Marcatore("verosimile", Attributo.INCERTEZZA, Direzione.AVANTI, 6),
    Marcatore("sospetta", Attributo.INCERTEZZA, Direzione.AVANTI, 6),
    Marcatore("sospetto", Attributo.INCERTEZZA, Direzione.AVANTI, 6),
    Marcatore("sospette", Attributo.INCERTEZZA, Direzione.AVANTI, 6),
    Marcatore("sospetti", Attributo.INCERTEZZA, Direzione.AVANTI, 6),
    Marcatore("possibile", Attributo.INCERTEZZA, Direzione.AVANTI, 6),
    Marcatore("probabile", Attributo.INCERTEZZA, Direzione.AVANTI, 6),
    Marcatore("dubbia", Attributo.INCERTEZZA, Direzione.AVANTI, 6),
    Marcatore("dubbio", Attributo.INCERTEZZA, Direzione.AVANTI, 6),
    Marcatore("da escludere", Attributo.INCERTEZZA, Direzione.AVANTI, 6),
]

# --- Marcatori di storicita' ------------------------------------------------
MARCATORI_STORICITA = [
    Marcatore("anamnesi remota", Attributo.STORICITA, Direzione.AVANTI, 30),
    Marcatore("anamnesi patologica remota", Attributo.STORICITA, Direzione.AVANTI, 30),
    Marcatore("interventi pregressi", Attributo.STORICITA, Direzione.AVANTI, 20),
    Marcatore("in passato", Attributo.STORICITA, Direzione.AVANTI, 8),
    Marcatore("storia di", Attributo.STORICITA, Direzione.AVANTI, 8),
    Marcatore("pregressa", Attributo.STORICITA, Direzione.AVANTI, 6),
    Marcatore("pregresso", Attributo.STORICITA, Direzione.AVANTI, 6),
    Marcatore("pregressi", Attributo.STORICITA, Direzione.AVANTI, 6),
    Marcatore("pregresse", Attributo.STORICITA, Direzione.AVANTI, 6),
    Marcatore("precedenti", Attributo.STORICITA, Direzione.AVANTI, 6),
]

MARCATORI = MARCATORI_NEGAZIONE + MARCATORI_INCERTEZZA + MARCATORI_STORICITA

# --- Terminatori ---
# Chiudono l'ambito prima dell'ampiezza ("Nega diabete ma riferisce
# ipertensione"). Virgola ed "e" non chiudono: la negazione copre gli elenchi.
TERMINATORI = {
    "ma", "tuttavia", "pero", "però", "mentre", "salvo", "eccetto",
    "riferisce", "presenta", "in terapia", "in trattamento", "portatore",
    "si segnala", "evidenza", "riscontro", "quadro di",
}

# Un ambito non attraversa mai il confine di frase.


@dataclass
class AmbitoAttivo:
    """Un ambito aperto da un marcatore su un intervallo di token."""

    marcatore: Marcatore
    inizio_token: int   # primo token coperto (incluso)
    fine_token: int     # ultimo token coperto (escluso)

    def copre(self, inizio: int, fine: int) -> bool:
        """L'entita' fra `inizio` e `fine` cade dentro l'ambito?"""
        return inizio >= self.inizio_token and fine <= self.fine_token


def _testo_token(documento, indice: int) -> str:
    return documento[indice].text.lower()


def _e_terminatore(documento, indice: int) -> bool:
    """Il token, da solo o con il successivo, chiude un ambito?"""
    parola = _testo_token(documento, indice)
    if parola in TERMINATORI:
        return True
    if indice + 1 < len(documento):
        coppia = f"{parola} {_testo_token(documento, indice + 1)}"
        if coppia in TERMINATORI:
            return True
    return False


def trova_ambiti(documento) -> list[AmbitoAttivo]:
    """I marcatori del documento con il loro ambito (fino a terminatore, fine frase o ampiezza)."""
    ambiti: list[AmbitoAttivo] = []
    # Le espressioni piu' lunghe per prime: "negativo per" vince su "non".
    marcatori_ordinati = sorted(MARCATORI, key=lambda m: -len(m.espressione.split()))

    limiti_frase = {frase.end for frase in documento.sents}

    for indice in range(len(documento)):
        for marcatore in marcatori_ordinati:
            parole = marcatore.espressione.split()
            if indice + len(parole) > len(documento):
                continue
            if [
                _testo_token(documento, indice + scarto) for scarto in range(len(parole))
            ] != parole:
                continue

            if marcatore.direzione is Direzione.AVANTI:
                inizio = indice + len(parole)
                fine = _estendi(documento, inizio, marcatore.ampiezza, limiti_frase, +1)
            else:
                fine = indice
                inizio = _estendi(documento, indice - 1, marcatore.ampiezza, limiti_frase, -1)

            if fine > inizio:
                ambiti.append(AmbitoAttivo(marcatore, inizio, fine))
            break  # un token apre un solo ambito: vince il marcatore piu' lungo

    return ambiti


def _estendi(documento, partenza: int, ampiezza: int, limiti_frase: set[int], passo: int) -> int:
    """Estende l'ambito da `partenza` per al piu' `ampiezza` token, fermandosi a terminatore o frase."""
    posizione = partenza
    for _ in range(ampiezza):
        if posizione < 0 or posizione >= len(documento):
            break
        if passo > 0 and posizione in limiti_frase:
            break
        if _e_terminatore(documento, posizione):
            break
        if documento[posizione].is_sent_start and posizione != partenza and passo > 0:
            break
        posizione += passo
    return posizione if passo > 0 else posizione + 1


def attributi_per_entita(
    ambiti: list[AmbitoAttivo], inizio_token: int, fine_token: int
) -> dict[Attributo, Marcatore]:
    """Gli attributi di un'entita' con il marcatore che li causa; non si escludono a vicenda."""
    risultato: dict[Attributo, Marcatore] = {}
    for ambito in ambiti:
        if ambito.copre(inizio_token, fine_token):
            # A parita' di attributo vince il marcatore piu' vicino.
            precedente = risultato.get(ambito.marcatore.attributo)
            if precedente is None:
                risultato[ambito.marcatore.attributo] = ambito.marcatore
    return risultato


# --- L'asse dell'experiencer: di chi si sta parlando ---
# Il quarto asse di ConText, aggiunto dopo il confronto A/B (docs/06).
# Marcatori dal conteggio sul corpus; "padre" e "madre" da soli non lo sono.

# Fra "familiarita" e "per" si tollera qualche carattere non alfabetico (refusi nel corpus).
PATTERN_SOGGETTO_FAMILIARE = re.compile(
    r"familiarit[aà]\W{0,3}(?:positiva|negativa)?\W{0,3}per\b"
    r"|familiarit[aà]\b"
    r"|anamnesi\s+familiare\b"
    r"|storia\s+familiare\b",
    re.IGNORECASE,
)

# Il parente nominato direttamente («Madre deceduta per fibrillazione atriale»):
# serve il termine di parentela seguito subito da una parola di malattia,
# perche' «la madre riferisce» parla del paziente (conteggi in docs/03).
PARENTE = (
    r"madre|padre|mamma|fratell[oi]|sorell[ae]|nonn[aoi]|zi[aoi]"
    r"|cugin[ao]|genitori|consanguine[oi]"
)
QUALIFICA_PARENTE = r"(?:\s+(?:pater\w+|mater\w+|vivent[ei]|gemell[ao]))?"
STATO_DEL_PARENTE = (
    r"decedut[oaie]|affett[oaie]|sottopost[oaie]|portator[ei]"
    r"|fibrillant[ei]|ipertes[oaie]|cardiopatic[oaie]|diabetic[oaie]"
    r"|dislipidemic[oaie]|nefropatic[oaie]|obes[oaie]"
)
PATTERN_SOGGETTO_PARENTE = re.compile(
    rf"\b(?:{PARENTE})\b{QUALIFICA_PARENTE}"
    rf"(?:\s+e\s+(?:{PARENTE})\b{QUALIFICA_PARENTE})?"
    rf"[,]?\s+(?:{STATO_DEL_PARENTE})\b",
    re.IGNORECASE,
)

# L'ambito di familiarita' si chiude a fine frase, non alla virgola (elenchi).
PATTERN_FINE_FRASE = re.compile(r"[.;:\n]|\bma\b|\btuttavia\b|\bnega\b|\briferisce\b")

# Nuova affermazione senza punteggiatura: maiuscola seguita da minuscola
# ("... ipertensione arteriosa Ex fumatore"); non spezza sugli acronimi.
PATTERN_NUOVA_AFFERMAZIONE = re.compile(r"(?<=[a-zà-ù]) (?=[A-Z][a-zà-ù])")

# Tetto di distanza: le frasi di familiarita' sono brevi.
MASSIMA_AMPIEZZA_SOGGETTO = 160


@dataclass(frozen=True)
class AmbitoSoggetto:
    """Un tratto di testo in cui si sta parlando di un familiare, non del paziente."""

    inizio: int
    fine: int
    espressione: str


def ambiti_familiarita(testo: str) -> list[AmbitoSoggetto]:
    """I tratti di testo governati da un marcatore di familiarita', su offset di carattere (usabile da tutte le pipeline)."""
    ambiti: list[AmbitoSoggetto] = []
    # Il marcatore esplicito apre l'ambito dopo di se'; il nome del parente
    # fa parte dell'affermazione, quindi l'ambito parte dall'inizio.
    for pattern, parte_da_inizio in (
        (PATTERN_SOGGETTO_FAMILIARE, False),
        (PATTERN_SOGGETTO_PARENTE, True),
    ):
        for trovato in pattern.finditer(testo):
            inizio = trovato.start() if parte_da_inizio else trovato.end()
            ricerca = trovato.end()
            limite = min(len(testo), ricerca + MASSIMA_AMPIEZZA_SOGGETTO)
            chiusura = PATTERN_FINE_FRASE.search(testo, ricerca, limite)
            fine = chiusura.start() if chiusura else limite
            fine = _taglia_su_nuova_affermazione(testo, ricerca, fine)
            ambiti.append(AmbitoSoggetto(inizio, fine, trovato.group(0).strip()))
    return sorted(ambiti, key=lambda a: a.inizio)


def _taglia_su_nuova_affermazione(testo: str, inizio: int, fine: int) -> int:
    """Accorcia l'ambito dove ricomincia un'affermazione senza punteggiatura (non dentro parentesi)."""
    for candidato in PATTERN_NUOVA_AFFERMAZIONE.finditer(testo, inizio, fine):
        tratto = testo[inizio:candidato.start()]
        if tratto.count("(") > tratto.count(")"):
            continue  # parentesi ancora aperta: non e' una nuova affermazione
        return candidato.start()
    return fine


def soggetto_familiare(
    testo: str, inizio: int | None, fine: int | None
) -> AmbitoSoggetto | None:
    """L'ambito di familiarita' che governa una menzione (l'espressione va in `Provenienza`)."""
    if inizio is None or fine is None:
        return None  # menzione non ancorata: senza offset la regola non si applica
    sovrapposti = [a for a in ambiti_familiarita(testo)
                   if a.inizio < fine and inizio < a.fine]
    if not sovrapposti:
        return None
    # Vince l'ambito piu' vicino: la regola in `Provenienza` deve nominare il parente giusto.
    return max(sovrapposti, key=lambda a: a.inizio)
