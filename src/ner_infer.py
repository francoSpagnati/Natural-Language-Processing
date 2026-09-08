"""Step 5 - Riconoscimento delle entita' con il modello addestrato.

Separato da `ner_train.py` perche' i due hanno cicli di vita diversi:
l'addestramento si esegue una volta e produce un artefatto, l'inferenza viene
importata dalla pipeline e deve restare leggera.

LA SEGMENTAZIONE DEVE ESSERE LA STESSA DELL'ADDESTRAMENTO
    Il modello ha visto segmenti tagliati ai confini di frase e lunghi al
    massimo 1.000 caratteri. Dandogli in inferenza un referto intero, tutto cio'
    che eccede la finestra verrebbe troncato in silenzio e le menzioni nella
    coda sparirebbero senza che nulla lo segnali. Si riusa quindi la stessa
    funzione `segmenta` di `silver_labels`, e gli offset vengono riportati sul
    testo completo sommando l'inizio del segmento.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import torch
from transformers import AutoModelForTokenClassification, AutoTokenizer

from ner_train import CARTELLA_MODELLO, MAX_SOTTOTOKEN, menzioni_da_bio
from silver_labels import segmenta

RADICE = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class MenzioneNER:
    """Una menzione riconosciuta, con gli offset nel testo completo."""

    inizio: int
    fine: int
    etichetta: str
    testo: str


class RiconoscitoreNER:
    """Applica il modello addestrato a un testo libero."""

    def __init__(self, cartella: Path = CARTELLA_MODELLO, dimensione_lotto: int = 8) -> None:
        if not (cartella / "config.json").exists():
            raise FileNotFoundError(
                f"Modello non trovato in {cartella}. Esegui prima: python3 src/ner_train.py"
            )
        self.tokenizzatore = AutoTokenizer.from_pretrained(cartella)
        self.modello = AutoModelForTokenClassification.from_pretrained(cartella)
        self.modello.eval()
        self.dimensione_lotto = dimensione_lotto
        self.etichette = self.modello.config.id2label

    @torch.no_grad()
    def trova(self, testo: str) -> list[MenzioneNER]:
        """Menzioni riconosciute nel testo, con offset assoluti."""
        if not testo.strip():
            return []

        segmenti, _ = segmenta(0, testo, [])
        menzioni: list[MenzioneNER] = []

        for inizio in range(0, len(segmenti), self.dimensione_lotto):
            gruppo = segmenti[inizio : inizio + self.dimensione_lotto]
            codifica = self.tokenizzatore(
                [s.testo for s in gruppo],
                truncation=True,
                max_length=MAX_SOTTOTOKEN,
                padding=True,
                return_offsets_mapping=True,
                return_tensors="pt",
            )
            offsets = codifica.pop("offset_mapping")
            scelte = self.modello(**codifica).logits.argmax(-1)

            for posizione, segmento in enumerate(gruppo):
                mappa = offsets[posizione].tolist()
                attivi = int(codifica["attention_mask"][posizione].sum())
                etichette = [
                    self.etichette[int(i)] for i in scelte[posizione][:attivi]
                ]
                for menzione in menzioni_da_bio(etichette, mappa[:attivi]):
                    assoluto_inizio = segmento.inizio_nel_referto + menzione.inizio
                    assoluto_fine = segmento.inizio_nel_referto + menzione.fine
                    frammento = testo[assoluto_inizio:assoluto_fine].strip()
                    if not frammento:
                        continue
                    # Lo strip puo' aver tolto spazi a sinistra: si riallinea
                    # l'offset perche' la provenienza resti esatta.
                    scarto = testo[assoluto_inizio:assoluto_fine].index(frammento)
                    menzioni.append(
                        MenzioneNER(
                            assoluto_inizio + scarto,
                            assoluto_inizio + scarto + len(frammento),
                            menzione.etichetta,
                            frammento,
                        )
                    )
        return menzioni
