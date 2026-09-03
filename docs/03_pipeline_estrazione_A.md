# Step 3 — Pipeline A: estrazione deterministica

**Stato:** completato.
**Riproducibilità:** `python3 src/extract_a.py`

---

## 1. Cosa fa e a cosa serve

È la baseline del progetto: nessuna libertà interpretativa, ogni entità
riconducibile alla regola che l'ha prodotta. Ha tre ruoli insieme:

1. il **riferimento** contro cui misurare le pipeline B (LLM) e C (NER+EL);
2. la fonte delle **etichette silver** per addestrare il NER dello step 5, senza
   annotazione manuale;
3. l'**estrattore predefinito** del sistema, perché è l'unico i cui errori si
   possono spiegare uno per uno.

| Parte dello stato paziente | Fonte | Metodo |
|---|---|---|
| farmaci in ingresso / alla dimissione | campi semi-strutturati | parsing a livelli |
| condizioni | prosa dell'anamnesi | gazetteer + ConText |
| farmaci citati in prosa | prosa dell'anamnesi | gazetteer + ConText |
| allergie | sottosezione dell'anamnesi | regex dedicata |

## 2. Risultati su tutti i 1 000 record

Esecuzione completa in **19 secondi**, 19 ms per record.

| | Totale | Dettaglio |
|---|---|---|
| **Condizioni** | 5 237 | 4 836 affermate, **299 negate**, 102 incerte |
| di cui con codice ICD | 4 345 (83 %) | 892 ambigue (più codici compatibili) |
| **Farmaci** | 14 235 | 5 494 in ingresso, 6 329 alla dimissione, 2 412 in prosa |
| di cui con codice ATC | 13 308 (93,5 %) | 163 ambigui, 764 NIL |
| **Allergie** | 198 | |
| Stato sezione allergie | | 525 ignoto, 346 negato, 129 affermato |

Gli ultimi tre numeri coincidono esattamente con quelli misurati nello step 0
per via indipendente: è un controllo incrociato che la pipeline non stia
perdendo record per strada.

**401 condizioni su 5 237 (7,7 %) portano un attributo** — negazione o
incertezza — che il puro confronto di stringhe avrebbe sbagliato. È la misura
diretta di quanto la logica ConText valga.

## 3. Le decisioni tecniche

### 3.1 spaCy `PhraseMatcher` invece di regex

Il brief lasciava la scelta. `PhraseMatcher` vince per tre motivi:

- **Confronta token, non caratteri.** Una regex su `ictus` lo troverebbe dentro
  `peri-ictus`; il matcher no, perché il confine di parola lo stabilisce il
  tokenizzatore italiano invece di `\b`.
- **Scala.** Le forme da cercare sono ~10 000: un'alternanza di regex di quella
  dimensione è lenta e illeggibile.
- **Il documento tokenizzato serve comunque** alla logica di negazione, che
  ragiona su frasi e distanze in token. Usare spaCy per il matching evita di
  mantenere due nozioni diverse di "parola".

Modello: `it_core_news_sm`, caricato **senza** NER, parser e lemmatizer — non
servono e costano tempo — con il `sentencizer` a regole al posto del parser
statistico, che su prosa clinica abbreviata è inaffidabile.

### 3.2 ConText adattato all'italiano, con marcatori ricavati dal corpus

medspaCy e scispaCy non sono utilizzabili: i loro marcatori sono scritti per
l'inglese, e `denies`, `no evidence of`, `rule out` in un referto italiano non
compaiono mai. L'algoritmo però si trasferisce: ogni marcatore apre un **ambito**
che si propaga in una direzione fino a un punto di terminazione, e le entità
dentro l'ambito ne ereditano l'attributo.

I marcatori **non sono tradotti dall'inglese ma contati sul corpus**:

| Marcatore | Occorrenze nelle 1 000 anamnesi |
|---|---|
| `non` | 2 665 |
| `nega` | 522 |
| `assenza di` | 370 |
| `senza` | 319 |
| `negativo per` | 102 |
| `sospetto` / `sospetta` | 134 / 72 |
| `pregressa` / `pregresso` | 253 / 170 |

Tre attributi, non uno: **negazione**, **incertezza** e **storicità**. La
storicità non cambia la polarità ma è clinicamente decisiva — una fibrillazione
atriale pregressa e una in atto portano a terapie diverse — quindi lo stato
resta `affermato` e la storicità viaggia nella regola registrata in
`Provenienza`, dove nessuna informazione si perde.

### 3.3 Due scelte sull'ampiezza degli ambiti

- **La virgola e la congiunzione `e` non terminano l'ambito.** In italiano
  clinico la negazione si estende regolarmente su un elenco: *«Nega diabete
  mellito, ipertensione arteriosa e dislipidemia»* nega tutti e tre.
- **`non` ha l'ambito più stretto di tutti** (4 token) pur essendo il marcatore
  più frequente. È anche il più insidioso: compare in *«non in terapia con X»*
  (negazione vera) e in *«non ha eseguito il dosaggio»*, dove non nega alcuna
  entità.

I terminatori (`ma`, `tuttavia`, `riferisce`, `presenta`, `in terapia`…)
impediscono alla negazione di scavalcare un'affermazione successiva: in *«Nega
diabete ma riferisce ipertensione»* l'ipertensione non risulta negata. Il
confine di frase resta il limite più forte.

## 4. Due difetti trovati e corretti, entrambi a monte

Costruire il gazetteer ha fatto emergere due bug **nell'estrazione ICD dello
step 2**, invisibili finché la terminologia non è stata usata davvero.

### 4.1 I modificatori fra parentesi venivano accodati invece che sostituiti

L'espansione generava le forme mettendo il modificatore in fondo. Funzionava
quando la parentesi è già finale (`ipertensione (arteriosa)`) ma produceva
forme prive di senso quando è in mezzo — e soprattutto **non generava mai la
forma più comune di tutte**: da `diabete (mellito) (non obeso) a esordio
nell'età adulta` non usciva `diabete mellito`.

Il sintomo che l'ha rivelato: il gazetteer, su *«Nega diabete mellito»*,
riconosceva soltanto `mellito` e lo collegava a **O24 — Diabete mellito in
gravidanza**. Ora i modificatori sono reinseriti nella posizione in cui stanno.

### 4.2 Le note istruttive dell'ICD finivano fra i sinonimi

`Utilizzare un codice aggiuntivo se si desidera identificare qualunque
manifestazione in atto del diabete / mellito.` — una nota al codificatore, che
va a capo. Filtrata la prima riga ma non la sua coda, sopravviveva `mellito`
come termine autonomo. Ora uno stato esplicito segue la nota fino alla fine: ha
rimosso **1 467 frammenti** dall'indice.

## 5. Un terzo difetto, questa volta nel gazetteer

L'espansione dei parentetici genera legittimamente anche il **tronco nudo**: da
`insufficienza (cardiaca) (renale)` esce `insufficienza`. Nell'indice ICD è
corretto; come voce di gazetteer è un disastro — estraeva 670 falsi positivi,
e con lui `chiusura` (194), `malattia` (190), `cronica` (170), `correzione` (98).

La correzione è una regola **ricavata dai dati e non un elenco di parole scritto
a mano**: una forma di una sola parola è ammessa solo se coincide con il
**titolo di una categoria ICD**. Nessun codice si intitola *Insufficienza*,
quindi la forma cade; E03 una volta tolto il qualificatore residuale si intitola
*Ipotiroidismo*, quindi resta. È l'ICD stesso a dire quali termini bastano da
soli a nominare una categoria.

Effetto: le condizioni estratte sono passate da 8 074 a **5 237**, cioè
**2 837 falsi positivi rimossi**, e le prime venti per frequenza sono ora tutte
termini clinici legittimi (dispnea, ipertensione arteriosa, cardiopatia,
scompenso cardiaco, dolore toracico…).

## 6. Sulle sonde dello step 0

Nel documento dello step 0 avevo scritto che le sonde esplorative sarebbero
state sostituite qui da parser definitivi. **Le riuso invece così come sono**, e
la ragione è che si sono rivelate migliori dell'attesa: interpretano il 99 %
delle voci di dimissione e il 98 % di quelle di ingresso, sono organizzate a
livelli con la provenienza di ogni match, e sono coperte da 29 test.
Riscriverle avrebbe prodotto codice equivalente con meno collaudo.

Restano in `explore_dataset.py`: il nome non è più esatto, ma spostarle avrebbe
rotto i riferimenti nella documentazione degli step precedenti.

## 7. Componenti creati

| Modulo | Responsabilità |
|---|---|
| `src/gazetteer.py` | Costruisce il `PhraseMatcher` dai vocabolari chiusi, filtra i termini inutilizzabili, restituisce le menzioni con offset e codici. |
| `src/context_it.py` | Marcatori italiani, calcolo degli ambiti, assegnazione degli attributi. Nessuna dipendenza dal resto: è testabile da solo. |
| `src/extract_a.py` | Orchestra il tutto e produce lo `StatoPaziente`. |

| File prodotto | Contenuto |
|---|---|
| `data/processed/pipeline_a/<encOid>.json` | uno stato paziente per record, 1 000 file |

Un file per record e non un unico JSON: gli stati vanno letti singolarmente
negli step successivi, e un file da centinaia di MB andrebbe caricato per intero
ogni volta.

**Test:** 30 nuovi (96 in totale). Quelli su ConText sono i più importanti
scritti finora — un errore lì inverte il significato clinico di un'affermazione.

## 8. Limiti noti

- **Gli acronimi non sono coperti.** `BPCO` non compare nel volume ICD, quindi
  non è nel gazetteer, e non l'ho aggiunto a mano: sarebbe un mapping inventato.
  È un lavoro da fare con una fonte citabile di abbreviazioni cliniche italiane.
- **Il lessico clinico non coincide con quello ICD.** `dislipidemia` non entra
  perché l'ICD scrive *Disturbi del metabolismo delle lipoproteine e altre
  dislipidemie*. È il limite strutturale del gazetteer, ed è esattamente ciò che
  le pipeline B e C dovrebbero superare: lo step 6 lo misurerà.
- **892 condizioni restano ambigue** (più codici compatibili). La
  disambiguazione ha bisogno del contesto e appartiene allo step 5.
- La storicità è registrata ma non ancora usata dal motore: lo sarà allo step 8,
  dove una condizione pregressa e una in atto vanno trattate diversamente.
- Gli ambiti sono tarati su numeri di token scelti a occhio dalle formulazioni
  reali. Sono parametri, non costanti fisiche: andrebbero verificati su un
  campione annotato a mano, che il progetto per ora non ha.
