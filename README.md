# Progetto di Natural Language Processing (NLP)

Questo repository contiene la struttura di base per un progetto di elaborazione del linguaggio naturale (NLP).

## Struttura del Progetto

La struttura delle cartelle è organizzata come segue:

```text
├── data/                  # Cartella per i dataset (CSV, JSON, TXT, ecc.)
├── notebooks/             # Jupyter Notebooks per l'esplorazione dei dati e prototipazione
│   └── 01_data_exploration.ipynb  # Notebook iniziale per l'esplorazione dei dati
├── src/                   # Codice sorgente del progetto (moduli Python, pipeline, ecc.)
├── .gitignore             # File per escludere file temporanei, virtual env e dataset da Git
└── requirements.txt       # Dipendenze Python necessarie per il progetto
```

## Configurazione e Installazione

Per iniziare a lavorare sul progetto, si consiglia di creare un ambiente virtuale Python e installare le dipendenze richieste.

### 1. Creare un ambiente virtuale (consigliato)

Esegui il seguente comando nella root del progetto:

```bash
python3 -m venv .venv
```

Attiva l'ambiente virtuale:
*   **Linux/macOS:**
    ```bash
    source .venv/bin/activate
    ```
*   **Windows (Command Prompt):**
    ```cmd
    .venv\Scripts\activate.bat
    ```
*   **Windows (PowerShell):**
    ```powershell
    .venv\Scripts\Activate.ps1
    ```

### 2. Installare le dipendenze

Con l'ambiente virtuale attivo, installa i pacchetti necessari tramite `pip`:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Scaricare i modelli NLP (Opzionale)

Se utilizzi librerie come Spacy o NLTK, potresti voler scaricare i relativi modelli linguistici. Ad esempio per Spacy (Italiano o Inglese):

```bash
# Modello per l'Italiano
python -m spacy download it_core_news_sm

# Modello per l'Inglese
python -m spacy download en_core_web_sm
```

## Utilizzo dei Notebook

Per avviare l'interfaccia di Jupyter e aprire i notebook di esplorazione:

```bash
jupyter notebook
```

O apri direttamente il progetto in VS Code / PyCharm, che supportano l'esecuzione diretta dei file `.ipynb`.
