"""Step 9 — i tre ranker: che cosa proporre, e in che ordine.

Il filtro dello step 8 dice che cosa **non** si puo' dare. Non dice che cosa
convenga dare: su 5 863 prescrizioni reali ne ha vietate 4, quindi da solo
lascia passare quasi tutto. Il ranker e' lo strato che ordina cio' che resta.

## Il bersaglio, e perche' e' gratuito

La verita' di riferimento e' gia' nei dati, esatta e senza annotazione: la
**terapia alla dimissione** e' la decisione che un cardiologo ha davvero preso
per quel paziente. E' la stessa proprieta' che allo step 7 ha permesso di
misurare il parser deterministico contro il campo stesso — un campo con
delimitatori e' la propria verita' — applicata qui a un compito di
raccomandazione. 841 ricoveri su 1 000 hanno una terapia di dimissione
codificata.

## L'unita': la classe terapeutica, non il principio attivo

Le raccomandazioni sono classi ATC di **livello 4** (cinque caratteri: `C07AB`
betabloccanti selettivi, `C03DA` antialdosteronici, `B01AF` anticoagulanti orali
diretti). E' il livello a cui le linee guida nominano i farmaci: l'ESC
raccomanda «un betabloccante», non «bisoprololo 2,5 mg». Scegliere fra venti
betabloccanti sostanzialmente intercambiabili e' una decisione di prontuario, e
misurarla come se fosse clinica misurerebbe rumore.

## I due compiti, e perche' servono entrambi

**Compito 1 — la terapia completa.** Prevedere l'intero insieme di classi alla
dimissione. Va misurato per una sola ragione: mostrare che e' quasi risolto
senza ragionare. La linea di base «continua quello che il paziente gia'
prendeva» azzecca il **63,6%** delle classi di dimissione. Un ranker che si
ferma li' non ha imparato nulla, e senza questo numero un 65% sembrerebbe un
risultato.

**Compito 2 — le aggiunte.** Prevedere le sole classi **nuove**, quelle che il
ricovero ha aggiunto: 2 075 decisioni su 841 ricoveri, 2,47 per ricovero. Qui la
continuita' non vale niente e la linea di base e' la frequenza. E' il compito
vero, ed e' su questo che i tre ranker si separano.

## Il tetto del ranker simbolico, noto prima di misurarlo

Misurato sul corpus: il **40,4%** delle prescrizioni di dimissione, e il
**41,7%** delle sole aggiunte, **non e' cardiovascolare** — inibitori di pompa
protonica (525 prescrizioni), allopurinolo, levotiroxina, potassio,
corticosteroidi topici. Un ranker costruito sulle linee guida cardiologiche non
puo' proporli, e il suo richiamo ha percio' un tetto intorno al 60% **per
costruzione**.

Non ho colmato quel divario inventando regole fuori dal dominio in cui ho una
fonte citabile: sarebbe stata conoscenza di un modello linguistico travestita da
linea guida. Il divario resta, misurato, ed e' precisamente cio' che il ranker
ibrido puo' chiudere imparandolo dai dati — e cio' che il confronto deve
mostrare.

E' la stessa forma del risultato dello step 6: il richiamo della pipeline A era
limitato dal denominatore della sua base di conoscenza, non dal suo algoritmo.
Qui il limite del ranker simbolico e' il perimetro delle linee guida che lo
alimentano.
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


# ---------------------------------------------------------------------------
# LE INDICAZIONI CLINICHE
#
# Sono nel grafo di conoscenza `kb/conoscenza.ttl` (scritto da `kb_build.py`,
# letto da `conoscenza.py`): ogni riga porta la fonte, e la fonte e' un
# documento pubblicato, non la conoscenza di un modello. Qui il ranker le
# riceve gia' lette: non ne possiede una copia.
# ---------------------------------------------------------------------------

# Peso della classe di raccomandazione ESC. I numeri sono un ordinamento, non
# una probabilita': servono a dire che una raccomandazione di classe I viene
# prima di una di classe IIb, non a quantificare di quanto.
PESO_CLASSE = {"I": 1.0, "IIa": 0.6, "IIb": 0.3}


# ---------------------------------------------------------------------------
# Il caso da ordinare
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Caso:
    """Cio' che un ranker vede di un paziente, e cio' che il medico ha deciso.

    `dimissione` e' la verita' di riferimento: e' presente nel caso perche' il
    caso e' anche l'unita' di valutazione, ma **nessun ranker la riceve** — la
    firma di `ordina` non la include.
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
    """Una classe proposta, con il punteggio e la ragione.

    `motivo` e `fonte` non sono ornamento: un supporto alla decisione che non
    sa dire perche' propone qualcosa non e' verificabile da un medico, ed e' il
    motivo per cui il ranker simbolico resta nel confronto anche se perde.
    """

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


# ---------------------------------------------------------------------------
# Ranker 0 — la linea di base
# ---------------------------------------------------------------------------

class RankerContinuita(Ranker):
    """«Prescrivi alla dimissione quello che il paziente gia' prendeva.»

    Non e' un ranker: e' il numero sotto cui nessun ranker puo' scendere senza
    essere peggio di non fare niente. Sul compito 1 azzecca il 63,6% delle
    classi. Sul compito 2, per costruzione, azzecca zero — e' il motivo per cui
    il compito 2 esiste.
    """

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
    """La linea di base del compito 2: proponi cio' che viene aggiunto piu' spesso.

    Ignora completamente il paziente. Serve a separare «il ranker ha capito
    qualcosa di questo malato» da «il ranker ha imparato quali farmaci si
    prescrivono in questo reparto».
    """

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


# ---------------------------------------------------------------------------
# Ranker 1 — simbolico
# ---------------------------------------------------------------------------

class RankerSimbolico(Ranker):
    """Ordina per indicazione citata: nessun dato, nessun apprendimento.

    Il punteggio di una classe e' il peso della **migliore** indicazione che la
    sostiene, non la somma: tre ragioni di classe IIa non fanno una classe I.
    Sommarle premierebbe le classi che compaiono in molte linee guida invece di
    quelle fortemente raccomandate per questo paziente.

    A parita' di punteggio vince la classe con piu' indicazioni distinte: fra
    due raccomandazioni di classe I, quella che vale per tre delle condizioni di
    questo paziente viene prima.
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


# ---------------------------------------------------------------------------
# Ranker 2 — ibrido
# ---------------------------------------------------------------------------

class RankerIbrido(Ranker):
    """Indicazione citata piu' co-occorrenza misurata sull'insieme di addestramento.

    Le due parti hanno ruoli diversi e complementari, ed e' questo che rende
    l'ibrido interessante e non solo «il simbolico con un numero in piu'»:

    * il **simbolico** sa che nella fibrillazione atriale serve un
      anticoagulante anche se in questo reparto lo prescrivessero raramente —
      la linea guida non dipende dall'abitudine locale;
    * la **statistica** sa che a questi pazienti si aggiunge un inibitore di
      pompa protonica, cosa che nessuna linea guida cardiologica dice, e che
      da sola vale il 40,4% delle prescrizioni.

    ## Il punteggio statistico, e un errore che ha dovuto essere corretto

    La prima versione ordinava per **informazione mutua puntuale** — di quanto
    una condizione rende una classe piu' probabile del solito — e il risultato
    e' stato che l'ibrido andava **peggio della linea di base di frequenza**
    (richiamo@5 sulle aggiunte: 26,3% contro 49,5%).

    La causa non era un difetto di implementazione ma di grandezza misurata. La
    PMI e' un *guadagno*: una classe aggiunta a meta' dei pazienti qualunque sia
    la loro malattia ha PMI vicina a zero, perche' nessuna condizione la rende
    piu' attesa di quanto gia' non sia. Ordinare per PMI mette in cima le classi
    *specifiche* e in fondo quelle *probabili*, mentre la domanda del compito e'
    quale classe verra' aggiunta — cioe' una probabilita', non un guadagno.

    La correzione e' lavorare in spazio logaritmico e sommare le due parti:

        log P(classe | condizione) = log P(classe) + PMI(condizione, classe)

    Il primo addendo e' esattamente il ranker di frequenza, il secondo e' cio'
    che l'ibrido aggiunge. Cosi' l'ibrido **non puo' fare peggio della frequenza
    per costruzione**: in assenza di evidenza sulla condizione la PMI e' zero e
    il punteggio ricade sulla frequenza.

    ## Le condizioni non sono l'unica caratteristica

    Il modello statistico guarda anche la **terapia in atto**, non solo le
    diagnosi. E' la controparte appresa della gastroprotezione: che un paziente
    prenda un antitrombotico predice l'aggiunta di un inibitore di pompa
    protonica meglio di qualunque sua diagnosi. Le due famiglie di
    caratteristiche sono distinte da un prefisso perche' `I50` la condizione e
    `C03CA` il farmaco non devono mai finire nello stesso conteggio.
    """

    sigla = "ibr"
    nome = "ibrido (indicazioni + co-occorrenza)"

    def __init__(self, peso_guida: float = 0.5,
                 indicazioni: tuple[Indicazione, ...] = INDICAZIONI) -> None:
        self.simbolico = RankerSimbolico(indicazioni)
        # Quanto pesa una raccomandazione di linea guida rispetto all'abitudine
        # misurata, in spazio logaritmico: 0,5 su una raccomandazione di classe
        # I moltiplica per e^0,5 ~ 1,65 la probabilita' stimata.
        #
        # Il valore e' stato scelto su una parte di **validazione ritagliata
        # dall'addestramento**, mai sulla prova. La curva e' piatta fra 0,25 e
        # 1,0 (richiamo@5 dal 43,1% al 43,9%, dentro il pavimento di rumore del
        # progetto) e cala nettamente sopra: a 2,0 scende a 39,5%, a 8,0 a
        # 33,3%. Sopra quella soglia la linea guida sovrasta il dato e il ranker
        # smette di sapere che in questo reparto si prescrivono gastroprotettori.
        #
        # A peso zero — sola statistica — il richiamo@3 e' 28,3% contro il 31,2%
        # dell'ottimo: le linee guida aggiungono qualcosa, ma **poco**, e questo
        # e' un risultato dello step 9, non un difetto della taratura.
        self.peso_guida = peso_guida
        self.pmi: dict[tuple[str, str], float] = {}
        self.log_base: dict[str, float] = {}
        self.minimo = -10.0
        self.casi_addestramento = 0

    @staticmethod
    def _caratteristiche(caso: Caso) -> set[str]:
        """Cio' che il modello statistico osserva del paziente.

        Le condizioni sono troncate a tre caratteri (`I50.9` -> `I50`): il
        corpus scrive la stessa malattia a profondita' diverse — `I48` e
        `I48.0`, `E11` ed `E14` — e contarle separate spezzerebbe l'evidenza in
        due mucchi troppo piccoli. La terapia in atto entra con un prefisso
        proprio, perche' una diagnosi e un farmaco non devono mai sommarsi nello
        stesso conteggio.
        """
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
        # Il logaritmo della frequenza di base: e' esattamente l'ordinamento del
        # ranker di frequenza, ed e' il punto da cui l'ibrido parte.
        self.log_base = {cls: math.log(v / n) for cls, v in conteggio_cls.items()}
        self.minimo = math.log(0.5 / n)   # una classe mai aggiunta: mezzo caso
        for (c, cls), v in congiunto.items():
            # Solo dove l'evidenza esiste: due ricoveri non stabiliscono nulla.
            if v < 3 or conteggio_car[c] < 5:
                continue
            p_condizionata = v / conteggio_car[c]
            self.pmi[(c, cls)] = math.log(p_condizionata) - self.log_base[cls]

    def _statistica(self, caso: Caso, cls: str) -> float:
        """log P(aggiunta della classe | la caratteristica piu' informativa).

        Il massimo e non la somma: una caratteristica che spiega fortemente la
        classe basta, e sommare premierebbe i pazienti con molte diagnosi invece
        dei pazienti per cui la classe e' indicata.
        """
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


# ---------------------------------------------------------------------------
# Ranker 3 — con modello linguistico
# ---------------------------------------------------------------------------

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

# Il tetto sull'array non e' una cautela generica: e' la correzione di un guasto
# osservato. Con `items` senza `maxItems`, la decodifica vincolata allo schema
# permette al modello di emettere stringhe all'infinito, e il modello locale da
# 4 miliardi di parametri lo fa: su un ricovero ha prodotto **oltre 310 voci da
# 91 candidati**, ripetendosi finche' non ha saturato il contesto, e il JSON e'
# arrivato troncato a meta' stringa. La chiamata spendeva minuti per produrre
# spazzatura.
#
# Quindici e' il numero giusto per il compito, non un numero prudente: la
# metrica piu' profonda del progetto e' il richiamo@10, e un medico guarda le
# prime proposte. Oltre il quindicesimo posto non c'e' nulla da misurare.
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
    """Il testo mandato al modello.

    Porta i **nomi** accanto ai codici: un modello che legge `I50.9` senza
    «insufficienza cardiaca» sta facendo un compito di memoria sulla
    terminologia invece che un compito clinico, e misureremmo la cosa sbagliata.
    """
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

    Il vincolo non e' un dettaglio implementativo: e' un requisito di sicurezza,
    e viene da un'osservazione misurata. Alla prima prova il modello locale, su
    un paziente con fibrillazione atriale, ha prodotto nove codici da un elenco
    di otto candidati — il nono copiato dalla riga della terapia in atto. Se il
    ranker puo' nominare una classe fuori dai candidati, **scavalca il filtro
    dello step 8**, che e' l'unico strato che impedisce di proporre un farmaco
    a cui il paziente e' allergico.

    I codici fuori elenco vengono scartati, e quante volte succede e' un dato
    che la valutazione riporta: e' la misura di quanto il vincolo serva.
    """

    sigla = "llm"
    nome = "modello linguistico"

    def __init__(self, backend, nomi_icd=None, nomi_atc=None, rapporto=None) -> None:
        self.backend = backend
        self.nomi_icd = nomi_icd or {}
        self.nomi_atc = nomi_atc or {}
        # Una corsa locale dura ore: senza un avanzamento visibile non si
        # distingue «lento» da «bloccato», e la prima volta che e' successo ho
        # creduto per venti minuti a un modello fermo che stava solo macinando.
        self.rapporto = rapporto
        self.secondi = 0.0
        self.scartati = 0          # codici proposti fuori dall'elenco candidato
        self.chiamate = 0
        self.token = {"ingresso": 0, "uscita": 0}
        self.costo = 0.0
        # Quante risposte sono un **sottoinsieme in ordine** dell'elenco
        # candidato, cioe' il modello ha selezionato senza riordinare. E' il
        # controllo che distingue «ordina male» da «non ordina affatto», e un
        # ranker che non riordina e' inutile a k piccolo — l'unico k che un
        # medico guarda.
        #
        # Il sospetto e' nato da una risposta che restituiva le classi in
        # ordine alfabetico di codice, cioe' nell'ordine in cui le aveva
        # ricevute. Quella chiamata era pero' **essa stessa in avaria** (vedi
        # TETTO_PROPOSTE), quindi non prova niente: serviva un contatore su
        # tutta la corsa, e questo e' quel contatore.
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


# ---------------------------------------------------------------------------
# Costruzione dei casi dalle uscite delle pipeline
# ---------------------------------------------------------------------------

def carica_casi(cartella: Path) -> list[Caso]:
    """Legge i casi valutabili: quelli con una terapia di dimissione codificata.

    Applica la stessa regola dello step 8 sulle condizioni — solo affermate e
    del paziente — perche' un ranker che raccomandasse in base alla malattia del
    padre sarebbe peggio di uno che non raccomanda niente.
    """
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
           seme: int = 20260915) -> list[list[Caso]]:
    """Divide i casi in `quante` pieghe disgiunte, in modo deterministico.

    Stessa idea di `dividi`: l'assegnazione dipende solo dall'`enc_oid` e dal
    seme, cosi' due corse producono le stesse pieghe. Serve alla validazione
    incrociata dello step 11 — ogni ricovero e' misurato una volta sola, come
    prova, da un ranker che non lo ha mai visto in addestramento.
    """
    import hashlib

    fuori: list[list[Caso]] = [[] for _ in range(quante)]
    for caso in casi:
        impronta = hashlib.sha256(f"{seme}:{caso.enc_oid}".encode()).hexdigest()
        fuori[int(impronta[:8], 16) % quante].append(caso)
    return fuori


def dividi(casi: Sequence[Caso], quota_prova: float = 0.3,
           seme: int = 20260915) -> tuple[list[Caso], list[Caso]]:
    """Divide in addestramento e prova in modo deterministico e riproducibile.

    La divisione usa l'`enc_oid`, non un mescolamento casuale: rieseguire la
    valutazione con la stessa quota deve dare **gli stessi** insiemi, altrimenti
    la differenza fra due corse confonde il metodo con la divisione. La quota
    e' approssimata, ed e' il prezzo della riproducibilita'.
    """
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
    """Le classi che il ranker puo' proporre.

    Costruito **solo** dai casi di addestramento: prenderlo dall'intero corpus
    farebbe trapelare nell'insieme candidato l'informazione che esistono classi
    prescritte solo nei casi di prova, e il richiamo misurato sarebbe gonfiato.

    La soglia esclude le classi viste una o due volte: non sono apprendibili, e
    lasciarle dentro allunga l'elenco mandato al modello — che si paga a token —
    senza aggiungere nulla di raggiungibile.
    """
    conteggio: Counter[str] = Counter()
    for caso in casi:
        conteggio.update(caso.dimissione)
    return sorted(c for c, v in conteggio.items() if v >= soglia)


def applica_filtro(caso: Caso, candidati: Sequence[str],
                   percorsi: dict[str, Path] | None = None) -> list[str]:
    """Toglie dai candidati cio' che il filtro dello step 8 vieta.

    Le classi solo `da_verificare` restano candidate: sono un avvertimento, non
    un'esclusione, e toglierle negherebbe terapie che quasi sempre si possono
    dare.

    ## Il filtro non toglie nulla, e la ragione e' corretta

    Misurato sui 244 ricoveri di prova: il filtro esclude **zero** classi. Non
    e' un guasto, ed e' stato verificato una causa alla volta.

    1. **I due step parlano a livelli diversi dell'ATC.** Il filtro giudica un
       *farmaco* (sette caratteri); il ranker propone una *classe* (cinque). La
       regola sulla metformina, `A10BA02`, non puo' toccare nessuna classe.
    2. **Le allergie codificate sono 57 in 841 ricoveri**, tutte a livello di
       sostanza. Per uguaglianza esatta non incontrano mai una classe.
    3. **Le due regole che avrebbero potuto scattare sono state declassate dallo
       step 8**, dal principio del fatto mancante: il betabloccante nel blocco
       atrioventricolare (5 pazienti di prova) e l'antitrombotico
       nell'emorragia intracranica (1). Entrambe emettono `da_verificare`.

    ## Perche' il prefisso NON e' la soluzione

    Ho provato a far incontrare i due livelli confrontando l'allergia per
    prefisso di classe. Toglieva 14 candidati a 12 pazienti — e il primo che ho
    aperto diceva tutto: paziente allergico all'**acido acetilsalicilico**
    (`B01AC06`), a cui il medico aveva prescritto **clopidogrel** (`B01AC04`),
    stessa classe. Il clopidogrel e' precisamente l'alternativa corretta per un
    allergico all'aspirina, e il blocco per prefisso gliela negava.

    E' la terza volta nel progetto che una regola di sicurezza troppo larga nega
    una terapia corretta invece di proteggere. Al livello di classe l'allergia a
    una sostanza e' un **avvertimento**, non un divieto: vedi `allerta_di_classe`.
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


# ---------------------------------------------------------------------------
# I nomi dei codici
# ---------------------------------------------------------------------------

PERCORSO_ATC = RADICE / "data" / "external" / "aifa" / "atc.csv"
PERCORSO_ICD = RADICE / "data" / "interim" / "terminologia_icd10.json"


def nomi_atc(percorso: Path = PERCORSO_ATC) -> dict[str, str]:
    """Descrizione italiana di ogni codice ATC.

    Fonte: AIFA — registro ATC (`atc.csv`), CC-BY 4.0. La stessa usata dal grafo
    dello step 7, perche' il nome che il ranker mostra a un medico e il nome che
    il grafo pubblica devono essere lo stesso nome.
    """
    import csv

    nomi: dict[str, str] = {}
    with percorso.open(encoding="utf-8-sig") as f:
        for riga in csv.DictReader(f, delimiter=";"):
            nomi[riga["CODICE_ATC"].strip()] = riga["DESCRIZIONE"].strip().lower()
    return nomi


def nomi_icd(percorso: Path = PERCORSO_ICD) -> dict[str, str]:
    """Titolo italiano di ogni voce ICD-10.

    Fonte: ICD-10 2019, Elenco Sistematico (edizione italiana), estratta allo
    step 2.
    """
    d = json.loads(percorso.read_text(encoding="utf-8"))
    return {v["codice"]: v["titolo"] for v in d["voci"]}


def allerta_di_classe(caso: Caso, cls: str) -> str | None:
    """Avverte che il paziente e' allergico a una sostanza di questa classe.

    Non esclude: avverte. La distinzione e' misurata, non prudenziale — un
    paziente allergico all'acido acetilsalicilico riceve correttamente il
    clopidogrel, che e' della stessa classe `B01AC`, e un'esclusione gli
    negherebbe l'unica alternativa. Chi legge la raccomandazione deve sapere
    che dentro quella classe c'e' una sostanza da evitare, e sceglierne
    un'altra.
    """
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
