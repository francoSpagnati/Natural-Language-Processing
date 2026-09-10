# Indice architetturale

Documento vivo, aggiornato **a ogni step**. Dà la visione d'insieme di come i
componenti si collegano; il dettaglio di ogni step sta nel documento dedicato.

**Ultimo step completato: 5 — Pipeline C (NER + entity linking).** Le tre
pipeline sono complete e misurate; lo step 6 le confronta.

La pipeline B ha concluso la sua corsa definitiva: **198 record in 14 h 41 m**
con `qwen3:4b` in locale. Il confronto della negazione con la pipeline A ha
fatto emergere un asse mancante nello schema — l'*experiencer* di ConText — che
è stato aggiunto (schema **1.1.0**) prima di procedere al confronto, perché
altrimenti lo step 6 avrebbe misurato una differenza che non esiste.

## Indice dei documenti

| Step | Documento | Stato |
|---|---|---|
| 0 | [`00_esplorazione_dati.md`](00_esplorazione_dati.md) | ✅ completato |
| 1 | [`01_schema_e_vocabolari.md`](01_schema_e_vocabolari.md) | ✅ completato, da validare |
| 2 | [`02_terminologia_icd10.md`](02_terminologia_icd10.md) | ✅ terminologia ICD-10 estratta |
| 2 | [`02b_risoluzione_atc.md`](02b_risoluzione_atc.md) | ✅ ATC dei farmaci risolto |
| 3 | [`03_pipeline_estrazione_A.md`](03_pipeline_estrazione_A.md) | ✅ completato |
| 4 | [`04_pipeline_estrazione_B.md`](04_pipeline_estrazione_B.md) | ✅ completato |
| 5 | [`05_pipeline_estrazione_C.md`](05_pipeline_estrazione_C.md) | ✅ completato |
| 6 | `06_confronto_pipeline.md` | ⬜ da fare |
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
                                      │              confronto pipeline: step 6 ⬜
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
| `tests/test_data_loading.py` | `data_loading` | — | 0 |
| `tests/test_sonde_esplorazione.py` | `explore_dataset` | — | 0 |
| `tests/test_pipeline_b.py` | `llm_backend`, `extract_b`, `risolutori` | — | 4 |
| `tests/test_pipeline_c.py` | `silver_labels`, `ner_train`, `entity_linking` | — | 5 |

I test sono 198 in tutto e **nessuno usa la rete**: la pipeline B e' provata
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

`python3 -m unittest discover -s tests -v` — 198 test.

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
