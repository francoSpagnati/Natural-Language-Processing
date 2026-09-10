# Step 4 — Pipeline B: estrazione con un modello linguistico

Seconda delle tre pipeline di estrazione. Dove la pipeline A riconosce solo ciò
che è già nei vocabolari chiusi, questa legge il referto come lo leggerebbe una
persona: trova le menzioni, ne interpreta il contesto e scioglie le
abbreviazioni. È la pipeline con cui si misura quanto costa, in copertura, la
scelta deterministica dello step 3.

---

## 1. Quale modello, e perché

La scelta è vincolata dal costo, non dalla qualità: le API Anthropic si pagano
a consumo e non rientrano nel piano a disposizione. Si sono quindi percorse due
strade, in quest'ordine:

1. **Google AI Studio (Gemini flash)**, gratuito ma limitato a 20 richieste al
   giorno per modello — abbastanza per capire come si comporta un modello
   grande su questo compito, non per elaborare il dataset;
2. **un modello locale** (`qwen3:4b` via Ollama), che è la configurazione
   effettiva della pipeline. Vedi la sezione 6.

Entrambi stanno dietro la stessa interfaccia e la stessa cache, e si scelgono
con `--motore locale|gemini`. Quanto segue in questa sezione riguarda il
motore remoto.

La chiave sta in `.env.local`, escluso da git; non compare in nessun file
versionato. `llm_backend.chiave_api()` la legge dall'ambiente e ripiega sul file
solo se la variabile non c'è.

### Quale modello

Non il più recente, ma quello che **risponde**. Su una raffica di prove
ravvicinate:

| modello | risposte riuscite |
|---|---|
| `gemini-3.8-flash` | 1 su 4 |
| `gemini-3.7-flash` | 2 su 4 |
| `gemini-3.5-flash` | 4 su 4 |
| `gemini-3-flash-preview` | 4 su 4 |

I fallimenti sono `503 UNAVAILABLE`, cioè saturazione del servizio. Su una corsa
di centinaia di record la reperibilità pesa più della versione, e un modello
stabile (non `preview`) mantiene i risultati confrontabili nel tempo: il
predefinito è quindi **`gemini-3.5-flash`**, sostituibile con `--modello`.

### Come è stato verificato il protocollo

La documentazione pubblica descrive un endpoint `v1beta/interactions` con un
campo `response_format`. Interrogando l'API con la chiave reale, funzionano
**entrambe** le forme, e quella usata qui è `v1beta/models/{modello}:generateContent`
con `generationConfig.responseJsonSchema`. Anche `thinkingConfig.thinkingLevel`
è stato verificato sul campo: `"thinkingLevel"` al primo livello di
`generationConfig` viene rifiutato, dentro `thinkingConfig` è accettato e azzera
i token di ragionamento (da ~620 a 0 su un compito banale).

Il principio è lo stesso applicato alle knowledge base: la forma del messaggio
è stata **misurata contro la fonte**, non dedotta da una pagina di
documentazione.

---

## 2. Che cosa si chiede al modello, e cosa no

Lo schema di uscita (`EstrazioneLLM` in `schema.py`) è deliberatamente più
povero di `StatoPaziente`. Al modello si chiede solo ciò che sa fare in modo
verificabile.

**Non si chiedono i codici.** Un LLM produrrebbe volentieri un ATC o un ICD, e
spesso plausibile, ma sarebbe conoscenza interna del modello e non conoscenza
tracciabile a una fonte citabile — il vincolo di provenienza che regge tutto il
progetto. ATC e ICD sono assegnati **dopo**, dagli stessi risolutori della
pipeline A (`risolutori.py`), che poggiano su AIFA e sul volume ICD-10 italiano.
Nello schema inviato al modello non esiste nemmeno un campo dove scrivere un
codice: il test `test_schema_non_prevede_codici` lo verifica.

Ha un secondo effetto, sul metodo: a **normalizzazione identica**, il confronto
dello step 6 misura la sola differenza di *estrazione*, che è ciò che si vuole
confrontare. Se ogni pipeline codificasse a modo suo, la differenza osservata
sarebbe la somma di due differenze non separabili.

### La citazione letterale come rilevatore di allucinazioni

Ogni menzione deve riportare la porzione di referto da cui proviene, copiata
carattere per carattere. La pipeline la ricerca nel testo originale: se non la
trova, l'entità resta senza offset e il record viene annotato.

È una verifica automatica e quantificabile, non un'impressione. **Sui 14 record
elaborati: 0 menzioni non ancorate su 552** (0,00%). Su questo campione il
modello non ha inventato nulla.

### L'unico campo interpretativo: `concetto`

Alle condizioni si chiede anche la forma estesa, con gli acronimi sciolti. Non
viola il vincolo di provenienza perché non è un codice e non viene creduto sulla
parola: serve come **chiave di ricerca** nell'indice ICD ufficiale, che resta
l'unica autorità a decidere se quel concetto esista e con quale codice.

È anche il punto in cui la pipeline B può superare la A. Esempio reale dal
dataset: `BBS` → «blocco di branca sinistra» → **I44.7**. La pipeline A su `BBS`
non ha alcun appiglio, perché nel volume ICD l'acronimo non compare.

L'espansione proposta dal modello resta **sempre** registrata nella regola di
provenienza, anche quando il risolutore aggancia un termine diverso: è un dato
prodotto dalla pipeline e deve restare ispezionabile.

---

## 3. Decisioni tecniche

### `urllib` invece di un SDK

Il protocollo è una singola POST JSON. Farla con la libreria standard tiene il
formato del messaggio visibile nel codice invece che sepolto in una dipendenza,
è coerente con `fetch_external_kb.py`, e non lega la riproducibilità dei
risultati alla versione di un pacchetto. Costa una trentina di righe fra
ritentativi e decodifica degli errori. **Nessuna dipendenza aggiunta.**

### Cache su disco

Ogni chiamata è indicizzata dall'impronta SHA-256 di modello, istruzioni, testo,
schema, temperatura e livello di ragionamento. Due conseguenze:

* rilanciare la pipeline non consuma quota e non ripete il costo;
* la valutazione dello step 11 è **ripetibile**: gli stessi record danno gli
  stessi risultati, cosa che con un modello generativo non sarebbe altrimenti
  garantita.

Cambiare il prompt o il modello invalida la cache da sé, perché entrambi entrano
nell'impronta.

### Esecuzione concorrente

L'API impiega **decine di secondi** per record (misurate: 6–23 s persino per una
richiesta banale). In sequenza, mille record richiederebbero oltre dieci ore. Il
runner usa quindi un pool di thread (`--parallele`, predefinito 8).

Il ripiego sul gazetteer attraversa la pipeline spaCy, che non è garantita
sicura da più thread: l'accesso è serializzato con un lucchetto. È un ripiego e
non il percorso principale, quindi la contesa resta bassa.

### Quota giornaliera: un errore che non va ritentato

Il livello gratuito impone **20 richieste al giorno per modello**
(`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, letto dai dettagli del
429). Va distinto dagli altri 429: un limite al minuto si supera aspettando, uno
al giorno no.

Nella prima versione il backend ritentava cinque volte per ogni record,
sprecando minuti in errori annunciati. Ora `ErroreQuotaGiornaliera` interrompe
la corsa, i record rimanenti non vengono nemmeno tentati e il messaggio dice che
i risultati già ottenuti sono in cache. La stessa corsa che prima impiegava
minuti ora termina in **1 secondo**. Quando invece l'API indica un `retryDelay`,
il backend aspetta quello invece di indovinare con un ritardo esponenziale.

---

## 4. Un difetto trovato costruendo, non ipotizzando

La copertura ATC della pipeline B era del **59%**, contro il 93,5% della A. Il
divario non era un limite del modello ma un mio difetto di conversione.

Nel referto di dimissione un farmaco è scritto per esteso:

```
Furosemide (Lasix cpr. 25 mg)
```

Il modello cita fedelmente l'intera menzione — è ciò che gli è stato chiesto —
ma il vocabolario ATC ha una voce per `Furosemide` e una per `Lasix`, e la
stringa intera non risolve mai. La pipeline A non incontra il problema perché il
suo parser separa i tre pezzi *prima* di cercarli.

`RisolutoreATC.risolvi_menzione` scompone la menzione a valle: prima la stringa
intera, poi il principio attivo, poi il nome commerciale ripulito da forma e
dose con `radice_nome_commerciale`, la funzione già collaudata nello step 0. Il
metodo restituisce anche **quale forma** ha prodotto il collegamento, che
finisce nella regola di provenienza: è la stessa lezione dello step 2, dove un
codice giusto era stato registrato con un metodo sbagliato.

Se principio attivo e nome commerciale portassero a codici diversi il risultato
è `AMBIGUO` e nessuno dei due viene scelto: un disaccordo fra due vie che
dovrebbero concordare è un dato da guardare, non da risolvere in silenzio.

**Effetto misurato: copertura ATC dal 59,0% all'87,4%.**

---

## 5. Il ripiego sulla categoria ICD

Il 72% delle condizioni restava senza codice non perché il concetto fosse
sbagliato, ma perché il lessico clinico e quello del volume ICD divergono. Il
caso tipico: **«fibrillazione atriale» non è un termine indicizzato**. Il volume
elenca solo le forme qualificate — parossistica (I48.0), persistente (I48.1),
cronica (I48.2), non specificata (I48.9) — e la categoria che le raccoglie,
`I48`.

La regola aggiunta è ricavata per intero dalla gerarchia del volume e non
contiene una riga di conoscenza medica scritta a mano:

> Se **tutti** i termini dell'indice che estendono la menzione a confine di
> parola ricadono in un'unica categoria a tre caratteri, allora la menzione
> denota quella categoria e il suo codice è la risposta.

Un codice a tre caratteri è una codifica ICD-10 valida, non un ripiego
inventato: dire `I48` significa «fibrillazione o flutter atriale, senza
specificare quale forma», che è esattamente ciò che il referto dice.

Quando invece le forme qualificate si distribuiscono su categorie diverse la
menzione resta `AMBIGUO` con i candidati in vista. «Diabete mellito» tocca
E10 (tipo 1), E11 (tipo 2), E12 e O24 (gestazionale): distinguerli richiede il
contesto clinico, che è il compito dello step 5.

### Un vincolo imposto da un falso positivo

La prima versione della regola generalizzava anche con **una sola** forma
qualificata, e ha prodotto subito un errore grave: «insufficienza mitralica» →
`Q23`, cioè *malformazioni congenite delle valvole aortica e mitrale*. L'unico
termine indicizzato che estende quella menzione è «insufficienza mitralica
congenita» (Q23.3), e la regola ne aveva dedotto la categoria sbagliata,
attribuendo a una valvulopatia acquisita un codice di cardiopatia congenita.

Con una sola forma non si distingue un **concetto padre** da un **fratello più
specifico**. La regola richiede quindi almeno due forme qualificate: è il
segnale che il volume sta davvero enumerando le varianti di un concetto
generico. Il caso è fissato in un test di regressione.

### Effetto misurato

| | prima | dopo |
|---|---|---|
| condizioni con codice ICD | 25,0% | **28,9%** |
| senza codice (`NIL`) | 72,1% | **64,6%** |
| ambigue | 2,9% | 6,5% |

L'aumento delle ambigue non è un peggioramento: sono menzioni che prima
risultavano semplicemente NIL e ora mostrano i candidati fra cui lo step 5 dovrà
scegliere.

Il metodo che ha prodotto ogni collegamento (`termine_esatto`,
`generalizzazione_a_categoria`, `gazetteer`, …) è registrato nella provenienza
di ogni condizione: un codice di categoria e uno di sottocategoria non valgono
la stessa cosa e chi legge deve poterli distinguere senza risalire al testo.

---

## 6. Il passaggio al modello locale

La quota gratuita di AI Studio — 20 richieste al giorno per modello — rende
impraticabile una corsa sul dataset, e la fatturazione e' stata esclusa. La
pipeline B gira quindi su un **modello eseguito in locale** con Ollama,
`qwen3:4b`, dietro la stessa interfaccia e la stessa cache del backend remoto
(`--motore locale|gemini`).

Anche in locale la generazione e' **vincolata allo schema**: Ollama accetta uno
JSON Schema nel campo `format` e lo impone al decodificatore. E' cio' che rende
sostenibile il passaggio a un modello molto meno capace — la validita'
strutturale e' garantita dal motore, non dalla bravura del modello.

### L'hardware, e cosa ci sta

| | |
|---|---|
| CPU | AMD Ryzen AI 7 PRO 350, 8 core / 16 thread |
| RAM | 14 GiB |
| GPU | Radeon 860M (`gfx1152`), via ROCm — 37/37 livelli sulla GPU |

Il tetto pratico e' un modello da ~4 miliardi di parametri quantizzato. Due
tentativi con modelli piu' grandi hanno fatto intervenire l'**OOM killer del
kernel**, che ha ucciso `ollama` insieme all'editor: `gemma2:9b` (5,4 GB) e
`medgemma-4b-it`, che pur essendo un file da 3,3 GB e' multimodale e in memoria
occupa molto di piu'. Il modello medicale resta quindi **non valutato**.

### Due difetti trovati misurando, non ipotizzando

**1. Il campo `system` di Ollama non raggiungeva il modello.** Stesso record,
stesse identiche istruzioni:

| dove stanno le istruzioni | token generati | risultato |
|---|---|---|
| campo `system` | 39 | **0 entita'** |
| in testa al `prompt` | 3 063 | 40 condizioni, 6 farmaci |

Non era un limite del modello ne' del ragionamento: era il canale sbagliato.

**2. Lo schema non dichiarava obbligatori i campi di primo livello.** Pydantic
non marca obbligatorio un campo che ha un valore predefinito, e il modello
sfruttava la scappatoia restituendo `{"condizioni": []}` e omettendo il resto.
Il predefinito serve al codice Python, non al modello: `schema_estrazione_llm()`
ora elenca tutti i campi in `required`.

### Il prompt riscritto per un modello piccolo

La prima versione del prompt enunciava regole astratte. Su un modello da 4
miliardi di parametri ha prodotto l'errore piu' grave possibile: **le negazioni
finivano nel testo del concetto invece che nel campo `stato`**.

| testo nel referto | `stato` | `concetto` |
|---|---|---|
| «Non noto distiroidismo» | `affermato` ❌ | "non distiroidismo" |
| «no diabete» | `affermato` ❌ | "non diabete" |
| «nega iperuricemia» | `affermato` ❌ | "non iperuricemia" |

E' esattamente cio' per cui esiste la logica ConText dello step 3, ed e' cio'
che rende una condizione sicura o pericolosa per il filtro dello step 8.

Il prompt e' stato riscritto **per esempi invece che per regole**, con la
negazione come regola numero uno e l'errore commesso mostrato come
controesempio esplicito (`SBAGLIATO: concetto "non diabete" con stato
"affermato"`). Sullo stesso record: **3 negazioni su 3 corrette**, acronimi
sciolti meglio (`OSAS` → «sindrome delle apnee ostruttive del sonno») e 16% di
token generati in meno.

### Cosa il modello locale fa bene e cosa no

Sul record di prova, 38 condizioni:

* **0 menzioni non ancorate.** Ogni citazione esiste alla lettera nel referto:
  nessuna allucinazione.
* **negazione corretta** dopo la riscrittura del prompt;
* **21% di menzioni ripetute** (38 menzioni per 30 concetti distinti). Non
  vengono eliminate: hanno offset diversi, sono menzioni distinte dello stesso
  fatto, e il progetto richiede che tutti i dati restino ispezionabili. La
  deduplica appartiene semmai al knowledge graph dello step 7;
* **estrae ancora non-condizioni** («108 glicemia», «Vaccino x 3»,
  «ecocardiogramma normofunzione») e talvolta la familiarita', nonostante le
  regole lo vietino. In gran parte questi si autoescludono in fase di
  normalizzazione, perche' non corrispondono ad alcun termine ICD;
* **sotto-estrae dall'elenco di dimissione**: su un referto con 889 caratteri di
  terapia ha trovato 6 farmaci contro i 16 della pipeline A. E' il campo
  semi-strutturato che il parser deterministico interpreta gia' al 99%.

### Tempi

| | s/record | 857 record |
|---|---|---|
| referto intero | 199 | ~47 h |
| sola anamnesi | 158 | ~38 h |

~11 token/s con il modello interamente sulla GPU. Dare al modello la sola prosa
dell'anamnesi fa risparmiare il 21%, molto meno di quanto ci si aspetterebbe: il
costo sta quasi tutto nelle condizioni estratte dalla prosa, non nei campi di
terapia.

---

## 7. Risultati misurati (motore remoto)

Su **14 record** (quanti la quota gratuita ha consentito), 552 entità estratte.
Queste misure sono state prese con il **prompt precedente** e con Gemini, prima
del passaggio al modello locale: restano come riferimento di quanto un modello
grande ottiene sullo stesso compito.

| | pipeline B | pipeline A (riferimento) |
|---|---|---|
| condizioni per record | 22,0 | 5,2 |
| farmaci con ATC | **87,4%** | 93,5% |
| condizioni con ICD | **25,0%** | 83% |
| menzioni non ancorate | **0,00%** | — (per costruzione) |

I due numeri di copertura **non sono confrontabili così come sono**, ed è il
risultato più istruttivo dello step. La pipeline A trova solo ciò che i suoi
vocabolari già contengono, quindi quasi tutto ciò che trova ha un codice: l'83%
è alto perché il denominatore è ristretto. La pipeline B estrae quattro volte
più condizioni per record, comprese quelle che l'ICD non copre a quella
granularità, e il denominatore si allarga. Una copertura più bassa su una
recall molto più alta può significare più entità codificate in assoluto, non
meno: quantificarlo è esattamente il compito dello step 6, a insiemi di record
identici.

I farmaci senza ATC rimasti sono in buona parte legittimi: classi terapeutiche
(`diuretico`, `SGLT2i`, `ARNI`, `glifozina`), integratori fuori dal registro ATC
(`Ferrograd`), e farmaci che compaiono solo nella prosa e che il vocabolario —
costruito dai campi strutturati — non ha mai visto (`metronidazolo`,
`piperacillina/tazobactam`). Quest'ultimo caso è un limite del *vocabolario*,
non della pipeline, e si supera risolvendo direttamente contro AIFA.

### Costo

Misurato dalle chiamate reali: **1 892 token in ingresso e 2 655 in uscita per
record**. Sul listino AI Studio:

| modello | 1 000 record | 857 record | 857 via Batch API |
|---|---|---|---|
| `gemini-3.5-flash-lite` | $7,21 | $6,18 | $3,09 |
| `gemini-3.8-flash` | $11,38 | $9,75 | $4,87 |
| `gemini-3.5-flash` | $26,73 | $22,91 | $11,46 |

---

## 7bis. La corsa definitiva: 200 record sul modello locale

Le misure della sezione precedente venivano da quattordici record su Gemini. Qui
ci sono quelle vere.

### Come si e' scelto il modello

Prima di impegnare quindici ore di calcolo si sono misurati i due candidati che
l'hardware regge, sugli stessi sei record:

| | `qwen3:4b` | `qwen3.5:4b` |
|---|---|---|
| secondi per record | **159** | 195 |
| token al secondo | **11,0** | 8,1 |
| citazioni ritrovate nel referto | **90,6%** | 60,0% |
| richiamo sulle condizioni | 73,9% | **82,6%** |
| richiamo sui farmaci in prosa | 25,0% | **75,0%** |
| negazioni corrette | **2/4** | 0/4 |

`qwen3.5:4b` estrae di piu', e su un progetto diverso avrebbe vinto. Qui no: il
40% delle sue citazioni non si ritrova alla lettera nel referto, e su centocinquanta
menzioni non e' rumore statistico. Le citazioni non ritrovate sono quelle che
mandano a vuoto sia il rilevatore di allucinazioni sia gli offset di provenienza,
cioe' le due garanzie su cui poggia tutto il progetto. Un modello che estrae di
piu' ma non si lascia verificare vale meno di uno che estrae meno e si lascia
verificare, quindi la scelta e' caduta su **`qwen3:4b`**.

### Un difetto trovato dalla verifica su due record

La verifica pre-corsa su due soli record ha mostrato **14 farmaci su 14 senza
codice ATC**. Il campo della terapia all'ingresso ha la forma `Medrol: 4 mg cpr.
/die (ore 8)` e il modello cita la riga intera, mentre il vocabolario contiene la
voce `Medrol`: la scomposizione delle menzioni composte gestiva solo il formato
di dimissione, che separa con la parentesi, e non quello d'ingresso, che separa
con i due punti. Corretto il difetto, la copertura di quei due record e' passata
**da 0% a 100%**. Nove ore di calcolo su un difetto del genere sarebbero state
buttate.

### La corsa riprendibile

Una corsa di quindici ore su un portatile viene interrotta: il coperchio si
chiude, il sistema sospende, la memoria finisce. Il meccanismo di ripresa e'
quindi parte del componente, non un accessorio.

Ogni record produce il suo file appena e' pronto, e un registro `_corsa.json` si
aggiorna ogni cinque. Rilanciare lo stesso comando salta i record che hanno gia'
un file. Il registro contiene pero' anche l'**impronta della configurazione** —
motore, modello, ragionamento, seme, hash del prompt e hash dello schema — e se
la ripresa avviene con una configurazione diversa il programma si ferma
elencando cosa e' cambiato. Mescolare in una cartella meta' risultati di un
modello e meta' di un altro produrrebbe un insieme che nessuno puo' piu'
interpretare, e il registro lo rende impossibile per costruzione.

Il meccanismo e' servito subito: due record sono andati in timeout dopo tre
tentativi, e il rilancio dello stesso comando ha ripreso esattamente quei due
(`ripresa: 198 gia' completati, 2 da fare`).

### Produzione misurata

**198 record in 881 minuti** (14 h 41 m), 421 110 token in ingresso e 430 955 in
uscita, 8,2 token al secondo. Il costo reale e' risultato **267 secondi per
record** contro i 159 stimati dal banco di prova: il banco misurava referti di
lunghezza media, la corsa ha incontrato anche i lunghi.

| | | |
|---|---|---|
| condizioni | 5 017 (**4 222 distinte**, vedi § 7quinquies) | **1 959 con codice ICD (39,0%)**, 176 ambigue |
| farmaci | 1 504 | **1 326 con codice ATC (88,2%)** |
| allergie | 251 | |
| stato clinico | affermato 4 641 · negato 275 · incerto 101 | |
| momento della terapia | ingresso 1 086 · dimissione 376 · narrativo 42 | |
| menzioni non ancorate | **883 su 6 772 (13,0%)** | il numero stampato in corsa, 11,4%, era sbagliato: vedi § 7septies |

L'11,4% di citazioni non ritrovate e' il numero piu' importante della tabella,
perche' e' la misura di quanto il modello si scosta dal testo. Sono parafrasi:
il referto dice `Nega angor` e il modello scrive `negazione di angor`. Restano
tutte nel file, marcate, con offset `null`: nessuna e' stata cancellata, cosi'
che il difetto sia contabile e non invisibile.

---

## 7ter. La negazione, misurata sul serio

Le quattro negazioni del banco di prova non bastavano a dire niente. Sui 198
record si puo' invece confrontare pipeline B con pipeline A, che la negazione la
decide con ConText deterministico.

Due menzioni sono considerate la stessa quando cadono nello stesso campo e i loro
intervalli di caratteri si sovrappongono: e' l'unico criterio che non dipende da
come le due pipeline hanno scelto i confini. Le 692 menzioni non ancorate sono
escluse d'ufficio, perche' senza offset non c'e' niente da sovrapporre.

**Su 688 menzioni confrontabili l'accordo e' del 92,0%**, con 55 disaccordi.

E il disaccordo ha una causa dominante che non e' un errore di negazione.

---

## 7quater. L'asse mancante: chi ha la malattia

Ventuno dei 55 disaccordi hanno tutti la stessa forma:

```
A = affermato    B = negato    «Familiarita per cardiopatia ischemica (padre, 56 aa)»
```

**Hanno torto tutte e due.** La frase non dice che il paziente ha la cardiopatia,
e non dice nemmeno che non ce l'ha: dice che ce l'ha suo padre. Nello schema
c'era un solo campo, `stato`, che misura la polarita' di un'affermazione, e la
familiarita' non e' una questione di polarita' — e' una questione di **soggetto**.
Costrette a scegliere, le due pipeline hanno scelto in modo diverso, e nessuna
delle due scelte era rappresentabile correttamente.

ConText ha quattro assi, non tre. Il quarto e' l'**experiencer**, e nella prima
versione dello schema mancava.

### La correzione

Lo schema sale a **1.1.0** con un campo nuovo su ogni condizione:

```python
class Soggetto(str, Enum):
    PAZIENTE = "paziente"
    FAMILIARE = "familiare"
```

I due assi restano indipendenti, e il corpus dimostra che devono esserlo:
`familiarita negativa per CAD` e' **insieme** `soggetto=familiare` e
`stato=negato`. Comprimerli in un campo solo perdeva sempre una delle due
informazioni.

### I marcatori vengono dal corpus, non dall'intuizione

Contati sul file grezzo, come tutti gli altri marcatori del progetto:

| espressione | occorrenze |
|---|---|
| `familiarita` (tutte le forme) | **508** |
| di cui `familiarita per` | 431 |
| `familiarita positiva` | 27 |
| `familiarita negativa` | 18 |
| `anamnesi familiare` | 28 |
| `storia familiare` | 2 |

`padre`, `madre`, `fratello` **non sono marcatori**, benche' frequenti (118, 108,
50): nel corpus compaiono quasi sempre come precisazione fra parentesi *dentro*
un ambito gia' aperto da `familiarita`, e promuoverli aprirebbe ambiti su frasi
che parlano del paziente.

### Un terminatore che il corpus ha imposto

I referti incollano piu' affermazioni senza punteggiatura, segnalando l'inizio
della successiva con la maiuscola:

```
Familiarita per cardiopatia ischemica ed ipertensione arteriosa Ex fumatore, 4-5 sigarette die
```

Senza un terminatore, `Ex fumatore` diventerebbe un'abitudine del padre. La
maiuscola pero' deve essere seguita da una minuscola, altrimenti l'ambito si
spezzerebbe su ogni acronimo — `CAD`, `IMA`, `MCV`, `HCM` sono ovunque. E il
taglio non si applica dentro una parentesi, perche' le precisazioni sui parenti
ne sono piene: `diabete mellito (padre, affetto da Parkinson, madre ETP)`.

Sui 538 ambiti trovati nel corpus la regola ne accorcia 11, e l'ispezione dice
che 8 sono accorciamenti corretti. Il compromesso e' voluto: un ambito troppo
corto perde una marcatura familiare, uno troppo lungo toglie al paziente una
condizione che ha davvero — e il secondo errore e' quello che il filtro di
sicurezza pagherebbe caro.

### Una sola implementazione per tre pipeline

La regola lavora su **offset di carattere**, non sui token di spaCy, e vive in
`risolutori.py` accanto alle altre normalizzazioni condivise. E' una scelta
deliberata: la pipeline B non costruisce un documento spaCy — ha solo il testo
del campo e gli offset della citazione — e due implementazioni della stessa
regola divergerebbero, facendo misurare allo step 6 anche quella differenza
invece del solo riconoscimento delle menzioni.

### Verifica della correzione

Rifatta girare, la pipeline A produce **zero differenze su 1 000 record** oltre
al nuovo campo: la modifica e' additiva, non ha spostato nulla di quanto c'era.
Trova 325 condizioni familiari su 5 237.

La pipeline B non e' stata rifatta girare — sarebbero altre quindici ore per un
campo che non viene dal modello. I 198 file sono stati migrati da
`src/migra_soggetto.py`, che applica la stessa funzione agli stessi ingressi. Che
questo dia per costruzione lo stesso risultato e' stato **provato e non
assunto**: la migrazione applicata alla vecchia uscita della pipeline A riproduce
esattamente la nuova, su tutti e 1 000 i record.

### Cosa resta aperto

La Regola 3 del prompt dice al modello di **non elencare** la familiarita'. Il
modello la elenca comunque, marcandola `negato` — che era la cosa piu' sensata
che potesse fare quando nello schema non c'era un posto per lei. Ora c'e', e la
regola va riscritta: *elencale, il soggetto lo calcola la pipeline*. Non e' stato
fatto adesso di proposito, perche' cambiare il prompt cambia l'impronta della
configurazione e renderebbe i 198 record non piu' riprendibili ne' confrontabili.
Va fatto insieme alla prossima corsa completa.

---

## 7quinquies. Chi ha ragione, quando le due pipeline non concordano

Con l'asse `soggetto` in funzione, l'accordo sullo stato clinico passa da 92,0%
a **94,9%**: 612 menzioni concordi su 645 confrontabili, contando solo quelle
che entrambe attribuiscono al paziente. L'asse `soggetto` concorda su 688 casi
su 688 — un risultato debole ma non nullo, perche' A e B hanno confini di
menzione diversi e la regola avrebbe potuto rispondere diversamente sui due
intervalli.

Restano 33 disaccordi, ed e' stato lo sforzo piu' utile dello step: sono stati
letti tutti e trentatre nel referto originale, uno per uno.

| chi ha ragione | casi |
|---|---|
| pipeline A (ConText deterministico) | **23** |
| pipeline B (`qwen3:4b`) | **9** |
| nessuna delle due | 1 |

**Dove vince A.** Il modello ignora marcatori che ha sotto gli occhi e che a
volte cita lui stesso: *«Si ricovera per dispnea in verosimile scompenso
cardiaco acuto»* -> B risponde `affermato`; *«in assenza di embolia polmonare»*,
*«Non versamento pericardico»*, *«nega iperuricemia, gotta»* -> B risponde
`affermato` su tutte. Sono negazioni e incertezze esplicite, con il marcatore
immediatamente prima della menzione. Un modello da quattro miliardi di parametri
le sbaglia dove una regola di prossimita' di cinquanta righe le prende.

**Dove vince B**, e sono i casi che spiegano perche' la pipeline esiste:

* *«**Asintomatico per** dolore toracico o equivalenti anginosi»* — A dice
  `affermato` perche' `asintomatico per` non e' nella lista dei marcatori. Non e'
  un difetto correggibile in generale: si puo' aggiungere questa espressione, ma
  la successiva sara' un'altra.
* *«Dall'ultimo ricovero **non riferiti** episodi sincopali o dispnea»* — stesso
  problema.
* *«episodi di cardiopalmo pregressi nel 2008 **dubbi** per tachicardia»* — la
  lista ha `dubbio` e `dubbia`, non `dubbi`.
* *«BPCO stadio GOLD **non** noto, artrite gottosa polso e mano dx nel 2023»* —
  il `non` appartiene a `non noto`, ma l'ambito di A scavalca la virgola e nega
  anche l'artrite. E' il prezzo diretto della scelta di **non** far chiudere
  l'ambito dalla virgola, presa perche' gli elenchi negati sono la norma
  (*«nega diabete, ipertensione e dislipidemia»*). Il modello, che legge la
  frase invece di contare i token, qui non si sbaglia.
* *«terapia con sacubitril/valsartan, **non** tollerata per ipotensione
  sintomatica»* — il `non` e' di `non tollerata`; il paziente l'ipotensione ce
  l'ha davvero.
* *«Si ricovera **nel sospetto di** ipertensione polmonare in artrite psoriasica»*
  — il sospetto riguarda l'ipertensione polmonare, l'artrite il paziente ce l'ha.

Il quadro e' quindi: **la regola deterministica sbaglia in modo sistematico e
prevedibile** (marcatori che non ha, ambiti che scavalcano), **il modello sbaglia
in modo sparso e sorprendente** (ignora marcatori espliciti). Sono due profili di
errore diversi, ed e' esattamente il tipo di complementarita' che lo step 6 deve
quantificare.

**Il caso che nessuna delle due prende:** *«ricoverata per FA tachifrequente con
sospetto di embolia polmonare (escluso con angioTC)»*. L'embolia e' stata
**esclusa**; A dice `incerto`, B dice `affermato`, e la risposta giusta e'
`negato`. La parentesi che rovescia l'affermazione e' fuori dalla portata di
entrambe.

**Un limite dell'asse nuovo, trovato negli stessi 33 casi:** *«secondo figlio
deceduto a 5 mesi per probabile cardiopatia congenita»* resta marcato
`soggetto=paziente` da tutte e due, perche' `figlio` non e' un marcatore. E' la
conseguenza diretta della scelta di non promuovere i termini di parentela, ed e'
un compromesso, non una svista: promuoverli catturerebbe questo caso e ne
romperebbe molti altri.

---

## 7sexies. Il difetto piu' grave: la generazione degenere

Il confronto ha fatto emergere un problema che nessuna misura precedente vedeva.

**795 delle 5 017 condizioni (15,8%) sono duplicati esatti** — stesso campo,
stessa citazione, stesso concetto. Nella pipeline A i duplicati sono **zero**,
per costruzione: il gazetteer trova ogni intervallo una volta sola.

E non sono distribuiti. Sono concentrati:

| | |
|---|---|
| record con almeno un duplicato | 41 su 198 |
| record con una condizione ripetuta 10+ volte | **6** |
| duplicati concentrati in quei 6 record | **529 su 795** |

In sei record il modello e' entrato in un **ciclo di generazione degenere**, e ha
ripetuto la stessa condizione fino a 102 volte di fila (`necrosi miocardica
inferolaterale` ×77, in un altro record una singola condizione ×102). E' il
comportamento noto dei modelli piccoli in decodifica vincolata da uno schema: il
decodificatore garantisce che l'uscita sia JSON valido e conforme, e infatti lo
e' — un array di oggetti tutti uguali e' perfettamente valido. **La validita'
strutturale non e' validita' semantica**, ed e' il limite preciso della garanzia
che lo schema offre.

Avevo attribuito a questo ciclo anche i due timeout. **Era sbagliato**, e la
diagnosi vera e' nel paragrafo seguente.

**Conseguenza sul conteggio.** Il numero di condizioni della pipeline B non e'
5 017 ma **4 222 distinte**, ed e' quello che va usato nel confronto dello step 6:
usare il numero grezzo attribuirebbe alla pipeline B un richiamo che non ha.

**Cosa non e' stato fatto, e perche'.** I duplicati non sono stati rimossi dai
file. Sono un difetto reale del componente e vanno visti; cancellarli
renderebbe la pipeline migliore di quanto sia. La deduplicazione va fatta al
momento del confronto, dove e' esplicita e misurabile, oppure a monte con
`repeat_penalty` e un tetto al numero di elementi nella prossima corsa — non
nascondendo il dato.

---

## 7septies. La verifica dei numeri, e cosa ha trovato

Ogni cifra dichiarata sopra e' stata ricalcolata dai file su disco con codice
indipendente da quello della pipeline. Condizioni, farmaci, codici, stati e
duplicati coincidono. Due voci no, e valeva la pena guardarle.

### Un errore mio

Il primo ricalcolo dava 1 333 duplicati invece di 795, perche' contava come
duplicate anche menzioni identiche in **record diversi** — che duplicati non
sono. Il numero giusto e' 795, come dichiarato.

### Un difetto vero, che nascondeva il difetto peggiore della pipeline

`misura_produzione` contava le menzioni non ancorate per condizioni e farmaci ma
**non per le allergie**, mentre nel denominatore le allergie c'erano. Il tasso
riportato in corsa, 11,4%, era quindi sottostimato: il valore vero e' **13,0%**
(883 su 6 772).

La differenza non e' aritmetica. Le allergie sono **il tipo di menzione che il
modello sbaglia di piu'**: 111 su 251, il **44,2%**, non si ritrovano nel referto,
contro il 13,8% delle condizioni e il 5,3% dei farmaci. Un difetto di conteggio
di una riga teneva invisibile il problema piu' grave della pipeline.

### Il problema piu' grave

Su 24 record dei 198, **l'anamnesi non nomina mai le allergie** — nessuna
occorrenza di `allerg`, `intolleran`, `anafila` — e la pipeline B ne estrae
comunque. Sono **65 allergie su 251, il 25,9%**, e in diversi casi con
`stato_sezione_allergie = affermato`, cioe' dichiarando che il clinico le ha
confermate.

Il caso peggiore, il record `10066482`: l'anamnesi non parla di allergie, e il
modello ne produce dieci, che sono **la lista dei farmaci che il paziente
assume**, copiata dal campo della terapia all'ingresso:

```
allergene: "Acido acetilsalicilico (Acido acetils eg cpr.gastr. 100 mg)"
allergene: "Bisoprololo (Congescor cp.riv. 2.5 mg)"
allergene: "Rosuvastatina (Rosuvastatina ari cp.riv. 20 mg)"
```

Per un sistema che deve **raccomandare una terapia**, questo e' l'errore
peggiore possibile: un'allergia inventata al farmaco che il paziente sta gia'
prendendo bloccherebbe la terapia corretta. Non e' un errore di richiamo, e'
un'inversione di significato.

Nello stesso gruppo, il record `10161552` ha allergie vere nel referto
(`Trimetoprim/sulfametoxazolo, Ciclosporina, Amoxicillina/acido clavulanico`) ma
la pipeline ne estrae 45, con `Ciprofloxacin` ripetuto decine di volte: e' di
nuovo la generazione degenere del § 7sexies, e la grafia inglese invece di
`Ciprofloxacina` e' anche il motivo per cui non si ancora.

### Un difetto della pipeline, non del modello

Delle 883 menzioni non ancorate, **138 sono testo che nel record esiste davvero,
ma in un altro campo**. Per le allergie sono 59 su 111, e la colpa qui non e' del
modello: `AllergiaLLM` **non ha un campo `campo`**, e la pipeline attribuisce
d'ufficio ogni allergia all'anamnesi. Quando il modello cita correttamente il
campo della terapia, l'ancoraggio fallisce per costruzione.

Vanno corrette due cose distinte, e vanno tenute distinte: dare alle allergie il
campo di provenienza come ce l'hanno condizioni e farmaci (difetto della
pipeline), e impedire al modello di scambiare la lista dei farmaci per una lista
di allergie (difetto del prompt).

### Un terzo difetto: farmaci elencati come condizioni

Il risolutore ATC riconosce **507 delle condizioni distinte di pipeline B come
farmaci** — `bisoprololo`, `levetiracetam`, `furosemide`, `pantoprazolo`. Il
modello li ha messi nell'elenco sbagliato.

### Il conteggio onesto

Mettendo insieme i tre difetti, il numero di condizioni che la pipeline B produce
e che sono utilizzabili nel confronto e':

| | |
|---|---|
| condizioni grezze | 5 017 |
| − duplicati nello stesso record | −795 |
| − farmaci elencati come condizioni | −507 |
| − citazioni non ritrovate nel referto | −309 |
| **= condizioni utilizzabili** | **3 406** (67,9% del grezzo) |

Sugli stessi 198 record la pipeline A ne produce **1 075** e la pipeline C
**1 112**. Il vantaggio di richiamo della pipeline B resta quindi reale e grande
— circa il triplo — ma e' **3 406 contro 5 017**, e usare il numero grezzo nello
step 6 le attribuirebbe un richiamo che non ha.

### Verifiche di regressione

* Le impronte di configurazione (schema e istruzioni) sono **invariate** dopo
  tutte le modifiche: la corsa resta riprendibile.
* La migrazione dello schema non ha alterato **nessuno** dei 198 file oltre al
  campo nuovo, confronto fatto contro una copia presa prima di migrare.
* La pipeline A rifatta girare da **zero differenze su 1 000 record** oltre al
  campo nuovo.
* 199 test, tutti verdi, incluso quello che fissa il conteggio delle allergie.

---

## 7octies. Perche' due record non si estraggono: due difetti, nessuno dei quali era quello ipotizzato

Il rilancio della corsa ha ripreso correttamente i due record mancanti e li ha
persi di nuovo: **tre ore, sei tentativi da trenta minuti, zero record**. La
temperatura e' 0, quindi stesso modello, stesso testo, stesso prompt, stesso
esito — rilanciare identico non era una scommessa ragionevole, e il registro
non poteva saperlo.

Per capirne la causa serviva vedere cosa il modello produce *mentre* lo produce,
non aspettare trenta minuti per un errore. Una sonda che chiama ollama in
**streaming** e legge i pezzi man mano ha dato la risposta in quattro minuti.

### Le due ipotesi sbagliate

| ipotesi | come e' caduta |
|---|---|
| generazione degenere: il modello ripete e non chiude l'array | l'uscita parziale ha 95 oggetti di cui **82 distinti**. Non ripete. |
| i record sono troppo lunghi | **13 record riusciti** hanno un prompt piu' lungo del piu' corto dei due falliti, e il piu' lungo fra i riusciti (20 189 caratteri) e' quasi il doppio del peggior fallito (10 862). I sei record col ciclo degenere stanno fra 4 902 e 9 445, cioe' intorno alla mediana. Fallimento e lunghezza sono **scorrelati**. |

### Primo difetto: la risposta finisce nel canale del ragionamento

Con `think: "low"`, dopo cinque minuti la sonda aveva ricevuto **8 603 caratteri
di ragionamento e zero di uscita**. Ma quel "ragionamento" non e' ragionamento:

```
{ "condizioni": [ { "testo_grezzo": "Obesita si", "concetto": "obesita", "campo": ...
```

E' **la risposta**, conforme allo schema. Il modello apre il blocco di
ragionamento, ci scrive dentro la risposta e non lo chiude mai, quindi la
richiesta non si conclude e trenta minuti dopo scatta il timeout.

Il corollario e' piu' grave del sintomo: **la decodifica vincolata dallo schema
governa il canale della risposta, non quello del ragionamento**. Dentro il blocco
di ragionamento il modello e' libero, e la garanzia strutturale su cui poggia
tutta la pipeline B li' non vale.

E non riguarda solo i due record falliti. Sui 198 riusciti la corsa ha misurato
**2 177 token in uscita per record** contro circa **1 106 stimati di JSON utile**:
grosso modo meta' dei token in uscita non e' finita nel risultato, coerente con
un modello che scrive la risposta due volte. Disattivare il ragionamento
**dovrebbe quasi dimezzare** il tempo della corsa, da ~15 ore a ~8.

### Secondo difetto: la sovra-estrazione sulle anamnesi narrative

Con `think: false` il canale si sistema — 0 caratteri di ragionamento, uscita
dove deve stare — ma **il record non finisce lo stesso**: dopo dieci minuti sono
16 236 caratteri, 95 oggetti, e sta ancora scrivendo.

Non ripete: sovra-estrae. Guardando cosa estrae si capisce perche':

```
"testo_grezzo": "con lenta risoluzione"        -> concetto "risoluzione lenta"
"testo_grezzo": "Dimessa con flusso di ossigeno incrementato ad 1 L/min"
                                                -> concetto "ossigeno incrementato"
```

Non sono condizioni cliniche: sono **frammenti di narrazione**. Su un'anamnesi
lunga e discorsiva il modello trasforma quasi ogni proposizione in una
"condizione", e l'uscita cresce senza un limite naturale. La mediana dei record
riusciti e' 25 condizioni; qui siamo a 95 e la generazione non e' finita.

### Le tre correzioni, e perche' vanno insieme

1. **`think: false`** invece di `"low"`, che rimette la risposta nel canale
   vincolato dallo schema e dimezza il costo.
2. **`maxItems` sugli array dello schema.** E' il rimedio strutturale al secondo
   difetto: non un'istruzione che il modello puo' ignorare, ma un vincolo che il
   decodificatore stesso applica, costringendo l'array a chiudersi. Un tetto
   generoso — sessanta elementi contro una mediana di venticinque — lascia
   intatti i record sani e limita per costruzione la durata dei patologici.
3. **Il prompt**, perche' `con lenta risoluzione` non deve essere estratto
   affatto: va detto che una condizione clinica non e' un frammento di frase.

Tutte e tre cambiano l'impronta della configurazione, e devono quindi andare
**nella stessa corsa**. Il registro rifiutera' giustamente di mescolarle con i
198 record attuali: quei due record restano mancanti, e il totale della corsa
resta 198 su 200.

---

## 8. Limiti noti

* **La quota gratuita è il vincolo dominante**: 20 richieste al giorno per
  modello rendono impraticabile una corsa sull'intero dataset senza attivare la
  fatturazione. È una decisione aperta, non una scelta già presa.
* **Il collegamento ICD è a corrispondenza esatta.** Il 72% delle condizioni
  resta `NIL` non perché il concetto sia sbagliato ma perché il lessico clinico e
  quello del volume ICD divergono. Caso emblematico: «fibrillazione atriale» non
  esiste come termine indicizzato — il volume ha solo le forme qualificate
  (`parossistica` I48.0, `persistente` I48.1, `cronica` I48.2) e la categoria
  `I48`. È il problema di *entity linking* che lo step 5 deve affrontare, e qui è
  volutamente lasciato aperto invece di essere tappato con una regola inventata.
* ~~**Il modello riceve una regola che la pipeline A non ha**: non attribuire al
  paziente ciò che il referto riferisce a un familiare.~~ **Risolto** dall'asse
  `soggetto` (§ 7quater): la familiarità ora si calcola con la stessa regola in
  tutte e tre le pipeline, e l'asimmetria che avrebbe falsato lo step 6 non c'è
  più.
* **Un solo campione, piccolo.** Quattordici record dicono che la pipeline
  funziona; non dicono quanto sia brava. Ogni numero qui va riletto sulla corsa
  definitiva.
* **La generazione degenere non e' sotto controllo** (§ 7sexies): il 15,8% delle
  condizioni sono duplicati, concentrati in sei record su 198. Serve un
  `repeat_penalty` e un tetto agli elementi dell'array nella prossima corsa.
* **Le allergie sono il punto piu' fragile** (§ 7septies): il 25,9% viene da
  referti che di allergie non parlano, e in un caso sono i farmaci che il
  paziente assume. Finche' non e' corretto, l'uscita allergie della pipeline B
  non e' utilizzabile dal filtro di sicurezza dello step 8.
* **Nessuna verifica di correttezza clinica.** L'assenza di allucinazioni è
  provata solo nel senso letterale: le citazioni esistono nel testo. Che
  l'interpretazione dello stato sia giusta lo dirà il confronto dello step 6.

---

## 9. Componenti creati

| File | Ruolo |
|---|---|
| `src/llm_backend.py` | interfaccia astratta, backend Gemini con cache e ritentativi, backend fittizio per i test |
| `src/risolutori.py` | `RisolutoreATC` e `RisolutoreICD` condivisi fra le pipeline (estratti da `extract_a.py`) |
| `src/extract_b.py` | prompt, orchestrazione concorrente, conversione in `StatoPaziente` |
| `schema.py` → `EstrazioneLLM` | schema di uscita del modello e sua traduzione in JSON Schema |
| `tests/test_pipeline_b.py` | 38 test, tutti senza rete e senza chiave |

I test girano con un backend fittizio: una suite che dipendesse dall'API sarebbe
lenta, costosa e verde o rossa a seconda del carico dei server, quindi inutile
come rete di sicurezza. Ciò che verificano non è la bravura del modello, che non
è deterministica, ma il contratto che gli sta intorno — che una citazione
inventata sia riconosciuta, che il codice non provenga mai dal modello, che la
cache non restituisca la risposta di una domanda diversa, e che una quota
giornaliera esaurita non venga ritentata.

### Comandi

```bash
python3 -m spacy download it_core_news_sm      # se non già fatto
echo 'GEMINI_API_KEY=...' > .env.local
python3 src/extract_b.py --record 25 --parallele 8
python3 src/extract_b.py --modello gemini-3-flash-preview   # altro modello
```
