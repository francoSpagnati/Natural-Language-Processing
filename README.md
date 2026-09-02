# Sistema di supporto alla decisione terapeutica cardiologica

Progetto finale per il corso *Natural Language Processing for Digital Health*.

Dato lo stato di un paziente cardiologico (patologie, farmaci in corso,
allergie), il sistema suggerisce una terapia **spiegabile**, con le motivazioni
espresse come cammini in una knowledge base a grafo (indicazioni,
controindicazioni, interazioni, linee guida), ed è esposto come **tool MCP**
richiamabile da un LLM.

> **Stato: step 0 di 11 completato** (esplorazione dei dati).
> Lo sviluppo procede per step sequenziali; vedi
> [`docs/00_architettura.md`](docs/00_architettura.md) per la visione d'insieme
> e l'indice dei documenti.

## Dataset

`data/raw/anamnesiterapie.txt`: 1000 anamnesi cardiologiche in italiano,
pseudonimizzate, in un unico array JSON. Ogni record ha un'anamnesi narrativa e
la terapia all'ingresso; 857 record hanno anche la terapia alla dimissione, che
fa da ground truth per la valutazione. Il dettaglio empirico del formato è in
[`docs/00_esplorazione_dati.md`](docs/00_esplorazione_dati.md).

I dati clinici **non sono versionati** (vedi `.gitignore`).

### Due vincoli di provenienza, non negoziabili

1. **Il dataset è l'export grezzo dell'ospedale.** Esistono varianti dello
   stesso dataset già filtrate e strutturate da un LLM: sono scartate, perché
   costruirci sopra significherebbe ereditare un'estrazione già fatta da un
   altro modello — cioè proprio ciò che questo progetto deve implementare e
   confrontare. Il confronto fra le tre pipeline non sarebbe più interpretabile.
2. **Ogni mapping viene da una knowledge base citabile.** Le conversioni nome
   commerciale → principio attivo → codice ATC e condizione → ICD-10 sono
   ancorate a fonti esterne riportate esplicitamente (WHO ATC/DDD Index, AIFA,
   openFDA, Wikidata). Le regolarità osservate nel dataset valgono come evidenza
   da verificare, mai come fonte autorevole. Le voci non coperte da alcuna fonte
   sono segnalate come mapping manuali con la fonte puntuale, non riempite in
   silenzio.

## Struttura del repository

```
data/raw/        dataset e risorse esterne (non versionati)
data/interim/    vocabolari grezzi rigenerabili
src/             moduli Python
docs/            un documento per step + indice architetturale
kb/              knowledge graph in Turtle          (step 7)
notebooks/       esplorazione interattiva
tests/           test                                (dallo step 2)
reports/         output rigenerabili
```

## Esecuzione

Nessuna dipendenza esterna per lo step 0: solo la libreria standard di Python
(≥ 3.10, per la sintassi `X | None` nelle annotazioni).

```bash
python3 src/explore_dataset.py
```

Rigenera `reports/00_esplorazione.txt` e i CSV in `data/interim/`.

## Scelte tecniche

Ogni scelta non ovvia è motivata nel documento dello step corrispondente, con le
alternative scartate e il perché. Le decisioni dello step 0 sono nella sezione 6
di [`docs/00_esplorazione_dati.md`](docs/00_esplorazione_dati.md).
