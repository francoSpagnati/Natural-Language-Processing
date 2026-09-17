"""Step 9ter - Da dove viene questa raccomandazione: la traccia sul grafo.

Risponde interrogando il grafo in SPARQL (PROV-O), non ristampando i JSON:
la stessa interrogazione gira sul grafo di un paziente e su quello dei 1 000
ricoveri. La catena: raccomandazione -> indicazione citata -> condizione ->
asserzione clinica -> menzioni con agente, campo e offset nel referto.
Vedi docs/09c_traccia.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, RDF, SKOS, XSD

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from confronto import Menzione, raggruppa  # noqa: E402
from grafo import (  # noqa: E402
    ATC,
    CT,
    ICD,
    MENZIONE,
    PIPELINE,
    PROV,
    RICOVERO,
    SIGLA_PARSER,
    agente,
    aggiungi_gruppo,
    aggiungi_pipeline,
)

FONTE_ICD = ("ICD-10 2019, Elenco Sistematico (edizione italiana), "
             "Ministero della Salute")
FONTE_ATC = ("AIFA - registro ATC (atc.csv), CC-BY 4.0")


# --- Il grafo di un paziente solo ---

def menzioni_da_stato(stato, sigla: str, enc_oid: int = 0) -> list[Menzione]:
    """Uno `StatoPaziente` in memoria -> le menzioni del grafo (stesso adattatore di `confronto.py`)."""
    fuori: list[Menzione] = []
    for c in stato.condizioni:
        p = c.provenienza
        if p.inizio is None or p.fine is None:
            continue
        fuori.append(Menzione(
            enc_oid=enc_oid, sigla=sigla, tipo="condizione", campo=p.campo_sorgente,
            inizio=p.inizio, fine=p.fine, testo=c.testo_grezzo, codice=c.codice,
            stato=c.stato.value, soggetto=c.soggetto.value,
            strutturata=p.pipeline == SIGLA_PARSER, regola=p.regola or ""))
    for f in stato.farmaci:
        p = f.provenienza
        if p.inizio is None or p.fine is None:
            continue
        fuori.append(Menzione(
            enc_oid=enc_oid, sigla=sigla, tipo="farmaco", campo=p.campo_sorgente,
            inizio=p.inizio, fine=p.fine, testo=f.nome_grezzo, codice=f.codice_atc,
            stato=f.stato.value, soggetto="paziente",
            strutturata=p.pipeline == SIGLA_PARSER, regola=p.regola or ""))
    return fuori


def _aggiungi_concetti_usati(g: Graph, menzioni: list[Menzione],
                             etichette_icd: dict[str, str],
                             etichette_atc: dict[str, str]) -> None:
    """Solo i concetti nominati, con etichetta e fonte: le terminologie intere servono al grafo del corpus, non qui."""
    for m in menzioni:
        if not m.codice:
            continue
        spazio, etichette, fonte = (
            (ATC, etichette_atc, FONTE_ATC) if m.tipo == "farmaco"
            else (ICD, etichette_icd, FONTE_ICD))
        nodo = spazio[m.codice]
        g.add((nodo, RDF.type, SKOS.Concept))
        g.add((nodo, SKOS.notation, Literal(m.codice)))
        etichetta = etichette.get(m.codice) or etichette.get(m.codice[:3])
        if etichetta:
            g.add((nodo, SKOS.prefLabel, Literal(etichetta, lang="it")))
        g.add((nodo, DCTERMS.source, Literal(fonte)))


def grafo_del_paziente(stati: dict[str, object], enc_oid: int = 0,
                       etichette_icd: dict[str, str] | None = None,
                       etichette_atc: dict[str, str] | None = None) -> Graph:
    """Il grafo di un paziente da una o piu' pipeline (`stati`: sigla -> `StatoPaziente`)."""
    g = Graph()
    for prefisso, spazio in (("ct", CT), ("ric", RICOVERO), ("men", MENZIONE),
                             ("atc", ATC), ("icd", ICD), ("pipe", PIPELINE),
                             ("prov", PROV), ("skos", SKOS), ("dcterms", DCTERMS)):
        g.bind(prefisso, spazio)
    aggiungi_pipeline(g)

    menzioni: list[Menzione] = []
    for sigla, stato in stati.items():
        menzioni.extend(menzioni_da_stato(stato, sigla, enc_oid))

    _aggiungi_concetti_usati(g, menzioni, etichette_icd or {}, etichette_atc or {})

    ricovero = RICOVERO[str(enc_oid)]
    g.add((ricovero, RDF.type, CT.Ricovero))
    g.add((ricovero, CT.identificativo, Literal(enc_oid, datatype=XSD.integer)))
    for i, gruppo in enumerate(raggruppa(menzioni)):
        aggiungi_gruppo(g, gruppo, i)

    # Il testo della menzione sta in un indice a parte, non fra le triple.
    g.testi_menzione = {  # type: ignore[attr-defined]
        (m.inizio, m.fine, m.sigla, m.tipo): m.testo for m in menzioni
    }
    return g


# --- Le interrogazioni ---

SPARQL_SOSTEGNO = """
PREFIX ct:   <%(ct)s>
PREFIX prov: <%(prov)s>
PREFIX skos: <%(skos)s>
PREFIX dcterms: <%(dcterms)s>

SELECT ?asserzione ?agenti ?campo ?inizio ?fine ?regola ?agente ?stato ?soggetto
       ?etichetta ?fonte
WHERE {
  ?asserzione a ct:AsserzioneClinica ;
              ct:concetto ?concetto ;
              ct:numeroPipeline ?agenti ;
              prov:wasDerivedFrom ?menzione .
  ?menzione ct:campoSorgente ?campo ;
            ct:inizio ?inizio ;
            ct:fine ?fine ;
            ct:stato ?stato ;
            ct:soggetto ?soggetto ;
            prov:wasAttributedTo ?agente ;
            ct:risolveA ?concetto .
  OPTIONAL { ?menzione ct:regola ?regola }
  OPTIONAL { ?concetto skos:prefLabel ?etichetta }
  OPTIONAL { ?concetto dcterms:source ?fonte }
}
ORDER BY ?inizio ?agente
""" % {"ct": str(CT), "prov": str(PROV), "skos": str(SKOS), "dcterms": str(DCTERMS)}


def sostegno_del_concetto(g: Graph, codice: str, tipo: str = "condizione") -> list[dict]:
    """Le menzioni che sostengono l'asserzione di quel codice, in SPARQL."""
    concetto = (ATC if tipo == "farmaco" else ICD)[codice]
    righe = g.query(SPARQL_SOSTEGNO, initBindings={"concetto": concetto})
    testi = getattr(g, "testi_menzione", {})

    fuori: list[dict] = []
    for r in righe:
        sigla = str(r.agente).rsplit("/", 1)[-1]
        chiave_testo = (int(r.inizio), int(r.fine), sigla, tipo)
        fuori.append({
            "agente": sigla,
            "campo": str(r.campo),
            "inizio": int(r.inizio),
            "fine": int(r.fine),
            "stato": str(r.stato),
            "soggetto": str(r.soggetto),
            "agenti_distinti": int(r.agenti),
            "regola": str(r.regola) if r.regola else None,
            "etichetta": str(r.etichetta) if r.etichetta else None,
            "fonte_terminologia": str(r.fonte) if r.fonte else None,
            "testo": testi.get(chiave_testo),
        })
    return fuori


def traccia_raccomandazione(g: Graph, classe_atc: str, caso, simbolico) -> dict:
    """La catena completa dietro una classe proposta: la regola (indicazione) e il fatto (asserzione con provenienza), uniti dal codice ICD-10."""
    anelli: list[dict] = []
    for ind in simbolico.motivazioni(caso, classe_atc):
        condizioni = sorted(c for c in caso.condizioni
                            if any(c.startswith(p) for p in ind.icd))
        anelli.append({
            "nodo": str(ind.uri),          # il nodo in kb/conoscenza.ttl
            "classe_raccomandazione": ind.classe_racc,
            "motivo": ind.motivo,
            "fonte": ind.fonte,
            "innescata_dalla_terapia": bool(ind.atc_richiesto),
            "fatto_non_estratto": ind.fatto_non_estratto,
            "condizioni": [
                {"codice": c, "sostegno": sostegno_del_concetto(g, c)}
                for c in condizioni
            ],
        })
    return {"classe_atc": classe_atc, "indicazioni": anelli}


# --- Presentazione ---

def stampa_traccia(traccia: dict, nome_classe: str = "") -> None:
    """La catena come albero leggibile. Vedi il docstring del modulo."""
    print(f"\n  {traccia['classe_atc']}  {nome_classe}")
    if not traccia["indicazioni"]:
        print("    └─ nessuna indicazione citata: la proposta viene dalla "
              "co-occorrenza\n       misurata sul corpus, non da una regola.")
        return

    for ind in traccia["indicazioni"]:
        print(f"    └─ indicazione, classe {ind['classe_raccomandazione']}")
        print(f"       │  {ind['motivo']}")
        print(f"       │  fonte: {ind['fonte']}")
        print(f"       │  nodo:  {ind['nodo']}")
        if ind["fatto_non_estratto"]:
            print(f"       │  fatto che il sistema NON estrae: "
                  f"{ind['fatto_non_estratto']}")
        if ind["innescata_dalla_terapia"]:
            print("       │  innescata dalla terapia in atto, non da una diagnosi")
        for cond in ind["condizioni"]:
            sostegno = cond["sostegno"]
            etichetta = next((s["etichetta"] for s in sostegno if s["etichetta"]), "")
            print(f"       └─ condizione  {cond['codice']}  {etichetta}")
            if not sostegno:
                print("          └─ (nessuna menzione nel grafo per questo codice)")
                continue
            fonte = next((s["fonte_terminologia"] for s in sostegno
                          if s["fonte_terminologia"]), None)
            if fonte:
                print(f"          │  codice da: {fonte}")
            print(f"          │  asserzione sostenuta da "
                  f"{sostegno[0]['agenti_distinti']} agente/i")
            for s in sostegno:
                testo = f" «{s['testo']}»" if s["testo"] else ""
                print(f"          └─ menzione  {s['agente']:6} "
                      f"{s['campo']} {s['inizio']}–{s['fine']}{testo}")
                if s["regola"]:
                    print(f"             regola: {s['regola']}")
