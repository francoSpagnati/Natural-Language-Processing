"""
Step 3 - Logica di negazione, incertezza e storicita' per l'italiano clinico.

Implementa un adattamento italiano dell'algoritmo **ConText** (Harkema et al.),
quello usato da medspaCy. medspaCy e scispaCy non sono utilizzabili qui perche'
i loro marcatori e le loro regole sono scritti per l'inglese: "denies", "no
evidence of", "rule out" non compaiono mai in un referto italiano.

COME FUNZIONA ConText, IN BREVE
    Ogni marcatore (un'espressione come "nega" o "sospetta") apre un *ambito*
    che si propaga in una direzione fino a un punto di terminazione. Le entita'
    che cadono dentro l'ambito ereditano l'attributo del marcatore. Non c'e'
    analisi sintattica: e' una regola di prossimita', ed e' precisamente questo
    che la rende ispezionabile e adatta a fare da baseline.

I MARCATORI SONO RICAVATI DAL CORPUS, NON TRADOTTI DALL'INGLESE
    Le liste sotto vengono da un conteggio sulle 1000 anamnesi (docs/03):
    "non" 2665 occorrenze, "nega" 522, "assenza di" 370, "senza" 319,
    "negativo per" 102. Tradurre i marcatori inglesi di medspaCy avrebbe
    prodotto espressioni che nel corpus non compaiono.

TRE ATTRIBUTI, NON UNO
    - **negazione**: l'affermazione e' esclusa ("nega diabete");
    - **incertezza**: e' ipotizzata ("sospetta cardiopatia ischemica");
    - **storicita'**: appartiene al passato ("pregressa fibrillazione atriale").

    La storicita' non cambia la polarita' ma e' clinicamente decisiva: una
    fibrillazione atriale pregressa e una in atto portano a terapie diverse.
    Nello schema resta `affermato`, e la storicita' viaggia nella regola
    registrata in `Provenienza`, cosi' nessuna informazione si perde.
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
    # Ampiezza massima dell'ambito in token. Serve a evitare che un marcatore
    # a inizio referto qualifichi entita' a venti parole di distanza, che nella
    # prosa clinica italiana quasi sempre appartengono a un'altra affermazione.
    ampiezza: int = 8


# --- Marcatori di negazione -------------------------------------------------
# Ordinati per frequenza osservata nel corpus. Le espressioni composte devono
# precedere quelle semplici ("negativo per" prima di "non"), altrimenti la
# semplice consuma la composta e l'ambito risulta sbagliato.
MARCATORI_NEGAZIONE = [
    Marcatore("negativo per", Attributo.NEGAZIONE, Direzione.AVANTI, 10),
    Marcatore("in assenza di", Attributo.NEGAZIONE, Direzione.AVANTI, 10),
    Marcatore("assenza di", Attributo.NEGAZIONE, Direzione.AVANTI, 10),
    Marcatore("non evidenza di", Attributo.NEGAZIONE, Direzione.AVANTI, 10),
    Marcatore("si esclude", Attributo.NEGAZIONE, Direzione.AVANTI, 8),
    Marcatore("esclusa", Attributo.NEGAZIONE, Direzione.AVANTI, 8),
    Marcatore("escluso", Attributo.NEGAZIONE, Direzione.AVANTI, 8),
    Marcatore("esclude", Attributo.NEGAZIONE, Direzione.AVANTI, 8),
    # "nega" ha ampiezza generosa perche' introduce quasi sempre un elenco:
    # "Nega diabete mellito, ipertensione e dislipidemia."
    Marcatore("nega", Attributo.NEGAZIONE, Direzione.AVANTI, 14),
    Marcatore("negati", Attributo.NEGAZIONE, Direzione.AVANTI, 14),
    Marcatore("senza", Attributo.NEGAZIONE, Direzione.AVANTI, 6),
    Marcatore("mai", Attributo.NEGAZIONE, Direzione.AVANTI, 6),
    # "non" e' il marcatore piu' frequente ma anche il piu' rischioso: compare
    # in "non in terapia con X" (negazione vera) e in "non ha eseguito il
    # dosaggio" (dove non nega alcuna entita'). L'ambito e' quindi stretto.
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

# --- Terminatori ------------------------------------------------------------
# Espressioni che chiudono un ambito prima del limite di ampiezza. Sono il
# meccanismo che impedisce a una negazione di propagarsi su un'affermazione
# successiva: in "Nega diabete ma riferisce ipertensione", l'ipertensione NON
# e' negata.
#
# La virgola e la congiunzione "e" NON terminano l'ambito, di proposito: in
# italiano clinico la negazione si estende regolarmente su un elenco
# ("Nega diabete, ipertensione e dislipidemia").
TERMINATORI = {
    "ma", "tuttavia", "pero", "però", "mentre", "salvo", "eccetto",
    "riferisce", "presenta", "in terapia", "in trattamento", "portatore",
    "si segnala", "evidenza", "riscontro", "quadro di",
}

# Un ambito non attraversa mai il confine di frase: e' il limite piu' forte, e
# spaCy ce lo da' gia' con il sentencizzatore.


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
    """Individua i marcatori nel documento e calcola l'ambito di ciascuno.

    L'ambito si estende dal marcatore fino al primo fra: un terminatore, la
    fine della frase, o il limite di ampiezza del marcatore.
    """
    ambiti: list[AmbitoAttivo] = []
    # Le espressioni piu' lunghe vanno provate per prime: "negativo per" deve
    # vincere su "non", altrimenti l'ambito sarebbe quello sbagliato.
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
    """Estende l'ambito da `partenza` per al piu' `ampiezza` token.

    Si ferma sul primo terminatore o sul confine di frase. Restituisce il
    limite esclusivo (in avanti) o inclusivo-a-sinistra (all'indietro).
    """
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
    """Gli attributi che si applicano a un'entita', con il marcatore che li ha causati.

    Restituisce un dizionario e non un singolo valore perche' gli attributi non
    si escludono: "nega pregressa fibrillazione atriale" e' insieme negata e
    storica, e servono entrambe le informazioni.
    """
    risultato: dict[Attributo, Marcatore] = {}
    for ambito in ambiti:
        if ambito.copre(inizio_token, fine_token):
            # A parita' di attributo tiene il marcatore piu' vicino, che e'
            # quello che governa davvero l'entita'.
            precedente = risultato.get(ambito.marcatore.attributo)
            if precedente is None:
                risultato[ambito.marcatore.attributo] = ambito.marcatore
    return risultato


# ---------------------------------------------------------------------------
# L'asse dell'*experiencer*: di chi si sta parlando
# ---------------------------------------------------------------------------
# ConText ha quattro assi, non tre. Oltre a negazione, incertezza e storicita'
# c'e' l'**experiencer**: se l'affermazione riguardi il paziente o qualcun
# altro. Nella prima versione dello schema mancava, e il confronto fra pipeline
# A e B su 198 record ne ha mostrato il costo: 21 dei 55 disaccordi sullo stato
# clinico erano frasi di familiarita', dove A leggeva `affermato` e B `negato`
# e **nessuna delle due aveva ragione**, perche' la frase non dice che il
# paziente ha la malattia ne' che non ce l'ha: dice che ce l'ha un parente.
#
# I marcatori vengono dal conteggio sul corpus grezzo (1000 ricoveri):
# "familiarita" 508 occorrenze, di cui "familiarita per" 431, "familiarita
# positiva" 27, "familiarita negativa" 18; "anamnesi familiare" 28; "storia
# familiare" 2. Espressioni come "padre" o "madre" NON sono marcatori: nel
# corpus compaiono quasi sempre come precisazione fra parentesi *dentro* un
# ambito gia' aperto da "familiarita", e usarle da sole aprirebbe ambiti su
# frasi che parlano del paziente.
#
# L'asse e' indipendente dagli altri tre, e il corpus lo dimostra:
# "familiarita negativa per cad" e' insieme familiare e negata.

# `familiarita;` con il punto e virgola compare davvero nel corpus (un refuso),
# quindi fra il sostantivo e "per" si tollera qualche carattere non alfabetico.
PATTERN_SOGGETTO_FAMILIARE = re.compile(
    r"familiarit[aà]\W{0,3}(?:positiva|negativa)?\W{0,3}per\b"
    r"|familiarit[aà]\b"
    r"|anamnesi\s+familiare\b"
    r"|storia\s+familiare\b",
    re.IGNORECASE,
)

# Un secondo modo di parlare di un parente, che il marcatore esplicito non copre:
# nominarlo direttamente. «Madre deceduta ad 80 aa per fibrillazione atriale» non
# contiene la parola "familiarita", ma la fibrillazione e' della madre.
#
# La regola e' stretta di proposito, perche' costruita sul corpus e non
# sull'intuizione. Sulle 436 occorrenze di un termine di parentela nell'anamnesi:
#
#   54%  stanno gia' dentro un ambito di "familiarita' per ..." -> coperte
#    4%  sono l'INFORMATORE, non il malato («la madre riferisce», «segnalata
#        dalla figlia»): li' la condizione e' del PAZIENTE, e marcarle familiari
#        sarebbe un errore peggiore di quello che questa regola ripara, perche'
#        nasconderebbe al filtro di sicurezza una condizione vera;
#   42%  restano, e in gran parte non parlano di malattia affatto («vive con il
#        fratello», «due fratelli in buona salute», «un figlio»).
#
# Quindi non basta il termine di parentela: serve che sia **immediatamente
# seguito** da una parola che dica che quel parente e' il malato. L'elenco viene
# dalle occorrenze vere, in ordine di frequenza: deceduto 27, affetto 7,
# sottoposto 6, portatore 2, piu' gli aggettivi di malattia della coda lunga.
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

# Un ambito di familiarita' si chiude a fine frase. La virgola non lo chiude,
# per la stessa ragione della negazione: gli elenchi sono la norma
# ("familiarita positiva per diabete mellito (madre), cardiopatia ischemica").
PATTERN_FINE_FRASE = re.compile(r"[.;:\n]|\bma\b|\btuttavia\b|\bnega\b|\briferisce\b")

# I referti incollano piu' affermazioni senza punteggiatura, segnalando l'inizio
# della successiva con la maiuscola: "familiarita per cardiopatia ischemica ed
# ipertensione arteriosa Ex fumatore". Senza questo terminatore l'ambito
# assorbirebbe abitudini e patologie che sono del paziente. La maiuscola deve
# essere seguita da una minuscola, altrimenti si spezzerebbe su ogni acronimo
# (CAD, MCV, IMA, HCM), che nel corpus sono frequentissimi.
PATTERN_NUOVA_AFFERMAZIONE = re.compile(r"(?<=[a-zà-ù]) (?=[A-Z][a-zà-ù])")

# Oltre questa distanza l'ambito non si propaga: nel corpus le frasi di
# familiarita' sono brevi, e un tetto evita che una frase senza punteggiatura
# finale trascini con se' meta' anamnesi.
MASSIMA_AMPIEZZA_SOGGETTO = 160


@dataclass(frozen=True)
class AmbitoSoggetto:
    """Un tratto di testo in cui si sta parlando di un familiare, non del paziente."""

    inizio: int
    fine: int
    espressione: str


def ambiti_familiarita(testo: str) -> list[AmbitoSoggetto]:
    """Trova i tratti di testo governati da un marcatore di familiarita'.

    Lavora su offset di carattere e non su token di spaCy, di proposito: e' la
    sola forma che tutte e tre le pipeline possono usare senza modifiche. La
    pipeline B non costruisce un documento spaCy — ha solo il testo del campo e
    gli offset della citazione del modello — e avere due implementazioni della
    stessa regola le farebbe divergere.
    """
    ambiti: list[AmbitoSoggetto] = []
    # Il marcatore esplicito apre l'ambito DOPO di se': in «familiarita per X»
    # il malato e' X. Il nome del parente invece fa parte dell'affermazione — in
    # «Madre deceduta per fibrillazione atriale» la menzione estratta comprende
    # spesso la parola "Madre" — quindi li' l'ambito parte dall'inizio.
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
    """Accorcia l'ambito dove ricomincia una nuova affermazione senza punteggiatura.

    Il taglio non si applica dentro una parentesi: le precisazioni sui parenti
    ne sono piene ("diabete mellito (padre, affetto da Parkinson, madre ETP)") e
    spezzarle toglierebbe la marcatura a condizioni che sono davvero familiari.
    """
    for candidato in PATTERN_NUOVA_AFFERMAZIONE.finditer(testo, inizio, fine):
        tratto = testo[inizio:candidato.start()]
        if tratto.count("(") > tratto.count(")"):
            continue  # parentesi ancora aperta: non e' una nuova affermazione
        return candidato.start()
    return fine


def soggetto_familiare(
    testo: str, inizio: int | None, fine: int | None
) -> AmbitoSoggetto | None:
    """L'ambito di familiarita' che governa una menzione, se ce n'e' uno.

    Restituisce l'ambito invece di un booleano perche' l'espressione che lo ha
    aperto va registrata nella regola di `Provenienza`: chi rilegge il dato deve
    poter risalire alla parola che ha deciso.
    """
    if inizio is None or fine is None:
        return None  # menzione non ancorata: senza offset la regola non si applica
    for ambito in ambiti_familiarita(testo):
        if ambito.inizio < fine and inizio < ambito.fine:
            return ambito
    return None
