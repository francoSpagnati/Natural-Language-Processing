"""Step 5, la prova che il brief chiede prima del fine-tuning.

sez. 3.2 C: «valuta prima l'uso di modelli NER biomedici/clinici pre-addestrati
eventualmente disponibili per l'italiano». Cercato su Hugging Face il 17
settembre 2026 (ricerca «italian medical ner», filtro token-classification):
un solo modello italiano, `HUMADEX/italian_medical_ner` — BERT base cased
addestrato con supervisione debole su testo clinico tradotto, etichette
PROBLEM / TEST / TREATMENT, Apache 2.0, Sallauka et al. 2025,
doi:10.3390/app15105585. Nessun modello italiano con etichette DRUG/CONDITION
ancorate a un vocabolario.

Qui si esegue quel modello sui 25 referti del riferimento annotato (step 6bis)
e si misura con la stessa funzione delle tre pipeline: PROBLEM contro le
condizioni attese, TREATMENT contro i farmaci citati nella prosa. Non collega
a nessun codice: e' la sola parte di riconoscimento, e la domanda e' se vede
di piu' del gazetteer (richiamo 19,5%) o del NER addestrato su silver (19,9%).

Uso:  python3 src/sonda_ner_preaddestrato.py     (scarica ~430 MB la prima volta)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE / "src"))

from confronto import Menzione  # noqa: E402
from data_loading import carica_dataset  # noqa: E402
from riferimento import CAMPO, carica, valuta  # noqa: E402

MODELLO = "HUMADEX/italian_medical_ner"
TIPO = {"PROBLEM": "condizione", "TREATMENT": "farmaco"}


def main() -> None:
    from transformers import pipeline

    record, _ = carica_dataset(RADICE / "data" / "raw" / "anamnesiterapie.txt")
    anamnesi = {r.enc_oid: (r.testo_anamnesi or "") for r in record}
    rif = carica(anamnesi)
    encs = sorted({e.enc_oid for e in rif})

    ner = pipeline("token-classification", model=MODELLO,
                   aggregation_strategy="simple")
    menzioni: list[Menzione] = []
    per_etichetta: dict[str, int] = {}
    for enc in encs:
        testo = anamnesi[enc]
        # Il modello ha 512 token di contesto: si passa il testo a finestre di
        # 1 500 caratteri con gli offset riportati al testo intero.
        for inizio in range(0, len(testo), 1500):
            for ent in ner(testo[inizio:inizio + 1500]):
                per_etichetta[ent["entity_group"]] = per_etichetta.get(ent["entity_group"], 0) + 1
                tipo = TIPO.get(ent["entity_group"])
                if tipo is None:
                    continue
                menzioni.append(Menzione(
                    enc, "P", tipo, CAMPO, inizio + ent["start"], inizio + ent["end"],
                    ent["word"], None, "affermato", "paziente", False, f"ner:{MODELLO}"))

    esito = {"modello": MODELLO, "referti": len(encs), "entita_per_etichetta": per_etichetta}
    print(f"{MODELLO} sui {len(encs)} referti del riferimento: {per_etichetta}")
    for tipo in ("condizione", "farmaco"):
        r = valuta(rif, menzioni, tipo)
        esito[tipo] = {k: v for k, v in r.items() if not k.startswith("_")}
        print(f"  {tipo:11} attese {r['attese']:4}  trovate {r['trovate']:4}  "
              f"P {r['precisione']:6.1%}  R {r['richiamo']:6.1%}  F1 {r['f1']:6.1%}")
    uscita = RADICE / "data" / "processed" / "sonda_ner_preaddestrato.json"
    uscita.write_text(json.dumps(esito, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Dettaglio in {uscita}")


if __name__ == "__main__":
    main()
