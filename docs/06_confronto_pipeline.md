# Step 6 — Confronto fra le tre pipeline

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

**198 record**, quanti ne ha la pipeline B. Confrontare A e C su mille referti e
B su duecento darebbe tre numeri che non stanno nella stessa tabella.

Le tre pipeline condividono già, per costruzione, tutto ciò che non è
riconoscimento: gli stessi risolutori ICD e ATC, la stessa implementazione di
ConText, lo stesso asse del soggetto, lo stesso parser dei campi strutturati.
Ogni allineamento è stato fatto negli step precedenti proprio per arrivare qui
con una differenza attribuibile a una causa sola.

---

## 2. Tre decisioni di disegno, imposte dai dati

### 2.1 Prosa e campi strutturati vanno separati

Il primo controllo ha cambiato il disegno dell'intero step:

| sui 198 record | A | B | C |
|---|---|---|---|
| condizioni dalla prosa | 1 075 | 4 462 | 1 112 |
| farmaci dalla prosa | 529 | 42 | 588 |
| farmaci dalla terapia d'ingresso | **1 118** | 1 086 | **1 118** |
| farmaci dalla terapia di dimissione | **1 317** | 376 | **1 317** |

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
produrrebbe un numero che sembra una misura senza esserlo. Nella prosa sono 147
su 4 267.

---

## 3. Chi vede cosa, nella prosa

**4 267 punti distinti.**

| viste da | punti |
|---|---|
| A, B e C | 761 |
| A e C | 740 |
| B e C | 34 |
| A e B | 14 |
| **solo B** | **2 616** |
| solo C | 76 |
| solo A | 26 |

A e C si sovrappongono quasi del tutto — 1 501 punti condivisi contro 26 e 76
esclusivi — ed era atteso, dato che il NER è addestrato sull'uscita del
gazetteer. Le poche differenze sono però le più istruttive.

La pipeline B vive in un mondo a parte: 2 616 punti che nessun'altra vede.
**Questo numero da solo non dice niente.** Potrebbe essere richiamo eccezionale o
rumore massiccio, e distinguerli richiede di guardare.

---

## 4. L'aggiudicazione, ed è il risultato centrale

Le menzioni esclusive sono state estratte, lette **nel loro referto** e giudicate
a mano: individuano un'entità clinica reale, sì o no? Tutte e 26 quelle di A, un
campione casuale di 25 di C e 30 di B. I verdetti sono registrati nel notebook,
uno per uno, con il seme del campionamento.

| | campione | corrette | precisione | **errori che portano un codice** |
|---|---|---|---|---|
| A | 26 | 14 | 53,8% | **12 su 12 — 100%** |
| C | 25 | 18 | **72,0%** | 0 su 7 — 0% |
| B | 30 | 17 | 56,7% | 0 su 13 — 0% |

Le tre precisioni sono vicine. L'ultima colonna dice una cosa completamente
diversa: **tutti gli errori esclusivi di A portano con sé un codice ICD assegnato
con sicurezza; nessuno di quelli di B e C ce l'ha.**

La ragione è strutturale, non accidentale. Il gazetteer di A **riconosce e
codifica in un solo passo**: se una forma ha fatto match, il codice c'è per
costruzione. B e C riconoscono prima e collegano dopo, quindi un riconoscimento
sbagliato di norma non aggancia nulla e resta visibile come irrisolto.

E l'errore non è casuale ma **sistematico**: i dodici errori sono tre forme
sole, ripetute.

```
Z29.0  «isolamento»     ×8   (Z29.0 = isolamento profilattico)
S26    «del cuore»      ×3   (S26   = trauma cardiaco)
M67.4  «ganglio»        ×1   (M67.4 = cisti gangliare)
```

Nei referti `isolamento` compare quasi sempre in due sensi che con l'isolamento
profilattico non c'entrano: *isolamento di germi* in una coltura, e *isolamento
elettrico delle vene polmonari*, che è una procedura di ablazione. `del cuore`
riceve un codice di trauma cardiaco dalla frase «Ospedale del Cuore».

**Per il filtro di sicurezza dello step 8 questa distinzione conta più di
qualunque punto percentuale.** Un errore che porta un codice verrà usato; uno che
resta irrisolto si vede.

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
| A–C | stato | 1 404 | 100,0% |
| A–C | soggetto | 1 404 | 100,0% |
| A–C | codice | 1 404 | 99,2% |
| A–B | stato | 683 | **94,6%** |
| A–B | soggetto | 683 | 100,0% |
| A–B | codice | 683 | 90,5% |
| B–C | stato | 700 | 94,4% |
| B–C | soggetto | 700 | 100,0% |
| B–C | codice | 700 | 90,3% |

L'accordo **A–C sullo stato al 100% non è un risultato**: le due usano *la
stessa* implementazione di ConText, quindi non potevano che concordare. È un
controllo di sanità, ed è passato — se avesse dato meno del 100% ci sarebbe stato
un difetto da qualche parte.

Il numero informativo è **A–B al 94,6%**: lì due metodi genuinamente diversi
arrivano alla stessa conclusione in 95 casi su 100. L'analisi dei 33 disaccordi
residui è nello step 4 (§ 7quinquies): A ha ragione 23 volte, B 9, nessuna delle
due 1.

Il **soggetto concorda al 100% ovunque**, e anche questo è per costruzione —
l'asse *experiencer* è calcolato dalla stessa funzione condivisa. Dice però una
cosa non ovvia: la regola è **stabile rispetto ai confini della menzione**, che
fra pipeline sono diversi. Avrebbe potuto rispondere diversamente sui due
intervalli, e non è successo.

---

## 6. Copertura dei codici

| | condizioni | con ICD | farmaci | con ATC |
|---|---|---|---|---|
| A | 1 075 | **99,9%** | 529 | 96,2% |
| B | 3 474 | 28,4% | 35 | 80,0% |
| C | 1 112 | 94,0% | 588 | 85,0% |

Il 99,9% di A **non è un merito, è una tautologia**: il suo vocabolario di
condizioni è costruito dai termini ICD, quindi tutto ciò che trova è codificabile
per definizione. Il denominatore è ristretto a ciò che la knowledge base già
conosce.

Il 28,4% di B ha il denominatore più largo di tutti — comprese le narrazioni che
l'ICD non ha alcuna ragione di coprire.

Il confronto sensato non è fra le percentuali ma fra i **valori assoluti**: A
codifica 1 074 condizioni, C ne codifica 1 045, B ne codifica 987. Numeri vicini,
ottenuti in tre modi completamente diversi.

---

## 7. Un modello linguistico contro una regex

Il parser deterministico fa da riferimento.

| campo | voci del parser | ritrovate da B | recupero |
|---|---|---|---|
| Terapia all'ingresso | 1 099 | 1 017 | **92,5%** |
| Terapia alla dimissione | 1 310 | 423 | **32,3%** |

Stesso modello, stesso prompt, campi altrettanto regolari — e un'asimmetria di
sessanta punti.

E la distribuzione **non è graduale ma bimodale**:

| recupero per record | record |
|---|---|
| nessuna voce (0%) | **96** |
| tutte o quasi (≥100%) | 58 |
| parziale | 11 |

**O legge il campo o lo salta.** Ho cercato una discriminante — lunghezza del
referto, numero di condizioni estratte prima, numero di voci da estrarre, ordine
dei campi nel prompt — e **non ce n'è una misurabile**: i due gruppi si
somigliano (27 contro 31 menzioni totali, 2 630 contro 1 971 caratteri di
anamnesi, 9 contro 7 voci da estrarre).

L'ipotesi che il campo di dimissione, essendo l'ultimo del prompt, pagasse il
bilancio speso prima è stata **provata e scartata**: il recupero non è monotono
nel numero di condizioni estratte, e i quarti centrali fanno meglio degli
estremi.

La conclusione è quindi negativa e va detta così: su un campo che una regex
interpreta al 99%, un modello da quattro miliardi di parametri lo interpreta al
32% **senza che si possa prevedere quando**. Non è un problema di capacità ma di
affidabilità, ed è la ragione per cui i campi strutturati restano al parser.

---

## 8. Che cosa se ne porta via il progetto

| | A | B | C |
|---|---|---|---|
| punti esclusivi nella prosa | 26 | 2 616 | 76 |
| precisione sul campione aggiudicato | 53,8% | 56,7% | **72,0%** |
| **errori che portano un codice** | **100%** | 0% | 0% |
| copertura ICD sulle condizioni | 99,9% | 28,4% | 94,0% |
| condizioni codificate, in assoluto | 1 074 | 987 | 1 045 |
| recupero sui campi strutturati | riferimento | 32,3% | riferimento |
| tempo per record | 0,02 s | 267 s | 0,46 s |

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
  provenienza, non fuse. Le 2 616 menzioni esclusive di B non sono verità né
  rumore: sono candidati con una precisione stimata del 57%, e il grafo deve
  poterlo dire.
* **Step 8 (filtro di sicurezza):** il filtro non può fidarsi di un codice solo
  perché c'è. Gli errori di A dimostrano che un codice sicuro può venire da un
  riconoscimento sbagliato, quindi serve almeno una regola che tenga conto del
  **metodo** registrato nella provenienza — che è precisamente ciò per cui il
  campo `regola` esiste dallo step 1.
* **Step 11 (valutazione):** la terapia di dimissione resta la ground truth, e va
  letta con il **parser**, non con il modello. Il 32,3% chiude la questione.

---

## 10. Limiti noti di questo confronto

* **Il campione aggiudicato è piccolo**: 81 menzioni in tutto. Basta a mostrare
  che il profilo di errore di A è qualitativamente diverso — 12 su 12 è un
  risultato netto — ma gli intervalli di confidenza sulle tre precisioni sono
  larghi, e le differenze fra 53,8%, 56,7% e 72,0% non sono da prendere come
  ordinamento stabile.
* **L'aggiudicazione è mia**, di una persona sola, senza un secondo giudice e
  senza misura di accordo fra annotatori. È dichiarata, non nascosta.
* **Le menzioni non ancorate di B sono escluse** dall'allineamento perché senza
  offset non c'è niente da sovrapporre. Sono 883 su 6 772, e restano nei file
  marcate: non entrano nel confronto ma non sono state cancellate.
* **I 147 gruppi ambigui** nella prosa non contribuiscono ai confronti attributo
  per attributo. Contribuiscono al Venn, dove serve solo sapere *quali* pipeline
  hanno visto il punto.
* **Il confronto è su 198 record**, non su mille. A e C potrebbero essere
  confrontate sull'intero dataset, e i loro numeri là sono nello step 5.
