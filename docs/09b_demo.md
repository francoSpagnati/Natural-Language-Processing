# Step 9bis — La demo: un paziente nuovo, dall'anamnesi alla proposta

Le metriche degli step 6, 6bis e 9 dicono *quanto bene* il sistema funziona.
Questo documento descrive il modo di vedere **che cosa fa**, su un paziente che
nel dataset non esiste: si scrive un'anamnesi e una terapia in atto, e il
sistema attraversa tutta la catena davanti a chi guarda.

Codice: [`src/demo.py`](../src/demo.py). Test:
[`tests/test_demo.py`](../tests/test_demo.py).

```
python3 src/demo.py --elenco            # i pazienti d'esempio
python3 src/demo.py --esempio 1         # la catena completa
python3 src/demo.py --interattivo       # incolla la tua anamnesi
python3 src/demo.py --anamnesi mio.txt --terapia mia.txt
python3 src/demo.py --esempio 1 --confronta   # i due motori affiancati
python3 src/demo.py --esempio 1 --traccia     # da dove viene ogni proposta
```

La traccia di provenienza ha un documento suo: [`09c_traccia.md`](09c_traccia.md).

---

## 1. Perché una demo, e perché **prima** del tool MCP

Il progetto è arrivato allo step 9 senza che nessuno avesse mai *usato* il
contratto dati: ogni step lo produceva, lo misurava o lo confrontava. La demo è
il primo punto in cui qualcuno lo **consuma** dall'inizio alla fine.

Il risultato è stato immediato: **la demo ha trovato tre difetti che nessuna
metrica aveva mostrato** (§4). È la terza volta che il progetto incontra la
stessa legge — *un difetto del contratto dati si vede solo quando qualcuno prova
a consumarlo* — dopo lo step 6 (l'asse `experiencer` mancante) e lo step 8 (i
dispositivi che nessuna pipeline estrae).

---

## 2. La catena, e dove passa

```
   testo libero scritto a mano
        │
        │  step 3/4/5  riconoscimento + codifica ICD-10 / ATC
        ▼
   stato del paziente          ← condizioni, farmaci, allergie, con offset
        │                        e con stato/soggetto (ConText)
        │  step 8      filtro di sicurezza: che cosa NON si può dare
        ▼
   candidati ammessi
        │
        │  step 9      ranker ibrido: che cosa conviene dare, e perché
        ▼
   terapia suggerita, con le fonti citate
```

Il punto che rende tutto questo possibile è piccolo e vale la pena dirlo:
`RecordPaziente` **non è legato al file grezzo**. Le pipeline leggono quello,
non il dataset, quindi costruire un paziente nuovo è costruire un oggetto. Se
la dipendenza fosse stata sul file, provare il sistema su un paziente nuovo
avrebbe richiesto di scriverlo dentro il dataset.

### Il motore predefinito è quello deterministico, e mostra *meno* del vero

La demo gira **senza rete, senza chiave API e senza costo**: l'estrazione usa la
pipeline A (gazetteer + ConText) e il parser deterministico della terapia. È una
scelta di dimostrabilità — chi guarda può rieseguirla — e non nasconde nulla:
sulle condizioni il gazetteer ha un richiamo misurato del **19,5%**, contro il
**68,7%** del modello linguistico. La demo predefinita mostra **meno** di quello
che il sistema sa fare, non di più, e `--confronta` rende visibile la differenza
sullo stesso paziente.

---

## 3. I tre esempi, e che cosa ciascuno dimostra

Tutti e tre **sintetici**: scritti con la grammatica del corpus — le
abbreviazioni, la punteggiatura, l'ordine delle sezioni — ma nessuno di quei
testi vi compare. Un test lo verifica meccanicamente a ogni esecuzione
(§5).

### Esempio 1 — la catena intera

Paziente con scompenso, fibrillazione atriale, ipertensione e diabete, già in
terapia con furosemide, metformina e pantoprazolo. Le prime proposte:

```
  1. C03DA  antagonisti dell'aldosterone
     [classe I]
     Antagonista del recettore mineralcorticoide. Terzo pilastro.
     fonte: ESC 2021, Guidelines for heart failure, terapia dell'HFrEF.

  2. C07AB  betabloccanti, selettivi
     [classe I]
     Betabloccante nello scompenso a frazione di eiezione ridotta.
     fonte: ESC 2021, Guidelines for heart failure, terapia dell'HFrEF.

  3. A10BK  inibitori del co-trasportatore SGLT-2
     [classe I]
     Inibitore di SGLT2 nello scompenso, indipendentemente dal diabete.
     fonte: ESC 2023, Focused update of the 2021 heart failure guidelines.
```

**Ogni riga porta la sua fonte.** È la differenza fra un suggerimento e
un'affermazione: un medico può andare a leggere la linea guida e contestare.

Da notare anche ciò che *non* succede: il gazetteer non riconosce
«fibrillazione atriale permanente», quindi l'anticoagulante non viene proposto.
Non è un caso costruito male, è il limite misurato della pipeline A — e
`--confronta` lo rende esplicito.

### Esempio 2 — negazione e familiarità

```
Uomo di 58 anni. Non riferisce angina ne' [cardiopatia] ischemica.
Padre deceduto a 60 anni per infarto miocardico; madre diabetica.
Segue cura per [ipertensione arteriosa] dal 2019; ...
```

```
x cardiopatia               I51.9     negato     paziente
  ipertensione arteriosa    I10       affermato  paziente
```

La riga marcata `x` **non diventa un fatto del paziente**. Senza quella
distinzione il sistema raccomanderebbe una terapia per una malattia che il
referto dichiara esclusa, o per la malattia del padre.

### Esempio 3 — l'allergia, e l'avvertimento che non è un divieto

```
  1. B01AC  antiaggreganti piastrinici
     [classe I]
     Antiaggregante piastrinico nella malattia aterosclerotica accertata.
     fonte: ESC 2024, Guidelines for chronic coronary syndromes.
     ATTENZIONE: allergia dichiarata a una sostanza di questa classe
     (B01AC06): scegliere un'altra molecola.
```

La classe resta proposta — è una raccomandazione di classe I — e insieme arriva
l'informazione che dentro quella classe c'è una molecola da evitare. È la forma
stabilita allo step 9 §8 dopo il caso del paziente allergico all'aspirina a cui
il medico aveva prescritto clopidogrel: **al livello di classe, un'allergia
avverte, non vieta.**

---

## 4. I tre difetti che la demo ha trovato

### «Non riferisce X» veniva registrato come affermato

Il primo paziente scritto a mano diceva *«Non riferisce angina né cardiopatia
ischemica»*, e il sistema registrava la cardiopatia come **affermata**.

La causa non era in un marcatore ma nella loro interazione. `non` apre un ambito
di negazione; `riferisce` è un **terminatore** di ambito — ci sta per una
ragione ottima, perché in *«Nega diabete ma riferisce ipertensione»*
l'ipertensione non è negata. Messi insieme, `non` apriva la negazione e
`riferisce` la chiudeva un token dopo, lasciando l'entità fuori.

La correzione riconosce l'intera espressione come un marcatore composto, così
l'ambito parte **dopo** di essa e il terminatore non entra in gioco. Giustificata
con lo stesso metodo che ha costruito il resto del lessico, cioè contando il
corpus:

| espressione | occorrenze | referti |
|---|---|---|
| `non riferisce` | 23 | 23 |
| `non riferiti` | 18 | 18 |
| `non riferita` | 6 | 6 |
| `non riferito` | 1 | 1 |
| **totale** | **48** | **48** |

Più di `non presenta` (6) e `non risultano` (2), che infatti non sono nel
lessico.

**Effetto misurato sul corpus intero: 4 attribuzioni su 5 237 cambiano**
(0,076%), tutte da `affermato` a `negato` — cioè tutte nella direzione giusta.
Un test fissa anche il caso opposto, perché una correzione che baratta un errore
con il suo contrario non è una correzione.

### La pipeline A estraeva le allergie ma non le codificava mai

Il terzo esempio non mostrava l'avvertimento per cui era stato scritto. La causa:
`allergie_dal_referto` produceva l'allergene come **stringa** e non chiamava mai
il risolutore ATC, benché la pipeline ne avesse già uno in mano.

Il filtro dello step 8 confronta **codici**, non nomi. Un'allergia non
codificata non poteva bloccare niente: **lo strato di sicurezza era cieco su
tutto ciò che quella pipeline produceva.**

| | |
|---|---|
| allergie estratte dalla pipeline A | 198 |
| di categoria «principi attivi» | 88 |
| ora codificate in ATC | **46** (prima: 0) |

Solo i principi attivi vengono codificati: un'allergia a un alimento va
conservata ma non vincola la scelta di un farmaco, ed è la distinzione che il
campo `categoria` esiste per esprimere.

**I numeri dello step 8 non si muovono**: rieseguito dopo la correzione, il
filtro dà ancora 91,34% ammesse, 8,60% da verificare, **4 vietate**. La
correzione rende capace lo strato di sicurezza senza cambiare nessun esito
documentato — i 46 allergeni in più appartengono a pazienti a cui quella
sostanza non era stata prescritta.

### La virgola decimale scartava la voce di terapia

Il terzo esempio dichiarava due farmaci e il sistema ne leggeva uno.

```
"Bisoprololo 2,5 mg: 1 cp"   →  scartato
"Bisoprololo 2.5 mg: 1 cp"   →  Bisoprololo
"Bisoprololo 5 mg: 1 cp"     →  Bisoprololo
```

La causa è una guardia messa lì apposta, e per un'ottima ragione: il livello 3
del parser — «prendi il nome che precede la prima cifra» — **non si applica alle
voci con una virgola**, perché quelle sono i blocchi scritti a mano dal clinico
che elencano più farmaci in un segmento solo (`cardirene 75 mg, ansimar 400 mg,
lucen 20 mg`), e prenderne uno significherebbe perdere gli altri in silenzio.

Ma **una virgola fra due cifre non è un elenco**: è il separatore decimale, e in
italiano è la notazione normale — «2,5 mg» è il dosaggio più comune del
bisoprololo. La guardia è stata ristretta a riconoscere solo le virgole di
elenco.

| | prima | dopo |
|---|---|---|
| voci di terapia d'ingresso riconosciute | 5 536 | **5 540** |
| scarti | 69 | 65 |
| copertura | 98,77% | **98,84%** |

Sul corpus vale quattro voci. **Su un testo scritto a mano vale tutto**, ed è il
motivo per cui non era mai emerso: nel corpus quel formato è raro, sotto la
tastiera di chi prova la demo è il primo che viene scritto. Due test fissano
entrambi i lati — la virgola decimale passa, quella di elenco resta guardata —
perché una correzione che baratta un errore con il suo opposto non è una
correzione.

### Perché tutti e tre, e tutti insieme

Nessuno dei tre era visibile a una metrica. Il primo sposta 4 attribuzioni su
5 237; il secondo non cambia **nessun** numero documentato; il terzo vale 4 voci
su 5 605. In una tabella di risultati sono rumore.

Guardati da dove il sistema viene *usato* sono tre cose diverse: una negazione
letta al contrario, uno strato di sicurezza cieco, e una prescrizione italiana
normale che non viene letta. **Una metrica aggregata misura la media, e i difetti
di un sistema di supporto alla decisione non stanno nella media.**

---

## 5. Gli esempi non possono contenere testo dei referti

Gli esempi si mostrano a terzi, quindi cadono sotto la regola di privacy del
progetto: **nessuna finestra di 40 caratteri di un file versionato può comparire
in meno di cinque referti.**

Il test che la verifica ha subito trovato una violazione nella prima stesura:

```
'ibrillazione atriale permanente. Iperten'  →  1 referto
```

Scrivendo testo sintetico «con la grammatica del corpus» avevo ricostruito per
caso una giunzione di frasi che esiste in un referto solo. Gli esempi sono stati
riscritti finché il conteggio non è andato a zero.

La soglia e la lunghezza di finestra il test **le importa da `src/privacy.py`**
invece di ridefinirle: due copie della stessa regola possono divergere, e quella
che diverge in silenzio è la regola di privacy.

Nota sulla regola, perché è facile fraintenderla: non vieta che una frase
compaia nel corpus. *«Ipertensione arteriosa in trattamento»* è scrittura
clinica comune e non identifica nessuno. Vieta le frasi **rare**, che sono
quelle che raccontano un paziente.

---

## 6. Che cosa la demo non è

Non è un dispositivo medico e non è una validazione clinica, e il programma lo
stampa in coda a ogni esecuzione. Il ranker è misurato contro **una** decisione
presa da **un** medico su 244 ricoveri: una proposta non prescritta non è per
forza un errore, e una prescritta e non proposta non è per forza una svista.
Il §1 di [`09_ranker.md`](09_ranker.md) spiega perché la precisione di quella
misura non è interpretabile come correttezza.
