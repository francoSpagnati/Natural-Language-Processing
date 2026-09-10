"""
Migrazione dello stato paziente da schema 1.0.0 a 1.1.0: aggiunge il `soggetto`.

PERCHE' UNA MIGRAZIONE E NON UNA RI-ESECUZIONE
    Le pipeline A e C si rifanno girare in pochi minuti, e infatti sono state
    rifatte. La pipeline B no: la corsa su 200 record ha richiesto quasi quindici
    ore di inferenza locale, e rieseguirla per aggiungere un campo che non viene
    dal modello sarebbe uno spreco.

PERCHE' E' LECITO
    Il `soggetto` non e' un'informazione che il modello produce: e' calcolato in
    modo deterministico da `soggetto_della_menzione` sul testo del referto e
    sugli offset gia' presenti nel file. Applicarlo dopo o durante l'estrazione
    da' per costruzione lo stesso risultato, perche' e' la stessa funzione sugli
    stessi ingressi. Il modulo di test lo verifica: la migrazione applicata alla
    vecchia uscita della pipeline A riproduce esattamente la nuova.

COSA NON TOCCA
    Nulla di quanto era gia' nel file. Aggiunge `soggetto`, appende la nota
    `experiencer:...` alla regola di provenienza quando l'ambito c'e', e alza la
    versione dello schema. Le menzioni senza offset — le citazioni che il
    modello non ha copiato alla lettera — restano `paziente`, che e' il valore
    predefinito, perche' senza posizione la regola di prossimita' non si applica.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_loading import carica_dataset
from risolutori import soggetto_della_menzione
from schema import VERSIONE_SCHEMA, Soggetto

RADICE = Path(__file__).resolve().parent.parent


def testi_per_record(percorso_dataset: Path) -> dict[int, dict[str, str]]:
    """Il testo di ogni campo di ogni ricovero, indicizzato per identificativo."""
    record, _ = carica_dataset(percorso_dataset)
    return {r.enc_oid: {ref.tipo: ref.testo for ref in r.referti} for r in record}


def migra_stato(stato: dict, campi: dict[str, str]) -> tuple[dict, int]:
    """Aggiunge il soggetto alle condizioni di un singolo stato paziente."""
    familiari = 0
    for condizione in stato.get("condizioni", []):
        provenienza = condizione["provenienza"]
        testo = campi.get(provenienza["campo_sorgente"], "")
        soggetto, nota = soggetto_della_menzione(
            testo, provenienza["inizio"], provenienza["fine"]
        )
        condizione["soggetto"] = soggetto.value
        if nota and nota not in provenienza["regola"]:
            provenienza["regola"] = f"{provenienza['regola']} {nota}"
        familiari += soggetto is Soggetto.FAMILIARE
    stato["versione_schema"] = VERSIONE_SCHEMA
    return stato, familiari


def migra_cartella(cartella: Path, campi_per_record: dict[int, dict[str, str]]) -> None:
    file_migrati = familiari = saltati = 0
    for percorso in sorted(cartella.glob("*.json")):
        if percorso.stem.startswith("_"):
            continue  # registro e riepilogo della corsa, non stati paziente
        stato = json.loads(percorso.read_text())
        campi = campi_per_record.get(stato["enc_oid"])
        if campi is None:
            saltati += 1
            continue
        stato, n = migra_stato(stato, campi)
        percorso.write_text(json.dumps(stato, ensure_ascii=False, indent=2))
        file_migrati += 1
        familiari += n
    print(f"{cartella.name}: {file_migrati} file migrati, {familiari} condizioni familiari", end="")
    print(f", {saltati} saltati (record non nel dataset)" if saltati else "")


def main() -> None:
    argomenti = argparse.ArgumentParser(description=__doc__)
    argomenti.add_argument("cartelle", nargs="+", type=Path)
    argomenti.add_argument("--dataset", type=Path,
                           default=RADICE / "data" / "raw" / "anamnesiterapie.txt")
    opzioni = argomenti.parse_args()

    campi = testi_per_record(opzioni.dataset)
    for cartella in opzioni.cartelle:
        migra_cartella(cartella, campi)


if __name__ == "__main__":
    main()
