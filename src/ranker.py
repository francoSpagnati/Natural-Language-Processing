"""Step 9 - I ranker: che cosa proporre, e in che ordine.

Il filtro (step 8) dice che cosa non si puo' dare; il ranker ordina cio' che
resta. La verita' e' la terapia di dimissione, gia' nei dati (841 ricoveri).
L'unita' e' la classe ATC a 5 caratteri (`LIVELLO_CLASSE`), il livello a cui
le linee guida nominano i farmaci. Motivazioni, compiti e tetto di dominio:
docs/09_ranker.md.
"""

from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from conoscenza import INDICAZIONI, Indicazione  # noqa: F401

RADICE = Path(__file__).resolve().parent.parent

# Le raccomandazioni sono classi ATC di livello 4: cinque caratteri.
LIVELLO_CLASSE = 5


def classe(atc: str) -> str:
    """La classe terapeutica di un codice ATC: i primi cinque caratteri."""
    return atc[:LIVELLO_CLASSE]


# Le indicazioni cliniche stanno in kb/conoscenza.ttl (kb_build.py -> conoscenza.py).

# Peso della classe di raccomandazione ESC: un ordinamento, non una probabilita'.
PESO_CLASSE = {"I": 1.0, "IIa": 0.6, "IIb": 0.3}


# --- Il caso da ordinare ---

@dataclass(frozen=True)
class Caso:
    """Cio' che un ranker vede di un paziente, e cio' che il medico ha deciso.

    `dimissione` e' la verita': nessun ranker la riceve (`ordina` non la include).
    """

    enc_oid: int
    condizioni: frozenset[str]        # codici ICD-10 affermati, del paziente
    terapia_ingresso: frozenset[str]  # classi ATC4
    allergie: frozenset[str]          # codici ATC a cui il paziente e' allergico
    dimissione: frozenset[str]        # classi ATC4 — la verita'

    @property
    def aggiunte(self) -> frozenset[str]:
        """Le classi che il ricovero ha aggiunto: il bersaglio del compito 2."""
        return self.dimissione - self.terapia_ingresso


@dataclass(frozen=True)
class Raccomandazione:
    """Una classe proposta, con il punteggio e la ragione citabile."""

    classe_atc: str
    punteggio: float
    motivo: str = ""
    fonte: str = ""


class Ranker(ABC):
    """Ordina le classi candidate per un paziente, dalla piu' alla meno adatta."""

    sigla: str = "?"
    nome: str = "?"

    @abstractmethod
    def ordina(self, caso: Caso, candidati: Sequence[str]) -> list[Raccomandazione]:
        ...

    def addestra(self, casi: Iterable[Caso]) -> None:
        """I ranker che non imparano da nulla non fanno niente qui."""
        return None


# --- Ranker 0 — la linea di base ---

class RankerContinuita(Ranker):
    """Linea di base: continua quello che il paziente gia' prendeva."""

    sigla = "base"
    nome = "continuita' della terapia"

    def ordina(self, caso: Caso, candidati: Sequence[str]) -> list[Raccomandazione]:
        return sorted(
            (Raccomandazione(c, 1.0 if c in caso.terapia_ingresso else 0.0,
                             "gia' in terapia all'ingresso" if c in caso.terapia_ingresso else "")
             for c in candidati),
            key=lambda r: (-r.punteggio, r.classe_atc),
        )


class RankerFrequenza(Ranker):
    """Linea di base: propone cio' che viene aggiunto piu' spesso, senza guardare il paziente."""

    sigla = "freq"
    nome = "frequenza delle aggiunte"

    def __init__(self) -> None:
        self.conteggio: Counter[str] = Counter()

    def addestra(self, casi: Iterable[Caso]) -> None:
        self.conteggio = Counter()
        for caso in casi:
            self.conteggio.update(caso.aggiunte)

    def ordina(self, caso: Caso, candidati: Sequence[str]) -> list[Raccomandazione]:
        return sorted(
            (Raccomandazione(c, float(self.conteggio.get(c, 0)),
                             f"aggiunta in {self.conteggio.get(c, 0)} ricoveri "
                             f"dell'insieme di addestramento")
             for c in candidati),
            key=lambda r: (-r.punteggio, r.classe_atc),
        )


# --- Ranker 1 — simbolico ---

class RankerSimbolico(Ranker):
    """Ordina per indicazione citata: nessun dato, nessun apprendimento.

    Punteggio = peso della migliore indicazione (non la somma: tre IIa non
    fanno una I); a parita' vince chi ha piu' indicazioni distinte.
    """

    sigla = "simb"
    nome = "simbolico (linee guida ESC)"

    def __init__(self, indicazioni: tuple[Indicazione, ...] = INDICAZIONI) -> None:
        self.indicazioni = indicazioni

    def _scatta(self, ind: Indicazione, caso: Caso) -> bool:
        if ind.atc_richiesto:
            if not any(t.startswith(p) for p in ind.atc_richiesto
                       for t in caso.terapia_ingresso):
                return False
            # Un'indicazione innescata dalla sola terapia non ha bisogno di ICD.
            if not ind.icd:
                return True
        return any(c.startswith(p) for p in ind.icd for c in caso.condizioni)

    def motivazioni(self, caso: Caso, cls: str) -> list[Indicazione]:
        """Le indicazioni che sostengono una classe per questo paziente."""
        return [i for i in self.indicazioni
                if cls.startswith(i.atc) and self._scatta(i, caso)]

    def ordina(self, caso: Caso, candidati: Sequence[str]) -> list[Raccomandazione]:
        fuori: list[Raccomandazione] = []
        dentro: list[Raccomandazione] = []
        for cls in candidati:
            valide = self.motivazioni(caso, cls)
            if not valide:
                fuori.append(Raccomandazione(cls, 0.0))
                continue
            migliore = max(valide, key=lambda i: PESO_CLASSE[i.classe_racc])
            punteggio = PESO_CLASSE[migliore.classe_racc] + 0.01 * (len(valide) - 1)
            dentro.append(Raccomandazione(
                cls, punteggio,
                f"classe {migliore.classe_racc}: {migliore.motivo}",
                migliore.fonte))
        dentro.sort(key=lambda r: (-r.punteggio, r.classe_atc))
        fuori.sort(key=lambda r: r.classe_atc)
        return dentro + fuori


# --- Ranker 2 — ibrido ---

class RankerIbrido(Ranker):
    """Indicazione citata piu' co-occorrenza imparata dall'addestramento.

    Punteggio in spazio logaritmico:
        log P(classe | caratteristica) = log P(classe) + PMI(caratteristica, classe)
    piu' un peso per l'indicazione ESC. Il primo addendo e' il ranker di
    frequenza, quindi senza evidenza l'ibrido ricade su di esso. Le
    caratteristiche sono le condizioni (a 3 caratteri) e la terapia in atto,
    con prefissi distinti. Perche' la PMI da sola non bastava: docs/09_ranker.md.
    """

    sigla = "ibr"
    nome = "ibrido (indicazioni + co-occorrenza)"

    def __init__(self, peso_guida: float = 0.5,
                 indicazioni: tuple[Indicazione, ...] = INDICAZIONI) -> None:
        self.simbolico = RankerSimbolico(indicazioni)
        # Peso della linea guida rispetto al dato, in spazio logaritmico; scelto
        # su una parte di validazione, curva piatta fra 0,25 e 1,0 (docs/09).
        self.peso_guida = peso_guida
        self.pmi: dict[tuple[str, str], float] = {}
        self.log_base: dict[str, float] = {}
        self.minimo = -10.0
        self.casi_addestramento = 0

    @staticmethod
    def _caratteristiche(caso: Caso) -> set[str]:
        """Condizioni troncate a 3 caratteri (`I50.9` -> `I50`) e terapia in atto, con prefissi distinti."""
        return ({f"D:{c[:3]}" for c in caso.condizioni}
                | {f"T:{t}" for t in caso.terapia_ingresso})

    def addestra(self, casi: Iterable[Caso]) -> None:
        """Stima P(aggiunta | caratteristica) sui soli casi di addestramento."""
        casi = list(casi)
        self.casi_addestramento = len(casi)
        if not casi:
            return

        conteggio_cls: Counter[str] = Counter()
        conteggio_car: Counter[str] = Counter()
        congiunto: Counter[tuple[str, str]] = Counter()
        for caso in casi:
            car = self._caratteristiche(caso)
            conteggio_car.update(car)
            conteggio_cls.update(caso.aggiunte)
            for c in car:
                for cls in caso.aggiunte:
                    congiunto[(c, cls)] += 1

        n = len(casi)
        # log della frequenza di base: il punto da cui l'ibrido parte.
        self.log_base = {cls: math.log(v / n) for cls, v in conteggio_cls.items()}
        self.minimo = math.log(0.5 / n)   # una classe mai aggiunta: mezzo caso
        for (c, cls), v in congiunto.items():
            # Solo dove l'evidenza esiste: due ricoveri non stabiliscono nulla.
            if v < 3 or conteggio_car[c] < 5:
                continue
            p_condizionata = v / conteggio_car[c]
            self.pmi[(c, cls)] = math.log(p_condizionata) - self.log_base[cls]

    def _statistica(self, caso: Caso, cls: str) -> float:
        """log P(classe | la caratteristica piu' informativa): il massimo, non la somma."""
        car = self._caratteristiche(caso)
        guadagno = max((self.pmi[(c, cls)] for c in car if (c, cls) in self.pmi),
                       default=0.0)
        return self.log_base.get(cls, self.minimo) + guadagno

    def ordina(self, caso: Caso, candidati: Sequence[str]) -> list[Raccomandazione]:
        simboliche = {r.classe_atc: r for r in self.simbolico.ordina(caso, candidati)}
        fuse: list[Raccomandazione] = []
        for cls in candidati:
            s = simboliche[cls]
            stat = self._statistica(caso, cls)
            motivo = s.motivo or (
                f"nessuna indicazione citata; co-occorrenza misurata su "
                f"{self.casi_addestramento} ricoveri")
            fuse.append(Raccomandazione(
                cls, stat + self.peso_guida * s.punteggio, motivo, s.fonte))
        fuse.sort(key=lambda r: (-r.punteggio, r.classe_atc))
        return fuse


# --- Ranker 3 — con modello linguistico ---

ISTRUZIONI_LLM = """Sei un supporto alla decisione terapeutica in cardiologia.

Ricevi lo stato di un paziente ricoverato e un elenco di CLASSI ATC candidate.
Ordina le classi candidate dalla piu' alla meno appropriata per questo paziente,
sulla base delle linee guida cardiologiche.

REGOLE VINCOLANTI

1. Rispondi SOLO con codici presi dall'elenco dei candidati, copiati
   esattamente. Un codice non presente nell'elenco viene scartato: l'elenco e'
   gia' stato ripulito da un filtro di sicurezza, e proporre qualcosa che non
   c'e' significa proporre un farmaco che il filtro ha escluso.

2. Proponi AL MASSIMO 15 classi, dalla migliore in giu'. Fermati prima se le
   classi rimanenti non sono indicate per questo paziente: un elenco corto e
   giusto vale piu' di un elenco lungo. Non ripetere mai una classe gia'
   scritta.

3. Le condizioni elencate sono gia' state verificate come affermate e riferite
   al paziente: non sono negate e non sono di un familiare.

4. Non aggiungere dosaggi, nomi commerciali o principi attivi. Solo codici di
   classe ATC.
"""

# `maxItems` e' necessario: senza tetto il modello locale emetteva centinaia
# di voci fino a saturare il contesto (docs/09_ranker.md).
TETTO_PROPOSTE = 15

SCHEMA_LLM = {
    "type": "object",
    "properties": {
        "ordine": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": TETTO_PROPOSTE,
            "description": "Classi ATC candidate, dalla piu' alla meno appropriata.",
        }
    },
    "required": ["ordine"],
    "additionalProperties": False,
}


def descrivi_caso(caso: Caso, candidati: Sequence[str],
                  nomi_icd: dict[str, str] | None = None,
                  nomi_atc: dict[str, str] | None = None) -> str:
    """Il testo mandato al modello: codici con i loro nomi, cosi' il compito e' clinico e non di memoria."""
    nomi_icd = nomi_icd or {}
    nomi_atc = nomi_atc or {}

    def riga(codice: str, nomi: dict[str, str]) -> str:
        nome = nomi.get(codice) or nomi.get(codice[:3]) or ""
        return f"{codice} {nome}".strip()

    parti = ["CONDIZIONI DEL PAZIENTE (ICD-10):"]
    parti.append("  " + "; ".join(riga(c, nomi_icd) for c in sorted(caso.condizioni))
                 if caso.condizioni else "  nessuna condizione codificata")
    parti.append("")
    parti.append("TERAPIA IN ATTO ALL'INGRESSO (classi ATC):")
    parti.append("  " + "; ".join(riga(c, nomi_atc) for c in sorted(caso.terapia_ingresso))
                 if caso.terapia_ingresso else "  nessuna")
    if caso.allergie:
        parti.append("")
        parti.append("ALLERGIE (ATC): " + "; ".join(sorted(caso.allergie)))
    parti.append("")
    parti.append("CLASSI CANDIDATE, gia' filtrate per sicurezza:")
    for c in candidati:
        parti.append(f"  {riga(c, nomi_atc)}")
    return "\n".join(parti)


class RankerLLM(Ranker):
    """Ordina chiedendo a un modello linguistico, vincolato all'insieme candidato.

    Un codice fuori elenco scavalcherebbe il filtro dello step 8: viene
    scartato e contato (`scartati`).
    """

    sigla = "llm"
    nome = "modello linguistico"

    def __init__(self, backend, nomi_icd=None, nomi_atc=None, rapporto=None) -> None:
        self.backend = backend
        self.nomi_icd = nomi_icd or {}
        self.nomi_atc = nomi_atc or {}
        # Avanzamento per record: una corsa locale dura ore.
        self.rapporto = rapporto
        self.secondi = 0.0
        self.scartati = 0          # codici proposti fuori dall'elenco candidato
        self.chiamate = 0
        self.token = {"ingresso": 0, "uscita": 0}
        self.costo = 0.0
        # Risposte che ricopiano l'ordine dei candidati senza riordinare:
        # distingue «ordina male» da «non ordina affatto».
        self.in_ordine_di_ingresso = 0
        self.risposte_non_vuote = 0

    def ordina(self, caso: Caso, candidati: Sequence[str]) -> list[Raccomandazione]:
        import time

        from llm_backend import Richiesta

        testo = descrivi_caso(caso, candidati, self.nomi_icd, self.nomi_atc)
        avvio = time.time()
        risposta = self.backend.genera(Richiesta(
            istruzioni=ISTRUZIONI_LLM, testo=testo, schema=SCHEMA_LLM,
            temperatura=0.0))
        self.chiamate += 1
        self.token["ingresso"] += risposta.token_ingresso
        self.token["uscita"] += risposta.token_uscita
        self.costo += risposta.costo
        self.secondi += time.time() - avvio
        if self.rapporto:
            self.rapporto(self.chiamate, caso.enc_oid, risposta,
                          time.time() - avvio)

        ammessi = set(candidati)
        visti: set[str] = set()
        ordine: list[str] = []
        for grezzo in risposta.contenuto.get("ordine", []):
            cls = classe(str(grezzo).strip().upper())
            if cls not in ammessi:
                self.scartati += 1
                continue
            if cls in visti:
                continue
            visti.add(cls)
            ordine.append(cls)

        if len(ordine) >= 2:
            self.risposte_non_vuote += 1
            posizione = {c: i for i, c in enumerate(candidati)}
            posizioni = [posizione[c] for c in ordine]
            if posizioni == sorted(posizioni):
                self.in_ordine_di_ingresso += 1

        n = len(ordine)
        fuori = sorted(ammessi - visti)
        return ([Raccomandazione(c, float(n - i), "proposta dal modello")
                 for i, c in enumerate(ordine)]
                + [Raccomandazione(c, 0.0, "non proposta") for c in fuori])


# --- Costruzione dei casi dalle uscite delle pipeline ---

def carica_casi(cartella: Path) -> list[Caso]:
    """Legge i casi con terapia di dimissione codificata; condizioni solo affermate e del paziente."""
    casi: list[Caso] = []
    for percorso in sorted(cartella.glob("*.json")):
        if percorso.stem.startswith("_"):
            continue
        d = json.loads(percorso.read_text(encoding="utf-8"))
        ingresso = {classe(f["codice_atc"]) for f in d["farmaci"]
                    if f.get("codice_atc") and f.get("momento") == "ingresso"}
        dimissione = {classe(f["codice_atc"]) for f in d["farmaci"]
                      if f.get("codice_atc") and f.get("momento") == "dimissione"}
        if not dimissione:
            continue
        condizioni = {c["codice"] for c in d["condizioni"]
                      if c.get("codice") and c.get("stato") == "affermato"
                      and c.get("soggetto", "paziente") == "paziente"}
        allergie = {a["codice_atc"] for a in d["allergie"] if a.get("codice_atc")}
        casi.append(Caso(d["enc_oid"], frozenset(condizioni), frozenset(ingresso),
                         frozenset(allergie), frozenset(dimissione)))
    return casi


def pieghe(casi: Sequence[Caso], quante: int = 5,
           seme: int = 20260915, stratifica: bool = False) -> list[list[Caso]]:
    """Divide i casi in `quante` pieghe disgiunte, deterministiche per hash dell'`enc_oid`."""
    import hashlib

    fuori: list[list[Caso]] = [[] for _ in range(quante)]
    if not stratifica:
        for caso in casi:
            impronta = hashlib.sha256(f"{seme}:{caso.enc_oid}".encode()).hexdigest()
            fuori[int(impronta[:8], 16) % quante].append(caso)
        return fuori
    # Stratificate per condizione principale: dentro ogni strato, a turno per impronta.
    def strato(caso: Caso) -> str:
        for prefisso in ("I50", "I48", "I25", "I10"):
            if any(c.startswith(prefisso) for c in caso.condizioni):
                return prefisso
        return "altro"
    per_strato: dict[str, list[Caso]] = {}
    for caso in casi:
        per_strato.setdefault(strato(caso), []).append(caso)
    for gruppo in per_strato.values():
        gruppo.sort(key=lambda c: hashlib.sha256(f"{seme}:{c.enc_oid}".encode()).hexdigest())
        for i, caso in enumerate(gruppo):
            fuori[i % quante].append(caso)
    return fuori


def dividi(casi: Sequence[Caso], quota_prova: float = 0.3,
           seme: int = 20260915) -> tuple[list[Caso], list[Caso]]:
    """Divide in addestramento e prova per hash dell'`enc_oid`: stessa quota, stessi insiemi."""
    import hashlib

    prova, addestramento = [], []
    for caso in casi:
        impronta = hashlib.sha256(f"{seme}:{caso.enc_oid}".encode()).hexdigest()
        if int(impronta[:8], 16) / 0xFFFFFFFF < quota_prova:
            prova.append(caso)
        else:
            addestramento.append(caso)
    return addestramento, prova


def insieme_candidato(casi: Sequence[Caso], soglia: int = 3) -> list[str]:
    """Le classi proponibili: aggiunte almeno `soglia` volte nei soli casi di addestramento."""
    conteggio: Counter[str] = Counter()
    for caso in casi:
        conteggio.update(caso.dimissione)
    return sorted(c for c, v in conteggio.items() if v >= soglia)


def applica_filtro(caso: Caso, candidati: Sequence[str],
                   percorsi: dict[str, Path] | None = None) -> list[str]:
    """Toglie dai candidati cio' che il filtro dello step 8 vieta; `da_verificare` resta.

    Un'allergia a una sostanza non esclude la sua classe (l'allergico
    all'aspirina riceve correttamente il clopidogrel): vedi `allerta_di_classe`
    e docs/09_ranker.md.
    """
    from filtro import Esito, StatoPerFiltro, valuta

    stato = StatoPerFiltro(
        caso.enc_oid,
        [{"codice": c, "testo": "", "agenti": ["A", "B", "C"]} for c in caso.condizioni],
        set(caso.allergie),
        set(caso.terapia_ingresso),
    )
    ammessi = []
    for cls in candidati:
        if valuta(stato, cls, esclusa_dalla_terapia=cls).esito is not Esito.VIETATO:
            ammessi.append(cls)
    return ammessi


# --- I nomi dei codici ---

PERCORSO_ATC = RADICE / "data" / "external" / "aifa" / "atc.csv"
PERCORSO_ICD = RADICE / "data" / "interim" / "terminologia_icd10.json"


def nomi_atc(percorso: Path = PERCORSO_ATC) -> dict[str, str]:
    """Descrizione italiana di ogni codice ATC (AIFA, `atc.csv`, CC-BY 4.0)."""
    import csv

    nomi: dict[str, str] = {}
    with percorso.open(encoding="utf-8-sig") as f:
        for riga in csv.DictReader(f, delimiter=";"):
            nomi[riga["CODICE_ATC"].strip()] = riga["DESCRIZIONE"].strip().lower()
    return nomi


def nomi_icd(percorso: Path = PERCORSO_ICD) -> dict[str, str]:
    """Titolo italiano di ogni voce ICD-10 (Elenco Sistematico 2019, step 2)."""
    d = json.loads(percorso.read_text(encoding="utf-8"))
    return {v["codice"]: v["titolo"] for v in d["voci"]}


def allerta_di_classe(caso: Caso, cls: str) -> str | None:
    """Avverte (non esclude) che il paziente e' allergico a una sostanza di questa classe."""
    colpite = sorted(a for a in caso.allergie if a.startswith(cls))
    if not colpite:
        return None
    return ("allergia dichiarata a una sostanza di questa classe "
            f"({', '.join(colpite)}): scegliere un'altra molecola.")


def annota(caso: Caso, raccomandazioni: Sequence[Raccomandazione]
           ) -> list[Raccomandazione]:
    """Aggiunge alle raccomandazioni gli avvertimenti che non sono esclusioni."""
    fuori = []
    for r in raccomandazioni:
        allerta = allerta_di_classe(caso, r.classe_atc)
        fuori.append(r if not allerta
                     else Raccomandazione(r.classe_atc, r.punteggio,
                                          f"{r.motivo} ATTENZIONE: {allerta}".strip(),
                                          r.fonte))
    return fuori
