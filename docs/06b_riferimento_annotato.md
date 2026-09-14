# Step 6bis — Un riferimento annotato a mano

Fino a qui il progetto non ha mai misurato il **richiamo**. Precisione sì, su
campioni aggiudicati; richiamo mai. La ragione è semplice e va detta: per sapere
quante condizioni una pipeline ha *mancato* bisogna sapere quante ce n'erano, e
questo richiede che qualcuno legga i referti e le elenchi tutte.

Una diagnosi che nessuna delle tre pipeline vede è **invisibile a ogni cifra**
degli step 3, 5 e 6. Questo documento costruisce il riferimento che la rende
visibile.

---

## 1. Che cosa è, e che cosa non è

È un **riferimento annotato a mano su 25 referti**, con tutte le entità che vi
compaiono. Permette di calcolare, per ciascuna delle tre pipeline:

* **precisione** — di ciò che ha trovato, quanto è corretto;
* **richiamo** — di ciò che c'era, quanto ha trovato;
* **F1** — la loro media armonica.

**Non è una verità assoluta.** È il giudizio di **un solo annotatore**, senza un
secondo giudice e quindi senza misura di accordo fra annotatori. Su un corpus
clinico reale due annotatori esperti non concordano mai del tutto: la letteratura
sull'annotazione biomedica riporta abitualmente accordi fra 0,7 e 0,9 di kappa
anche fra professionisti. Un annotatore solo produce un riferimento **utilizzabile
e dichiarato**, non una verità.

### Il conflitto di interesse, e come è stato ridotto

Chi annota ha anche scritto le pipeline. È un conflitto reale: conoscendo il
comportamento di un metodo si può, senza volerlo, annotare in modo che lo
favorisca.

La mitigazione adottata è **l'annotazione alla cieca**: i 25 referti sono stati
letti e annotati leggendo **solo il testo grezzo**, senza aprire le uscite delle
pipeline per quei record.

**Con un'eccezione, che va dichiarata subito**: dopo aver annotato i primi cinque
referti ho lanciato la misura per verificare che il caricatore funzionasse, e ho
visto le metriche aggregate prima di annotare i venti restanti. Non ho visto le
uscite per singola menzione, e non saprei dire in che direzione avrei dovuto
spostare le annotazioni per favorire un metodo; ma la cecità non è stata
perfetta, e chi legge deve saperlo.

È comunque una mitigazione, non una soluzione: resta che le linee guida qui sotto
sono state scritte da chi conosce i tre metodi. Per questo sono state fissate
**prima** di annotare. Una passata di correzione c'è stata dopo aver visto i
disaccordi, ed è documentata per intero al § 7.

---

## 2. Il campione

25 referti estratti a caso dai 1 000, con seme `20260914`. Tutti e mille hanno il
campo Anamnesi non vuoto, quindi non c'è stata alcuna selezione preliminare.

| | mediana | media | min | max |
|---|---|---|---|---|
| corpus (1 000) | 1 664 | 2 224 | 222 | 17 590 |
| campione (25) | 1 786 | 2 260 | 502 | 6 459 |

Il campione non è distorto verso i referti corti o lunghi. Sono 56 507 caratteri
di prosa clinica.

**Solo il campo Anamnesi.** I due campi di terapia hanno già un riferimento
migliore di uno annotato a mano — il parser deterministico, che allo step 0 è
stato misurato interpretare il 99% delle voci — e annotarli sarebbe sostituire
una misura buona con una peggiore.

---

## 3. Le linee guida, fissate prima di annotare

Ogni scelta qui sotto cambia i numeri finali, quindi ciascuna è dichiarata con la
sua ragione.

### 3.1 Che cosa è una condizione

**Sì**, si annota:

* **malattie e diagnosi**, comprese quelle risolte o pregresse
  (`ipertensione arteriosa`, `pregresso ictus ischemico`);
* **sintomi e segni** (`dispnea da sforzo`, `cardiopalmo`, `astenia`);
* **reperti strumentali anomali** (`ipertrofia del ventricolo sinistro`,
  `stenosi del 50% su IVA`), perché sono l'informazione clinica su cui si
  decide;
* **fattori di rischio cardiovascolare riconosciuti** (`fumatore`, `obesità`,
  `dislipidemia`), perché nel dominio cardiologico entrano nelle scelte
  terapeutiche;
* **stati clinicamente rilevanti** (`in dialisi`, `portatore di pacemaker`).

**No**, non si annota:

* **procedure e interventi** (`appendicectomia`, `ablazione transcatetere`,
  `bypass gastrico`): sono atti, non condizioni. Quando una procedura implica
  una condizione, si annota la condizione se il referto la nomina, non la
  procedura;
* **esami con esito normale** (`spirometria nella norma`, `ecocardiogramma
  normale`): l'assenza di anomalia non è un'entità clinica;
* **misure nude senza giudizio** (`VCI 14 mm`, `intervallo PR 210 msec`): sono
  numeri, e diventano condizioni solo quando il referto li qualifica;
* **abitudini non riconosciute come fattori di rischio** (`alimentazione
  selettiva`, `vita attiva`);
* **farmaci**, che hanno un tipo loro (§ 3.2).

### 3.2 I farmaci nella prosa

Si annotano separatamente, come tipo `farmaco`. Sono clinicamente informativi
proprio perché **non stanno nei campi strutturati**: un farmaco sospeso, ridotto
o mal tollerato racconta una storia terapeutica che la terapia all'ingresso non
contiene.

Si annota il **nome della sostanza o del prodotto** come compare nel referto,
compresi i refusi, e anche quando il farmaco è nominato come allergene.

### 3.3 Confini della menzione

Si annota **il segmento più corto che identifica l'entità**, comprensivo dei
qualificatori che ne cambiano il significato clinico:

* `stenosi aortica severa` — il grado si annota, perché cambia la condotta;
* `insufficienza mitralica` e non l'intera frase che ne descrive il jet, il
  grado e le conseguenze emodinamiche — la descrizione estesa non è parte
  dell'entità;
* non si includono i marcatori di contesto (`nega`, `familiarità per`,
  `sospetta`): il loro effetto va negli attributi, non nel testo.

### 3.4 Gli attributi

* **stato**: `affermato`, `negato`, `incerto`. Una condizione esplicitamente
  esclusa si annota come `negato`, non si omette: una pipeline che la trova e la
  marca negata ha fatto la cosa giusta, e omettendola la conteremmo come falso
  positivo.
* **soggetto**: `paziente` o `familiare`. Una condizione di un parente si
  annota, marcata `familiare`.

### 3.5 Ripetizioni

Se la stessa entità compare più volte nello stesso referto, si annota **ogni
occorrenza**, perché l'allineamento avviene per sovrapposizione di caratteri e
una pipeline che le trova entrambe non va penalizzata.

---

## 4. Come si allinea una pipeline al riferimento

Stesso criterio dello step 6: **stesso ricovero, stesso campo, intervalli di
caratteri che si sovrappongono**. È l'unico criterio che non dipende da come
ciascuna pipeline sceglie i confini, che sono sistematicamente diversi.

* **vero positivo** — una menzione della pipeline si sovrappone a un'entità
  annotata dello stesso tipo;
* **falso positivo** — una menzione che non si sovrappone a nulla di annotato;
* **falso negativo** — un'entità annotata che nessuna menzione copre.

Una entità annotata può essere coperta da una sola menzione: se una pipeline ne
produce tre sovrapposte, una conta come vero positivo e due come falsi positivi.
Senza questa regola una pipeline che frammenta guadagnerebbe richiamo senza
pagarlo in precisione.

---

## 5. Il riferimento non è versionato

Le annotazioni contengono testo clinico verbatim, quindi stanno in
`data/processed/riferimento/` come tutto il resto dei dati clinici, escluso da
git. Questo documento e il codice che lo usa sono versionati; le annotazioni no.

---

## 6. Risultati

Il riferimento contiene **619 entità su 25 referti**: 559 condizioni e 60
farmaci citati nella prosa. Per stato: 542 affermate, 71 negate, 6 incerte. Per
soggetto: 596 del paziente, 23 di un familiare.

### Condizioni

| | attese | trovate | VP | FP | FN | precisione | **richiamo** | F1 |
|---|---|---|---|---|---|---|---|---|
| A | 559 | 136 | 109 | 27 | 450 | 80,1% | **19,5%** | 31,4% |
| B | 559 | 408 | 392 | 16 | 167 | **96,1%** | **70,1%** | **81,1%** |
| C | 559 | 136 | 111 | 25 | 448 | 81,6% | **19,9%** | 31,9% |

**Le due pipeline simboliche mancano quattro condizioni su cinque.** È il numero
che mancava a questo progetto, e ribalta la lettura di tutto lo step 6.

La ragione è strutturale e non è un difetto di implementazione: il vocabolario
della pipeline A è costruito dai termini ICD-10, e la pipeline C è addestrata
sulle etichette silver che A produce. Entrambe possono trovare **solo ciò che è
già nella knowledge base**. Nella prosa cardiologica reale la maggior parte delle
condizioni non è scritta in forma da nomenclatura:

```
ipertrofia del ventricolo sinistro
insufficienza paraprotesica
steno-insufficienza aortica reumatica
extrasistolia polimorfa ad alta incidenza
```

Nessuna di queste è un termine ICD, e nessuna delle due pipeline le vede. La
copertura ICD del 99,4% di A, che nello step 6 sembrava un punto di forza, si
rivela ora esattamente il sintomo del problema: **il suo denominatore è ristretto
a ciò che il vocabolario già conosce**, e quel vocabolario copre un quinto della
realtà clinica.

### Farmaci citati nella prosa

| | attese | trovate | VP | FP | FN | precisione | **richiamo** | F1 |
|---|---|---|---|---|---|---|---|---|
| A | 60 | 41 | 39 | 2 | 21 | 95,1% | 65,0% | 77,2% |
| B | 60 | **0** | 0 | 0 | 60 | **0,0%** | **0,0%** | **0,0%** |
| C | 60 | 44 | 42 | 2 | 18 | 95,5% | **70,0%** | **80,8%** |

Il quadro si **ribalta esattamente**: la pipeline B non trova nessuno dei 60
farmaci citati nella prosa. Si concentra sui campi di terapia, dove arriva al
99,6%, e nell'anamnesi non ne segnala. Sono farmaci che raccontano la storia
terapeutica — sospensioni, riduzioni, intolleranze — e che i campi strutturati
non contengono per definizione, perché quelli elencano ciò che il paziente assume
*ora*.

> **Questo zero è stato messo in dubbio, indagato, e si è rivelato causato da una
> mia istruzione.** La causa e la correzione stanno nel § 8; questa sezione
> conserva la misura come è stata prodotta, perché è quella che ha portato alla
> scoperta. Il numero da citare per la pipeline B sui farmaci narrati **non è
> questo zero**: è l'86,7% del § 8.

I vocabolari di farmaci, a differenza di quelli di condizioni, funzionano: sono
liste chiuse di nomi commerciali e principi attivi, e un nome di farmaco è un
nome, non una descrizione. C riconosce anche i refusi del referto
(`clopidrogrel`, `rivaroxabn`, `Macintentan`), cosa che un gazetteer non può fare.

### La conclusione che ne viene

**Nessuna pipeline vince, e adesso si sa perché in modo preciso**: sono
complementari su assi diversi.

| | condizioni | farmaci nella prosa |
|---|---|---|
| A e C | F1 ≈ 31% | F1 ≈ 79% |
| B, come misurata qui | F1 = 81% | F1 = 0% |
| B, dopo la correzione del § 8 | F1 = 80% | F1 = 87% |

Sulle **condizioni** la complementarità resta il fatto centrale, e non dipende da
nulla che sia stato corretto dopo: A e C mancano quattro condizioni su cinque
perché il loro vocabolario è la loro definizione di realtà clinica, e nessuna
correzione di prompt cambia questo.

Sui **farmaci narrati** la conclusione è cambiata. Si legga il § 8: la
complementarità che questa tabella mostrava era in parte un difetto delle mie
istruzioni, non una proprietà dei metodi.

La decisione dello step 7 — costruire il knowledge graph da **tutte e tre le
pipeline, con la provenienza** — resta giustificata, ma da un argomento più
solido di quello che avevo scritto qui: non «una pipeline copre ciò che l'altra
non vede», che era in parte un artefatto, ma **le condizioni**, dove il divario
fra 70% e 20% di richiamo è strutturale e misurato due volte.

### Un controllo indipendente che torna

La precisione di B sulle condizioni misurata qui, **96,1%**, si confronta con il
**91,7% ± 3,6** ottenuto allo step 6 aggiudicando 60 menzioni esclusive. Sono due
misure diverse su insiemi diversi — qui tutte le menzioni sui 25 referti, là solo
le esclusive sul corpus — e cadono dentro un paio di punti l'una dall'altra. Non
è una prova, ma è la corroborazione che ci si può permettere senza un secondo
annotatore.

---

## 7. Una seconda passata sui disaccordi, e perché va dichiarata

Alla prima misura B aveva **25 falsi positivi**. Leggendoli uno per uno, **nove
erano miei errori di annotazione**, non errori di B:

```
«intraprotesica di grado lieve»                        l'avevo saltata perche' ellittica
«MAV»                                                  condizione vera, non annotata
«emorragia cerebrale post-traumatica»                  condizione vera, non annotata
«ipomobilita e fusione delle cuspidi aortiche»         reperto valvolare, non annotato
«SARS CoV2»                                            infezione vera, non annotata
«malattia ostruttiva cronica del circonflesso»         annotata solo per la coronaria destra
«laparocele», «insufficienza respiratoria ipercapnica», «angor»
                                                       annotate con un indice troppo stretto
```

Il riferimento è stato corretto **solo** dove le linee guida del § 3, fissate
prima di annotare, dicono senza ambiguità che l'entità andava annotata. Dove il
disaccordo era un giudizio opinabile — `Protesi ginocchio bilateralmente` è uno
stato clinicamente rilevante? `controllo glucidico altalenante` è una condizione?
— **il riferimento non è stato toccato**, e quelle restano contate come errori di
B.

L'effetto della correzione: la precisione di B sulle condizioni passa da 93,9% a
96,1%, il richiamo da 69,8% a 70,1%.

**Questa passata è il punto più fragile del documento e va letta come tale.**
Correggere il riferimento dopo aver visto le uscite di una pipeline è
metodologicamente compromettente, e ho lasciato le correzioni tracciabili una per
una proprio per questo. La difesa è che le regole applicate erano scritte prima,
non dopo; il limite è che sono io ad averle applicate.

Un riferimento costruito bene richiederebbe due annotatori indipendenti, una
misura del loro accordo, e un terzo che scioglie i disaccordi. Questo ne ha uno.

### Il resto dei limiti

* **Un solo annotatore**, che ha anche scritto le pipeline. La mitigazione —
  annotare alla cieca, leggendo solo il testo grezzo — è stata seguita per tutti
  e 25 i referti, con **un'eccezione dichiarata**: dopo i primi cinque ho lanciato
  la misura e visto le metriche aggregate, prima di annotare i venti restanti. Non
  ho visto le uscite per singola menzione, ma la cecità non è stata perfetta.
* **25 referti su 1 000.** Con 559 condizioni l'errore standard sul richiamo è di
  circa 2 punti, quindi il divario fra 20% e 70% non è in discussione; le
  differenze fra A e C (19,5% contro 19,9%) invece sono rumore.
* **Solo il campo Anamnesi**, e solo i tipi condizione e farmaco. Gli attributi —
  stato e soggetto — sono annotati ma non ancora misurati contro il riferimento:
  è il passo naturale successivo.
* **Il riferimento non è una verità**, è un giudizio dichiarato. Ogni numero di
  questo documento va letto come «rispetto a come *io* ho letto questi 25
  referti».

---

## 8. Lo zero sui farmaci non era del modello: era mio

Il § 6 riportava che la pipeline B non trovava **nessuno** dei 60 farmaci citati
nella prosa. Uno zero secco è la cifra che un lettore attento mette in dubbio per
prima, e messo in dubbio si è sciolto. Questa sezione racconta l'indagine per
intero, perché il metodo conta più del numero.

### 8.1 Lo zero non era una cecità: era un campionamento

La prima cosa da fare davanti a uno zero non è spiegarlo, è **cercare il fenomeno
altrove**. Nei risultati grezzi della corsa da 1 000 record la pipeline B produce
62 farmaci con `campo_sorgente` uguale ad `Anamnesi`, in **20 referti su 1 000**,
tutti ancorati al testo, e sono corretti: nomi commerciali, principi attivi, un
refuso del referto conservato come tale, uno marcato `negato`.

Quindi il tasso non era nullo, era **0,062 farmaci narrati per referto**. Con un
tasso del 2% di referti coinvolti, la probabilità di vederne zero su 25 è
`0,98²⁵ = 60%`. **Lo zero misurato era l'esito più probabile del campione**, non
una proprietà del metodo. Detto in termini di intervallo: zero successi su 60
osservazioni dà un limite superiore al 95% del **6,0%**, e il tasso misurato sul
corpus intero pone il tetto vero a circa **2,6%** del richiamo. La conclusione
corretta era «richiamo nei bassi singoli punti percentuali», non «zero».

### 8.2 La causa era nelle mie istruzioni

La REGOLA 7 del prompt si intitolava *«FARMACI: TUTTE LE SEZIONI, NON UNA SOLA»* e
definiva i farmaci come il contenuto delle **due sezioni di terapia**. Il suo
esempio era una riga di terapia; la sua lista di controllo finale chiedeva al
modello di verificare che per ogni sezione `###` di terapia ci fosse almeno una
voce. Da nessuna parte diceva che la prosa dell'anamnesi contiene farmaci.

Il modello faceva **esattamente ciò che gli era stato chiesto**. Il 2% di referti
in cui trovava farmaci narrati era il modello che deviava dalle istruzioni, non
che le seguiva.

È la **seconda volta** nel progetto che un difetto attribuito al modello si è
rivelato un difetto del prompt, e le due volte sono opposte e simmetriche:

| | difetto | causa |
|---|---|---|
| `mdc` (§ 7nonies di `docs/04`) | il modello **inventava** un'allergia 150 volte | un esempio positivo nel prompt, copiato come contenuto |
| farmaci narrati (qui) | il modello **ometteva** un'intera categoria | una regola che definiva la categoria in modo troppo stretto |

La lezione comune: **il prompt è codice, e le sue omissioni sono bug quanto le sue
affermazioni.** Un esempio positivo è un modello da copiare; una definizione
ristretta è un filtro che esclude.

### 8.3 La correzione, e la sua verifica

Ho aggiunto una **REGOLA 7bis** che dice che i farmaci nominati nella prosa
dell'anamnesi vanno estratti con `campo` `Anamnesi`, che un farmaco sospeso o
rifiutato si estrae comunque e la differenza va in `stato`, e che un farmaco
nominato come allergene appartiene a entrambe le liste. Applicando la lezione di
`mdc`, la regola **non contiene alcun esempio positivo con una sostanza vera**:
solo tre casi `SBAGLIATO`, che nella prima vicenda non hanno mai perso contenuto
nell'uscita.

Rifare il corpus intero sarebbe costato circa 3 dollari. Rifare i **soli 25
referti del riferimento** è costato **0,079 dollari** e risponde alla stessa
domanda, così ho aggiunto a `extract_b.py` l'opzione `--solo`, che elabora una
lista di identificativi invece di campionare.

La corsa è stata fatta **due volte**, perché fra la prima e la seconda ho dovuto
ripulire il prompt da sette esempi che citavano testo clinico verbatim (§ 8.8).
Entrambe sono riportate: la seconda è quella prodotta dal prompt che il
repository contiene davvero.

| farmaci nella prosa | attese | trovate | VP | FP | FN | precisione | **richiamo** | F1 |
|---|---|---|---|---|---|---|---|---|
| A | 60 | 41 | 39 | 2 | 21 | 95,1% | 65,0% | 77,2% |
| B, senza la 7bis | 60 | 0 | 0 | 0 | 60 | 0,0% | 0,0% | 0,0% |
| B, con la 7bis, prima corsa | 60 | 59 | 52 | 7 | 8 | 88,1% | 86,7% | 87,4% |
| **B, con la 7bis, prompt committato** | 60 | 55 | 50 | 5 | 10 | 90,9% | **83,3%** | **87,0%** |
| C | 60 | 44 | 42 | 2 | 18 | 95,5% | 70,0% | 80,8% |

Da 0,0% a circa **85%** di richiamo, con una regola di prompt, e le due corse
concordano entro tre punti. Ed è il miglior F1 delle tre pipeline anche sui
farmaci, non solo sulle condizioni.

### 8.4 Perché questo numero è ottimistico, e il controllo che lo sostiene

**L'86,7% è misurato sugli stessi 25 referti che hanno rivelato il problema.** È
la definizione di misurare sull'insieme su cui si è aggiustato, e va detto prima
di qualunque altra cosa. La regola non contiene nulla di specifico a quei 25
referti, ma la scelta di scriverla viene da loro.

Il controllo possibile senza annotare altro: **30 referti diversi**, scelti fra
quelli della corsa da 1 000 esclusi i 25 del riferimento, con seme dichiarato
(`20260914`), a 0,088 dollari.

| sugli stessi 30 referti | farmaci narrati | per referto | referti coinvolti | non ancorati |
|---|---|---|---|---|
| corsa senza la 7bis | 0 | 0,00 | 0/30 | 0 |
| corsa con la 7bis | 90 | 3,00 | 19/30 | 0 |
| *atteso dal riferimento* | | *2,40* | | |

Il comportamento generalizza: su referti che non hanno avuto parte nella diagnosi
il tasso passa da zero a **3,00 per referto**, contro i 2,40 che il riferimento
dichiara. Tutte ancorate: nessun nome inventato. Questo non misura il richiamo su
quei 30 — non sono annotati — ma esclude l'ipotesi che la regola funzioni solo
dove è stata concepita.

Il 3,00 contro 2,40 è **sopra** il vero, e il § 8.5 dice perché.

### 8.5 Una crepa nelle linee guida, che l'indagine ha scoperto

I 7 falsi positivi di B non sono un errore del modello. Quattro di essi sono
termini di **classe** e non di sostanza: un diuretico, uno steroide, «terapia
antibiotica». Uno è un farmaco nominato come allergene, che il § 3.2 dice di
annotare e che io avevo saltato — lo stesso tipo di mio errore già trovato nel
§ 7. Due sono lo stesso farmaco citato due volte con confini diversi, e la regola
di copertura unica li fa pagare in precisione, come è giusto.

Ma il riferimento contiene **anch'esso** termini di classe fra i farmaci —
`diuretici`, `FANS`, `NAO`, `EBPM`, `folati` — e questo significa che

> **il § 3.2 non decide se una classe di farmaci sia un farmaco, e io ho
> annotato in modo incoerente.**

È un difetto delle linee guida, non di una pipeline, e tocca tutte e tre. Tre
degli 8 mancati di B sono anch'essi classi. Sotto una lettura coerente che
includa le classi la precisione di B sui farmaci starebbe fra l'88,1% misurato e
circa il 95%, e il richiamo fra l'86,7% e circa il 92% — ma cambierebbe anche i
numeri di A e C.

**Non ho corretto il riferimento.** Aggiungere al riferimento, dopo aver visto i
disaccordi, proprio le entità che trasformano i falsi positivi di una pipeline in
veri positivi è il modo più diretto di fabbricare un buon risultato. La crepa
resta dichiarata qui, il numero resta l'88,1%, e la decisione su come trattare le
classi appartiene a una revisione delle linee guida fatta **prima** di rimisurare.

### 8.6 Il prezzo sulle condizioni era rumore, e ora si sa quanto vale il rumore

Nella prima corsa con la 7bis il richiamo sulle condizioni scendeva da **70,1% a
68,2%**, e la lettura naturale era che la regola nuova distraesse il modello dalle
condizioni. Guardando le singole entità la regressione non era però ordinata:
**23 condizioni perse e 12 guadagnate**, senza schema riconoscibile.

La ripulitura del prompt ha reso disponibile una terza corsa, e la terza corsa
smentisce quella lettura:

| condizioni | VP | precisione | **richiamo** |
|---|---|---|---|
| senza la 7bis | 392 | 96,1% | **70,1%** |
| con la 7bis, prima corsa | 381 | 95,7% | **68,2%** |
| con la 7bis, prompt committato | 392 | 95,1% | **70,1%** |

La regola non costa richiamo sulle condizioni: due corse su tre danno lo stesso
numero, e la terza sta due punti sotto. Quello che si è misurato non è l'effetto
della regola, è il **rumore fra corse dello stesso modello sugli stessi record**,
e vale circa **due punti di richiamo**.

È un numero utile molto oltre questo paragrafo, perché è il **pavimento di rumore
di ogni misura del progetto** che passi da questo modello. Detto altrimenti:
nessuna differenza inferiore a due punti fra due corse della pipeline B va letta
come un effetto di qualcosa. La distanza fra 20% e 70% sulle condizioni resta di
un ordine di grandezza oltre il rumore; la distanza fra A e C (19,5% contro
19,9%), che il § 7 chiamava rumore per via dell'errore di campionamento, lo è
adesso per due motivi indipendenti.

### 8.7 Che cosa resta in sospeso

La correzione è verificata su 55 referti ma il corpus dello step 6 è ancora
prodotto **senza** la REGOLA 7bis. Rifarlo costa circa **3,03 dollari**, misurati
sul costo reale per record di queste due corse, e il budget residuo è inferiore:
è una decisione di spesa, non tecnica. Fino a quel momento valgono due cose
insieme, e il documento le tiene entrambe: i numeri dello step 6 descrivono la
corsa senza la 7bis, e il § 8.3 descrive di quanto quella corsa sottostimi la
pipeline B sui farmaci narrati.
