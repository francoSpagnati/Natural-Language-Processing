# Step 4 — Pipeline B: estrazione con un modello linguistico

Seconda delle tre pipeline di estrazione. Dove la pipeline A riconosce solo ciò
che è già nei vocabolari chiusi, questa legge il referto come lo leggerebbe una
persona: trova le menzioni, ne interpreta il contesto e scioglie le
abbreviazioni. È la pipeline con cui si misura quanto costa, in copertura, la
scelta deterministica dello step 3.

---

## 1. Il fornitore: Google AI Studio, non Anthropic

Il progetto usa **Gemini via Google AI Studio**. La ragione è economica e non
tecnica: le API Anthropic si pagano a consumo e non rientrano nel piano a
disposizione, mentre AI Studio offre una quota utilizzabile.

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

## 5. Risultati misurati

Su **14 record** (quanti la quota gratuita ha consentito), 552 entità estratte.

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

## 6. Limiti noti

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
* **Il modello riceve una regola che la pipeline A non ha**: non attribuire al
  paziente ciò che il referto riferisce a un familiare. È clinicamente corretto,
  ma introduce un'asimmetria di cui lo step 6 deve tenere conto.
* **Un solo campione, piccolo.** Quattordici record dicono che la pipeline
  funziona; non dicono quanto sia brava. Ogni numero qui va riletto sulla corsa
  definitiva.
* **Nessuna verifica di correttezza clinica.** L'assenza di allucinazioni è
  provata solo nel senso letterale: le citazioni esistono nel testo. Che
  l'interpretazione dello stato sia giusta lo dirà il confronto dello step 6.

---

## 7. Componenti creati

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
