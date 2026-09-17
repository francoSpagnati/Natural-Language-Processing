# Step 10 — Il server MCP, e la frontiera oltre lo strumento

**Stato:** completato.
**Riproducibilità:** `python3 src/mcp_client_locale.py --strumenti` (handshake), `python3 src/valuta_mcp.py` (le dieci domande, con ollama), `claude mcp add cardio -- python3 src/mcp_server.py`

Tutta la catena — estrazione, filtro, ranker, traccia — esposta a un modello
conversazionale via *Model Context Protocol*, con l'SDK Python ufficiale `mcp`.
Codice: [`src/mcp_server.py`](../src/mcp_server.py),
[`src/mcp_client_locale.py`](../src/mcp_client_locale.py),
[`src/valuta_mcp.py`](../src/valuta_mcp.py).

---

## 1. La domanda che decide il disegno

Non «quali strumenti esporre», ma **che cosa un modello non deve poter fare**.
Otto step hanno costruito garanzie — filtro contestabile riga per riga,
codici ancorati a fonti, provenienza con gli offset — e un modello che
potesse scrivere le butterebbe via.

**Sola lettura, dichiarata nel protocollo.** Ogni strumento porta
`read_only_hint=True`: la promessa è verificabile dal client, non affidata
alla mia parola. Lo step 9 ha già mostrato come si rompe una barriera: il
modello locale ha nominato 40 codici fuori elenco, 15 inesistenti. Qui il
modello **chiede**, il codice deterministico **risponde**.

**Il corpus non passa di qui.** Un client MCP può essere remoto: uno
strumento che leggesse un referto per `enc_oid` spedirebbe testo clinico
fuori dalla macchina. Gli strumenti lavorano sul testo che ricevono; del
corpus escono solo aggregati. La difesa è nella **firma** (nessun argomento
che indichi un ricovero), e un test la fissa.

## 2. I sei strumenti

| strumento | risponde a |
| --- | --- |
| `cardio_proponi_terapia` | «che cosa aggiungeresti alla dimissione?» — dal **testo** |
| `cardio_proponi_da_stato` | la stessa domanda — da uno **`StatoPaziente`** già codificato |
| `cardio_sostegno_del_concetto` | **«da dove viene questo fatto?»** — la catena in SPARQL |
| `cardio_verifica_sicurezza` | «questo farmaco si può dare a questo paziente?» |
| `cardio_cerca_codice` | «che cos'è `C03DA`?», «il codice dei sartani?» |
| `cardio_statistiche_corpus` | «quanto è affidabile quello che mi dici?» — solo aggregati |

**Due ingressi per la stessa proposta.** Il brief sez. 3.5 fissa la firma
`suggest_cardiac_therapy(patient_state)`: lo stato strutturato è l'unico
input del motore. `cardio_proponi_da_stato` è quella firma, con lo schema
JSON generato dall'SDK dal modello Pydantic `StatoPaziente`. Il tool a testo
esiste perché un modello conversazionale davanti a un'anamnesi non ha una
pipeline di estrazione: estrae con il motore deterministico e entra nello
stesso punto (`demo.analizza_stati`); un test verifica che i due percorsi
diano le stesse proposte. Entrambi dichiarano `ranker: ibrido`.

**Quando non sa, lo dice.** Un codice non estratto non restituisce una lista
vuota — «non significa che il fatto sia falso: significa che il sistema non
lo ha estratto» — perché un modello davanti a una lista vuota conclude «il
paziente non ha questa condizione». Ogni proposta dichiara il proprio
**fondamento** (`indicazione citata`, con la fonte, oppure `co-occorrenza
misurata nel corpus`, con un avvertimento in chiaro), e ogni risposta porta il
suo tetto: il 40,4% delle prescrizioni non è cardiologia, un'assenza non è
una controindicazione. `cardio_verifica_sicurezza` rifiuta tutto ciò che non
è un codice del registro AIFA, senza emettere verdetto; un allergene non
codificato è dichiarato fatto mancante.

## 3. Due client, quattro corse a mano

Claude Code (`claude mcp add`) e un **host locale** con `qwen3.5:4b` via
ollama: il modello riceve le descrizioni degli strumenti, decide, chiama,
legge, risponde. Il secondo chiude il cerchio — modello, server e dati sulla
stessa macchina — e ha trovato tre difetti che una prova a mano non vedeva.

| corsa | che cosa è successo | causa | correzione |
| --- | --- | --- | --- |
| 1 | chiama lo strumento giusto, poi scrive «betabloccante selettivo (A02BC)» e un «profilo nefroprotettivo» inventato | lo strumento aveva estratto **zero** condizioni («iperteso» non è nel gazetteer; terapia con virgole invece di `;` e dose) e restituito il tasso di base con `fonte: null`; il modello ha riempito il vuoto | `fondamento` per ogni proposta, `fatti_mancanti` con il rimedio, formato nella descrizione |
| 2 | domanda telegrafica: passa il testo intatto, risposta corretta | — | — |
| 3 | **«paziente iperteso» → «Ipotensione»**: il modello riscrive l'anamnesi prima di passarla; la catena di provenienza è formalmente corretta su un fatto invertito | il server non ha mai visto il messaggio dell'utente | istruzione: *chi* copia (il modello) e *da dove* (dal messaggio); controllo a valle nel client |
| 4 | dopo le correzioni: strumento giusto, testo intatto, prosa aderente | | |

È la quarta ricorrenza del principio del fatto mancante, la prima a questa
frontiera. E la lezione dell'intero step: **tutte le garanzie valgono fino al
confine dello strumento**; oltre c'è prosa generata, che può invertire un
fatto. Si possono ridurre i vuoti e dichiarare il limite, non garantirlo.

## 4. La valutazione: dieci domande scritte prima

Quattro corse non sono una misura. [`src/valuta_mcp.py`](../src/valuta_mcp.py)
ha dieci domande scritte **prima** di eseguirle, ciascuna con lo strumento
atteso: i cinque strumenti a testo, prosa e telegrafico, due casi di
sicurezza, una fuori ambito. Si conta strumento giusto al primo colpo, testo
passato intatto (`testo_fedele` nel client: il testo passato deve essere un
pezzo del messaggio dell'utente, normalizzati; se no, avviso al modello e
conteggio), risposta arrivata. Modello `qwen3.5:4b`, zero denaro, 9–226 s per
domanda.

| | corsa 1 | corsa 2 |
| --- | --- | --- |
| strumento giusto | 9/10 | 9/10 |
| testo intatto | 5/5 | 6/6 |
| risposta arrivata | 10/10 | 10/10 |
| parafrasi rilevate | 0 | 0 |

**Corsa 1** fallisce la domanda 1 con zero strumenti: il modello ha letto
«passa l'anamnesi ALLA LETTERA» come un obbligo dell'*utente* e gli ha chiesto
di riscrivere un testo che aveva già. L'istruzione contro la parafrasi ha
prodotto un errore diverso; riformulata nominando chi copia e da dove.

**Corsa 2** fallisce la domanda 2 nel modo che vale di più: il modello decide
da sé che cosa aggiungere e chiede al filtro se sia ammesso passando **i
nomi** (`farmaco_atc='Bisoprololo'`). Il filtro confronta codici, nessuna
regola incontra un nome, la risposta era «ammesso» **a vuoto** — per uno
strato di sicurezza l'errore peggiore. Ora rifiuta e rimanda a
`cardio_cerca_codice`; quinta ricorrenza del principio.

Nove su dieci in entrambe le corse, con errori **diversi**: la scelta dello
strumento è sensibile alla formulazione, non a un difetto fisso. Zero
parafrasi in undici passaggi con il controllo che le avrebbe contate: non è
la norma, e undici casi non dicono quanto sia rara.

## 5. Costo, e due trappole dell'SDK

Import del server 0,42 s; prima proposta 1,60 s (carica 1 002 JSON, addestra
l'ibrido), successiva sullo stesso testo 0 s (`lru_cache`); una SPARQL di
sostegno 0,70 s; un giro del modello locale 23–45 s. **L'orchestrazione costa
due ordini di grandezza più degli strumenti.**

Con `mcp` 2.x `FastMCP` è diventato `MCPServer` e `inputSchema` è diventato
`input_schema`: il client è fallito al primo giro sul secondo. La skill
ufficiale `mcp-builder` (in `.claude/skills/`, con provenienza dichiarata)
documenta ancora la 1.x e prevede la valutazione con l'API Anthropic, che qui
non si usa: la valutazione è fatta con il modello locale.

## 6. Che cosa resta aperto

* **La parafrasi è contata, non impedita.** Una difesa vera farebbe entrare il
  testo *senza passare dal modello* — un `resource` MCP che il client apre da
  file, con il modello che riceve solo l'identificatore. Un disegno diverso.
* **Dieci domande sono una misura piccola**: distinguono un difetto
  sistematico da uno occasionale, non stimano quanto sia raro. La lista è
  scritta per essere estesa a costo zero.
* **Il server non espone il corpus, per scelta.** Se servisse, la strada è un
  secondo server che accetti solo il client locale, non un parametro.
