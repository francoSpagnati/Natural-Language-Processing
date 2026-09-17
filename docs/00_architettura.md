# Indice architetturale

Il documento d'ingresso della cartella `docs/`. Dice come i pezzi si
collegano, che cosa ogni step ha trovato e che cosa resta aperto; il dettaglio
è nel documento di ciascuno step. La relazione completa è il
[`README.md`](../README.md); il codice è spiegato in
[`guida_al_codice.md`](guida_al_codice.md); il brief è in [`brief.md`](brief.md).

**Stato: tutti i dodici step sono completati.** 472 test, nessuno usa la rete.

---

## 1. Che cosa fa il sistema

Legge referti cardiologici italiani, ne estrae lo stato clinico, lo codifica
in **ICD-10** e **ATC**, lo mette in un knowledge graph con la provenienza di
ogni fatto, e propone la terapia di dimissione passando da un filtro di
sicurezza simbolico e da un ordinamento misurato contro le decisioni vere
dei cardiologi. Il tutto è esposto come strumento MCP a un modello
conversazionale, con una traccia che dice *per quali parole del referto* una
proposta esiste.

```text
referto grezzo ─► tre pipeline di estrazione ─► StatoPaziente ─► grafo di provenienza (PROV-O, 1,2 M triple)
                   A deterministica                   │                       ▲
                   B modello linguistico              ▼                       │ «da dove viene?»
                   C NER + entity linking     filtro simbolico ─► ranker ─► proposta + traccia ─► server MCP
                                              (step 8)            (step 9)   (9bis, 9ter)         (step 10)
kb/conoscenza.ttl (27 indicazioni, 12 controindicazioni, con fonte) ──► letto da filtro, ranker e traccia
```

Tre pipeline e non una, perché lo scopo è **confrontare metodi di
estrazione**. Il filtro è **simbolico per vincolo** — mai modello, mai
dataset — perché una regola di sicurezza deve poter essere contestata da un
clinico riga per riga.

---

## 2. La tesi, in sei righe

1. **Su un campo strutturato il metodo più semplice vince.** Il parser legge
   la terapia d'ingresso al 100%; il modello linguistico al 99,3%, pagando.
   L'LLM va riservato al testo libero (step 4, 6).
2. **Nessuna pipeline da sola descrive il paziente.** Richiamo sulle
   condizioni: gazetteer 19,5%, NER 19,9%, LLM 70,1%. Il grafo esiste per
   tenerle insieme con la provenienza (step 6bis, 7).
3. **La verità di riferimento era già nei dati.** La terapia di dimissione è
   la decisione vera di un cardiologo, su 841 ricoveri, gratis (step 9).
4. **Sapere che cosa si prescrive in questo reparto vale più che sapere la
   medicina.** Il 40,4% delle prescrizioni non è cardiologia; il ranker a
   linee guida ha un tetto per costruzione e il modello linguistico lo prende
   in pieno (step 9, 11).
5. **Il miglior ranker non è misurabilmente migliore di un contatore.** In
   F1 per livello ATC ibrido e frequenza sono alla pari a ogni livello
   (differenze fra −3 e +1 punti, dentro il rumore); l'ibrido centra più
   spesso *almeno una* aggiunta (top-5: 74,5% contro 66,8% alla sostanza).
   Il simbolico ha la precisione più alta e il richiamo più basso (step 11).
6. **Le garanzie valgono fino al confine dello strumento.** Un modello
   conversazionale davanti al sistema può invertire un fatto nella parafrasi
   («iperteso» → «ipotensione»), e il server non se ne accorge (step 10).

---

## 3. Gli step

| step | documento | che cosa ha trovato |
| --- | --- | --- |
| 0 | [`00_esplorazione_dati.md`](00_esplorazione_dati.md) | 1 000 referti; i campi di terapia sono liste con delimitatori, l'anamnesi è prosa; i derivati passati per un LLM sono scartati |
| 1 | [`01_schema_e_vocabolari.md`](01_schema_e_vocabolari.md) | `StatoPaziente` in Pydantic con tre stati e il soggetto; 406 principi + 923 marchi, 249 condizioni candidate |
| 2 | [`02_terminologia_icd10.md`](02_terminologia_icd10.md) | 10 803 codici ICD-10 dal PDF ufficiale; il confronto di stringhe copre il 18% e sbaglia polarità |
| 2b | [`02b_risoluzione_atc.md`](02b_risoluzione_atc.md) | 94% dei farmaci risolti ad ATC via AIFA, cascata di sei strategie, ogni voce con metodo e fonte |
| 3 | [`03_pipeline_estrazione_A.md`](03_pipeline_estrazione_A.md) | gazetteer + ConText riscritto per l'italiano; precisione alta, richiamo basso |
| 4 | [`04_pipeline_estrazione_B.md`](04_pipeline_estrazione_B.md) | citazione letterale come rilevatore di allucinazioni; cinque difetti su sette erano del prompt; 1 000 record per 1,65 $ |
| 5 | [`05_pipeline_estrazione_C.md`](05_pipeline_estrazione_C.md) | NER su silver trova di più e non sa codificarlo; il pre-addestrato italiano: richiamo 51,7%, precisione 31,0%, nessun codice |
| 6 | [`06_confronto_pipeline.md`](06_confronto_pipeline.md) | nessuna vince; gli errori di A arrivano già codificati 7 su 8; il soggetto mancante scoperto dal flutter del feto |
| 6b | [`06b_riferimento_annotato.md`](06b_riferimento_annotato.md) | 25 referti annotati: richiamo 19,5 / 70,1 / 19,9%; lo zero di B sui farmaci era mio; rumore di fondo 2 punti |
| 7 | [`07_knowledge_graph.md`](07_knowledge_graph.md) | `kb/conoscenza.ttl` (il grafo clinico del brief) + grafo di provenienza da 1,2 M triple; il consenso a tre del 46,6% era 14,8% |
| 8 | [`08_filtro_sicurezza.md`](08_filtro_sicurezza.md) | 5 863 prescrizioni: 91,3% ammesse, 4 vietate; **principio del fatto mancante**; casi avversari 14 su 20 |
| 9 | [`09_ranker.md`](09_ranker.md) | copiare l'ingresso fa 63,6%; sulle aggiunte ibrido, frequenza, simbolico, LLM |
| 9b | [`09b_demo.md`](09b_demo.md) | demo su pazienti nuovi; tre difetti trovati solo end-to-end; `--stato` entra dal confine del brief |
| 9c | [`09c_traccia.md`](09c_traccia.md) | «da dove viene questo fatto» in SPARQL, dalla regola in `kb/` alle parole del referto |
| 10 | [`10_tool_mcp.md`](10_tool_mcp.md) | 6 strumenti di sola lettura (a testo e a `StatoPaziente`), 2 client, 10 domande: 9/10, 6/6; la parafrasi contata |
| 11 | [`11_valutazione.md`](11_valutazione.md) | P/R/F1 per i 5 livelli ATC e top-5, 5 pieghe, bootstrap, controllo casuale, per pipeline, spiegabilità, LLM su 841 |

Notebook: [`01_analisi_esplorativa`](../notebooks/01_analisi_esplorativa.ipynb)
(step 0), [`02_confronto_pipeline`](../notebooks/02_confronto_pipeline.ipynb)
(step 6), [`03_knowledge_graph`](../notebooks/03_knowledge_graph.ipynb) (step 7),
[`04_ranker`](../notebooks/04_ranker.ipynb) (step 9).

---

## 4. I numeri, con l'incertezza

Misura: la **terapia proposta** (ingresso continuato + 5 classi nuove)
contro la **terapia di dimissione**, precisione / richiamo / F1 a ogni
livello ATC. Validazione incrociata a 5 pieghe sugli **841** ricoveri, unità
= sostanza; intervalli al 95% da 1 000 ricampionamenti dei ricoveri,
differenze appaiate. Sotto, P / R / F1 in %; la tabella completa a cinque livelli è nel doc 11.

| ranker · P / R / F1 | 1° `C` | 3° `C07A` | 5° `C07AB07` | top-5 al 5° |
| --- | --- | --- | --- | --- |
| casuale, seme fisso | 63,3 / 86,4 / 70,9 | 46,1 / 71,0 / 54,3 | 37,0 / 61,2 / 44,9 | 10,8% |
| continuità della terapia | 85,8 / 82,6 / 81,5 | 62,7 / 71,0 / 64,4 | 39,4 / 64,1 / 47,5 | 31,7% |
| simbolico, 27 indicazioni ESC | **90,0** / 80,8 / 82,5 | **68,6** / 70,3 / 67,1 | 38,8 / 63,5 / 46,9 | 25,4% |
| frequenza, non guarda il paziente | 84,2 / 92,3 / **86,1** | 65,6 / 82,6 / **70,5** | 47,4 / 75,3 / 56,2 | 66,8% |
| **ibrido**, indicazioni + co-occorrenza | 79,8 / **92,8** / 83,7 | 63,2 / **82,9** / 69,2 | 47,9 / **76,2** / **56,9** | **74,5%** |
| `deepseek-v4.1-flash`, unità classe (1° e 4°) | 88,8 / 81,1 / 82,1 | 42,2 / 69,5 / 51,0 | — | — |

| differenza appaiata di F1 | 1° | 5° |
| --- | --- | --- |
| **ibrido − frequenza** | [−2,9, −2,0] | [+0,1, +1,2] — dentro il rumore a ogni livello |
| ibrido − simbolico | [−0,1, +2,6] | **[+9,2, +10,9]** |
| ibrido − frequenza, top-5 | [+1,4, +4,1] | **[+4,7, +10,8]** |
| `deepseek` − frequenza (unità classe, 1° e 4°) | [−5,1, −2,4] | [−9,3, −7,3] |

Altri numeri che decidono il disegno:

| | |
| --- | --- |
| referti con terapia di dimissione codificata | **841** su 1 000 |
| prescrizioni di dimissione non cardiologiche | **40,4%** |
| filtro su 5 863 prescrizioni | 91,3% ammesse, 8,6% da verificare, **4** vietate; casi avversari 14 su 20 |
| proposte centrate con un'indicazione citabile | frequenza 33,9%, ibrido 37,2%, simbolico 74,1% |
| l'estrazione sul ranking (F1 ibrido al 5°, da A / B / C) | 56,9 / 56,9 / 56,9 |
| interrogazione SPARQL / lettura da dizionario | 12,43 ms / 0,073 µs |
| speso in inferenza a pagamento | **4,79 $**, budget chiuso |

**Rumore di fondo del progetto: due punti percentuali.** Una differenza più
piccola non è un risultato.

---

## 5. Che cosa resta aperto

- **Il riferimento annotato è di un solo annotatore**, che è anche l'autore:
  progetto individuale, limite dichiarato.
- **Il richiamo del filtro è limitato dal vocabolario chiuso** («aspirina»,
  «ASA» non risolvono): ora dichiarato come fatto mancante; un filtro reale
  cercherebbe nel registro AIFA a runtime.
- **Le interazioni farmaco-farmaco non ci sono** (Wikidata P769 ne offre
  4 372: prima estensione).
- **La parafrasi è contata, non impedita**: la difesa vera è un `resource`
  MCP che entra senza passare dal modello.

---

## 6. I vincoli, e perché

1. **Solo dati grezzi.** Le varianti già passate per un LLM sono scartate.
2. **Ogni mappatura da una knowledge base citabile** — AIFA, ICD-10 2019,
   ESC. Una voce non coperta si marca, non si riempie.
3. **Si conserva tutto.** Le voci non risolte restano marcate.
4. **Il dataset non si versiona.** È dell'ospedale; il server MCP lavora sul
   testo che riceve, non su un archivio.
5. **Sicurezza sempre simbolica.** Il filtro non impara dal dataset e non
   chiede a un modello.
6. **Tre esiti, non due.** Ammesso / da verificare / vietato.
7. **Una regola che richiede un fatto che il sistema non sa stabilire
   segnala, non vieta.** Cinque ricorrenze.
8. **Prima il modello locale.** Si paga solo con token misurati; mai l'API
   Anthropic.

---

## 7. Come si riproduce

```bash
python3 -m unittest discover -s tests -q          # 472 test, nessuna rete
python3 src/demo.py --esempio 1 --traccia         # un paziente dall'inizio alla fine
python3 src/kb_build.py --figura                  # il grafo di conoscenza e la figura
python3 src/valuta_gerarchica.py --sostanza       # step 11 (gratis); --llm --llm-solo-cache, --stratifica, --cartella
python3 src/mcp_client_locale.py --strumenti      # handshake col server MCP
claude mcp add cardio -- python3 src/mcp_server.py
```

I dati non sono versionati: `data/raw/` è l'export grezzo, `data/external/`
le knowledge base scaricabili con `src/fetch_external_kb.py` (manifest in
`kb/`), `data/interim/` gli intermedi e la cache delle risposte LLM,
`data/processed/` le uscite di ogni step. Le corse con modello linguistico
sono in cache per impronta di richiesta: ogni metrica nuova sulle stesse
risposte si ricalcola gratis; chi rilancia deve nominare il modello
(`qwen3.5:4b`, non il predefinito), che fa parte della chiave.

---

## 8. Moduli

| modulo | step | ruolo |
| --- | --- | --- |
| `data_loading.py`, `explore_dataset.py`, `fetch_external_kb.py` | 0 | caricamento, sonde, knowledge base con manifest |
| `schema.py`, `build_vocabularies.py` | 1 | `StatoPaziente`; vocabolari chiusi |
| `extract_icd10.py`, `normalize_drugs.py` | 2, 2b | terminologia ICD-10 dal PDF; farmaco → ATC |
| `gazetteer.py`, `context_it.py`, `extract_a.py` | 3 | pipeline A |
| `llm_backend.py`, `extract_b.py` | 4 | backend con cache; pipeline B |
| `silver_labels.py`, `ner_train.py`, `ner_infer.py`, `entity_linking.py`, `extract_c.py`, `sonda_ner_preaddestrato.py` | 5 | pipeline C e la prova sul pre-addestrato |
| `risolutori.py` | 3–5 | codifica identica per tutte le pipeline |
| `confronto.py`, `rianalizza.py`, `riferimento.py` | 6, 6b | confronto; riferimento annotato |
| `kb_build.py`, `conoscenza.py` | 7 | scrive e legge `kb/conoscenza.ttl` |
| `grafo.py`, `interroga.py`, `traccia.py` | 7, 9c | grafo di provenienza, SPARQL, traccia |
| `filtro.py` | 8 | filtro simbolico, tre esiti |
| `ranker.py`, `valuta_ranker.py`, `demo.py` | 9, 9b | ranker; valutazione; demo |
| `mcp_server.py`, `mcp_client_locale.py`, `valuta_mcp.py` | 10 | server MCP, host locale, dieci domande |
| `valuta_gerarchica.py` | 11 | P/R/F1 per livello, top-k, pieghe, bootstrap, controllo casuale, spiegabilità |

Ogni modulo ha il suo file di test in `tests/`, tutti su dati sintetici.
