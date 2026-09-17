# Step 9bis — La demo end-to-end, e i difetti che si vedono solo usando

**Stato:** completato.
**Riproducibilità:** `python3 src/demo.py --esempio 1 --traccia`; `--interattivo` per un'anamnesi da tastiera; `--stato <file.json>` per entrare nel motore da un'uscita di pipeline; `--json` per l'uscita come dato

Il progetto era arrivato allo step 9 senza che nessuno avesse mai *usato* il
contratto dati: ogni step lo produceva, lo misurava o lo confrontava. La demo
è il primo punto in cui qualcuno lo **consuma** dall'inizio alla fine, su un
paziente nuovo scritto a mano. Ha trovato tre difetti che nessuna metrica
mostrava, ed è per questo che viene **prima** del tool MCP: un difetto di
catena trovato da un modello conversazionale si confonderebbe con un difetto
del modello.

---

## 1. La catena, e dove passa

```
testo libero ──step 3/4/5──▶ StatoPaziente ──step 8──▶ candidati ammessi ──step 9──▶ proposte, con le fonti
                              (condizioni, farmaci,     filtro simbolico          ranker ibrido      │
                               allergie, con offset,                                                 ▼
                               stato e soggetto)                                            traccia (step 9ter)
```

`RecordPaziente` non è legato al file grezzo: le pipeline leggono un oggetto,
quindi un paziente nuovo è un oggetto nuovo. `demo.analizza` fa tutta la
catena e restituisce un dato; `analizza_stati` la fa **dallo stato in poi**,
ed è il punto in cui entrano il tool MCP a stato paziente e `--stato`. La
presentazione è separata dal calcolo: la pagina di dimostrazione e il server
MCP consumano lo stesso dato.

**Il motore predefinito è quello deterministico**, gazetteer + ConText: zero
rete, zero chiavi, zero denaro, riproducibile. Mostra *meno* di ciò che il
sistema sa fare — richiamo 19,5% sulle condizioni contro 70,1% del modello
linguistico — ed è una scelta di dimostrabilità; `--motore locale` o
`openrouter` affianca il modello e la traccia mostra due agenti.

## 2. I tre esempi, sintetici

| esempio | mostra |
| --- | --- |
| 1 · scompenso e fibrillazione atriale | la catena intera: quattro pilastri dello scompenso con la fonte ESC, un gastroprotettore «appreso dal corpus» dichiarato tale |
| 2 · negazione e familiarità | «non riferisce angina né cardiopatia ischemica» → negato; «padre deceduto per infarto» → familiare: nessuno dei due diventa un fatto del paziente |
| 3 · allergia dichiarata | allergia all'acido acetilsalicilico e cardiopatia ischemica: la classe `B01AC` è proposta con l'**avvertimento** di scegliere un'altra molecola, non vietata |

Sono scritti con la grammatica del corpus ma non sono referti. Un test
verifica che ogni esempio sia completo e che il gazetteer vi riconosca le
condizioni attese: un esempio vuoto non dimostra niente.

## 3. I tre difetti che la demo ha trovato

| difetto | causa | correzione | peso in una metrica |
| --- | --- | --- | --- |
| «Non riferisce X» registrato come **affermato** | `non` apre la negazione, `riferisce` è un terminatore d'ambito (giusto in «nega diabete ma riferisce ipertensione»): insieme la chiudevano un token dopo | `non riferisce` riconosciuto come marcatore composto, giustificato contando: 48 referti nel corpus | 4 attribuzioni su 5 237 |
| le allergie estratte dalla pipeline A **non erano mai codificate** | l'estrattore le registrava, nessuno chiamava il risolutore ATC | codifica delle 88 allergie a principi attivi: 46 ora con ATC (prima 0) | nessun numero documentato cambiava |
| «Bisoprololo 2,5 mg» **scartato** dal parser | la virgola decimale non era prevista dal formato della dose | parser corretto | 4 voci su 5 605 |

Nessuno era visibile a una metrica: in una tabella sono rumore. Guardati da
dove il sistema viene *usato* sono una negazione letta al contrario, uno
strato di sicurezza cieco e una prescrizione italiana normale non letta.
**Una metrica aggregata misura la media, e i difetti di un supporto alla
decisione non stanno nella media.** È la terza volta che il progetto incontra
la stessa legge — un difetto del contratto dati si vede quando qualcuno lo
consuma — dopo lo step 6 (il soggetto mancante) e lo step 8 (i dispositivi
che nessuna pipeline estrae).

## 4. Che cosa la demo non è

Non è una validazione clinica e non usa pazienti reali. Il ranker è misurato
contro una decisione presa da un medico per ricovero: una proposta non
prescritta non è per forza un errore. E il motore deterministico mostra il
sistema al suo minimo, non al suo meglio.
