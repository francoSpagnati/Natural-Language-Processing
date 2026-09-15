# Step 9 — I tre ranker: che cosa proporre, e in che ordine

Il filtro dello step 8 dice che cosa **non** si può dare. Su 5 863 prescrizioni
reali ne ha vietate quattro, quindi da solo lascia passare quasi tutto: è una
rete di sicurezza, non un suggeritore. Lo step 9 è lo strato che ordina ciò che
il filtro lascia passare.

Codice: [`src/ranker.py`](../src/ranker.py),
[`src/valuta_ranker.py`](../src/valuta_ranker.py).
Test: [`tests/test_ranker.py`](../tests/test_ranker.py).

---

## 1. Il bersaglio è gratuito, ed è il primo risultato dello step

La verità di riferimento non va annotata: **è già nei dati.** La terapia alla
dimissione è la decisione che un cardiologo ha davvero preso per quel paziente,
scritta nel referto. Su 1 000 ricoveri, **841** ne hanno una codificata.

È la stessa proprietà che allo step 7 ha permesso di misurare il parser
deterministico contro il campo stesso — *un campo con delimitatori è la propria
verità* — applicata qui a un compito di raccomandazione. La conseguenza pratica
è che lo step 9 misura su 841 ricoveri invece che sui 25 del riferimento
annotato a mano, e che nessuno ha dovuto decidere a mano che cosa fosse giusto.

### Il limite di questa verità, detto prima dei numeri

Il riferimento è **una** decisione giusta, non **l'insieme** delle decisioni
giuste. Una classe proposta e non prescritta non è per forza un errore: può
essere una terapia corretta che quel medico non ha scelto, o che il paziente non
tollerava per una ragione che il referto non scrive.

Ne segue che **il richiamo è la metrica che conta e la precisione va letta con
cautela.** Un supporto alla decisione si giudica da ciò che *non* suggerisce.

---

## 2. L'unità della raccomandazione: la classe, non la molecola

Le raccomandazioni sono classi ATC di **livello 4**, cinque caratteri:

| codice | classe |
|---|---|
| `C07AB` | betabloccanti, selettivi |
| `C03DA` | antagonisti dell'aldosterone |
| `B01AF` | inibitori del fattore Xa diretto |
| `A10BK` | inibitori del co-trasportatore SGLT-2 |

È il livello a cui le linee guida nominano i farmaci: l'ESC raccomanda «un
betabloccante», non «bisoprololo 2,5 mg». Scegliere fra venti betabloccanti
sostanzialmente intercambiabili è una decisione di prontuario, e misurarla come
se fosse clinica misurerebbe rumore.

---

## 3. I due compiti

**Compito 1 — la terapia completa.** Prevedere l'intero insieme di classi alla
dimissione. Esiste per una sola ragione: mostrare che è quasi risolto senza
ragionare.

**Compito 2 — le aggiunte.** Prevedere le sole classi **nuove**, quelle che il
ricovero ha aggiunto. 2 075 decisioni su 841 ricoveri, 2,47 per ricovero. È il
compito vero.

### La linea di base che tiene onesto tutto lo step

Misurato sul corpus, a livello di classe ATC4:

```
classi alla dimissione per ricovero        6,78
  già presenti all'ingresso (continuate)  63,6%   3 627
  nuove, decise durante il ricovero       36,4%   2 075
  sospese durante il ricovero                       970
```

**Un ranker che azzecca il 63% della terapia di dimissione non ha imparato
nulla**: copiare la terapia in atto lo ottiene gratis. Senza questo numero un
risultato del 65% sembrerebbe buono.

---

## 4. Il tetto del ranker simbolico, noto *prima* di misurarlo

Una misura fatta prima di scrivere una sola regola:

> Il **40,4%** delle prescrizioni di dimissione, e il **41,7%** delle sole
> aggiunte, **non è cardiovascolare.**

| classe | prescrizioni | di cui nuove | |
|---|---|---|---|
| `A02BC` | 525 | 209 | inibitori di pompa protonica |
| `A10BK` | 225 | 65 | inibitori SGLT-2 |
| `M04AA` | 113 | 11 | allopurinolo |
| `H03AA` | 110 | 6 | levotiroxina |
| `G04CA` | 100 | 27 | alfa-bloccanti urologici |
| `B03BB` | 94 | 46 | acido folico |
| `A12BA` | 72 | 52 | potassio |
| `D07AC` | 59 | 59 | corticosteroidi topici |

Un ranker costruito sulle linee guida cardiologiche **non può proporre queste
classi**, e il suo richiamo ha perciò un tetto intorno al 60% per costruzione.

**Non ho colmato quel divario inventando regole fuori dal dominio in cui ho una
fonte citabile**: sarebbe stata conoscenza di un modello linguistico travestita
da linea guida, esattamente ciò che il vincolo di provenienza del progetto
vieta. Il divario resta, misurato, ed è ciò che il ranker ibrido deve chiudere
imparandolo dai dati.

È la stessa forma del risultato dello step 6: il richiamo della pipeline A era
limitato dal **denominatore della sua base di conoscenza**, non dal suo
algoritmo. Qui il limite del ranker simbolico è il perimetro delle linee guida
che lo alimentano.

---

## 5. Le indicazioni cliniche

Stessa disciplina delle controindicazioni dello step 8: **ogni riga porta la
fonte**, e la fonte è un documento pubblicato. 27 indicazioni, con la
classe di raccomandazione ESC (I, IIa, IIb).

La granularità della citazione è **documento + sezione**, deliberatamente non la
pagina: la trascrizione dalle tabelle di raccomandazione è manuale, e un numero
di pagina non verificabile sarebbe una precisione falsa.

| condizione | classe proposta | racc. | fonte |
|---|---|---|---|
| `I50` scompenso | `C09A` ACE-inibitore | I | ESC 2021 HF |
| `I50` | `C07AB` betabloccante | I | ESC 2021 HF |
| `I50` | `C03DA` antialdosteronico | I | ESC 2021 HF |
| `I50` | `A10BK` SGLT2-inibitore | I | ESC 2023, aggiornamento HF |
| `I48` fibrillazione | `B01AF` anticoagulante diretto | I | ESC 2024 AF |
| `I48` | `B01AA` antagonista vit. K | IIa | ESC 2024 AF |
| `I10` ipertensione | `C09AA` / `C09CA` / `C08CA` / `C03AA` | I | ESC/ESH 2024 |
| `I20`–`I25`, `I70` | `C10AA` statina | I | ESC/EAS 2019 dislipidemie |
| `I20`–`I25`, `I70` | `B01AC` antiaggregante | I | ESC 2024 CCS |
| `E11` + malattia CV | `A10BK` / `A10BJ` | I | ESC 2023 diabete |
| `N18` malattia renale | `A10BK` | I | ESC 2023 diabete, sez. renale |
| *terapia con* `B01A` | `A02BC` gastroprotettore | IIa | ESC 2023 ACS / 2024 AF |

### Un'indicazione può essere innescata da una terapia, non da una diagnosi

L'ultima riga è di forma diversa dalle altre e ha richiesto un campo apposta nel
modello dati (`atc_richiesto`). **La gastroprotezione non è indicata da una
malattia: è indicata dall'antitrombotico che il paziente sta prendendo.** Senza
quel campo la regola non sarebbe esprimibile, e `A02BC` — la seconda classe più
prescritta dell'intero corpus — resterebbe fuori dal ranker simbolico.

### Il principio del fatto mancante, di nuovo

5 delle 27 indicazioni portano un campo `fatto_non_estratto`, per la
stessa ragione dello step 8: la linea guida decide su un fatto che il sistema
non sa stabilire.

- I quattro pilastri dello scompenso valgono per l'**HFrEF**, cioè per la
  frazione di eiezione ridotta. **Nessuna pipeline estrae la frazione di
  eiezione**, quindi `HFrEF` e `HFpEF` non sono distinguibili e le regole
  valgono per `I50` nel suo insieme.
- L'anticoagulazione nella fibrillazione atriale dipende dal punteggio
  CHA₂DS₂-VA, che richiede **età e sesso** — non nello schema.
- L'associazione con ezetimibe si aggiunge quando il colesterolo LDL non è
  all'obiettivo: **il valore di laboratorio non è nello schema.**

Qui, a differenza dello step 8, il fatto mancante non declassa un divieto:
declassa una raccomandazione da certa a plausibile. La differenza è che un
suggerimento sbagliato è meno grave di un divieto sbagliato — ma il fatto che
manca è lo stesso, ed è la terza volta nel progetto che la stessa lacuna si
presenta in un punto diverso della catena.

---

## 6. I tre ranker

| ranker | come decide | che cosa gli serve | costo |
|---|---|---|---|
| **simbolico** | indicazione citata, peso = classe di raccomandazione | le 27 indicazioni | nessuno |
| **ibrido** | indicazione + co-occorrenza misurata | le regole + i casi di addestramento | nessuno |
| **con modello** | un modello linguistico ordina i candidati | inferenza | locale gratis / remoto misurato al §9 |

Più due linee di base: **continuità** (copia la terapia in atto) e
**frequenza** (proponi ciò che si aggiunge più spesso, ignorando il paziente).

### Il simbolico: il massimo, non la somma

Il punteggio di una classe è il peso della **migliore** indicazione che la
sostiene. Sommare premierebbe le classi che compaiono in molte linee guida
invece di quelle fortemente raccomandate per *questo* paziente: tre ragioni di
classe IIa non fanno una classe I.

### L'ibrido, e un errore che ha dovuto essere corretto

La prima versione ordinava per **informazione mutua puntuale** — di quanto una
condizione rende una classe più probabile del solito — e il risultato è stato
che l'ibrido andava **peggio della linea di base di frequenza**: richiamo@5
sulle aggiunte 26,3% contro 49,5%.

La causa non era un difetto di implementazione ma di grandezza misurata. La PMI
è un **guadagno**: una classe aggiunta a metà dei pazienti qualunque sia la loro
malattia ha PMI vicina a zero, perché nessuna condizione la rende più attesa di
quanto già non sia. Ordinare per PMI mette in cima le classi *specifiche* e in
fondo quelle *probabili*, mentre la domanda del compito è quale classe verrà
aggiunta — cioè una probabilità, non un guadagno.

La correzione è lavorare in spazio logaritmico e sommare:

```
log P(classe | condizione) = log P(classe) + PMI(condizione, classe)
                             └── il ranker   └── ciò che l'ibrido
                                di frequenza     aggiunge
```

Così **l'ibrido non può fare peggio della frequenza per costruzione**: in
assenza di evidenza sulla condizione la PMI è zero e il punteggio ricade sulla
frequenza. È una proprietà, non una speranza, e un test la fissa
(`test_a_peso_zero_non_fa_peggio_della_frequenza`).

### Il peso delle linee guida, tarato dove si deve

Quanto pesa una raccomandazione ESC rispetto all'abitudine misurata è un
parametro, e **è stato scelto su una parte di validazione ritagliata
dall'addestramento, mai sulla prova**:

| peso | richiamo@3 | richiamo@5 | richiamo@10 | MAP |
|---|---|---|---|---|
| 0,00 | 28,3% | 43,0% | 62,4% | 0,393 |
| 0,25 | 31,2% | 43,3% | 63,4% | **0,396** |
| **0,50** | 30,6% | 43,1% | 66,1% | 0,382 |
| 1,00 | **31,2%** | **43,9%** | **66,2%** | 0,373 |
| 2,00 | 25,5% | 39,5% | 61,0% | 0,338 |
| 8,00 | 22,2% | 33,3% | 56,8% | 0,297 |

La curva è piatta fra 0,25 e 1,0 — dentro il pavimento di rumore del progetto —
e cala nettamente sopra: a peso 8 la linea guida sovrasta il dato e il ranker
smette di sapere che in questo reparto si prescrivono gastroprotettori. Scelto
**0,5**.

Il numero che conta in questa tabella è il primo: **a peso zero — sola
statistica, nessuna linea guida — il richiamo@3 è 28,3% contro il 31,2%
dell'ottimo.** Le linee guida aggiungono qualcosa, ma poco. È un risultato dello
step 9, non un difetto della taratura.

---

## 7. Il risultato

597 ricoveri di addestramento, **244 di prova**, 91 classi candidate, divisione
deterministica per `enc_oid` — rieseguire la valutazione deve dare gli stessi
insiemi, altrimenti la differenza fra due corse confonde il metodo con la
divisione.

L'insieme candidato è costruito **solo** sui casi di addestramento: prenderlo
dal corpus intero farebbe entrare le classi presenti solo nella prova e
gonfierebbe il richiamo. Il prezzo è un tetto, che va riportato perché nessun
ranker può superarlo: **96,3%** sulla terapia completa, **95,5%** sulle aggiunte.

I ricoveri che hanno effettivamente un bersaglio sono **243** sul compito 1 e
**196** sul compito 2 — 48 ricoveri di prova non hanno aggiunte dentro
l'insieme candidato, e contarli come fallimenti misurerebbe l'assenza di una
domanda invece della qualità di una risposta.

### Compito 1 — la terapia completa

| ranker | ric@3 | ric@5 | ric@10 | MAP |
|---|---|---|---|---|
| **continuità della terapia** | **40,5%** | **56,4%** | **67,0%** | **0,656** |
| frequenza | 26,4% | 40,9% | 56,5% | 0,467 |
| simbolico | 18,2% | 26,1% | 36,7% | 0,317 |
| ibrido | 23,8% | 36,0% | 54,7% | 0,451 |

**Il compito 1 è vinto dalla linea di base banale, e questo è il risultato del
compito 1.** Nessun ragionamento clinico batte «continua ciò che il paziente
già prendeva», perché due terzi della terapia di dimissione *sono* la terapia
d'ingresso.

### Compito 2 — le sole aggiunte

| ranker | ric@3 | ric@5 | ric@10 | prec@5 | MAP |
|---|---|---|---|---|---|
| continuità | 10,4% | 11,7% | 12,5% | 6,9% | 0,114 |
| frequenza | 36,8% | 49,5% | 67,2% | 27,9% | 0,426 |
| simbolico | 20,3% | 28,0% | 31,0% | 15,1% | 0,210 |
| **ibrido** | **38,8%** | **53,1%** | **70,2%** | 27,7% | **0,456** |

Tre letture, in ordine di importanza:

1. **L'ibrido batte la frequenza su tutte e cinque le metriche.** I margini sono
   piccoli — da 2 a 3,6 punti, cioè al limite del pavimento di rumore — ma sono
   **coerenti**, e cinque margini nella stessa direzione dicono più di uno solo.

2. **Il simbolico da solo perde contro un ranker che non guarda il paziente.**
   28,0% contro 49,5% a k=5. Non è sorprendente dato il tetto del §4, ma va
   detto chiaramente: *le linee guida cardiologiche, da sole, sono un ranker
   peggiore del sapere quali farmaci si prescrivono in questo reparto.*

3. **La continuità crolla a 11,7%**, come deve. È la verifica che il compito 2
   misura davvero qualcosa di diverso dal compito 1.

Il ranker con modello linguistico ha una sezione propria — il §9 — perché il suo
risultato richiede di spiegare anche *come* il modello sbaglia, non solo quanto.
Anticipazione: **perde contro il ranker di frequenza**, e per la ragione del §4.

### Il simbolico perde anche quando ha ragione

Un ricovero di prova, `enc_oid` 10083543 — fibrillazione atriale parossistica
(`I48`, `I48.0`), aterosclerosi (`I70`), dispnea — già in terapia con
anticoagulante diretto, antiaritmico e betabloccante.

Il medico ha aggiunto: `B01AX` altri antitrombotici, `C09CA` sartano, `C10BA`
statina **in associazione**.

Le prime due proposte del ranker simbolico:

```
1. B01AC  antiaggreganti piastrinici        classe I — aterosclerosi
2. C10AA  inibitori della HMG-CoA riduttasi classe I — aterosclerosi
```

Entrambe sono clinicamente corrette. Entrambe contano come errori, perché il
medico ha prescritto `C10BA` (statina **in associazione** con ezetimibe) e non
`C10AA` (statina semplice). **Il ranker ha proposto una statina e il medico ha
prescritto una statina, e la misura lo conta come sbagliato.**

Quanto costa questo artefatto, misurato risalendo la gerarchia ATC
(micro-media sulle prescrizioni, richiamo@5 sulle aggiunte):

| ranker | ATC4 esatto | ATC3 | ATC2 |
|---|---|---|---|
| simbolico | 25,1% | 29,2% | 30,7% |
| frequenza | 46,3% | 52,8% | 53,1% |
| ibrido | 46,0% | 52,0% | **56,9%** |

Allargare di un solo livello vale **da 4 a 7 punti**. È la motivazione diretta
della metrica gerarchica dello step 11: due terapie della stessa famiglia non
sono un errore quanto due terapie di famiglie diverse.

---

## 8. Il filtro dello step 8 non toglie niente, e la ragione è corretta

Avevo scritto che lo step 8 e lo step 9 «si incastrano»: il filtro decide che
cosa è ammissibile, il ranker ordina ciò che resta. **La misura lo ha
smentito.** Sui 244 ricoveri di prova il filtro esclude *zero* classi, per
nessun paziente.

Verificato una causa alla volta:

1. **I due step parlano a livelli diversi dell'ATC.** Il filtro giudica un
   *farmaco* (sette caratteri), il ranker propone una *classe* (cinque). La
   regola sulla metformina, `A10BA02`, non può toccare nessuna classe
   candidata, e non è un difetto: la metformina è controindicata
   nell'insufficienza renale grave, gli altri antidiabetici orali no.

2. **Le allergie codificate sono 57 in 841 ricoveri**, tutte a livello di
   sostanza. Per uguaglianza esatta non incontrano mai una classe. È anche un
   numero che vale la pena guardare: **il 93% dei ricoveri non ha nessuna
   allergia con un codice ATC**, e la rete di sicurezza è tesa su pochissimi
   fatti.

3. **Le due regole che avrebbero potuto scattare sono state declassate dallo
   step 8 stesso**, dal principio del fatto mancante — il betabloccante nel
   blocco atrioventricolare (5 pazienti di prova) e l'antitrombotico
   nell'emorragia intracranica (1). Entrambe emettono `da_verificare`, quindi
   non escludono. Il principio era giusto allo step 8 e resta giusto qui; la
   sua conseguenza è che il filtro, al livello di classe, tace.

### Perché il prefisso non è la soluzione, misurato

Ho provato a far incontrare i due livelli confrontando l'allergia per
**prefisso di classe**: un'allergia al ramipril `C09AA05` escluderebbe la classe
`C09AA`. Sembra difendibile — tosse e angioedema da ACE-inibitore *sono* effetti
di classe. Toglieva 14 candidati a 12 pazienti.

Il primo caso aperto ha chiuso la questione:

> Paziente allergico all'**acido acetilsalicilico** (`B01AC06`). Il medico gli
> ha prescritto **clopidogrel** (`B01AC04`) — stessa classe `B01AC`.

Il clopidogrel è *precisamente* l'alternativa corretta per un allergico
all'aspirina, e il blocco per prefisso gliela negava. **È la terza volta nel
progetto che una regola di sicurezza troppo larga nega una terapia corretta
invece di proteggere**, dopo i betabloccanti col pacemaker e gli antitrombotici
nell'emorragia remota.

La forma corretta è allora la stessa dello step 8, applicata a un livello più
basso: al livello di classe l'allergia a una sostanza è un **avvertimento**, non
un divieto. `allerta_di_classe` produce 14 avvertimenti sui 244 ricoveri, e la
raccomandazione li porta con sé:

```
B01AC  antiaggreganti piastrinici
       classe I: antiaggregante nella malattia aterosclerotica accertata.
       ATTENZIONE: allergia dichiarata a una sostanza di questa classe
       (B01AC06): scegliere un'altra molecola.
```

Il medico riceve la raccomandazione giusta *e* l'informazione che dentro quella
classe c'è una molecola da evitare. Nessuna delle due gli viene nascosta.

---

## 9. Il ranker con modello linguistico

### Il vincolo all'insieme candidato è un requisito di sicurezza, e serve

Alla prima prova, su un paziente con fibrillazione atriale, il modello ha
prodotto **nove codici da un elenco di otto candidati** — il nono copiato dalla
riga della terapia in atto. Un codice fuori elenco è un farmaco che il filtro
dello step 8 non ha mai ammesso: se il ranker potesse nominarlo, scavalcherebbe
l'unico strato che decide che cosa sia ammissibile.

Sulla corsa completa il vincolo è scattato **18 volte su 244 ricoveri** col
modello remoto e **40 volte** con quello locale — e i due modelli sbagliano in
due modi diversi, che è il risultato più interessante del confronto:

| codici fuori elenco | `deepseek-v4.1-flash` | `qwen3.5:4b` |
|---|---|---|
| proposti | 18 | 40 |
| presenti nel registro ATC dell'AIFA | **18 su 18** | **25 su 40** |
| classi **già nella terapia del paziente** | **18 su 18** | 7 su 40 |

**Il modello grande non allucina: ricopia.** Prende una classe dalla sezione
«terapia in atto» del prompt e la ripropone, invece di restare nell'elenco dei
candidati. È un errore più benigno di una fabbricazione — il farmaco esiste e il
paziente lo sta già prendendo.

**Il modello piccolo, invece, enumera l'albero ATC.** Fra i suoi 40 codici fuori
elenco compaiono `R05AA`, `R05AB`, `R05AC`, `R05AD`, `R05AE`, `R05AF`, `R05AG`:
sette suffissi consecutivi, nessuno dei quali è nel registro AIFA. Lo stesso
schema si ripete su `C04CA`/`C04CB`/`C04CC` e su `C01A`/`C01AB`/`C01AC`/`C01AF`.
Non sta scegliendo un farmaco: sta **generando codici della forma giusta**,
scorrendo le lettere. Quindici occorrenze su quaranta non corrispondono a nulla
nell'unica fonte ATC del progetto, e tre sono perfino tronche (`C01`, `C01A`,
`C01B`: tre o quattro caratteri invece di cinque).

La pipeline B dello step 4 misurava proprio questa distinzione con la citazione
letterale — «0 menzioni non ancorate su 552» — e qui la si ritrova sull'altro
lato del sistema, sul *codice* invece che sul testo. Sposta il giudizio sul
vincolo: per il modello remoto è un'igiene, per quello locale è **la cosa che lo
rende utilizzabile**. Un ranker che può nominare `R05AF` scavalca il filtro
dello step 8 proponendo un codice che nel filtro non esiste — e un codice che
non esiste non può essere né vietato né verificato.

### Il guasto che ha reso la corsa impossibile: uno schema senza tetto

Lo schema chiedeva un array di stringhe senza `maxItems`. Sotto decodifica
vincolata allo schema, **quel vincolo permette al modello di emettere stringhe
all'infinito** — e il modello locale da 4 miliardi di parametri lo fa: su un
ricovero ha prodotto **oltre 310 voci da 91 candidati**, ripetendosi finché non
ha saturato il contesto, e il JSON è arrivato troncato a metà stringa.

Il sintomo si presentava come lentezza. Per venti minuti ho creduto a un modello
fermo, mentre stava macinando spazzatura a pieno regime.

Due correzioni, entrambe misurate:

| | prima | dopo |
|---|---|---|
| tetto sull'array (`maxItems: 15`) | assente | 15 |
| contesto allocato | 8 192 token | 4 096 |
| **secondi per ricovero** | oltre 240, con JSON non valido | **24** |

Quindici non è un numero prudente, è il numero giusto: la metrica più profonda
del progetto è il richiamo@10, e un medico guarda le prime proposte. Oltre il
quindicesimo posto non c'è nulla da misurare.

### «Ordina male» oppure «non ordina affatto»

L'osservazione che aveva fatto nascere il sospetto — una risposta che elencava
le classi in **ordine alfabetico di codice**, cioè nell'ordine in cui le aveva
ricevute — **veniva da una chiamata che era essa stessa in avaria**, prima del
tetto sull'array. Non prova niente, e riportarla come proprietà del modello
sarebbe stato l'errore che il progetto ha già commesso due volte: attribuire al
modello un difetto del proprio codice.

Serviva un contatore su tutta la corsa, e c'è: la valutazione conta quante
risposte sono un **sottoinsieme in ordine** dei candidati.

**Misurato: 2 risposte su 239 per `deepseek`, lo 0,8%; 9 su 244 per `qwen`, il
3,7%.** Entrambi riordinano davvero. L'ipotesi era sbagliata, e va detto con la
stessa chiarezza con cui era stata formulata.

### Il risultato: il modello perde contro un contatore

| ranker (compito 2, le aggiunte) | ric@3 | ric@5 | ric@10 | MAP |
|---|---|---|---|---|
| frequenza (non guarda il paziente) | 36,8% | 49,5% | 67,2% | 0,426 |
| **ibrido** | **38,8%** | **53,1%** | **70,2%** | **0,456** |
| simbolico | 20,3% | 28,0% | 31,0% | 0,210 |
| `deepseek-v4.1-flash` — remoto, 0,1425 $ | 18,0% | 24,0% | 36,7% | 0,219 |
| `qwen3.5:4b` — locale, gratis | 14,2% | 19,7% | 27,6% | 0,178 |

Entrambi i modelli stanno **sotto il ranker di frequenza**, che non guarda
nemmeno il paziente, e il migliore dei due è **alla pari col ranker
simbolico**.

La ragione non è un'impressione, è misurabile, ed è la stessa del §4:

| fra le prime 5 aggiunte proposte | classi cardiovascolari |
|---|---|
| `deepseek-v4.1-flash` | **84,5%** |
| `qwen3.5:4b` | **82,6%** |
| ibrido | 74,3% |

La base è la stessa per tutti e tre — le prime cinque proposte dell'ordinamento
del compito 2 — perché confrontare quote calcolate su basi diverse sarebbe un
modo elegante di sbagliare. Contando invece i soli codici che il modello nomina
davvero, una base che per l'ibrido non esiste, `deepseek` è all'87,4% e `qwen`
al 91,6%: la conclusione non cambia, e la differenza fra le due basi è il
riempimento d'ufficio di cui si parla più sotto.

| | le classi più proposte |
|---|---|
| `deepseek` | `C09AA` ACE-I, `C08CA` calcioantagonisti, `C09CA` sartani, `C03DA` antialdosteronici, `C07AB` betabloccanti |
| `qwen` | `C09CA` sartani, `C08CA` calcioantagonisti, `C09BB` associazioni, `C07AB`, `C09AA` |
| ibrido | `B01AX` antitrombotici, `C03DA` antialdosteronici, **`A02BC` gastroprotettori**, `C07AB`, `C03CA` diuretici dell'ansa |

**I modelli si comportano come ottimi ranker di linee guida, e prendono
esattamente il tetto che il §4 aveva predetto.** Propongono la cardiologia
giusta e mancano il 40% che cardiologia non è: nessuna linea guida cardiologica dice di
aggiungere un gastroprotettore, ma in questo reparto lo si aggiunge 209 volte.

È la conferma più pulita della tesi dello step: su questo compito **sapere che
cosa si prescrive in questo reparto vale più che sapere la medicina.** Non
perché la medicina conti meno, ma perché il bersaglio della misura è una
decisione reale, e le decisioni reali contengono molto che le linee guida non
regolano.

### Un difetto minore di aderenza alle istruzioni

Il prompt dice «fermati quando le classi rimanenti non sono indicate: un elenco
corto e giusto vale più di un elenco lungo». Nessuno dei due modelli si ferma:
`deepseek` nomina **14,6 classi su 15** quando risponde, `qwen` **13,2**, ed
entrambi toccano il massimo. Un ranker che non sa fermarsi sposta tutto il peso
della selezione su chi legge, e spiega perché la quota cardiovascolare misurata
sui soli codici nominati è più alta di quella misurata sulle prime cinque: la
coda dell'elenco è riempimento d'ufficio.

### Locale contro remoto: la stessa forma di errore, un gradino più in basso

La corsa locale era il termine di paragone richiesto prima di autorizzare la
spesa, e ora c'è. **Stesso prompt, stesso insieme candidato, stessi 244
ricoveri, stessa cache**: cambia solo il modello.

| | `qwen3.5:4b` locale | `deepseek-v4.1-flash` remoto |
|---|---|---|
| richiamo@5 sulle aggiunte | 19,7% | **24,0%** |
| MAP | 0,178 | **0,219** |
| quota cardiovascolare (prime 5) | 82,6% | 84,5% |
| codici fuori elenco scartati | **40** | 18 |
| risposte che ricalcano l'ordine d'ingresso | 9 / 244 | 2 / 239 |
| secondi per ricovero | **23,8** | 5,7 |
| durata della corsa | **1 h 34 min** | 22 min |
| costo | **0 $** | 0,1425 $ |

I 4,3 punti di richiamo@5 sono sopra il rumore di fondo del progetto, che è di
due punti: il modello grande ordina davvero meglio. Ma **la differenza fra i due
modelli è molto più piccola della differenza che separa entrambi dal contatore
di frequenza**, che sta a 49,5% e non guarda nemmeno il paziente. Il limite non
è la taglia del modello: è che il compito chiede di sapere che cosa si
prescrive in *questo* reparto, e nessuno dei due lo sa.

Il modello piccolo sbaglia nello stesso modo, solo più spesso: scavalca
l'elenco candidato **40 volte contro 18**, e ricalca l'ordine d'ingresso 9 volte
contro 2. Sono entrambi errori che il codice intercetta — il vincolo
all'insieme candidato è esattamente lo strato che rende un modello da 4 miliardi
di parametri utilizzabile senza che possa scavalcare il filtro di sicurezza.

**Conclusione operativa: su questo compito il locale basta**, perché il ranker
che si userebbe non è nessuno dei due. Se però si dovesse usarne uno, i 14
centesimi di differenza comprano 4 punti di richiamo e un'ora e mezza di
macchina.

### Il costo

| | remoto | locale |
|---|---|---|
| ricoveri | 244 | 244 |
| token in entrata / in uscita | 447 244 / 22 997 | 447 841 / 32 916 |
| **costo dichiarato dal fornitore** | **0,1425 $** | **0 $** |
| tempo di macchina | 22 min | 1 h 34 min |

La stima portata prima di spendere era «circa 0,12 $», calcolata sui token di
una prova da dieci record: lo scarto è di tre centesimi in eccesso.

I token in entrata quasi coincidono — 447 244 contro 447 841 — perché il prompt
è lo stesso e li conta il tokenizzatore di ciascun modello. In uscita il modello
locale ne spende **il 43% in più** per dire meno: è la coda di codici enumerati
di cui sopra.

Spesa totale del progetto, **sommando il costo dichiarato dal fornitore su tutte
le 2 321 risposte a pagamento che la cache conserva**: **4,4494 $** sui 5
disponibili. È una misura, non un ricordo — la cache porta il costo dentro ogni
risposta proprio per non doverlo ristimare dai token con un listino che nel
frattempo può essere cambiato.

---

## 10. Che cosa lo step 9 lascia aperto

- **Gli attributi del riferimento non sono valutati.** Lo stesso limite dello
  step 6bis.
- **Il dosaggio non è modellato.** Il ranker propone classi, non posologie, e
  una raccomandazione terapeutica senza dose è incompleta.
- **La frazione di eiezione, il punteggio CHA₂DS₂-VA e i valori di laboratorio**
  restano i tre fatti che più limitano la precisione clinica delle regole.
- **La precisione non è interpretabile** come misura di correttezza, per la
  ragione del §1: il riferimento è una decisione giusta, non tutte.
- **La metrica gerarchica** è rimandata allo step 11, dove il §7 mostra che vale
  da 4 a 7 punti.
