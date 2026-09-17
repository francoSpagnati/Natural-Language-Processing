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
    pieghe,
)
from valuta_ranker import carica_casi, dividi, misura  # noqa: E402

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
    7: "5o - sostanza",
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


def proiezioni(r: Ranker, casi: Sequence[Caso], candidati: Sequence[str]
               ) -> tuple[dict[int, list[str]], dict[int, frozenset[str]]]:
    """Ordini e bersagli del compito 2 per un ranker gia' addestrato."""
    ordini: dict[int, list[str]] = {}
    bersagli: dict[int, frozenset[str]] = {}
    for caso in casi:
        ammessi = applica_filtro(caso, candidati)
        codici = [x.classe_atc for x in r.ordina(caso, ammessi)]
        ordini[caso.enc_oid] = [c for c in codici if c not in caso.terapia_ingresso]
        bersagli[caso.enc_oid] = caso.aggiunte & set(ammessi)
    return ordini, bersagli


def esito_da_proiezioni(sigla: str, nome: str, ordini, bersagli, k: int) -> Esito:
    return Esito(
        sigla, nome,
        {n: richiamo_per_livello(ordini, bersagli, n, k) for n in LIVELLI},
        misure_gerarchiche(ordini, bersagli, k),
        errori_di_famiglia(ordini, bersagli, k),
        ordini, bersagli,
    )


def valuta_incrociata(fabbriche: Sequence, casi: Sequence[Caso], quante: int,
                      k: int, stratifica: bool = False) -> list[Esito]:
    """Validazione incrociata a `quante` pieghe.

    Per ogni piega: l'insieme candidato e i ranker si costruiscono **solo**
    sulle altre, e la piega e' misurata come prova. Ogni ricovero contribuisce
    una volta sola, e nessun ranker vede mai in addestramento il paziente su cui
    viene misurato. Le proiezioni delle pieghe si concatenano e le metriche si
    calcolano sull'unione, come se fosse un'unica prova da 841 ricoveri.

    Il prezzo e' che l'insieme candidato cambia da piega a piega — e' costruito
    sull'addestramento di ciascuna — quindi il tetto non e' unico. E' corretto:
    e' il prezzo che paga qualunque sistema che debba proporre a un paziente
    nuovo classi che ha visto solo in altri pazienti.

    `fabbriche` sono funzioni senza argomenti che restituiscono un ranker
    nuovo: riaddestrare lo stesso oggetto cinque volte lascerebbe residui.
    """
    divisione = pieghe(casi, quante, stratifica=stratifica)
    accumulo: dict[str, tuple[str, dict, dict]] = {}
    for i, prova in enumerate(divisione):
        addestramento = [c for j, p in enumerate(divisione) if j != i for c in p]
        candidati = insieme_candidato(addestramento)
        for fabbrica in fabbriche:
            r = fabbrica()
            r.addestra(addestramento)
            ordini, bersagli = proiezioni(r, prova, candidati)
            nome, o, b = accumulo.setdefault(r.sigla, (r.nome, {}, {}))
            o.update(ordini)
            b.update(bersagli)
    return [esito_da_proiezioni(sigla, nome, o, b, k)
            for sigla, (nome, o, b) in accumulo.items()]


def stampa_step9(esiti: Sequence[Esito]) -> None:
    """Le metriche dello step 9 sulle stesse proiezioni: richiamo@k e MAP."""
    print("\nMETRICHE DELLO STEP 9 SULLE STESSE PROIEZIONI (aggiunte)")
    print(f"{'ranker':36}{'ric@3':>8}{'ric@5':>8}{'ric@10':>8}{'prec@5':>8}{'MAP':>8}")
    for e in esiti:
        m = misura(e.ordini, e.bersagli)
        print(f"{e.nome[:35]:36}{m['richiamo@3']:7.1%} {m['richiamo@5']:7.1%} "
              f"{m['richiamo@10']:7.1%} {m['precisione@5']:7.1%} {m['MAP']:7.3f}")


def spiegabilita(esiti: Sequence[Esito], casi: Sequence[Caso], k: int = 5,
                 simbolico: RankerSimbolico | None = None) -> dict[str, dict]:
    """Quante proposte portano una ragione citabile, e quante fra quelle centrate.

    Il ranker ibrido non e' misurabilmente migliore della frequenza sul
    richiamo (§7). Quello che lo distingue e' un'altra cosa, e va contata
    invece che affermata: per ogni proposta fra le prime k, ha almeno
    un'indicazione ESC che scatta su questo paziente? La frequenza per
    costruzione non ne ha: propone senza guardare il paziente. Si contano
    separatamente le proposte **centrate** (prescritte davvero), perche' e' li'
    che una motivazione vale: una proposta sbagliata e motivata resta sbagliata.
    """
    simbolico = simbolico or RankerSimbolico()
    per_enc = {c.enc_oid: c for c in casi}
    fuori = {}
    for e in esiti:
        proposte = motivate = centri = centri_motivati = 0
        for enc, ordine in e.ordini.items():
            caso, veri = per_enc[enc], e.bersagli.get(enc, frozenset())
            for cls in ordine[:k]:
                ha_motivo = bool(simbolico.motivazioni(caso, cls))
                proposte += 1
                motivate += ha_motivo
                if cls in veri:
                    centri += 1
                    centri_motivati += ha_motivo
        fuori[e.sigla] = {
            "proposte": proposte, "motivate": motivate,
            "quota_motivate": motivate / proposte if proposte else 0.0,
            "centri": centri, "centri_motivati": centri_motivati,
            "quota_centri_motivati": centri_motivati / centri if centri else 0.0,
        }
    return fuori


def _stampa_spiegabilita(esiti: Sequence[Esito], quote: dict[str, dict], k: int) -> None:
    print(f"\nPROPOSTE CON UN'INDICAZIONE CITABILE (prime {k})")
    print(f"{'ranker':36}{'proposte':>10}{'motivate':>10}{'centri':>9}{'motivati':>10}")
    for e in esiti:
        q = quote[e.sigla]
        print(f"{e.nome[:35]:36}{q['proposte']:>10}{q['quota_motivate']:>9.1%} "
              f"{q['centri']:>8}{q['quota_centri_motivati']:>9.1%}")


def _llm_su_tutti(casi: Sequence[Caso], opzioni) -> Esito:
    """Il ranker LLM remoto su tutti i casi, con un tetto di spesa."""
    from llm_backend import BackendOpenRouter
    from ranker import RankerLLM, nomi_icd

    if opzioni.llm != ["openrouter"]:
        raise SystemExit("con --pieghe il ranker LLM e' solo quello remoto (--llm openrouter)")
    kwargs: dict = {"ragionamento": "no"}
    if opzioni.modello:
        kwargs["modello"] = opzioni.modello
    backend = BackendOpenRouter(**kwargs)
    tetto = opzioni.tetto_dollari

    speso = {"nuovo": 0.0}    # solo le risposte pagate adesso: la cache non costa

    def rapporto(n, enc, risposta, secondi):
        if not risposta.da_cache:
            speso["nuovo"] += risposta.costo
        if n % 50 == 0 or not risposta.da_cache and n <= 3:
            print(f"  llm {n}/{len(casi)}  enc {enc}  cache={risposta.da_cache}  "
                  f"speso ora {speso['nuovo']:.4f} $ (registrato {r_llm.costo:.4f} $)")
        if speso["nuovo"] > tetto:
            raise SystemExit(f"tetto di spesa superato: {speso['nuovo']:.4f} $ > {tetto} $")

    r_llm = RankerLLM(backend, nomi_icd(), nomi_atc(), rapporto=rapporto)
    addestramento, _ = dividi(casi, opzioni.quota_prova)
    candidati = insieme_candidato(addestramento)
    tutti = sorted(casi, key=lambda c: c.enc_oid)
    if opzioni.llm_solo_cache:
        # Nessuna spesa: solo i ricoveri la cui risposta e' gia' su disco. Il
        # sottoinsieme e' deciso dall'ordine degli identificativi e dalla
        # divisione singola, non dall'esito: le differenze appaiate su di esso
        # restano lecite, e vanno dichiarate come misurate su quel sottoinsieme.
        from llm_backend import CARTELLA_CACHE, Richiesta
        from ranker import ISTRUZIONI_LLM, SCHEMA_LLM, descrivi_caso
        icd, atc = nomi_icd(), nomi_atc()

        def in_cache(c):
            r = Richiesta(istruzioni=ISTRUZIONI_LLM, schema=SCHEMA_LLM, temperatura=0.0,
                          testo=descrivi_caso(c, applica_filtro(c, candidati), icd, atc))
            return (CARTELLA_CACHE / (r.impronta(backend.modello) + ".json")).exists()
        tutti = [c for c in tutti if in_cache(c)]
    print(f"Ranker LLM ({backend.modello}) su {len(tutti)} casi, {len(candidati)} "
          f"candidati della divisione singola, tetto {tetto} $ ...")
    ordini, bersagli = proiezioni(r_llm, tutti, candidati)
    print(f"  chiamate {r_llm.chiamate}, token {r_llm.token}, costo {r_llm.costo:.4f} $, "
          f"codici scartati {r_llm.scartati}")
    e = esito_da_proiezioni("llm_rem", f"modello linguistico ({backend.modello})",
                            ordini, bersagli, opzioni.k)
    return e


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
    print(f"{'ranker':36}{'nulla':>9}" + "".join(f"{f'{n}o liv':>9}" for n in range(1, len(LIVELLI))))
    for e in esiti:
        q = e.famiglia["quote"]
        print(f"{e.nome[:35]:36}" + "".join(f"{q[n]:8.1%} " for n in range(len(LIVELLI))))


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
    argomenti.add_argument("--pieghe", type=int, default=0,
                           help="Validazione incrociata a K pieghe su tutti i casi "
                                "invece della divisione singola. Il ranker LLM e' "
                                "escluso: servirebbero chiamate nuove.")
    argomenti.add_argument("--bootstrap", type=int, default=1000,
                           help="Giri di bootstrap sui ricoveri (0 per saltarlo).")
    argomenti.add_argument("--llm-solo-cache", action="store_true",
                           help="Con --llm: misura il ranker LLM solo sui ricoveri gia' in "
                                "cache (zero spesa), e le differenze appaiate su quel "
                                "sottoinsieme.")
    argomenti.add_argument("--tetto-dollari", type=float, default=0.45,
                           help="Con --pieghe e --llm openrouter: la corsa si ferma "
                                "se la spesa supera questo tetto.")
    argomenti.add_argument("--stratifica", action="store_true",
                           help="Pieghe stratificate per condizione principale "
                                "(I50, I48, I25, I10, altro).")
    argomenti.add_argument("--sostanza", action="store_true",
                           help="Unita' = sostanza (ATC a 7 caratteri, il 5o livello "
                                "del brief) invece della classe a 5. Aggiunge il "
                                "livello 7 alla tabella.")
    opzioni = argomenti.parse_args()

    if opzioni.sostanza:
        # `classe()` legge la costante a ogni chiamata: basta cambiarla prima di
        # caricare i casi, e candidati, bersagli e proposte sono tutti a 7.
        import ranker
        ranker.LIVELLO_CLASSE = 7
        global LIVELLI
        LIVELLI = (1, 3, 4, 5, 7)
        print("Unita': la sostanza (7 caratteri).")

    casi = carica_casi(opzioni.cartella_b)

    if opzioni.pieghe:
        fabbriche = [RankerCasuale, RankerContinuita, RankerFrequenza,
                     RankerSimbolico, RankerIbrido]
        print(f"Casi: {len(casi)}, validazione incrociata a {opzioni.pieghe} "
              f"pieghe: ogni ricovero misurato una volta come prova.")
        esiti = valuta_incrociata(fabbriche, casi, opzioni.pieghe, opzioni.k,
                                  stratifica=opzioni.stratifica)
        coppie = [("ibr", "freq"), ("ibr", "simb"), ("freq", "simb")]
        esito_llm = None
        if opzioni.llm:
            # Il ranker LLM non impara dai casi: le pieghe non gli servono.
            # Si misura su TUTTI gli 841 con l'insieme candidato della divisione
            # singola, cosi' le risposte gia' pagate arrivano dalla cache. Ogni
            # ricovero e' misurato una volta, come per gli altri ranker, e le
            # differenze appaiate sono lecite.
            esito_llm = _llm_su_tutti(casi, opzioni)
            if len(esito_llm.bersagli) == len(esiti[0].bersagli):
                esiti.append(esito_llm)
                coppie += [("llm_rem", "freq"), ("llm_rem", "ibr"), ("llm_rem", "simb")]
        stampa_step9(esiti)
        stampa(esiti, opzioni.k)
        quote = spiegabilita(esiti, casi, opzioni.k)
        _stampa_spiegabilita(esiti, quote, opzioni.k)
        incertezza = None
        if opzioni.bootstrap:
            print(f"\nBootstrap su {opzioni.bootstrap} ricampionamenti dei ricoveri...")
            incertezza = bootstrap(esiti, opzioni.k, opzioni.bootstrap, coppie=coppie)
            _stampa_incertezza(esiti, incertezza, opzioni.k)
        extra = {"pieghe": opzioni.pieghe, "casi": len(casi), "spiegabilita": quote}
        if esito_llm is not None and esito_llm not in esiti:
            # L'LLM copre un sottoinsieme: tutti i ranker ristretti a quello,
            # cosi' il confronto e' appaiato sugli stessi ricoveri.
            chiavi = set(esito_llm.bersagli)
            ridotti = [esito_da_proiezioni(e.sigla, e.nome,
                                           {x: o for x, o in e.ordini.items() if x in chiavi},
                                           {x: b for x, b in e.bersagli.items() if x in chiavi},
                                           opzioni.k) for e in esiti] + [esito_llm]
            print(f"\nSOTTOINSIEME CON RISPOSTA LLM IN CACHE: {len(chiavi)} ricoveri")
            stampa_step9(ridotti)
            stampa(ridotti, opzioni.k)
            if opzioni.bootstrap:
                inc = bootstrap(ridotti, opzioni.k, opzioni.bootstrap,
                                coppie=[("llm_rem", "freq"), ("llm_rem", "ibr"),
                                        ("llm_rem", "simb"), ("ibr", "freq")])
                _stampa_incertezza(ridotti, inc, opzioni.k)
                extra["sottoinsieme_llm"] = {
                    "ricoveri": len(chiavi),
                    "risultati": {e.sigla: misura(e.ordini, e.bersagli) for e in ridotti},
                    "incertezza": inc}
        _scrivi(opzioni.uscita, esiti, opzioni.k, incertezza, extra)
        return

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
        _stampa_incertezza(esiti, incertezza, opzioni.k)
    _scrivi(opzioni.uscita, esiti, opzioni.k, incertezza,
            {"casi_di_prova": len(prova), "classi_candidate": len(candidati)})


def _stampa_incertezza(esiti: Sequence[Esito], incertezza: dict, k: int) -> None:
    print(f"\nINTERVALLI AL 95% (richiamo@{k} esatto, e hF)")
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


def _scrivi(uscita: Path, esiti: Sequence[Esito], k: int,
            incertezza: dict | None, intestazione: dict) -> None:
    uscita.parent.mkdir(parents=True, exist_ok=True)
    uscita.write_text(json.dumps({
        "k": k,
        **intestazione,
        "livelli": {str(n): NOMI_LIVELLO[n] for n in LIVELLI},
        "risultati": [{
            "sigla": e.sigla, "nome": e.nome,
            "step9": misura(e.ordini, e.bersagli),
            "richiamo_per_livello": {str(n): v for n, v in e.richiamo.items()},
            "gerarchiche": e.gerarchiche,
            "errori_di_famiglia": {
                "proposte_non_esatte": e.famiglia["proposte_non_esatte"],
                "quote": {str(n): v for n, v in e.famiglia["quote"].items()},
            },
        } for e in esiti],
        **({"incertezza": incertezza} if incertezza else {}),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nDettaglio in {uscita}")

if __name__ == "__main__":
    main()
