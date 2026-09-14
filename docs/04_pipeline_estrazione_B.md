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
Familiarita per cardiopatia ischemica ed ipotiroidismo Ex fumatore, poche sigarette al giorno
```

Senza un terminatore, `Ex fumatore` diventerebbe un'abitudine del padre. La
maiuscola pero' deve essere seguita da una minuscola, altrimenti l'ambito si
spezzerebbe su ogni acronimo — `CAD`, `IMA`, `MCV`, `HCM` sono ovunque. E il
taglio non si applica dentro una parentesi, perche' le precisazioni sui parenti
ne sono piene: `ipotiroidismo (padre, in cura per Parkinson, madre ETP)`.

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
volte cita lui stesso: *«Si ricovera per dispnea in sospetto scompenso
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
* *«episodi di cardiopalmo pregressi **dubbi** per tachicardia»* — la
  lista ha `dubbio` e `dubbia`, non `dubbi`.
* *«BPCO stadio GOLD **non** noto, artrite gottosa della mano destra»* —
  il `non` appartiene a `non noto`, ma l'ambito di A scavalca la virgola e nega
  anche l'artrite. E' il prezzo diretto della scelta di **non** far chiudere
  l'ambito dalla virgola, presa perche' gli elenchi negati sono la norma
  (*«nega diabete, ipertensione e dislipidemia»*). Il modello, che legge la
  frase invece di contare i token, qui non si sbaglia.
* *«terapia con sacubitril/valsartan, **non** tollerata per ipotensione
  sintomatica»* — il `non` e' di `non tollerata`; il paziente l'ipotensione ce
  l'ha davvero.
* *«Si ricovera **nel sospetto di** ipertensione polmonare su base autoimmune»*
  — il sospetto riguarda l'ipertensione polmonare, l'artrite il paziente ce l'ha.

Il quadro e' quindi: **la regola deterministica sbaglia in modo sistematico e
prevedibile** (marcatori che non ha, ambiti che scavalcano), **il modello sbaglia
in modo sparso e sorprendente** (ignora marcatori espliciti). Sono due profili di
errore diversi, ed e' esattamente il tipo di complementarita' che lo step 6 deve
quantificare.

**Il caso che nessuna delle due prende:** *«ricoverata per FA tachifrequente con
sospetto di embolia polmonare, poi escluso»*. L'embolia e' stata
**esclusa**; A dice `incerto`, B dice `affermato`, e la risposta giusta e'
`negato`. La parentesi che rovescia l'affermazione e' fuori dalla portata di
entrambe.

**Un limite dell'asse nuovo, trovato negli stessi 33 casi:** *«secondo figlio
deceduto in eta' neonatale per sospetta cardiopatia congenita»* resta marcato
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
(`Trimetoprim/sulfametoxazolo, poi Amoxicillina`) ma
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

## 7octies. Perche' due record non si estraggono, e una diagnosi che ho dovuto ritirare

Il rilancio della corsa ha ripreso correttamente i due record mancanti e li ha
persi di nuovo: **tre ore, sei tentativi da trenta minuti, zero record**. La
temperatura e' 0 — stesso modello, stesso testo, stesso prompt, stesso esito.
Rilanciare identico non era una scommessa ragionevole, e il registro non poteva
saperlo: la ripresa sa quali record mancano, non perche' manchino.

Per capirne la causa serviva vedere l'uscita **mentre si forma**, non aspettare
trenta minuti per un errore. Una sonda che chiama ollama in streaming l'ha data
in quattro minuti.

### Una diagnosi sbagliata, e come e' caduta

La prima sonda sembrava aver trovato qualcosa di grosso: con `think: "low"` il
modello scriveva la risposta JSON **dentro il blocco di ragionamento** senza mai
chiuderlo, e la richiesta non si concludeva. Sembrava spiegare tutto, compreso il
costo della corsa.

Era un artefatto della sonda. `BackendOllama` ha `ragionamento: bool = False` e
`extract_b` lo costruisce passando **solo il modello**: la corsa vera girava gia'
senza ragionamento, ed ero io ad averlo acceso nella sonda. La prova definitiva
sta nella cache: **su tutte e 222 le risposte salvate, `token_ragionamento` e'
zero**.

Con lo stesso errore era caduta anche la stima secondo cui meta' dei token in
uscita andasse sprecata. Misurata sulle risposte vere, la produzione e' di
**2,42 caratteri di JSON per token in uscita**, che per un JSON fitto di
punteggiatura e' del tutto normale: **tutti** i token generati sono finiti nel
risultato. Il calcolo precedente confrontava i token misurati con una mia stima
grossolana della dimensione del JSON, e la stima era sbagliata, non il modello.

La lezione e' che una sonda deve riprodurre la configurazione della corsa, non
una configurazione plausibile; e che i dati gia' in cache valevano piu' di
qualunque sonda nuova.

### Un difetto vero, trovato per la stessa strada

Il flag `--ragionamento` **non raggiunge il motore locale**. Alimenta
`Richiesta.livello_ragionamento`, che serve a Gemini; `BackendOllama._corpo` usa
invece `self.ragionamento`, che nessuno imposta. Il registro dei 198 record dice
quindi `"ragionamento": "low"` mentre la corsa e' avvenuta **senza**
ragionamento: l'impronta della configurazione registrava l'intenzione della riga
di comando invece di cio' che ha davvero raggiunto il modello, ed e' esattamente
il tipo di scarto che l'impronta esiste per impedire.

### La causa vera: la lunghezza dell'uscita

Con la sonda configurata come la corsa (`think: false`) il record `10190890`
produce **16 236 caratteri in dieci minuti e non ha finito**. Non ripete — 95
oggetti di cui **82 distinti** — sovra-estrae. Basta guardare cosa:

```
"testo_grezzo": "con lenta risoluzione"        -> concetto "risoluzione lenta"
"testo_grezzo": "dimesso con ossigenoterapia a basso flusso"
                                                -> concetto "ossigenoterapia"
```

Non sono condizioni cliniche, sono **frammenti di narrazione**. Su un'anamnesi
lunga e discorsiva il modello trasforma quasi ogni proposizione in una
"condizione", e l'uscita cresce senza un limite naturale.

I numeri della cache chiudono il caso:

| | token in uscita |
|---|---|
| mediana | 1 812 |
| 95° percentile | 5 241 |
| **massimo riuscito** | **9 762** = 19,8 minuti di generazione a 8,2 token/s |
| tetto pratico imposto dal timeout di 1 800 s | ~14 800 |

La risposta piu' lunga andata a buon fine ha occupato venti dei trenta minuti
disponibili. I due record falliti chiedevano piu' del tetto. E la correlazione
fra token in ingresso e token in uscita e' **r = 0,52**: la lunghezza del referto
influenza quella della risposta ma non la determina, ed e' per questo che i
fallimenti non si spiegano guardando solo il prompt.

### Le correzioni

1. **`maxItems` sugli array dello schema.** E' il rimedio strutturale: non
   un'istruzione che il modello puo' ignorare, ma un vincolo che il
   decodificatore stesso applica, costringendo l'array a chiudersi. Un tetto
   generoso — sessanta elementi contro una mediana di venticinque — lascia
   intatti i record sani e limita per costruzione la durata dei patologici.
2. **Il prompt**, perche' `con lenta risoluzione` non deve essere estratto
   affatto: va detto che una condizione non e' un frammento di frase.
3. **Il flag `--ragionamento` va collegato al motore locale**, o l'impronta
   continuera' a registrare un valore che non corrisponde alla corsa.

Le prime due cambiano l'impronta della configurazione e devono andare **nella
stessa corsa**. Il registro rifiutera' giustamente di mescolarle con i 198
record attuali: quei due record restano mancanti, e il totale resta **198 su
200**.

Cade invece la previsione che disattivare il ragionamento dimezzasse la corsa:
era gia' disattivato, e le quindici ore sono il costo reale di `qwen3:4b` su
questa macchina.

---

## 7nonies. La seconda corsa: sette bersagli su otto, e un esempio che il modello copiava

Le correzioni dello step precedente avevano quattro bersagli dichiarati **prima**
di rilanciare, ciascuno misurabile. `src/rianalizza.py` affianca le due corse e
segna riga per riga l'esito, così il giudizio non viene deciso a posteriori
guardando i numeri che sono usciti meglio.

| | prima (198 rec) | dopo (199 rec) | esito |
|---|---|---|---|
| condizioni per record | 25,3 | 24,3 | migliorato |
| duplicati fra le condizioni | 15,8% | 13,2% | migliorato |
| record oltre il tetto di 60 | 14 | **0** | migliorato |
| farmaci dalla dimissione | 376 | **756** | migliorato |
| allergie su referti che non le nominano | 65 | 58 | migliorato |
| menzioni non ancorate | 13,0% | **9,5%** | migliorato |
| allergie non ancorate | 44,2% | **65,2%** | **PEGGIORATO** |

Il `maxItems` ha eliminato del tutto i record oltre il tetto, e con essi i due
record che nella prima corsa non concludevano: **199 su 200, un solo fallimento
contro due**. La terapia di dimissione raddoppia. Le menzioni non ancorate
scendono di un quarto.

### L'unica riga peggiorata, e perché è la più istruttiva

Le allergie non ancorate salgono dal 44,2% al 65,2%. Guardando che cosa sono:

```
105 su 131   testo_originale = 'mdc'
```

`mdc` non compare in quei referti. Compariva nel **prompt**, nell'esempio
positivo della REGOLA 9:

```
GIUSTO:  da "riferita allergia a mdc (eruzioni pomfoidi)",
         allergene "mdc", categoria "altro"
```

Il modello lo ha copiato 105 volte fra le allergie. E, cercando la stessa stringa
fra le condizioni, altre **45 volte la frase d'esempio per intero**. Centocinquanta
menzioni fabbricate da una riga sola del prompt.

Su **64 record il referto dice testualmente che le allergie non sono note**, e
**56 di quelli (88%) hanno comunque un'allergia estratta**. La regola scritta
tre righe sotto l'esempio dice «se il referto non nomina allergie, lascia la
lista vuota». Non è servita.

### Che cosa distingue un esempio che trapela da uno che non trapela

Due controlli, che portano a una regola pratica:

* **L'esempio `SBAGLIATO:` accanto non è mai trapelato.** Zero occorrenze di
  «Bisoprololo» fra le allergie estratte. Un esempio negativo insegna un
  confine; uno positivo offre un modello da ricopiare, e il divieto scritto
  sotto non lo neutralizza.
* **Gli esempi delle regole sulle condizioni trapelano molto meno** — 21 casi su
  367 condizioni non ancorate, contro 105 su 131 per le allergie. La differenza
  non è nel prompt ma nei dati: una condizione da citare il referto ce l'ha quasi
  sempre, un'allergia quasi mai. **Quando il modello non trova materiale nel
  testo, prende quello che gli è stato messo davanti.**

Che è, in fondo, il senso della REGOLA 8: un modello non lascia volentieri un
campo vuoto. Se non gli si toglie l'alternativa, la riempie.

### Il difetto è stato trovato dall'ancoraggio, non dal sospetto

Nessuno cercava questo errore. Le 105 menzioni `mdc` sono clinicamente
plausibili — l'allergia al mezzo di contrasto è comune in cardiologia, e in un
riepilogo per il clinico non avrebbero fatto alzare un sopracciglio. Sono state
trovate perché **non esistono alla lettera nel referto**, e il confronto verbatim
non ha opinioni sulla plausibilità.

È la terza volta in questo progetto che quel meccanismo trova qualcosa che
nessuna revisione a vista avrebbe trovato, e la seconda volta che quel qualcosa
è un difetto del prompt e non del modello.

### La correzione

Tolto l'esempio positivo. Tolto anche l'elenco «mezzo di contrasto, ASA,
statine», che pur essendo formulato come divieto piantava lo stesso prior.
Aggiunto invece il caso che il modello sbaglia davvero: la parola *allergia*
presente ma seguita da una negazione.

`impronta_istruzioni` passa da `1bb13e603612a1e3` a `5bd4c6615085c6f5`, così la
prossima corsa non si mescola con questa.

**La sovra-estrazione resta non risolta.** 24,3 condizioni per record contro le
5,4 della pipeline A: il miglioramento è di un punto, non di un ordine di
grandezza, e non ho una leva validata. Né il prompt né un vincolo di lunghezza
separano il segnale dalla narrazione — vedi § 7sexies, dove `maxLength` è stato
misurato e scartato **prima** di applicarlo su quattordici ore di corsa.

---

## 7decies. Un terzo backend, e il campo che lo rende sicuro

Il collo di bottiglia della pipeline B non è mai stato il denaro: **235 secondi
per record** significano 65 ore per il corpus intero, e per questo ogni misura di
questo documento è su 200 record e non su 1 000.

Misurando i token veri delle 425 risposte in cache — 2 747 in ingresso e 2 145 in
uscita per record, di cui 1 963 di istruzioni fisse e quindi cacheabili — l'intero
corpus su un modello a consumo costa **poco più di un dollaro**. È una
sproporzione che rendeva la scelta obbligata.

`BackendOpenRouter` sta dietro la stessa interfaccia e la stessa cache degli altri
due, quindi lo step 6 può confrontare modelli diversi a parità di prompt senza che
il resto della pipeline se ne accorga.

### Il campo che conta più del prezzo

```python
"provider": {"require_parameters": True}
```

OpenRouter instrada la stessa richiesta a fornitori diversi, e **non tutti
applicano `response_format`**. Un fornitore che lo ignora non restituisce un
errore: restituisce un JSON plausibile, generato senza vincolo. La pipeline lo
accetterebbe, i test resterebbero verdi, e la garanzia strutturale su cui è
costruita la pipeline B — *la validità sintattica è garantita dal decodificatore,
non sperata dal prompt* — diventerebbe una speranza, in silenzio.

`require_parameters` impedisce l'instradamento verso chi non supporta i parametri
della richiesta. C'è un test apposta, ed è il più importante del gruppo.

### Due scelte spiegate

**`schema_stretto()` non toglie `maxItems`.** La modalità strict pretende
`additionalProperties: false` su ogni oggetto, e quello viene aggiunto. Ma
`maxItems` non è fra le parole chiave che il sottoinsieme strict garantisce, e il
tetto di 60 elementi è la correzione che ha eliminato i timeout. Toglierlo in
silenzio perderebbe la protezione senza dirlo; lasciarlo fa emergere il problema
come errore esplicito alla prima richiesta, dove si vede. **Da verificare nel
pre-volo**, non da dare per buono.

**Il ragionamento è spento**, e non per il costo: su più modelli è documentato che
con `response_format` attivo il vincolo dello schema finisce applicato al canale
di ragionamento, lasciando `content` vuoto. È lo stesso sintomo che in § 7octies
ho attribuito per errore al modello locale — lì non c'era, ma su questi endpoint
esiste davvero.

### Provenienza della forma della richiesta

Verificata sulla documentazione, non dedotta: `response_format` e
`provider.require_parameters` da <https://openrouter.ai/docs/features/structured-outputs>,
il campo `reasoning` da <https://openrouter.ai/docs/use-cases/reasoning-tokens>.
I parametri che ciascun modello dichiara di supportare sono interrogabili su
<https://openrouter.ai/api/v1/models>, campo `supported_parameters`: è così che
si è scelto `deepseek/deepseek-v4.1-flash`, che dichiara `structured_outputs`,
invece di `qwen/qwen3.7-flash`, che su quell'instradamento **non lo dichiara**
pur supportandolo sull'API nativa di Alibaba.

La risposta porta ora anche il **costo dichiarato dal fornitore**, messo in cache
insieme al resto, per non doverlo ristimare dai token con un listino che nel
frattempo può essere cambiato.

---

## 7undecies. La corsa sul corpus intero, e cosa se ne impara

**1 000 record su 1 000, zero falliti, 39 minuti, 2,42 $.** È la prima corsa
completa del progetto: fino a qui ogni misura era su 200 record, perché 235
secondi per record in locale significano 65 ore per il corpus.

| | B-locale (`qwen3:4b`) | B-remota (`deepseek-v4.1-flash`) |
|---|---|---|
| record | 199 su 200 | **1 000 su 1 000** |
| tempo | 13 h | 39 min |
| costo | 0 € | 2,42 $ |
| menzioni non ancorate | 9,5% | **0,5%** |

### Che cosa è del modello e che cosa del prompt

Fra le due corse è cambiato **anche** il prompt: la REGOLA 9 sulle allergie è
stata riscritta (§ 7nonies). Attribuire tutto al modello sarebbe scorretto, e la
separazione si può fare con precisione perché quella riscrittura tocca **solo le
allergie**: le regole su condizioni e farmaci sono identiche parola per parola.

Sugli stessi 199 record, dove il prompt non è cambiato:

| misura | B-locale | B-remota |
|---|---|---|
| condizioni per record | 24,3 | **17,2** |
| duplicati fra le condizioni | 13,2% | **0,3%** |
| menzioni non ancorate (escluse allergie) | 7,9% | **0,5%** |
| farmaci dalla terapia di dimissione | 756 | **1 386** |
| farmaci elencati come condizioni | 44 | **0** |

Il difetto del § 7sexies — la **generazione degenere**, 555 duplicati da
rimuovere — praticamente scompare. Non è stato risolto da una correzione: è
sparito cambiando modello, il che dice che era una proprietà di quel modello e
non del compito.

Sulle allergie invece **non si può attribuire niente**: le 105 menzioni `mdc`
erano attese sparire per costruzione, avendo tolto l'esempio dal prompt.

### Il prezzo che si paga

I farmaci che B trova **nella prosa** crollano da 42 a 61 su mille record, contro
i 2 332 della pipeline A. Il modello remoto si concentra sui campi di terapia,
dove arriva al 99,6%, e nell'anamnesi quasi non segnala farmaci. I farmaci
narrati — *«sospesa terapia con rivaroxaban»* — sono clinicamente informativi
proprio perché non stanno nei campi strutturati, e ora si perdono.

### Due record falliti, e un difetto del backend

Sulla corsa da 200 due record erano falliti: uno con JSON troncato a metà di una
stringa, uno con `finish_reason=error`. **Rilanciandoli sono riusciti entrambi al
primo colpo**, il che li qualifica come guasti transitori del fornitore.

Il difetto era mio: `_interpreta` veniva chiamato nel ramo `else` del ciclo, cioè
fuori dalla portata dell'`except`, quindi un errore sollevato lì usciva dai
ritentativi. Con `response_format` attivo un JSON malformato **non può** venire
da un errore del modello — viene da una generazione interrotta — ed era proprio
il caso da ritentare. Introdotta `ErroreRitentabile`, con i test presi dai due
casi veri.

La conferma è arrivata subito: sulla corsa da mille record, **4 record recuperati
dai ritentativi e zero falliti**. Senza la correzione sarebbero stati quattro
fallimenti da rilanciare a mano.

### La cache si è ripagata

Dopo la correzione dell'asse experiencer tutte e tre le pipeline sono state
rieseguite per propagare il nuovo soggetto. La pipeline B è costata **zero**:
1 000 record su 1 000 serviti dalla cache delle risposte, in meno di un minuto.
È la ragione per cui quella cache esiste, scritta allo step 4 prima di sapere che
sarebbe servita a questo.

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
| `tests/test_pipeline_b.py` | 76 test, tutti senza rete e senza chiave |

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

# tre motori dietro la stessa interfaccia e la stessa cache
python3 src/extract_b.py --motore locale --modello qwen3:4b --record 200
python3 src/extract_b.py --motore gemini --record 20 --parallele 8
python3 src/extract_b.py --motore openrouter --record 200 --parallele 8

# le chiavi stanno in .env.local, che git ignora
echo 'GEMINI_API_KEY=...'     >> .env.local
echo 'OPENROUTER_API_KEY=...' >> .env.local
chmod 600 .env.local

# dopo una corsa nuova: rimisura tutto e affianca la corsa precedente
python3 src/rianalizza.py
python3 src/confronto.py
```

---

## §7duodecies — Il modello non legge più i campi di terapia

Fino a questa versione la pipeline B mandava al modello tutte e tre le sezioni
del referto. Era sbagliato, e la domanda che l'ha smontato è stata posta in
forma semplice: *i farmaci vanno presi dai campi di terapia, che sono
strutturati e più affidabili; l'anamnesi serve ad altro.*

### Perché era sbagliato, misurato

I due campi di terapia sono liste con delimitatori — `;` all'ingresso, voci fra
virgolette alla dimissione. Questo li rende **una verità esatta e gratuita**: si
contano le voci senza annotare nulla, su tutti e 1 000 i referti, senza
inferenza e senza costo.

Il progetto aveva annotato a mano 25 referti per misurare il richiamo sulle
condizioni e non si era accorto che per i farmaci di terapia la verità era già
nei dati. Confrontati su quella verità, sui 25 referti del riferimento:

| terapia d'ingresso | VP | FP | FN | precisione | richiamo |
|---|---|---|---|---|---|
| **parser deterministico** (già in A e C) | 133 | 0 | 0 | **100,0%** | **100,0%** |
| modello linguistico (a pagamento) | 133 | 1 | 0 | 99,3% | 100,0% |

| terapia alla dimissione | VP | FP | FN | precisione | richiamo |
|---|---|---|---|---|---|
| **parser deterministico** | 150 | 0 | 2 | **100,0%** | 98,7% |
| modello linguistico | 152 | 1 | 0 | 99,3% | 100,0% |

Il modello pagava per fare **peggio di un parser gratuito** su un campo già
risolto. E quei due campi erano il **28,6% del testo inviato** e il **42,4%
delle voci prodotte**: circa un terzo del costo di una corsa, speso per rifare
peggio un lavoro già fatto.

C'era anche un danno che non si vedeva nei totali: il modello talvolta emetteva
**una voce per somministrazione** invece che per farmaco. `Isoptin: 250 mg
(ore 20) 240 mg (ore 8)` è **un** farmaco con due dosi, e diventava due. Il
parser non ha questo problema perché non interpreta: conta i delimitatori.

### Il disegno, campo per campo

| campo | contenuto | metodo | perché |
|---|---|---|---|
| Terapia all'ingresso | lista `Nome: posologia ;` | parser deterministico | ha delimitatori: non serve riconoscere, serve dividere |
| Terapia alla dimissione | lista `"Principio (commerciale): posologia"` | parser deterministico | come sopra |
| Anamnesi — condizioni | prosa | modello linguistico | richiamo 70% contro il 20% di gazetteer e NER |
| Anamnesi — allergie | prosa | modello linguistico | nessuna lista le contiene |
| Anamnesi — familiarità | prosa | ConText + modello | serve l'asse dell'experiencer |
| Anamnesi — farmaci | prosa | modello linguistico | **solo quelli con un fatto**: § successivo |

**Il principio: a ogni campo il metodo più semplice che lo risolve.** Un campo
con delimitatori si legge con un parser; il testo libero richiede
riconoscimento. Mandare un modello linguistico su un campo strutturato non
aggiunge capacità — aggiunge costo e una sorgente di errore dove non ce n'era.

I farmaci di terapia entrano ora dallo stesso `farmaci_da_campo_strutturato` che
usano A e C. Il progetto ha **una sola lettura** dei due campi invece di tre che
potevano divergere, e il confronto dello step 6 misura la differenza di
estrazione *dalla prosa*, che è l'unica su cui le tre pipeline si distinguono.

### Il parser, migliorato prima di affidargli tutto

Prendendosi l'intera responsabilità dei due campi, il parser andava portato a
posto. Tre correzioni, ciascuna con il suo test:

| correzione | recupera | perché falliva |
|---|---|---|
| parentesi annidata nel commerciale | 12 voci | un farmaco estero porta la provenienza fra parentesi dentro la descrizione, e `[^()]*` non la attraversa |
| nome seguito dalla dose, senza commerciale | 40 voci | `Rosuvastatina 5 mg (ore 22)`: nessun `:` fra nome e posologia |
| forma farmaceutica in coda al nome | 2 voci | `Spironolattone cps` veniva respinto dalla guardia |

| copertura | prima | dopo |
|---|---|---|
| terapia d'ingresso | 98,02% | **98,77%** |
| terapia alla dimissione | 99,3% | **99,97%** |

Sulla terza correzione vale la pena essere espliciti: la guardia
`nome_farmaco_plausibile` rifiuta un nome che contiene una forma farmaceutica,
perché è il segnale che la posologia non è stata separata. **Non l'ho
indebolita**: le si ripresenta un nome ripulito. Indebolire una guardia per far
passare un caso è il modo in cui un vocabolario chiuso si degrada.

### Una regola nuova che stava facendo danno, fermata da un test

La regola «il nome è ciò che precede la prima cifra» sembrava innocua. Su un
blocco scritto a mano dal clinico — quattro farmaci in un unico segmento,
separati da virgole — ne estraeva **uno** e perdeva gli altri tre in silenzio.
Un test che asseriva il vecchio comportamento (scartare il blocco intero) ha
fermato la modifica.

Dichiarare uno scarto è meglio che estrarre una parte e dare l'illusione della
copertura. La regola ora non si applica se la voce contiene virgole.

### REGOLA 7 riscritta: il fatto, non il nome

La versione precedente chiedeva **tutti** i farmaci nominati nella prosa, e
portava il richiamo da 0% a 83%. Ma la domanda giusta non era quella. Misurando
a che cosa servono quelle menzioni, sui 56 farmaci del riferimento:

| contesto | menzioni | |
|---|---|---|
| sospensione o riduzione | 12 | 21% |
| intolleranza o allergia | 3 | 5% |
| evento avverso | 3 | 5% |
| rifiuto o mancata assunzione | 1 | 2% |
| **con marcatore di sicurezza** | **19** | **34%** |
| nessun marcatore | 31 | 55% |

Due terzi sono racconto. Un terzo porta informazione che i campi strutturati
**non possono** contenere per definizione — un farmaco sospeso per emorragia è
una controindicazione, e nella terapia d'ingresso non c'è perché quella elenca
ciò che il paziente assume *ora*.

La regola chiede quindi i farmaci a cui l'anamnesi attribuisce un **fatto**:
sospensione, riduzione, intolleranza, evento avverso, rifiuto, assunzione
passata. E dice esplicitamente che **la lista vuota è la risposta giusta** nel
caso più frequente.

Applicando la lezione di `mdc`, la regola non contiene esempi positivi con
sostanze vere: solo casi `SBAGLIATO`, che in quella vicenda non hanno mai perso
contenuto nell'uscita.

### Il campo di una menzione del modello è fissato, non dichiarato

Al modello arriva solo l'anamnesi, quindi ogni sua citazione viene da lì. Lo
schema ammette ancora i tre valori — è condiviso con le altre pipeline — e se il
modello ne scegliesse un altro la citazione verrebbe cercata nel campo
sbagliato, **dove potrebbe perfino trovarsi per caso** e produrre un ancoraggio
falso. `campo_del_modello` lo fissa ad `Anamnesi`: rende quell'errore
impossibile invece che improbabile.

### Validazione prima di spendere

La corsa doveva essere l'ultima a pagamento, quindi è stata validata su 25
referti (0,046 dollari) prima di lanciare il corpus. La cache è indicizzata su
`(modello, istruzioni, testo, schema)`, quindi quei 25 sono stati riusati dalla
corsa intera senza ripagarli: la validazione è costata zero in più.

| | risultato |
|---|---|
| record completati | 25/25, nessun fallimento |
| terapia d'ingresso | 136 dal parser, 136 nell'uscita — **0 record disallineati** |
| terapia alla dimissione | 153 dal parser, 153 nell'uscita |
| provenienza dei farmaci di terapia | tutti `campo_strutturato` |
| condizioni, richiamo | 68,7% (le tre corse precedenti: 70,1 / 68,2 / 70,1) |
| farmaci in prosa | precisione 95,3%, richiamo 68,3% |
| token in uscita per record | **934**, erano 2 145 (−56%) |

Il richiamo sulle condizioni resta dentro il pavimento di rumore di due punti
misurato al § 8.6 di `06b`: la ristrutturazione non le ha toccate.

Sui farmaci il 68,3% **sottostima**, e la ragione è dichiarata: il riferimento
annota *ogni* farmaco nominato nella prosa, la regola nuova ne chiede di
proposito un sottoinsieme. Dei 19 mancati, **16 non hanno alcun marcatore di
evento** — la regola non li vuole. I mancati veri sono **3**, e i falsi positivi
**2**. Sul bersaglio che la regola si pone il richiamo è del 93%.

Resta però un disallineamento fra la regola e il riferimento, ed è onesto
lasciarlo scritto: per misurare questa regola come si deve servirebbe un
riferimento che annoti il *fatto* oltre al farmaco. Non è stato rifatto, perché
rifarlo dopo aver visto i risultati è esattamente il vizio che il § 7 di `06b`
descrive.


### La corsa finale, e un guasto che ha insegnato qualcosa

**1 000 record su 1 000, nessun fallimento, 1,652 dollari.**

| | prima | dopo |
|---|---|---|
| condizioni | 16 742 | 16 323 |
| farmaci di terapia | 12 392 | **11 919** (dal parser, esatti) |
| farmaci narrati nella prosa | 62 | **2 174** |
| token in uscita per record | 2 145 | **934** (−56%) |
| menzioni non ancorate | 0,3% | 0,3% |

I conteggi di terapia — 5 536 all'ingresso, 6 383 alla dimissione — coincidono
**esattamente** con quelli del parser. Non è un accordo misurato: è un'identità
per costruzione, perché la lettura di quei campi nel progetto è una sola.

#### Il guasto: `IncompleteRead` a 510 record su 1 000

Dopo 75 minuti la corsa è morta su una connessione chiusa a metà risposta. È il
guasto di rete più transitorio che esista, e usciva dal ciclo dei tentativi come
se fosse definitivo.

La ragione è una tassonomia: **`IncompleteRead` discende da
`http.client.HTTPException` e NON da `URLError`**, e il ciclo catturava
`URLError`, `TimeoutError` e `JSONDecodeError` — la famiglia sbagliata.

È la **seconda volta** che il progetto inciampa sulla stessa forma di problema.
La prima fu `ErroreRitentabile`, che gestiva i guasti *del modello* ma veniva
invocato fuori dal `try` e quindi non veniva mai ritentato. Questo è lo stesso
difetto un livello più in basso, sui guasti *della rete*. La lezione comune: un
meccanismo di ritentativo va provato **facendo fallire davvero** la cosa che
dovrebbe assorbire, non guardandolo nel codice.

Ora esiste `ERRORI_DI_RETE`, applicato a tutti e tre i backend, con tre test di
regressione. Non cattura `OSError` intero, e c'è un test anche per quello: un
permesso negato è un difetto da vedere subito, non un guasto da assorbire.

Il danno reale è stato quasi nullo: il checkpoint aveva salvato 509 record e la
cache conteneva anche le risposte arrivate dopo, così alla ripresa **488 dei 491
record mancanti sono arrivati dalla cache** e solo 3 sono stati ripagati.

#### Un effetto collaterale che il «100%» ha rivelato

Il confronto dello step 6 dava «terapia ritrovata da B: 100,0%», che è il genere
di cifra da verificare invece che da festeggiare. Verificandola è saltato fuori
che **le pipeline A e C erano state prodotte prima delle correzioni al parser**,
e avevano quindi 66 voci in meno di B sugli stessi campi.

Le tre pipeline sarebbero sembrate in disaccordo sui campi strutturati per un
motivo che non ha nulla a che vedere con l'estrazione: una era semplicemente più
vecchia. A e C sono deterministiche e rifarle non costa nulla, quindi sono state
rifatte. È la ragione per cui un numero perfetto va guardato con lo stesso
sospetto di uno zero.
