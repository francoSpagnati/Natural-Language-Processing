"""Il riferimento annotato a mano (25 referti) e le misure che rende possibili.

L'unico modo di misurare il richiamo. Le annotazioni sono stringhe verbatim
(non offset): ogni occorrenza distinta e' un'entita', e il modulo si ferma se
la stringa non e' nel referto. Il confronto e' per sovrapposizione, come allo
step 6. Limiti (un solo annotatore, alla cieca): docs/06b_riferimento_annotato.md.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
CARTELLA = RADICE / "data" / "processed" / "riferimento"
CAMPO = "Anamnesi"


@dataclass(frozen=True)
class Entita:
    """Un'entita' del riferimento, risolta sugli offset del referto."""

    enc_oid: int
    tipo: str
    inizio: int
    fine: int
    testo: str
    stato: str
    soggetto: str


def _occorrenze(testo_campo: str, frammento: str) -> list[tuple[int, int]]:
    """Tutte le posizioni del frammento, ai confini di parola («TVS» non dentro «TVSostenuta»)."""
    pattern = r"(?<!\w)" + re.escape(frammento) + r"(?!\w)"
    return [(m.start(), m.end()) for m in re.finditer(pattern, testo_campo)]


def carica(anamnesi: dict[int, str], cartella: Path = CARTELLA) -> list[Entita]:
    """Risolve le annotazioni sugli offset, fermandosi su ogni incoerenza."""
    entita: list[Entita] = []
    problemi: list[str] = []
    for percorso in sorted(cartella.glob("gold_*.json")):
        blocco = json.loads(percorso.read_text(encoding="utf-8"))
        for chiave, tipi in blocco.items():
            enc = int(chiave)
            testo = anamnesi.get(enc)
            if testo is None:
                problemi.append(f"{percorso.name}: record {enc} assente dal dataset")
                continue
            for tipo, voci in tipi.items():
                for voce in voci:
                    frammento, stato, soggetto = voce[:3]
                    # Quarto elemento opzionale: quale occorrenza (da 1), per stati diversi della stessa stringa.
                    quale = voce[3] if len(voce) > 3 else None
                    trovate = _occorrenze(testo, frammento)
                    if not trovate:
                        problemi.append(
                            f"{percorso.name}: {enc} — {frammento!r} non compare nel referto"
                        )
                        continue
                    if quale is not None:
                        if quale > len(trovate):
                            problemi.append(
                                f"{percorso.name}: {enc} — {frammento!r} ha "
                                f"{len(trovate)} occorrenze, chiesta la {quale}"
                            )
                            continue
                        trovate = [trovate[quale - 1]]
                    for inizio, fine in trovate:
                        entita.append(
                            Entita(enc, tipo, inizio, fine, frammento, stato, soggetto)
                        )
    if problemi:
        raise SystemExit(
            "Il riferimento non si risolve sul testo:\n  " + "\n  ".join(problemi)
        )
    return entita


def valuta(riferimento: list[Entita], menzioni: list, tipo: str) -> dict:
    """P, R e F1 di una pipeline contro il riferimento; un'entita' e' coperta da una sola menzione."""
    atteso = [e for e in riferimento if e.tipo == tipo]
    encs = {e.enc_oid for e in riferimento}
    trovato = [m for m in menzioni
               if m.tipo == tipo and m.campo == CAMPO and m.enc_oid in encs
               and m.inizio is not None]

    per_record: dict[int, list[Entita]] = {}
    for e in atteso:
        per_record.setdefault(e.enc_oid, []).append(e)

    usate: set[int] = set()
    veri_positivi = 0
    falsi_positivi: list = []
    for m in sorted(trovato, key=lambda x: (x.enc_oid, x.inizio)):
        candidate = [
            (i, e) for i, e in enumerate(per_record.get(m.enc_oid, []))
            if id(e) not in usate and e.inizio < m.fine and m.inizio < e.fine
        ]
        if candidate:
            usate.add(id(candidate[0][1]))
            veri_positivi += 1
        else:
            falsi_positivi.append(m)

    mancate = [e for e in atteso if id(e) not in usate]
    precisione = veri_positivi / len(trovato) if trovato else 0.0
    richiamo = veri_positivi / len(atteso) if atteso else 0.0
    f1 = (2 * precisione * richiamo / (precisione + richiamo)
          if precisione + richiamo else 0.0)
    return {
        "attese": len(atteso),
        "trovate": len(trovato),
        "veri_positivi": veri_positivi,
        "falsi_positivi": len(falsi_positivi),
        "falsi_negativi": len(mancate),
        "precisione": precisione,
        "richiamo": richiamo,
        "f1": f1,
        "_mancate": mancate,
        "_falsi_positivi": falsi_positivi,
    }


def main() -> None:
    sys.path.insert(0, str(RADICE / "src"))
    from confronto import CARTELLE, _carica_da, carica as carica_menzioni, ripulisci
    from data_loading import carica_dataset
    from risolutori import RisolutoreATC

    record, _ = carica_dataset(RADICE / "data" / "raw" / "anamnesiterapie.txt")
    anamnesi = {r.enc_oid: (r.testo_anamnesi or "") for r in record}
    rif = carica(anamnesi)
    encs = sorted({str(e.enc_oid) for e in rif})
    print(f"RIFERIMENTO — {len(encs)} referti, {len(rif)} entita' annotate")
    for tipo in ("condizione", "farmaco"):
        print(f"   {tipo:12} {sum(1 for e in rif if e.tipo == tipo)}")

    cartella_b = RADICE / "data" / "processed" / "pipeline_b_deepseek_1000"
    dati = {s: carica_menzioni(s, encs) for s in ("A", "C")}
    dati["B"] = _carica_da(cartella_b, "B", encs)
    dati["B"], _ = ripulisci(dati["B"], RisolutoreATC())

    for tipo in ("condizione", "farmaco"):
        print(f"\n{tipo.upper()}")
        print(f"   {'':3} {'attese':>7} {'trovate':>8} {'VP':>5} {'FP':>5} {'FN':>5}"
              f" {'precis.':>8} {'richiamo':>9} {'F1':>7}")
        for sigla in "ABC":
            menzioni = [m for v in dati[sigla].values() for m in v]
            r = valuta(rif, menzioni, tipo)
            print(f"   {sigla:3} {r['attese']:7} {r['trovate']:8} {r['veri_positivi']:5}"
                  f" {r['falsi_positivi']:5} {r['falsi_negativi']:5}"
                  f" {r['precisione']:8.1%} {r['richiamo']:9.1%} {r['f1']:7.1%}")


if __name__ == "__main__":
    main()
