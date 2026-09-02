"""
Step 1 - Schema dello "stato paziente strutturato".

E' il contratto dati del progetto: l'unica struttura che le tre pipeline di
estrazione (A deterministica, B LLM, C NER+Entity Linking) devono produrre, e
l'unico input che il motore di raccomandazione e il tool MCP accettano. Averlo
definito una volta sola e in un punto solo e' cio' che rende le tre pipeline
confrontabili: se ciascuna avesse il proprio formato, il confronto dello step 6
misurerebbe le differenze di formato invece che quelle di estrazione.

PERCHE' PYDANTIC
    - Valida i dati invece di limitarsi a descriverli: un JSON che non rispetta
      lo schema viene rifiutato al momento del caricamento, non tre step dopo.
    - Genera automaticamente lo JSON Schema, che serve sia a documentare i file
      intermedi sia, allo step 10, a far capire a un LLM la firma del tool MCP.
    - Lo step 10 richiede comunque modelli Pydantic per il tool MCP: definire lo
      schema con altri strumenti significherebbe mantenerne due versioni
      allineate a mano.
    Il costo e' l'unica dipendenza esterna finora; e' accettato consapevolmente.

I TRE STATI DI CONOSCENZA
    La scelta di modellazione piu' importante. Nei referti "il paziente non e'
    iperteso" e "dell'ipertensione non si parla" sono cose diverse: la prima e'
    un'informazione clinica (il medico ha verificato), la seconda e' assenza di
    informazione. Collassarle in un booleano perderebbe esattamente cio' che
    serve al filtro di sicurezza, che deve poter distinguere "non ha allergie"
    da "non sappiamo se ne ha".
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

# Versione dello schema. Cambiarla quando la struttura cambia in modo non
# retrocompatibile: i file intermedi la riportano, cosi' e' sempre possibile
# capire con quale versione sono stati prodotti.
VERSIONE_SCHEMA = "1.0.0"


class StatoConoscenza(str, Enum):
    """Cosa sappiamo di un'affermazione clinica.

    Eredita da `str` cosi' serializza come stringa leggibile nel JSON, invece
    che come indice numerico: i file intermedi devono restare ispezionabili a
    occhio.
    """

    AFFERMATO = "affermato"   # il referto lo afferma: "Ipertensione arteriosa."
    NEGATO = "negato"         # il referto lo nega: "Nega diabete mellito."
    INCERTO = "incerto"       # il referto lo ipotizza: "sospetta cardiopatia"
    IGNOTO = "ignoto"         # il referto non ne parla


class MomentoTerapia(str, Enum):
    """A quale momento del ricovero si riferisce una terapia."""

    INGRESSO = "ingresso"       # terapia domiciliare, dal campo terapia in ingresso
    DIMISSIONE = "dimissione"   # terapia prescritta alla dimissione (ground truth)
    NARRATIVO = "narrativo"     # menzionata nella prosa dell'anamnesi


class StatoNormalizzazione(str, Enum):
    """Esito del collegamento di una menzione a un identificatore standard.

    `NIL` e' esplicito e distinto da `NON_TENTATO`: lo step 5 richiede che le
    menzioni non collegabili siano marcate come entita' fuori KB, non forzate
    su un match sbagliato ne' confuse con quelle mai processate.
    """

    RISOLTO = "risolto"           # collegato a un identificatore standard
    NIL = "nil"                   # nessun candidato affidabile: entita' fuori KB
    AMBIGUO = "ambiguo"           # piu' candidati, nessuno prevalente
    NON_TENTATO = "non_tentato"   # normalizzazione non ancora eseguita


class Pipeline(str, Enum):
    """Quale pipeline ha prodotto l'estrazione (serve al confronto dello step 6)."""

    A_DETERMINISTICA = "A_deterministica"
    B_LLM = "B_llm"
    C_NER_EL = "C_ner_el"
    CAMPO_STRUTTURATO = "campo_strutturato"  # letto da un campo semi-strutturato


class Provenienza(BaseModel):
    """Da dove viene un'entita' estratta.

    Il brief chiede che la pipeline A sia tracciabile: per ogni entita' devono
    essere note la posizione nel testo e la regola che l'ha generata. Lo stesso
    schema serve pero' anche a B e C, dove `regola` diventa rispettivamente il
    prompt e il modello: cosi' l'audit e' uniforme fra le tre.
    """

    pipeline: Pipeline
    campo_sorgente: str = Field(description="Referto da cui proviene, es. 'Anamnesi'.")
    testo_originale: str = Field(description="La menzione esatta, come appare nel referto.")
    # Offset assenti quando l'entita' non viene dal testo libero (es. campo
    # semi-strutturato) o quando la pipeline non li fornisce (tipico di un LLM
    # generativo, che riscrive invece di puntare).
    inizio: int | None = Field(default=None, description="Offset di inizio nel campo sorgente.")
    fine: int | None = Field(default=None, description="Offset di fine nel campo sorgente.")
    regola: str | None = Field(
        default=None,
        description="Regola, pattern, prompt o modello che ha generato l'entita'.",
    )


class FarmacoEstratto(BaseModel):
    """Un farmaco attribuito al paziente.

    Nome grezzo e forme normalizzate sono campi separati e il grezzo non viene
    mai sovrascritto: e' l'unico modo per poter verificare a posteriori una
    normalizzazione sbagliata, e per non perdere informazione se la fonte
    esterna cambia.
    """

    nome_grezzo: str = Field(description="Nome come compare nel referto, non modificato.")
    principio_attivo: str | None = Field(
        default=None, description="Denominazione del principio attivo, se risolta."
    )
    codice_atc: str | None = Field(
        default=None, description="Codice ATC di 5o livello, se risolto (step 2)."
    )
    stato_normalizzazione: StatoNormalizzazione = StatoNormalizzazione.NON_TENTATO
    fonte_normalizzazione: str | None = Field(
        default=None,
        description="Fonte citabile che sostiene la normalizzazione, es. 'AIFA confezioni_fornitura'.",
    )
    momento: MomentoTerapia
    stato: StatoConoscenza = StatoConoscenza.AFFERMATO
    posologia: str | None = None
    provenienza: Provenienza


class CondizioneEstratta(BaseModel):
    """Una condizione clinica attribuita (o negata) al paziente."""

    testo_grezzo: str = Field(description="Menzione come compare nel referto.")
    concetto: str | None = Field(
        default=None, description="Forma normalizzata della condizione, se risolta."
    )
    codice: str | None = Field(
        default=None, description="Identificatore standard (ICD), se risolto (step 2)."
    )
    sistema_codifica: str | None = Field(
        default=None, description="Terminologia dell'identificatore, es. 'ICD-9-CM'."
    )
    stato_normalizzazione: StatoNormalizzazione = StatoNormalizzazione.NON_TENTATO
    stato: StatoConoscenza
    provenienza: Provenienza


class AllergiaEstratta(BaseModel):
    """Un'allergia o intolleranza documentata.

    `categoria` distingue le allergie a principi attivi (le uniche che vincolano
    la scelta terapeutica) da quelle ad alimenti, pollini o mezzi di contrasto,
    che vanno conservate ma non filtrano i farmaci.
    """

    allergene: str
    categoria: str = Field(description="'principi attivi', 'alimenti', 'altro', ...")
    codice_atc: str | None = Field(
        default=None, description="ATC dell'allergene, se e' un farmaco ed e' risolto."
    )
    stato_normalizzazione: StatoNormalizzazione = StatoNormalizzazione.NON_TENTATO
    provenienza: Provenienza


class StatoPaziente(BaseModel):
    """Lo stato strutturato di un paziente: il contratto dati del progetto.

    Prodotto da ciascuna delle tre pipeline, consumato dal motore di
    raccomandazione e dal tool MCP.
    """

    enc_oid: int = Field(description="Identificativo del ricovero (encounter).")
    versione_schema: str = VERSIONE_SCHEMA
    pipeline: Pipeline = Field(description="Pipeline che ha prodotto questo stato.")
    generato_il: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    condizioni: list[CondizioneEstratta] = Field(default_factory=list)
    farmaci: list[FarmacoEstratto] = Field(default_factory=list)
    allergie: list[AllergiaEstratta] = Field(default_factory=list)

    # Stato della *sezione* allergie, indipendente dalla lista: distingue
    # "il clinico ha verificato che non ce ne sono" (assenza dichiarata, lista
    # vuota ma informativa) da "il referto non ne parla" (lista vuota e basta).
    # Senza questo campo le due situazioni sarebbero indistinguibili, e il
    # filtro di sicurezza non potrebbe sapere quanto fidarsi di una lista vuota.
    stato_sezione_allergie: StatoConoscenza = StatoConoscenza.IGNOTO

    testo_supporto: str | None = Field(
        default=None,
        description="Testo narrativo di contesto, per l'LLM chiamante via MCP.",
    )
    note_estrazione: list[str] = Field(
        default_factory=list,
        description="Avvisi non bloccanti: frammenti non interpretati, ambiguita'.",
    )

    @property
    def farmaci_in_corso(self) -> list[FarmacoEstratto]:
        """I farmaci della terapia domiciliare, cioe' quelli gia' assunti.

        Sono i soli rilevanti per il filtro sulle interazioni della Fase 1: la
        terapia alla dimissione e' cio' che il sistema deve *predire*, quindi
        usarla come input sarebbe una fuga di informazione dalla ground truth.
        """
        return [f for f in self.farmaci if f.momento == MomentoTerapia.INGRESSO]

    @property
    def condizioni_affermate(self) -> list[CondizioneEstratta]:
        """Le sole condizioni affermate: quelle che generano candidati terapeutici."""
        return [c for c in self.condizioni if c.stato == StatoConoscenza.AFFERMATO]


def json_schema() -> dict:
    """Restituisce lo JSON Schema dello stato paziente.

    Serializzato in `data/interim/`, documenta i file intermedi in modo
    verificabile a macchina invece che a parole.
    """
    return StatoPaziente.model_json_schema()


# ---------------------------------------------------------------------------
# Modelli dei vocabolari chiusi (step 1)
# ---------------------------------------------------------------------------
# I vocabolari non sono lo stato paziente, ma hanno lo stesso bisogno di una
# struttura dichiarata: sono file intermedi che vanno ispezionati a mano per
# capire cosa e' stato normalizzato bene e cosa e' rimasto scoperto. Modellarli
# con Pydantic significa che il loro JSON Schema e' generato, non descritto a
# parole, e che una modifica alla struttura non passa inosservata.


class EsitoConfermaEsterna(str, Enum):
    """Esito del confronto di una voce del vocabolario con una fonte esterna."""

    CONFERMATA = "confermata"       # la fonte esterna concorda
    DISCORDANTE = "discordante"     # la fonte esterna dice altro
    NON_TROVATA = "non_trovata"     # la voce non compare nella fonte
    NON_VERIFICATA = "non_verificata"  # confronto non ancora eseguito


class OccorrenzaVoce(BaseModel):
    """Quante volte e da dove proviene una voce del vocabolario."""

    campo: str = Field(description="Campo del dataset, es. 'terapia_dimissione'.")
    occorrenze: int
    record_distinti: int


class VoceFarmaco(BaseModel):
    """Una voce del vocabolario chiuso dei farmaci.

    La forma grezza resta la chiave: e' cio' che comparira' davvero nei testi da
    processare. Tutto il resto e' annotazione, e ogni annotazione porta con se'
    la fonte che la sostiene.
    """

    forma_grezza: str = Field(description="La stringa come appare nel dataset.")
    tipo: str = Field(description="'principio_attivo' | 'nome_commerciale'.")
    occorrenze_totali: int
    occorrenze_per_campo: list[OccorrenzaVoce] = Field(default_factory=list)

    # Evidenza interna al dataset (il "ponte" dello step 0): utile, ma da sola
    # non e' una fonte autorevole.
    principio_attivo_dataset: str | None = None
    varianti_osservate: list[str] = Field(default_factory=list)

    # Evidenza esterna citabile. `atc_candidati` NON e' ancora una risoluzione:
    # e' cio' che AIFA associa alla voce, che lo step 2 dovra' disambiguare
    # (una stessa denominazione puo' avere piu' ATC per confezioni diverse).
    conferma_aifa: EsitoConfermaEsterna = EsitoConfermaEsterna.NON_VERIFICATA
    principi_attivi_aifa: list[str] = Field(default_factory=list)
    atc_candidati: list[str] = Field(default_factory=list)
    fonte: str | None = Field(default=None, description="Fonte della conferma esterna.")


class VoceCondizione(BaseModel):
    """Una voce candidata del vocabolario delle condizioni.

    A differenza dei farmaci, le condizioni non sono elencate in alcun campo
    strutturato del dataset: queste voci sono *candidate* ricavate dalla prosa e
    vanno validate contro una terminologia esterna nello step 2. Il campo
    `codice` resta quindi nullo per costruzione in questo step.
    """

    testo_grezzo: str
    occorrenze: int
    record_distinti: int
    esempi_contesto: list[str] = Field(
        default_factory=list, description="Frasi in cui la voce compare, per ispezione."
    )
    indizi_negazione: list[str] = Field(
        default_factory=list,
        description="Marcatori di negazione osservati accanto alla voce.",
    )
    codice: str | None = None
    sistema_codifica: str | None = None
    stato_normalizzazione: StatoNormalizzazione = StatoNormalizzazione.NON_TENTATO


class Vocabolario(BaseModel):
    """Contenitore di un vocabolario chiuso, con i suoi metadati di produzione."""

    nome: str
    versione_schema: str = VERSIONE_SCHEMA
    generato_il: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    dataset_sorgente: str
    fonti_esterne: list[str] = Field(default_factory=list)
    conteggi: dict[str, int] = Field(
        default_factory=dict, description="Riepilogo numerico per l'ispezione rapida."
    )
    farmaci: list[VoceFarmaco] = Field(default_factory=list)
    condizioni: list[VoceCondizione] = Field(default_factory=list)
