# Indice architetturale

Documento vivo, aggiornato **a ogni step**. Dà la visione d'insieme di come i
componenti si collegano; il dettaglio di ogni step sta nel documento dedicato.

**Ultimo step completato: 6bis — Un riferimento annotato a mano, che misura per
la prima volta il richiamo.**

**È il risultato più importante del progetto finora, e ribalta la lettura dello
step 6.** Su 25 referti annotati a mano (619 entità) le due pipeline simboliche
**mancano quattro condizioni su cinque**:

| condizioni | precisione | **richiamo** | F1 |
|---|---|---|---|
| A (gazetteer) | 80,1% | **19,5%** | 31,4% |
| B (LLM) | 96,1% | **70,1%** | **81,1%** |
| C (NER) | 81,6% | **19,9%** | 31,9% |

La ragione è strutturale: il vocabolario di A è costruito dai termini ICD-10 e C
è addestrata sulle etichette che A produce, quindi entrambe trovano **solo ciò
che la knowledge base già conosce**. Nella prosa cardiologica la maggior parte
delle condizioni non è scritta in forma da nomenclatura — «insufficienza paraprotesica» — e resta invisibile. La copertura ICD del 99,4% di A, che sembrava un
punto di forza, è il sintomo: il suo denominatore è ristretto a un quinto della
realtà clinica.

**Sui farmaci citati nella prosa il quadro si ribalta esattamente**: A 65,0% e C
70,0% di richiamo, **B zero su sessanta**. Il modello si concentra sui campi di
terapia e nell'anamnesi non segnala farmaci, perdendo le sospensioni, le riduzioni
e le intolleranze che i campi strutturati non contengono per definizione.

Da qui la decisione per lo step 7: il knowledge graph si costruisce da **tutte e
tre le pipeline, con la provenienza**. Non è prudenza, è l'unica scelta che non
butti via l'80% delle condizioni oppure il 100% dei farmaci narrati.

Il riferimento ha **un solo annotatore**, che ha anche scritto le pipeline. I
limiti — cecità imperfetta e una passata di correzione dopo aver visto i
disaccordi — sono documentati uno per uno in `06b`, non nascosti.

---

**Step 6 — Confronto fra le tre pipeline, su tutti e 1 000 i record.**

Il risultato che conta non è quale pipeline vinca — nessuna vince, e le tre
precisioni distano fra loro meno dell'errore standard del campione. Conta che i
tre **profili di errore** sono qualitativamente diversi: **tutti gli errori
esclusivi della pipeline A portano con sé un codice ICD assegnato con sicurezza
(9 su 9)**, contro uno solo fra quelli di B e nessuno fra quelli di C. Il
gazetteer riconosce e codifica in un solo passo, quindi un match sbagliato è già
codificato; le altre due riconoscono prima e collegano dopo, e un riconoscimento
sbagliato resta visibile come irrisolto. È la distinzione che il filtro di
sicurezza dello step 8 deve tenere presente.

**La pipeline B è stata rieseguita** dopo le correzioni, e `src/rianalizza.py`
affianca le due corse segnando riga per riga l'esito su bersagli dichiarati
*prima* del rilancio. **199 record su 200** (erano 198), sette bersagli su otto
migliorati: i record oltre il tetto di 60 elementi passano da 14 a **zero**, la
terapia di dimissione recuperata da 376 a **756 voci** (dal 32,3% al 50,5%), le
menzioni non ancorate dal 13,0% al **9,5%**.

L'unica riga peggiorata è la più istruttiva. Le allergie non ancorate salgono al
65,2%, e sono **il mio esempio nel prompt che il modello ricopia**: la stringa
`mdc` compare 105 volte fra le allergie e 45 volte, per intero, fra le
condizioni, senza esistere in nessuno di quei referti. Su 64 record che dichiarano
«allergie non note», 56 (88%) hanno comunque un'allergia estratta. L'esempio
*negativo* accanto non è mai trapelato: **un esempio positivo offre un modello da
ricopiare, e il divieto scritto sotto non lo neutralizza**. Corretto in
`04` § 7nonies; l'impronta delle istruzioni è cambiata, quindi la prossima corsa
non si mescola con questa.

L'aggiudicazione ha trovato anche un **buco vero nell'asse experiencer**: «Zia e
nonna fibrillanti» viene attribuito al paziente con codice `I48`, perché il
lessico riconosce `familiarità per` e `anamnesi familiare` ma non i nomi di
parentela diretti. È il tipo di errore peggiore per lo step 8 — condizione
giusta, codice giusto, persona sbagliata — e va chiuso prima del filtro.

**È stato aggiunto un terzo backend, `BackendOpenRouter`**, dietro la stessa
interfaccia e la stessa cache degli altri due. Il collo di bottiglia non è mai
stato il denaro ma il tempo: 235 secondi per record significano 65 ore per il
corpus intero. Il campo che rende il backend sicuro è
`provider.require_parameters`: senza di esso OpenRouter può instradare verso un
fornitore che ignora `response_format`, e la garanzia strutturale della pipeline B
diventerebbe una speranza senza che nulla lo segnali.

**La pipeline B esiste ora in due versioni, e nessuna sostituisce l'altra:**
`qwen3:4b` in locale su 199 record (13 ore, gratis) e
`deepseek/deepseek-v4.1-flash` su **1 000 record (39 minuti, 2,42 $)**. È la
prima corsa completa del progetto, e rende le tre pipeline confrontabili
sull'intero corpus.

Tenere entrambe non è ridondanza: è ciò che permette di separare **quanto di una
differenza sia del metodo e quanto della taglia del modello**. Sugli stessi 199
record, con le regole di prompt sulle condizioni identiche, la versione remota
dimezza le condizioni per record (24,3 → 17,2), azzera i duplicati da generazione
degenere (13,2% → 0,3%) e le menzioni non ancorate (7,9% → 0,5%).

**Una conclusione dello step 6 è stata ritirata.** Avevo scritto che i campi
strutturati restano al parser perché *«non è un problema di capacità ma di
affidabilità»*: il modello locale leggeva la terapia di dimissione al 50%, in
modo bimodale, e non avevo trovato nessuna discriminante fra i record letti e
quelli saltati. Il modello remoto la legge al **99,6%**. La discriminante non era
nei record ma nel modello, e cercandola solo fra le proprietà dei dati non potevo
trovarla. I campi strutturati restano comunque al parser — non più perché il
modello sbagli, ma perché una regex fa lo stesso lavoro gratis, in 0,02 secondi e
in modo deterministico.

**L'aggiudicazione è stata rifatta su 60 menzioni** della versione remota: 91,7%
± 3,6 contro il 66,7% ± 8,6 della locale. È l'unico confronto di precisione del
progetto in cui gli intervalli **non** si sovrappongono; quelli di A, B-locale e
C si sovrappongono tutti fra loro e non ordinano nulla.

**Il buco dell'asse experiencer è chiuso.** «Zia e nonna fibrillanti» riceveva
`I48` attribuito al paziente. La regola nuova è stretta di proposito, costruita
sul corpus: il 4% delle occorrenze di un termine di parentela è l'*informatore*
(«la madre riferisce»), e marcarle familiari nasconderebbe al filtro una
condizione vera del paziente — un errore peggiore, perché in direzione opposta.
Effetto: 39 condizioni su 16 639 cambiano soggetto, 17 delle quali portavano un
codice ICD.

## Indice dei documenti

| Step | Documento | Stato |
|---|---|---|
| 0 | [`notebooks/01_analisi_esplorativa.ipynb`](../notebooks/01_analisi_esplorativa.ipynb) | ✅ analisi esplorativa eseguita |
| 6 | [`notebooks/02_confronto_pipeline.ipynb`](../notebooks/02_confronto_pipeline.ipynb) | ✅ confronto con aggiudicazione manuale |
| 0 | [`00_esplorazione_dati.md`](00_esplorazione_dati.md) | ✅ completato |
| 1 | [`01_schema_e_vocabolari.md`](01_schema_e_vocabolari.md) | ✅ completato, da validare |
| 2 | [`02_terminologia_icd10.md`](02_terminologia_icd10.md) | ✅ terminologia ICD-10 estratta |
| 2 | [`02b_risoluzione_atc.md`](02b_risoluzione_atc.md) | ✅ ATC dei farmaci risolto |
| 3 | [`03_pipeline_estrazione_A.md`](03_pipeline_estrazione_A.md) | ✅ completato |
| 4 | [`04_pipeline_estrazione_B.md`](04_pipeline_estrazione_B.md) | ✅ completato |
| 5 | [`05_pipeline_estrazione_C.md`](05_pipeline_estrazione_C.md) | ✅ completato |
| 6 | [`06_confronto_pipeline.md`](06_confronto_pipeline.md) | ✅ completato |
| 6bis | [`06b_riferimento_annotato.md`](06b_riferimento_annotato.md) | ✅ richiamo misurato su 25 referti |
| 7 | `07_knowledge_graph.md` | ⬜ da fare |
| 8 | `08_motore_fase1_filtro.md` | ⬜ da fare |
| 9 | `09_motore_fase2_ranker.md` | ⬜ da fare |
| 10 | `10_tool_mcp.md` | ⬜ da fare |
| 11 | `11_valutazione.md` | ⬜ da fare |

## Architettura di destinazione

```
                          data/raw/anamnesiterapie.txt
                       (export grezzo: 857 + 143 record)
                                        │
                                 [src/data_loading.py]          ← step 0 ✅
                                        │
                          ┌─────────────┴─────────────┐
                          ▼                           ▼
                 vocabolari chiusi              testo per paziente
                 farmaci: 406 principi + 923 marchi    │
                 condizioni: 249 candidate             │
                     step 1 ✅                          │
                          │                            │
                 [normalizzazione]                     │
                  ATC via AIFA: 94% ✅                  │
                  ICD-10 italiano estratto ✅           │
                     step 2                             │
                          │                            │
                          └───────────┬────────────────┘
                                      ▼
                    ┌─────────── tre pipeline di estrazione ───────────┐
                    ▼                 ▼                                ▼
             A: deterministica   B: LLM (locale)         C: NER + Entity Linking
                 step 3 ✅          step 4 ✅                    step 5 ✅
                    │                 │                                │
                    └────── etichette silver ────────────────────────►─┘
                                      │
                                      ▼
                    StatoPaziente (src/schema.py)             ← definito allo step 1 ✅
                                      │              confronto pipeline: step 6 ✅
                                      ▼
                    ┌───── motore di raccomandazione ─────┐
                    │  Fase 1 — filtro simbolico (step 8) │ ← mai LLM, mai dataset
                    │        │                            │
                    │        ▼                            │
                    │  Fase 2 — Ranker (step 9)           │
                    │   Symbolic / Hybrid / LLM           │
                    └────────────────┬────────────────────┘
                                     │        ▲
                                     │        └── kb/*.ttl  (rdflib) ← step 7 ⬜
                                     ▼                (openFDA, Wikidata, ESC)
                          Tool MCP (step 10 ⬜)
                                     │
                                     ▼
                          Valutazione ATC gerarchica (step 11 ⬜)
```

## Moduli esistenti e dipendenze

| Modulo | Dipende da | Usato da | Step |
|---|---|---|---|
| `src/data_loading.py` | solo stdlib (`json`, `dataclasses`, `pathlib`) | tutti gli step successivi | 0 |
| `src/explore_dataset.py` | `data_loading` | nessuno (usa-e-getta, non importato dalle pipeline) | 0 |
| `src/fetch_external_kb.py` | solo stdlib (`urllib`, `hashlib`) | step 2 (normalizzazione), step 7 (KG) | 0 |
| `src/verifica_ponte_aifa.py` | fonti AIFA + output di `explore_dataset` | nessuno (verifica di provenienza) | 0 |
| `src/schema.py` | `pydantic` | **tutti** gli step successivi: e' il contratto dati | 1 |
| `src/build_vocabularies.py` | `data_loading`, `explore_dataset`, `schema`, fonti AIFA | step 2 (normalizzazione), step 3 (gazetteer) | 1 |
| `src/extract_icd10.py` | `pdftotext` (poppler), PDF ICD-10 | step 3 (gazetteer condizioni), step 5 (entity linking) | 2 |
| `src/normalize_drugs.py` | `schema`, vocabolario, fonti AIFA | step 7 (KG), step 8 (filtro), step 11 (metrica ATC) | 2 |
| `src/gazetteer.py` | `spacy`, vocabolari chiusi | step 3, step 5 (candidati per l'EL) | 3 |
| `src/context_it.py` | nessuna (solo stdlib) | step 3, step 5, **tutte le pipeline** (asse experiencer) | 3 |
| `src/extract_a.py` | tutti i precedenti | step 5 (etichette silver), step 6, step 8 | 3 |
| `src/risolutori.py` | `schema`, mappatura ATC, terminologia ICD | **tutte** le pipeline: la normalizzazione dev'essere identica | 4 |
| `src/llm_backend.py` | solo stdlib (`urllib`, `hashlib`) | step 4, step 9 (LLMRanker), step 10 | 4 |
| `src/extract_b.py` | `llm_backend`, `risolutori`, `gazetteer`, `schema` | step 6 (confronto) | 4 |
| `src/entity_linking.py` | `risolutori`, terminologia ICD | pipeline A e C: la codifica dev'essere identica | 5 |
| `src/silver_labels.py` | uscita di `extract_a` | `ner_train`, `ner_infer` | 5 |
| `src/ner_train.py` | `torch`, `transformers`, bioBIT | produce il modello in `data/processed/ner_it/` | 5 |
| `src/ner_infer.py` | il modello addestrato | `extract_c` | 5 |
| `src/extract_c.py` | `ner_infer`, `entity_linking`, `extract_a` (parti condivise) | step 6 (confronto) | 5 |
| `src/migra_soggetto.py` | `data_loading`, `risolutori`, `schema` | migrazione una-tantum dello schema 1.0.0 → 1.1.0 | 5 |
| `src/confronto.py` | `risolutori`, uscite delle tre pipeline | step 6 (confronto), notebook 02 | 6 |
| `src/rianalizza.py` | `data_loading`, uscite di B | rimisura e affianca due corse qualsiasi di B | 6 |
| `src/riferimento.py` | `confronto`, annotazioni a mano | step 6bis, step 11 (valutazione) | 6bis |
| `tests/test_data_loading.py` | `data_loading` | — | 0 |
| `tests/test_sonde_esplorazione.py` | `explore_dataset` | — | 0 |
| `tests/test_pipeline_b.py` | `llm_backend`, `extract_b`, `risolutori` | — | 4 |
| `tests/test_pipeline_c.py` | `silver_labels`, `ner_train`, `entity_linking` | — | 5 |
| `tests/test_confronto.py` | `confronto` | — | 6 |
| `tests/test_riferimento.py` | `riferimento` | — | 6bis |
| `notebooks/01_analisi_esplorativa.ipynb` | `data_loading` | analisi esplorativa: conteggi, distribuzioni, regex commentate | 0 |
| `src/confronto.py` | `risolutori`, uscite delle tre pipeline | step 6; il knowledge graph dello step 7 ne eredita le conclusioni | 6 |
| `notebooks/02_confronto_pipeline.ipynb` | `confronto` | il confronto con i grafici e l'aggiudicazione manuale | 6 |

I test sono 219 in tutto e **nessuno usa la rete**: la pipeline B e' provata
con un backend fittizio, perche' una suite dipendente dall'API sarebbe lenta,
costosa e verde o rossa a seconda del carico dei server.

## Dati

| Percorso | Contenuto | Origine |
|---|---|---|
| `data/raw/anamnesiterapie.txt` | 1000 record (857 con terapia alla dimissione) | **export grezzo** del sistema ospedaliero, pseudonimizzato |
| `data/external/aifa/*.csv` | registro ATC in italiano, anagrafica confezioni, titolari AIC | **AIFA**, CC-BY 4.0, scaricate da `src/fetch_external_kb.py` |
| `kb/manifest_fonti.json` | URL, data, SHA-256 e scopo di ogni fonte esterna | versionato: la tracciabilità sopravvive al clone |
| `data/interim/*.csv` | vocabolari grezzi e ponte commerciale→principio | rigenerati da `src/explore_dataset.py` |
| `data/interim/vocabolario_farmaci.json` | 1 329 voci con esito del confronto AIFA e ATC candidati | `src/build_vocabularies.py` |
| `data/interim/vocabolario_condizioni.json` | 249 condizioni candidate con contesti e indizi di negazione | `src/build_vocabularies.py` |
| `data/interim/schema_stato_paziente.json` | JSON Schema generato dai modelli Pydantic | `src/build_vocabularies.py` |
| `data/external/ICD-10 2019 vol1...pdf` | ICD-10 2019 italiano, Centro Collaboratore OMS (FVG) | scaricato a mano da reteclassificazioni.it |
| `data/interim/terminologia_icd10.json` | 10 803 codici + indice di 13 642 termini italiani | `src/extract_icd10.py` |
| `data/interim/mappatura_atc.json` | 1 329 voci con ATC, metodo di risoluzione, fonte ed evidenza | `src/normalize_drugs.py` |
| `data/processed/pipeline_a/*.json` | uno `StatoPaziente` per record (1 000) | `src/extract_a.py` |
| `data/processed/pipeline_b/*.json` | uno `StatoPaziente` per record elaborato dall'LLM, più `_corsa.json` (registro con l'impronta della configurazione, che rende la corsa riprendibile) e `_riepilogo.json` (produzione misurata) | `src/extract_b.py` |
| `data/interim/cache_llm/*.json` | risposte del modello indicizzate per impronta: rendono ripetibile la valutazione | `src/llm_backend.py` |
| `data/interim/silver_ner/*.json` | etichette BIO divise per ricovero (700/150/150) | `src/silver_labels.py` |
| `data/processed/ner_it/` | modello NER addestrato e sue misure su sviluppo | `src/ner_train.py` |
| `data/processed/pipeline_c/*.json` | uno `StatoPaziente` per record dalla pipeline C | `src/extract_c.py` |
| `.env.local` | chiave API di Google AI Studio | **non versionato**, escluso da `.gitignore` |
| `data/processed/pipeline_a/*.json` | 1 000 stati paziente estratti dalla pipeline A | `src/extract_a.py` |
| `reports/00_esplorazione.txt` | report completo dello step 0 | rigenerato da `src/explore_dataset.py` |

## Test

`python3 -m unittest discover -s tests -v` — 219 test.

I test usano dati **sintetici** costruiti nel test stesso, mai il file clinico:
il dataset non è versionato, quindi chi clona il repository deve poter eseguire
i test lo stesso, e nessun dato di paziente finisce in un file su GitHub.

## Principi architetturali adottati

1. **Nessun dato derivato da LLM come fonte.** Il dataset canonico è l'export
   grezzo dell'ospedale. Le varianti già filtrate e strutturate da un LLM sono
   scartate: costruirci sopra significherebbe ereditare un'estrazione fatta da
   un altro modello, che è proprio ciò che il progetto deve implementare e
   misurare. Vale anche per il questionario clinico che quelle varianti
   aggiungevano.
2. **Ogni mapping deve venire da una knowledge base citabile.** Le conversioni
   nome commerciale → principio attivo → ATC, e condizione → ICD-10, si
   ancorano a fonti esterne riportate esplicitamente (WHO ATC/DDD, AIFA,
   openFDA, Wikidata). Le regolarità osservate nel dataset valgono come
   evidenza empirica da verificare, mai come fonte autorevole; le voci non
   coperte da alcuna fonte vanno segnalate come mapping manuali citati, non
   riempite silenziosamente.
3. **Separare caricamento e interpretazione.** `data_loading.py` non fa scelte
   cliniche: così un bug di parsing non si confonde mai con un bug di
   modellazione clinica.
4. **Misurare invece di assumere.** Le sonde di parsing sono organizzate a
   livelli e contano quante voci cadono in ciascuno: l'irregolarità dei campi è
   un numero nel report, non un'impressione.
5. **Le anomalie si accumulano, non si sollevano.** Su dati clinici reali serve
   sapere *quanti* record sono difettosi, non fermarsi al primo.
6. **Precisione prima della copertura sui vocabolari.** Il vocabolario chiuso è
   il fondamento di ogni step successivo: un nome sporco si propaga ovunque.
7. **Tre stati di conoscenza, non due.** Affermato / negato / ignoto. Il
   questionario li fornisce nativamente e collassarli perderebbe informazione
   clinica rilevante.
8. **Sicurezza clinica sempre simbolica.** La Fase 1 del motore dipenderà solo
   dalla Knowledge Graph, mai dall'LLM né dal dataset di training (step 8).
