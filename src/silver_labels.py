"""Step 5 - Etichette silver per il NER, ricavate dalla pipeline A.

Un modello a token impara contesti e morfologia, non stringhe: puo' quindi
trovare cio' che il gazetteer non ha nel vocabolario (l'ipotesi che lo step 5
mette alla prova). Si etichettano solo i confini (CONDIZIONE, FARMACO)
nell'anamnesi; lo stato resta a ConText. Divisione per ricovero, non per
frase. Vedi docs/05_pipeline_estrazione_C.md.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
CARTELLA_PIPELINE_A = RADICE / "data" / "processed" / "pipeline_a"
CARTELLA_USCITA = RADICE / "data" / "interim" / "silver_ner"

CAMPO_ANAMNESI = "Anamnesi"
ETICHETTA_CONDIZIONE = "CONDIZIONE"
ETICHETTA_FARMACO = "FARMACO"
ETICHETTE = (ETICHETTA_CONDIZIONE, ETICHETTA_FARMACO)

# Schema BIO: B- inizio di entita', I- continuazione, O fuori. Serve a
# rappresentare entita' adiacenti dello stesso tipo senza fonderle.
ETICHETTE_BIO = ["O"] + [f"{p}-{e}" for e in ETICHETTE for p in ("B", "I")]

# Finestra del modello 512 sottotoken (~3 caratteri l'uno): 1 000 caratteri lasciano margine.
MAX_CARATTERI_SEGMENTO = 1000

PROPORZIONI = {"addestramento": 0.70, "sviluppo": 0.15, "prova": 0.15}
SEME_DIVISIONE = 20260908


@dataclass
class EntitaSilver:
    """Una menzione annotata, con gli offset relativi al testo che la contiene."""

    inizio: int
    fine: int
    etichetta: str
    testo: str


@dataclass
class Segmento:
    """Un'unita' di addestramento: un pezzo di anamnesi con le sue entita' e la posizione nel referto."""

    enc_oid: int
    inizio_nel_referto: int
    testo: str
    entita: list[EntitaSilver] = field(default_factory=list)


def carica_annotazioni(cartella: Path = CARTELLA_PIPELINE_A) -> list[tuple[int, str, list[EntitaSilver]]]:
    """Legge l'uscita della pipeline A come (enc_oid, anamnesi, entita')."""
    documenti = []
    for percorso in sorted(cartella.glob("*.json"), key=lambda p: int(p.stem)):
        stato = json.loads(percorso.read_text(encoding="utf-8"))
        testo = stato.get("testo_supporto") or ""
        if not testo.strip():
            continue

        entita: list[EntitaSilver] = []
        for voce, etichetta in (
            (stato["condizioni"], ETICHETTA_CONDIZIONE),
            (stato["farmaci"], ETICHETTA_FARMACO),
        ):
            for elemento in voce:
                provenienza = elemento["provenienza"]
                if provenienza["campo_sorgente"] != CAMPO_ANAMNESI:
                    continue
                inizio, fine = provenienza["inizio"], provenienza["fine"]
                if inizio is None or fine is None:
                    continue
                # Offset che non ritaglia il testo dichiarato: si scarta.
                if testo[inizio:fine] != provenienza["testo_originale"]:
                    continue
                entita.append(EntitaSilver(inizio, fine, etichetta, testo[inizio:fine]))

        documenti.append((stato["enc_oid"], testo, _senza_sovrapposizioni(entita)))
    return documenti


def _senza_sovrapposizioni(entita: list[EntitaSilver]) -> list[EntitaSilver]:
    """Fra menzioni sovrapposte tiene la piu' lunga (BIO non ne rappresenta due)."""
    ordinate = sorted(entita, key=lambda e: (-(e.fine - e.inizio), e.inizio))
    tenute: list[EntitaSilver] = []
    occupati: set[int] = set()
    for elemento in ordinate:
        posizioni = range(elemento.inizio, elemento.fine)
        if occupati.isdisjoint(posizioni):
            tenute.append(elemento)
            occupati.update(posizioni)
    return sorted(tenute, key=lambda e: e.inizio)


def _confini_di_frase(testo: str) -> list[int]:
    """Posizioni dopo cui si puo' tagliare senza spezzare una frase (a regole: bastano tagli sicuri)."""
    confini = []
    for indice, carattere in enumerate(testo):
        if carattere == "\n" or (
            carattere in ".;!?"
            and indice + 1 < len(testo)
            and testo[indice + 1] in " \n"
            # Un punto preceduto da una sola lettera e' quasi sempre
            # un'abbreviazione, non una fine di frase.
            and not (indice >= 1 and testo[indice - 1].isalpha() and
                     (indice < 2 or not testo[indice - 2].isalpha()))
        ):
            confini.append(indice + 1)
    return confini


def segmenta(
    enc_oid: int,
    testo: str,
    entita: list[EntitaSilver],
    massimo: int = MAX_CARATTERI_SEGMENTO,
) -> tuple[list[Segmento], int]:
    """Divide un'anamnesi in segmenti che stiano nella finestra del modello; conta le entita' perse."""
    if len(testo) <= massimo:
        tagli = [0, len(testo)]
    else:
        confini = [c for c in _confini_di_frase(testo)]
        tagli, corrente = [0], 0
        for confine in confini:
            if confine - corrente >= massimo:
                tagli.append(confine)
                corrente = confine
        # Meglio un segmento lungo che una menzione spezzata.
        if tagli[-1] != len(testo):
            tagli.append(len(testo))

    segmenti, perse = [], 0
    for inizio, fine in zip(tagli, tagli[1:]):
        frammento = testo[inizio:fine]
        if not frammento.strip():
            continue
        interne = []
        for elemento in entita:
            if elemento.inizio >= inizio and elemento.fine <= fine:
                interne.append(
                    EntitaSilver(
                        elemento.inizio - inizio,
                        elemento.fine - inizio,
                        elemento.etichetta,
                        elemento.testo,
                    )
                )
            elif elemento.inizio < fine and elemento.fine > inizio:
                perse += 1
        segmenti.append(Segmento(enc_oid, inizio, frammento, interne))
    return segmenti, perse


def dividi(identificativi: list[int], seme: int = SEME_DIVISIONE) -> dict[str, set[int]]:
    """Divide i ricoveri in addestramento / sviluppo / prova, in modo riproducibile."""
    mescolati = list(identificativi)
    random.Random(seme).shuffle(mescolati)
    totale = len(mescolati)
    n_addestramento = int(totale * PROPORZIONI["addestramento"])
    n_sviluppo = int(totale * PROPORZIONI["sviluppo"])
    return {
        "addestramento": set(mescolati[:n_addestramento]),
        "sviluppo": set(mescolati[n_addestramento : n_addestramento + n_sviluppo]),
        "prova": set(mescolati[n_addestramento + n_sviluppo :]),
    }


def main() -> None:
    documenti = carica_annotazioni()
    partizioni = dividi([enc_oid for enc_oid, _, _ in documenti])

    per_partizione: dict[str, list[Segmento]] = {nome: [] for nome in partizioni}
    perse_totali = 0
    for enc_oid, testo, entita in documenti:
        segmenti, perse = segmenta(enc_oid, testo, entita)
        perse_totali += perse
        nome = next(n for n, ids in partizioni.items() if enc_oid in ids)
        per_partizione[nome].extend(segmenti)

    CARTELLA_USCITA.mkdir(parents=True, exist_ok=True)
    print(f"{len(documenti)} referti, {perse_totali} menzioni perse nei tagli.\n")
    for nome, segmenti in per_partizione.items():
        entita = sum(len(s.entita) for s in segmenti)
        condizioni = sum(
            1 for s in segmenti for e in s.entita if e.etichetta == ETICHETTA_CONDIZIONE
        )
        (CARTELLA_USCITA / f"{nome}.json").write_text(
            json.dumps([asdict(s) for s in segmenti], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"  {nome:14s} {len(partizioni[nome]):4d} referti, {len(segmenti):5d} segmenti, "
            f"{entita:5d} entita' ({condizioni} condizioni, {entita - condizioni} farmaci)"
        )
    print(f"\nScritto in {CARTELLA_USCITA.relative_to(RADICE)}/")


if __name__ == "__main__":
    main()
