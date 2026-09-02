# Indice architetturale

Documento vivo, aggiornato **a ogni step**. Dà la visione d'insieme di come i
componenti si collegano; il dettaglio di ogni step sta nel documento dedicato.

**Ultimo step completato: 1.** Step 2 avviato: terminologia ICD-10 estratta, collegamento delle condizioni in attesa di una decisione (vedi `02_terminologia_icd10.md`, § 6).

## Indice dei documenti

| Step | Documento | Stato |
|---|---|---|
| 0 | [`00_esplorazione_dati.md`](00_esplorazione_dati.md) | ✅ completato |
| 1 | [`01_schema_e_vocabolari.md`](01_schema_e_vocabolari.md) | ✅ completato, da validare |
| 2 | [`02_terminologia_icd10.md`](02_terminologia_icd10.md) | 🟡 parte 1 fatta, decisione aperta |
| 3 | `03_pipeline_estrazione_A.md` | ⬜ da fare |
| 4 | `04_pipeline_estrazione_B.md` | ⬜ da fare |
| 5 | `05_pipeline_estrazione_C.md` | ⬜ da fare |
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
                  ATC (AIFA) / ICD (da scegliere)      │
                     step 2 ⬜                          │
                          │                            │
                          └───────────┬────────────────┘
                                      ▼
                    ┌─────────── tre pipeline di estrazione ───────────┐
                    ▼                 ▼                                ▼
             A: deterministica   B: LLM locale            C: NER + Entity Linking
                 step 3 ⬜          step 4 ⬜                    step 5 ⬜
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
| `tests/test_data_loading.py` | `data_loading` | — | 0 |
| `tests/test_sonde_esplorazione.py` | `explore_dataset` | — | 0 |

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
| `data/interim/terminologia_icd10.json` | 10 803 codici + indice di 14 898 termini italiani | `src/extract_icd10.py` |
| `reports/00_esplorazione.txt` | report completo dello step 0 | rigenerato da `src/explore_dataset.py` |

## Test

`python3 -m unittest discover -s tests -v` — 55 test.

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
