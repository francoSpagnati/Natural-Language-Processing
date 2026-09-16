# Sistema di supporto alla decisione terapeutica in cardiologia

Progetto finale per il corso *Natural Language Processing for Digital Health*.

Legge referti cardiologici italiani, ne estrae lo stato clinico con **tre
pipeline diverse** (deterministica, modello linguistico, NER + entity linking),
lo codifica in **ICD-10** e **ATC**, lo mette in un knowledge graph con la
provenienza di ogni fatto, e propone la terapia di dimissione passando da un
**filtro di sicurezza simbolico** e da un ordinamento misurato contro le
decisioni vere dei cardiologi. Il tutto è esposto come **server MCP** a un
modello conversazionale, con una traccia che dice *per quali parole del referto*
una proposta esiste.

**Tutti i dodici step sono completati.** Il punto d'ingresso è
[`docs/00_architettura.md`](docs/00_architettura.md): che cosa fa il sistema, la
tesi in sei righe, che cosa ogni step ha trovato, i numeri con l'incertezza, che
cosa resta aperto.

## I risultati in tre righe

- **Il miglior ranker non è misurabilmente migliore di un contatore** che non
  guarda il paziente: 48,5% contro 47,5% di richiamo@5, intervallo al 95%
  [−1,5%, +3,4%], validazione incrociata su 841 ricoveri.
- **Il modello linguistico perde contro quel contatore** di 20–31 punti, perché
  propone la cardiologia giusta e manca il 40,4% delle prescrizioni che
  cardiologia non è.
- **Le garanzie del sistema valgono fino al confine dello strumento.** Un modello
  davanti al server MCP può invertire un fatto nella parafrasi («iperteso» →
  «ipotensione») senza che il server se ne accorga.

## Dataset e vincoli

`data/raw/anamnesiterapie.txt`: 1 000 anamnesi cardiologiche in italiano,
pseudonimizzate, con terapia all'ingresso e — per 841 — la terapia alla
dimissione, che è la verità di riferimento del compito. **I dati clinici non sono
versionati**, e un controllo automatico (`src/privacy.py`) verifica che nessun
file del repository contenga una finestra di testo presente in meno di cinque
referti.

Due vincoli non negoziabili:

1. **Solo l'export grezzo.** Le varianti già passate per un LLM sono scartate:
   costruirci sopra significherebbe misurare un'estrazione fatta da altri.
2. **Ogni mappatura da una knowledge base citabile** — AIFA (ATC), ICD-10 2019
   Elenco Sistematico italiano. Una voce non coperta si marca, non si inventa.

## Struttura

```
src/          un modulo per step, più i moduli condivisi (schema, backend LLM, privacy)
tests/        446 test su dati sintetici, nessuno usa la rete
docs/         un documento per step + l'indice architetturale
notebooks/    quattro notebook di analisi, senza output salvati
kb/           manifest delle fonti esterne: URL, data, SHA-256
data/         non versionato: grezzo, knowledge base, intermedi, uscite
.claude/      skill di progetto per Claude Code
```

## Esecuzione

Python ≥ 3.10. Dipendenze motivate una per una in `requirements.txt`.

```bash
pip install -r requirements.txt
python3 -m spacy download it_core_news_sm
python3 src/fetch_external_kb.py                  # scarica AIFA, scrive il manifest
ollama pull qwen3.5:4b                            # il modello locale degli step 9 e 10

python3 -m unittest discover -s tests -q          # 446 test
python3 src/privacy.py                            # deve dire: frasi specifiche: 0
python3 src/demo.py --esempio 1 --traccia         # un paziente dall'inizio alla fine
python3 src/valuta_gerarchica.py --pieghe 5       # la valutazione finale, gratis
claude mcp add cardio -- python3 src/mcp_server.py
```

La pipeline B sul corpus intero e il ranker remoto usano
`deepseek/deepseek-v4.1-flash` via OpenRouter, chiave in `.env.local` (non
versionato); le prove locali dello step 4 usavano `qwen3:4b`. Ogni risposta è in cache
per impronta della richiesta: rieseguire una valutazione non chiama il modello e
non costa. Spesa totale del progetto: **4,45 $**.

## Fonti esterne

| fonte | uso | licenza |
|---|---|---|
| [AIFA](https://www.aifa.gov.it/liste-dei-farmaci) | registro ATC italiano, anagrafica confezioni | CC-BY 4.0 |
| ICD-10 2019, Centro Collaboratore OMS FVG, via [reteclassificazioni.it](https://www.reteclassificazioni.it/) | terminologia delle condizioni, 10 803 codici | PDF scaricato a mano |
| ESC 2021 (scompenso) e aggiornamento 2023, ESC 2024 (fibrillazione atriale), ESC 2023 (sindromi coronariche; malattia cardiovascolare nel diabete), ESC/ESH 2024 (ipertensione), ESC/EAS 2019 (dislipidemie) | le 27 indicazioni del ranker simbolico, citate una per una in `src/ranker.py` | pubbliche |
| [bioBIT](https://huggingface.co/IVN-RIN/bioBIT), Buonocore et al. 2023 | modello di base del NER italiano | Hugging Face |
| [Qwen3.5 4B](https://ollama.com/library/qwen3.5) via Ollama; DeepSeek V4.1 Flash via OpenRouter | i modelli linguistici; **non** sono fonti di conoscenza, solo motori di estrazione e ordinamento | Apache 2.0 / a consumo |
| [`anthropics/skills`](https://github.com/anthropics/skills) `mcp-builder` | guida alla costruzione del server MCP, con provenienza dichiarata in `.claude/skills/` | Apache 2.0 |
