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

**199 record**, quanti ne ha la pipeline B. Confrontare A e C su mille referti e
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

| sui 199 record | A | B | C |
|---|---|---|---|
| condizioni dalla prosa | 1 104 | 3 851 | 1 137 |
| farmaci dalla prosa | 503 | 57 | 560 |
| farmaci dalla terapia d'ingresso | **1 126** | 1 056 | **1 126** |
| farmaci dalla terapia di dimissione | **1 316** | 727 | **1 316** |

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

**4 537 punti distinti.**

| viste da | punti |
|---|---|
| A, B e C | 839 |
| A e C | 654 |
| B e C | 39 |
| A e B | 13 |
| **solo B** | **2 906** |
| solo C | 63 |
| solo A | 23 |

A e C si sovrappongono quasi del tutto — 1 493 punti condivisi contro 23 e 63
esclusivi — ed era atteso, dato che il NER è addestrato sull'uscita del
gazetteer. Le poche differenze sono però le più istruttive.

La pipeline B vive in un mondo a parte: 2 906 punti che nessun'altra vede.
**Questo numero da solo non dice niente.** Potrebbe essere richiamo eccezionale o
rumore massiccio, e distinguerli richiede di guardare.

---

## 4. L'aggiudicazione, ed è il risultato centrale

Le menzioni esclusive sono state estratte, lette **nel loro referto** e giudicate
a mano: individuano un'entità clinica reale, sì o no? Tutte e 23 quelle di A, un
campione casuale di 25 di C e 30 di B. I verdetti sono registrati nel notebook,
uno per uno, con il seme del campionamento.

| | campione | corrette | precisione | **errori che portano un codice** |
|---|---|---|---|---|
| A | 23 | 14 | 60,9% | **9 su 9 — 100%** |
| C | 25 | 18 | **72,0%** | 0 su 7 — 0% |
| B | 30 | 20 | 66,7% | 1 su 10 — 10% |

Le tre precisioni vanno lette con l'errore standard che un campione di 25-30
comporta: circa **±9 punti**. B passa dal 56,7% della corsa precedente al 66,7%,
ma quella differenza **non è distinguibile dal rumore del campionamento**, e non
va raccontata come un miglioramento dimostrato.

Un controllo che si poteva fare e si è fatto: delle menzioni esclusive di C
ricampionate qui, **sei erano già state giudicate** nell'aggiudicazione della
corsa precedente. I sei giudizi nuovi coincidono con i sei vecchi.

Le tre precisioni sono vicine. L'ultima colonna dice una cosa completamente
diversa: **tutti gli errori esclusivi di A portano con sé un codice ICD assegnato
con sicurezza; nessuno di quelli di B e C ce l'ha.**

La ragione è strutturale, non accidentale. Il gazetteer di A **riconosce e
codifica in un solo passo**: se una forma ha fatto match, il codice c'è per
costruzione. B e C riconoscono prima e collegano dopo, quindi un riconoscimento
sbagliato di norma non aggancia nulla e resta visibile come irrisolto.

E l'errore non è casuale ma **sistematico**: i nove errori sono tre forme sole,
ripetute.

```
Z29.0  «isolamento»     ×6   (Z29.0 = isolamento profilattico)
S26    «del cuore»      ×2   (S26   = trauma cardiaco)
M67.4  «ganglio»        ×1   (M67.4 = cisti gangliare)
```

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
| A–C | stato | 1 377 | 100,0% |
| A–C | soggetto | 1 377 | 100,0% |
| A–C | codice | 1 377 | 99,4% |
| A–B | stato | 740 | **96,9%** |
| A–B | soggetto | 740 | 99,9% |
| A–B | codice | 740 | 92,4% |
| B–C | stato | 763 | 96,7% |
| B–C | soggetto | 763 | 99,9% |
| B–C | codice | 763 | 91,9% |

L'accordo **A–C sullo stato al 100% non è un risultato**: le due usano *la
stessa* implementazione di ConText, quindi non potevano che concordare. È un
controllo di sanità, ed è passato — se avesse dato meno del 100% ci sarebbe stato
un difetto da qualche parte.

Il numero informativo è **A–B al 96,9%**: lì due metodi genuinamente diversi
arrivano alla stessa conclusione in 97 casi su 100. L'analisi dei 33 disaccordi
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
| A | 1 104 | **99,8%** | 503 | 96,2% |
| B | 3 851 | 28,1% | 57 | 84,2% |
| C | 1 137 | 94,5% | 560 | 85,2% |

Il 99,9% di A **non è un merito, è una tautologia**: il suo vocabolario di
condizioni è costruito dai termini ICD, quindi tutto ciò che trova è codificabile
per definizione. Il denominatore è ristretto a ciò che la knowledge base già
conosce.

Il 28,1% di B ha il denominatore più largo di tutti — comprese le narrazioni che
l'ICD non ha alcuna ragione di coprire.

Il confronto sensato non è fra le percentuali ma fra i **valori assoluti**: A
codifica 1 102 condizioni, C ne codifica 1 074, B ne codifica 1 084. Numeri vicini,
ottenuti in tre modi completamente diversi.

---

## 7. Un modello linguistico contro una regex

Il parser deterministico fa da riferimento.

| campo | voci del parser | ritrovate da B | recupero |
|---|---|---|---|
| Terapia all'ingresso | 1 117 | 990 | **88,6%** |
| Terapia alla dimissione | 1 308 | 661 | **50,5%** |

Stesso modello, stesso prompt, campi altrettanto regolari — e un'asimmetria di
trentotto punti. Era di sessanta prima che la REGOLA 7 fosse riscritta senza
gerarchia fra i due campi (step 4, § 7nonies).

E la distribuzione **non è graduale ma bimodale**, esattamente come prima:

| recupero per record | prima | dopo |
|---|---|---|
| nessuna voce (0%) | **96** | 59 |
| tutte o quasi (≥100%) | 58 | **95** |
| parziale | 11 | 11 |

I due gruppi si sono scambiati le dimensioni, e la forma è rimasta identica. La
correzione ha cambiato **quanto spesso** il modello legge il campo, non **il
modo** in cui fallisce quando non lo legge: resta un interruttore, non un
cursore. Undici record parziali prima, undici dopo.

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
50% **senza che si possa prevedere su quali record**. Non è un problema di capacità ma di
affidabilità, ed è la ragione per cui i campi strutturati restano al parser.

---

## 8. Che cosa se ne porta via il progetto

| | A | B | C |
|---|---|---|---|
| punti esclusivi nella prosa | 23 | 2 906 | 63 |
| precisione sul campione aggiudicato | 60,9% | 66,7% | **72,0%** |
| **errori che portano un codice** | **100%** | 10% | 0% |
| copertura ICD sulle condizioni | 99,8% | 28,1% | 94,5% |
| condizioni codificate, in assoluto | 1 102 | 1 084 | 1 074 |
| recupero sulla terapia di dimissione | riferimento | 50,5% | riferimento |
| tempo per record | 0,02 s | 235 s | 0,46 s |

Le tre precisioni distano fra loro meno dell'errore standard del campione
(±9 punti): **la riga che separa davvero le tre pipeline è la terza, non la
seconda.**

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
  provenienza, non fuse. Le 2 906 menzioni esclusive di B non sono verità né
  rumore: sono candidati con una precisione stimata attorno al 67%, con un
  intervallo largo, e il grafo deve poterlo dire.
* **Step 8 (filtro di sicurezza):** il filtro non può fidarsi di un codice solo
  perché c'è. Gli errori di A dimostrano che un codice sicuro può venire da un
  riconoscimento sbagliato, quindi serve almeno una regola che tenga conto del
  **metodo** registrato nella provenienza — che è precisamente ciò per cui il
  campo `regola` esiste dallo step 1.
* **Step 11 (valutazione):** la terapia di dimissione resta la ground truth, e va
  letta con il **parser**, non con il modello. Il 50,5%, per giunta distribuito
  in modo bimodale, chiude la questione.

---

## 10. Limiti noti di questo confronto

* **Il campione aggiudicato è piccolo**: 78 menzioni in tutto. Basta a mostrare
  che il profilo di errore di A è qualitativamente diverso — 9 su 9 è un
  risultato netto — ma l'errore standard sulle tre precisioni è di circa nove
  punti, e le differenze fra 60,9%, 66,7% e 72,0% **non** sono da prendere come
  ordinamento stabile. Vale anche nel tempo: il passaggio di B dal 56,7% al 66,7%
  fra le due corse è dentro quel margine.
* **L'aggiudicazione è mia**, di una persona sola, senza un secondo giudice e
  senza misura di accordo fra annotatori. È dichiarata, non nascosta.
* **Le menzioni non ancorate di B sono escluse** dall'allineamento perché senza
  offset non c'è niente da sovrapporre. Sono 664 su 6 980, e restano nei file
  marcate: non entrano nel confronto ma non sono state cancellate.
* **I 173 gruppi ambigui** nella prosa non contribuiscono ai confronti attributo
  per attributo. Contribuiscono al Venn, dove serve solo sapere *quali* pipeline
  hanno visto il punto.
* **Il confronto è su 199 record**, non su mille. A e C potrebbero essere
  confrontate sull'intero dataset, e i loro numeri là sono nello step 5.
