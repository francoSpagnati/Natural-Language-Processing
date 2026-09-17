# Prompt di progetto — Sistema di supporto alla decisione terapeutica cardiologica (NLP + Knowledge Graph + MCP)

> Incolla questo prompt come primo messaggio in una sessione di coding (es. Claude Code). Il dataset (file .txt contenenti JSON) deve essere disponibile nella working directory.

## 1. Contesto

Sto sviluppando il progetto finale per il corso di Natural Language Processing for Digital Health. Ho a disposizione un dataset reale (già pseudonimizzato) di circa **840 anamnesi cardiologiche in italiano**, salvate come file `.txt` il cui contenuto è in realtà **JSON**. Ogni record contiene, tra le altre cose, testo libero narrativo e campi semi-strutturati riconoscibili tramite pattern/regex, tra cui **terapia in ingresso** e **terapia in uscita** (farmaci/principi attivi in italiano, senza codici standardizzati).

Obiettivo: costruire un sistema che, dato lo stato di un paziente cardiologico (patologie, farmaci in corso, allergie), suggerisca una terapia **spiegabile**, con le motivazioni espresse come cammini/link all'interno di una knowledge base a grafo (indicazioni, controindicazioni, interazioni). Il sistema finale deve essere esposto come **funzione/tool MCP**, richiamabile da un LLM (function calling), con descrizione chiara di input/output.

Il progetto sarà valutato su: qualità e correttezza del codice, utilità, complessità gestita bene, chiarezza/navigabilità, efficienza. Devo essere in grado di spiegare a voce ogni riga generata, quindi **ogni scelta tecnica non ovvia va commentata/documentata con la motivazione**, non solo implementata.

## 2. Fase 0 — Esplorazione obbligatoria dei dati (da fare per prima, prima di scrivere pipeline definitive)

Prima di scrivere codice definitivo:
1. Carica un campione di file (es. 10-20) e stampa la struttura JSON reale (chiavi, nesting, tipi).
2. Verifica quali campi sono affidabilmente regex/JSON-estraibili (es. `terapia_ingresso`, `terapia_uscita`, `diagnosi`, testo narrativo libero) e quali sono invece solo dentro la prosa libera.
3. Estrai la lista di *tutti* i valori distinti che compaiono nei campi terapia (ingresso + uscita) su tutto il dataset: questo sarà il **vocabolario chiuso dei farmaci** su cui costruire dizionario di normalizzazione e knowledge graph. Fai lo stesso, se possibile, per le patologie/diagnosi menzionate.
4. Segnala eventuali anomalie (formati misti, encoding, JSON malformati, valori mancanti) prima di procedere.

Non proseguire con assunzioni rigide sullo schema finché non hai verificato empiricamente il formato reale.

## 3. Architettura del sistema

### 3.1 Normalizzazione farmaci/patologie (vocabolario chiuso come *scope*, non come fonte relazionale)
- Il vocabolario chiuso emerso dal dataset (punto 2.3) serve a definire **quali** farmaci e patologie sono rilevanti per il progetto — non a definire le relazioni cliniche tra loro (quelle vengono da KB esterne, vedi 3.3).
- Costruisci un dizionario di normalizzazione: nome commerciale/variante testuale italiana → principio attivo (denominazione internazionale, INN) → **codice ATC completo (5° livello)**. La risoluzione del codice ATC è **obbligatoria** (non solo "se reperibile facilmente"), perché serve sia per interrogare le KB esterne sia per calcolare la metrica gerarchica (vedi sezione 4).
- Per ogni principio attivo del vocabolario chiuso senza corrispondenza ATC diretta, documenta il fallback usato (mapping manuale puntuale, motivato).
- Stessa logica di normalizzazione per un vocabolario chiuso di patologie/condizioni cardiologiche (verso un identificativo stabile, es. ICD-10 o concetto Wikidata/SNOMED se disponibile senza licenza).

### 3.2 Tre pipeline di estrazione dallo stato paziente (testo libero → stato strutturato)

Per ogni nuova anamnesi, implementare **tre pipeline parallele e confrontabili**, che condividono lo stesso schema di output finale:

**A. Pipeline deterministica (baseline tracciabile, nessuna libertà interpretativa)**
- Estrazione dei campi strutturati via regex/parsing JSON.
- Riconoscimento nel testo narrativo libero tramite dictionary/gazetteer matching sul vocabolario chiuso (es. `PhraseMatcher` di spaCy o regex ottimizzate), non modelli neurali generici.
- Gestione di negazione/incertezza nel testo italiano (es. "nessuna storia di...", "si esclude...", "non in terapia con..."): implementa una logica a regole ispirata all'algoritmo ConText usato da medspaCy (visto a lezione), adattata all'italiano con una lista di trigger di negazione/storicità/incertezza, perché medspaCy/scispaCy sono pensati per l'inglese.
- Output: JSON tracciabile, con per ogni entità estratta la posizione nel testo e la regola che l'ha generata (per audit/debug).
- Questa pipeline serve anche come **fonte di etichette silver** per bootstrare la pipeline C (vedi sotto).

**B. Pipeline basata su LLM locale (estrazione generativa, meno vincolata)**
- Stesso compito di estrazione, ma delegato a un LLM locale (predisponi un'interfaccia astratta `LLMBackend` con implementazione locale iniziale, es. via Ollama o un modello HuggingFace piccolo, sostituibile in seguito con un backend API).
- Prompt strutturato che richiede output JSON nello stesso schema della pipeline A.

**C. Pipeline con modello di Named Entity Recognition + Entity Linking (approccio statistico, via di mezzo tra A e B)**
- Riconoscimento delle menzioni di farmaci/patologie nel testo tramite un modello di NER vero e proprio (non regole, non prompt), in linea con quanto visto a lezione sul riconoscimento di entità.
- Valuta prima l'uso di modelli NER biomedici/clinici pre-addestrati eventualmente disponibili per l'italiano; se la copertura risulta insufficiente (probabile, dato che gran parte dei modelli clinici open — scispaCy, i modelli usati a lezione per l'EL — sono pensati per l'inglese), esegui il fine-tuning di un modello NER italiano generico (es. basato su un BERT italiano) sui tipi di entità `DRUG`/`CONDITION`, usando come **training set silver** le annotazioni prodotte dalla pipeline A su tutto il dataset (weak supervision), eventualmente raffinate con una piccola validazione manuale su un sottoinsieme.
- **Entity Linking**: le menzioni individuate dal modello NER non restano stringhe libere ma vengono collegate (candidate generation + disambiguazione, come visto nell'unità su Entity Linking) al vocabolario chiuso normalizzato costruito in 3.1, e quindi a un **indicatore universale preciso**: codice ATC per i farmaci, codice ICD-10 (o concetto Wikidata/SNOMED se accessibile senza licenza) per le patologie. Le menzioni che non trovano un link affidabile nel vocabolario chiuso vanno gestite esplicitamente come NIL (entità fuori KB), non forzate su un match sbagliato.
- Questa pipeline è quella metodologicamente più vicina a un vero sistema di NER + EL clinico, e permette di misurare quanto un modello statistico addestrato (anche solo su etichette silver) generalizzi meglio delle sole regole, restando comunque ancorato a identificatori standard (a differenza della pipeline B, meno controllabile).

**D. Confronto tra le tre pipeline**
- Metrica di accordo a coppie (A vs B, A vs C, B vs C) sui campi strutturati, con precision/recall/F1 per entità estratta, usando la pipeline A come riferimento primario dove disponibile (sui campi terapia è la più affidabile per costruzione).
- Riporta anche dove le pipeline divergono, con qualche esempio concreto commentato, e una valutazione qualitativa di quando ciascun approccio fallisce (es. varianti di scrittura non previste dalle regole per A, allucinazioni per B, errori di linking per C).

Tutte e tre le pipeline producono lo **stesso schema di output**: un file JSON "stato paziente strutturato" (patologie, farmaci in corso — con relativo codice ATC/ICD quando risolto —, allergie se presenti, eventuale testo di supporto), che è l'unico input accettato dal motore di raccomandazione/dal tool MCP.

### 3.3 Knowledge Graph (indicazioni / controindicazioni / interazioni / causa-effetto / standard clinici)
- Tecnologia: **RDF con `rdflib`**, serializzato in un file Turtle versionato nel repo (nessun server necessario, query in SPARQL, coerente con quanto trattato a lezione su RDF/OWL/SPARQL per il ragionamento clinico).
- Schema minimo: entità `Drug`, `Condition`, `Guideline`; relazioni `hasIndication`, `hasContraindication`, `interactsWith`, `causesADR` (adverse drug event), `recommendedBy` (Drug/Condition → Guideline), con proprietà `source` (URI/riferimento alla fonte esatta) e `atcCode` obbligatoria sui nodi `Drug`, per garantire tracciabilità delle motivazioni come link reali, non solo interni al grafo.

**Popolamento: primariamente automatico da knowledge base esterne**, non curato a mano. Per ogni farmaco/patologia del vocabolario chiuso (3.1):
- Indicazioni/controindicazioni/interazioni: interroga fonti pubbliche strutturate — valuta empiricamente copertura e affidabilità di più fonti candidate (es. openFDA per il testo strutturato delle schede tecniche/label — indicazioni, controindicazioni, interazioni; Wikidata via SPARQL per relazioni farmaco↔condizione e codici ATC; WHO ATC/DDD Index o dataset ATC derivati apertamente disponibili) e documenta nel README quale fonte è stata usata per cosa e perché. Poiché i nomi dei farmaci nel dataset sono in italiano, prevedi uno step di mapping verso la denominazione internazionale (INN) prima di interrogare le fonti.
- Ricorri a curatela manuale puntuale **solo** per le voci del vocabolario chiuso non coperte da nessuna fonte esterna, segnalandole esplicitamente come tali (con la fonte usata, es. scheda tecnica ufficiale) — non deve essere la strategia principale.

**Layer standard/procedure cardiologiche internazionali**: aggiungi nodi `Guideline` per collegare coppie farmaco-condizione rilevanti alle linee guida cardiologiche internazionali (es. ESC — European Society of Cardiology, ACC/AHA), con proprietà come classe di raccomandazione (I/IIa/IIb/III) e livello di evidenza (A/B/C) dove disponibili. Attenzione: a differenza dei dati farmacologici, le linee guida sono tipicamente pubblicate come documenti (PDF/executive summary), non come API strutturate — prevedi quindi per questo layer una curatela semi-manuale su un numero limitato di raccomandazioni chiave rilevanti per le patologie presenti nel dataset, citando esplicitamente documento e anno come fonte.

**Aggiornamento della KB**: implementa il popolamento come uno script/modulo di *import* separato dal resto del sistema (`kb_build.py` o simile), rieseguibile per rigenerare il file Turtle. Traccia nei metadati del grafo (o in un manifest separato) per ogni tripla importata automaticamente: fonte, data di fetch, versione della fonte se disponibile — così il grafo può essere aggiornato ri-eseguendo l'import quando le fonti esterne cambiano, senza perdere tracciabilità di cosa proviene da dove e quando.

Per la visualizzazione, converti i sottografi rilevanti in `networkx` e rendili come immagine (`matplotlib`) o HTML interattivo (`pyvis`).

### 3.4 Motore di raccomandazione

Il motore è diviso in due fasi nettamente separate, così da poter "staccare" il ruolo del dataset di training (o dell'LLM) senza mai intaccare la sicurezza clinica del sistema.

**Fase 1 — Generazione e filtro dei candidati (sempre attiva, sempre simbolica, non staccabile)**
1. Query SPARQL per candidati farmaco indicati per le condizioni del paziente.
2. Filtro escludendo farmaci controindicati/allergie/interazioni con la terapia già in corso.

Questa fase dipende solo dalla Knowledge Graph (KB esterne + linee guida), mai dal dataset di training né da un LLM: è il livello di sicurezza, identico in tutte le modalità della Fase 2.

**Fase 2 — Ranking dei candidati (modulo intercambiabile, tre strategie da confrontare)**
Implementa il ranking come componente intercambiabile dietro un'interfaccia comune `Ranker`:
- `SymbolicOnlyRanker`: ordina i candidati già filtrati usando solo evidenza simbolica dal grafo (es. classe di raccomandazione delle linee guida I/IIa/IIb/III dove disponibile), senza alcun uso del dataset di training né di LLM.
- `HybridRanker`: `SymbolicOnlyRanker` + prior empirico calcolato dal dataset di training (frequenza con cui un farmaco compare nella terapia di uscita per pazienti con profilo di condizioni simile).
- `LLMRanker`: dato lo stesso insieme di candidati già filtrato per sicurezza in Fase 1, un LLM (stesso backend astratto `LLMBackend` usato per la pipeline B) riceve per ciascun candidato indicazioni, note sulle interazioni già escluse e classe di raccomandazione da linea guida, e sceglie/ordina i candidati motivando la scelta in linguaggio naturale. **Vincolo di sicurezza da rispettare e documentare esplicitamente**: l'LLM non genera candidati né può bypassare il filtro di Fase 1 — sceglie solo tra opzioni già validate simbolicamente, quindi nel caso peggiore sceglie un'opzione subottimale, mai una controindicata.

Nota metodologica per la relazione: disattivare `HybridRanker` (o `LLMRanker`) non rende inutile il dataset — resta comunque la fonte del vocabolario chiuso, delle etichette silver per la pipeline C, e soprattutto del **test set di valutazione**, cioè ciò che permette di misurare sperimentalmente quale strategia di ranking si avvicina di più alle terapie realmente prescritte.

**Output**: indipendentemente dalla strategia scelta, il motore restituisce una lista ordinata dei top-k candidati (k configurabile, es. 3-5), inclusi eventualmente farmaci diversi ma della stessa classe ATC/con effetto equivalente. Per ciascun candidato: i cammini nel grafo usati come motivazione (con link/URI di fonte e, se pertinente, riferimento alla linea guida), più — solo per `LLMRanker` — la giustificazione testuale generata. Includi sempre nell'output anche **quale strategia di ranking è stata usata**, per trasparenza e riproducibilità. Restituire più candidati motivati, anziché un'unica scelta secca, resta una decisione voluta: lascia al chiamante (LLM esterno via MCP, o clinico) la possibilità di selezionare/raffinare ulteriormente tra opzioni clinicamente valide.

### 3.5 Esposizione come tool MCP
- Implementa con l'SDK Python ufficiale `mcp` (es. `FastMCP`), definendo un tool tipo `suggest_cardiac_therapy(patient_state: PatientState) -> TherapyRecommendation`, dove `TherapyRecommendation` è una **lista di candidati** (vedi 3.4), con modelli Pydantic per input/output così lo schema/description è generato automaticamente e comprensibile a un LLM.
- Nella descrizione del tool, chiarisci esplicitamente che i candidati restituiti sono opzioni motivate e filtrate su base simbolica (indicazioni/controindicazioni/linee guida), non un ordine vincolante: l'LLM chiamante è libero di selezionare tra i candidati proposti, chiederne motivazione aggiuntiva, o — usando la propria conoscenza clinica generale — segnalare che nessuno dei candidati è ottimale. Il tool fornisce evidenza verificabile, la decisione finale resta al layer LLM/umano (coerente con l'approccio RAG visto a lezione: la generazione è ancorata a evidenza recuperata, non sostituita da essa).
- Poiché non è disponibile un client MCP live, prepara anche un piccolo harness di test che simula la chiamata: un LLM (inizialmente locale) riceve la descrizione del tool, decide di chiamarlo con lo stato paziente, riceve la lista di candidati e la usa per formulare una risposta in linguaggio naturale, motivando l'eventuale scelta tra i candidati citando i cammini nel grafo ricevuti.

## 4. Valutazione (obbligatoria, non opzionale)

- Split train/test del dataset (es. 80/20), stratificato se possibile per patologia principale.
- **Metrica primaria: precisione/recall/F1 gerarchici sui 5 livelli ATC**, non match esatto sul nome del farmaco. Per ogni paziente del test set:
  - risolvi sia i farmaci raccomandati dal sistema sia i farmaci realmente presenti nella terapia di uscita (ground truth) ai rispettivi codici ATC completi (5° livello, vedi 3.1);
  - per ciascun livello ATC l = 1..5 (gruppo anatomico → sottogruppo terapeutico → sottogruppo farmacologico → sottogruppo chimico → sostanza chimica), tronca i codici predetti e reali a quel livello e calcola precision/recall/F1 insiemistici a quel livello;
  - riporta i risultati come tabella per livello (l=5 è il match più stringente — stesso principio attivo; l=1 il più permissivo — stessa area terapeutica), così un farmaco della stessa classe/con effetto equivalente al farmaco realmente prescritto viene correttamente premiato come "quasi corretto" invece che trattato come errore totale.
- Dato che il motore restituisce **top-k candidati** (3.4) e non un singolo farmaco, valuta anche una versione "top-k" della metrica sopra: per ciascun livello ATC, la raccomandazione è considerata corretta a quel livello se **almeno uno** dei k candidati proposti matcha il farmaco reale a quel livello (analogo al concetto di Top-k Accuracy visto per l'Entity Linking a lezione).
- Confronta inoltre le tre strategie di ranking (`SymbolicOnlyRanker`, `HybridRanker`, `LLMRanker`, vedi 3.4) con la stessa metrica gerarchica/top-k ATC, tenendo fissa la pipeline di estrazione (usa la A come default per isolare l'effetto del ranking da quello dell'estrazione). **Non eseguire l'intero prodotto cartesiano 3 pipeline di estrazione × 3 ranker** come valutazione principale: è troppo per i tempi del corso. Usalo al più come confronto ridotto su un sottoinsieme, e documenta esplicitamente nel README questa scelta di scope.
- Metrica secondaria: stessa valutazione end-to-end (sempre a livelli ATC) separata per ciascuna delle tre pipeline di estrazione dello stato paziente (A deterministica, B LLM, C NER+Entity Linking), per capire se — e quanto — il tipo di estrazione impatta la qualità finale della raccomandazione.
- Riporta anche alcuni casi concreti (2-4 esempi) con paziente, lista di candidati proposti, motivazioni a grafo/linee guida e confronto con la terapia reale a vari livelli ATC, incluso almeno un caso in cui il sistema sbaglia anche a livello ATC ampio — utile in sede di discussione per mostrare comprensione dei limiti.

## 5. Requisiti di qualità del codice e deliverable

- Deliverable finale: **repository di codice** (struttura tipo `data/`, `src/` con moduli separati per parsing, normalizzazione, pipeline estrazione A/B/C, knowledge graph, motore di raccomandazione, tool MCP, valutazione; `notebooks/` per l'esplorazione; `kb/` per il file Turtle; `tests/`; `docs/` con un documento per ogni step di sviluppo più un indice architetturale complessivo — vedi sezione 6; `README.md`).
- README con: architettura, motivazione di ogni scelta tecnica (perché rdflib e non un DB a grafo dedicato, perché estrazione deterministica come default, perché prior empirico, ecc.), istruzioni per l'esecuzione, esempi d'uso concreti con output reali.
- Codice commentato in modo che io possa spiegare ogni funzione; preferire chiarezza a compattezza.
- Nessuna libreria vietata, ma ogni scelta va giustificata nei commenti/README.

## 6. Modalità di lavoro richiesta

Il progetto va sviluppato per **step espliciti e sequenziali**, mai tutto in un colpo solo. Per ogni step:

1. Implementa **solo** quello step (non anticipare step successivi).
2. Scrivi (o aggiorna) nella cartella `docs/` un documento dedicato allo step, che contenga: cosa è stato fatto, quali componenti/moduli sono stati creati con una breve descrizione della responsabilità di ciascuno, quali decisioni tecniche sono state prese e **perché** (incluse le alternative scartate e il motivo), eventuali limiti noti o cose lasciate volutamente semplificate. L'obiettivo è che l'intera architettura e il percorso decisionale siano ricostruibili leggendo solo `docs/`, senza dover rileggere tutto il codice — utile sia per prepararmi alla discussione con il docente sia per riprendere il lavoro a distanza di tempo.
3. Mantieni anche un documento indice (`docs/00_architettura.md`), aggiornato incrementalmente ad ogni step, con la visione d'insieme di come i componenti si collegano tra loro (anche solo come diagramma testuale/lista dei moduli e delle loro dipendenze).
4. **Al termine di ogni step, fermati esplicitamente e attendi la mia conferma prima di procedere allo step successivo.** Non passare automaticamente allo step successivo nello stesso turno, anche se ti sembra ovvio come continuare.

Step previsti (usa questa numerazione anche nei nomi dei file in `docs/`, es. `docs/03_pipeline_estrazione_A.md`):
0. Esplorazione dati (sezione 2) → `docs/00_esplorazione_dati.md`
1. Schema "stato paziente strutturato" e vocabolario chiuso farmaci/patologie (da farmi validare prima di proseguire)
2. Normalizzazione e risoluzione ATC/ICD (sezione 3.1)
3. Pipeline di estrazione A — deterministica (sezione 3.2)
4. Pipeline di estrazione B — LLM locale (sezione 3.2)
5. Pipeline di estrazione C — NER + Entity Linking (sezione 3.2)
6. Confronto tra le tre pipeline di estrazione (sezione 3.2, punto D)
7. Costruzione della Knowledge Graph: import da fonti esterne, layer linee guida, meccanismo di aggiornamento (sezione 3.3)
8. Motore di raccomandazione — Fase 1, filtro simbolico di sicurezza (sezione 3.4)
9. Motore di raccomandazione — Fase 2, ranker intercambiabili: Symbolic / Hybrid / LLM (sezione 3.4)
10. Tool MCP e harness di test (sezione 3.5)
11. Valutazione: metrica gerarchica ATC, top-k, confronto pipeline, confronto ranker (sezione 4)

Se durante uno step incontri ambiguità nei dati reali che cambiano scelte architetturali importanti, fermati comunque e chiedimi conferma invece di procedere con un'assunzione silenziosa — questo vale in aggiunta, non in sostituzione, allo stop obbligatorio di fine step.
