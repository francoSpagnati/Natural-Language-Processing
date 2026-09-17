"""Verifica il «ponte» commerciale -> principio ricavato dal dataset contro il registro AIFA.

Non costruisce il dizionario (step 2): misura quanto fidarsi del ponte.

    python3 src/verifica_ponte_aifa.py   (dopo fetch_external_kb.py)
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
PERCORSO_PONTE = RADICE / "data" / "interim" / "ponte_commerciale_principio.csv"
PERCORSO_CONFEZIONI = RADICE / "data" / "external" / "aifa" / "confezioni_fornitura.csv"

# L'anagrafica AIFA ha campi liberi molto lunghi (URL dei fogli illustrativi):
# senza alzare il limite il modulo csv solleva _csv.Error.
csv.field_size_limit(10**7)

# Token significativi: almeno 5 caratteri ("di", "acido" darebbero falsi accoppiamenti).
LUNGHEZZA_MINIMA_TOKEN = 5

# Confronto per prefisso: "Bisoprololo" contro "bisoprololo emifumarato".
LUNGHEZZA_PREFISSO = 6


def normalizza(testo: str) -> str:
    """Minuscolo, punteggiatura ridotta a spazi, spazi collassati."""
    testo = re.sub(r"[^a-z0-9/ ]", " ", testo.strip().lower())
    return re.sub(r"\s+", " ", testo).strip()


def carica_indice_aifa(percorso: Path) -> dict[str, set[str]]:
    """Indice denominazione commerciale -> principi attivi (`PA_ASSOCIATI`)."""
    indice: dict[str, set[str]] = {}
    with percorso.open(encoding="utf-8", errors="replace") as f:
        for riga in csv.DictReader(f, delimiter=";"):
            denominazione = normalizza(riga.get("DENOMINAZIONE") or "")
            principi = (riga.get("PA_ASSOCIATI") or "").strip().lower()
            if denominazione and principi:
                indice.setdefault(denominazione, set()).add(principi)
    return indice


def principio_confermato(principio_dataset: str, principi_aifa: set[str]) -> bool:
    """Ogni token significativo del principio del dataset compare per prefisso fra i principi AIFA (le associazioni danno falsi disaccordi)."""
    testo_aifa = " | ".join(sorted(principi_aifa))
    token = [t for t in re.split(r"[/ ]+", principio_dataset) if len(t) >= LUNGHEZZA_MINIMA_TOKEN]
    if not token:
        return False
    return all(t[:LUNGHEZZA_PREFISSO] in testo_aifa for t in token)


def main() -> None:
    if not PERCORSO_CONFEZIONI.exists():
        sys.exit("Manca l'anagrafica AIFA: esegui prima `python3 src/fetch_external_kb.py`.")
    if not PERCORSO_PONTE.exists():
        sys.exit("Manca il ponte: esegui prima `python3 src/explore_dataset.py`.")

    indice_aifa = carica_indice_aifa(PERCORSO_CONFEZIONI)
    print(f"Denominazioni commerciali distinte in AIFA: {len(indice_aifa)}")

    with PERCORSO_PONTE.open(encoding="utf-8") as f:
        coppie = list(csv.DictReader(f))

    confermate, discordanti, assenti = [], [], []
    for coppia in coppie:
        radice = normalizza(coppia["radice_commerciale"])
        principio = normalizza(coppia["principio_attivo_prevalente"])
        if radice not in indice_aifa:
            assenti.append(coppia)
        elif principio_confermato(principio, indice_aifa[radice]):
            confermate.append(coppia)
        else:
            discordanti.append((coppia, indice_aifa[radice]))

    totale = len(coppie)
    print(f"\nCoppie del ponte interno: {totale}")
    for etichetta, gruppo in (
        ("CONFERMATE da AIFA", confermate),
        ("DISCORDANTI", discordanti),
        ("nome commerciale non presente in AIFA", assenti),
    ):
        print(f"  {etichetta:40} {len(gruppo):4d}  ({100 * len(gruppo) / totale:5.1f}%)")

    print("\n--- discordanti (campione: quasi tutte associazioni precostituite) ---")
    for coppia, principi_aifa in discordanti[:10]:
        print(
            f"  {coppia['radice_commerciale']!r:26} "
            f"dataset={coppia['principio_attivo_prevalente']!r:44} "
            f"AIFA={' | '.join(sorted(principi_aifa))[:48]!r}"
        )


if __name__ == "__main__":
    main()
