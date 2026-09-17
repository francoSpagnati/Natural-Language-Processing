"""La knowledge base clinica: strutture, lettura e scrittura del Turtle.

Il grafo di conoscenza del progetto (brief §3.3) sta in `kb/conoscenza.ttl`,
versionato. Contiene tre tipi di nodo — `Drug` (classi ATC), `Condition`
(codici ICD-10), `Guideline` (documenti citati) — e due tipi di relazione
reificata, perche' portano attributi:

* **Indicazione**: farmaco → condizione, con classe di raccomandazione ESC,
  motivo, fonte, eventuale terapia che la innesca e fatto non estratto;
* **Controindicazione**: farmaco → condizione, con esito (vietato o da
  verificare), motivo, fonte, fatti che la revocano e fatto non estratto.

`kb_build.py` e' lo script di import che **scrive** il Turtle a partire dalla
curatela dichiarata; questo modulo lo **legge**, e il ranker (step 9) e il
filtro (step 8) prendono le regole da qui. Un test verifica che il Turtle nel
repository sia identico a quello che `kb_build.py` rigenererebbe: la
conoscenza che il motore usa e' quella che il grafo dichiara, senza copie.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from rdflib import DCTERMS, RDF, RDFS, SKOS, Graph, Literal, Namespace, URIRef

RADICE = Path(__file__).resolve().parent.parent
PERCORSO = RADICE / "kb" / "conoscenza.ttl"

BASE = "https://example.org/terapia-cardiaca/"  # lo stesso del grafo dei ricoveri: icd:I50 e' un nodo solo
CT = Namespace(BASE + "schema#")
ATC = Namespace(BASE + "atc/")
ICD = Namespace(BASE + "icd10/")
KB = Namespace(BASE + "kb/")


class Esito(str, Enum):
    AMMESSO = "ammesso"
    DA_VERIFICARE = "da_verificare"
    VIETATO = "vietato"


@dataclass(frozen=True)
class Indicazione:
    """Una ragione citabile per proporre una classe di farmaci.

    `atc_richiesto` esiste perche' un'indicazione puo' essere innescata da una
    terapia e non da una diagnosi: la gastroprotezione non e' indicata da una
    malattia, e' indicata dall'antiaggregante che il paziente sta prendendo.
    """

    atc: str                     # classe raccomandata (prefisso ATC)
    icd: tuple[str, ...]         # prefissi ICD-10 che la innescano
    classe_racc: str             # classe di raccomandazione ESC: I, IIa, IIb
    motivo: str
    fonte: str
    atc_richiesto: tuple[str, ...] = ()
    fatto_non_estratto: str | None = None

    @property
    def uri(self) -> URIRef:
        return KB[f"indicazione/{self.atc}-{'+'.join(self.icd + self.atc_richiesto)}"]


@dataclass(frozen=True)
class Controindicazione:
    atc: str              # prefisso ATC del farmaco (qualunque livello)
    icd: tuple[str, ...]  # prefissi ICD-10 della condizione
    esito: Esito
    motivo: str
    fonte: str
    revocata_da: tuple[str, ...] = ()
    fatto_non_estratto: str | None = None

    @property
    def uri(self) -> URIRef:
        return KB[f"controindicazione/{self.atc}-{'+'.join(self.icd)}"]


# Una regola la cui applicazione corretta richiede un fatto che il sistema non
# sa stabilire non puo' emettere un divieto: puo' segnalare. Trovato allo step 8
# (betabloccante in blocco AV: 12 falsi blocchi su 14 avevano un pacemaker che
# nessuna pipeline estrae), ricomparso agli step 9, 10 e nel server MCP.
PRINCIPIO_DEL_FATTO_MANCANTE = (
    "Regola declassata: la sua applicazione corretta richiede un fatto che "
    "nessuna pipeline estrae. Segnala, non vieta."
)


# ---------------------------------------------------------------------------
# Scrittura
# ---------------------------------------------------------------------------

def _guideline(g: Graph, fonte: str) -> URIRef:
    """Un nodo Guideline per citazione; l'URI e' il testo stesso, senza troncarlo:
    due citazioni che condividono i primi 80 caratteri sono gia' successe."""
    nodo = KB["linea_guida/" + "".join(c if c.isalnum() else "-" for c in fonte)]
    g.add((nodo, RDF.type, CT.Guideline))
    g.add((nodo, DCTERMS.source, Literal(fonte)))
    return nodo


def _codice(g: Graph, spazio: Namespace, tipo: URIRef, codice: str,
            etichette: dict[str, str]) -> URIRef:
    nodo = spazio[codice]
    g.add((nodo, RDF.type, tipo))
    g.add((nodo, SKOS.notation, Literal(codice)))
    if codice in etichette:
        g.add((nodo, RDFS.label, Literal(etichette[codice], lang="it")))
    return nodo


def scrivi(indicazioni: tuple[Indicazione, ...],
           controindicazioni: tuple[Controindicazione, ...],
           etichette_atc: dict[str, str], etichette_icd: dict[str, str],
           percorso: Path = PERCORSO) -> Graph:
    g = Graph()
    for prefisso, spazio in (("ct", CT), ("atc", ATC), ("icd", ICD), ("kb", KB),
                             ("skos", SKOS), ("dcterms", DCTERMS)):
        g.bind(prefisso, spazio)

    for i in indicazioni:
        farmaco = _codice(g, ATC, CT.Drug, i.atc, etichette_atc)
        g.add((farmaco, CT.atcCode, Literal(i.atc)))
        g.add((i.uri, RDF.type, CT.Indicazione))
        g.add((i.uri, CT.farmaco, farmaco))
        for c in i.icd:
            cond = _codice(g, ICD, CT.Condition, c, etichette_icd)
            g.add((i.uri, CT.condizione, cond))
            g.add((farmaco, CT.hasIndication, cond))
        for a in i.atc_richiesto:
            g.add((i.uri, CT.terapiaRichiesta, _codice(g, ATC, CT.Drug, a, etichette_atc)))
        g.add((i.uri, CT.classeRaccomandazione, Literal(i.classe_racc)))
        g.add((i.uri, CT.motivo, Literal(i.motivo, lang="it")))
        g.add((i.uri, CT.recommendedBy, _guideline(g, i.fonte)))
        if i.fatto_non_estratto:
            g.add((i.uri, CT.fattoNonEstratto, Literal(i.fatto_non_estratto, lang="it")))

    for c in controindicazioni:
        farmaco = _codice(g, ATC, CT.Drug, c.atc, etichette_atc)
        g.add((farmaco, CT.atcCode, Literal(c.atc)))
        g.add((c.uri, RDF.type, CT.Controindicazione))
        g.add((c.uri, CT.farmaco, farmaco))
        for k in c.icd:
            cond = _codice(g, ICD, CT.Condition, k, etichette_icd)
            g.add((c.uri, CT.condizione, cond))
            g.add((farmaco, CT.hasContraindication, cond))
        for k in c.revocata_da:
            g.add((c.uri, CT.revocataDa, _codice(g, ICD, CT.Condition, k, etichette_icd)))
        g.add((c.uri, CT.esito, Literal(c.esito.value)))
        g.add((c.uri, CT.motivo, Literal(c.motivo, lang="it")))
        g.add((c.uri, CT.recommendedBy, _guideline(g, c.fonte)))
        if c.fatto_non_estratto:
            g.add((c.uri, CT.fattoNonEstratto, Literal(c.fatto_non_estratto, lang="it")))

    percorso.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(percorso, format="turtle")
    return g


# ---------------------------------------------------------------------------
# Lettura
# ---------------------------------------------------------------------------

def _codici(g: Graph, soggetto: URIRef, predicato: URIRef) -> tuple[str, ...]:
    return tuple(sorted(str(g.value(o, SKOS.notation)) for o in g.objects(soggetto, predicato)))


def _fonte(g: Graph, nodo: URIRef) -> str:
    return str(g.value(g.value(nodo, CT.recommendedBy), DCTERMS.source))


def carica(percorso: Path = PERCORSO) -> tuple[tuple[Indicazione, ...], tuple[Controindicazione, ...]]:
    """Le regole, lette dal Turtle. Ordine deterministico: per URI."""
    g = Graph().parse(percorso, format="turtle")
    indicazioni, controindicazioni = [], []
    for nodo in sorted(g.subjects(RDF.type, CT.Indicazione)):
        fne = g.value(nodo, CT.fattoNonEstratto)
        indicazioni.append(Indicazione(
            str(g.value(g.value(nodo, CT.farmaco), SKOS.notation)),
            _codici(g, nodo, CT.condizione),
            str(g.value(nodo, CT.classeRaccomandazione)),
            str(g.value(nodo, CT.motivo)), _fonte(g, nodo),
            _codici(g, nodo, CT.terapiaRichiesta),
            str(fne) if fne is not None else None))
    for nodo in sorted(g.subjects(RDF.type, CT.Controindicazione)):
        fne = g.value(nodo, CT.fattoNonEstratto)
        controindicazioni.append(Controindicazione(
            str(g.value(g.value(nodo, CT.farmaco), SKOS.notation)),
            _codici(g, nodo, CT.condizione),
            Esito(str(g.value(nodo, CT.esito))),
            str(g.value(nodo, CT.motivo)), _fonte(g, nodo),
            _codici(g, nodo, CT.revocataDa),
            str(fne) if fne is not None else None))
    return tuple(indicazioni), tuple(controindicazioni)


INDICAZIONI, REGOLE_CONTROINDICAZIONE = carica() if PERCORSO.exists() else ((), ())
