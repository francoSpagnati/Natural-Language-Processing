"""Step 9 - La valutazione dei ranker contro la terapia di dimissione reale.

Richiamo@k, precisione@k e MAP sui due compiti (terapia completa e sole
aggiunte), divisione singola deterministica. La precisione non e' correttezza:
il riferimento e' una decisione, non l'insieme delle decisioni giuste. La
misura finale del progetto e' nello step 11. Vedi docs/09_ranker.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ranker import (  # noqa: E402
    Caso,
    Raccomandazione,
    Ranker,
    RankerContinuita,
    RankerFrequenza,
    RankerIbrido,
    RankerSimbolico,
    applica_filtro,
    carica_casi,
    dividi,
    insieme_candidato,
)

RADICE = Path(__file__).resolve().parent.parent
K_MISURATI = (3, 5, 10)


# --- Metriche ---

def precisione_media(ordine: Sequence[str], bersaglio: frozenset[str]) -> float:
    """Average precision; un ricovero senza bersagli va escluso dalla media, non contato come zero."""
    if not bersaglio:
        return 0.0
    presi = 0
    somma = 0.0
    for i, cls in enumerate(ordine, start=1):
        if cls in bersaglio:
            presi += 1
            somma += presi / i
    return somma / len(bersaglio)


def misura(ordini: dict[int, list[str]], bersagli: dict[int, frozenset[str]]) -> dict:
    """Aggrega richiamo@k, precisione@k e MAP sui casi che hanno un bersaglio."""
    valutabili = [e for e, b in bersagli.items() if b]
    if not valutabili:
        return {"casi": 0}

    esito: dict = {"casi": len(valutabili),
                   "bersagli_per_caso": sum(len(bersagli[e]) for e in valutabili) / len(valutabili)}
    for k in K_MISURATI:
        ric = []
        pre = []
        for e in valutabili:
            primi = ordini[e][:k]
            azzeccati = len([c for c in primi if c in bersagli[e]])
            ric.append(azzeccati / len(bersagli[e]))
            pre.append(azzeccati / k)
        esito[f"richiamo@{k}"] = sum(ric) / len(ric)
        esito[f"precisione@{k}"] = sum(pre) / len(pre)
    esito["MAP"] = sum(precisione_media(ordini[e], bersagli[e])
                       for e in valutabili) / len(valutabili)
    return esito


# --- La valutazione ---

def valuta_ranker(r: Ranker, casi: Sequence[Caso], candidati: Sequence[str],
                  usa_filtro: bool = True) -> dict:
    """Misura un ranker sui due compiti, in una sola passata sui casi."""
    ordini_completa: dict[int, list[str]] = {}
    bersagli_completa: dict[int, frozenset[str]] = {}
    ordini_aggiunte: dict[int, list[str]] = {}
    bersagli_aggiunte: dict[int, frozenset[str]] = {}
    ammessi_totali = 0

    per_caso = candidati
    for caso in casi:
        if usa_filtro:
            per_caso = applica_filtro(caso, candidati)
        ammessi_totali += len(per_caso)
        ordine: list[Raccomandazione] = r.ordina(caso, per_caso)
        codici = [x.classe_atc for x in ordine]

        ordini_completa[caso.enc_oid] = codici
        # Il bersaglio e' intersecato con i candidati: cio' che non e' proponibile
        # non e' un errore del ranker, ed e' contabilizzato a parte come tetto.
        bersagli_completa[caso.enc_oid] = caso.dimissione & set(per_caso)

        # Compito 2: senza le classi gia' in terapia.
        nuovi = [c for c in codici if c not in caso.terapia_ingresso]
        ordini_aggiunte[caso.enc_oid] = nuovi
        bersagli_aggiunte[caso.enc_oid] = caso.aggiunte & set(per_caso)

    return {
        "sigla": r.sigla,
        "nome": r.nome,
        "candidati_medi": ammessi_totali / len(casi),
        "terapia_completa": misura(ordini_completa, bersagli_completa),
        "aggiunte": misura(ordini_aggiunte, bersagli_aggiunte),
    }


def tetto_dei_candidati(casi: Sequence[Caso], candidati: Sequence[str]) -> dict:
    """Quanta parte della verita' e' raggiungibile con questo insieme candidato: il tetto di ogni ranker."""
    insieme = set(candidati)
    dim = sum(len(c.dimissione) for c in casi)
    dim_dentro = sum(len(c.dimissione & insieme) for c in casi)
    agg = sum(len(c.aggiunte) for c in casi)
    agg_dentro = sum(len(c.aggiunte & insieme) for c in casi)
    return {
        "classi_candidate": len(insieme),
        "tetto_terapia_completa": dim_dentro / dim if dim else 0.0,
        "tetto_aggiunte": agg_dentro / agg if agg else 0.0,
    }


# --- Presentazione ---

def stampa(risultati: list[dict], tetto: dict, prova: Sequence[Caso]) -> None:
    print(f"\nRicoveri di prova: {len(prova)}")
    print(f"Classi candidate: {tetto['classi_candidate']}  "
          f"(tetto raggiungibile: terapia completa "
          f"{tetto['tetto_terapia_completa']:.1%}, aggiunte "
          f"{tetto['tetto_aggiunte']:.1%})")

    for compito, titolo in (("terapia_completa", "COMPITO 1 — la terapia di dimissione completa"),
                            ("aggiunte", "COMPITO 2 — le sole classi AGGIUNTE durante il ricovero")):
        print(f"\n{'=' * 78}\n{titolo}")
        m0 = risultati[0][compito]
        print(f"  bersagli per ricovero: {m0['bersagli_per_caso']:.2f} "
              f"su {m0['casi']} ricoveri valutabili\n")
        intest = f"  {'ranker':34}"
        for k in K_MISURATI:
            intest += f" ric@{k:<3}"
        intest += f" prec@5  MAP"
        print(intest)
        for r in risultati:
            m = r[compito]
            if not m.get("casi"):
                continue
            riga = f"  {r['nome'][:34]:34}"
            for k in K_MISURATI:
                riga += f" {m[f'richiamo@{k}']:6.1%}"
            riga += f" {m['precisione@5']:6.1%} {m['MAP']:6.3f}"
            print(riga)


def main() -> None:
    import argparse

    argomenti = argparse.ArgumentParser(
        description="Step 9: misura i ranker contro la terapia realmente prescritta.")
    argomenti.add_argument("--cartella-b", type=Path,
                           default=RADICE / "data" / "processed" / "pipeline_b_v3")
    argomenti.add_argument("--uscita", type=Path,
                           default=RADICE / "data" / "processed" / "ranker_step9.json")
    argomenti.add_argument("--quota-prova", type=float, default=0.3)
    argomenti.add_argument("--senza-filtro", action="store_true",
                           help="Non applica il filtro dello step 8 ai candidati. "
                                "Serve a misurare quanto il filtro cambia il risultato.")
    argomenti.add_argument("--llm", default=None,
                           choices=["locale", "openrouter"],
                           help="Aggiunge il ranker con modello linguistico. "
                                "'locale' usa Ollama sulla macchina (gratis, ~15 s "
                                "per ricovero); 'openrouter' usa il modello remoto "
                                "a consumo.")
    argomenti.add_argument("--modello", default=None,
                           help="Modello del ranker LLM, se diverso dal predefinito.")
    argomenti.add_argument("--record-llm", type=int, default=None,
                           help="Limita il ranker LLM ai primi N ricoveri di prova. "
                                "Gli altri ranker restano misurati su tutti.")
    opzioni = argomenti.parse_args()

    casi = carica_casi(opzioni.cartella_b)
    addestramento, prova = dividi(casi, opzioni.quota_prova)
    candidati = insieme_candidato(addestramento)

    print(f"Casi valutabili: {len(casi)}  "
          f"(addestramento {len(addestramento)}, prova {len(prova)})")

    rankers: list[Ranker] = [
        RankerContinuita(),
        RankerFrequenza(),
        RankerSimbolico(),
        RankerIbrido(),
    ]
    for r in rankers:
        r.addestra(addestramento)

    risultati = [valuta_ranker(r, prova, candidati, not opzioni.senza_filtro)
                 for r in rankers]

    costo_llm = None
    if opzioni.llm:
        from llm_backend import BackendOllama, BackendOpenRouter
        from ranker import RankerLLM, nomi_atc, nomi_icd

        classe_backend = {"locale": BackendOllama,
                          "openrouter": BackendOpenRouter}[opzioni.llm]
        argomenti_backend: dict = {"ragionamento": "no"}
        if opzioni.llm == "locale":
            # Contesto ridotto: il prompt del ranker e' quattro volte piu' corto di un referto.
            argomenti_backend["contesto"] = 4096
        if opzioni.modello:
            argomenti_backend["modello"] = opzioni.modello
        backend = classe_backend(**argomenti_backend)

        # Prefisso per enc_oid, non campione casuale: la cache si riusa.
        prova_llm = sorted(prova, key=lambda c: c.enc_oid)
        if opzioni.record_llm:
            prova_llm = prova_llm[:opzioni.record_llm]

        def avanzamento(n, enc, risposta, secondi):
            fonte = "cache" if risposta.da_cache else f"{secondi:5.0f}s"
            print(f"  [{n:4}/{len(prova_llm)}] {enc}  {fonte}  "
                  f"{risposta.token_uscita:4} tok", flush=True)

        r_llm = RankerLLM(backend, nomi_icd(), nomi_atc(), rapporto=avanzamento)
        r_llm.nome = f"modello linguistico ({backend.modello})"
        print(f"\nRanker LLM: {backend.modello} su {len(prova_llm)} ricoveri di prova...")
        risultati.append(valuta_ranker(r_llm, prova_llm, candidati,
                                       not opzioni.senza_filtro))
        costo_llm = {
            "modello": backend.modello, "ricoveri": len(prova_llm),
            "chiamate": r_llm.chiamate, "token": r_llm.token,
            "costo_dollari": round(r_llm.costo, 4),
            # Quante volte il modello ha nominato una classe fuori dall'elenco
            # candidato: la misura di quanto il vincolo serva.
            "codici_scartati": r_llm.scartati,
            # Il controllo «ordina davvero?»: vedi RankerLLM.
            "risposte_in_ordine_di_ingresso": r_llm.in_ordine_di_ingresso,
            "risposte_non_vuote": r_llm.risposte_non_vuote,
        }
        print(f"  {r_llm.chiamate} chiamate, {r_llm.token['ingresso']} token in "
              f"entrata, {r_llm.token['uscita']} in uscita, "
              f"{r_llm.costo:.4f} $, {r_llm.scartati} codici fuori elenco scartati.")
        if r_llm.risposte_non_vuote:
            quota = r_llm.in_ordine_di_ingresso / r_llm.risposte_non_vuote
            print(f"  risposte che ricalcano l'ordine dei candidati: "
                  f"{r_llm.in_ordine_di_ingresso}/{r_llm.risposte_non_vuote} "
                  f"({quota:.1%}) — se e' alta, il modello seleziona senza ordinare.")

    tetto = tetto_dei_candidati(prova, candidati)
    stampa(risultati, tetto, prova)

    opzioni.uscita.write_text(json.dumps(
        {"casi": len(casi), "addestramento": len(addestramento), "prova": len(prova),
         "filtro_applicato": not opzioni.senza_filtro,
         "tetto": tetto, "llm": costo_llm, "risultati": risultati},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nDettaglio in {opzioni.uscita}")


if __name__ == "__main__":
    main()
