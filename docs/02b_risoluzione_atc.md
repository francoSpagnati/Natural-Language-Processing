# Step 2 (parte 2) — Risoluzione ATC dei farmaci

**Stato:** completato.
**Riproducibilità:** `python3 src/normalize_drugs.py`

---

## 1. Perché è obbligatoria

Il brief richiede la risoluzione ATC come requisito, non come opzione: il codice
serve a interrogare le knowledge base esterne (step 7) e a calcolare la metrica
gerarchica sui 5 livelli (step 11). Senza ATC non c'è né KG né valutazione.

## 2. Il risultato

| | Voci | Risolte | Ambigue | NIL |
|---|---|---|---|---|
| Principi attivi | 406 | **316 (77,8 %)** | 1 | 89 |
| Nomi commerciali | 923 | **811 (87,9 %)** | 18 | 94 |

**Copertura pesata sulle occorrenze: 94,0 %** (17 047 su 18 142).

Quest'ultimo è il numero che conta davvero. Il conteggio per voce distinta è
dominato dalla coda rara — farmaci visti una volta sola — mentre la copertura
pesata dice quanta parte del *testo reale* riusciamo effettivamente a
normalizzare. Il residuo del 6 % è concentrato in poche voci ricorrenti,
elencate in sez. 5.

## 3. Una cascata di strategie, non un solo confronto

Lo step 1 si fermava al 70 % con la sola corrispondenza esatta. L'ispezione
delle voci mancanti aveva mostrato che il residuo non era rumore ma **cause
sistematiche**, ciascuna con una regola propria. Le strategie sono provate in
ordine, e la prima che riesce vince:

| # | Strategia | Cosa risolve | Esempio | Voci |
|---|---|---|---|---|
| 1 | `principio_esatto` | il nome è già la descrizione ufficiale | `Bisoprololo` → C07AB07 | 296 |
| 2 | `associazione` | il dataset usa `/`, AIFA la congiunzione | `Rosuvastatina/ezetimibe` → `ROSUVASTATINA E EZETIMIBE` → C10BA06 | 12 |
| 3 | `commerciale_esatto` | denominazione autorizzata | `Congescor` → C07AB07 | 629 |
| 4 | `commerciale_abbreviato` | sigla del produttore troncata | `pantoprazolo sand` → `pantoprazolo sandoz` → A02BC02 | 188 |
| 5 | `suffisso_salino` | il dataset aggiunge il sale, AIFA no | `Warfarin sodico` → `WARFARIN` → B01AA03 | 18 |
| 6 | `forma_salina` | il dataset abbrevia, AIFA scrive per esteso | `Enoxaparina` → `ENOXAPARINA SODICA` → B01AB05 | 3 |

Ogni voce porta nel JSON **il metodo che l'ha risolta e l'evidenza esatta**
della fonte. Non è decorazione: i metodi non sono equivalenti, e chi legge deve
poter dare peso diverso a una corrispondenza esatta e a un accostamento per
prefisso — e chi valuta deve poter escludere i metodi deboli per misurarne
l'effetto.

### 3.1 Nessuna lista di sigle scritta a mano

La strategia 4 si sarebbe potuta risolvere con un elenco di abbreviazioni
(`sand` → Sandoz, `eg` → EG S.p.A.). Compilarlo a mano sarebbe stato però
esattamente il tipo di dato inventato che il progetto vieta.

La regola usata ricava invece il collegamento dai dati AIFA stessi: **i token
del nome nel dataset devono essere prefissi dei token della denominazione
AIFA**. `pantoprazolo sand` corrisponde a `pantoprazolo sandoz` perché `sand`
è prefisso di `sandoz`; nessuna sigla è scritta da noi. La stessa regola
risolve gratis anche i principi attivi troncati dall'ospedale:
`acido acetils eg` → `acido acetilsalicilico eg` → B01AC06.

Effetto collaterale prezioso: **`Silodosina` (G04CA04) e `Febuxostat`
(M04AA03), che il registro ATC di AIFA non elenca affatto**, si risolvono
comunque attraverso le denominazioni commerciali che li contengono. È il motivo
per cui usare due indici AIFA invece di uno solo ripaga.

### 3.2 Un errore di provenienza, trovato e corretto

Nella prima versione le strategie sui sali precedevano quelle commerciali. Il
risultato: `pantoprazolo sand`, troncato di `sand`, diventava `pantoprazolo` —
una sostanza esistente. Il codice ATC finale era **giusto**, ma la voce
risultava risolta «per forma salina» quando in realtà è un generico riconosciuto
per nome commerciale.

Un errore invisibile nei numeri (la copertura cambiava dello 0,2 %) ma che
avrebbe reso **falsa la provenienza registrata** — cioè proprio ciò che questo
progetto usa per difendere le sue scelte. Spostate le due strategie sui sali in
fondo, `suffisso_salino` è passato da 206 a 18 occorrenze: le 188 differenze
erano tutte generici mal attribuiti. Coperto da un test di regressione.

## 4. Le ambiguità non vengono risolte d'ufficio

19 voci hanno più codici ATC compatibili e restano marcate `ambiguo`, senza
`codice_atc`:

| Voce | Candidati | Perché |
|---|---|---|
| `lyrica` | N02BF02, N03AX16 | pregabalin ha due codici, per il dolore neuropatico e per l'epilessia |
| `humalog` | A10AB04, A10AC04, A10AD04 | insulina lispro in formulazioni rapida, intermedia e mista |
| `luvion` | C03DA02, C03DA03 | canrenone e potassio canrenoato |
| `ventolin` | R03AC02, R03CC02 | salbutamolo inalatorio e sistemico |

Sono **ambiguità reali della sostanza**, non difetti del metodo: la stessa
molecola ha codici diversi secondo indicazione o via di somministrazione.
Sceglierne uno qui produrrebbe un errore silenzioso a valle, dove nessuno
saprebbe più che la scelta era arbitraria. La disambiguazione ha bisogno del
contesto clinico del paziente, quindi appartiene all'entity linking (step 5).

## 5. Cosa resta non risolto

183 voci, **835 occorrenze (4,6 %)**. Le altre 260 occorrenze che mancano al
100 % sono le voci ambigue di sez. 4, che un codice ce l'hanno ma non uno solo.
Le non risolte più frequenti:

| Occorrenze | Voce | Causa |
|---|---|---|
| 64 | `ferrograd` | nome commerciale assente dall'anagrafica AIFA corrente |
| 55 | `Ferroso solfato` | AIFA elenca solo `FERROSO GLUCONATO`: sostanza diversa |
| 45 | `tamsulosin sun` | denominazione non presente in quella forma |
| 36 | `Insulina lispro da dna ricombinante` | dicitura descrittiva, non una denominazione |
| 33 | `Clopidogrel/acido acetilsalicilico` | l'associazione non è nel registro ATC AIFA |
| 24 | `Omega polienoici` | AIFA la chiama `OMEGA-3-TRIGLICERIDI INCLUSI ALTRI ESTERI E ACIDI` |
| 16 | `-` | segnaposto del sistema ospedaliero |

Nessuna è stata forzata su un accostamento plausibile. `Ferroso solfato` è il
caso esemplare: troncato diventa `ferroso`, che non è una sostanza, quindi la
regola non produce nulla — invece di accostarlo a `Ferroso gluconato`, che è un
sale diverso. Il vincolo di **corrispondenza esatta dopo il troncamento** è
precisamente ciò che rende sicura una regola altrimenti azzardata, ed è coperto
da un test.

## 6. Componenti creati

| Modulo | Responsabilità |
|---|---|
| `src/normalize_drugs.py` | Costruisce gli indici AIFA e applica la cascata di strategie, registrando metodo, fonte ed evidenza per ogni voce. |

| File | Contenuto |
|---|---|
| `data/interim/mappatura_atc.json` | 1 329 voci con ATC risolto, candidati, metodo, stato, fonte ed evidenza |

Modelli aggiunti a `src/schema.py`: `MetodoRisoluzione`, `VoceMappaturaATC`,
`MappaturaATC`.

**Test:** 11 nuovi (66 in totale), su un indice AIFA in miniatura costruito nel
test con le convenzioni di scrittura della fonte reale, così girano senza gli
82 MB di anagrafica.

## 7. Limiti noti

- La copertura del 94 % è pesata sulle occorrenze; per voce distinta è più
  bassa — 1 127 su 1 329, cioè **84,8 %** — perché la coda rara è meno coperta.
- `commerciale_abbreviato` è la strategia più permissiva: richiede che i token
  del dataset siano prefissi di quelli AIFA, il che in teoria può accostare due
  medicinali con radice comune. Non si è osservato nel dataset, ma il metodo è
  registrato su ogni voce proprio per poterle isolare.
- Le 19 voci ambigue restano senza codice fino allo step 5.
- La risoluzione parte dal vocabolario chiuso, quindi vale per i farmaci
  osservati in questo dataset; un farmaco nuovo va normalizzato al volo, cosa
  che il modulo supporta ma che nessuno step ha ancora esercitato.
