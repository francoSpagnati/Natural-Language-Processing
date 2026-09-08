"""Step 5 - Collegamento delle menzioni alla knowledge base (pipeline C).

IL PROBLEMA CHE RESTA DOPO IL NER
    Il riconoscitore trova la menzione ma non le assegna un codice. Se la
    menzione compare tale e quale nell'indice ICD-10 basta cercarla, ed e' cio'
    che gia' fa `RisolutoreICD`. Il caso interessante e' l'altro: il NER puo'
    riconoscere come condizione una stringa che nel volume ICD non c'e' in
    quella forma -- "dislipidemia", "cardiopatia ipocinetica", "insufficienza
    mitralica moderata". Senza un ultimo passaggio, tutto questo resterebbe NIL
    e la pipeline C non aggiungerebbe nulla alla A sul fronte della codifica.

LA SIMILARITA' PROPONE, NON RISOLVE
    L'ultimo passaggio cerca il termine ICD piu' simile alla menzione,
    confrontando gli insiemi di trigrammi di caratteri con la similarita' di
    Jaccard: e' la tecnica classica di generazione dei candidati nell'entity
    linking. Il termine proposto viene sempre dall'indice estratto dal volume
    ufficiale, mai dalla conoscenza di un modello.

    Misurata sul lessico reale dei referti, pero', **la similarita' ortografica
    non separa il collegamento giusto da quello sbagliato**:

    | punteggio | menzione -> termine agganciato | esito |
    |---|---|---|
    | 0,600 | insufficienza mitralica moderata -> ...congenita (Q23.3) | sbagliato |
    | 0,547 | broncopneumopatia cronica ostruttiva -> altra pneumopatia... (J44.8) | categoria giusta |
    | 0,463 | extrasistolia sopraventricolare -> tachicardia sopraventricolare (I47.1) | sbagliato |
    | 0,424 | cardiopatia ipocinetica -> cardiomiopatia ischemica (I25.5) | sbagliato |
    | 0,409 | precordialgie -> dolore precordiale (R07.2) | corretto |
    | 0,340 | aneurisma dell'aorta ascendente -> aneurisma e dissezione dell'aorta (I71) | corretto |

    Il punteggio piu' alto e' l'errore piu' pericoloso -- la stessa trappola
    congenito/acquisito gia' incontrata nello step 4 -- mentre i due
    collegamenti corretti stanno in fondo. La ragione e' che in italiano medico
    una parola di differenza ("congenita" contro "moderata") e' ortograficamente
    vicina e clinicamente lontanissima, mentre i sinonimi ("precordialgie" e
    "dolore precordiale") sono ortograficamente distanti. Nessuna soglia
    separa i due gruppi.

    Di conseguenza il collegamento per similarita' **non produce mai un codice
    risolto**: restituisce sempre `AMBIGUO`, con il termine agganciato e il
    punteggio scritti nel metodo. E' una proposta da verificare, non una
    codifica, e non arriva mai al filtro di sicurezza dello step 8 -- che
    consuma solo le condizioni risolte. Un collegamento sbagliato attribuirebbe
    al paziente una diagnosi che non ha, ed e' peggio di un collegamento
    mancante.

    I trigrammi sui caratteri, e non le parole, perche' il divario fra lessico
    clinico e lessico ICD e' spesso morfologico ("ipertensiva" contro
    "ipertensione") e un confronto per parole non lo vedrebbe affatto.

PERCHE' NON C'E' UN DIZIONARIO DI SIGLE
    Le sigle cliniche (BPCO, FA, IRC) non sono risolvibili da nessuna fonte
    citabile a disposizione, e questo e' stato verificato invece che supposto:

    * il **corpus non definisce le proprie sigle**. L'algoritmo di
      Schwartz & Hearst (PSB 2003), applicato con il suo vincolo di
      sottosequenza, produce 105 coppie da mille referti, in larga parte rumore
      e con errori veri ("FA = frequenza cardiaca non ottimale"): i clinici
      scrivono la sigla e basta;
    * **Wikidata non le copre**: la query SPARQL per voci con codice ICD-10
      (P494) e un alias italiano in maiuscolo restituisce zero risultati.

    Inventare le espansioni violerebbe il vincolo di provenienza del progetto.
    Le sigle restano quindi non collegate anche nella pipeline C, ed e' un esito
    da riportare: l'unica pipeline che le scioglie e' la B, perche' un LLM
    attinge alla propria conoscenza interna -- che infatti viene usata solo come
    chiave di ricerca nell'indice ufficiale, mai come fonte del codice.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from risolutori import EsitoICD, RisolutoreICD, normalizza
from schema import StatoNormalizzazione

# Soglia bassa perche' l'esito e' una *proposta* e non un codice: il rischio
# di un falso positivo non esiste (nulla diventa RISOLTO per similarita'),
# mentre le proposte utili -- "precordialgie" -> "dolore precordiale" a 0,41
# -- stanno in basso. Sotto 0,35 il rumore diventa comunque prevalente.
SOGLIA_SIMILARITA = 0.35
DIMENSIONE_NGRAMMA = 3

# Sotto questa lunghezza i trigrammi sono troppo pochi perche' la similarita'
# sia informativa: "FA" condivide trigrammi con qualunque cosa.
LUNGHEZZA_MINIMA = 6


def trigrammi(testo: str, dimensione: int = DIMENSIONE_NGRAMMA) -> set[str]:
    """Insieme dei trigrammi di caratteri, con i bordi marcati.

    I bordi (spazi aggiunti a inizio e fine) fanno pesare di piu' l'inizio e la
    fine della parola, dove in italiano sta l'informazione morfologica utile.
    """
    imbottito = f" {testo} "
    return {imbottito[i : i + dimensione] for i in range(len(imbottito) - dimensione + 1)}


@dataclass(frozen=True)
class Proposta:
    """Un termine della knowledge base proposto per una menzione."""

    termine: str
    codici: tuple[str, ...]
    punteggio: float


class IndiceSimilarita:
    """Ricerca del termine ICD piu' simile, con indice inverso sui trigrammi.

    Confrontare la menzione con tutti i 13.642 termini ad ogni chiamata sarebbe
    inutilmente costoso: l'indice inverso limita il confronto ai soli termini
    che condividono almeno un trigramma, che sono ordini di grandezza meno.
    """

    def __init__(self, indice_termini: dict[str, list[str]]) -> None:
        self.termini = {t: tuple(c) for t, c in indice_termini.items() if len(t) >= LUNGHEZZA_MINIMA}
        self.trigrammi_per_termine = {t: trigrammi(t) for t in self.termini}
        self.per_trigramma: dict[str, list[str]] = defaultdict(list)
        for termine, gruppo in self.trigrammi_per_termine.items():
            for trigramma in gruppo:
                self.per_trigramma[trigramma].append(termine)

    def migliore(self, menzione: str, soglia: float = SOGLIA_SIMILARITA) -> Proposta | None:
        """Il termine piu' simile sopra soglia, o None."""
        chiave = normalizza(menzione)
        if len(chiave) < LUNGHEZZA_MINIMA:
            return None
        gruppo = trigrammi(chiave)
        if not gruppo:
            return None

        condivisi: dict[str, int] = defaultdict(int)
        for trigramma in gruppo:
            for termine in self.per_trigramma.get(trigramma, ()):
                condivisi[termine] += 1

        migliore: Proposta | None = None
        for termine, comuni in condivisi.items():
            # Jaccard: intersezione / unione. Il massimo raggiungibile con
            # `comuni` trigrammi comuni permette di scartare in anticipo i
            # termini che non potrebbero comunque superare il migliore trovato.
            unione = len(gruppo) + len(self.trigrammi_per_termine[termine]) - comuni
            punteggio = comuni / unione if unione else 0.0
            if punteggio >= soglia and (migliore is None or punteggio > migliore.punteggio):
                migliore = Proposta(termine, self.termini[termine], punteggio)
        return migliore


class CollegatoreICD:
    """`RisolutoreICD` piu' un ultimo passaggio per similarita'.

    L'ordine e' deliberato: prima tutti i metodi esatti, che danno un
    collegamento certo, e solo alla fine quello approssimato. La similarita'
    non deve mai scavalcare una corrispondenza esatta.
    """

    def __init__(self, risolutore: RisolutoreICD, soglia: float = SOGLIA_SIMILARITA) -> None:
        self.risolutore = risolutore
        self.soglia = soglia
        self.indice = IndiceSimilarita(risolutore.indice)

    def collega(self, menzione: str) -> EsitoICD:
        esito = self.risolutore.risolvi(menzione)
        if esito.stato is not StatoNormalizzazione.NIL:
            return esito

        proposta = self.indice.migliore(menzione, self.soglia)
        if proposta is None:
            return esito

        # Sempre AMBIGUO, mai RISOLTO: vedi il ragionamento in testa al modulo.
        # Il codice resta `None`, cosi' nessun consumatore a valle puo' usarlo
        # per sbaglio come se fosse una codifica accertata; i candidati e il
        # punteggio restano visibili per l'ispezione e per lo step 6.
        return EsitoICD(
            codice=None,
            stato=StatoNormalizzazione.AMBIGUO,
            concetto=proposta.termine,
            candidati=tuple(sorted(set(proposta.codici))),
            metodo=f"proposta_similarita:{proposta.punteggio:.2f}:{proposta.termine}",
        )
