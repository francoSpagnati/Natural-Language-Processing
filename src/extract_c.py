"""Step 5 - Pipeline C: riconoscimento con NER e collegamento alla knowledge base.

Rispetto alla A cambia solo il modo di trovare le menzioni nella prosa (il
modello di `ner_train.py` al posto del gazetteer); negazione, parser dei campi
di terapia, allergie e codifica sono identici, cosi' il confronto misura una
differenza sola. L'entity linking per similarita' propone e non risolve.
Vedi docs/05_pipeline_estrazione_C.md.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from context_it import attributi_per_entita, trova_ambiti
from data_loading import RecordPaziente, carica_dataset
from entity_linking import CollegatoreICD
from extract_a import (
    CAMPO_ANAMNESI,
    allergie_dal_referto,
    farmaci_da_campo_strutturato,
    regola_provenienza,
    stato_da_attributi,
)
from gazetteer import GazetteerClinico
from ner_infer import RiconoscitoreNER
from risolutori import RisolutoreATC, RisolutoreICD, soggetto_della_menzione
from schema import (
    CondizioneEstratta,
    FarmacoEstratto,
    MomentoTerapia,
    Pipeline,
    Provenienza,
    StatoNormalizzazione,
    StatoPaziente,
)
from silver_labels import ETICHETTA_CONDIZIONE, ETICHETTA_FARMACO

RADICE = Path(__file__).resolve().parent.parent
PERCORSO_DATASET = RADICE / "data" / "raw" / "anamnesiterapie.txt"
CARTELLA_USCITA = RADICE / "data" / "processed" / "pipeline_c"


def _entita_dalla_prosa(
    record: RecordPaziente,
    riconoscitore: RiconoscitoreNER,
    collegatore: CollegatoreICD,
    risolutore_atc: RisolutoreATC,
    nlp,
) -> tuple[list[CondizioneEstratta], list[FarmacoEstratto]]:
    """Menzioni riconosciute dal NER, con attributi ConText e codifica."""
    testo = record.testo_anamnesi or ""
    condizioni: list[CondizioneEstratta] = []
    farmaci: list[FarmacoEstratto] = []
    if not testo.strip():
        return condizioni, farmaci

    menzioni = riconoscitore.trova(testo)
    if not menzioni:
        return condizioni, farmaci

    # ConText ragiona in token: gli offset di carattere del NER vanno riportati a indici di token.
    documento = nlp(testo)
    ambiti = trova_ambiti(documento)

    for menzione in menzioni:
        intervallo = documento.char_span(
            menzione.inizio, menzione.fine, alignment_mode="expand"
        )
        attributi = (
            attributi_per_entita(ambiti, intervallo.start, intervallo.end)
            if intervallo is not None
            else {}
        )
        soggetto, nota_soggetto = soggetto_della_menzione(
            testo, menzione.inizio, menzione.fine
        )
        regola = regola_provenienza(attributi, f"ner:{menzione.etichetta.lower()}")
        provenienza = Provenienza(
            pipeline=Pipeline.C_NER_EL,
            campo_sorgente=CAMPO_ANAMNESI,
            testo_originale=menzione.testo,
            inizio=menzione.inizio,
            fine=menzione.fine,
            regola=f"{regola} {nota_soggetto}" if nota_soggetto else regola,
        )

        if menzione.etichetta == ETICHETTA_CONDIZIONE:
            esito = collegatore.collega(menzione.testo)
            condizioni.append(
                CondizioneEstratta(
                    testo_grezzo=menzione.testo,
                    concetto=esito.concetto,
                    codice=esito.codice,
                    sistema_codifica="ICD-10" if esito.codice else None,
                    stato_normalizzazione=esito.stato,
                    stato=stato_da_attributi(attributi),
                    soggetto=soggetto,
                    provenienza=provenienza.model_copy(
                        update={"regola": f"{provenienza.regola} icd:{esito.metodo}"}
                    ),
                )
            )
        elif menzione.etichetta == ETICHETTA_FARMACO:
            codice, stato_norm, fonte, forma = risolutore_atc.risolvi_menzione(menzione.testo)
            farmaci.append(
                FarmacoEstratto(
                    nome_grezzo=menzione.testo,
                    codice_atc=codice,
                    stato_normalizzazione=stato_norm,
                    fonte_normalizzazione=fonte,
                    momento=MomentoTerapia.NARRATIVO,
                    stato=stato_da_attributi(attributi),
                    soggetto=soggetto,
                    provenienza=provenienza.model_copy(
                        update={"regola": f"{provenienza.regola} atc:{forma}"}
                    ),
                )
            )

    return condizioni, farmaci


def estrai(
    record: RecordPaziente,
    riconoscitore: RiconoscitoreNER,
    collegatore: CollegatoreICD,
    risolutore_atc: RisolutoreATC,
    nlp,
) -> StatoPaziente:
    """Costruisce lo stato paziente usando il NER sulla prosa."""
    condizioni, farmaci_prosa = _entita_dalla_prosa(
        record, riconoscitore, collegatore, risolutore_atc, nlp
    )
    farmaci = farmaci_da_campo_strutturato(record, risolutore_atc) + farmaci_prosa
    allergie, stato_sezione = allergie_dal_referto(record)

    note: list[str] = []
    if not record.ha_terapia_dimissione:
        note.append("referto di dimissione assente: record non utilizzabile come ground truth")

    return StatoPaziente(
        enc_oid=record.enc_oid,
        pipeline=Pipeline.C_NER_EL,
        condizioni=condizioni,
        farmaci=farmaci,
        allergie=allergie,
        stato_sezione_allergie=stato_sezione,
        testo_supporto=record.testo_anamnesi,
        note_estrazione=note,
    )


def main() -> None:
    argomenti = argparse.ArgumentParser(description="Pipeline C: NER + entity linking.")
    argomenti.add_argument("--record", type=int, default=None, help="Quanti record elaborare.")
    argomenti.add_argument(
        "--solo-prova",
        action="store_true",
        help="Elabora solo la partizione di prova, quella mai vista in addestramento.",
    )
    opzioni = argomenti.parse_args()

    record, _ = carica_dataset(PERCORSO_DATASET)
    if opzioni.solo_prova:
        from silver_labels import dividi

        prova = dividi([r.enc_oid for r in record])["prova"]
        record = [r for r in record if r.enc_oid in prova]
    if opzioni.record:
        record = record[: opzioni.record]

    riconoscitore = RiconoscitoreNER()
    gazetteer = GazetteerClinico()
    collegatore = CollegatoreICD(RisolutoreICD(gazetteer=gazetteer))
    risolutore_atc = RisolutoreATC()

    CARTELLA_USCITA.mkdir(parents=True, exist_ok=True)
    print(f"Pipeline C su {len(record)} record.")

    totali = {"condizioni": 0, "farmaci": 0, "allergie": 0}
    codificate = {"icd": 0, "atc": 0, "proposte": 0}
    avvio = time.monotonic()

    for indice, rec in enumerate(record, start=1):
        try:
            stato = estrai(rec, riconoscitore, collegatore, risolutore_atc, gazetteer.nlp)
        except Exception as errore:  # noqa: BLE001 - un record non deve fermare la corsa
            print(f"  [{rec.enc_oid}] fallito: {type(errore).__name__}: {errore}", file=sys.stderr)
            continue

        (CARTELLA_USCITA / f"{rec.enc_oid}.json").write_text(
            stato.model_dump_json(indent=2), encoding="utf-8"
        )
        totali["condizioni"] += len(stato.condizioni)
        totali["farmaci"] += len(stato.farmaci)
        totali["allergie"] += len(stato.allergie)
        codificate["icd"] += sum(1 for c in stato.condizioni if c.codice)
        codificate["atc"] += sum(1 for f in stato.farmaci if f.codice_atc)
        codificate["proposte"] += sum(
            1 for c in stato.condizioni if "proposta_similarita" in (c.provenienza.regola or "")
        )
        if indice % 50 == 0 or indice == len(record):
            print(f"  {indice}/{len(record)} record ({time.monotonic() - avvio:.0f}s)", flush=True)

    durata = time.monotonic() - avvio
    print(f"\nCompletati in {durata:.0f}s ({durata / max(len(record), 1):.2f}s per record).")
    print(
        f"Condizioni {totali['condizioni']} ({codificate['icd']} con codice ICD, "
        f"{codificate['proposte']} con sola proposta per similarita'), "
        f"farmaci {totali['farmaci']} ({codificate['atc']} con ATC), "
        f"allergie {totali['allergie']}."
    )
    print(f"Uscita in {CARTELLA_USCITA.relative_to(RADICE)}/")


if __name__ == "__main__":
    main()
