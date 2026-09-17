"""Step 6 - Confronto fra le tre pipeline di estrazione.

Uno studio di accordo e complementarita', non di accuratezza (il riferimento
annotato arriva allo step 6bis). Due menzioni sono la stessa se stanno nello
stesso campo dello stesso ricovero e i loro intervalli si sovrappongono; i
gruppi cosi' formati sono i «punti di accordo». Prosa e campi strutturati sono
separati, e i farmaci che B elenca come condizioni vengono riclassificati e
contati, non scartati. Vedi docs/06_confronto_pipeline.md.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path

from risolutori import RisolutoreATC

RADICE = Path(__file__).resolve().parent.parent
CARTELLE = {"A": "pipeline_a", "B": "pipeline_b", "C": "pipeline_c"}
CAMPO_PROSA = "Anamnesi"
PIPELINE_STRUTTURATA = "campo_strutturato"


@dataclass(frozen=True)
class Menzione:
    """Una menzione estratta, ridotta a cio' che serve per confrontarla."""

    enc_oid: int
    sigla: str          # "A", "B", "C"
    tipo: str           # "condizione" | "farmaco"
    campo: str
    inizio: int
    fine: int
    testo: str
    codice: str | None
    stato: str
    soggetto: str
    strutturata: bool   # letta da un parser di campo, non riconosciuta nel testo
    # Come e' stata prodotta: `gazetteer:...`, `llm:...`, `icd:termine_esatto`.
    regola: str = ""


def _menzioni_di(stato: dict, sigla: str) -> list[Menzione]:
    fuori: list[Menzione] = []
    for tipo, elenco, chiave_testo, chiave_codice in (
        ("condizione", "condizioni", "testo_grezzo", "codice"),
        ("farmaco", "farmaci", "nome_grezzo", "codice_atc"),
    ):
        for voce in stato[elenco]:
            provenienza = voce["provenienza"]
            if provenienza["inizio"] is None:
                continue  # non ancorata: senza offset non c'e' niente da allineare
            fuori.append(
                Menzione(
                    enc_oid=stato["enc_oid"],
                    sigla=sigla,
                    tipo=tipo,
                    campo=provenienza["campo_sorgente"],
                    inizio=provenienza["inizio"],
                    fine=provenienza["fine"],
                    testo=voce[chiave_testo],
                    codice=voce[chiave_codice],
                    stato=voce["stato"],
                    soggetto=voce.get("soggetto", "paziente"),
                    strutturata=provenienza["pipeline"] == PIPELINE_STRUTTURATA,
                    regola=provenienza.get("regola", ""),
                )
            )
    return fuori


def _carica_da(cartella: Path, sigla: str,
               encs: list[str] | None = None) -> dict[int, list[Menzione]]:
    """Carica le menzioni da una cartella qualsiasi, con la sigla data."""
    percorsi = sorted(p for p in cartella.glob("*.json") if not p.stem.startswith("_"))
    if encs is not None:
        ammessi = set(encs)
        percorsi = [p for p in percorsi if p.stem in ammessi]
    fuori: dict[int, list[Menzione]] = {}
    for percorso in percorsi:
        stato = json.loads(percorso.read_text(encoding="utf-8"))
        fuori[stato["enc_oid"]] = _menzioni_di(stato, sigla)
    return fuori


def carica(sigla: str, encs: list[str] | None = None,
           radice: Path = RADICE) -> dict[int, list[Menzione]]:
    """Carica le menzioni di una pipeline, indicizzate per ricovero."""
    cartella = radice / "data" / "processed" / CARTELLE[sigla]
    percorsi = sorted(p for p in cartella.glob("*.json") if not p.stem.startswith("_"))
    if encs is not None:
        ammessi = set(encs)
        percorsi = [p for p in percorsi if p.stem in ammessi]
    fuori: dict[int, list[Menzione]] = {}
    for percorso in percorsi:
        stato = json.loads(percorso.read_text(encoding="utf-8"))
        fuori[stato["enc_oid"]] = _menzioni_di(stato, sigla)
    return fuori


# --- Ripulitura della pipeline B ---

def ripulisci(
    per_record: dict[int, list[Menzione]], risolutore: RisolutoreATC
) -> tuple[dict[int, list[Menzione]], dict[str, int]]:
    """Toglie i duplicati e sposta (contandoli) i farmaci finiti fra le condizioni."""
    conti = Counter()
    fuori: dict[int, list[Menzione]] = {}
    for enc, menzioni in per_record.items():
        viste: set[tuple] = set()
        tenute: list[Menzione] = []
        for menzione in menzioni:
            chiave = (menzione.tipo, menzione.campo, menzione.inizio, menzione.fine, menzione.testo)
            if chiave in viste:
                conti["duplicati_rimossi"] += 1
                continue
            viste.add(chiave)
            if menzione.tipo == "condizione" and risolutore.risolvi(menzione.testo)[0]:
                conti["farmaci_riclassificati"] += 1
                menzione = replace(menzione, tipo="farmaco")
            tenute.append(menzione)
        fuori[enc] = tenute
        conti["tenute"] += len(tenute)
    return fuori, dict(conti)


# --- Allineamento: le menzioni che si sovrappongono formano un gruppo ---

@dataclass(frozen=True)
class Gruppo:
    """Un punto del referto su cui una o piu' pipeline hanno trovato qualcosa."""

    enc_oid: int
    campo: str
    menzioni: tuple[Menzione, ...]

    @property
    def sigle(self) -> frozenset[str]:
        return frozenset(m.sigla for m in self.menzioni)

    @property
    def ambiguo(self) -> bool:
        """Vero se una pipeline contribuisce piu' di una menzione: il gruppo non serve a confrontare stato o codice."""
        return len(self.menzioni) > len(self.sigle)

    def una(self, sigla: str) -> Menzione | None:
        trovate = [m for m in self.menzioni if m.sigla == sigla]
        return trovate[0] if len(trovate) == 1 else None


def raggruppa(menzioni: list[Menzione]) -> list[Gruppo]:
    """Raggruppa le menzioni sovrapposte nello stesso campo (fusione di intervalli)."""
    per_campo: dict[tuple[int, str], list[Menzione]] = defaultdict(list)
    for menzione in menzioni:
        per_campo[(menzione.enc_oid, menzione.campo)].append(menzione)

    gruppi: list[Gruppo] = []
    for (enc, campo), elenco in per_campo.items():
        elenco.sort(key=lambda m: (m.inizio, m.fine))
        corrente: list[Menzione] = []
        limite = -1
        for menzione in elenco:
            if corrente and menzione.inizio >= limite:
                gruppi.append(Gruppo(enc, campo, tuple(corrente)))
                corrente = []
                limite = -1
            corrente.append(menzione)
            limite = max(limite, menzione.fine)
        if corrente:
            gruppi.append(Gruppo(enc, campo, tuple(corrente)))
    return gruppi


# --- Misure ---

def venn(gruppi: list[Gruppo]) -> Counter:
    """Quante volte ogni combinazione di pipeline ha trovato lo stesso punto."""
    return Counter("".join(sorted(g.sigle)) for g in gruppi)


def accordo(gruppi: list[Gruppo], sigla_a: str, sigla_b: str, attributo: str) -> dict:
    """Accordo fra due pipeline su un attributo, sui soli gruppi non ambigui visti da entrambe."""
    concordi = Counter()
    discordi = Counter()
    esempi: list[tuple] = []
    for gruppo in gruppi:
        if gruppo.ambiguo:
            continue
        prima, seconda = gruppo.una(sigla_a), gruppo.una(sigla_b)
        if prima is None or seconda is None:
            continue
        x, y = getattr(prima, attributo), getattr(seconda, attributo)
        if x == y:
            concordi[x] += 1
        else:
            discordi[(x, y)] += 1
            if len(esempi) < 40:
                esempi.append((gruppo.enc_oid, x, y, prima.testo, seconda.testo))
    totale = sum(concordi.values()) + sum(discordi.values())
    return {
        "confrontabili": totale,
        "concordi": sum(concordi.values()),
        "quota_accordo": sum(concordi.values()) / totale if totale else 0.0,
        "per_valore_concorde": dict(concordi),
        "per_coppia_discorde": {f"{x}|{y}": n for (x, y), n in discordi.most_common()},
        "esempi_discordi": esempi,
    }


def copertura(menzioni: list[Menzione]) -> dict:
    """Quante menzioni hanno ricevuto un codice, per tipo."""
    fuori = {}
    for tipo in ("condizione", "farmaco"):
        dello_stesso_tipo = [m for m in menzioni if m.tipo == tipo]
        con_codice = sum(1 for m in dello_stesso_tipo if m.codice)
        fuori[tipo] = {
            "menzioni": len(dello_stesso_tipo),
            "con_codice": con_codice,
            "quota": con_codice / len(dello_stesso_tipo) if dello_stesso_tipo else 0.0,
        }
    return fuori


def solo_di(gruppi: list[Gruppo], sigla: str) -> list[Menzione]:
    """Le menzioni trovate da una sola pipeline: e' li' che sta la differenza."""
    return [m for g in gruppi if g.sigle == {sigla} for m in g.menzioni]


# --- Report ---

CAMPI_STRUTTURATI = ("Terapia medica all'ingresso", "Terapia alla Dimissione")


def confronta(radice: Path = RADICE, cartella_b: Path | None = None) -> dict:
    """Il confronto completo sui record della pipeline B; `cartella_b` sceglie quale corsa di B."""
    cartella_b = cartella_b or radice / "data" / "processed" / CARTELLE["B"]
    encs = sorted(p.stem for p in cartella_b.glob("*.json") if not p.stem.startswith("_"))
    dati = {sigla: carica(sigla, encs, radice) for sigla in CARTELLE}
    if cartella_b != radice / "data" / "processed" / CARTELLE["B"]:
        dati["B"] = _carica_da(cartella_b, "B", encs)
    dati["B"], ripulitura = ripulisci(dati["B"], RisolutoreATC())

    fuori: dict = {"record": len(encs), "ripulitura_B": ripulitura, "campi": {}}

    for campo in (CAMPO_PROSA, *CAMPI_STRUTTURATI):
        menzioni = [m for sigla in CARTELLE for lista in dati[sigla].values()
                    for m in lista if m.campo == campo]
        gruppi = raggruppa(menzioni)
        misure = {
            "punti_distinti": len(gruppi),
            "gruppi_ambigui": sum(1 for g in gruppi if g.ambiguo),
            "venn": dict(venn(gruppi)),
            "solo": {s: len(solo_di(gruppi, s)) for s in CARTELLE},
        }
        if campo == CAMPO_PROSA:
            misure["accordo"] = {
                f"{a}{b}-{att}": accordo(gruppi, a, b, att)["quota_accordo"]
                for a, b in (("A", "C"), ("A", "B"), ("B", "C"))
                for att in ("stato", "soggetto", "codice")
            }
            misure["copertura"] = {
                s: copertura([m for lista in dati[s].values() for m in lista
                              if m.campo == campo])
                for s in CARTELLE
            }
        else:
            # Sui campi strutturati A e C usano lo stesso parser, che fa da
            # riferimento: la domanda e' quanto il modello ne recuperi.
            v = misure["venn"]
            trovate = v.get("ABC", 0) + v.get("AB", 0) + v.get("BC", 0)
            perse = v.get("AC", 0) + v.get("A", 0) + v.get("C", 0)
            misure["riferimento_parser"] = {
                "voci_del_parser": trovate + perse,
                "ritrovate_da_B": trovate,
                "recupero": trovate / (trovate + perse) if trovate + perse else 0.0,
                "solo_di_B": v.get("B", 0),
            }
        fuori["campi"][campo] = misure
    return fuori


def stampa(misure: dict) -> None:
    print(f"\nCONFRONTO FRA LE TRE PIPELINE — {misure['record']} record\n")
    r = misure["ripulitura_B"]
    print(f"ripulitura di B: {r.get('duplicati_rimossi', 0)} duplicati rimossi, "
          f"{r.get('farmaci_riclassificati', 0)} farmaci riclassificati da condizioni\n")

    prosa = misure["campi"][CAMPO_PROSA]
    print(f"PROSA — {prosa['punti_distinti']} punti distinti "
          f"({prosa['gruppi_ambigui']} ambigui)")
    for chiave in ("ABC", "AB", "AC", "BC", "A", "B", "C"):
        if prosa["venn"].get(chiave):
            print(f"   viste da {chiave:4} {prosa['venn'][chiave]:6}")
    print("\n   accordo sui punti condivisi:")
    for chiave, valore in prosa["accordo"].items():
        print(f"      {chiave:14} {valore:6.1%}")
    print("\n   copertura dei codici:")
    for sigla, c in prosa["copertura"].items():
        print(f"      {sigla}  condizioni {c['condizione']['menzioni']:5} "
              f"({c['condizione']['quota']:5.1%} con ICD)   "
              f"farmaci {c['farmaco']['menzioni']:5} ({c['farmaco']['quota']:5.1%} con ATC)")

    for campo in CAMPI_STRUTTURATI:
        r = misure["campi"][campo]["riferimento_parser"]
        print(f"\n{campo.upper()} — il parser deterministico fa da riferimento")
        print(f"   voci del parser {r['voci_del_parser']:5} · ritrovate da B "
              f"{r['ritrovate_da_B']:5} ({r['recupero']:.1%}) · solo di B {r['solo_di_B']}")


def main() -> None:
    argomenti = argparse.ArgumentParser(description="Confronto fra le tre pipeline.")
    argomenti.add_argument(
        "--cartella-b", type=Path, default=None,
        help="Quale corsa della pipeline B mettere sul banco.",
    )
    argomenti.add_argument(
        "--uscita", type=Path, default=RADICE / "data" / "processed" / "confronto_step6.json",
    )
    opzioni = argomenti.parse_args()
    misure = confronta(cartella_b=opzioni.cartella_b)
    stampa(misure)
    uscita = opzioni.uscita
    uscita.write_text(json.dumps(misure, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        print(f"\nMisure complete in {uscita.relative_to(RADICE)}")
    except ValueError:
        print(f"\nMisure complete in {uscita}")


if __name__ == "__main__":
    main()
