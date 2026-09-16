# Step 9ter — Da dove viene questa raccomandazione: la traccia sul grafo

**Stato:** completato.
**Riproducibilità:** `python3 src/demo.py --esempio 1 --traccia`

Questo documento nasce da una domanda, e la risposta onesta è scomoda:

> *«Nella demo e anche in generale non c'è nessun modo di visualizzare il grafo
> di interazioni o qualcosa che mostra da dove nel grafo proviene
> un'informazione. Si può fare? Oppure si è dimostrato inutilizzabile?»*

Codice: [`src/traccia.py`](../src/traccia.py). Test:
[`tests/test_traccia.py`](../tests/test_traccia.py).

---

## 1. La verifica: chi leggeva davvero il grafo

```
chi importa grafo.py   →  src/interroga.py
                          notebooks/03_knowledge_graph.ipynb
                          tests/test_grafo.py

chi legge i JSON       →  src/filtro.py      (step 8)
   delle pipeline          src/valuta_ranker.py (step 9)
                          src/demo.py
                          src/confronto.py, silver_labels.py, rianalizza.py
```

**Il grafo era un artefatto parallelo.** Un milione e duecentomila triple che
nessuno strato del sistema consumava: il filtro, il ranker e la demo leggevano i
JSON delle pipeline e il grafo lo scavalcavano.

## 2. Ma non era inutile, e va detto con precisione

Il numero che ha **deciso il disegno dello step 8** è uscito interrogando quel
grafo. La domanda era: *il filtro può pretendere che una condizione sia vista da
più di una pipeline?*

| | prima della correzione | dopo |
|---|---|---|
| asserzioni su un solo agente | 41,2% | **76,3%** |
| ridondanza vera (tre agenti) | 46,6% | **14,8%** |

Il «consenso a tre» del 46,6% era falso: i dodicimila farmaci di terapia
comparivano in tutte e tre le pipeline, ma le tre li leggono con lo **stesso**
parser deterministico — una sola lettura contata tre volte. Il grafo lo ha reso
visibile perché `ct:numeroPipeline` conta gli *agenti distinti*, e senza quella
correzione il filtro si sarebbe fidato di più proprio dove non aveva imparato
nulla.

Quindi il grafo aveva già fatto il lavoro di un **artefatto di analisi**. Quello
che non aveva mai fatto era essere uno **strato del sistema**.

---

## 3. Che cosa fa ora: la catena, interrogata in SPARQL

```
  C03DA  antagonisti dell'aldosterone
    └─ indicazione, classe I
       │  Antagonista del recettore mineralcorticoide. Terzo pilastro.
       │  fonte: ESC 2021, Guidelines for heart failure, terapia dell'HFrEF.
       └─ condizione  I50.9  Scompenso cardiaco, non specificato
          │  codice da: ICD-10 2019, Elenco Sistematico (edizione italiana)
          │  asserzione sostenuta da 1 agente
          └─ menzione  A   Anamnesi 21–39  «scompenso cardiaco»
             regola: gazetteer:scompenso cardiaco
```

L'ultimo anello è quello che conta davanti a un medico: **gli offset di
carattere nel referto originale**. Una raccomandazione che sa dire *per quali
parole* la propone si può contestare; una che non lo sa, si può solo credere.

La risposta viene da un'interrogazione SPARQL, non da un attraversamento di
dizionari, e la differenza non è estetica:

* **la stessa interrogazione gira sui due grafi.** Quello di un paziente della
  demo ha 193 triple, quello del corpus ne ha 1 215 906: il modello dei dati è
  lo stesso, quindi il testo della query è lo stesso.
* **la catena è navigabile all'indietro**, perché è fatta di archi e non di
  chiamate di funzione.
* **la provenienza è in PROV-O**, quindi chi legge il grafo non deve conoscere
  le convenzioni di questo progetto: `prov:wasAttributedTo` e
  `prov:wasDerivedFrom` significano già qualcosa.

### Un anello nuovo: non solo *chi*, ma *come*

`ct:regola` è stato aggiunto al grafo per questa traccia. Diceva già quale
agente aveva prodotto una menzione; ora dice anche con quale regola:

```
gazetteer:scompenso cardiaco        ← corrispondenza di vocabolario
icd:termine_esatto                  ← il codice viene da un titolo ICD esatto
icd:generalizzazione_ambigua        ← il codice è una generalizzazione
llm:deepseek/deepseek-v4.1-flash    ← lo ha proposto un modello
```

È la differenza fra un codice certo e uno che qualcuno dovrebbe guardare — e lo
step 6 ha misurato che quella differenza conta: **gli errori esclusivi della
pipeline A arrivano già codificati, 9 su 9**, contro uno solo fra quelli di B.
Un codice sbagliato che sembra certo è l'errore più pericoloso del progetto, e
ora la traccia lo espone.

### Due indicazioni indipendenti restano due

```
  A10BK  inibitori del co-trasportatore SGLT-2
    └─ indicazione, classe I — quarto pilastro dello scompenso
       └─ condizione I50.9 ← menzione A, Anamnesi 21–39
    └─ indicazione, classe I — diabete tipo 2 con malattia cardiovascolare
       └─ condizione E11   ← menzione A, Anamnesi 168–190
```

Due ragioni citabili, due condizioni diverse, due punti diversi del referto. Un
sistema che le fondesse in una perderebbe proprio ciò che rende forte la
proposta.

### Quando non c'è catena, lo dice

Il 40% delle prescrizioni di dimissione non è cardiologia e nessuna linea guida
cardiologica lo regola. Per quelle proposte la traccia dichiara:

> *Nessuna indicazione citata: la proposta viene dalla co-occorrenza misurata
> sul corpus, non da una regola.*

«Non so perché, ma in questo reparto si fa» è **un'informazione diversa** da una
raccomandazione citata, e confonderle sarebbe la bugia più facile da raccontare.

---

## 4. Perché il filtro e il ranker continuano a *non* passare dal grafo

Il sistema legge le uscite delle pipeline in due forme, e la divisione è voluta.
Misurata sulla macchina del progetto:

| | costo |
|---|---|
| costruzione del grafo di un paziente | 2,7 ms |
| **una interrogazione SPARQL** | **12,43 ms** |
| una lettura da dizionario | 0,073 µs |
| rapporto | ~170 000× |

Lo step 8 valuta **5 863 prescrizioni**: in SPARQL sarebbero 73 secondi di sole
interrogazioni, per ottenere esattamente gli stessi fatti.

La divisione che ne segue:

* **gli strati che decidono** — filtro e ranker — leggono la proiezione
  compatta. Girano migliaia di volte e non hanno bisogno di navigare;
* **lo strato che spiega** — la traccia — interroga il grafo. Gira una volta per
  ogni domanda che una persona pone, e ha bisogno esattamente di navigare.

### Il rischio che questa divisione apre, e la guardia

Due proiezioni della stessa sorgente possono allontanarsi in silenzio. Se il
grafo vedesse fatti che il filtro non vede, la traccia mostrerebbe la
provenienza di una raccomandazione decisa su altro — l'errore peggiore
possibile, perché renderebbe **falsa proprio la spiegazione**.

`TestLeDueProiezioniNonDivergono` è la guardia: verifica che i codici che il
filtro considera fatti del paziente siano esattamente quelli che il grafo
asserisce come affermati e riferiti al paziente. E verifica il rovescio — che
ciò che il filtro scarta resti **nel grafo, marcato**, perché il vincolo del
progetto è conservare, non cancellare: è così che si può controllare che una
condizione sia stata scartata per la ragione giusta.

---

## 5. Il testo clinico non entra nelle triple

Il grafo è un artefatto che può circolare; il testo verbatim di un referto no.
`aggiungi_menzione` scrive campo, offset, stato, soggetto, agente e regola —
**mai il testo**. Chi ha i dati grezzi lo ritrova dagli offset.

La traccia deve però mostrarlo, altrimenti l'anello più utile diventa una coppia
di numeri. La soluzione è che il grafo di un paziente della demo, che non viene
mai scritto su disco, porti i testi in un indice **fuori dalle triple**. Così la
regola resta vera per ogni grafo che possa circolare, e un test la fissa:
`test_il_testo_clinico_NON_entra_nelle_triple` verifica entrambe le metà — il
testo non è fra i letterali, e la traccia lo mostra lo stesso.

---

## 6. Come vederla

```
python3 src/demo.py --esempio 1 --traccia
python3 src/demo.py --esempio 1 --traccia --motore locale   # due agenti
python3 src/demo.py --esempio 1 --json --traccia
```

Con un motore solo le asserzioni risultano sostenute da **un** agente, che è
l'informazione onesta e non una mancanza. Chiedendo anche il modello
linguistico, il deterministico resta attivo — costa zero — e il grafo mostra
allora **due agenti** dove le due pipeline vedono lo stesso punto del referto.
È esattamente ciò che `ct:numeroPipeline` esiste per rendere interrogabile.

La stessa catena è navigabile nella pagina di dimostrazione, allo stadio 05.

---

## 7. Che cosa resta aperto

- **La visualizzazione è una catena, non un grafo disegnato.** Per una
  raccomandazione la catena *è* il sottografo rilevante, e un diagramma a nodi
  con centinaia di menzioni sarebbe meno leggibile, non più. Un esploratore del
  grafo intero resta una cosa diversa, e non l'ho fatta.
- **La traccia spiega le proposte con una regola.** Per quelle apprese dal
  corpus dichiara di non avere una regola, ma non mostra *quali* ricoveri
  dell'addestramento l'hanno suggerita. Sarebbe la spiegazione naturale della
  parte statistica del ranker ibrido, e il grafo avrebbe già la forma per
  portarla.
- **Il tool MCP dello step 10** espone `sostegno_del_concetto` come strumento a
  sé (`cardio_sostegno_del_concetto`): «da dove viene questo fatto» è la domanda
  che un modello conversazionale ha bisogno di poter fare. Lo step 10 ha però
  trovato il limite: la traccia vale quanto il testo che arriva allo strumento,
  e se il modello lo parafrasa gli offset indicano parole che nessuno ha scritto.
