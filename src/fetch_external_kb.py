"""Scarica le knowledge base esterne della normalizzazione e ne registra la provenienza.

Fonte: AIFA (autorevole per l'Italia, descrizioni ATC in italiano, CC-BY 4.0);
WHO ATC/DDD e Wikidata valutate e scartate (docs/02b). Il manifest in `kb/`
(versionato) registra origine, data e impronta di ogni file.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
CARTELLA_FONTI = RADICE / "data" / "external" / "aifa"
# Il manifest sta in `kb/`, versionato, non in `data/`.
PERCORSO_MANIFEST = RADICE / "kb" / "manifest_fonti.json"

# Identificarsi e' buona educazione verso un servizio pubblico e riduce il
# rischio di essere bloccati da filtri anti-bot.
USER_AGENT = "NLP-DigitalHealth-Project/0.1 (progetto universitario)"

# Le fonti, con il ruolo di ciascuna (`serve_per` finisce nel manifest).
FONTI = [
    {
        "nome": "aifa_atc",
        "url": "https://drive.aifa.gov.it/farmaci/atc.csv",
        "file": "atc.csv",
        "serve_per": "Registro ATC con descrizioni in italiano: gerarchia completa "
                     "dei 5 livelli, base della risoluzione ATC e della metrica gerarchica.",
    },
    {
        "nome": "aifa_confezioni",
        "url": "https://drive.aifa.gov.it/farmaci/confezioni_fornitura.csv",
        "file": "confezioni_fornitura.csv",
        "serve_per": "Anagrafica delle confezioni autorizzate: lega denominazione "
                     "commerciale, principi attivi e codice ATC. E' la fonte "
                     "autorevole del dizionario nome commerciale -> principio attivo.",
    },
    {
        "nome": "aifa_principi_attivi",
        "url": "https://drive.aifa.gov.it/farmaci/PA_confezioni.csv",
        "file": "PA_confezioni.csv",
        "serve_per": "Principi attivi per codice AIC, con quantita' e unita' di "
                     "misura: disambigua le associazioni precostituite.",
    },
    {
        "nome": "aifa_classe_a_nome_commerciale",
        "url": "https://www.aifa.gov.it/documents/20142/3815901/"
               "Classe_A_per_nome_commerciale_30-04-2026.csv",
        "file": "Classe_A_per_nome_commerciale_30-04-2026.csv",
        "serve_per": "Farmaci di classe A per nome commerciale, con titolare AIC: "
                     "fonte per validare le abbreviazioni dei produttori che "
                     "compaiono nei nomi dei generici ('Atorvastatina eg').",
    },
    {
        "nome": "aifa_classe_h_nome_commerciale",
        "url": "https://www.aifa.gov.it/documents/20142/3815901/"
               "Classe_H_per_nome_commerciale_30-04-2026.csv",
        "file": "Classe_H_per_nome_commerciale_30-04-2026.csv",
        "serve_per": "Come sopra, per i farmaci di classe H (uso ospedaliero), "
                     "presenti nel dataset perche' i pazienti sono ricoverati.",
    },
]

CITAZIONE = {
    "fonte": "AIFA - Agenzia Italiana del Farmaco",
    "licenza": "CC-BY 4.0",
    "url_licenza": "https://creativecommons.org/licenses/by/4.0/deed.it",
    "pagina_open_data": "https://www.aifa.gov.it/open-data",
    "pagina_liste_farmaci": "https://www.aifa.gov.it/liste-dei-farmaci",
}


def impronta_sha256(percorso: Path) -> str:
    """SHA-256 di un file, per accorgersi nel manifest se una fonte e' cambiata."""
    digest = hashlib.sha256()
    with percorso.open("rb") as f:
        # A blocchi e non tutto in memoria: `confezioni_fornitura.csv` supera
        # i 70 MB.
        for blocco in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(blocco)
    return digest.hexdigest()


def scarica(fonte: dict, cartella: Path) -> dict:
    """Scarica una fonte e restituisce la sua voce di manifest."""
    destinazione = cartella / fonte["file"]
    richiesta = urllib.request.Request(fonte["url"], headers={"User-Agent": USER_AGENT})

    with urllib.request.urlopen(richiesta, timeout=180) as risposta:
        destinazione.write_bytes(risposta.read())

    return {
        "nome": fonte["nome"],
        "url": fonte["url"],
        "file": str(destinazione.relative_to(RADICE)),
        "serve_per": fonte["serve_per"],
        "byte": destinazione.stat().st_size,
        "sha256": impronta_sha256(destinazione),
        "scaricato_il": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main() -> None:
    CARTELLA_FONTI.mkdir(parents=True, exist_ok=True)
    PERCORSO_MANIFEST.parent.mkdir(parents=True, exist_ok=True)

    voci = []
    for fonte in FONTI:
        print(f"Scarico {fonte['nome']} ...", flush=True)
        try:
            voce = scarica(fonte, CARTELLA_FONTI)
        except Exception as errore:  # noqa: BLE001 - vogliamo continuare con le altre
            # Una fonte irraggiungibile non ferma le altre; l'esito va nel manifest.
            print(f"  FALLITO: {type(errore).__name__}: {errore}")
            voci.append({"nome": fonte["nome"], "url": fonte["url"], "errore": str(errore)})
            continue
        print(f"  ok  {voce['byte'] / 1e6:.1f} MB  sha256={voce['sha256'][:16]}...")
        voci.append(voce)

    manifest = {
        "generato_il": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "citazione": CITAZIONE,
        "fonti": voci,
    }
    PERCORSO_MANIFEST.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nManifest scritto in {PERCORSO_MANIFEST.relative_to(RADICE)}")


if __name__ == "__main__":
    main()
