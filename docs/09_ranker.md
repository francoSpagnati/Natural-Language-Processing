# Step 9 — I tre ranker: che cosa proporre, e in che ordine

**Stato:** completato; i numeri definitivi (validazione incrociata, intervalli, livello di sostanza) sono nello [step 11](11_valutazione.md).
**Riproducibilità:** `python3 src/valuta_ranker.py` (senza modello linguistico, gratis)

Il filtro dello step 8 dice che cosa **non** si può dare, e su 5 863
prescrizioni reali ne vieta quattro: è una rete di sicurezza, non un
suggeritore. Lo step 9 ordina ciò che il filtro lascia passare. Codice:
[`src/ranker.py`](../src/ranker.py), [`src/valuta_ranker.py`](../src/valuta_ranker.py);
le 27 indicazioni stanno in [`kb/conoscenza.ttl`](../kb/conoscenza.ttl).

---

## 1. Il bersaglio è gratuito, ed è il primo risultato

La verità di riferimento non va annotata: **è già nei dati.** La terapia alla
dimissione è la decisione che un cardiologo ha davvero preso, scritta nel
referto; su 1 000 ricoveri, **841** ne hanno una codificata. Lo step misura
quindi su 841 ricoveri invece che sui 25 annotati a mano, e nessuno ha dovuto
decidere che cosa fosse giusto.

Il limite, detto prima dei numeri: è **una** decisione giusta, non l'insieme
delle decisioni giuste. Una classe proposta e non prescritta non è per forza
un errore. Ne segue che **il richiamo è la metrica che conta** e la precisione
va letta con cautela: un supporto alla decisione si giudica da ciò che *non*
suggerisce.

## 2. L'unità: la classe, non la molecola

Il ranker propone classi ATC a cinque caratteri (`C07AB` betabloccanti
selettivi, non il bisoprololo). La scelta della molecola dentro la classe è
del reparto e del prontuario, non della linea guida; il brief stesso ammette
«farmaci diversi ma della stessa classe». Lo step 11 misura anche con unità =
sostanza (7 caratteri, il quinto livello ATC): i due ranker migliori
cambiano di rango, e il perché è lì.

## 3. I due compiti, e la linea di base che tiene onesto tutto

Misurato sul corpus, per ricovero: 6,78 classi alla dimissione, di cui
**63,6% già presenti all'ingresso** (3 627) e 36,4% nuove (2 075); 970
sospese.

**Compito 1, la terapia completa**, esiste solo per mostrare che è quasi
risolto senza ragionare: copiare la terapia in atto fa il 63,6%, e batte ogni
ranker (richiamo@5 56,4% contro 40,9% della frequenza). Senza questo numero
un 65% sembrerebbe un risultato.

**Compito 2, le sole aggiunte**: 2 075 decisioni, 2,47 per ricovero. È il
compito vero, e tutto il resto del documento lo riguarda.

## 4. Il tetto del ranker simbolico, noto prima di misurarlo

Il **40,4%** delle prescrizioni di dimissione (41,7% delle aggiunte) non è
cardiologia: gastroprotettori (`A02BC`, 525 prescrizioni, 209 nuove),
antidiabetici, allopurinolo, levotiroxina, potassio, corticosteroidi topici
(59, tutti nuovi). Nessuna linea guida cardiologica li regola. Un ranker a
linee guida ha quindi un tetto **per costruzione**, misurato prima di
scrivere una regola; sapere che cosa si prescrive in questo reparto vale più
che sapere la medicina.

## 5. Le 27 indicazioni

Curatela manuale con fonte per riga — ESC 2021 e aggiornamento 2023
(scompenso), ESC 2024 (fibrillazione atriale), ESC 2023 (sindromi coronariche;
diabete), ESC/ESH 2024 (ipertensione), ESC/EAS 2019 (dislipidemie) — ciascuna
con la classe di raccomandazione I / IIa / IIb. Vivono nel grafo di
conoscenza (`kb_build.py` le scrive, `conoscenza.py` le legge, il ranker le
riceve). Due forme che hanno richiesto un campo apposta:

* **un'indicazione innescata da una terapia, non da una diagnosi**
  (`atc_richiesto`): la gastroprotezione è indicata dall'antitrombotico che
  il paziente prende. Senza quel campo `A02BC`, seconda classe più prescritta
  del corpus, resterebbe fuori;
* **il fatto mancante** (`fatto_non_estratto`), su 5 regole: i quattro pilastri
  dello scompenso valgono per la frazione di eiezione ridotta, che nessuna
  pipeline estrae; l'anticoagulazione nella fibrillazione dipende da età e
  sesso; l'ezetimibe dal valore di LDL. La regola resta, declassata da certa a
  plausibile: stesso principio dello step 8, un livello più in basso.

## 6. I tre ranker, e due linee di base

| ranker | come decide | che cosa gli serve |
|---|---|---|
| continuità | ripropone la terapia in atto | niente |
| frequenza | le classi più aggiunte nel reparto, **senza guardare il paziente** | i casi di addestramento |
| **simbolico** | peso della migliore indicazione che scatta (il massimo, non la somma: tre IIa non fanno una I) | le 27 indicazioni |
| **ibrido** | simbolico + co-occorrenza condizione→classe misurata sul corpus | entrambi |
| **con modello linguistico** | il modello ordina i candidati già filtrati | inferenza |

**Un errore corretto nell'ibrido.** La prima versione ordinava per
informazione mutua puntuale e faceva *peggio* della frequenza (26,3% contro
49,5%). La PMI è un guadagno, non una probabilità: mette in cima le classi
*specifiche* e in fondo quelle *probabili*, mentre la domanda è quale classe
verrà aggiunta. Corretto lavorando in logaritmo: `log P(classe | condizione)
= log P(classe) + PMI`, così **l'ibrido non può fare peggio della frequenza
per costruzione** — a evidenza zero ricade su di essa — e un test lo fissa.
Il peso delle linee guida rispetto all'abitudine è tarato su una parte di
validazione ritagliata dall'addestramento, mai sulla prova: fra peso 0 e
peso 1 il richiamo@5 varia di meno di un punto, a peso 8 perde dieci punti.

## 7. Il risultato sulla divisione singola (597 addestramento, 244 prova)

| compito 2, le aggiunte | ric@3 | ric@5 | ric@10 | prec@5 | MAP |
|---|---|---|---|---|---|
| continuità | 10,4% | 11,7% | 12,5% | 6,9% | 0,114 |
| frequenza | 36,8% | 49,5% | 67,2% | 27,9% | 0,426 |
| simbolico | 20,3% | 28,0% | 31,0% | 15,1% | 0,210 |
| **ibrido** | **38,8%** | **53,1%** | **70,2%** | 27,7% | **0,456** |
| `deepseek-v4.1-flash`, remoto | 18,0% | 24,0% | 36,7% | — | 0,219 |
| `qwen3.5:4b`, locale | 14,2% | 19,7% | 27,6% | — | 0,178 |

Su questa divisione l'ibrido batteva la frequenza su tutte le metriche, di
2–3,6 punti, «coerenti». **Rivisto allo step 11**: con la validazione
incrociata su tutti gli 841 ricoveri il vantaggio scende a un punto (48,5%
contro 47,5%), intervallo [−1,5%, +3,4%]: a livello di classe i due sono
**indistinguibili**, e questa divisione era un campione favorevole a chi
impara. A livello di sostanza, invece, l'ibrido è avanti di 4–9 punti. Vedi
[`11_valutazione.md`](11_valutazione.md) §7 e §10.

**Il simbolico perde anche quando ha ragione.** Un paziente con aterosclerosi
riceve dal simbolico `C10AA` statina, classe I; il medico ha prescritto
`C10BA`, statina in associazione. Stessa famiglia, contata come errore. Da
qui la metrica gerarchica dello step 11 — che ha poi mostrato che quei punti
li guadagna anche un ranker casuale.

**I modelli linguistici perdono contro il contatore**, e la ragione è
misurabile: fra le prime cinque proposte, l'84,5% di `deepseek` e l'82,6% di
`qwen` sono classi cardiovascolari (l'ibrido: 74,3%). Sono ottimi ranker di
linee guida, e prendono in pieno il tetto del §4: nessuna linea guida dice di
aggiungere un gastroprotettore, e in questo reparto lo si aggiunge 209 volte.

## 8. Il filtro non toglie niente, e la ragione è corretta

Sui 244 ricoveri di prova il filtro esclude **zero** classi. Tre cause,
verificate una per una: il filtro giudica farmaci a 7 caratteri e il ranker
propone classi a 5 (la metformina `A10BA02` non tocca nessuna classe, ed è
giusto: gli altri antidiabetici non sono controindicati); le allergie
codificate sono 57 in 841 ricoveri, tutte a livello di sostanza (il 93% dei
ricoveri non ne ha nessuna); le due regole che potevano scattare sono
declassate dal principio del fatto mancante.

Il prefisso di classe non è la soluzione, misurato: bloccherebbe il
clopidogrel `B01AC04` a un allergico all'aspirina `B01AC06`, che è
*precisamente* l'alternativa corretta. È la terza volta che una regola troppo
larga nega una terapia giusta. Al livello di classe l'allergia a una sostanza
è quindi un **avvertimento** che viaggia con la proposta (`allerta_di_classe`,
14 su 244), non un divieto.

## 9. Il ranker con modello linguistico

**Il vincolo all'insieme candidato è sicurezza.** Alla prima prova il modello
ha restituito nove codici da un elenco di otto: il nono ricopiato dalla
terapia in atto. Un codice fuori elenco scavalca il filtro dello step 8. Sulla
corsa completa:

| codici fuori elenco, 244 ricoveri | `deepseek-v4.1-flash` | `qwen3.5:4b` |
|---|---|---|
| proposti (scartati) | 18 | 40 |
| esistenti nel registro AIFA | 18 su 18 | **25 su 40** |
| già nella terapia del paziente | 18 su 18 | 7 su 40 |

Il modello grande non allucina: ricopia. Il piccolo **enumera l'albero ATC**
(`R05AA`…`R05AG`, sette suffissi consecutivi, nessuno esistente): per lui il
vincolo non è igiene, è ciò che lo rende utilizzabile.

**Uno schema senza `maxItems` non termina.** Sotto decodifica vincolata il
modello locale ha prodotto 310 voci da 91 candidati fino a saturare il
contesto; il sintomo era lentezza, non errore. Con il tetto: da oltre 240 s a
24 s per ricovero.

| | `qwen3.5:4b` locale | `deepseek-v4.1-flash` remoto |
|---|---|---|
| richiamo@5 sulle aggiunte | 19,7% | **24,0%** |
| risposte che ricalcano l'ordine d'ingresso | 9 / 244 | 2 / 239 |
| durata | 1 h 34 min | 22 min |
| costo | 0 $ | 0,1425 $ |

## 10. Che cosa resta aperto

* Il dosaggio non è modellato: una raccomandazione senza posologia è
  incompleta.
* Frazione di eiezione, punteggio CHA₂DS₂-VA e valori di laboratorio restano
  i tre fatti che più limitano le regole.
* La precisione non è interpretabile come correttezza (§1).
