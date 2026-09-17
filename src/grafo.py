"""Step 7 - Knowledge graph RDF dello stato dei pazienti, con la provenienza.

Ogni menzione e' un nodo con pipeline, campo, offset e regola (PROV-O); le
menzioni sovrapposte nello stesso punto del referto sostengono una sola
asserzione clinica, cosi' «quante pipeline lo dicono» e' una SPARQL. ATC e
ICD-10 sono schemi SKOS con `dcterms:source`. I farmaci dei campi di terapia
hanno l'agente `campo_strutturato` (un solo parser, non tre pipeline). Il
grafo conserva tutto e non decide: decide lo step 8. Vedi docs/07_knowledge_graph.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS, SKOS, XSD

from confronto import CARTELLE, Gruppo, Menzione, _carica_da, carica, raggruppa, ripulisci
from conoscenza import ATC, BASE, CT, ICD  # gli stessi nodi di kb/conoscenza.ttl
from risolutori import RisolutoreATC

RADICE = Path(__file__).resolve().parent.parent

RICOVERO = Namespace(BASE + "ricovero/")
MENZIONE = Namespace(BASE + "menzione/")
ASSERZIONE = Namespace(BASE + "asserzione/")
PIPELINE = Namespace(BASE + "pipeline/")
PROV = Namespace("http://www.w3.org/ns/prov#")

FONTE_ATC = ("AIFA - registro ATC (atc.csv), CC-BY 4.0, "
             "https://www.aifa.gov.it/open-data")
FONTE_ICD = ("ICD-10 2019 in italiano, Volume 1 - Centro Collaboratore Italiano "
             "dell'OMS, https://www.reteclassificazioni.it/")

# I livelli della classificazione ATC si leggono dalla lunghezza del codice: e'
# la definizione dell'OMS, non una convenzione di questo progetto.
LIVELLI_ATC = {1: "anatomico", 3: "terapeutico", 4: "farmacologico",
               5: "chimico", 7: "sostanza"}

SIGLA_PARSER = "campo_strutturato"

DESCRIZIONE_PIPELINE = {
    SIGLA_PARSER: (
        "Parser deterministico dei campi di terapia",
        "Legge le due liste con delimitatori senza inferenza. Le tre pipeline "
        "lo condividono: quei campi hanno una sola lettura in tutto il "
        "progetto, non tre.",
    ),
    "A": ("Pipeline A - gazetteer deterministico",
          "Riconoscimento per dizionario chiuso con algoritmo ConText per "
          "negazione, incertezza, storicita' e soggetto."),
    "B": ("Pipeline B - modello linguistico con decodifica vincolata",
          "Estrazione a schema JSON vincolato; i codici NON provengono dal "
          "modello ma dagli stessi risolutori della pipeline A."),
    "C": ("Pipeline C - riconoscitore neurale di entita'",
          "Transformer italiano biomedico affinato su etichette silver "
          "prodotte dalla pipeline A."),
}


def _identificatore(*parti) -> str:
    """Identificatore stabile e leggibile, non un hash opaco."""
    return "-".join(str(p).replace(" ", "_").replace("/", "_") for p in parti)


# --- Le terminologie ---

def aggiungi_atc(g: Graph, percorso: Path) -> int:
    """La gerarchia ATC completa come schema SKOS (serve intera per i livelli superiori)."""
    schema = ATC["schema"]
    g.add((schema, RDF.type, SKOS.ConceptScheme))
    g.add((schema, SKOS.prefLabel,
           Literal("Anatomical Therapeutic Chemical (ATC)", lang="en")))
    g.add((schema, DCTERMS.source, Literal(FONTE_ATC)))

    codici = {}
    with percorso.open(encoding="utf-8-sig") as f:
        for riga in csv.DictReader(f, delimiter=";"):
            codici[riga["CODICE_ATC"].strip()] = riga["DESCRIZIONE"].strip()

    for codice, descrizione in codici.items():
        nodo = ATC[codice]
        g.add((nodo, RDF.type, SKOS.Concept))
        g.add((nodo, SKOS.inScheme, schema))
        g.add((nodo, SKOS.notation, Literal(codice)))
        g.add((nodo, SKOS.prefLabel, Literal(descrizione, lang="it")))
        g.add((nodo, DCTERMS.source, Literal(FONTE_ATC)))
        livello = LIVELLI_ATC.get(len(codice))
        if livello:
            g.add((nodo, CT.livelloATC, Literal(livello)))
        # Il padre e' il prefisso: il codice porta la gerarchia dentro di se'.
        for lunghezza in (5, 4, 3, 1):
            if len(codice) > lunghezza and codice[:lunghezza] in codici:
                g.add((nodo, SKOS.broader, ATC[codice[:lunghezza]]))
                break
    return len(codici)


def aggiungi_icd(g: Graph, percorso: Path) -> int:
    """Le voci ICD-10 come schema di concetti SKOS."""
    dati = json.loads(percorso.read_text(encoding="utf-8"))
    schema = ICD["schema"]
    g.add((schema, RDF.type, SKOS.ConceptScheme))
    g.add((schema, SKOS.prefLabel,
           Literal("ICD-10 2019, edizione italiana", lang="it")))
    g.add((schema, DCTERMS.source, Literal(FONTE_ICD)))

    presenti = {v["codice"] for v in dati["voci"]}
    for voce in dati["voci"]:
        nodo = ICD[voce["codice"]]
        g.add((nodo, RDF.type, SKOS.Concept))
        g.add((nodo, SKOS.inScheme, schema))
        g.add((nodo, SKOS.notation, Literal(voce["codice"])))
        g.add((nodo, SKOS.prefLabel, Literal(voce["titolo"], lang="it")))
        g.add((nodo, DCTERMS.source, Literal(FONTE_ICD)))
        g.add((nodo, CT.livelloICD, Literal(voce["livello"])))
        # Una sottocategoria "I48.0" sta sotto la categoria "I48".
        if "." in voce["codice"]:
            padre = voce["codice"].split(".")[0]
            if padre in presenti:
                g.add((nodo, SKOS.broader, ICD[padre]))
    return len(dati["voci"])


# --- Le pipeline come agenti PROV ---

def aggiungi_pipeline(g: Graph) -> None:
    for sigla, (nome, nota) in DESCRIZIONE_PIPELINE.items():
        agente = PIPELINE[sigla]
        g.add((agente, RDF.type, PROV.Agent))
        g.add((agente, RDF.type, PROV.SoftwareAgent))
        g.add((agente, RDFS.label, Literal(nome, lang="it")))
        g.add((agente, DCTERMS.description, Literal(nota, lang="it")))


# --- I fatti clinici ---

def _uri_concetto(menzione: Menzione) -> URIRef | None:
    """Il concetto a cui la menzione e' risolta; una menzione irrisolta resta nel grafo senza codice."""
    if not menzione.codice:
        return None
    return ATC[menzione.codice] if menzione.tipo == "farmaco" else ICD[menzione.codice]


def agente(m: Menzione) -> URIRef:
    """Chi ha prodotto la menzione: la pipeline, o il parser condiviso per i campi di terapia (un consenso a tre sarebbe finto)."""
    return PIPELINE[SIGLA_PARSER if m.strutturata else m.sigla]


def aggiungi_menzione(g: Graph, m: Menzione, n: int) -> URIRef:
    nodo = MENZIONE[_identificatore(m.enc_oid, m.sigla, m.tipo, m.inizio, m.fine, n)]
    g.add((nodo, RDF.type, CT.Menzione))
    g.add((nodo, RDF.type, PROV.Entity))
    g.add((nodo, CT.tipoEntita, Literal(m.tipo)))
    g.add((nodo, CT.campoSorgente, Literal(m.campo)))
    g.add((nodo, CT.inizio, Literal(m.inizio, datatype=XSD.integer)))
    g.add((nodo, CT.fine, Literal(m.fine, datatype=XSD.integer)))
    g.add((nodo, CT.stato, Literal(m.stato)))
    g.add((nodo, CT.soggetto, Literal(m.soggetto)))
    g.add((nodo, PROV.wasAttributedTo, agente(m)))
    # Come e' stata prodotta (la regola), non solo da chi.
    if m.regola:
        g.add((nodo, CT.regola, Literal(m.regola)))
    # Il testo della menzione non va su disco: si ritrova dagli offset.
    concetto = _uri_concetto(m)
    if concetto is not None:
        g.add((nodo, CT.risolveA, concetto))
    else:
        g.add((nodo, CT.irrisolta, Literal(True)))
    return nodo


def aggiungi_gruppo(g: Graph, gruppo: Gruppo, n: int) -> None:
    """Un punto del referto diventa un'asserzione sostenuta dalle menzioni che vi si sovrappongono."""
    ricovero = RICOVERO[str(gruppo.enc_oid)]
    tipi = {m.tipo for m in gruppo.menzioni}
    tipo = tipi.pop() if len(tipi) == 1 else "misto"
    nodo = ASSERZIONE[_identificatore(gruppo.enc_oid, tipo, n)]

    g.add((nodo, RDF.type, CT.AsserzioneClinica))
    g.add((nodo, RDF.type, PROV.Entity))
    g.add((nodo, CT.tipoEntita, Literal(tipo)))
    g.add((nodo, CT.riguarda, ricovero))
    g.add((ricovero, CT.haAsserzione, nodo))
    agenti = {agente(m) for m in gruppo.menzioni}
    g.add((nodo, CT.numeroPipeline, Literal(len(agenti), datatype=XSD.integer)))
    if gruppo.ambiguo:
        # Una pipeline contribuisce piu' di una menzione: il gruppo dice ancora
        # *chi* ha visto il punto, ma non permette di appaiare stato e codice.
        g.add((nodo, CT.allineamentoAmbiguo, Literal(True)))

    for i, m in enumerate(gruppo.menzioni):
        menzione = aggiungi_menzione(g, m, i)
        g.add((nodo, PROV.wasDerivedFrom, menzione))
        g.add((menzione, CT.sostiene, nodo))
        concetto = _uri_concetto(m)
        if concetto is not None:
            g.add((nodo, CT.concetto, concetto))
            g.add((nodo, CT.codiceDa, agente(m)))


def aggiungi_ricoveri(g: Graph, per_ricovero: dict[int, list[Menzione]]) -> dict:
    conteggi = Counter()
    for enc, menzioni in per_ricovero.items():
        ricovero = RICOVERO[str(enc)]
        g.add((ricovero, RDF.type, CT.Ricovero))
        g.add((ricovero, CT.identificativo, Literal(enc, datatype=XSD.integer)))
        for i, gruppo in enumerate(raggruppa(menzioni)):
            aggiungi_gruppo(g, gruppo, i)
            conteggi["asserzioni"] += 1
            conteggi[f"pipeline_{len({agente(m) for m in gruppo.menzioni})}"] += 1
        conteggi["menzioni"] += len(menzioni)
    conteggi["ricoveri"] = len(per_ricovero)
    return dict(conteggi)


# --- Costruzione ---

@dataclass
class Costruzione:
    grafo: Graph
    conteggi: dict


def costruisci(radice: Path = RADICE, cartella_b: Path | None = None) -> Costruzione:
    g = Graph()
    for prefisso, spazio in (("ct", CT), ("ric", RICOVERO), ("men", MENZIONE),
                             ("ass", ASSERZIONE), ("atc", ATC), ("icd", ICD),
                             ("pipe", PIPELINE), ("prov", PROV),
                             ("skos", SKOS), ("dcterms", DCTERMS)):
        g.bind(prefisso, spazio)

    conteggi = {}
    conteggi["concetti_atc"] = aggiungi_atc(
        g, radice / "data" / "external" / "aifa" / "atc.csv")
    conteggi["concetti_icd"] = aggiungi_icd(
        g, radice / "data" / "interim" / "terminologia_icd10.json")
    aggiungi_pipeline(g)

    dati: dict[str, dict[int, list[Menzione]]] = {}
    for sigla in ("A", "C"):
        dati[sigla] = carica(sigla, radice=radice)
    if cartella_b is not None:
        dati["B"] = _carica_da(cartella_b, "B")
    else:
        dati["B"] = carica("B", radice=radice)
    dati["B"], _ = ripulisci(dati["B"], RisolutoreATC())

    # Solo i ricoveri elaborati da tutte e tre, o i conteggi di accordo sarebbero falsati.
    comuni = set.intersection(*(set(d) for d in dati.values()))
    per_ricovero: dict[int, list[Menzione]] = {
        enc: [m for sigla in "ABC" for m in dati[sigla].get(enc, [])]
        for enc in sorted(comuni)
    }
    conteggi.update(aggiungi_ricoveri(g, per_ricovero))
    conteggi["triple"] = len(g)
    return Costruzione(g, conteggi)


def main() -> None:
    argomenti = argparse.ArgumentParser(
        description="Step 7: costruisce il knowledge graph RDF con la provenienza.")
    argomenti.add_argument(
        "--cartella-b", type=Path, default=None,
        help="Cartella della corsa della pipeline B da usare, se diversa da quella predefinita.")
    argomenti.add_argument(
        "--uscita", type=Path, default=RADICE / "data" / "processed" / "grafo.ttl",
        help="File Turtle da scrivere.")
    opzioni = argomenti.parse_args()

    costruzione = costruisci(cartella_b=opzioni.cartella_b)
    c = costruzione.conteggi
    print("KNOWLEDGE GRAPH — step 7")
    print(f"  terminologie   ATC {c['concetti_atc']:6}   ICD-10 {c['concetti_icd']:6}")
    print(f"  ricoveri       {c['ricoveri']:6}")
    print(f"  menzioni       {c['menzioni']:6}")
    print(f"  asserzioni     {c['asserzioni']:6}")
    for n in (1, 2, 3):
        quota = c.get(f"pipeline_{n}", 0) / c["asserzioni"] if c["asserzioni"] else 0
        print(f"    sostenute da {n} pipeline: {c.get(f'pipeline_{n}', 0):6} ({quota:.1%})")
    print(f"  triple         {c['triple']:6}")

    opzioni.uscita.parent.mkdir(parents=True, exist_ok=True)
    costruzione.grafo.serialize(destination=opzioni.uscita, format="turtle")
    print(f"\nScritto in {opzioni.uscita}")


if __name__ == "__main__":
    main()
