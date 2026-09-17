# Sistema di supporto alla decisione terapeutica in cardiologia

Progetto finale di NLP per la salute digitale. Estrae lo stato clinico da
referti italiani, lo codifica in ICD-10 e ATC, e propone la terapia di
dimissione. Tutto in **italiano**: codice, commenti, documentazione, commit.

## Come si lavora qui

Il progetto avanza per **step numerati**, uno per documento in `docs/`. Alla fine
di ogni step ci si **ferma e si aspetta la conferma di Carlo** prima di
cominciare il successivo. `docs/00_architettura.md` e' l'indice vivo: va
aggiornato a ogni step.

Prima di committare o spingere: skill **`consegna-step`**.
Prima di lanciare qualunque cosa che chiami un modello: skill **`corsa-llm`**.

## Vincoli permanenti

- **Solo dati grezzi**: `data/raw/anamnesiterapie.txt`. Mai file gia' passati
  per un LLM.
- **Ogni mappatura da una knowledge base citabile** (WHO ATC/DDD, AIFA, ICD-10
  2019 Elenco Sistematico). Una voce non coperta si marca, non si inventa.
- **Si conserva tutto**: le voci non risolte si marcano, non si cancellano.
- **I dati clinici non si versionano** e non escono dalla macchina.
- **Lo step 8 resta simbolico**: mai LLM, mai dataset.
- **Prima il modello locale**; si paga solo con numeri misurati. Mai l'API
  Anthropic.

## Mappa

```
src/explore_dataset.py    step 0   esplorazione del dataset
src/build_vocabularies.py step 1   vocabolari chiusi di farmaci e condizioni
src/extract_icd10.py      step 2   terminologia ICD-10 dal PDF ufficiale
src/normalize_drugs.py    step 2b  farmaco -> ATC
src/extract_a.py          step 3   pipeline A, deterministica
src/extract_b.py          step 4   pipeline B, con modello linguistico
src/extract_c.py          step 5   pipeline C, NER + entity linking
src/confronto.py          step 6   confronto fra le tre pipeline
src/riferimento.py        step 6b  riferimento annotato a mano
src/grafo.py              step 7   knowledge graph RDF con provenienza
src/filtro.py             step 8   filtro di sicurezza simbolico
src/ranker.py             step 9   i tre ranker + due linee di base
src/valuta_ranker.py      step 9   valutazione contro la terapia reale
src/demo.py               step 9b  demo end-to-end
src/traccia.py            step 9c  traccia di provenienza via SPARQL
src/mcp_server.py         step 10  server MCP, 5 strumenti di sola lettura
src/mcp_client_locale.py  step 10  host MCP locale con ollama
src/valuta_gerarchica.py  step 11  metrica gerarchica, controllo casuale, bootstrap
src/llm_backend.py                 backend LLM intercambiabili, con cache
```

Dati (tutti in `.gitignore`): `data/raw/` sorgente, `data/interim/` intermedi e
`cache_llm/`, `data/processed/` uscite delle pipeline, `data/external/` knowledge
base scaricabili con `src/fetch_external_kb.py` (manifest citabile in `kb/`).

## Comandi

```bash
python3 -m unittest discover -s tests -q     # 446 test, nessuno usa la rete
python3 src/demo.py --esempio 1 --traccia    # un paziente dall'inizio alla fine
python3 src/valuta_ranker.py                 # ranker senza LLM (gratis)
python3 src/valuta_gerarchica.py             # step 11 con bootstrap (gratis)
python3 src/mcp_client_locale.py --strumenti # handshake col server MCP
```

## Numeri da non ricalcolare

| | |
|---|---|
| referti | 1 000, di cui **841** con terapia di dimissione codificata |
| linea di base: copiare la terapia d'ingresso | **63,6%** della dimissione |
| ibrido / frequenza, richiamo@5 sulle aggiunte, 5 pieghe su 841 | **48,5% / 47,5%**, differenza [−1,5%, +3,4%]: **indistinguibili** |
| modello linguistico contro frequenza (divisione singola) | da −20 a −31 punti, distinguibile |
| tetto di dominio: prescrizioni non cardiologiche | **40,4%** |
| filtro step 8 su 5 863 prescrizioni | 91,3% ammesse, 8,6% da verificare, 4 vietate |
| interrogazione SPARQL contro lettura da dizionario | 12,43 ms contro 0,073 µs |
| speso su OpenRouter | **4,4494 $** su 5 |

**Rumore di fondo del progetto: due punti percentuali.** Una differenza piu'
piccola non significa niente e non va raccontata come un risultato.
