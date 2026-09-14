# Step 8 — Il filtro di sicurezza simbolico

È il punto in cui il sistema smette di descrivere e comincia a raccomandare, e
quindi il punto in cui un errore smette di essere una cifra sbagliata in un
rapporto e diventa una terapia negata o una controindicazione lasciata passare.

---

## 1. Perché simbolico, e perché non tocca il dataset

Due vincoli del progetto si incontrano qui, e nessuno dei due è negoziabile.

**Mai un modello linguistico.** Una regola di sicurezza deve poter essere letta,
discussa e *contestata* da un clinico. Un modello che risponde «questo farmaco è
controindicato» non è contestabile: non gli si può chiedere su quale riga di
quale linea guida si basa. Qui ogni regola porta la sua fonte nel codice, e la
fonte viaggia dentro la spiegazione che il filtro restituisce — non resta in un
commento che nessuno legge.

**Mai il dataset.** Le regole non si imparano dai referti. Se le imparassimo,
misureremmo che cosa i cardiologi di quel reparto hanno prescritto — non che
cosa è sicuro — e il sistema raccomanderebbe di ripetere le abitudini del
reparto, **inclusi i suoi errori**. Il dataset serve a *provare* il filtro, mai
a costruirlo.

---

## 2. I tre esiti, e perché non sono due

Un filtro che risponde solo «sì» o «no» nasconde che i suoi due errori sono
entrambi dannosi, e che non sono simmetrici:

* un **falso blocco** nega al paziente una terapia che potrebbe assumere;
* un **falso permesso** lascia passare una controindicazione.

«Nel dubbio blocca» tratta il secondo come grave e il primo come gratuito, e non
è vero: **negare un anticoagulante a chi ha la fibrillazione atriale fa danno
quanto darlo a chi sta sanguinando.**

Gli esiti sono quindi tre — `ammesso`, `da_verificare`, `vietato` — e il secondo
esiste perché ci sono casi in cui la risposta onesta è «guarda tu», con il
motivo e l'evidenza allegati.

---

## 3. Le quattro famiglie di regole

| famiglia | da dove viene | esito tipico |
|---|---|---|
| **Allergia alla sostanza** | anamnesi del paziente + ATC | vietato |
| **Allergia al sottogruppo** | gerarchia ATC (reattività crociata) | da verificare |
| **Duplicazione terapeutica** | gerarchia ATC | da verificare |
| **Controindicazione per condizione** | tabella manuale dichiarata, § 4 | variabile |
| **Provenienza** | misure dello step 6bis | declassa |

Le prime tre non richiedono conoscenza esterna al progetto: la gerarchia ATC
**è già** la knowledge base, e il livello di un codice si legge dalla sua
lunghezza per definizione dell'OMS. Due farmaci con lo stesso ATC di 5° livello
sono la stessa sostanza; con lo stesso di 4° livello sono lo stesso sottogruppo
farmacologico.

La quarta è l'unica che richiede conoscenza esterna, ed è la più delicata.

---

## 4. La tabella delle controindicazioni, e che cosa **non** è

Dodici regole, ciascuna con la sua fonte puntuale: RCP AIFA/EMA sezione 4.3 per
le controindicazioni da scheda tecnica, linee guida ESC per quelle da consenso
clinico.

| farmaco (ATC) | condizione (ICD-10) | esito | fonte |
|---|---|---|---|
| C07 betabloccanti | J45, J44 asma/BPCO | da verificare | ESC/ESH 2024 |
| C07 betabloccanti | I44.1–3 blocco AV | vietato → **declassato**, § 6 | RCP 4.3 |
| C08D verapamil, diltiazem | I50 scompenso | vietato | ESC 2021 |
| M01A FANS | I50 scompenso | vietato | ESC 2021 |
| M01A FANS | N18.4–5 insuff. renale | vietato | RCP 4.3 |
| C09 ACE-i, sartani | O gravidanza | vietato | RCP 4.3/4.6 |
| C09 ACE-i, sartani | I70.1 stenosi renale | vietato | RCP 4.3 |
| A10BA02 metformina | N18.4–5 | vietato | RCP 4.3 |
| B01A antitrombotici | I60–62 emorragia | vietato → **declassato**, § 6 | RCP 4.3, ESC 2020 |
| C01BD01 amiodarone | E05, E03 tireopatia | da verificare | RCP 4.3/4.4 |
| C10AA statine | K70–74 epatopatia | da verificare | RCP 4.3 |
| C03A tiazidici | M10 gotta | da verificare | RCP 4.4 |

**Va detto chiaramente che cosa questa tabella non è.** Non è una base di
conoscenza clinica completa: sono dodici regole scelte per essere
rappresentative dei *meccanismi* che un filtro deve saper esprimere — classe di
farmaco contro categoria di condizione — non l'insieme delle controindicazioni
esistenti.

Il vincolo del progetto dice che una voce non coperta da una fonte esterna va
**segnalata come mappatura manuale con la fonte puntuale usata**, invece di
essere riempita in silenzio. È esattamente ciò che questa tabella è: una
mappatura manuale dichiarata. Un sistema reale la sostituirebbe con una base di
conoscenza mantenuta; la struttura del filtro non cambierebbe, ed è il motivo
per cui la tabella è isolata in una sola costante.

---

## 5. Le due righe che giustificano tutto lo schema

```python
if c["stato"] != "affermato" or c.get("soggetto", "paziente") != "paziente":
    continue
```

Sono le due righe per cui l'asse dello **stato** e quello del **soggetto**
esistono. Senza la prima, una condizione *esclusa* dal clinico
controindicherebbe un farmaco. Senza la seconda, **il sistema negherebbe un
antinfiammatorio a chi ha il padre scompensato.**

Lo step 7 ha misurato che il **12,2%** delle menzioni di condizione non è una
condizione attuale del paziente. Qui quel numero smette di essere una statistica
e diventa una riga di codice: una prescrizione su otto sarebbe valutata contro
un fatto che al paziente non appartiene.

---

## 6. La prova: il filtro contro la terapia che i cardiologi hanno prescritto

È la verifica più severa disponibile senza dati nuovi. La terapia alla dimissione
è ciò che un medico ha deciso per quel paziente: un filtro che ne vieta una quota
consistente **non ha trovato errori dei cardiologi**, ha un difetto proprio.

| su 1 000 ricoveri, 5 863 prescrizioni di dimissione | | |
|---|---|---|
| ammesso | 5 355 | 91,3% |
| da verificare | 504 | 8,6% |
| **vietato** | **4** | **0,07%** |

Quattro divieti su quasi seimila prescrizioni reali, e sono tutti e quattro casi
di **farmaco prescritto a un paziente che il referto dichiara allergico o
intollerante a quella stessa sostanza**. Sono esattamente ciò che un filtro di
sicurezza deve produrre: pochissimi blocchi, ciascuno difendibile uno per uno.

### La prima versione ne bloccava 28, e i 24 di troppo hanno insegnato il principio

La versione iniziale emetteva **28 divieti**. Guardandoli uno per uno — che è
l'unico modo di sapere se un filtro funziona — ne sono usciti due gruppi.

**Quattordici betabloccanti in blocco atrioventricolare.** Cercando nei referti:
in **12 casi su 14** il testo nomina un pacemaker o un defibrillatore. Un
paziente stimolato può assumere un betabloccante in sicurezza — è proprio il
dispositivo a proteggerlo dalla bradicardia. **Un divieto con l'86% di falsi
blocchi non è un presidio di sicurezza: è un guasto che nega terapie.**

**Dieci antitrombotici in emorragia intracranica.** Qui manca un'altra cosa: la
regola vale per l'emorragia *in atto o recente*, mentre un'emorragia remota è
una cautela. Distinguere richiede la **storicità**.

### Il principio che ne è seguito

> Una regola la cui applicazione corretta richiede un fatto che il sistema non
> sa stabilire **non può emettere un divieto**. Può segnalare, non decidere.

Non è prudenza generica: è una conseguenza misurata, e il filtro la applica in
codice attraverso il campo `fatto_non_estratto`.

---

## 7. Il risultato dello step 8: lo strato di sicurezza ha bisogno di fatti che
nessuno estrae

I due gruppi di falsi blocchi hanno la stessa forma, e **non sono difetti di
estrazione**.

**Il pacemaker.** `Z95.0 Presenza di dispositivi cardiaci elettronici` esiste
nella terminologia ICD-10 che il progetto ha estratto. Nessuna delle tre
pipeline lo produce, e per una ragione di progetto: **un dispositivo non è una
malattia**, e tutte e tre cercano diagnosi. Il gazetteer ha un vocabolario di
patologie; la REGOLA 2 del prompt dice che una condizione è «diagnosi, patologie
e fattori di rischio»; il NER è addestrato sulle etichette del gazetteer.

**La storicità.** ConText la calcola — **97 condizioni su 1 520** la portano
nella pipeline A — ma lo schema non ha un campo per registrarla: finisce dentro
la stringa di provenienza, dove un filtro non può interrogarla in modo
affidabile. L'asse esiste nell'algoritmo e manca al contratto dati.

È la stessa forma di scoperta dello step 6, quando il confronto rivelò che
mancava l'asse dell'*experiencer*: **un difetto del contratto dati diventa
visibile solo quando qualcuno prova a consumarlo.** Allora fu la familiarità;
adesso sono la storicità e i fatti non-diagnostici.

### Che cosa servirebbe, ed è fuori da questo step

| fatto mancante | dove esiste già | cosa manca |
|---|---|---|
| dispositivi impiantati | ICD-10 Z95.x, estratto | nessuna pipeline li cerca: non sono malattie |
| storicità | calcolata da ConText | un campo nello schema, non una stringa |
| gravità dell'allergia | distinta clinicamente | lo schema ha `categoria`, non la severità |

L'ultima riga spiega un caso residuo: un'*intolleranza* gastrointestinale alla
metformina è trattata come un'allergia, mentre clinicamente è una cautela.

---

## 8. Un falso blocco che è un errore di estrazione, non di regola

Uno dei quattro divieti residui merita di essere raccontato per intero, perché
mostra come un errore si propaghi lungo la catena senza che nessuno strato lo
possa fermare.

Un referto racconta che una terapia anticoagulante è stata **sostituita** con
un'altra a causa di una reazione cutanea. La reazione riguarda il farmaco
*sospeso*; quello nuovo è il rimedio. L'estrazione ha attribuito la reazione al
farmaco sbagliato — al sostituto invece che al sostituito — e il filtro ha
fedelmente vietato la terapia in corso.

Il filtro ha fatto il suo lavoro: **ha propagato senza inventare**. È l'errore a
monte che non era visibile, ed è visibile adesso solo perché qualcosa a valle lo
ha usato.

---

## 9. Test

19 test in `tests/test_filtro.py`, organizzati attorno alle proprietà da cui
dipendono le decisioni cliniche.

| proprietà | perché, se si rompesse, non si noterebbe |
|---|---|
| una condizione **negata** non controindica | il sistema negherebbe terapie per malattie che il clinico ha escluso |
| una condizione di un **familiare** non controindica | negherebbe un antinfiammatorio a chi ha il padre scompensato |
| la reattività crociata **non** è un divieto | negherebbe intere classi di farmaci su un'ipotesi |
| una regola con un **fatto mancante** segnala e non vieta | 12 falsi blocchi su 14, misurati |
| se il fatto revocante **c'è**, la regola non scatta affatto | il meccanismo è pronto per quando il dispositivo sarà estratto |
| il solo gazetteer non basta a vietare | un divieto poggerebbe sulla pipeline con la precisione più bassa |
| la **fonte** viaggia nel verdetto | una regola che non dice su cosa si basa non è contestabile da un clinico |
| un divieto vince su un dubbio, un dubbio non declassa un divieto | l'ordine degli esiti diventerebbe dipendente dall'ordine delle regole |
