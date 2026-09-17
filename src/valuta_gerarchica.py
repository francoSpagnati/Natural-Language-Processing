"""Step 11 - La valutazione per livello ATC: precisione, richiamo e F1.

## Che cosa si misura

Per ogni ricovero il sistema produce una **terapia proposta**: la terapia
d'ingresso continuata, piu' le prime k classi nuove che il ranker mette in
cima. La si confronta con la **terapia di dimissione** scritta dal medico, che
e' la verita' e che nessun ranker riceve.

Il confronto si fa a ciascuno dei cinque livelli dell'ATC. Al primo livello i
codici sono troncati al gruppo anatomico (`C`), al quinto sono le sostanze
(`C07AB02`). A ogni livello, sui due insiemi troncati:

* **precisione** = quota delle proposte che il medico ha prescritto davvero;
* **richiamo** = quota delle prescrizioni che il sistema aveva proposto;
* **F1** = media armonica delle due.

Le tre cifre sono medie sui ricoveri: ogni paziente pesa uno. Salendo di
livello una statina semplice proposta dove il medico ne ha prescritta una in
associazione e' giusta fino al terzo livello (`C10A`) e sbagliata dal quarto:
la tabella per livello mostra **dove** il sistema si ferma, senza pesi
inventati. E' la metrica primaria del brief (sezione 4).

La versione **top-k** del brief e' la seconda tabella: a ogni livello, la
quota di ricoveri in cui almeno una delle k proposte nuove coincide con
un'aggiunta reale.

## Il controllo e l'incertezza

Un ranker che tira a sorte sta in tabella: salendo di livello i codici
distinti diventano pochi e chiunque migliora, quindi il guadagno vero e' la
distanza dal caso, non la cifra assoluta.

L'incertezza viene da un bootstrap sui ricoveri, con le differenze fra ranker
calcolate dentro lo stesso ricampionamento. Il rumore di fondo del progetto e'
due punti percentuali: una differenza piu' piccola non e' un risultato.
"""
from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))

import ranker as modulo_ranker  # noqa: E402
from ranker import (  # noqa: E402
    Caso, Raccomandazione, Ranker, RankerContinuita, RankerFrequenza,
    RankerIbrido, RankerSimbolico, applica_filtro, carica_casi, dividi,
    insieme_candidato, nomi_atc, pieghe,
)

# I livelli dell'ATC in caratteri di prefisso: C / C07 / C07A / C07AB / C07AB02.
LIVELLI: tuple[int, ...] = (1, 3, 4, 5, 7)

NOMI_LIVELLO = {
    1: "1o - gruppo anatomico",
    3: "2o - gruppo terapeutico",
    4: "3o - gruppo farmacologico",
    5: "4o - sottogruppo chimico",
    7: "5o - sostanza",
}


def livelli_misurabili() -> tuple[int, ...]:
    """I livelli non piu' fini dell'unita' con cui il ranker lavora.

    Con l'unita' a 5 caratteri (la classe) il quinto livello non e' misurabile:
    una proposta a 5 caratteri non puo' coincidere con una sostanza a 7.
    """
    return tuple(n for n in LIVELLI if n <= modulo_ranker.LIVELLO_CLASSE)


# ---------------------------------------------------------------------------
# Il controllo: un ranker che non sa niente
# ---------------------------------------------------------------------------

class RankerCasuale(Ranker):
    """Ordina a caso, con seme fisso.

    Non serve a competere: serve a misurare quanto del guadagno per livello e'
    meccanico. Troncare i codici riduce il numero di classi distinte, quindi
    alza chiunque, anche chi tira a sorte. Il seme e' fisso perche' due corse
    devono dare lo stesso numero.
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
# La misura
# ---------------------------------------------------------------------------

def precisione_richiamo_f1(proposti: set[str], veri: set[str]) -> tuple[float, float, float]:
    """P, R e F1 insiemistici fra due insiemi di codici gia' troncati."""
    if not proposti or not veri:
        return (0.0, 0.0, 0.0)
    comuni = len(proposti & veri)
    p, r = comuni / len(proposti), comuni / len(veri)
    return (p, r, 2 * p * r / (p + r) if p + r else 0.0)


def terapia_proposta(caso: Caso, ordine: Sequence[str], k: int) -> set[str]:
    """Cio' che il sistema mostra: l'ingresso continuato piu' le prime k nuove."""
    return set(caso.terapia_ingresso) | set(ordine[:k])


def misure_per_livello(ordini: dict[int, list[str]], casi: dict[int, Caso],
                       k: int) -> dict[int, dict[str, float]]:
    """P, R e F1 medi sui ricoveri, per ogni livello ATC misurabile.

    `ordini[enc]` sono le classi nuove nell'ordine del ranker (l'ingresso e'
    gia' escluso); il taglio a k avviene **prima** del troncamento, altrimenti
    troncare e deduplicare regalerebbe proposte in piu' dentro la stessa k.
    """
    fuori: dict[int, dict[str, float]] = {}
    for n in livelli_misurabili():
        somme = [0.0, 0.0, 0.0]
        for enc, caso in casi.items():
            proposti = {c[:n] for c in terapia_proposta(caso, ordini.get(enc, []), k)}
            veri = {c[:n] for c in caso.dimissione}
            for i, v in enumerate(precisione_richiamo_f1(proposti, veri)):
                somme[i] += v
        quanti = len(casi) or 1
        fuori[n] = {"P": somme[0] / quanti, "R": somme[1] / quanti, "F1": somme[2] / quanti}
    return fuori


def top_k_per_livello(ordini: dict[int, list[str]], casi: dict[int, Caso],
                      k: int) -> dict[int, float]:
    """Quota dei ricoveri con almeno un'aggiunta reale fra le k proposte nuove.

    Si contano solo i ricoveri che hanno aggiunto qualcosa: dove il medico non
    ha aggiunto niente non c'e' nulla da centrare.
    """
    fuori: dict[int, float] = {}
    # La chiave del dizionario, non `caso.enc_oid`: il bootstrap ricampiona
    # con reimmissione e rinumera i ricoveri, e lo stesso paziente deve poter
    # comparire due volte.
    con_aggiunte = [(enc, c) for enc, c in casi.items() if c.aggiunte]
    for n in livelli_misurabili():
        centrati = 0
        for enc, caso in con_aggiunte:
            proposti = {c[:n] for c in ordini.get(enc, [])[:k]}
            if proposti & {c[:n] for c in caso.aggiunte}:
                centrati += 1
        fuori[n] = centrati / len(con_aggiunte) if con_aggiunte else 0.0
    return fuori


@dataclass(frozen=True)
class Esito:
    sigla: str
    nome: str
    per_livello: dict[int, dict[str, float]]
    top_k: dict[int, float]
    # Le proiezioni grezze restano: il bootstrap ricampiona i pazienti e
    # rimisura, senza rieseguire il ranker.
    ordini: dict[int, list[str]]
    casi: dict[int, Caso]


def esito_da_proiezioni(sigla: str, nome: str, ordini: dict[int, list[str]],
                        casi: dict[int, Caso], k: int) -> Esito:
    return Esito(sigla, nome, misure_per_livello(ordini, casi, k),
                 top_k_per_livello(ordini, casi, k), ordini, casi)


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
    """Ricampiona i **ricoveri** con reimmissione e rimisura F1 a ogni livello.

    L'unita' e' il ricovero, non la prescrizione: le prescrizioni dello stesso
    paziente non sono indipendenti, e trattarle come tali stringerebbe gli
    intervalli fino a farli mentire. Le differenze fra due ranker si calcolano
    dentro lo stesso giro, su pazienti identici, perche' due ranker misurati
    sullo stesso campione sono correlati.
    """
    rng = random.Random(seme)
    enc = sorted(esiti[0].casi)
    livelli = livelli_misurabili()
    per_ranker: dict[str, dict[int, list[float]]] = {
        e.sigla: {n: [] for n in livelli} for e in esiti}
    differenze: dict[str, dict[int, list[float]]] = {}
    differenze_top_k: dict[str, dict[int, list[float]]] = {}

    for _ in range(giri):
        campione = [rng.choice(enc) for _ in enc]
        # Gli indici ripetuti vanno tenuti distinti, altrimenti il
        # ricampionamento con reimmissione diventa un sottoinsieme.
        effe: dict[str, dict[int, float]] = {}
        top: dict[str, dict[int, float]] = {}
        for e in esiti:
            ordini = {i: e.ordini.get(x, []) for i, x in enumerate(campione)}
            casi = {i: e.casi[x] for i, x in enumerate(campione)}
            effe[e.sigla] = {n: m["F1"] for n, m in misure_per_livello(ordini, casi, k).items()}
            top[e.sigla] = top_k_per_livello(ordini, casi, k)
            for n, v in effe[e.sigla].items():
                per_ranker[e.sigla][n].append(v)
        for a, b in coppie:
            if a not in effe or b not in effe:
                continue
            for n in livelli:
                differenze.setdefault(f"{a}-{b}", {}).setdefault(n, []).append(
                    effe[a][n] - effe[b][n])
                differenze_top_k.setdefault(f"{a}-{b}", {}).setdefault(n, []).append(
                    top[a][n] - top[b][n])

    return {
        "giri": giri,
        "ricoveri_ricampionati": len(enc),
        "per_ranker": {s: {n: intervallo(v) for n, v in d.items()}
                       for s, d in per_ranker.items()},
        "differenze_appaiate": {
            coppia: {n: intervallo(v) for n, v in d.items()}
            for coppia, d in differenze.items()},
        "differenze_top_k": {
            coppia: {n: intervallo(v) for n, v in d.items()}
            for coppia, d in differenze_top_k.items()},
    }


# ---------------------------------------------------------------------------
# La validazione incrociata
# ---------------------------------------------------------------------------

def proiezioni(r: Ranker, casi: Sequence[Caso], candidati: Sequence[str]
               ) -> dict[int, list[str]]:
    """Le classi nuove che un ranker gia' addestrato propone, per ricovero."""
    ordini: dict[int, list[str]] = {}
    for caso in casi:
        ammessi = applica_filtro(caso, candidati)
        codici = [x.classe_atc for x in r.ordina(caso, ammessi)]
        ordini[caso.enc_oid] = [c for c in codici if c not in caso.terapia_ingresso]
    return ordini


def valuta_incrociata(fabbriche: Sequence, casi: Sequence[Caso], quante: int,
                      k: int, stratifica: bool = False) -> list[Esito]:
    """Validazione incrociata a `quante` pieghe.

    Per ogni piega l'insieme candidato e i ranker si costruiscono solo sulle
    altre, e la piega e' misurata come prova. Ogni ricovero contribuisce una
    volta sola e nessun ranker vede in addestramento il paziente su cui viene
    misurato. Le proiezioni si concatenano e le misure si calcolano
    sull'unione, come se fosse un'unica prova.

    `fabbriche` sono funzioni senza argomenti che restituiscono un ranker
    nuovo: riaddestrare lo stesso oggetto lascerebbe residui.
    """
    divisione = pieghe(casi, quante, stratifica=stratifica)
    per_enc = {c.enc_oid: c for c in casi}
    accumulo: dict[str, tuple[str, dict]] = {}
    for i, prova in enumerate(divisione):
        addestramento = [c for j, p in enumerate(divisione) if j != i for c in p]
        candidati = insieme_candidato(addestramento)
        for fabbrica in fabbriche:
            r = fabbrica()
            r.addestra(addestramento)
            nome, o = accumulo.setdefault(r.sigla, (r.nome, {}))
            o.update(proiezioni(r, prova, candidati))
    return [esito_da_proiezioni(sigla, nome, o, per_enc, k)
            for sigla, (nome, o) in accumulo.items()]


# ---------------------------------------------------------------------------
# La spiegabilita': quante proposte portano una ragione citabile
# ---------------------------------------------------------------------------

def spiegabilita(esiti: Sequence[Esito], k: int = 5,
                 simbolico: RankerSimbolico | None = None) -> dict[str, dict]:
    """Quante proposte hanno almeno un'indicazione ESC che scatta sul paziente.

    Si contano a parte le proposte **centrate** (prescritte davvero), perche'
    e' li' che una motivazione vale: una proposta sbagliata e motivata resta
    sbagliata. La frequenza per costruzione non guarda il paziente: le sue
    proposte sono motivate solo per coincidenza, e lo si conta.
    """
    simbolico = simbolico or RankerSimbolico()
    fuori = {}
    for e in esiti:
        proposte = motivate = centri = centri_motivati = 0
        for enc, ordine in e.ordini.items():
            caso = e.casi[enc]
            for cls in ordine[:k]:
                ha_motivo = bool(simbolico.motivazioni(caso, cls))
                proposte += 1
                motivate += ha_motivo
                if cls in caso.dimissione:
                    centri += 1
                    centri_motivati += ha_motivo
        fuori[e.sigla] = {
            "proposte": proposte, "motivate": motivate,
            "quota_motivate": motivate / proposte if proposte else 0.0,
            "centri": centri, "centri_motivati": centri_motivati,
            "quota_centri_motivati": centri_motivati / centri if centri else 0.0,
        }
    return fuori


# ---------------------------------------------------------------------------
# Il ranker LLM, dalla cache
# ---------------------------------------------------------------------------

def _llm_su_tutti(casi: Sequence[Caso], opzioni) -> Esito:
    """Il ranker LLM remoto su tutti i casi, con un tetto di spesa.

    Non impara dai casi, quindi le pieghe non gli servono: si misura su tutti
    i ricoveri con l'insieme candidato della divisione singola, cosi' le
    risposte gia' pagate arrivano dalla cache. Con `--llm-solo-cache` non
    spende nulla e misura solo i ricoveri gia' su disco.
    """
    from llm_backend import CARTELLA_CACHE, BackendOpenRouter, Richiesta
    from ranker import ISTRUZIONI_LLM, SCHEMA_LLM, RankerLLM, descrivi_caso, nomi_icd

    kwargs: dict = {"ragionamento": "no"}
    if opzioni.modello:
        kwargs["modello"] = opzioni.modello
    backend = BackendOpenRouter(**kwargs)
    tetto = opzioni.tetto_dollari
    speso = {"nuovo": 0.0}    # solo le risposte pagate adesso: la cache non costa

    def rapporto(n, enc, risposta, secondi):
        if not risposta.da_cache:
            speso["nuovo"] += risposta.costo
        if n % 100 == 0 or not risposta.da_cache and n <= 3:
            print(f"  llm {n}/{len(tutti)}  enc {enc}  cache={risposta.da_cache}  "
                  f"speso ora {speso['nuovo']:.4f} $")
        if speso["nuovo"] > tetto:
            raise SystemExit(f"tetto di spesa superato: {speso['nuovo']:.4f} $ > {tetto} $")

    icd, atc = nomi_icd(), nomi_atc()
    r_llm = RankerLLM(backend, icd, atc, rapporto=rapporto)
    addestramento, _ = dividi(casi)
    candidati = insieme_candidato(addestramento)
    tutti = sorted(casi, key=lambda c: c.enc_oid)
    if opzioni.llm_solo_cache:
        def in_cache(c):
            r = Richiesta(istruzioni=ISTRUZIONI_LLM, schema=SCHEMA_LLM, temperatura=0.0,
                          testo=descrivi_caso(c, applica_filtro(c, candidati), icd, atc))
            return (CARTELLA_CACHE / (r.impronta(backend.modello) + ".json")).exists()
        tutti = [c for c in tutti if in_cache(c)]
    print(f"Ranker LLM ({backend.modello}) su {len(tutti)} casi, {len(candidati)} "
          f"candidati della divisione singola, tetto {tetto} $ ...")
    ordini = proiezioni(r_llm, tutti, candidati)
    print(f"  chiamate {r_llm.chiamate}, costo registrato {r_llm.costo:.4f} $, "
          f"codici scartati {r_llm.scartati}")
    return esito_da_proiezioni("llm_rem", f"modello linguistico ({backend.modello})",
                               ordini, {c.enc_oid: c for c in tutti}, opzioni.k)


# ---------------------------------------------------------------------------
# Stampa e scrittura
# ---------------------------------------------------------------------------

def _intestazione(etichetta: str) -> str:
    return f"{etichetta:36}" + "".join(f"{NOMI_LIVELLO[n][:14]:>18}" for n in livelli_misurabili())


def stampa(esiti: Sequence[Esito], k: int) -> None:
    print(f"\nTERAPIA PROPOSTA (ingresso + {k} nuove) CONTRO DIMISSIONE: P / R / F1 per livello")
    print(_intestazione("ranker"))
    for e in esiti:
        print(f"{e.nome[:35]:36}" + "".join(
            f"  {m['P']*100:4.1f}/{m['R']*100:4.1f}/{m['F1']*100:4.1f}"
            for m in e.per_livello.values()))

    casuale = next((e for e in esiti if e.sigla == "caso"), None)
    if casuale:
        print("\nF1 SOPRA IL CASO (punti percentuali)")
        print(_intestazione("ranker"))
        for e in esiti:
            if e.sigla == "caso":
                continue
            print(f"{e.nome[:35]:36}" + "".join(
                f"{(e.per_livello[n]['F1'] - casuale.per_livello[n]['F1']) * 100:+17.1f} "
                for n in e.per_livello))

    print(f"\nTOP-{k}: ricoveri con almeno un'aggiunta reale fra le {k} proposte nuove")
    print(_intestazione("ranker"))
    for e in esiti:
        print(f"{e.nome[:35]:36}" + "".join(f"{v:17.1%} " for v in e.top_k.values()))


def _stampa_spiegabilita(esiti: Sequence[Esito], quote: dict[str, dict], k: int) -> None:
    print(f"\nPROPOSTE CON UN'INDICAZIONE CITABILE (prime {k})")
    print(f"{'ranker':36}{'proposte':>10}{'motivate':>10}{'centri':>9}{'motivati':>10}")
    for e in esiti:
        q = quote[e.sigla]
        print(f"{e.nome[:35]:36}{q['proposte']:>10}{q['quota_motivate']:>9.1%} "
              f"{q['centri']:>8}{q['quota_centri_motivati']:>9.1%}")


def _stampa_incertezza(esiti: Sequence[Esito], incertezza: dict) -> None:
    print("\nINTERVALLI AL 95% DI F1, PER LIVELLO")
    print(_intestazione("ranker"))
    for e in esiti:
        i = incertezza["per_ranker"][e.sigla]
        print(f"{e.nome[:35]:36}" + "".join(
            f"{f'[{b*100:.1f}, {a*100:.1f}]':>18}" for b, a in i.values()))
    print("\nDIFFERENZE APPAIATE DI F1 (stesso campione a ogni giro)")
    print(_intestazione("coppia"))
    for coppia, d in incertezza["differenze_appaiate"].items():
        print(f"{coppia:36}" + "".join(
            f"{f'[{b*100:+.1f}, {a*100:+.1f}]':>18}" for b, a in d.values()))
    print("\nDIFFERENZE APPAIATE DI TOP-K")
    print(_intestazione("coppia"))
    for coppia, d in incertezza["differenze_top_k"].items():
        print(f"{coppia:36}" + "".join(
            f"{f'[{b*100:+.1f}, {a*100:+.1f}]':>18}" for b, a in d.values()))
    print("  un intervallo che include lo zero = NON distinguibile")


def esempio_svolto(esito: Esito, enc: int, k: int, nomi: dict[str, str] | None = None) -> str:
    """La misura fatta a mano su un ricovero, livello per livello.

    Serve al documento: mostra che cosa la tabella conta, su un caso vero.
    """
    caso = esito.casi[enc]
    nomi = nomi or {}
    righe = [f"ricovero {enc}: ingresso {sorted(caso.terapia_ingresso)}",
             f"  proposte nuove (prime {k}): {esito.ordini[enc][:k]}",
             f"  dimissione: {sorted(caso.dimissione)}"]
    proposta = terapia_proposta(caso, esito.ordini[enc], k)
    for n in livelli_misurabili():
        prop = {c[:n] for c in proposta}
        veri = {c[:n] for c in caso.dimissione}
        p, r, f = precisione_richiamo_f1(prop, veri)
        righe.append(f"  {NOMI_LIVELLO[n]:28} proposti {len(prop):2}, veri {len(veri):2}, "
                     f"comuni {len(prop & veri):2}  P {p:.0%} R {r:.0%} F1 {f:.0%}")
    return "\n".join(righe)


def _scrivi(uscita: Path, esiti: Sequence[Esito], k: int,
            incertezza: dict | None, intestazione: dict) -> None:
    uscita.parent.mkdir(parents=True, exist_ok=True)
    uscita.write_text(json.dumps({
        "k": k,
        **intestazione,
        "livelli": {str(n): NOMI_LIVELLO[n] for n in livelli_misurabili()},
        "risultati": [{
            "sigla": e.sigla, "nome": e.nome,
            "per_livello": {str(n): m for n, m in e.per_livello.items()},
            "top_k": {str(n): v for n, v in e.top_k.items()},
        } for e in esiti],
        **({"incertezza": {
            "giri": incertezza["giri"],
            "ricoveri_ricampionati": incertezza["ricoveri_ricampionati"],
            "per_ranker": {s: {str(n): v for n, v in d.items()}
                           for s, d in incertezza["per_ranker"].items()},
            "differenze_appaiate": {c: {str(n): v for n, v in d.items()}
                                    for c, d in incertezza["differenze_appaiate"].items()},
            "differenze_top_k": {c: {str(n): v for n, v in d.items()}
                                 for c, d in incertezza["differenze_top_k"].items()},
        }} if incertezza else {}),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nDettaglio in {uscita}")


def main() -> None:
    import argparse

    argomenti = argparse.ArgumentParser(
        description="Step 11: precisione, richiamo e F1 per livello ATC.")
    argomenti.add_argument("--cartella", type=Path,
                           default=RADICE / "data" / "processed" / "pipeline_b_v3",
                           help="Uscita della pipeline da cui leggere i casi.")
    argomenti.add_argument("--uscita", type=Path,
                           default=RADICE / "data" / "processed" / "valutazione_step11.json")
    argomenti.add_argument("--k", type=int, default=5)
    argomenti.add_argument("--pieghe", type=int, default=5)
    argomenti.add_argument("--bootstrap", type=int, default=1000,
                           help="Giri di bootstrap sui ricoveri (0 per saltarlo).")
    argomenti.add_argument("--stratifica", action="store_true",
                           help="Pieghe stratificate per condizione principale "
                                "(I50, I48, I25, I10, altro).")
    argomenti.add_argument("--sostanza", action="store_true",
                           help="Unita' = sostanza (7 caratteri) invece della classe a 5: "
                                "aggiunge il quinto livello.")
    argomenti.add_argument("--llm", action="store_true",
                           help="Aggiunge il ranker LLM remoto (deepseek via OpenRouter).")
    argomenti.add_argument("--llm-solo-cache", action="store_true",
                           help="Con --llm: solo i ricoveri gia' in cache, zero spesa.")
    argomenti.add_argument("--tetto-dollari", type=float, default=0.0,
                           help="Con --llm: la corsa si ferma oltre questa spesa nuova.")
    argomenti.add_argument("--modello", default=None)
    argomenti.add_argument("--esempi", type=int, default=0,
                           help="Stampa la misura svolta a mano sui primi N ricoveri.")
    opzioni = argomenti.parse_args()

    if opzioni.sostanza:
        # `classe()` legge la costante a ogni chiamata: basta cambiarla prima di
        # caricare i casi, e candidati, bersagli e proposte sono tutti a 7.
        modulo_ranker.LIVELLO_CLASSE = 7
    unita = "sostanza (7 caratteri)" if opzioni.sostanza else "classe (5 caratteri)"

    casi = carica_casi(opzioni.cartella)
    fabbriche = [RankerCasuale, RankerContinuita, RankerFrequenza,
                 RankerSimbolico, RankerIbrido]
    print(f"Casi: {len(casi)} da {opzioni.cartella.name}, unita' = {unita}, "
          f"validazione incrociata a {opzioni.pieghe} pieghe.")
    esiti = valuta_incrociata(fabbriche, casi, opzioni.pieghe, opzioni.k,
                              stratifica=opzioni.stratifica)
    coppie = [("ibr", "freq"), ("ibr", "simb"), ("freq", "simb"), ("freq", "base")]
    if opzioni.llm:
        esito_llm = _llm_su_tutti(casi, opzioni)
        if not esito_llm.casi:
            raise SystemExit("nessuna risposta LLM in cache per questi casi: la cache e' "
                             "a livello di classe (5 caratteri), sulla pipeline B")
        if len(esito_llm.casi) != len(casi):
            # Le differenze appaiate esigono gli stessi ricoveri: tutti i
            # ranker ristretti a quelli con risposta in cache.
            chiavi = set(esito_llm.casi)
            esiti = [esito_da_proiezioni(e.sigla, e.nome,
                                         {x: o for x, o in e.ordini.items() if x in chiavi},
                                         {x: c for x, c in e.casi.items() if x in chiavi},
                                         opzioni.k) for e in esiti]
            print(f"  tutti i ranker ristretti ai {len(chiavi)} ricoveri con risposta LLM")
        esiti.append(esito_llm)
        coppie += [("llm_rem", "freq"), ("llm_rem", "simb")]

    stampa(esiti, opzioni.k)
    quote = spiegabilita(esiti, opzioni.k)
    _stampa_spiegabilita(esiti, quote, opzioni.k)
    incertezza = None
    if opzioni.bootstrap:
        print(f"\nBootstrap su {opzioni.bootstrap} ricampionamenti dei ricoveri...")
        incertezza = bootstrap(esiti, opzioni.k, opzioni.bootstrap, coppie=coppie)
        _stampa_incertezza(esiti, incertezza)
    if opzioni.esempi:
        print("\nLA MISURA SVOLTA A MANO")
        ibrido = next(e for e in esiti if e.sigla == "ibr")
        for enc in sorted(ibrido.casi)[:opzioni.esempi]:
            print(esempio_svolto(ibrido, enc, opzioni.k))
    _scrivi(opzioni.uscita, esiti, opzioni.k, incertezza,
            {"pieghe": opzioni.pieghe, "casi": len(esiti[0].casi), "unita": unita,
             "cartella": opzioni.cartella.name, "spiegabilita": quote})


if __name__ == "__main__":
    main()
