"""
Verifica il "ponte" interno al dataset contro il registro AIFA.

CONTESTO
    Lo step 0 ha ricavato, incrociando i due campi terapia del dataset, una
    corrispondenza fra nome commerciale e principio attivo (il "ponte", in
    `data/interim/ponte_commerciale_principio.csv`). Quella corrispondenza e'
    prodotta in modo deterministico dal dataset grezzo — nessun LLM — ma resta
    pur sempre un'*osservazione locale*: dice come un certo ospedale ha
    trascritto le terapie, non cosa contiene davvero un medicinale.

    Questo script la confronta con l'anagrafica AIFA, che e' la fonte
    autorevole. Non costruisce il dizionario di normalizzazione (e' lo step 2):
    serve solo a quantificare quanto ci si possa fidare del ponte, e a rendere
    quel numero riproducibile invece che affermato.

Esecuzione (richiede prima `python3 src/fetch_external_kb.py`):
    python3 src/verifica_ponte_aifa.py
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

# Lunghezza minima di un token per essere considerato significativo nel
# confronto: sotto i 5 caratteri si tratta quasi sempre di congiunzioni o
# frammenti ("di", "e", "acido") che darebbero falsi accoppiamenti.
LUNGHEZZA_MINIMA_TOKEN = 5

# Confrontiamo solo il prefisso dei token, non la parola intera, perche' fra
# dataset e AIFA cambiano le desinenze e le forme salino:
# "Bisoprololo" vs "bisoprololo emifumarato", "Dapagliflozin" vs
# "dapagliflozin propanediolo monoidrato".
LUNGHEZZA_PREFISSO = 6


def normalizza(testo: str) -> str:
    """Minuscolo, punteggiatura ridotta a spazi, spazi collassati.

    La punteggiatura va rimossa perche' le due fonti separano diversamente le
    associazioni ("Rosuvastatina/ezetimibe" contro "rosuvastatina ezetimibe").
    """
    testo = re.sub(r"[^a-z0-9/ ]", " ", testo.strip().lower())
    return re.sub(r"\s+", " ", testo).strip()


def carica_indice_aifa(percorso: Path) -> dict[str, set[str]]:
    """Costruisce l'indice denominazione commerciale -> principi attivi.

    Il campo `PA_ASSOCIATI` elenca i principi attivi della confezione secondo
    AIFA; `DENOMINAZIONE` e' il nome commerciale senza la confezione.
    """
    indice: dict[str, set[str]] = {}
    with percorso.open(encoding="utf-8", errors="replace") as f:
        for riga in csv.DictReader(f, delimiter=";"):
            denominazione = normalizza(riga.get("DENOMINAZIONE") or "")
            principi = (riga.get("PA_ASSOCIATI") or "").strip().lower()
            if denominazione and principi:
                indice.setdefault(denominazione, set()).add(principi)
    return indice


def principio_confermato(principio_dataset: str, principi_aifa: set[str]) -> bool:
    """Il principio osservato nel dataset e' compatibile con quelli AIFA?

    Confronto volutamente indulgente: ogni token significativo del principio
    del dataset deve comparire (per prefisso) fra i principi AIFA. Cosi'
    "Bisoprololo" risulta confermato da "bisoprololo emifumarato", che e' la
    stessa sostanza in forma salina.

    Il rovescio della medaglia e' che le associazioni precostituite risultano
    spesso NON confermate: AIFA registra la confezione sotto il principio
    principale ("olmesartan medoxomil"), mentre il dataset elenca l'intera
    associazione ("Olmesartan medoxomil/amlodipina"). Sono falsi disaccordi, di
    cui va tenuto conto nel leggere il risultato.
    """
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
