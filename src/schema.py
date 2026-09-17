"""Step 1 - Schema dello stato paziente strutturato.

Il contratto dati del progetto: cio' che le tre pipeline producono e cio' che
motore e tool MCP accettano. Pydantic valida i file intermedi e genera lo JSON
Schema usato dal tool MCP. Tre stati di conoscenza (affermato / negato /
ignoto) e l'asse del soggetto: docs/01_schema_e_vocabolari.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

# Versione dello schema, riportata nei file intermedi.
VERSIONE_SCHEMA = "1.1.0"


class StatoConoscenza(str, Enum):
    """Cosa sappiamo di un'affermazione clinica. `str` per serializzare leggibile."""

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
    """Esito del collegamento a un codice; `NIL` (fuori KB) e' distinto da `NON_TENTATO`."""

    RISOLTO = "risolto"           # collegato a un identificatore standard
    NIL = "nil"                   # nessun candidato affidabile: entita' fuori KB
    AMBIGUO = "ambiguo"           # piu' candidati, nessuno prevalente
    NON_TENTATO = "non_tentato"   # normalizzazione non ancora eseguita


class Soggetto(str, Enum):
    """Di chi parla l'affermazione (asse *experiencer* di ConText), indipendente da `stato`."""

    PAZIENTE = "paziente"
    FAMILIARE = "familiare"


class Pipeline(str, Enum):
    """Quale pipeline ha prodotto l'estrazione (serve al confronto dello step 6)."""

    A_DETERMINISTICA = "A_deterministica"
    B_LLM = "B_llm"
    C_NER_EL = "C_ner_el"
    CAMPO_STRUTTURATO = "campo_strutturato"  # letto da un campo semi-strutturato


class Provenienza(BaseModel):
    """Da dove viene un'entita': campo, offset e regola (prompt o modello per B e C)."""

    pipeline: Pipeline
    campo_sorgente: str = Field(description="Referto da cui proviene, es. 'Anamnesi'.")
    testo_originale: str = Field(description="La menzione esatta, come appare nel referto.")
    # Offset assenti se l'entita' non viene dal testo libero o la pipeline non li da'.
    inizio: int | None = Field(default=None, description="Offset di inizio nel campo sorgente.")
    fine: int | None = Field(default=None, description="Offset di fine nel campo sorgente.")
    regola: str | None = Field(
        default=None,
        description="Regola, pattern, prompt o modello che ha generato l'entita'.",
    )


class FarmacoEstratto(BaseModel):
    """Un farmaco attribuito al paziente; il nome grezzo non viene mai sovrascritto."""

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
    soggetto: Soggetto = Field(
        default=Soggetto.PAZIENTE,
        description="Chi ha la condizione: il paziente o un familiare.",
    )
    provenienza: Provenienza


class AllergiaEstratta(BaseModel):
    """Un'allergia documentata; solo la categoria «principi attivi» vincola la terapia."""

    allergene: str
    categoria: str = Field(description="'principi attivi', 'alimenti', 'altro', ...")
    codice_atc: str | None = Field(
        default=None, description="ATC dell'allergene, se e' un farmaco ed e' risolto."
    )
    stato_normalizzazione: StatoNormalizzazione = StatoNormalizzazione.NON_TENTATO
    provenienza: Provenienza


class StatoPaziente(BaseModel):
    """Lo stato strutturato di un paziente: prodotto dalle pipeline, consumato da motore e MCP."""

    enc_oid: int = Field(description="Identificativo del ricovero (encounter).")
    versione_schema: str = VERSIONE_SCHEMA
    pipeline: Pipeline = Field(description="Pipeline che ha prodotto questo stato.")
    generato_il: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    condizioni: list[CondizioneEstratta] = Field(default_factory=list)
    farmaci: list[FarmacoEstratto] = Field(default_factory=list)
    allergie: list[AllergiaEstratta] = Field(default_factory=list)

    # Stato della sezione allergie: «nessuna, verificato» e' diverso da «non se ne parla».
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
        """I farmaci gia' assunti: la dimissione e' da predire, non da leggere."""
        return [f for f in self.farmaci if f.momento == MomentoTerapia.INGRESSO]

    @property
    def condizioni_affermate(self) -> list[CondizioneEstratta]:
        """Le sole condizioni affermate: quelle che generano candidati terapeutici."""
        return [c for c in self.condizioni if c.stato == StatoConoscenza.AFFERMATO]


def json_schema() -> dict:
    """Lo JSON Schema dello stato paziente (scritto in `data/interim/`)."""
    return StatoPaziente.model_json_schema()


# --- Modelli dei vocabolari chiusi (step 1) ---


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
    """Una voce del vocabolario chiuso dei farmaci: la forma grezza e' la chiave."""

    forma_grezza: str = Field(description="La stringa come appare nel dataset.")
    tipo: str = Field(description="'principio_attivo' | 'nome_commerciale'.")
    occorrenze_totali: int
    occorrenze_per_campo: list[OccorrenzaVoce] = Field(default_factory=list)

    # Evidenza interna al dataset (il «ponte» dello step 0), non autorevole da sola.
    principio_attivo_dataset: str | None = None
    varianti_osservate: list[str] = Field(default_factory=list)

    # Evidenza esterna (AIFA); `atc_candidati` va ancora disambiguato allo step 2.
    conferma_aifa: EsitoConfermaEsterna = EsitoConfermaEsterna.NON_VERIFICATA
    principi_attivi_aifa: list[str] = Field(default_factory=list)
    atc_candidati: list[str] = Field(default_factory=list)
    fonte: str | None = Field(default=None, description="Fonte della conferma esterna.")


class VoceCondizione(BaseModel):
    """Una voce candidata delle condizioni, dalla prosa; `codice` arriva allo step 2."""

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


# --- Modelli della normalizzazione ATC (step 2) ---


class MetodoRisoluzione(str, Enum):
    """Come una voce e' stata collegata a un codice ATC; registrato perche' i metodi non si equivalgono."""

    PRINCIPIO_ESATTO = "principio_esatto"
    ASSOCIAZIONE = "associazione"
    SUFFISSO_SALINO = "suffisso_salino"
    FORMA_SALINA = "forma_salina"
    COMMERCIALE_ESATTO = "commerciale_esatto"
    COMMERCIALE_ABBREVIATO = "commerciale_abbreviato"
    NON_RISOLTO = "non_risolto"


class VoceMappaturaATC(BaseModel):
    """Una voce del vocabolario con il suo esito di risoluzione ATC."""

    forma_grezza: str
    tipo: str
    occorrenze: int

    codice_atc: str | None = Field(
        default=None, description="ATC di 5o livello, se risolto senza ambiguita'."
    )
    atc_candidati: list[str] = Field(
        default_factory=list, description="Tutti i codici compatibili trovati."
    )
    descrizione_atc: str | None = None
    metodo: MetodoRisoluzione = MetodoRisoluzione.NON_RISOLTO
    stato: StatoNormalizzazione = StatoNormalizzazione.NON_TENTATO
    fonte: str | None = None
    evidenza: str | None = Field(
        default=None,
        description="La voce della fonte esterna che ha prodotto il collegamento.",
    )


class MappaturaATC(BaseModel):
    """Il risultato completo della normalizzazione ATC del vocabolario."""

    versione_schema: str = VERSIONE_SCHEMA
    generato_il: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    fonti_esterne: list[str] = Field(default_factory=list)
    conteggi: dict[str, int] = Field(default_factory=dict)
    voci: list[VoceMappaturaATC] = Field(default_factory=list)


# --- Schema di uscita della pipeline B (estrazione con LLM) ---
# Volutamente piu' povero di StatoPaziente: al modello si chiedono menzioni
# citate alla lettera (`testo_grezzo`, che serve anche come test di
# allucinazione) e il `concetto` con gli acronimi sciolti, mai i codici: la
# codifica resta ai risolutori di AIFA e ICD-10. Vedi docs/04_pipeline_estrazione_B.md.


class CampoReferto(str, Enum):
    """Campo del record da cui proviene una menzione (stessi valori di `data_loading`)."""

    ANAMNESI = "Anamnesi"
    TERAPIA_INGRESSO = "Terapia medica all'ingresso"
    TERAPIA_DIMISSIONE = "Terapia alla Dimissione"


class FarmacoLLM(BaseModel):
    """Menzione di un farmaco individuata dal modello."""

    testo_grezzo: str = Field(
        description="Il nome del farmaco copiato alla lettera dal referto, senza correzioni."
    )
    campo: CampoReferto = Field(description="Campo del referto in cui compare la menzione.")
    stato: StatoConoscenza = Field(
        description="AFFERMATO se il paziente lo assume, NEGATO se e' esplicitamente escluso, "
        "INCERTO se e' dubbio o solo ipotizzato."
    )
    posologia: str | None = Field(
        default=None, description="Dose e frequenza come scritte nel referto, se presenti."
    )


class CondizioneLLM(BaseModel):
    """Menzione di una condizione clinica individuata dal modello."""

    testo_grezzo: str = Field(
        description="La condizione copiata alla lettera dal referto, senza correzioni."
    )
    concetto: str = Field(
        description="La stessa condizione in forma estesa e distesa, in italiano, con gli "
        "acronimi sciolti (es. 'BPCO' -> 'broncopneumopatia cronica ostruttiva'). Se il "
        "referto la scrive gia' per esteso, ripeti la stessa forma."
    )
    campo: CampoReferto = Field(description="Campo del referto in cui compare la menzione.")
    stato: StatoConoscenza = Field(
        description="AFFERMATO se il paziente ne e' affetto, NEGATO se e' esplicitamente "
        "esclusa, INCERTO se e' sospetta o da confermare."
    )


class AllergiaLLM(BaseModel):
    """Allergia o intolleranza individuata dal modello."""

    allergene: str = Field(description="La sostanza, copiata alla lettera dal referto.")
    # Senza il campo, l'ancoraggio delle allergie citate da altri campi falliva.
    campo: CampoReferto = Field(description="Campo del referto da cui viene la citazione.")
    categoria: str = Field(
        description="'principi attivi', 'alimenti', 'altro' o la categoria indicata nel referto."
    )


# Tetto per array (`maxItems`): il decodificatore vincolato lo applica, il
# prompt no; senza, il modello locale non chiudeva l'array (docs/04).
MASSIMI_ELEMENTI = 60


class EstrazioneLLM(BaseModel):
    """Uscita di una chiamata di estrazione; la generazione e' vincolata a questo schema."""

    condizioni: list[CondizioneLLM] = Field(
        default_factory=list, max_length=MASSIMI_ELEMENTI
    )
    farmaci: list[FarmacoLLM] = Field(default_factory=list, max_length=MASSIMI_ELEMENTI)
    allergie: list[AllergiaLLM] = Field(
        default_factory=list, max_length=MASSIMI_ELEMENTI
    )
    stato_sezione_allergie: StatoConoscenza = Field(
        default=StatoConoscenza.IGNOTO,
        description="AFFERMATO se il referto elenca allergie, NEGATO se dichiara che non "
        "ce ne sono, IGNOTO se non se ne parla.",
    )


def schema_estrazione_llm() -> dict:
    """JSON Schema di `EstrazioneLLM` con `$defs` espansi e chiavi superflue rimosse."""
    grezzo = EstrazioneLLM.model_json_schema()
    definizioni = grezzo.pop("$defs", {})
    # Tutti `required`: altrimenti un modello piccolo omette i campi con predefinito.
    grezzo["required"] = list(grezzo["properties"])

    def espandi(nodo):
        if isinstance(nodo, list):
            return [espandi(v) for v in nodo]
        if not isinstance(nodo, dict):
            return nodo
        if "$ref" in nodo:
            nome = nodo["$ref"].rsplit("/", 1)[-1]
            unito = {**definizioni[nome], **{k: v for k, v in nodo.items() if k != "$ref"}}
            return espandi(unito)
        return {
            chiave: espandi(valore)
            for chiave, valore in nodo.items()
            if chiave not in ("default", "title")
        }

    return espandi(grezzo)
