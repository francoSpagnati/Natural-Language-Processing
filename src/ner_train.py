"""Step 5 - Addestramento del riconoscitore di entita' (pipeline C).

Modello di base `IVN-RIN/bioBIT` (BERT italiano biomedico, Buonocore et al.
2023, doi:10.1016/j.jbi.2023.104431), parametrico con `--modello-base`. Ciclo
di addestramento esplicito; etichette allineate ai sottotoken con la mappa di
offset; valutazione per entita' (inizio, fine ed etichetta), non per token.
Vedi docs/05_pipeline_estrazione_C.md.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

import torch
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForTokenClassification, AutoTokenizer

from silver_labels import CARTELLA_USCITA as CARTELLA_SILVER
from silver_labels import ETICHETTE_BIO

RADICE = Path(__file__).resolve().parent.parent
CARTELLA_MODELLO = RADICE / "data" / "processed" / "ner_it"

MODELLO_BASE_PREDEFINITO = "IVN-RIN/bioBIT"
MAX_SOTTOTOKEN = 512

INDICE_PER_ETICHETTA = {etichetta: i for i, etichetta in enumerate(ETICHETTE_BIO)}
ETICHETTA_PER_INDICE = {i: etichetta for etichetta, i in INDICE_PER_ETICHETTA.items()}

# I sottotoken speciali e quelli da ignorare nella perdita.
IGNORA = -100


@dataclass
class Menzione:
    """Una menzione come intervallo di caratteri con la sua etichetta."""

    inizio: int
    fine: int
    etichetta: str

    def chiave(self) -> tuple[int, int, str]:
        return (self.inizio, self.fine, self.etichetta)


def carica_partizione(nome: str, cartella: Path = CARTELLA_SILVER) -> list[dict]:
    return json.loads((cartella / f"{nome}.json").read_text(encoding="utf-8"))


def allinea(offsets, entita: list[dict]) -> list[int]:
    """Etichette BIO per sottotoken dagli intervalli di caratteri; i sottotoken speciali (0, 0) sono esclusi dalla perdita."""
    etichette = []
    for inizio_tok, fine_tok in offsets:
        if inizio_tok == fine_tok:  # token speciale
            etichette.append(IGNORA)
            continue
        assegnata = "O"
        for elemento in entita:
            if inizio_tok < elemento["fine"] and fine_tok > elemento["inizio"]:
                prefisso = "B" if inizio_tok <= elemento["inizio"] else "I"
                assegnata = f"{prefisso}-{elemento['etichetta']}"
                break
        etichette.append(INDICE_PER_ETICHETTA[assegnata])
    return etichette


def menzioni_da_bio(etichette: list[str], offsets) -> list[Menzione]:
    """Ricostruisce gli intervalli di caratteri da una sequenza BIO."""
    menzioni: list[Menzione] = []
    corrente = None
    for etichetta, (inizio_tok, fine_tok) in zip(etichette, offsets):
        if inizio_tok == fine_tok:
            continue
        if etichetta.startswith("B-"):
            if corrente:
                menzioni.append(corrente)
            corrente = Menzione(inizio_tok, fine_tok, etichetta[2:])
        elif etichetta.startswith("I-") and corrente and corrente.etichetta == etichetta[2:]:
            corrente.fine = fine_tok
        else:
            if corrente:
                menzioni.append(corrente)
            corrente = None
    if corrente:
        menzioni.append(corrente)
    return menzioni


class DatiSegmenti(Dataset):
    """Segmenti tokenizzati con le etichette allineate."""

    def __init__(self, segmenti: list[dict], tokenizzatore, massimo: int = MAX_SOTTOTOKEN):
        self.esempi = []
        for segmento in segmenti:
            codifica = tokenizzatore(
                segmento["testo"],
                truncation=True,
                max_length=massimo,
                return_offsets_mapping=True,
            )
            offsets = codifica.pop("offset_mapping")
            self.esempi.append(
                {
                    "input_ids": codifica["input_ids"],
                    "attention_mask": codifica["attention_mask"],
                    "labels": allinea(offsets, segmento["entita"]),
                    "offsets": offsets,
                    "segmento": segmento,
                }
            )

    def __len__(self) -> int:
        return len(self.esempi)

    def __getitem__(self, indice: int) -> dict:
        return self.esempi[indice]


def raggruppa(lotto: list[dict], id_riempimento: int) -> dict:
    """Porta gli esempi del lotto alla stessa lunghezza."""
    massimo = max(len(e["input_ids"]) for e in lotto)
    def riempi(sequenza, valore):
        return sequenza + [valore] * (massimo - len(sequenza))
    return {
        "input_ids": torch.tensor([riempi(e["input_ids"], id_riempimento) for e in lotto]),
        "attention_mask": torch.tensor([riempi(e["attention_mask"], 0) for e in lotto]),
        "labels": torch.tensor([riempi(e["labels"], IGNORA) for e in lotto]),
    }


@torch.no_grad()
def valuta(modello, dati: DatiSegmenti, id_riempimento: int, dimensione_lotto: int = 16) -> dict:
    """Precisione, richiamo e F1 per entita', globali e per etichetta."""
    modello.eval()
    attesi: dict[str, int] = {}
    predetti: dict[str, int] = {}
    corretti: dict[str, int] = {}

    for inizio in range(0, len(dati), dimensione_lotto):
        gruppo = [dati[i] for i in range(inizio, min(inizio + dimensione_lotto, len(dati)))]
        lotto = raggruppa(gruppo, id_riempimento)
        uscite = modello(input_ids=lotto["input_ids"], attention_mask=lotto["attention_mask"])
        scelte = uscite.logits.argmax(-1)

        for posizione, esempio in enumerate(gruppo):
            lunghezza = len(esempio["input_ids"])
            etichette = [ETICHETTA_PER_INDICE[int(i)] for i in scelte[posizione][:lunghezza]]
            trovate = {m.chiave() for m in menzioni_da_bio(etichette, esempio["offsets"])}
            vere = {
                (e["inizio"], e["fine"], e["etichetta"]) for e in esempio["segmento"]["entita"]
            }
            for chiave in vere:
                attesi[chiave[2]] = attesi.get(chiave[2], 0) + 1
            for chiave in trovate:
                predetti[chiave[2]] = predetti.get(chiave[2], 0) + 1
            for chiave in trovate & vere:
                corretti[chiave[2]] = corretti.get(chiave[2], 0) + 1

    def misure(c, p, a):
        precisione = c / p if p else 0.0
        richiamo = c / a if a else 0.0
        f1 = 2 * precisione * richiamo / (precisione + richiamo) if precisione + richiamo else 0.0
        return {"precisione": precisione, "richiamo": richiamo, "f1": f1, "attesi": a, "predetti": p}

    risultato = {
        etichetta: misure(corretti.get(etichetta, 0), predetti.get(etichetta, 0), attesi.get(etichetta, 0))
        for etichetta in set(attesi) | set(predetti)
    }
    risultato["complessivo"] = misure(
        sum(corretti.values()), sum(predetti.values()), sum(attesi.values())
    )
    return risultato


def stampa_misure(nome: str, misure: dict) -> None:
    complessivo = misure["complessivo"]
    print(
        f"  {nome}: F1 {complessivo['f1']:.3f} "
        f"(P {complessivo['precisione']:.3f}, R {complessivo['richiamo']:.3f}, "
        f"{complessivo['attesi']} attese)"
    )
    for etichetta, valori in sorted(misure.items()):
        if etichetta == "complessivo":
            continue
        print(
            f"      {etichetta:12s} F1 {valori['f1']:.3f}  P {valori['precisione']:.3f}  "
            f"R {valori['richiamo']:.3f}  ({valori['attesi']} attese, {valori['predetti']} predette)"
        )


def main() -> None:
    argomenti = argparse.ArgumentParser(description="Addestra il NER della pipeline C.")
    argomenti.add_argument("--modello-base", default=MODELLO_BASE_PREDEFINITO)
    argomenti.add_argument("--epoche", type=int, default=3)
    argomenti.add_argument("--lotto", type=int, default=8)
    argomenti.add_argument("--passo-apprendimento", type=float, default=3e-5)
    argomenti.add_argument("--seme", type=int, default=20260908)
    argomenti.add_argument("--uscita", type=Path, default=CARTELLA_MODELLO)
    opzioni = argomenti.parse_args()

    torch.manual_seed(opzioni.seme)
    random.seed(opzioni.seme)

    tokenizzatore = AutoTokenizer.from_pretrained(opzioni.modello_base)
    if not tokenizzatore.is_fast:
        raise SystemExit(
            "Serve un tokenizzatore veloce: l'allineamento usa la mappa di offset."
        )
    modello = AutoModelForTokenClassification.from_pretrained(
        opzioni.modello_base,
        num_labels=len(ETICHETTE_BIO),
        id2label=ETICHETTA_PER_INDICE,
        label2id=INDICE_PER_ETICHETTA,
    )

    addestramento = DatiSegmenti(carica_partizione("addestramento"), tokenizzatore)
    sviluppo = DatiSegmenti(carica_partizione("sviluppo"), tokenizzatore)
    id_riempimento = tokenizzatore.pad_token_id

    caricatore = DataLoader(
        addestramento,
        batch_size=opzioni.lotto,
        shuffle=True,
        collate_fn=lambda lotto: raggruppa(lotto, id_riempimento),
    )
    ottimizzatore = torch.optim.AdamW(modello.parameters(), lr=opzioni.passo_apprendimento)
    passi_totali = len(caricatore) * opzioni.epoche
    programma = torch.optim.lr_scheduler.OneCycleLR(
        ottimizzatore, max_lr=opzioni.passo_apprendimento, total_steps=passi_totali, pct_start=0.1
    )

    print(
        f"Modello di base: {opzioni.modello_base}\n"
        f"{len(addestramento)} segmenti di addestramento, {len(sviluppo)} di sviluppo, "
        f"{passi_totali} passi in {opzioni.epoche} epoche.\n"
    )

    migliore = -1.0
    for epoca in range(1, opzioni.epoche + 1):
        modello.train()
        perdita_totale = 0.0
        for passo, lotto in enumerate(caricatore, start=1):
            uscite = modello(**lotto)
            uscite.loss.backward()
            torch.nn.utils.clip_grad_norm_(modello.parameters(), 1.0)
            ottimizzatore.step()
            programma.step()
            ottimizzatore.zero_grad()
            perdita_totale += uscite.loss.item()
            if passo % 50 == 0:
                print(
                    f"  epoca {epoca} passo {passo}/{len(caricatore)} "
                    f"perdita {perdita_totale / passo:.4f}",
                    flush=True,
                )

        print(f"\nEpoca {epoca}: perdita media {perdita_totale / len(caricatore):.4f}")
        misure = valuta(modello, sviluppo, id_riempimento)
        stampa_misure("sviluppo", misure)

        # Si salva solo se lo sviluppo migliora: senza questo controllo si
        # conserverebbe l'ultima epoca, che non e' necessariamente la migliore.
        if misure["complessivo"]["f1"] > migliore:
            migliore = misure["complessivo"]["f1"]
            opzioni.uscita.mkdir(parents=True, exist_ok=True)
            modello.save_pretrained(opzioni.uscita)
            tokenizzatore.save_pretrained(opzioni.uscita)
            (opzioni.uscita / "misure_sviluppo.json").write_text(
                json.dumps(
                    {"epoca": epoca, "modello_base": opzioni.modello_base, "misure": misure},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"  salvato in {opzioni.uscita.relative_to(RADICE)}/ (F1 migliore finora)")
        print()

    print(f"Miglior F1 su sviluppo: {migliore:.3f}")


if __name__ == "__main__":
    main()
