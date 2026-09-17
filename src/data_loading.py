"""Caricamento del dataset grezzo (`anamnesiterapie.txt`, un array JSON).

Porta il file in strutture Python senza interpretare nulla. Si usa solo
l'export grezzo, mai le varianti gia' passate per un LLM. Il referto di
dimissione manca in 143 record su 1 000: e' una caratteristica del dataset,
non un'anomalia; i record malformati si raccolgono in una lista di anomalie
invece di fermare il caricamento.
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
    """Un problema riscontrato nel caricamento di un record."""

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
    """Un ricovero: `encOid` (identificativo dell'encounter, unico nel dataset) + i referti per tipo."""

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
        """True se il record ha la terapia di dimissione (puo' fare da verita' nella valutazione)."""
        return self.testo_terapia_dimissione is not None


def carica_dataset(percorso: str | Path) -> tuple[list[RecordPaziente], list[Anomalia]]:
    """Carica il dataset: (record, anomalie)."""
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
