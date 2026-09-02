# Sistema di supporto alla decisione terapeutica cardiologica

Progetto finale per il corso *Natural Language Processing for Digital Health*.

Dato lo stato di un paziente cardiologico (patologie, farmaci in corso,
allergie), il sistema suggerisce una terapia **spiegabile**, con le motivazioni
espresse come cammini in una knowledge base a grafo (indicazioni,
controindicazioni, interazioni, linee guida), ed è esposto come **tool MCP**
richiamabile da un LLM.

> **Stato: step 1 di 11 completato** (schema dello stato paziente e vocabolari chiusi).
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
data/raw/        dataset clinico grezzo (non versionato)
data/external/   knowledge base esterne scaricate (non versionate)
data/interim/    vocabolari grezzi rigenerabili
src/             moduli Python
docs/            un documento per step + indice architetturale
kb/              manifest delle fonti esterne + knowledge graph in Turtle (step 7)
notebooks/       esplorazione interattiva
tests/           test                                (dallo step 2)
reports/         output rigenerabili
```

## Esecuzione

Python ≥ 3.10 (sintassi `X | None` nelle annotazioni). L'unica dipendenza
esterna finora è **Pydantic**, introdotta allo step 1 per lo schema dei dati:

```bash
pip install -r requirements.txt
```

Le dipendenze dei prossimi step sono elencate e motivate in `requirements.txt`,
commentate finché lo step che le richiede non è implementato.

```bash
python3 src/explore_dataset.py     # esplorazione: report + vocabolari grezzi
python3 src/fetch_external_kb.py   # scarica le KB esterne + scrive il manifest
python3 src/verifica_ponte_aifa.py # confronta il ponte interno con AIFA

python3 src/build_vocabularies.py   # vocabolari chiusi in JSON + JSON Schema

python3 -m unittest discover -s tests -v   # 46 test
```

Il primo rigenera `reports/00_esplorazione.txt` e i CSV in `data/interim/`.

## Fonti esterne

| Fonte | Uso | Licenza |
|---|---|---|
| [AIFA — Agenzia Italiana del Farmaco](https://www.aifa.gov.it/liste-dei-farmaci) | registro ATC in italiano, anagrafica delle confezioni (nome commerciale → principio attivo → ATC), titolari AIC | CC-BY 4.0 |

`src/fetch_external_kb.py` le scarica e scrive `kb/manifest_fonti.json` con URL,
data di download, dimensione, SHA-256 e il motivo per cui ogni file serve. Il
manifest è versionato anche se i dati non lo sono, così la tracciabilità
sopravvive a un clone e si può accorgersi quando una fonte cambia a monte.

## Scelte tecniche

Ogni scelta non ovvia è motivata nel documento dello step corrispondente, con le
alternative scartate e il perché. Le decisioni dello step 0 sono nella sezione 6
di [`docs/00_esplorazione_dati.md`](docs/00_esplorazione_dati.md).
