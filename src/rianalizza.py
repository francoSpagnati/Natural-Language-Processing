"""Riesecuzione di tutte le analisi dopo una nuova corsa della pipeline B.

Rifa' in un colpo solo le misure dello step 4 e dello step 6, e se esiste una
corsa precedente archiviata le confronta: e' cosi' che si verifica se una
correzione ha funzionato. Vedi docs/04_pipeline_estrazione_B.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from data_loading import carica_dataset

RADICE = Path(__file__).resolve().parent.parent
CORRENTE = RADICE / "data" / "processed" / "pipeline_b"
ARCHIVIO = RADICE / "data" / "processed" / "pipeline_b_v1_prima_correzioni"
CORSA_CORRENTE = RADICE / "data" / "processed" / "pipeline_b_v3"
PAROLA_ALLERGIA = re.compile(r"allerg|intolleran|anafila", re.IGNORECASE)


def stati(cartella: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(cartella.glob("*.json")) if not p.stem.startswith("_")]


def misura(cartella: Path, anamnesi: dict[int, str]) -> dict:
    """Le misure che i quattro bersagli delle correzioni rendono confrontabili."""
    elenco = stati(cartella)
    if not elenco:
        return {}

    condizioni = [c for s in elenco for c in s["condizioni"]]
    farmaci = [f for s in elenco for f in s["farmaci"]]
    allergie = [a for s in elenco for a in s["allergie"]]
    tutte = condizioni + farmaci + allergie

    # Duplicati: contati dentro lo stesso record, come vuole la definizione.
    duplicati = 0
    oltre_il_tetto = 0
    for s in elenco:
        chiavi = Counter((c["provenienza"]["campo_sorgente"], c["testo_grezzo"], c["concetto"])
                         for c in s["condizioni"])
        duplicati += sum(n - 1 for n in chiavi.values() if n > 1)
        oltre_il_tetto += any(len(s[k]) > 60 for k in ("condizioni", "farmaci", "allergie"))

    # Allergie su referti che la parola "allergia" non la contengono affatto.
    allergie_inventate = record_inventati = 0
    for s in elenco:
        if s["allergie"] and not PAROLA_ALLERGIA.search(anamnesi.get(s["enc_oid"], "")):
            record_inventati += 1
            allergie_inventate += len(s["allergie"])

    def non_ancorate(voci):
        return sum(1 for v in voci if v["provenienza"]["inizio"] is None)

    return {
        "record": len(elenco),
        "condizioni": len(condizioni),
        "condizioni_per_record": len(condizioni) / len(elenco),
        "condizioni_distinte": len(condizioni) - duplicati,
        "duplicati": duplicati,
        "quota_duplicati": duplicati / len(condizioni) if condizioni else 0.0,
        "record_oltre_il_tetto": oltre_il_tetto,
        "farmaci": len(farmaci),
        "farmaci_dimissione": sum(1 for f in farmaci
                                  if f["provenienza"]["campo_sorgente"] == "Terapia alla Dimissione"),
        "allergie": len(allergie),
        "allergie_inventate": allergie_inventate,
        "record_con_allergie_inventate": record_inventati,
        "non_ancorate": non_ancorate(tutte),
        "quota_non_ancorate": non_ancorate(tutte) / len(tutte) if tutte else 0.0,
        "non_ancorate_allergie": non_ancorate(allergie),
        "quota_non_ancorate_allergie": non_ancorate(allergie) / len(allergie) if allergie else 0.0,
    }


RIGHE = [
    ("record elaborati", "record", "{:.0f}", None),
    ("condizioni per record", "condizioni_per_record", "{:.1f}", "giu"),
    ("duplicati fra le condizioni", "quota_duplicati", "{:.1%}", "giu"),
    ("record oltre il tetto di 60", "record_oltre_il_tetto", "{:.0f}", "giu"),
    ("farmaci dalla dimissione", "farmaci_dimissione", "{:.0f}", "su"),
    ("allergie estratte", "allergie", "{:.0f}", None),
    ("allergie su referti che non le nominano", "allergie_inventate", "{:.0f}", "giu"),
    ("menzioni non ancorate", "quota_non_ancorate", "{:.1%}", "giu"),
    ("allergie non ancorate", "quota_non_ancorate_allergie", "{:.1%}", "giu"),
]


def confronta_corse(prima: dict, dopo: dict) -> None:
    """Stampa le due corse affiancate, segnando dove la correzione ha funzionato."""
    print(f"\n{'':42} {'prima':>10} {'dopo':>10}   esito")
    for etichetta, chiave, formato, verso in RIGHE:
        a, b = prima.get(chiave), dopo.get(chiave)
        if a is None or b is None:
            continue
        if verso is None or a == b:
            esito = ""
        elif (b < a) == (verso == "giu"):
            esito = "migliorato"
        else:
            esito = "PEGGIORATO"
        print(f"{etichetta:42} {formato.format(a):>10} {formato.format(b):>10}   {esito}")
    print("\nLe due corse hanno insiemi di record diversi solo se una e' incompleta:")
    print("il seme di campionamento e il numero di record richiesti sono gli stessi.")
    print("Le colonne dicono 'prima' e 'dopo' ma il confronto non e' per forza")
    print("temporale: puo' affiancare due modelli diversi sugli stessi record.")


def main() -> None:
    argomenti = argparse.ArgumentParser(
        description="Rimisura una corsa della pipeline B e la affianca a un'altra."
    )
    argomenti.add_argument(
        "--corsa", type=Path, default=CORRENTE,
        help="Cartella della corsa da misurare.",
    )
    argomenti.add_argument(
        "--riferimento", type=Path, default=ARCHIVIO,
        help="Corsa con cui confrontarla. Serve a dire se una modifica ha "
             "funzionato invece di sperarlo: puo' essere una corsa precedente "
             "dello stesso modello o un modello diverso sugli stessi record.",
    )
    opzioni = argomenti.parse_args()

    record, _ = carica_dataset(RADICE / "data" / "raw" / "anamnesiterapie.txt")
    anamnesi = {r.enc_oid: (r.testo_anamnesi or "") for r in record}

    dopo = misura(opzioni.corsa, anamnesi)
    if not dopo:
        sys.exit(f"Nessun risultato in {opzioni.corsa}: la corsa non e' ancora partita.")

    print(f"CORSA {opzioni.corsa.name} — {dopo['record']} record")
    for etichetta, chiave, formato, _ in RIGHE:
        if chiave in dopo:
            print(f"  {etichetta:42} {formato.format(dopo[chiave]):>10}")

    prima = misura(opzioni.riferimento, anamnesi)
    if prima:
        print(f"\n{'=' * 74}\nCONFRONTO CON {opzioni.riferimento.name} ({prima['record']} record)")
        confronta_corse(prima, dopo)
    else:
        print(f"\n(nessuna corsa in {opzioni.riferimento.name}: niente da confrontare)")


if __name__ == "__main__":
    main()
