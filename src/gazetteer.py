"""Step 3 - Gazetteer sui vocabolari chiusi.

Riconosce nel testo le forme dei vocabolari (farmaci dallo step 1-2,
condizioni dall'indice ICD-10) con `PhraseMatcher` di spaCy su token
minuscoli: nessuna inferenza, tutto tracciabile. Perche' spaCy e non regex,
e come e' filtrato l'ICD: docs/03_pipeline_estrazione_A.md.
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


# Parole che nel nome di un farmaco sono unita' di misura, forme farmaceutiche o
# indicazioni orarie: da sole non identificano nulla.
PATTERN_UNITA_O_FORMA = re.compile(
    r"^(mg|mcg|g|gr|ml|ui|u|cp|cpr|cps|cpz|gtt|fl|bust|puff|ore|die|al|alle|"
    r"cpr\.?|cp\.?|riv|gastr|rp|sc|ev|os)$",
    re.IGNORECASE,
)


def forma_farmaco_ammissibile(forma: str) -> bool:
    """Scarta i residui di parsing ("5 mg", "ore 17", "cpr."): tolti cifre, unita' e forme, devono restare tre lettere."""
    forma = forma.strip()
    if len(forma) < 4 or forma == "-":
        return False
    for pezzo in re.split(r"[\s/,+.\-]+", forma):
        pezzo = pezzo.strip()
        if len(pezzo) >= 3 and pezzo.isalpha() and not PATTERN_UNITA_O_FORMA.match(pezzo):
            return True
    return False


def carica_forme_farmaci() -> dict[str, list[str]]:
    """Forma testuale -> codici ATC; le voci NIL restano, senza codice (riconosciute ma non normalizzate)."""
    dati = json.loads(PERCORSO_MAPPATURA_ATC.read_text(encoding="utf-8"))
    forme: dict[str, list[str]] = {}
    for voce in dati["voci"]:
        forma = voce["forma_grezza"].strip()
        if not forma_farmaco_ammissibile(forma):
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


# Qualificatori residuali dell'ICD ("Altro ...", "... non specificata"): non
# sono contenuto clinico. "cronica" o "acuta" invece lo sono e restano.
PATTERN_QUALIFICATORE_INIZIALE = re.compile(
    r"^(altro|altra|altri|altre|altre forme di|altri disturbi del|"
    r"altre malattie del|altri)\s+", re.IGNORECASE
)
PATTERN_QUALIFICATORE_FINALE = re.compile(
    r"[, ]+(non specificat\w+|s\.a\.i\.?|nas|di altro tipo|"
    r"non altrimenti specificat\w+)\s*$", re.IGNORECASE
)


def varianti_derivate(termine: str) -> list[str]:
    """Forme senza i qualificatori residuali dell'ICD: "altro ipotiroidismo" -> "ipotiroidismo"."""
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
    """Termine ICD -> codici; una forma di una sola parola resta solo se e' il titolo di una categoria."""
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
        # Solo tokenizzazione e frasi: il resto della pipeline spaCy e' disattivato.
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
        # Solo il tokenizzatore: su decine di migliaia di forme conta.
        pattern = list(self.nlp.tokenizer.pipe(forme.keys()))
        self.matcher.add(etichetta, pattern)

    def codici_per(self, forma: str, etichetta: str) -> list[str]:
        """I codici associati a una forma del vocabolario."""
        sorgente = (
            self.forme_farmaci if etichetta == ETICHETTA_FARMACO else self.forme_condizioni
        )
        return sorgente.get(forma.lower(), [])

    def trova(self, documento) -> list[Menzione]:
        """Le menzioni in un documento spaCy; fra sovrapposte vince la piu' lunga."""
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
