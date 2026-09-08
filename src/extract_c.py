"""Step 5 - Pipeline C: riconoscimento con NER e collegamento alla knowledge base.

COSA CAMBIA RISPETTO ALLA PIPELINE A, E COSA NO
    Cambia **solo il modo di trovare le menzioni nella prosa**: al posto del
    gazetteer sui vocabolari chiusi c'e' un modello a token addestrato sulle
    annotazioni della pipeline A (`ner_train.py`).

    Resta identico tutto il resto, e non per pigrizia ma per poter attribuire la
    differenza a una causa sola:

    * la **negazione e l'incertezza** vengono da `context_it`, le stesse regole
      della pipeline A;
    * i **farmaci dei campi semi-strutturati** vengono dallo stesso parser a
      livelli, che li interpreta al 99% e non ha nulla da guadagnare da un NER;
    * le **allergie** vengono dalla stessa sonda a regole;
    * la **codifica** passa dagli stessi risolutori su AIFA e ICD-10.

    Se anche solo uno di questi differisse, il confronto dello step 6
    misurerebbe la somma di due differenze invece del riconoscimento delle
    menzioni, che e' cio' che si vuole confrontare.

    L'unica aggiunta e' il collegamento per similarita' di `entity_linking`, che
    entra in gioco solo dove tutti i metodi esatti hanno fallito e che non
    produce mai un codice risolto: propone e basta. Serve a rendere visibile
    quali menzioni *nuove* il NER porta e quanto sono lontane dal lessico ICD.
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
from risolutori import RisolutoreATC, RisolutoreICD
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

    # ConText ragiona su frasi e distanze in token: serve lo stesso documento
    # tokenizzato usato dalla pipeline A. Gli offset di carattere del NER vanno
    # quindi riportati a indici di token.
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
        provenienza = Provenienza(
            pipeline=Pipeline.C_NER_EL,
            campo_sorgente=CAMPO_ANAMNESI,
            testo_originale=menzione.testo,
            inizio=menzione.inizio,
            fine=menzione.fine,
            regola=regola_provenienza(attributi, f"ner:{menzione.etichetta.lower()}"),
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
