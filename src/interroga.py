"""Interrogazioni SPARQL sul knowledge graph dello step 7.

Le domande per cui il grafo e' stato costruito in quella forma, scritte in
SPARQL e non in Python. Rileggere il Turtle (oltre un milione di triple) costa
piu' che ricostruirlo: il predefinito e' ricostruire, `--grafo` legge il file.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from rdflib import Graph

RADICE = Path(__file__).resolve().parent.parent
PREDEFINITO = RADICE / "data" / "processed" / "grafo.ttl"

PREFISSI = """
PREFIX ct:   <https://example.org/terapia-cardiaca/schema#>
PREFIX pipe: <https://example.org/terapia-cardiaca/pipeline/>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
"""

DOMANDE: list[tuple[str, str, str]] = [
    (
        "Quante asserzioni sopravvivono a una soglia di consenso",
        """Il filtro dello step 8 potrà pretendere che una condizione sia vista da
        più di una pipeline. Questa è la domanda che dice quanto costerebbe.
        `ct:numeroPipeline` conta gli AGENTI distinti, non le menzioni: le tre
        pipeline leggono i campi di terapia con lo stesso parser, e contarle
        separatamente mostrerebbe un consenso a tre dove c'è una sola lettura.""",
        """
        SELECT ?pipeline (COUNT(?a) AS ?asserzioni) WHERE {
          ?a a ct:AsserzioneClinica ; ct:numeroPipeline ?pipeline .
        } GROUP BY ?pipeline ORDER BY ?pipeline
        """,
    ),
    (
        "Le asserzioni codificate dal solo gazetteer",
        """Lo step 6 ha mostrato che gli errori esclusivi della pipeline A arrivano
        già codificati, 9 su 9, mentre quelli delle altre due restano visibili
        come irrisolti. Sono quindi gli errori più pericolosi del progetto: un
        codice sbagliato che sembra certo. Questa interrogazione li isola.""",
        """
        SELECT (COUNT(DISTINCT ?a) AS ?quante) WHERE {
          ?a a ct:AsserzioneClinica ; ct:concetto ?c ; ct:codiceDa pipe:A .
          FILTER NOT EXISTS { ?a ct:codiceDa ?altra . FILTER(?altra != pipe:A) }
        }
        """,
    ),
    (
        "Quanto ciascuna pipeline contribuisce da sola",
        """La complementarità misurata allo step 6bis, riletta sul corpus intero:
        quante asserzioni esistono solo perché quella pipeline le ha viste.""",
        """
        SELECT ?pipeline (COUNT(DISTINCT ?a) AS ?solo_sua) WHERE {
          ?a a ct:AsserzioneClinica ; ct:numeroPipeline 1 ; prov:wasDerivedFrom ?m .
          ?m prov:wasAttributedTo ?pipeline .
        } GROUP BY ?pipeline ORDER BY DESC(?solo_sua)
        """,
    ),
    (
        "Le condizioni negate o di un familiare",
        """Sono le due che un sistema ingenuo attribuirebbe al paziente. Se il
        grafo non le sapesse distinguere, il motore dello step 9 raccomanderebbe
        una terapia per la malattia del padre.""",
        """
        SELECT ?stato ?soggetto (COUNT(?m) AS ?menzioni) WHERE {
          ?m a ct:Menzione ; ct:tipoEntita "condizione" ;
             ct:stato ?stato ; ct:soggetto ?soggetto .
        } GROUP BY ?stato ?soggetto ORDER BY DESC(?menzioni)
        """,
    ),
    (
        "I dieci gruppi terapeutici più presenti, risalendo la gerarchia ATC",
        """Usa `skos:broader` per salire dal principio attivo al livello
        anatomico. È l'operazione su cui poggia la metrica gerarchica dello
        step 11: due terapie diverse nello stesso gruppo non sono un errore
        quanto due terapie in gruppi diversi.""",
        # Aggrega prima per concetto: `skos:broader+` percorso una volta per codice, non per asserzione.
        """
        SELECT ?codice ?nome (SUM(?n) AS ?asserzioni) WHERE {
          {
            SELECT ?atc (COUNT(DISTINCT ?a) AS ?n) WHERE {
              ?a a ct:AsserzioneClinica ; ct:tipoEntita "farmaco" ;
                 ct:concetto ?atc .
            } GROUP BY ?atc
          }
          ?atc skos:broader+ ?gruppo .
          ?gruppo ct:livelloATC "terapeutico" ; skos:notation ?codice ;
                  skos:prefLabel ?nome .
        } GROUP BY ?codice ?nome ORDER BY DESC(?asserzioni) LIMIT 10
        """,
    ),
    (
        "Quanta parte del grafo resta senza codice",
        """Il vincolo del progetto è conservare, non cancellare: le menzioni
        irrisolte restano, marcate. Questa dice quante sono, cioè quanto lavoro
        di normalizzazione resta scoperto.""",
        """
        SELECT ?tipo (COUNT(?m) AS ?irrisolte) WHERE {
          ?m a ct:Menzione ; ct:tipoEntita ?tipo ; ct:irrisolta true .
        } GROUP BY ?tipo ORDER BY DESC(?irrisolte)
        """,
    ),
]


def main() -> None:
    argomenti = argparse.ArgumentParser(description="Interroga il knowledge graph.")
    argomenti.add_argument(
        "--grafo", type=Path, default=None,
        help="Interroga questo file Turtle invece di ricostruire il grafo. "
             "Piu' lento: il parser di rdflib e' piu' costoso della costruzione.")
    argomenti.add_argument(
        "--cartella-b", type=Path, default=None,
        help="Corsa della pipeline B da usare nella ricostruzione.")
    opzioni = argomenti.parse_args()

    avvio = time.monotonic()
    if opzioni.grafo is not None:
        g = Graph()
        g.parse(opzioni.grafo, format="turtle")
        come = f"letto da {opzioni.grafo.name}"
    else:
        from grafo import costruisci
        g = costruisci(cartella_b=opzioni.cartella_b).grafo
        come = "ricostruito dalle uscite delle pipeline"
    print(f"Grafo {come}: {len(g)} triple in {time.monotonic() - avvio:.0f} s\n",
          flush=True)

    for titolo, perche, query in DOMANDE:
        print("=" * 74)
        print(titolo.upper())
        print("  " + " ".join(perche.split()))
        print()
        for riga in g.query(PREFISSI + query):
            print("   " + "   ".join(
                str(v).rsplit("/", 1)[-1].rsplit("#", 1)[-1] for v in riga))
        print(flush=True)


if __name__ == "__main__":
    main()
