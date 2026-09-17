# Indice architetturale

Il documento d'ingresso del progetto. Dice che cosa fa il sistema, come i pezzi
si collegano, che cosa ogni step ha trovato e che cosa resta aperto. Il
dettaglio — misure, errori corretti, decisioni — sta nel documento di ciascuno
step, linkato in tabella.

**Stato: tutti i dodici step sono completati.** 446 test, nessuno usa la rete.

---

## 1. Che cosa fa il sistema

Legge referti cardiologici italiani, ne estrae lo stato clinico, lo codifica in
**ICD-10** (condizioni) e **ATC** (farmaci), lo mette in un knowledge graph con
la provenienza di ogni fatto, e propone la terapia di dimissione passando da un
filtro di sicurezza simbolico e da un ordinamento misurato. Il tutto è esposto
come strumento a un modello conversazionale, con una traccia che dice *per quali
parole del referto* una proposta esiste.

```
 referto grezzo ─► tre pipeline di estrazione ─► StatoPaziente ─► knowledge graph
                     A deterministica                              (PROV-O, 1,2 M triple)
                     B modello linguistico                                │
                     C NER + entity linking                               ▼
                                                    filtro simbolico ─► ranker ─► proposta
                                                    (step 8)           (step 9)     + traccia (9ter)
                                                                                    │
                                                              server MCP (step 10) ◄┘
```

Tre pipeline e non una, perché lo scopo del progetto è **confrontare metodi di
estrazione**, non solo estrarre. Il filtro è **simbolico per vincolo** — mai
modello linguistico, mai dataset — perché una regola di sicurezza deve poter
essere contestata da un clinico riga per riga.

---

## 2. La tesi, in sei righe

1. **Su un campo strutturato il metodo più semplice vince.** Il parser
   deterministico legge la terapia d'ingresso al 100%; il modello linguistico al
   99,3%, pagando. L'LLM va riservato al testo libero (step 4, 6).
2. **Nessuna pipeline da sola descrive il paziente.** Richiamo sulle condizioni:
   gazetteer 19,5%, NER 19,9%, LLM 70,1%. Il grafo esiste per tenerle insieme
   con la provenienza (step 6bis, 7).
3. **La verità di riferimento era già nei dati.** La terapia di dimissione è la
   decisione vera di un cardiologo, su 841 ricoveri, gratis (step 9).
4. **Sapere che cosa si prescrive in questo reparto vale più che sapere la
   medicina.** Il 40,4% delle prescrizioni non è cardiologia; il ranker a linee
   guida ha un tetto per costruzione, e il modello linguistico lo prende in
   pieno (step 9, 11).
5. **Il miglior ranker non è misurabilmente migliore di un contatore.** Su
   tutti gli 841 ricoveri, in validazione incrociata: ibrido 48,5%, frequenza
   47,5%, differenza [−1,5%, +3,4%] al 95%. Un punto, dentro il rumore
   (step 11).
6. **Le garanzie valgono fino al confine dello strumento.** Un modello
   conversazionale davanti al sistema può invertire un fatto nella parafrasi
   («iperteso» → «ipotensione»), e il server non se ne accorge (step 10).

---

## 3. Gli step

| step | documento | che cosa ha trovato |
|---|---|---|
| 0 | [`00_esplorazione_dati.md`](00_esplorazione_dati.md) | 1 000 referti; i campi di terapia sono liste con delimitatori, l'anamnesi è prosa |
| 1 | [`01_schema_e_vocabolari.md`](01_schema_e_vocabolari.md) | `StatoPaziente` in Pydantic; 406 principi + 923 marchi, 249 condizioni candidate |
| 2 | [`02_terminologia_icd10.md`](02_terminologia_icd10.md) | 10 803 codici ICD-10 dal PDF ufficiale italiano |
| 2b | [`02b_risoluzione_atc.md`](02b_risoluzione_atc.md) | 94% dei farmaci risolti ad ATC via AIFA, ogni voce con metodo e fonte |
| 3 | [`03_pipeline_estrazione_A.md`](03_pipeline_estrazione_A.md) | pipeline deterministica: gazetteer + ConText italiano |
| 4 | [`04_pipeline_estrazione_B.md`](04_pipeline_estrazione_B.md) | pipeline LLM: 0 menzioni non ancorate su 552; il mio esempio nel prompt ricopiato 105 volte |
| 5 | [`05_pipeline_estrazione_C.md`](05_pipeline_estrazione_C.md) | NER (bioBIT) su etichette silver di A: non trova ciò che il gazetteer non trova |
| 6 | [`06_confronto_pipeline.md`](06_confronto_pipeline.md) | nessuna vince; gli errori esclusivi di A arrivano già codificati, 9 su 9 |
| 6b | [`06b_riferimento_annotato.md`](06b_riferimento_annotato.md) | 25 referti annotati a mano: il richiamo misurato per la prima volta |
| 7 | [`07_knowledge_graph.md`](07_knowledge_graph.md) | 1,2 M triple PROV-O/SKOS; il «consenso a tre» del 46,6% era una lettura contata tre volte |
| 8 | [`08_filtro_sicurezza.md`](08_filtro_sicurezza.md) | 5 863 prescrizioni: 91,3% ammesse, 4 vietate; **principio del fatto mancante** |
| 9 | [`09_ranker.md`](09_ranker.md) | copiare l'ingresso fa 63,6%; sulle aggiunte (divisione singola) ibrido 53,1%, contatore 49,5%, LLM 24,0% |
| 9b | [`09b_demo.md`](09b_demo.md) | demo su pazienti nuovi; tre difetti trovati solo end-to-end |
| 9c | [`09c_traccia.md`](09c_traccia.md) | «da dove viene questo fatto» risposto in SPARQL; 12,43 ms contro 0,073 µs |
| 10 | [`10_tool_mcp.md`](10_tool_mcp.md) | 6 strumenti di sola lettura (a testo e a stato paziente), 2 client; il corpus non passa di qui |
| 11 | [`11_valutazione.md`](11_valutazione.md) | i 4–7 punti erano aritmetica; bootstrap e 5 pieghe: ibrido e frequenza indistinguibili |

Notebook: [`01_analisi_esplorativa`](../notebooks/01_analisi_esplorativa.ipynb)
(step 0), [`02_confronto_pipeline`](../notebooks/02_confronto_pipeline.ipynb)
(step 6), [`03_knowledge_graph`](../notebooks/03_knowledge_graph.ipynb) (step 7),
[`04_ranker`](../notebooks/04_ranker.ipynb) (step 9).

---

## 4. I numeri, con l'incertezza dove c'è

Compito: le **2 075 classi ATC aggiunte** alla dimissione. Validazione
incrociata a 5 pieghe su tutti gli **841** ricoveri, richiamo@5; intervalli al
95% da 1 000 ricampionamenti dei ricoveri.

| ranker | richiamo@5 | intervallo |
|---|---|---|
| casuale, seme fisso | 5,3% | [4,0%, 6,5%] |
| continuità della terapia | 10,6% | [9,1%, 12,2%] |
| simbolico, 27 indicazioni ESC citate | 23,7% | [21,5%, 25,8%] |
| frequenza, non guarda il paziente | 47,5% | [44,8%, 50,3%] |
| **ibrido**, indicazioni + co-occorrenza | **48,5%** | [45,7%, 51,1%] |

| differenza appaiata | intervallo | |
|---|---|---|
| **ibrido − frequenza** | **[−1,5%, +3,4%]** | include lo zero |
| ibrido − simbolico | [+21,7%, +28,0%] | esclude lo zero |
| frequenza − simbolico | [+20,9%, +26,9%] | esclude lo zero |

I due ranker con modello linguistico sono misurati solo sulla divisione singola
(244 ricoveri di prova), perché rimisurarli costerebbe 600 chiamate nuove:
`deepseek-v4.1-flash` **24,0%** [19,9%, 28,9%], `qwen3.5:4b` **19,7%** [15,9%,
23,8%]; contro la frequenza sulla stessa divisione, `deepseek` sta a
[−31,5%, −19,6%]. Sulla stessa divisione l'ibrido faceva 53,1%: era un campione
favorevole a chi impara.

Altri numeri che decidono il disegno:

| | |
|---|---|
| referti con terapia di dimissione codificata | **841** su 1 000 |
| prescrizioni di dimissione non cardiologiche | **40,4%** |
| filtro step 8 su 5 863 prescrizioni | 91,3% ammesse, 8,6% da verificare, **4** vietate |
| codici fuori elenco del ranker LLM | remoto 18 (tutti reali), locale 40 (**15 inesistenti**) |
| interrogazione SPARQL / lettura da dizionario | 12,43 ms / 0,073 µs |
| speso su OpenRouter | **4,4494 $** su 5 |

**Rumore di fondo del progetto: due punti percentuali.** Una differenza più
piccola non è un risultato.

---

## 5. Che cosa resta aperto

Tre cose, e sono decisioni, non lavoro rimasto a metà.

1. **Il ranker con modello linguistico non è in validazione incrociata.**
   Rimisurarlo su tutti gli 841 costerebbe circa 600 chiamate: 35 centesimi sul
   remoto, quattro ore di CPU sul locale.
2. **Quattro corse non sono una valutazione del server MCP.** Servirebbero dieci
   domande con l'esito atteso, contando quante volte il modello sceglie lo
   strumento giusto e passa il testo intatto. Con ollama costa zero denaro e
   circa un'ora di macchina.
3. **La parafrasi resta il limite non risolto dello step 10.** L'unica difesa
   vera è far entrare il testo *senza passare dal modello* — un `resource` MCP
   che il client apre da file, con il modello che riceve solo l'identificatore.
   È un disegno diverso, non un parametro.

Più una manutenzione: **la chiave OpenRouter va ruotata a fine progetto**, perché
è comparsa in chiaro in una conversazione.

---

## 6. I vincoli, e perché

1. **Solo dati grezzi.** Le varianti già passate per un LLM sono scartate:
   costruirci sopra significherebbe misurare un'estrazione fatta da altri.
2. **Ogni mappatura da una knowledge base citabile** — AIFA, ICD-10 2019 Elenco
   Sistematico, WHO ATC/DDD. Una voce non coperta si marca, non si riempie.
3. **Si conserva tutto.** Le voci non risolte restano marcate: servono a vedere
   che cosa è stato mancato.
4. **Il dataset non si versiona.** È dell'ospedale, pseudonimizzato ma non
   nostro da ridistribuire: `data/` è in `.gitignore`, e il server MCP lavora
   sul testo che riceve, non su un archivio.
5. **Sicurezza sempre simbolica.** Il filtro non impara dal dataset e non chiede
   a un modello.
6. **Tre esiti, non due.** Ammesso / da verificare / vietato: un falso blocco
   nega una terapia, un falso permesso lascia passare una controindicazione.
7. **Una regola che richiede un fatto che il sistema non sa stabilire può
   segnalare, non vietare.** Trovato allo step 8 (pacemaker), ricomparso allo
   step 9 (allergia di classe) e allo step 10 (estrazione vuota).
8. **Prima il modello locale.** Si paga solo con token misurati alla mano; mai
   l'API Anthropic.

---

## 7. Come si riproduce

```bash
python3 -m unittest discover -s tests -q          # 446 test, nessuna rete
python3 src/demo.py --esempio 1 --traccia         # un paziente dall'inizio alla fine
python3 src/valuta_ranker.py                      # step 9 senza LLM, gratis
python3 src/valuta_gerarchica.py                  # step 11 con bootstrap, gratis
python3 src/mcp_client_locale.py --strumenti      # handshake col server MCP
claude mcp add cardio -- python3 src/mcp_server.py
```

I dati non sono versionati: `data/raw/` è l'export grezzo, `data/external/` le
knowledge base scaricabili con `src/fetch_external_kb.py` (manifest con URL,
data e SHA-256 in `kb/`), `data/interim/` gli intermedi e la cache delle
risposte LLM, `data/processed/` le uscite di ogni step. La chiave OpenRouter sta
in `.env.local`, mai nel codice.

Le corse con modello linguistico sono in cache per impronta di richiesta: ogni
metrica nuova sulle stesse risposte si ricalcola **gratis**, e il costo di ogni
risposta è salvato dentro la risposta. Chi rilancia deve nominare il modello
(`qwen3.5:4b`, non il predefinito): il modello fa parte della chiave di cache.

---

## 8. Moduli

| modulo | step | ruolo |
|---|---|---|
| `data_loading.py` | 0 | carica il grezzo, non interpreta |
| `explore_dataset.py` | 0 | sonde di parsing a livelli, report |
| `fetch_external_kb.py` | 0 | scarica AIFA e altre fonti, aggiorna il manifest |
| `schema.py` | 1 | `StatoPaziente`: il contratto dati di tutto il progetto |
| `build_vocabularies.py` | 1 | vocabolari chiusi di farmaci e condizioni |
| `extract_icd10.py` | 2 | terminologia ICD-10 dal PDF |
| `normalize_drugs.py` | 2b | farmaco → ATC, con metodo e fonte |
| `gazetteer.py`, `context_it.py` | 3 | riconoscimento e assi negazione/storicità/soggetto |
| `risolutori.py`, `entity_linking.py` | 3–5 | codifica identica per tutte le pipeline |
| `extract_a.py` / `extract_b.py` / `extract_c.py` | 3 / 4 / 5 | le tre pipeline |
| `llm_backend.py` | 4 | backend intercambiabili (ollama, OpenRouter, fittizio) con cache |
| `silver_labels.py`, `ner_train.py`, `ner_infer.py` | 5 | etichette silver e riconoscitore neurale |
| `confronto.py`, `rianalizza.py` | 6 | confronto fra pipeline e fra corse |
| `riferimento.py` | 6b | il riferimento annotato e il richiamo |
| `kb_build.py`, `conoscenza.py` | 7 | scrive e legge `kb/conoscenza.ttl`: le regole che ranker e filtro usano |
| `grafo.py`, `interroga.py` | 7 | grafo RDF con provenienza, interrogazioni SPARQL |
| `filtro.py` | 8 | filtro simbolico, tre esiti, regole con fonte |
| `ranker.py`, `valuta_ranker.py` | 9 | tre ranker + due linee di base, valutazione |
| `demo.py`, `traccia.py` | 9b, 9c | demo end-to-end, traccia di provenienza |
| `mcp_server.py`, `mcp_client_locale.py` | 10 | server MCP di sola lettura, host locale |
| `valuta_gerarchica.py` | 11 | metrica gerarchica, controllo casuale, bootstrap |

Ogni modulo ha il suo file di test in `tests/`, tutti su dati sintetici.
