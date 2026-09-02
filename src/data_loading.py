"""
Caricamento del dataset grezzo di anamnesi cardiologiche.

Questo modulo fa UNA sola cosa: portare il file `.txt` (che in realta' contiene
JSON) in strutture Python affidabili, senza interpretare clinicamente nulla.
L'interpretazione (normalizzazione farmaci, estrazione entita', ...) e' compito
degli step successivi: tenerla fuori da qui evita che un bug di parsing si
confonda con un bug di modellazione clinica.

PROVENIENZA DEL DATO (vincolo di progetto, non dettaglio implementativo)
    Il file caricato e' `anamnesiterapie.txt`, l'export **grezzo** del sistema
    ospedaliero. Nella stessa macchina esistono varianti dello stesso dataset
    con i campi gia' separati e un questionario clinico gia' codificato, ma
    sono state prodotte facendo passare i dati attraverso un LLM per filtrarli e
    strutturarli. Non sono usate: costruirci sopra la pipeline significherebbe
    ereditare un'estrazione fatta da un altro modello, che e' esattamente cio'
    che questo progetto deve invece implementare e misurare.

Scelte tecniche principali (motivate perche' non ovvie):

1. Il referto "Terapia alla Dimissione" e' **opzionale**: 143 record su 1000 ne
   sono privi. La sua assenza non e' un'anomalia ma una caratteristica del
   dataset, quindi il loader la registra come tale e non la segnala come errore.
   Serve pero' distinguerli, perche' solo i record che ce l'hanno possono fare
   da ground truth nella valutazione (sezione 4 del brief).

2. Il loader non solleva eccezioni sui record malformati: li raccoglie in una
   lista di anomalie. Su dati clinici reali serve *misurare* quanti record sono
   difettosi, non fermarsi al primo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# I tipi di referto presenti nell'export grezzo (verificati empiricamente nello
# step 0 su tutti i 1000 record).
TIPO_ANAMNESI = "Anamnesi"
TIPO_TERAPIA_INGRESSO = "Terapia medica all'ingresso"
TIPO_TERAPIA_DIMISSIONE = "Terapia alla Dimissione"

# Referti presenti in ogni record: la loro assenza sarebbe un difetto del dato.
TIPI_OBBLIGATORI = (TIPO_ANAMNESI, TIPO_TERAPIA_INGRESSO)

# Referto presente solo in parte dei record: la sua assenza e' attesa.
TIPI_OPZIONALI = (TIPO_TERAPIA_DIMISSIONE,)

TIPI_ATTESI = TIPI_OBBLIGATORI + TIPI_OPZIONALI


@dataclass
class Anomalia:
    """Un problema riscontrato durante il caricamento di un record.

    Serve a produrre un report quantitativo delle anomalie invece di far
    fallire l'intero caricamento su un singolo record difettoso.
    """

    enc_oid: int | None
    tipo_problema: str
    dettaglio: str


@dataclass
class Referto:
    """Un singolo referto (una sezione) di un ricovero."""

    tipo: str
    data: str | None
    report_oid: int | None
    testo: str


@dataclass
class RecordPaziente:
    """Un ricovero: identificativo + i suoi referti, interrogabili per tipo.

    `encOid` e' l'identificativo dell'*encounter* (ricovero), non del paziente:
    lo trattiamo come chiave primaria perche' e' l'unica disponibile e nel
    dataset risulta unico (verificato nello step 0).
    """

    enc_oid: int
    referti: list[Referto] = field(default_factory=list)

    def testo(self, tipo: str) -> str | None:
        """Restituisce il testo del referto di un dato tipo, o None se assente."""
        for referto in self.referti:
            if referto.tipo == tipo:
                return referto.testo
        return None

    @property
    def testo_anamnesi(self) -> str | None:
        return self.testo(TIPO_ANAMNESI)

    @property
    def testo_terapia_ingresso(self) -> str | None:
        return self.testo(TIPO_TERAPIA_INGRESSO)

    @property
    def testo_terapia_dimissione(self) -> str | None:
        return self.testo(TIPO_TERAPIA_DIMISSIONE)

    @property
    def ha_terapia_dimissione(self) -> bool:
        """True se il record puo' fare da ground truth nella valutazione.

        Esposto come proprieta' perche' la distinzione fra i due sottoinsiemi
        del dataset ricorre in quasi tutti gli step successivi.
        """
        return self.testo_terapia_dimissione is not None


def carica_dataset(percorso: str | Path) -> tuple[list[RecordPaziente], list[Anomalia]]:
    """Carica il dataset e restituisce la coppia (record, anomalie).

    Il file e' un unico array JSON (non JSON-per-riga), quindi lo leggiamo
    interamente in memoria: ~3,4 MB, del tutto gestibili, e questo evita la
    complessita' di un parser incrementale che qui non porterebbe vantaggi.
    """
    percorso = Path(percorso)
    anomalie: list[Anomalia] = []

    # encoding esplicito: il testo e' italiano con accenti; affidarsi al default
    # della piattaforma renderebbe il caricamento non riproducibile altrove.
    with percorso.open(encoding="utf-8") as f:
        grezzi = json.load(f)

    record: list[RecordPaziente] = []
    enc_oid_visti: set[int] = set()

    for grezzo in grezzi:
        enc_oid = grezzo.get("encOid")

        if enc_oid in enc_oid_visti:
            anomalie.append(Anomalia(enc_oid, "encOid_duplicato", "record ignorato"))
            continue
        enc_oid_visti.add(enc_oid)

        referti: list[Referto] = []
        for referto_grezzo in grezzo.get("referti", []):
            tipo = referto_grezzo.get("tipo")
            contenuto = referto_grezzo.get("testo")

            if tipo not in TIPI_ATTESI:
                anomalie.append(Anomalia(enc_oid, "tipo_referto_inatteso", repr(tipo)))

            if not isinstance(contenuto, str):
                anomalie.append(
                    Anomalia(
                        enc_oid,
                        "testo_tipo_inatteso",
                        f"tipo={tipo!r} python={type(contenuto).__name__}",
                    )
                )
                contenuto = ""
            elif not contenuto.strip():
                anomalie.append(Anomalia(enc_oid, "testo_vuoto", f"tipo={tipo!r}"))

            referti.append(
                Referto(
                    tipo=tipo,
                    data=referto_grezzo.get("data"),
                    report_oid=referto_grezzo.get("reportOid"),
                    testo=contenuto,
                )
            )

        # Solo i referti obbligatori mancanti sono un'anomalia: l'assenza della
        # terapia alla dimissione e' una caratteristica nota del dataset.
        tipi_presenti = {r.tipo for r in referti}
        for tipo_atteso in TIPI_OBBLIGATORI:
            if tipo_atteso not in tipi_presenti:
                anomalie.append(Anomalia(enc_oid, "referto_obbligatorio_mancante", tipo_atteso))

        record.append(RecordPaziente(enc_oid=enc_oid, referti=referti))

    return record, anomalie
