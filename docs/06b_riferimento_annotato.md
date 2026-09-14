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

Il quadro si **ribalta esattamente**. La pipeline B non trova **nemmeno un**
farmaco citato nella prosa: si concentra sui campi di terapia, dove arriva al
99,6%, e nell'anamnesi non ne segnala. Sono farmaci che raccontano la storia
terapeutica — sospensioni, riduzioni, intolleranze — e che i campi strutturati
non contengono per definizione, perché quelli elencano ciò che il paziente assume
*ora*.

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
| B | F1 = 81% | F1 = 0% |

La decisione dello step 7 — costruire il knowledge graph da **tutte e tre le
pipeline, con la provenienza** — non è più una scelta di prudenza: è l'unica che
non butti via metà dell'informazione. Usare una pipeline sola significherebbe
perdere l'80% delle condizioni oppure il 100% dei farmaci narrati.

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
