"""
Step 3 - Gazetteer sui vocabolari chiusi.

Riconosce nel testo libero le menzioni di farmaci e condizioni, cercando le
forme dei vocabolari costruiti negli step 1 e 2. Non fa inferenza: se una
stringa non e' nel vocabolario, non viene riconosciuta. E' esattamente il
comportamento voluto per la pipeline A, che deve essere la baseline
completamente tracciabile contro cui misurare le altre due.

PERCHE' `PhraseMatcher` DI spaCy E NON REGEX
    Il brief lascia la scelta. `PhraseMatcher` vince per tre motivi concreti:

    1. **Confronta token, non caratteri.** Una regex su "ictus" troverebbe
       "ictus" dentro "peri-ictus"; il matcher su token no, perche' il confine
       di parola lo stabilisce il tokenizzatore italiano invece di `\\b`.
    2. **Scala.** Le forme da cercare sono ~15 000; un'alternanza di regex di
       quella dimensione diventa lenta e illeggibile, mentre `PhraseMatcher`
       usa internamente una struttura ad automa.
    3. **Serve comunque il documento tokenizzato** per la logica di negazione
       (`context_it.py`), che ragiona su frasi e distanze in token. Usare spaCy
       per il matching evita di mantenere due nozioni diverse di "parola".

    L'attributo di confronto e' `LOWER`: la capitalizzazione nei referti e'
    incoerente ("Ipertensione", "ipertensione", "IPERTENSIONE") e non porta
    informazione clinica.

PERCHE' LE CONDIZIONI VENGONO DALL'ICD E NON DAL DATASET
    Lo step 0 ha stabilito che il dataset non contiene un elenco di patologie.
    Il vocabolario delle condizioni e' quindi la terminologia ICD-10 italiana
    (step 2), filtrata per togliere le voci che come gazetteer farebbero solo
    danno: quelle troppo corte, quelle numeriche delle tabelle di mortalita' e
    le parole generiche che in un referto non denotano una diagnosi.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import spacy
from spacy.matcher import PhraseMatcher

RADICE = Path(__file__).resolve().parent.parent
PERCORSO_MAPPATURA_ATC = RADICE / "data" / "interim" / "mappatura_atc.json"
PERCORSO_TERMINOLOGIA_ICD = RADICE / "data" / "interim" / "terminologia_icd10.json"

MODELLO_SPACY = "it_core_news_sm"

# Etichette usate dal matcher. Restano separate perche' farmaci e condizioni
# hanno destinazioni diverse nello stato paziente e regole di negazione diverse.
ETICHETTA_FARMACO = "FARMACO"
ETICHETTA_CONDIZIONE = "CONDIZIONE"

# Soglie di ammissione al gazetteer delle condizioni, tarate ispezionando i
# termini reali (vedi docs/03).
LUNGHEZZA_MINIMA_TERMINE = 5
PAROLE_MASSIME_TERMINE = 6

# Termini ICD da non ammettere: sono corretti nella classificazione ma come
# gazetteer producono solo falsi positivi.
PATTERN_TERMINE_INAMMISSIBILE = re.compile(
    r"^\d"                       # voci delle tabelle di mortalita': "077 tumore..."
    r"|^(altr|non specificat|specificat|senza|con |sequele|altre forme)"  # qualificatori
    r"|\bs\.a\.i\b"              # "senza altra indicazione": marcatore ICD, non clinico
    r"|\bogni condizione\b",     # rinvii interni alla classificazione
    re.IGNORECASE,
)

# Parole singole troppo generiche per denotare una diagnosi in un referto.
# Sono termini ICD legittimi, ma da soli in prosa italiana significano altro.
TERMINI_GENERICI_ESCLUSI = {
    "dolore", "febbre", "tosse", "nausea", "vomito", "cefalea", "astenia",
    "edema", "edemi", "shock", "coma", "morte", "aborto", "parto", "nascita",
    "gravidanza", "frattura", "ferita", "ustione", "avvelenamento", "contusione",
    "lesione", "lesioni", "tumore", "cisti", "polipo", "ulcera", "ernia",
    "stenosi", "occlusione", "emorragia", "infezione", "ascesso", "anemia",
}


@dataclass
class Menzione:
    """Una menzione riconosciuta nel testo, con la sua posizione esatta."""

    testo: str            # la stringa come appare nel referto
    forma_vocabolario: str  # la forma del vocabolario che ha prodotto il match
    etichetta: str        # FARMACO o CONDIZIONE
    inizio: int           # offset di carattere nel testo originale
    fine: int
    inizio_token: int     # indice di token, serve alla logica di negazione
    fine_token: int
    codici: list[str]     # ATC o ICD associati alla forma


def carica_forme_farmaci() -> dict[str, list[str]]:
    """Forma testuale -> codici ATC, dalle voci risolte o ambigue.

    Le voci NIL sono incluse **senza codice**: il gazetteer deve riconoscerle
    comunque, altrimenti un farmaco realmente presente nel testo risulterebbe
    assente invece che "riconosciuto ma non normalizzato". Sono due errori
    diversi e vanno tenuti distinti.
    """
    dati = json.loads(PERCORSO_MAPPATURA_ATC.read_text(encoding="utf-8"))
    forme: dict[str, list[str]] = {}
    for voce in dati["voci"]:
        forma = voce["forma_grezza"].strip()
        if len(forma) < 4 or forma == "-":
            continue
        codici = [voce["codice_atc"]] if voce["codice_atc"] else voce["atc_candidati"]
        forme.setdefault(forma.lower(), []).extend(codici)
    return {forma: sorted(set(codici)) for forma, codici in forme.items()}


def termine_ammissibile(termine: str) -> bool:
    """Il termine ICD e' utilizzabile come voce di gazetteer?"""
    if len(termine) < LUNGHEZZA_MINIMA_TERMINE:
        return False
    if len(termine.split()) > PAROLE_MASSIME_TERMINE:
        return False
    if PATTERN_TERMINE_INAMMISSIBILE.search(termine):
        return False
    if termine in TERMINI_GENERICI_ESCLUSI:
        return False
    return True


# Qualificatori con cui l'ICD costruisce le proprie categorie residuali. Non
# sono contenuto clinico ma contabilita' della classificazione: "Altro
# ipotiroidismo" e' il modo in cui l'ICD dice "ipotiroidismo non altrove
# classificato". Nei referti il medico scrive "ipotiroidismo" e basta, quindi
# senza rimuoverli il gazetteer manca la forma che compare davvero.
#
# La rimozione produce forme *derivate* dall'ICD stesso: nessun sinonimo e'
# inventato da noi. Restano fuori i qualificatori che sono contenuto clinico
# ("cronica", "acuta", "maligna"), perche' distinguono condizioni diverse.
PATTERN_QUALIFICATORE_INIZIALE = re.compile(
    r"^(altro|altra|altri|altre|altre forme di|altri disturbi del|"
    r"altre malattie del|altri)\s+", re.IGNORECASE
)
PATTERN_QUALIFICATORE_FINALE = re.compile(
    r"[, ]+(non specificat\w+|s\.a\.i\.?|nas|di altro tipo|"
    r"non altrimenti specificat\w+)\s*$", re.IGNORECASE
)


def varianti_derivate(termine: str) -> list[str]:
    """Forme aggiuntive ottenute togliendo i qualificatori residuali dell'ICD.

    "altro ipotiroidismo" -> "ipotiroidismo"
    "cardiopatia ischemica cronica, non specificata" -> "cardiopatia ischemica cronica"

    Applicata sia in testa sia in coda, e ripetuta finche' il termine si
    accorcia, perche' i due qualificatori possono comparire insieme.
    """
    varianti = []
    corrente = termine
    for _ in range(3):  # limite prudenziale: nessun termine reale ne ha di piu'
        ridotto = PATTERN_QUALIFICATORE_FINALE.sub("", corrente).strip()
        ridotto = PATTERN_QUALIFICATORE_INIZIALE.sub("", ridotto).strip()
        if ridotto == corrente or not ridotto:
            break
        varianti.append(ridotto)
        corrente = ridotto
    return varianti


def carica_forme_condizioni() -> dict[str, list[str]]:
    """Termine ICD -> codici, filtrato per l'uso come gazetteer.

    Le forme di **una sola parola** sono ammesse solo se coincidono con il
    titolo di una categoria ICD. E' il filtro che elimina i tronchi prodotti
    dall'espansione dei parentetici: da "insufficienza (cardiaca) (renale)"
    l'indice ricava anche "insufficienza", che pero' da sola non e' una
    diagnosi — nessun codice ICD si intitola cosi'. "Ipotiroidismo" invece
    sopravvive, perche' e' il titolo di E03 una volta tolto il qualificatore
    residuale "Altro".

    La regola e' ricavata dai dati e non da un elenco di parole scritto a mano:
    e' l'ICD stesso a dire quali termini bastano da soli a nominare una
    categoria.
    """
    dati = json.loads(PERCORSO_TERMINOLOGIA_ICD.read_text(encoding="utf-8"))

    # I titoli delle categorie, con le loro varianti senza qualificatori.
    titoli_ammessi: set[str] = set()
    for voce in dati["voci"]:
        titolo = voce["titolo"].lower().strip()
        titoli_ammessi.add(titolo)
        titoli_ammessi.update(v.lower() for v in varianti_derivate(titolo))

    forme: dict[str, list[str]] = {}

    def considera(forma: str, codici: list[str]) -> None:
        if not termine_ammissibile(forma):
            return
        if len(forma.split()) == 1 and forma not in titoli_ammessi:
            return
        forme.setdefault(forma, []).extend(codici)

    for termine, codici in dati["indice_termini"].items():
        considera(termine, codici)
        # Le forme derivate non sostituiscono l'originale: si aggiungono.
        for variante in varianti_derivate(termine):
            considera(variante, codici)

    return {forma: sorted(set(codici)) for forma, codici in forme.items()}


class GazetteerClinico:
    """Riconosce farmaci e condizioni cercando le forme dei vocabolari chiusi."""

    def __init__(self, nlp=None) -> None:
        # Il modello serve solo per tokenizzare e segmentare in frasi: gli altri
        # componenti (NER generico, parser) non servono e costano tempo, quindi
        # li disattiviamo. Il sentencizzatore a regole basta e non dipende dal
        # parser statistico, che su prosa clinica abbreviata e' inaffidabile.
        if nlp is None:
            nlp = spacy.load(MODELLO_SPACY, exclude=["ner", "parser", "lemmatizer"])
            nlp.add_pipe("sentencizer")
        self.nlp = nlp

        self.forme_farmaci = carica_forme_farmaci()
        self.forme_condizioni = carica_forme_condizioni()

        # `attr="LOWER"` confronta i token in minuscolo: la capitalizzazione nei
        # referti e' incoerente e non porta informazione clinica.
        self.matcher = PhraseMatcher(self.nlp.vocab, attr="LOWER")
        self._aggiungi(ETICHETTA_FARMACO, self.forme_farmaci)
        self._aggiungi(ETICHETTA_CONDIZIONE, self.forme_condizioni)

    def _aggiungi(self, etichetta: str, forme: dict[str, list[str]]) -> None:
        # `nlp.tokenizer.pipe` invece di `nlp.pipe`: per costruire i pattern
        # serve solo la tokenizzazione, e su decine di migliaia di forme la
        # differenza di tempo e' sostanziale.
        pattern = list(self.nlp.tokenizer.pipe(forme.keys()))
        self.matcher.add(etichetta, pattern)

    def codici_per(self, forma: str, etichetta: str) -> list[str]:
        """I codici associati a una forma del vocabolario."""
        sorgente = (
            self.forme_farmaci if etichetta == ETICHETTA_FARMACO else self.forme_condizioni
        )
        return sorgente.get(forma.lower(), [])

    def trova(self, documento) -> list[Menzione]:
        """Trova le menzioni in un documento gia' analizzato da spaCy.

        In caso di sovrapposizione vince la menzione **piu' lunga**: fra
        "diabete" e "diabete mellito tipo 2" quella giusta e' la seconda, e
        tenerle entrambe produrrebbe due condizioni dove ce n'e' una.
        """
        grezze = []
        for identificativo, inizio, fine in self.matcher(documento):
            etichetta = self.nlp.vocab.strings[identificativo]
            porzione = documento[inizio:fine]
            grezze.append((inizio, fine, etichetta, porzione))

        # Ordinamento per lunghezza decrescente, poi posizione: cosi' scorrendo
        # e scartando le sovrapposizioni sopravvive sempre la piu' lunga.
        grezze.sort(key=lambda g: (-(g[1] - g[0]), g[0]))

        occupati: set[int] = set()
        menzioni: list[Menzione] = []
        for inizio, fine, etichetta, porzione in grezze:
            if any(i in occupati for i in range(inizio, fine)):
                continue
            occupati.update(range(inizio, fine))
            forma = porzione.text.lower()
            menzioni.append(
                Menzione(
                    testo=porzione.text,
                    forma_vocabolario=forma,
                    etichetta=etichetta,
                    inizio=porzione.start_char,
                    fine=porzione.end_char,
                    inizio_token=inizio,
                    fine_token=fine,
                    codici=self.codici_per(forma, etichetta),
                )
            )

        menzioni.sort(key=lambda m: m.inizio)
        return menzioni
