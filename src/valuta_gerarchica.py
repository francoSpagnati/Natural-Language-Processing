"""Step 11 - La valutazione gerarchica: quanto costa contare tutto uguale.

Lo step 9 conta una proposta giusta o sbagliata, e basta. Un ricovero di prova
mostra perche' non basta: il ranker simbolico propone `C10AA` (statina
semplice), il medico ha prescritto `C10BA` (statina **in associazione** con
ezetimibe). **Il ranker ha proposto una statina e il medico ha prescritto una
statina, e la misura lo conta come sbagliato** — esattamente come se avesse
proposto un antibiotico.

Questo step misura quanto vale quella differenza, con tre strumenti e un
controllo.

## I tre strumenti

1. **Richiamo per livello ATC.** Si troncano proposte e bersagli allo stesso
   prefisso e si rimisura. Non richiede nessun peso arbitrario: e' la stessa
   metrica dello step 9 su un'unita' piu' grossa.

2. **Precisione e richiamo gerarchici** (`hP`, `hR`, `hF`), nella forma classica
   della classificazione gerarchica: ogni codice si espande nell'insieme dei
   suoi antenati e si misura la sovrapposizione fra gli antenati proposti e
   quelli veri. Anche qui nessun peso inventato — il peso e' la profondita'
   dell'albero, che e' un fatto della terminologia.
   Riferimento: S. Kiritchenko, S. Matwin, F. Famili, «Functional annotation of
   genes using hierarchical text categorization», BioLINK SIG 2005; ripreso in
   C. N. Silla Jr., A. A. Freitas, «A survey of hierarchical classification
   across different application domains», DMKD 22(1-2), 2011.

3. **La quota degli errori di famiglia.** Fra le proposte sbagliate nelle prime
   k, quante condividono con un bersaglio il quarto livello (`C10`) o il terzo
   (`C10B`)? E' la domanda del caso della statina, contata su tutti i ricoveri.

## Il controllo, che e' la parte che rende oneste le altre

Troncare i codici **alza il richiamo per forza**: ci sono meno classi distinte,
quindi indovinare e' piu' facile. Un numero che sale dopo il troncamento non
dimostra niente da solo.

Per questo ogni tabella porta la riga di un **ranker casuale a seme fisso**, che
subisce lo stesso effetto meccanico e nient'altro. Cio' che conta non e' quanto
sale un ranker, ma **quanto sale piu' del caso**.

## Uso

    python3 src/valuta_gerarchica.py
    python3 src/valuta_gerarchica.py --llm locale      # riusa la cache, gratis
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE / "src"))

from ranker import (  # noqa: E402
    Caso, Raccomandazione, Ranker, RankerContinuita, RankerFrequenza,
    RankerIbrido, RankerSimbolico, applica_filtro, insieme_candidato, nomi_atc,
)
from valuta_ranker import carica_casi, dividi  # noqa: E402

# I livelli dell'ATC, in caratteri di prefisso, come li definisce la
# classificazione e come li porta il registro AIFA: C / C07 / C07A / C07AB.
# Il quinto livello (7 caratteri, la sostanza) sta sotto l'unita' di questo
# progetto e non entra nel confronto.
LIVELLI: tuple[int, ...] = (1, 3, 4, 5)

NOMI_LIVELLO = {
    1: "1o - gruppo anatomico",
    3: "2o - gruppo terapeutico",
    4: "3o - gruppo farmacologico",
    5: "4o - sottogruppo chimico",
}


def antenati(codice: str) -> tuple[str, ...]:
    """Il codice e tutti i suoi antenati, dal piu' generale al piu' specifico.

    `C07AB` -> `('C', 'C07', 'C07A', 'C07AB')`. Un codice piu' corto produce
    meno antenati, e questo e' corretto: e' meno specifico davvero.
    """
    return tuple(codice[:n] for n in LIVELLI if len(codice) >= n)


def profondita_comune(a: str, b: str) -> int:
    """Quanti livelli ATC condividono due codici.

    0 = niente in comune, 4 = stesso sottogruppo chimico. E' la distanza
    dell'albero, contata in livelli invece che in archi, perche' i livelli sono
    cio' che la terminologia nomina.
    """
    comuni = 0
    for n in LIVELLI:
        if len(a) >= n and len(b) >= n and a[:n] == b[:n]:
            comuni += 1
        else:
            break
    return comuni


# ---------------------------------------------------------------------------
# Il controllo: un ranker che non sa niente
# ---------------------------------------------------------------------------

class RankerCasuale(Ranker):
    """Ordina a caso, con seme fisso.

    Non serve a competere: serve a misurare **quanto del guadagno di una metrica
    gerarchica e' meccanico**. Troncare i codici riduce il numero di classi
    distinte, quindi alza il richiamo di chiunque, anche di chi tira a sorte.
    Senza questa riga, «il richiamo sale di 7 punti salendo di un livello» non e'
    un risultato: e' aritmetica.

    Il seme e' fisso perche' due corse della stessa valutazione devono dare lo
    stesso numero, altrimenti la differenza fra due metodi si confonde con la
    differenza fra due sorteggi.
    """

    sigla = "caso"
    nome = "casuale (seme fisso)"

    def __init__(self, seme: int = 20260916) -> None:
        self._seme = seme

    def addestra(self, casi: Sequence[Caso]) -> None:
        return None

    def ordina(self, caso: Caso, candidati: Sequence[str]) -> list[Raccomandazione]:
        rng = random.Random(self._seme + caso.enc_oid)
        mescolati = list(candidati)
        rng.shuffle(mescolati)
        return [Raccomandazione(c, float(len(mescolati) - i), "sorteggio")
                for i, c in enumerate(mescolati)]


# ---------------------------------------------------------------------------
# Le tre misure
# ---------------------------------------------------------------------------

def richiamo_per_livello(ordini: dict[int, list[str]],
                         bersagli: dict[int, frozenset[str]],
                         livello: int, k: int) -> float:
    """Richiamo@k dopo aver troncato proposte e bersagli allo stesso livello.

    Macro-media sui ricoveri, come nello step 9: ogni paziente pesa uno, cosi'
    un ricovero con dieci aggiunte non domina dieci ricoveri con una.
    """
    quote = []
    for enc, veri in bersagli.items():
        if not veri:
            continue
        veri_l = {c[:livello] for c in veri}
        # Si prendono le prime k proposte PRIMA di troncare: troncare e poi
        # deduplicare regalerebbe al ranker proposte in piu' dentro la stessa k.
        proposti_l = {c[:livello] for c in ordini.get(enc, [])[:k]}
        quote.append(len(veri_l & proposti_l) / len(veri_l))
    return sum(quote) / len(quote) if quote else 0.0


def misure_gerarchiche(ordini: dict[int, list[str]],
                       bersagli: dict[int, frozenset[str]],
                       k: int) -> dict:
    """Precisione, richiamo e F gerarchici sulle prime k proposte.

    Ogni codice si espande nei suoi antenati; si misura la sovrapposizione fra
    l'insieme degli antenati proposti e quello degli antenati veri. Una proposta
    della famiglia giusta ma del sottogruppo sbagliato prende credito parziale,
    e una proposta di un altro apparato non ne prende nessuno.
    """
    hp, hr = [], []
    for enc, veri in bersagli.items():
        if not veri:
            continue
        ant_veri: set[str] = set()
        for c in veri:
            ant_veri |= set(antenati(c))
        ant_prop: set[str] = set()
        for c in ordini.get(enc, [])[:k]:
            ant_prop |= set(antenati(c))
        if not ant_prop:
            hp.append(0.0)
            hr.append(0.0)
            continue
        comuni = len(ant_veri & ant_prop)
        hp.append(comuni / len(ant_prop))
        hr.append(comuni / len(ant_veri))
    precisione = sum(hp) / len(hp) if hp else 0.0
    richiamo = sum(hr) / len(hr) if hr else 0.0
    effe = (2 * precisione * richiamo / (precisione + richiamo)
            if precisione + richiamo else 0.0)
    return {"hP": precisione, "hR": richiamo, "hF": effe}


def errori_di_famiglia(ordini: dict[int, list[str]],
                       bersagli: dict[int, frozenset[str]],
                       k: int) -> dict:
    """Fra le proposte non esatte nelle prime k, quante sbagliano di poco.

    E' il caso della statina contato su tutti i ricoveri: il ranker ha proposto
    una statina, il medico ne ha prescritta un'altra, e lo step 9 lo conta come
    un errore qualunque.
    """
    conteggio = {n: 0 for n in range(len(LIVELLI))}
    totale = 0
    for enc, veri in bersagli.items():
        if not veri:
            continue
        for proposta in ordini.get(enc, [])[:k]:
            profondita = max((profondita_comune(proposta, v) for v in veri),
                             default=0)
            if profondita == len(LIVELLI):
                continue          # esatta: non e' un errore
            conteggio[profondita] += 1
            totale += 1
    return {
        "proposte_non_esatte": totale,
        "quote": {n: (c / totale if totale else 0.0)
                  for n, c in sorted(conteggio.items())},
    }


@dataclass(frozen=True)
class Esito:
    sigla: str
    nome: str
    richiamo: dict[int, float]
    gerarchiche: dict
    famiglia: dict
    # Le proiezioni grezze restano a disposizione: il bootstrap ricampiona i
    # pazienti e rimisura, senza rieseguire il ranker.
    ordini: dict[int, list[str]]
    bersagli: dict[int, frozenset[str]]


def valuta(r: Ranker, casi: Sequence[Caso], candidati: Sequence[str],
           k: int = 5) -> Esito:
    """Misura un ranker sul compito 2, le sole aggiunte.

    Il compito 1 non e' rifatto qui: lo step 9 ha mostrato che lo vince la
    continuita' della terapia, e una metrica piu' generosa su un compito gia'
    risolto da una copia non aggiunge niente.
    """
    ordini: dict[int, list[str]] = {}
    bersagli: dict[int, frozenset[str]] = {}
    for caso in casi:
        ammessi = applica_filtro(caso, candidati)
        codici = [x.classe_atc for x in r.ordina(caso, ammessi)]
        ordini[caso.enc_oid] = [c for c in codici
                                if c not in caso.terapia_ingresso]
        bersagli[caso.enc_oid] = caso.aggiunte & set(ammessi)
    return Esito(
        r.sigla, r.nome,
        {n: richiamo_per_livello(ordini, bersagli, n, k) for n in LIVELLI},
        misure_gerarchiche(ordini, bersagli, k),
        errori_di_famiglia(ordini, bersagli, k),
        ordini, bersagli,
    )


# ---------------------------------------------------------------------------
# L'incertezza: quali differenze sopravvivono al campione
# ---------------------------------------------------------------------------

def intervallo(valori: Sequence[float], confidenza: float = 0.95) -> tuple[float, float]:
    """Percentili empirici di una distribuzione bootstrap."""
    ordinati = sorted(valori)
    coda = (1 - confidenza) / 2
    basso = ordinati[int(coda * len(ordinati))]
    alto = ordinati[min(int((1 - coda) * len(ordinati)), len(ordinati) - 1)]
    return basso, alto


def bootstrap(esiti: Sequence[Esito], k: int, giri: int = 1000,
              seme: int = 20260916,
              coppie: Sequence[tuple[str, str]] = (("ibr", "freq"),)) -> dict:
    """Ricampiona i **pazienti** con reimmissione e rimisura ogni volta.

    L'unita' di ricampionamento e' il ricovero, non la prescrizione: le
    prescrizioni dello stesso paziente non sono indipendenti fra loro, e
    trattarle come tali stringerebbe gli intervalli fino a farli mentire.

    Serve a rispondere alla domanda che tutto lo step pone: la differenza fra
    due ranker sopravvive al campione, oppure e' un accidente di quali 244
    ricoveri sono finiti nella prova? Le differenze si calcolano **dentro lo
    stesso giro**, su pazienti identici, perche' due ranker valutati sullo
    stesso campione sono correlati e sottrarre due intervalli separati
    sovrastimerebbe l'incertezza.
    """
    rng = random.Random(seme)
    enc = sorted(e for e, v in esiti[0].bersagli.items() if v)
    per_ranker: dict[str, dict[str, list[float]]] = {
        e.sigla: {"hF": [], **{f"ric{n}": [] for n in LIVELLI}} for e in esiti}
    differenze: dict[str, dict[str, list[float]]] = {}

    for _ in range(giri):
        campione = [rng.choice(enc) for _ in enc]
        # Gli indici ripetuti vanno tenuti distinti, altrimenti il
        # ricampionamento con reimmissione diventa un sottoinsieme.
        misure: dict[str, dict[str, float]] = {}
        for e in esiti:
            ordini = {i: e.ordini[x] for i, x in enumerate(campione)}
            bersagli = {i: e.bersagli[x] for i, x in enumerate(campione)}
            m = {f"ric{n}": richiamo_per_livello(ordini, bersagli, n, k)
                 for n in LIVELLI}
            m["hF"] = misure_gerarchiche(ordini, bersagli, k)["hF"]
            misure[e.sigla] = m
            for chiave, valore in m.items():
                per_ranker[e.sigla][chiave].append(valore)
        for a, b in coppie:
            if a not in misure or b not in misure:
                continue
            for chiave in ("hF", f"ric{LIVELLI[-1]}"):
                differenze.setdefault(f"{a}-{b}", {}).setdefault(
                    chiave, []).append(misure[a][chiave] - misure[b][chiave])

    return {
        "giri": giri,
        "ricoveri_ricampionati": len(enc),
        "per_ranker": {s: {c: intervallo(v) for c, v in d.items()}
                       for s, d in per_ranker.items()},
        "differenze_appaiate": {
            coppia: {c: intervallo(v) for c, v in misure.items()}
            for coppia, misure in differenze.items()},
    }


def stampa(esiti: Sequence[Esito], k: int) -> None:
    print(f"\nRICHIAMO@{k} SULLE AGGIUNTE, PER LIVELLO ATC")
    print(f"{'ranker':36}" + "".join(f"{NOMI_LIVELLO[n][:12]:>13}" for n in LIVELLI))
    for e in esiti:
        print(f"{e.nome[:35]:36}"
              + "".join(f"{e.richiamo[n]:12.1%} " for n in LIVELLI))

    casuale = next((e for e in esiti if e.sigla == "caso"), None)
    if casuale:
        print(f"\nGUADAGNO SUL CASO (punti percentuali, richiamo@{k})")
        print(f"{'ranker':36}" + "".join(f"{NOMI_LIVELLO[n][:12]:>13}" for n in LIVELLI))
        for e in esiti:
            if e.sigla == "caso":
                continue
            print(f"{e.nome[:35]:36}"
                  + "".join(f"{(e.richiamo[n] - casuale.richiamo[n]) * 100:+11.1f}  "
                            for n in LIVELLI))

    print(f"\nMETRICHE GERARCHICHE (prime {k} proposte)")
    print(f"{'ranker':36}{'hP':>9}{'hR':>9}{'hF':>9}")
    for e in esiti:
        g = e.gerarchiche
        print(f"{e.nome[:35]:36}{g['hP']:8.1%} {g['hR']:8.1%} {g['hF']:8.1%}")

    print(f"\nDOVE CADONO LE PROPOSTE NON ESATTE (prime {k})")
    print(f"{'ranker':36}{'nulla':>9}{'1o liv':>9}{'2o liv':>9}{'3o liv':>9}")
    for e in esiti:
        q = e.famiglia["quote"]
        print(f"{e.nome[:35]:36}" + "".join(f"{q[n]:8.1%} " for n in range(4)))


def main() -> None:
    import argparse

    argomenti = argparse.ArgumentParser(
        description="Step 11: la valutazione gerarchica dei ranker.")
    argomenti.add_argument("--cartella-b", type=Path,
                           default=RADICE / "data" / "processed" / "pipeline_b_v3")
    argomenti.add_argument("--uscita", type=Path,
                           default=RADICE / "data" / "processed" / "valutazione_step11.json")
    argomenti.add_argument("--k", type=int, default=5)
    argomenti.add_argument("--quota-prova", type=float, default=0.3)
    argomenti.add_argument("--llm", default=None, nargs="+",
                           choices=["locale", "openrouter"],
                           help="Aggiunge il ranker LLM riusando la cache "
                                "(gratis se la corsa dello step 9 e' gia' stata "
                                "fatta con lo stesso modello).")
    argomenti.add_argument("--modello", default=None)
    argomenti.add_argument("--bootstrap", type=int, default=1000,
                           help="Giri di bootstrap sui ricoveri (0 per saltarlo).")
    opzioni = argomenti.parse_args()

    casi = carica_casi(opzioni.cartella_b)
    addestramento, prova = dividi(casi, opzioni.quota_prova)
    candidati = insieme_candidato(addestramento)
    print(f"Casi: {len(casi)} (addestramento {len(addestramento)}, "
          f"prova {len(prova)}), {len(candidati)} classi candidate.")

    rankers: list[Ranker] = [RankerCasuale(), RankerContinuita(),
                             RankerFrequenza(), RankerSimbolico(),
                             RankerIbrido()]
    for r in rankers:
        r.addestra(addestramento)

    coppie = [("ibr", "freq")]
    if opzioni.llm:
        from llm_backend import BackendOllama, BackendOpenRouter
        from ranker import RankerLLM, nomi_icd

        for motore in opzioni.llm:
            classe = {"locale": BackendOllama,
                      "openrouter": BackendOpenRouter}[motore]
            kwargs: dict = {"ragionamento": "no"}
            if motore == "locale":
                kwargs["contesto"] = 4096
                kwargs["modello"] = opzioni.modello or "qwen3.5:4b"
            elif opzioni.modello:
                kwargs["modello"] = opzioni.modello
            backend = classe(**kwargs)
            r_llm = RankerLLM(backend, nomi_icd(), nomi_atc())
            r_llm.sigla = "llm_loc" if motore == "locale" else "llm_rem"
            r_llm.nome = f"modello linguistico ({backend.modello})"
            rankers.append(r_llm)
        sigle = {r.sigla for r in rankers}
        for a, b in (("llm_rem", "freq"), ("llm_rem", "llm_loc")):
            if a in sigle and b in sigle:
                coppie.append((a, b))

    prova = sorted(prova, key=lambda c: c.enc_oid)
    esiti = [valuta(r, prova, candidati, opzioni.k) for r in rankers]
    stampa(esiti, opzioni.k)

    incertezza = None
    if opzioni.bootstrap:
        print(f"\nBootstrap su {opzioni.bootstrap} ricampionamenti dei ricoveri...")
        incertezza = bootstrap(esiti, opzioni.k, opzioni.bootstrap,
                               coppie=coppie)
        print(f"\nINTERVALLI AL 95% (richiamo@{opzioni.k} esatto, e hF)")
        print(f"{'ranker':36}{'ric esatto':>22}{'hF':>22}")
        for e in esiti:
            i = incertezza["per_ranker"][e.sigla]
            r5 = i[f"ric{LIVELLI[-1]}"]
            hf = i["hF"]
            print(f"{e.nome[:35]:36}"
                  f"{f'[{r5[0]:.1%}, {r5[1]:.1%}]':>22}"
                  f"{f'[{hf[0]:.1%}, {hf[1]:.1%}]':>22}")
        print("\nDIFFERENZE APPAIATE (stesso campione a ogni giro)")
        for coppia, misure in incertezza["differenze_appaiate"].items():
            for chiave, (basso, alto) in misure.items():
                verdetto = ("include lo zero: NON distinguibile"
                            if basso <= 0 <= alto else "esclude lo zero")
                print(f"  {coppia:14} {chiave:6} "
                      f"[{basso:+.1%}, {alto:+.1%}] — {verdetto}")

    opzioni.uscita.parent.mkdir(parents=True, exist_ok=True)
    opzioni.uscita.write_text(json.dumps({
        "k": opzioni.k,
        "casi_di_prova": len(prova),
        "classi_candidate": len(candidati),
        "livelli": {str(n): NOMI_LIVELLO[n] for n in LIVELLI},
        "risultati": [{
            "sigla": e.sigla, "nome": e.nome,
            "richiamo_per_livello": {str(n): v for n, v in e.richiamo.items()},
            "gerarchiche": e.gerarchiche,
            "errori_di_famiglia": {
                "proposte_non_esatte": e.famiglia["proposte_non_esatte"],
                "quote": {str(n): v for n, v in e.famiglia["quote"].items()},
            },
        } for e in esiti],
        **({"incertezza": incertezza} if incertezza else {}),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nDettaglio in {opzioni.uscita}")


if __name__ == "__main__":
    main()
