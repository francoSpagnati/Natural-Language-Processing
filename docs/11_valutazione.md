# Step 11 — La valutazione gerarchica, e i punti che erano aritmetica

**Stato:** completato.
**Riproducibilità:** `python3 src/valuta_gerarchica.py --pieghe 5`

Lo step 9 conta una proposta giusta o sbagliata. Un ricovero di prova mostra
perché non basta: il ranker simbolico propone `C10AA` (statina semplice), il
medico ha prescritto `C10BA` (statina **in associazione** con ezetimibe).

**Il ranker ha proposto una statina, il medico ha prescritto una statina, e la
misura lo conta come sbagliato** — esattamente come se avesse proposto un
antibiotico.

Questo step misura quanto vale quella differenza. La risposta breve è: **molto
meno di quanto sembrava, e non nel modo che mi aspettavo.**

Codice: [`src/valuta_gerarchica.py`](../src/valuta_gerarchica.py).
Test: [`tests/test_valuta_gerarchica.py`](../tests/test_valuta_gerarchica.py).

---

## 1. L'albero, che non è inventato

Il registro ATC dell'AIFA porta tutti i livelli con il loro nome:

```
C          sistema cardiovascolare        1 carattere
C07        betabloccanti                  3
C07A       betabloccanti                  4
C07AB      betabloccanti, selettivi       5   ← l'unità di questo progetto
C07AB02    metoprololo                    7
```

Quattro livelli sopra la sostanza, e sono quelli su cui si misura. Il quinto sta
sotto l'unità del progetto e non entra nel confronto.

## 2. Il controllo, che viene prima dei risultati

Troncare i codici **alza il richiamo per forza**: ci sono meno classi distinte,
quindi indovinare è più facile. Un numero che sale dopo il troncamento non
dimostra niente da solo.

Per questo ogni tabella porta la riga di un **ranker casuale a seme fisso**, che
subisce lo stesso effetto meccanico e nient'altro. Ciò che conta non è quanto
sale un ranker: è **quanto sale più del caso**.

Senza questa riga lo step 11 avrebbe prodotto la conclusione sbagliata, ed è la
parte del lavoro di cui sono più contento.

---

## 3. Il risultato principale: i 4–7 punti erano aritmetica

Richiamo@5 sulle aggiunte, 244 ricoveri di prova, 91 classi candidate.

| ranker | 1° liv. | 2° liv. | 3° liv. | **4° liv. (esatto)** |
|---|---|---|---|---|
| **casuale (seme fisso)** | **57,3%** | **19,6%** | **13,6%** | **7,2%** |
| continuità della terapia | 18,8% | 12,0% | 11,9% | 11,7% |
| frequenza | 79,4% | 55,1% | 55,8% | 49,5% |
| simbolico (ESC) | 58,6% | 37,1% | 35,7% | 28,0% |
| **ibrido** | **82,9%** | **61,6%** | **58,0%** | **53,1%** |
| `deepseek-v4.1-flash` | 49,8% | 35,9% | 29,5% | 24,0% |
| `qwen3.5:4b` | 46,6% | 26,4% | 22,2% | 19,7% |

L'ibrido sale da 53,1% a 58,0% salendo di un livello: sono i **~5 punti** che lo
step 9 aveva anticipato, dentro l'intervallo 4–7 previsto.

Ma il ranker casuale sale da 7,2% a 13,6%, cioè **6,4 punti**. Al netto del caso:

| guadagno sul caso (punti) | 1° liv. | 2° liv. | 3° liv. | 4° liv. |
|---|---|---|---|---|
| ibrido | +25,5 | +42,0 | **+44,4** | **+45,9** |
| frequenza | +22,1 | +35,5 | +42,2 | +42,3 |
| simbolico | +1,3 | +17,4 | +22,1 | +20,8 |
| `deepseek` | **−7,5** | +16,3 | +16,0 | +16,7 |
| continuità | −38,5 | −7,6 | −1,7 | +4,5 |

**Il vantaggio dell'ibrido sul caso non cresce salendo di livello: cala**, da
+45,9 a +44,4. La metrica gerarchica non premia il ranker bravo — premia di più
chi tira a sorte.

La conclusione è netta, e va detta com'è: **la metrica gerarchica non cambia
quale metodo vince, e i punti che fa guadagnare non sono un miglioramento della
misura, sono un effetto del denominatore.** Lo step 11 era motivato da
un'intuizione clinica corretta, e la misura dice che quell'intuizione non si
traduce in un numero diverso.

### Una riga che dice più delle altre

`deepseek` al primo livello è **sotto il caso**: −7,5 punti. Un ranker casuale
sparge le sue cinque proposte fra i gruppi anatomici; il modello le concentra
tutte sul cuore. Dato che il 40,4% delle prescrizioni di dimissione non è
cardiologia, concentrarsi sul cuore **costa**, e al livello più grossolano il
costo si vede in negativo.

È lo stesso tetto del §4 dello step 9, misurato da un'angolazione diversa.

---

## 4. Le metriche gerarchiche classiche dicono la stessa cosa

Precisione, richiamo e F gerarchici: ogni codice si espande nei suoi antenati e
si misura la sovrapposizione fra antenati proposti e antenati veri.

Riferimento: S. Kiritchenko, S. Matwin, F. Famili, *Functional annotation of
genes using hierarchical text categorization*, BioLINK SIG 2005; ripreso in
C. N. Silla Jr., A. A. Freitas, *A survey of hierarchical classification across
different application domains*, Data Mining and Knowledge Discovery 22(1–2), 2011, doi:10.1007/s10618-010-0175-9.

| ranker | hP | hR | hF |
|---|---|---|---|
| casuale | 12,4% | 22,9% | 16,1% |
| continuità | 10,0% | 13,3% | 11,4% |
| **frequenza** | **39,4%** | 58,8% | **47,2%** |
| ibrido | 37,6% | **62,7%** | 47,0% |
| simbolico | 23,4% | 39,0% | 29,3% |
| `deepseek` | 22,3% | 34,1% | 26,9% |
| `qwen3.5:4b` | 20,3% | 27,9% | 23,5% |

**Sotto la metrica gerarchica l'ibrido e la frequenza sono indistinguibili**:
47,0% contro 47,2%, due decimi di punto, un ordine di grandezza sotto il
pavimento di rumore del progetto. Lo step 9 dava all'ibrido un vantaggio di 2–3,6
punti, piccolo ma coerente su cinque metriche; qui si annulla, perché la
precisione gerarchica favorisce la frequenza (39,4% contro 37,6%) quanto il
richiamo favorisce l'ibrido.

Non è una contraddizione: è la stessa differenza vista con un peso diverso. Ma
impedisce di dire «l'ibrido è il migliore» senza aggiungere *secondo quale
metrica*.

---

## 5. Il caso della statina, contato invece che raccontato

Fra le proposte **non esatte** nelle prime 5, quanti livelli condividono con un
bersaglio?

| ranker | nulla | 1° liv. | 2° liv. | **3° liv. (quasi-centro)** |
|---|---|---|---|---|
| casuale | 67,0% | 25,3% | 4,3% | 3,4% |
| frequenza | 53,6% | 24,0% | 5,8% | **16,5%** |
| ibrido | 53,7% | 25,8% | 6,2% | **14,2%** |
| simbolico | 43,4% | **43,0%** | 8,8% | 4,8% |
| `deepseek` | 34,3% | **51,6%** | 8,5% | 5,6% |
| `qwen3.5:4b` | 33,0% | **51,6%** | 8,5% | 6,9% |

Due letture, e la seconda corregge lo step 9.

**Il quasi-centro è reale ma minoritario.** Una proposta sbagliata su sette
dell'ibrido differisce dal bersaglio solo per il sottogruppo chimico: quattro
volte il tasso del caso (14,2% contro 3,4%), quindi non è rumore. Ma è il 14% dei
suoi errori, non il modo in cui il ranker sbaglia di solito.

**L'aneddoto dello step 9 indicava il ranker sbagliato.** Il caso della statina
veniva dal ranker *simbolico*, e il simbolico è quello che fa **meno**
quasi-centri di tutti i ranker che imparano: 4,8%. Il 43% dei suoi errori
condivide **solo l'apparato**. Il suo difetto non è «famiglia giusta, molecola
sbagliata»: è «cuore giusto, farmaco sbagliato».

Un solo esempio scelto a mano suggeriva una diagnosi, la misura su 244 ricoveri
ne dà un'altra. È la terza volta nel progetto che succede, e la regola è sempre
la stessa: un aneddoto mostra che un fenomeno *esiste*, mai quanto **pesa**.

### I due modelli linguistici sbagliano come il simbolico

`deepseek` e `qwen` hanno lo stesso profilo di errore del ranker a regole:
**51,6% degli errori nel solo apparato**, quasi-centri fra il 5,6% e il 6,9%. E
hanno la quota più bassa di proposte completamente fuori bersaglio (33–34%
contro il 67% del caso).

Traduzione: **propongono quasi sempre qualcosa di cardiovascolare, e quasi mai
la classe giusta.** Lo step 9 era arrivato alla stessa conclusione contando la
quota cardiovascolare delle prime cinque proposte; qui ci si arriva contando la
forma degli errori nell'albero ATC. Due misure indipendenti, stessa risposta —
ed è la forma di conferma che vale più di una misura ripetuta.

---

## 6. Quali differenze sopravvivono al campione

Tutte le cifre sopra sono puntuali su 196 ricoveri con bersaglio. Un bootstrap
da **1 000 ricampionamenti** dice quali differenze reggono.

Due scelte metodologiche, entrambe necessarie perché il numero non menta:

- **si ricampionano i pazienti, non le prescrizioni.** Le prescrizioni dello
  stesso ricovero non sono indipendenti fra loro, e trattarle come tali
  stringerebbe gli intervalli;
- **le differenze si calcolano dentro lo stesso giro**, su pazienti identici.
  Due ranker valutati sullo stesso campione sono correlati, e sottrarre due
  intervalli separati sovrastimerebbe l'incertezza.

Il seme è fisso, e un test verifica che due corse diano lo stesso intervallo: un
intervallo che cambia a ogni esecuzione non si può riportare.

| ranker | richiamo@5 esatto | hF |
|---|---|---|
| casuale | [4,7%, 9,8%] | [14,2%, 17,9%] |
| continuità | [8,7%, 14,9%] | [9,2%, 13,6%] |
| frequenza | [44,5%, 54,2%] | [43,8%, 50,4%] |
| ibrido | [48,1%, 58,1%] | [44,1%, 49,7%] |
| simbolico | [23,5%, 32,9%] | [26,2%, 32,3%] |
| `deepseek-v4.1-flash` | [19,9%, 28,9%] | [24,1%, 30,1%] |
| `qwen3.5:4b` | [15,9%, 23,8%] | [20,8%, 26,1%] |

### Le differenze appaiate

| differenza | richiamo@5 esatto | hF | |
|---|---|---|---|
| **ibrido − frequenza** | **[−0,2%, +7,5%]** | **[−2,0%, +1,7%]** | include lo zero |
| `deepseek` − frequenza | [−31,5%, −19,6%] | [−24,0%, −16,3%] | esclude lo zero |
| `deepseek` − `qwen` | [+0,1%, +8,2%] | [+1,0%, +6,0%] | esclude lo zero |

**Il risultato più importante dello step, e corregge lo step 9.** Lo step 9
riportava che l'ibrido batte la frequenza su tutte e cinque le metriche, con
margini «piccoli ma coerenti». Con il bootstrap: **la differenza non è
distinguibile da zero.** L'intervallo pende dalla parte giusta — sfiora lo zero a
−0,2 — ma non lo esclude.

Detto senza attenuazioni: **il miglior ranker del progetto non è misurabilmente
migliore di un contatore che non guarda il paziente**, su 196 ricoveri. La
direzione è coerente su cinque metriche e l'intervallo pende positivo; il
campione non basta a concluderlo.

Le altre due differenze invece **reggono**, e sono le due affermazioni dello step
9 che ora hanno un intervallo dietro:

- **il modello linguistico perde davvero contro un contatore**, e di molto: da 20
  a 31 punti di richiamo;
- **il modello grande ordina davvero meglio del piccolo**, ma per poco: il limite
  inferiore è +0,1 punti. Lo step 9 diceva «sopra il rumore di fondo»; è vero, e
  di un soffio.

---

## 7. Validazione incrociata: tutti gli 841 ricoveri come prova

Le sezioni precedenti usano una sola divisione: 597 ricoveri per imparare, 244
per misurare. Il bootstrap dice quanto quei 244 sono affidabili, ma non usa mai
gli altri 597 come prova.

Con **cinque pieghe** ogni ricovero è misurato una volta, da un ranker che non
lo ha mai visto in addestramento; l'insieme candidato è ricostruito a ogni piega
sulle altre quattro, così nessuna classe presente solo nella prova può entrare.
Il ranker con modello linguistico è escluso: servirebbero 600 chiamate nuove.

| ranker | ric@3 | **ric@5** | ric@10 | prec@5 | MAP |
|---|---|---|---|---|---|
| casuale | 3,2% | 5,3% | 10,8% | 2,8% | 0,075 |
| continuità | 10,1% | 10,6% | 13,2% | 6,6% | 0,108 |
| simbolico | 15,8% | 23,7% | 29,2% | 13,6% | 0,185 |
| frequenza | 32,6% | 47,5% | 65,2% | 26,5% | 0,402 |
| **ibrido** | **36,8%** | **48,5%** | **67,2%** | 26,6% | **0,425** |

Intervalli al 95%, 1 000 ricampionamenti su 841 ricoveri:

| differenza appaiata | richiamo@5 | hF | |
|---|---|---|---|
| **ibrido − frequenza** | **[−1,5%, +3,4%]** | [−1,8%, +0,4%] | include lo zero |
| ibrido − simbolico | [+21,7%, +28,0%] | [+14,6%, +17,9%] | esclude lo zero |
| frequenza − simbolico | [+20,9%, +26,9%] | [+15,2%, +18,7%] | esclude lo zero |

Tre cose cambiano, una no.

**La divisione singola era favorevole a chi impara.** L'ibrido scende da 53,1% a
**48,5%**, il simbolico da 28,0% a 23,7%, la frequenza da 49,5% a 47,5%. I 244
ricoveri di prova erano un campione un po' fortunato; con tutti gli 841 le cifre
si assestano più in basso, come ci si aspetta.

**Il vantaggio dell'ibrido si riduce a un punto** — 48,5% contro 47,5% — con
intervallo [−1,5%, +3,4%]: **dentro il pavimento di rumore del progetto e
attorno allo zero.** Non è più «coerente ma non distinguibile»: è
indistinguibile e basta. Sotto hF la frequenza è avanti.

**Il simbolico è nettamente sotto entrambi**, e ora lo si può dire con un
intervallo: da 21 a 28 punti di richiamo. È la tesi del §4 dello step 9 — *le
linee guida da sole sono un ranker peggiore del sapere che cosa si prescrive in
questo reparto* — con la misura che le mancava.

**L'effetto del denominatore resta identico.** Il caso guadagna 7,0 punti
salendo di un livello (5,3% → 12,3%), l'ibrido 7,7 (48,5% → 56,2%): il vantaggio
sul caso passa da +43,2 a +43,9, meno di un punto. La conclusione del §3 non
dipendeva dalla divisione.

Comando: `python3 src/valuta_gerarchica.py --pieghe 5`.

---

## 8. Una trappola trovata misurando

**Troncare i codici può *abbassare* il richiamo.** Succede su **15 ricoveri di
prova** reali:

```
bersagli: A10BK, C03CA, C03DA, N02BF
prime 5:  C03DA, B01AC, C03CA, B01AX, B01AA
          richiamo a 5 caratteri = 2/4 = 50%
          richiamo a 3 caratteri = 1/3 = 33%
```

`C03CA` (diuretici dell'ansa) e `C03DA` (antialdosteronici) collassano entrambi
in `C03`. **Due bersagli distinti centrati diventano un solo bersaglio
centrato**, e il denominatore scende da 4 a 3.

È il motivo per cui la tabella del §3 non è monotona, e per cui il richiamo
troncato da solo non basta: chi guardasse solo quella concluderebbe che la
metrica gerarchica è sempre più generosa, e non è vero. Un test lo fissa, così la
prossima «semplificazione» non lo cancella.

---

## 9. Che cosa lo step 11 lascia aperto

- **Il livello giusto resta una scelta, non una misura.** Lo step 11 mostra che
  salire di livello non migliora il confronto fra metodi; non dice quale livello
  un clinico voglia vedere. Quella domanda si risponde con un clinico, non con
  un corpus.
- **Il peso clinico degli errori non è modellato.** Proporre un gastroprotettore
  di troppo e mancare un antialdosteronico contano uguale in ogni tabella di
  questo documento. Sono errori molto diversi, e distinguerli richiederebbe una
  scala di gravità — che sarebbe una fonte in più da citare, non una formula da
  inventare.
- **Il ranker con modello linguistico non è nella validazione incrociata.**
  I suoi numeri restano quelli della divisione singola (§3–6); rimisurarlo su
  tutti gli 841 costerebbe circa 600 chiamate, che per il modello remoto sono
  altri 35 centesimi e per il locale quattro ore di CPU.
