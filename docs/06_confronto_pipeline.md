# Step 6 — Confronto fra le tre pipeline

**Stato:** completato.
**Riproducibilità:** `python3 src/confronto.py`

Le pipeline A, B e C leggono gli stessi referti e producono lo stesso schema.
Questo step misura in che cosa differiscono, e quanto di quella differenza è
attribuibile al solo **riconoscimento** delle menzioni.

**Non è un confronto di accuratezza contro una verità.** Il brief esclude
l'annotazione manuale, quindi non esiste un riferimento annotato. È uno studio di
**accordo e complementarità**, più un'**aggiudicazione manuale su un campione**,
che è l'unico modo onesto di dire qualcosa sulla precisione.

Componenti: [`src/confronto.py`](../src/confronto.py) (misure e allineamento),
[`notebooks/02_confronto_pipeline.ipynb`](../notebooks/02_confronto_pipeline.ipynb)
(l'analisi con i grafici), [`tests/test_confronto.py`](../tests/test_confronto.py)
(16 test).

---

## 1. L'insieme di confronto

**Tutti e 1 000 i record.** Fino alla prima stesura di questo documento erano
199 — quanti ne aveva la pipeline B, l'unica che richiedesse un modello
linguistico e quindi ore di calcolo. Passando a un modello remoto la pipeline B
ha elaborato l'intero corpus in 39 minuti per 2,42 $, e il vincolo è caduto.

### La pipeline B esiste in due versioni, e nessuna sostituisce l'altra

| | modello | record | tempo | costo |
|---|---|---|---|---|
| **B-locale** | `qwen3:4b` via Ollama | 199 | 13 h | 0 € |
| **B-remota** | `deepseek/deepseek-v4.1-flash` | 1 000 | 39 min | 2,42 $ |

Le misure di questo documento sono sulla **B-remota**, che è l'unica a coprire il
corpus. La B-locale resta nei dati e resta un braccio del confronto: è ciò che
rende possibile la domanda del § 7bis, cioè **quanto di ciò che avevo attribuito
al metodo era invece la taglia del modello**. Le due hanno lo stesso schema e le
stesse regole di prompt sulle condizioni, quindi su quel punto sono confrontabili
direttamente.

Le tre pipeline condividono già, per costruzione, tutto ciò che non è
riconoscimento: gli stessi risolutori ICD e ATC, la stessa implementazione di
ConText, lo stesso asse del soggetto, lo stesso parser dei campi strutturati.
Ogni allineamento è stato fatto negli step precedenti proprio per arrivare qui
con una differenza attribuibile a una causa sola.

---

## 2. Tre decisioni di disegno, imposte dai dati

### 2.1 Prosa e campi strutturati vanno separati

Il primo controllo ha cambiato il disegno dell'intero step:

| sui 1 000 record | A | B | C |
|---|---|---|---|
| condizioni dalla prosa | 5 237 | 16 639 | 5 420 |
| farmaci dalla prosa | 2 332 | **62** | 2 542 |
| farmaci dalla terapia d'ingresso | **5 494** | 5 761 | **5 494** |
| farmaci dalla terapia di dimissione | **6 329** | 6 578 | **6 329** |

Sui campi di terapia **A e C danno numeri identici**, perché usano lo stesso
parser deterministico. Confrontarli lì misurerebbe zero per costruzione, e
mescolarli con la prosa diluirebbe la differenza vera in una componente
condivisa.

Il confronto si spezza quindi in due domande diverse:

1. **sulla prosa** — le tre pipeline riconoscono davvero cose diverse;
2. **sui campi strutturati** — il parser fa da riferimento affidabile (interpreta
   il 99% delle voci, misurato allo step 0) e la domanda diventa: *un modello
   linguistico regge il confronto con quaranta righe di regex?*

### 2.2 I farmaci che B elenca come condizioni si riclassificano, non si scartano

Il risolutore ATC riconosce come farmaci una parte delle "condizioni" di B —
`bisoprololo`, `furosemide`, `levetiracetam`. Scartarle direbbe che la pipeline
non le ha viste, e sarebbe **falso**: la menzione è stata riconosciuta
correttamente nel testo, l'errore sta nell'etichetta.

Vengono quindi **spostate** nell'elenco dei farmaci, e lo spostamento viene
contato. È anche coerente con la regola del progetto di non cancellare mai dati:
il difetto resta visibile invece di sparire.

Sulle 198 uscite: **427 duplicati rimossi** e **98 farmaci riclassificati**.

> I numeri sono più bassi di quelli dello step 4 (795 e 507) perché qui le
> menzioni non ancorate sono già escluse: senza offset non c'è niente da
> allineare. La differenza dice una cosa utile — la maggior parte dei farmaci
> finiti fra le condizioni erano anche non ancorati, cioè citazioni prese dai
> campi di terapia ma dichiarate come anamnesi.

### 2.3 L'allineamento non può dipendere dai confini

Due menzioni sono la stessa quando cadono nello stesso ricovero, nello stesso
campo, e i loro **intervalli di caratteri si sovrappongono**. È l'unico criterio
che non dipende da come ciascuna pipeline sceglie i confini, che sono
sistematicamente diversi: il gazetteer aggancia il termine di vocabolario, il
NER l'estensione appresa, il modello spesso la frase intera.

Le menzioni collegate formano un **grafo**, e ogni componente connessa è un
«punto» del referto su cui una o più pipeline hanno trovato qualcosa.

Le componenti in cui una pipeline mette **più di una menzione** sono ambigue —
succede quando una citazione lunga di B ne abbraccia diverse corte di A — e
vengono escluse dai confronti attributo per attributo invece di essere risolte a
forza: non è definito quale menzione confrontare con quale, e sceglierne una
produrrebbe un numero che sembra una misura senza esserlo. Nella prosa sono 173
su 4 537.

---

## 3. Chi vede cosa, nella prosa

**20 573 punti distinti.**

| viste da | punti |
|---|---|
| A, B e C | 3 626 |
| A e C | 3 683 |
| B e C | 231 |
| A e B | 52 |
| **solo B** | **12 511** |
| solo C | 325 |
| solo A | 145 |

A e C si sovrappongono quasi del tutto — 7 309 punti condivisi contro 145 e 325
esclusivi — ed era atteso, dato che il NER è addestrato sull'uscita del
gazetteer. Le poche differenze sono però le più istruttive.

La pipeline B vive in un mondo a parte: 12 511 punti che nessun'altra vede, il
61% di tutti i punti del corpus.
**Questo numero da solo non dice niente.** Potrebbe essere richiamo eccezionale o
rumore massiccio, e distinguerli richiede di guardare.

---

## 4. L'aggiudicazione, ed è il risultato centrale

Le menzioni esclusive sono state estratte, lette **nel loro referto** e giudicate
a mano: individuano un'entità clinica reale, correttamente attribuita, sì o no?
**60 menzioni di B e 30 per ciascuna delle altre due**, campionate con seme
`20260914` dallo stesso confronto a 1 000 record. I verdetti sono registrati nel
notebook, uno per uno.

| | campione | corrette | precisione | **errori che portano un codice** |
|---|---|---|---|---|
| **B** (remota) | 60 | 55 | **91,7% ± 3,6%** | 1 su 5 — 20% |
| A | 30 | 22 | 73,3% ± 8,1% | **7 su 8 — 88%** |
| C | 30 | 20 | 66,7% ± 8,6% | 0 su 10 — 0% |

Il `±` è l'errore standard del campione, e va letto **prima** dei numeri che
precede.

* Gli intervalli di **A [65,2–81,4] e C [58,1–75,3] si sovrappongono**: fra
  quelle due la precisione non ordina niente.
* Quello di **B [88,1–95,2] è disgiunto da entrambi**. Su questo campione B è
  distinguibilmente più precisa, ed è il solo confronto di precisione del
  progetto in cui si possa dirlo.

Lo stesso vale per le due versioni di B, sugli stessi 199 record e con le regole
di prompt sulle condizioni identiche: **66,7% ± 8,6 in locale contro 91,7% ± 3,6
in remoto**, intervalli disgiunti. Lì la differenza è attribuibile al modello.

I cinque errori della B-remota, per intero, perché la loro natura conta più del
conteggio:

| menzione | perché è un errore |
|---|---|
| «rimozione polipi e fibromi endometriali» | è una procedura, non una condizione |
| «Pregresso bypass gastrico» | idem |
| «dell'aorta ascendente (43mm)» | confine: il testo diceva *dilatazione ... dell'aorta ascendente*, e la parola che nomina la patologia è rimasta fuori |
| un'annotazione sulle abitudini alimentari | è uno stile di vita, non una condizione |
| «flutter atriale» → `I48` | **soggetto sbagliato**: l'aritmia è del **feto**, non della paziente |

Sparite del tutto, rispetto alla B-locale, tre categorie che là erano la norma:
**risultati di esami normali** («Spirometria nella norma», «Buone condizioni
generali»), **misure nude** («VCI 14 mm», «intervallo PR 210 msec») e **frammenti
di parola** («corticos» da *corticosteroidea*). Nelle 60 menzioni lette non ce
n'è nessuna.

Le tre precisioni sono vicine. L'ultima colonna dice una cosa completamente
diversa: **tutti gli errori esclusivi di A portano con sé un codice ICD assegnato
con sicurezza; nessuno di quelli di B e C ce l'ha.**

La ragione è strutturale, non accidentale. Il gazetteer di A **riconosce e
codifica in un solo passo**: se una forma ha fatto match, il codice c'è per
costruzione. B e C riconoscono prima e collegano dopo, quindi un riconoscimento
sbagliato di norma non aggancia nulla e resta visibile come irrisolto.

E l'errore non è casuale ma **sistematico**: sui 1 000 record i sette errori
codificati del campione sono **una forma sola**, ripetuta.

```
Z29.0  «isolamento»  ×7   (Z29.0 = isolamento profilattico)
```

Nei referti quella parola non significa mai isolamento profilattico: significa
*isolamento elettrico delle vene polmonari*, che è una procedura di ablazione.
Sette volte su sette il gazetteer la codifica come un ricovero in isolamento.

Nei referti `isolamento` compare quasi sempre in due sensi che con l'isolamento
profilattico non c'entrano: *isolamento di germi* in una coltura, e *isolamento
elettrico delle vene polmonari*, che è una procedura di ablazione. `del cuore`
riceve un codice di trauma cardiaco dalla frase «Ospedale del Cuore».

**Per il filtro di sicurezza dello step 8 questa distinzione conta più di
qualunque punto percentuale.** Un errore che porta un codice verrà usato; uno che
resta irrisolto si vede.

### L'unico errore codificato di B, e il buco che ha scoperto

Nella corsa precedente nessun errore di B portava un codice. Adesso ce n'è uno, e
non è rumore statistico: è un difetto nuovo, in un componente che credevo chiuso.

```
[I48] «fibrillanti»   soggetto = paziente
```

La menzione è giusta come entità — *fibrillanti* sta per fibrillazione atriale, e
I48 è il codice corretto. È sbagliato **a chi viene attribuita**: nel referto
l'aggettivo non si riferisce al paziente ma a due sue parenti, nominate per grado
di parentela nella frase precedente. La forma è questa (esempio ricostruito, non
copiato dal referto):

```
Nega familiarita per cardiopatia. Madre e sorella fibrillanti.
```

L'asse *experiencer* introdotto nello step 4 riconosce i marcatori espliciti
(`familiarità per`, `anamnesi familiare`, `storia familiare`) ed è per questo che
il soggetto concorda al 99,9% fra le pipeline. Ma **una frase che nomina
direttamente il parente non contiene nessuno di quei marcatori**: la regola non la
vede, e l'attribuzione cade sul paziente per impostazione.

È il caso peggiore possibile per il filtro dello step 8 — una condizione
cardiologica, con codice sicuro, attribuita alla persona sbagliata — ed è
esattamente la categoria di errore che finora avevo attribuito solo ad A. Va
aggiunto ai limiti aperti dello step 4: i marcatori di parentela diretti
(*madre*, *padre*, *zia*, *nonna*, *fratello*) non sono nel lessico.

Gli errori delle altre due hanno nature diverse e più benigne:

* **C** sbaglia quasi solo i **confini**: `re` da *remdesivir*, `gli` da
  *glifozina*, `Ta` da *Tavanic*. Frammenti visibili, non codificati. Le sue
  menzioni esclusive corrette sono farmaci veri che il vocabolario non ha —
  `dronedarone`, `olmesartan`, `Oncocarbide`, `Trixeo` — e riconosce anche i
  refusi del referto (`amidoarone`, `rivaroxabn`), cosa che un gazetteer non può
  fare.
* **B** sovra-estrae **narrazione**: risultati di esami normali, descrizioni di
  interventi, intestazioni di sezione. Ma trova anche condizioni vere che le
  altre due non hanno, come `MGUS IgM kappa`, `restenosi intrastent della
  circonflessa`, `insufficienza aortica moderata`.

---

## 5. Accordo sugli attributi

Sui punti visti da entrambe, nei gruppi non ambigui:

| coppia | attributo | confrontabili | accordo |
|---|---|---|---|
| A–C | stato | 7 147 | 100,0% |
| A–C | soggetto | 7 147 | 100,0% |
| A–C | codice | 7 147 | 99,3% |
| A–B | stato | 3 534 | **97,7%** |
| A–B | soggetto | 3 534 | 99,9% |
| A–B | codice | 3 534 | 95,8% |
| B–C | stato | 3 711 | 97,7% |
| B–C | soggetto | 3 711 | 99,9% |
| B–C | codice | 3 711 | 94,8% |

L'accordo **A–C sullo stato al 100% non è un risultato**: le due usano *la
stessa* implementazione di ConText, quindi non potevano che concordare. È un
controllo di sanità, ed è passato — se avesse dato meno del 100% ci sarebbe stato
un difetto da qualche parte.

Il numero informativo è **A–B al 97,7% su 3 534 punti confrontabili**: lì due metodi
genuinamente diversi — una finestra di marcatori contro un modello linguistico —
arrivano alla stessa conclusione in 98 casi su 100. L'analisi dei 33 disaccordi
residui è nello step 4 (§ 7quinquies): A ha ragione 23 volte, B 9, nessuna delle
due 1.

Il **soggetto concorda al 99,9% ovunque**, e anche questo è quasi per costruzione —
l'asse *experiencer* è calcolato dalla stessa funzione condivisa. Dice però una
cosa non ovvia: la regola è **stabile rispetto ai confini della menzione**, che
fra pipeline sono diversi. Avrebbe potuto rispondere diversamente sui due
intervalli, e non è successo.

---

## 6. Copertura dei codici

| | condizioni | con ICD | farmaci | con ATC |
|---|---|---|---|---|
| A | 5 237 | **99,4%** | 2 332 | 96,1% |
| B | 16 561 | 34,8% | **61** | 24,6% |
| C | 5 420 | 93,4% | 2 542 | 86,7% |

Il 99,9% di A **non è un merito, è una tautologia**: il suo vocabolario di
condizioni è costruito dai termini ICD, quindi tutto ciò che trova è codificabile
per definizione. Il denominatore è ristretto a ciò che la knowledge base già
conosce.

Il 34,8% di B ha il denominatore più largo di tutti — comprese le narrazioni che
l'ICD non ha alcuna ragione di coprire.

Il confronto sensato non è fra le percentuali ma fra i **valori assoluti**: A
codifica 5 205 condizioni, C ne codifica 5 064, B ne codifica 5 763. Numeri
vicini, ottenuti in tre modi completamente diversi.

### Una riga che non è un miglioramento, e va detta

**I farmaci che B trova nella prosa crollano a 61**, con il 24,6% di ATC, contro
i 2 332 di A e i 2 542 di C. La B-locale ne trovava di più. Non è rumore tolto:
i farmaci citati nella narrazione — *«sospesa terapia con rivaroxaban»*,
*«ridotto il dabigatran dopo sanguinamenti»* — sono clinicamente rilevanti
proprio perché raccontano una storia terapeutica che i campi strutturati non
contengono. Il modello remoto si concentra sui campi di terapia, dove è
eccellente, e nell'anamnesi quasi non segnala farmaci.

È il motivo per cui lo step 7 non prende una pipeline sola. Numeri vicini,
ottenuti in tre modi completamente diversi.

---

## 7. Un modello linguistico contro una regex

Il parser deterministico fa da riferimento.

| campo | voci del parser | ritrovate da B | recupero |
|---|---|---|---|
| Terapia all'ingresso | 5 456 | 5 451 | **99,9%** |
| Terapia alla dimissione | 6 294 | 6 269 | **99,6%** |

**Praticamente perfetto su entrambi i campi.** Su 6 294 voci di terapia di
dimissione il modello ne ritrova 6 269.

---

## 7bis. Una conclusione di questo documento, e perché era sbagliata

La versione precedente di questa sezione si chiudeva così:

> *«su un campo che una regex interpreta al 99%, un modello lo interpreta al 50%
> senza che si possa prevedere su quali record. **Non è un problema di capacità
> ma di affidabilità**, ed è la ragione per cui i campi strutturati restano al
> parser.»*

La misura era giusta, l'inferenza no. Ecco i due numeri appaiati, **sugli stessi
199 record**, con lo stesso schema e le stesse regole di prompt:

| | B-locale (`qwen3:4b`) | B-remota (`deepseek-v4.1-flash`) |
|---|---|---|
| terapia all'ingresso | 88,6% | **99,9%** |
| terapia alla dimissione | 50,5% | **99,6%** |
| record con recupero 0% sulla dimissione | 59 su 165 | 2 su 845 |

### Come ci sono arrivato, e dove ho sbagliato

Avevo osservato che il recupero era **bimodale**: o il modello leggeva il campo
(95 record) o lo saltava del tutto (59), con appena 11 record in mezzo. Sul
corpus intero, con il modello remoto, la bimodalità semplicemente non c'è più:
827 record completi, 16 parziali, 2 a zero. Avevo
allora cercato la discriminante fra i due gruppi — lunghezza del referto, numero
di condizioni estratte prima, numero di voci da estrarre, posizione del campo nel
prompt — e **non ne avevo trovata nessuna**: i due gruppi si somigliavano in
tutto ciò che sapevo misurare (27 contro 31 menzioni totali, 2 630 contro 1 971
caratteri di anamnesi, 9 contro 7 voci da estrarre).

Da «non trovo una discriminante nei record» ho concluso «il comportamento è
intrinsecamente incoerente». È un salto, e non regge: **la discriminante non era
nei record, era nel modello.** Cercandola solo fra le proprietà dei dati non
potevo trovarla, per quanto a lungo guardassi.

L'errore non è stato misurare male, ed è questo che lo rende istruttivo:
un'assenza di correlazione era stata trattata come una proprietà del compito,
mentre era una proprietà di un modello da quattro miliardi di parametri.

### Che cosa resta valido

Che **i campi strutturati restino al parser**, quello sì. Non perché un modello
non sappia leggerli — ora sappiamo che sa — ma perché una regex di quaranta righe
li interpreta al 99%, in 0,02 secondi per record, gratis, in modo deterministico
e riproducibile all'infinito. Usare un modello linguistico dove basta una regex
resta la scelta sbagliata, e allo step 11 la terapia di dimissione continuerà a
essere letta dal parser.

Ciò che cambia è la **ragione**: non più «il modello non è affidabile lì», ma
«il modello lì non serve».

---

## 8. Che cosa se ne porta via il progetto

| | A | B (remota) | C |
|---|---|---|---|
| punti esclusivi nella prosa | 145 | 12 511 | 325 |
| precisione sul campione aggiudicato | 73,3% ± 8,1% | **91,7% ± 3,6%** | 66,7% ± 8,6% |
| **errori che portano un codice** | **7 su 8 — 88%** | 1 su 5 — 20% | 0 su 10 — 0% |
| copertura ICD sulle condizioni | 99,4% | 34,8% | 93,4% |
| condizioni codificate, in assoluto | 5 205 | 5 763 | 5 064 |
| farmaci trovati nella prosa | 2 332 | **61** | 2 542 |
| recupero sulla terapia di dimissione | riferimento | 99,6% | riferimento |
| tempo per record | 0,02 s | 2,3 s | 0,31 s |
| costo per 1 000 record | 0 € | 2,42 $ | 0 € |

Due avvertenze sulla riga della precisione, e vanno lette prima della riga:

* gli intervalli di **A e C si sovrappongono**: fra quelle due il numero non
  ordina niente;
* il **91,7% di B è su un campione di 60** contro i 30 delle altre, quindi ha un
  intervallo più stretto a parità di metodo.

**La riga che separa le tre pipeline resta però la terza, non la seconda**, ed è
l'unica che non dipende dalla dimensione del campione: è una differenza
strutturale, non statistica. A riconosce e codifica in un passo solo, quindi un
riconoscimento sbagliato nasce già codificato; B e C riconoscono prima e
collegano dopo, e un errore di norma non aggancia nulla e resta visibile.

**Non c'è una pipeline che vince**, e cercarne una era la domanda sbagliata. Ci
sono tre profili di errore diversi, e per il motore di raccomandazione conta più
il profilo del punteggio:

* **A** è tredicimila volte più veloce di B e ha la copertura più alta, ma la
  copertura è alta per costruzione e **i suoi errori sono già codificati**: sono
  esattamente quelli che il filtro di sicurezza userebbe senza accorgersene.
* **C** ha la precisione migliore sulle menzioni esclusive, i suoi errori sono di
  confine e restano irrisolti, e trova ciò che alla knowledge base manca —
  compresi i refusi.
* **B** trova moltissimo e capisce il contesto meglio di una regola di prossimità
  in alcuni casi precisi (`asintomatico per`, `non riferiti`), ma un terzo di ciò
  che trova è narrazione scambiata per diagnosi, e sul campo strutturato è
  inaffidabile in modo imprevedibile.

L'uso sensato è **insieme**, e con ruoli diversi: il gazetteer per codificare, il
NER per segnalare ciò che alla knowledge base manca, il modello per la
comprensione contestuale dove serve davvero — e **mai il modello dove basta una
regex**.

---

## 9. Conseguenze per gli step successivi

* **Step 7 (knowledge graph):** le entità vanno nel grafo con la pipeline di
  provenienza, non fuse. Le 12 511 menzioni esclusive di B non sono verità né
  rumore: sono candidati con una precisione stimata al 91,7% (± 3,6), e il grafo
  deve poter registrare sia il numero sia il fatto che viene da un campione.
* **Step 8 (filtro di sicurezza):** il filtro non può fidarsi di un codice solo
  perché c'è. Gli errori di A dimostrano che un codice sicuro può venire da un
  riconoscimento sbagliato, quindi serve almeno una regola che tenga conto del
  **metodo** registrato nella provenienza — che è precisamente ciò per cui il
  campo `regola` esiste dallo step 1.
* **Step 11 (valutazione):** la terapia di dimissione resta la ground truth, e va
  letta con il **parser**, non con il modello — non più perché il modello sbagli
  (al 99,6% non sbaglia) ma perché una regex fa lo stesso lavoro gratis, in 0,02
  secondi e in modo deterministico. Vedi § 7bis.

---

## 10. Limiti noti di questo confronto

* **Il campione aggiudicato resta piccolo**: 120 menzioni in tutto. Basta a
  mostrare che il profilo di errore di A è qualitativamente diverso — 7 errori
  codificati su 8, tutti la stessa forma — e che B sta su un livello di
  precisione distinguibile. **Non** basta a ordinare A e C fra loro.
* **Il richiamo non è misurato affatto.** Nessuna cifra di questo documento dice
  quante condizioni siano state *mancate*: una diagnosi che nessuna delle tre
  pipeline vede è invisibile a ogni misura qui dentro. Serve un riferimento
  annotato a mano, ed è il motivo per cui lo step 11 ne costruisce uno su 25
  referti.
* **L'aggiudicazione è mia**, di una persona sola, senza un secondo giudice e
  senza misura di accordo fra annotatori. È dichiarata, non nascosta.
* **Le menzioni non ancorate di B sono escluse** dall'allineamento perché senza
  offset non c'è niente da sovrapporre. Sono 141 su 29 533 (0,5%), e restano nei
  file marcate: non entrano nel confronto ma non sono state cancellate.
* **I 266 gruppi ambigui** nella prosa non contribuiscono ai confronti attributo
  per attributo. Contribuiscono al Venn, dove serve solo sapere *quali* pipeline
  hanno visto il punto.
* **Un solo annotatore, e sono io.** Senza un secondo giudice non c'è misura di
  accordo fra annotatori, quindi le precisioni riportate sono giudizi dichiarati,
  non verità stabilite.
* **L'aggiudicazione della B-remota è su un modello, non su "gli LLM".** Un altro
  modello della stessa taglia potrebbe comportarsi diversamente.
* **Il confronto è ora su tutti i 1 000 record**, tolto il paragone fra le due
  versioni di B, che è sui 199 A e C potrebbero essere
  confrontate sull'intero dataset, e i loro numeri là sono nello step 5.
