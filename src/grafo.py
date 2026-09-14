"""Step 7 - Knowledge graph RDF dello stato dei pazienti, con la provenienza.

PERCHE' UN GRAFO, E NON UNA TABELLA
    Le tre pipeline producono tre descrizioni dello stesso ricovero, che si
    sovrappongono in parte e si contraddicono in parte. Una tabella costringe a
    scegliere una versione prima di sapere quale sia giusta; un grafo tiene tutte
    e tre insieme, ciascuna con l'indicazione di chi l'ha prodotta, e rimanda la
    scelta a chi interroga.

    Lo step 6bis ha reso questa scelta obbligatoria invece che prudente: sulle
    condizioni le due pipeline simboliche hanno un richiamo del 20% e quella a
    modello linguistico del 70%. Nessuna delle tre e' sufficiente da sola.

LE TRE FONTI E COSA CIASCUNA CONTRIBUISCE
    A  gazetteer deterministico     precisione 80,1%  richiamo 19,5%
    B  modello linguistico          precisione 96,1%  richiamo 70,1%
    C  riconoscitore neurale        precisione 81,6%  richiamo 19,9%

    (misure dello step 6bis su 25 referti annotati, condizioni)

LA DECISIONE DI MODELLAZIONE CHE CONTA: LA MENZIONE E' UN NODO
    La tentazione e' collegare il ricovero direttamente alla condizione. Cosi'
    pero' si perde esattamente cio' che serve allo step 8: *chi* lo dice e *da
    dove*. Qui ogni menzione e' un nodo con la sua pipeline, il suo campo, i suoi
    offset e la sua regola, e l'asserzione clinica e' derivata dalle menzioni che
    la sostengono.

    Ne segue la proprieta' che rende il grafo utile: le menzioni che si
    sovrappongono nello stesso punto dello stesso referto — anche se prodotte da
    pipeline diverse — diventano **una sola asserzione sostenuta da piu'
    menzioni**. Il filtro di sicurezza dello step 8 puo' allora pretendere che una
    condizione sia vista da almeno due pipeline, o rifiutare i codici che
    provengono dal solo gazetteer, e sono due interrogazioni SPARQL di tre righe.

VOCABOLARI: STANDARD DOVE ESISTONO, LOCALI DOVE SERVE
    Il vincolo di provenienza del progetto vale anche per l'ontologia: dove esiste
    uno standard W3C non se ne inventa uno.

    * **PROV-O** (W3C Recommendation, 2013-04-30) per la provenienza: una
      menzione e' una `prov:Entity` generata da una `prov:Activity` (l'esecuzione
      di una pipeline) attribuita a un `prov:Agent` (la pipeline stessa).
      L'asserzione clinica e' `prov:wasDerivedFrom` le sue menzioni.
    * **SKOS** (W3C Recommendation, 2009-08-18) per le due terminologie: ATC e
      ICD-10 sono `skos:ConceptScheme`, i codici sono `skos:Concept`, e la
      gerarchia e' `skos:broader`.
    * **DCMI Metadata Terms** per citare la fonte di ogni concetto: ogni codice
      ATC porta `dcterms:source` verso il file AIFA da cui viene, ogni codice
      ICD-10 verso il volume italiano.

    Solo cio' che e' specifico di questo dominio — il ricovero, la menzione, lo
    stato di conoscenza, il soggetto — sta in un vocabolario locale, nello spazio
    di nomi `ct:`. Quello spazio usa `example.org`, che l'RFC 2606 riserva proprio
    a questo: dichiarare che l'URI identifica senza pretendere di risolversi.

CIO' CHE IL GRAFO NON FA
    Non decide. Non fonde le contraddizioni, non sceglie fra uno stato
    `affermato` e uno `negato` quando due pipeline dissentono, non scarta le
    menzioni non risolte. Conserva tutto e segna chi dice cosa: la decisione e'
    dello step 8, che e' simbolico e ispezionabile, e questo modulo deve
    limitarsi a metterlo in condizione di prenderla.
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
from risolutori import RisolutoreATC

RADICE = Path(__file__).resolve().parent.parent

BASE = "https://example.org/terapia-cardiaca/"
CT = Namespace(BASE + "schema#")
RICOVERO = Namespace(BASE + "ricovero/")
MENZIONE = Namespace(BASE + "menzione/")
ASSERZIONE = Namespace(BASE + "asserzione/")
ATC = Namespace(BASE + "atc/")
ICD = Namespace(BASE + "icd10/")
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

DESCRIZIONE_PIPELINE = {
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
    """Identificatore stabile e leggibile, non un hash opaco.

    Un URI che si puo' leggere rende ispezionabile un dump Turtle senza dover
    risalire a una tabella di corrispondenze, e la riproducibilita' e' gratis:
    due esecuzioni sugli stessi dati producono gli stessi URI.
    """
    return "-".join(str(p).replace(" ", "_").replace("/", "_") for p in parti)


# ---------------------------------------------------------------------------
# Le terminologie
# ---------------------------------------------------------------------------

def aggiungi_atc(g: Graph, percorso: Path) -> int:
    """La gerarchia ATC completa come schema di concetti SKOS.

    Serve intera, non solo per i codici che compaiono nei referti: la metrica
    gerarchica dello step 11 misura *quanto* due codici siano vicini, e senza i
    livelli superiori non ci sarebbe nulla rispetto a cui essere vicini.
    """
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


# ---------------------------------------------------------------------------
# Le pipeline come agenti PROV
# ---------------------------------------------------------------------------

def aggiungi_pipeline(g: Graph) -> None:
    for sigla, (nome, nota) in DESCRIZIONE_PIPELINE.items():
        agente = PIPELINE[sigla]
        g.add((agente, RDF.type, PROV.Agent))
        g.add((agente, RDF.type, PROV.SoftwareAgent))
        g.add((agente, RDFS.label, Literal(nome, lang="it")))
        g.add((agente, DCTERMS.description, Literal(nota, lang="it")))


# ---------------------------------------------------------------------------
# I fatti clinici
# ---------------------------------------------------------------------------

def _uri_concetto(menzione: Menzione) -> URIRef | None:
    """Il concetto di terminologia a cui la menzione e' stata risolta.

    Puo' non esistercene uno: una menzione irrisolta resta nel grafo con il suo
    testo e senza codice. Cancellarla sarebbe la scorciatoia peggiore, perche'
    nasconderebbe proprio i casi che il progetto deve poter esaminare.
    """
    if not menzione.codice:
        return None
    return ATC[menzione.codice] if menzione.tipo == "farmaco" else ICD[menzione.codice]


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
    g.add((nodo, PROV.wasAttributedTo, PIPELINE[m.sigla]))
    # Il testo della menzione NON entra nel grafo quando questo viene
    # serializzato su disco: e' testo clinico verbatim, e il grafo e' un
    # artefatto che puo' circolare. Chi ha i dati grezzi lo ritrova dagli offset.
    concetto = _uri_concetto(m)
    if concetto is not None:
        g.add((nodo, CT.risolveA, concetto))
    else:
        g.add((nodo, CT.irrisolta, Literal(True)))
    return nodo


def aggiungi_gruppo(g: Graph, gruppo: Gruppo, n: int) -> None:
    """Un punto del referto diventa un'asserzione sostenuta dalle sue menzioni.

    E' qui che le tre pipeline si incontrano: se A e B hanno riconosciuto la
    stessa porzione di testo, le loro due menzioni sostengono la stessa
    asserzione, e il conteggio delle pipeline diventa interrogabile.
    """
    ricovero = RICOVERO[str(gruppo.enc_oid)]
    tipi = {m.tipo for m in gruppo.menzioni}
    tipo = tipi.pop() if len(tipi) == 1 else "misto"
    nodo = ASSERZIONE[_identificatore(gruppo.enc_oid, tipo, n)]

    g.add((nodo, RDF.type, CT.AsserzioneClinica))
    g.add((nodo, RDF.type, PROV.Entity))
    g.add((nodo, CT.tipoEntita, Literal(tipo)))
    g.add((nodo, CT.riguarda, ricovero))
    g.add((ricovero, CT.haAsserzione, nodo))
    g.add((nodo, CT.numeroPipeline,
           Literal(len(gruppo.sigle), datatype=XSD.integer)))
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
            g.add((nodo, CT.codiceDa, PIPELINE[m.sigla]))


def aggiungi_ricoveri(g: Graph, per_ricovero: dict[int, list[Menzione]]) -> dict:
    conteggi = Counter()
    for enc, menzioni in per_ricovero.items():
        ricovero = RICOVERO[str(enc)]
        g.add((ricovero, RDF.type, CT.Ricovero))
        g.add((ricovero, CT.identificativo, Literal(enc, datatype=XSD.integer)))
        for i, gruppo in enumerate(raggruppa(menzioni)):
            aggiungi_gruppo(g, gruppo, i)
            conteggi["asserzioni"] += 1
            conteggi[f"pipeline_{len(gruppo.sigle)}"] += 1
        conteggi["menzioni"] += len(menzioni)
    conteggi["ricoveri"] = len(per_ricovero)
    return dict(conteggi)


# ---------------------------------------------------------------------------
# Costruzione
# ---------------------------------------------------------------------------

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

    # Solo i ricoveri che tutte e tre hanno elaborato: un ricovero visto da due
    # pipeline su tre falserebbe ogni conteggio di accordo, e la differenza
    # sarebbe invisibile nel grafo.
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
