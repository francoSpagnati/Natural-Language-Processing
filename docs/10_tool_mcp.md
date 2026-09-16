# Step 10 — Il tool MCP: il sistema diventa uno strumento per un altro agente

Fino allo step 9 il sistema si usa da riga di comando: chi lo interroga sa già
che cosa chiedere. Qui diventa uno **strumento che un modello conversazionale può
chiamare** — ed è il primo punto del progetto in cui un modello linguistico sta
*davanti* al sistema invece che dentro una pipeline.

Codice: [`src/mcp_server.py`](../src/mcp_server.py),
[`src/mcp_client_locale.py`](../src/mcp_client_locale.py).
Test: [`tests/test_mcp_server.py`](../tests/test_mcp_server.py).

---

## 1. La domanda che decide il disegno

Non è «quali strumenti esporre», è **che cosa un modello non deve poter fare.**

Il progetto ha passato otto step a costruire garanzie: il filtro simbolico che
può essere contestato da un clinico, i codici ancorati a knowledge base citate,
la provenienza con gli offset nel referto. Mettere un modello davanti a tutto
questo è il modo più rapido per buttarle via, se il modello può scrivere.

Quindi due vincoli, prima di scrivere una riga.

### Sola lettura, e dichiarata nel protocollo

Nessuno strumento scrive, addestra o decide. Tutti dichiarano
`read_only_hint=True`, che è la forma in cui MCP rende quella promessa
**verificabile dal lato del client** invece che affidata alla mia parola.

Non è prudenza generica: lo step 8 è simbolico *per vincolo* — «mai LLM, mai
dataset» — e un modello che potesse toccare le regole, il grafo o l'insieme
candidato scavalcherebbe l'unico strato che stabilisce che cosa è ammissibile.

Lo step 9 ha già mostrato come si rompe una barriera del genere. Vincolato
all'insieme candidato, il modello locale ha comunque nominato **40 codici fuori
elenco, 15 dei quali non esistono nel registro ATC dell'AIFA** — fra questi
`R05AA`…`R05AG`, sette suffissi consecutivi. Un codice che non esiste non può
essere né vietato né verificato. Qui la difesa ha la stessa forma: il modello
**chiede**, il codice deterministico **risponde**.

### Il corpus non passa di qui

Questo è il vincolo che mi ha sorpreso scrivendolo, ed è il più importante.

Un client MCP può essere remoto. **Claude Code manda il risultato di uno
strumento a un modello che gira altrove**: un tool che leggesse un referto per
`enc_oid` spedirebbe testo clinico fuori dalla macchina senza che nessuno se ne
accorga, e senza violare nessuna riga di `.gitignore`.

È la stessa regola del grafo dello step 7 — *il testo clinico non entra nelle
triple* — applicata a una frontiera nuova. Gli strumenti lavorano solo su testo
che l'utente incolla. Del corpus escono solo **aggregati**.

La difesa sta nella **firma**, non in un controllo a valle:

```python
def test_nessuno_strumento_accetta_un_identificativo_di_ricovero(self):
    vietati = {"enc_oid", "record", "referto", "paziente_id", "id_ricovero"}
    for s in strumenti():
        argomenti = set(s.input_schema.get("properties", {}))
        self.assertEqual(argomenti & vietati, set())
```

Se un domani qualcuno aggiunge un tool comodo che prende un `enc_oid`, il test
rosso arriva prima del dato spedito.

---

## 2. I cinque strumenti

| strumento | risponde a |
|---|---|
| `cardio_proponi_terapia` | «che cosa aggiungeresti alla dimissione?» |
| `cardio_sostegno_del_concetto` | **«da dove viene questo fatto?»** |
| `cardio_verifica_sicurezza` | «questo farmaco si può dare a questo paziente?» |
| `cardio_cerca_codice` | «che cos'è `C03DA`?» / «qual è il codice dei sartani?» |
| `cardio_statistiche_corpus` | «quanto è affidabile quello che mi stai dicendo?» |

`cardio_sostegno_del_concetto` è quello per cui lo step 9ter aveva lasciato la
nota di disegno: *«da dove viene questo fatto» è esattamente la domanda che un
modello conversazionale ha bisogno di poter fare.* Restituisce la catena
interrogata in SPARQL — agente, regola, offset di carattere — e non un riassunto.

Due dettagli che valgono più di quanto sembri:

**Quando non sa, lo dice.** Un codice che il sistema non ha estratto non
restituisce una lista vuota e basta:

> *«Nessuna menzione sostiene questo codice in questo testo. Non significa che il
> fatto sia falso: significa che il sistema non lo ha estratto.»*

Un modello che leggesse una lista vuota concluderebbe «il paziente non ha questa
condizione». È la differenza fra assenza di prova e prova di assenza, e su un
supporto alla decisione clinica non è una sottigliezza.

**Ogni risposta porta il suo tetto.** `cardio_proponi_terapia` allega che il
**40,4%** delle prescrizioni di dimissione non è cardiologia, quindi un'assenza
dalle proposte non è una controindicazione. Un modello conversazionale tende a
presentare come completo l'elenco che riceve; qui riceve anche il limite.

---

## 3. Due client, e il secondo è quello che dimostra qualcosa

### Claude Code

```bash
claude mcp add cardio -- python3 src/mcp_server.py
claude mcp list
#   cardio: python3 .../src/mcp_server.py - ✔ Connected
```

### L'host locale con ollama

Sessanta righe scritte a mano invece di un framework, per la stessa ragione del
ciclo di addestramento dello step 5: ogni passaggio resta visibile — **quante
volte il modello chiama uno strumento, con quali argomenti, e quanto ci mette**.

Le quattro corse che seguono sono in ordine cronologico. Le prime tre hanno
trovato difetti; la quarta è il risultato. Le riporto tutte perché la sequenza
dice come il sistema è stato messo alla prova, e perché **due dei tre difetti
erano miei**.

### Corsa 1 — sembrava un successo, e non lo era

Prima domanda, in prosa piena. Il modello chiama `cardio_proponi_terapia` al
primo giro, con gli argomenti giusti. Avevo scritto che «sceglie lo strumento
giusto al primo colpo», e mi ero fermato lì.

Poi ho letto la prosa che aveva prodotto:

> «l'aggiunta di un **Betabloccante selettivo (A02BC)**»
> «**Profilo nefroprotettivo:** […] offre un'ulteriore protezione renale»

`A02BC` sono gli **inibitori di pompa protonica**. Il «profilo nefroprotettivo»
è farmacologia inventata.

### Perché: il fatto mancante, di nuovo

Guardando cosa lo strumento gli aveva davvero passato:

```
condizioni: []                        ← nessuna
farmaci:    []                        ← nessuno
A02BC   inibitori della pompa acida    classe=None  fonte=None
C03DA   antagonisti dell'aldosterone   classe=None  fonte=None
C07AB   betabloccanti, selettivi       classe=None  fonte=None
```

Due difetti miei, entrambi silenziosi. «Paziente **iperteso**» non è nel
gazetteer, che riconosce le forme per esteso — fatto già noto dallo step 9bis.
E il modello aveva passato la terapia separata da **virgole**, mentre il parser
vuole il punto e virgola *e la dose*: la descrizione dello strumento non lo
diceva.

Quindi lo strumento ha restituito **il tasso di base del reparto** presentandolo
come una risposta su quel paziente. Il modello ha visto `fonte: null` e ha
riempito il vuoto da sé.

È la quarta ricorrenza del `PRINCIPIO_DEL_FATTO_MANCANTE` dello step 8, e la
prima a questa frontiera: **una risposta la cui premessa è fallita non deve
presentarsi come valida.** Ogni proposta dichiara ora il proprio `fondamento` —
`indicazione citata`, con la fonte, oppure `co-occorrenza misurata nel corpus`,
con un avvertimento in chiaro: *«Non attribuirle una motivazione clinica che il
sistema non ha dato.»* E quando non estrae nulla, lo strumento lo dice, col
rimedio.

### Corsa 2 — la domanda telegrafica

Stessi fatti clinici, stile da appunti: *«Uomo, FE ridotta, iperteso, oggi
furosemide + ramipril»*. Il modello chiama `cardio_cerca_codice` quattro volte e
non arriva a una risposta.

Due conseguenze. La prima è sul mio client, che stampava solo i **nomi** dei
parametri e non i valori — nascondendo proprio l'errore tipico di un modello
piccolo: strumento giusto, argomento sbagliato. La seconda è un guardiano contro
la chiamata ripetuta identica, che ora torna al modello come informazione
(*«hai già chiamato X con questi stessi argomenti»*) invece di restituirgli due
volte la stessa risposta.

### Corsa 3 — il difetto peggiore, e non è nel codice

```
-> cardio_proponi_terapia(anamnesi='Ipotensione con frazione di eiezione …',
                          terapia_ingresso='furosemide; ramipril')
```

Il paziente è **iperteso**. Il modello, passando il testo allo strumento, l'ha
riscritto, e la riscrittura ha invertito il fatto: ipertensione → **ipotensione**.

Questo è più grave dell'`A02BC`, perché **il server non ha modo di
accorgersene**. Riceve la parafrasi credendola il testo del clinico, estrae
correttamente da quella, e produce offset di provenienza che puntano a parole che
nessuno ha scritto. Tutta la catena dello step 9ter — agente, regola, posizione
nel referto — resta formalmente corretta e sostanzialmente falsa.

**È il limite strutturale di mettere un modello davanti a questo sistema**, e va
dichiarato: *la provenienza vale quanto il testo che arriva allo strumento.*
L'unica difesa disponibile è chiederlo — `IMPORTANTE: passa l'anamnesi ALLA
LETTERA` nella descrizione, e la stessa istruzione nel client — e sapere che è
una difesa debole.

Nota positiva della stessa corsa: il `FORMATO:` aggiunto dopo la corsa 1 ha
funzionato, il punto e virgola è comparso.

### Corsa 4 — dopo le correzioni

```
[giro 1] 15.7s, 1 chiamate a strumenti
    -> cardio_proponi_terapia(anamnesi='Paziente iperteso con frazione di eie…',
                              terapia_ingresso='furosemide; ramipril', quante='1')
[giro 2] 27.2s, 0 chiamate a strumenti
```

> «Lo strumento non può fornire una proposta clinica perché il testo fornitomi
> non contiene le informazioni necessarie: il sistema non riconosce il termine
> «iperteso» come condizione e non identifica la terapia con il formato corretto.
> […] Per procedere avrei bisogno di: 1. un codice ICD-10 per l'ipertensione […]»

**Anamnesi passata alla lettera, nessuna invenzione, e un rifiuto motivato al
posto di una raccomandazione fabbricata.** È il confronto che conta: davanti allo
stesso testo, prima della correzione il modello inventava un «profilo
nefroprotettivo», dopo dichiara che non ha i fatti e chiede quelli che gli
servono.

Il merito non è del modello: è del campo `fatti_mancanti`. **Un modello
conversazionale riempie i vuoti che gli si lasciano**, e l'unico modo di
impedirglielo è non lasciarne.

Resta un'imprecisione nella sua prosa — attribuisce al separatore un problema
che qui era la dose mancante — che viene dalla prima versione del mio messaggio
d'errore, ora corretta per nominare entrambi i requisiti.

### Che cosa la sequenza dimostra

`qwen3.5:4b`, su una macchina senza GPU, **sceglie lo strumento giusto quando la
domanda è in prosa** e usa il formato che la descrizione gli indica. Chiude il
cerchio — modello locale, server locale, dati locali — e dimostra che il server
non è legato a un fornitore.

Ma la lezione vera è sull'altro lato: **tutte le garanzie del progetto valgono
fino al confine dello strumento.** Oltre quel confine c'è prosa generata, e la
prosa può invertire un fatto, rinominare un codice, o inventare una motivazione.
Ciò che si può fare è ridurre i vuoti da riempire e dichiarare il limite; ciò che
non si può fare è garantirlo.

---

## 4. Il costo, misurato

| | |
|---|---|
| import del server | 0,42 s |
| prima proposta (carica 1 002 JSON, addestra l'ibrido) | 1,60 s |
| proposta successiva sullo stesso testo | **0,000 s** (cache) |
| `cardio_cerca_codice` | 0,007 s |
| `cardio_sostegno_del_concetto` (costruisce il grafo + SPARQL) | 0,70 s |
| un giro del modello locale | 23–45 s |

Il rapporto è quello che conta: **l'orchestrazione costa due ordini di grandezza
più degli strumenti.** Il collo di bottiglia è il modello, non il sistema — e i
1,6 s della prima chiamata si pagano una volta per sessione, non per domanda.

I `0,000 s` della seconda chiamata sono una `lru_cache` sulla coppia di testi.
Un server MCP riceve spesso la stessa domanda riformulata nella stessa
conversazione, e ricostruire la catena ogni volta sarebbe tempo speso a vuoto.

---

## 5. Due trappole della versione dell'SDK

**`FastMCP` non esiste più.** Da `mcp` 2.0 si chiama `MCPServer`:

```python
from mcp.server.mcpserver import MCPServer   # mcp 2.x
from mcp.server.fastmcp import FastMCP       # mcp 1.x — quasi tutta la
                                             # documentazione in giro
```

La skill ufficiale `mcp-builder` di Anthropic, installata in
[`.claude/skills/`](../.claude/skills/mcp-builder/), documenta ancora la 1.x. Il
pacchetto installato però lo dice da solo, con un messaggio d'errore che nomina
la guida di migrazione: è il modo giusto di rompere una compatibilità.

**`inputSchema` è diventato `input_schema`.** Il client locale è fallito al primo
giro proprio lì. L'ho scoperto dall'eccezione, non dalla documentazione — ed è la
ragione per cui il client stampa i suoi passaggi invece di nasconderli.

---

## 6. Dove questa skill non valeva, e perché

`mcp-builder` è ufficiale e generica; tre sue raccomandazioni non valgono qui, e
la ragione è registrata in
[`NOTA-PROGETTO.md`](../.claude/skills/mcp-builder/NOTA-PROGETTO.md):

- **`scripts/evaluation.py` non si esegue**: importa `from anthropic import
  Anthropic`, cioè l'API a consumo che il piano di Carlo non copre. Le domande
  di valutazione restano utili, l'esecutore cambia — qui è ollama.
- **Python, non TypeScript**: il server importa `traccia.py`, `ranker.py` e
  `filtro.py`. Riscriverli significherebbe mantenerne due copie allineate.
- **stdio, non HTTP**: il server gira sulla macchina di Carlo e i dati che
  indicizza non escono dal disco. stdio rende quella proprietà vera per
  costruzione invece di affidarla a un firewall.

---

## 7. Che cosa lo step 10 lascia aperto

- **La parafrasi del testo resta il limite non risolto.** Il server non può
  sapere se l'anamnesi che riceve è quella del clinico: la corsa 3 l'ha
  invertita («iperteso» → «Ipotensione») e nessun controllo lato server può
  accorgersene. La difesa è un'istruzione, quindi è debole. Una difesa vera
  richiederebbe che il testo entrasse nel sistema **senza passare dal modello**
  — per esempio un `resource` MCP che il client apre da file, con il modello che
  ne riceve solo l'identificatore. È un disegno diverso, ed è la prima cosa da
  fare se questo server dovesse servire a qualcosa più di una dimostrazione.
- **Quattro corse non sono una valutazione.** Servirebbero dieci domande con
  l'esito atteso, e il conteggio di quante volte il modello sceglie lo strumento
  giusto e passa il testo intatto. La skill `mcp-builder` descrive proprio questo
  (Fase 4), e si può fare a costo zero con ollama. Le quattro corse qui sono
  aneddoti utili, non una misura, e la differenza va detta.
- **Il server non espone il corpus, per scelta.** Se servisse — per esempio per
  mostrare un caso reale al docente — la strada corretta non è aggiungere un
  tool, ma un secondo server che accetti **solo** il client locale, dove il
  testo non lascia la macchina. È un disegno diverso, non un parametro.
- **Nessuno strumento di `resource` né di `prompt`.** MCP ne prevede altri due
  tipi; qui servivano gli strumenti, e aggiungere superficie senza una domanda
  a cui risponda è il modo più facile per rendere un server difficile da capire.
