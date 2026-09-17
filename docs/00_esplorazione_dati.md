# Step 0 — Esplorazione del dataset

**Stato:** completato.
**Riproducibilità:** `python3 src/explore_dataset.py` (scrive `reports/00_esplorazione.txt` e i CSV in `data/interim/`, non versionati)

Prima di scrivere una riga di estrazione: da dove viene il file, che struttura
ha davvero, quali campi sono affidabili e per che cosa. Le sonde di questo
step misurano la regolarità dei campi; i parser definitivi nascono allo
step 3.

---

## 1. Provenienza: solo l'export grezzo

Nella cartella dei dati convivevano tre file.

| file | record | provenienza |
| --- | --- | --- |
| **`anamnesiterapie.txt`** | **1 000** | **export grezzo del sistema ospedaliero** |
| `anamnesiterapie_completo.txt` | 1 000 | derivato: il grezzo passato per un LLM, campi già separati |
| `pazienti_con_terapia_uscita.txt` | 857 | derivato, con un questionario di condizioni già codificato |

I derivati erano più comodi — condizioni già strutturate, un questionario
«Anamnesi Strutturata» pronto — e sono stati **scartati**: costruire tre
pipeline di estrazione sopra un'estrazione già fatta da un modello linguistico
avrebbe misurato quella, non le nostre. Il questionario non è verificabile
contro nessuna fonte. Anche il CSV ATC trovato nella stessa cartella è stato
verificato prima di tenerlo: coincide con il registro AIFA scaricato.

## 2. Struttura reale del file

Un unico array JSON valido, UTF-8: `[{encOid, referti: [{tipo, data,
reportOid, testo}]}]`. 1 000 record, 1 000 `encOid` distinti, chiavi sempre le
stesse, **zero anomalie di caricamento**. Tre tipi di referto:

| campo | presente in | lunghezza min / mediana / max | natura |
| --- | --- | --- | --- |
| Anamnesi | 1 000 | 222 / 1 665 / 17 590 | prosa libera |
| Terapia medica all'ingresso | 1 000 | 4 / 275 / 1 899 | lista con `;`, solo nomi commerciali |
| Terapia alla Dimissione | 857 | 15 / 649 / 2 281 | voci fra virgolette con principio attivo |

Due coorti: **857** con dimissione (la verità di riferimento del compito; 841
con voci codificabili) e 143 solo con testo.

## 3. Affidabilità dei campi

Sonde a **livelli**, dal formato più stretto al più lasco, con conteggio per
livello: così ogni voce porta con sé quanto è regolare, e una regex
permissiva non nasconde le irregolari.

| campo | interpretato | non interpretato | esempio di irregolarità |
| --- | --- | --- | --- |
| Terapia alla dimissione | 99,1% (6 269 voci in formato pieno) | 56 (0,9%) | parentesi annidate: `(Propranololo 10 mg cps (galenico) cps.)` |
| Terapia all'ingresso | 98,1% (5 480 nome + posologia) | 111 (1,9%) | prosa scritta a mano: `Rybelsus 14 mg 1 cpr la mattina, Jardiance…` |

Esclusi esplicitamente: 74 voci non farmacologiche (ossigeno, CPAP, NIV),
senza codice ATC; 98 record senza terapia all'ingresso («nessuna terapia
domiciliare»: legittimo, non un errore). La guardia
`nome_farmaco_plausibile()` sui livelli laschi ha alzato i non interpretati
ma tolto voci come `Bisoprololo 3.75 mg 1 cp alle ore 08`, dove i due punti di
`08:00` fingevano da separatore: **precisione prima della copertura**, perché
il vocabolario chiuso si propaga a ogni step successivo.

**Il ponte fra i due campi.** L'ingresso ha nomi commerciali, la dimissione
principi attivi: dalle coppie nello stesso ricovero si ricava un ponte
commerciale → principio, trattato come **evidenza interna** e non come
knowledge base. Verificato contro AIFA su 787 coppie: 529 confermate (67,2%),
21 discordanti (2,7%), 237 con nome non presente in AIFA (30,1%: abbreviazioni
del produttore, denominazioni fuori registro). È il numero che ha reso
necessaria la cascata dello step 2b.

**Allergie**: sezione assente in 525 record (informazione ignota), «non note»
in 346, presenti in 129. Le tre cose sono diverse e lo schema le distingue.

**Condizioni**: nessun campo strutturato. Sono tutte nella prosa, con 668
intestazioni di sezione candidate distinte e una coda lunghissima di sigle:
non si può segmentare sulle intestazioni. L'eco testuale del questionario
(«Ipertensione arteriosa si.») copre 268 record con 9 termini distinti: troppo
poco per fondarci sopra qualcosa.

## 4. Knowledge base esterne, scaricate con manifest

| fonte | file | serve per |
| --- | --- | --- |
| AIFA, registro ATC (CC-BY 4.0) | `atc.csv`, 7 211 codici con descrizione in italiano | gerarchia ATC, metrica gerarchica |
| AIFA, anagrafica confezioni | `confezioni_fornitura.csv`, 159 942 confezioni | nome commerciale → principio → ATC |
| AIFA, principi attivi per AIC | `PA_confezioni.csv` | disambiguare le associazioni |
| AIFA, classe A/H con titolare AIC | | validare le abbreviazioni dei produttori |

`src/fetch_external_kb.py` scarica e scrive in `kb/manifest_fonti.json` URL,
data, byte e SHA-256 di ogni file: la provenienza è un dato, non
un'affermazione.

## 5. Decisioni

| decisione | perché | alternativa scartata |
| --- | --- | --- |
| solo l'export grezzo | i derivati hanno l'estrazione già fatta da un LLM | i derivati, più comodi |
| il ponte commerciale → principio come evidenza, non come KB | è un'osservazione interna; le fonti sono AIFA / WHO | usarlo come dizionario |
| dimissione opzionale nel loader | 143 record ne sono privi: caratteristica, non difetto | 143 falsi allarmi |
| loader separato dalle sonde (`data_loading.py` / `explore_dataset.py`) | il loader è riusato da ogni step; le sonde sono usa-e-getta | uno script solo |
| il loader accumula `Anomalia`, non solleva | su dati reali serve misurare quanti record sono difettosi | `raise` al primo errore |

## 6. Limiti e implicazioni

* I 56 frammenti con parentesi annidate restano irrisolti: 0,9% non
  giustifica un parser a stack.
* Il vocabolario delle condizioni non può venire dal dataset: serve una
  terminologia esterna (step 1–2).
* Ciò che è strutturato (i due campi di terapia) si legge con un parser e
  vale come verità gratuita; ciò che è prosa (condizioni, allergie, farmaci
  narrati) richiede riconoscimento. È il principio che ha guidato gli step 3–4.
