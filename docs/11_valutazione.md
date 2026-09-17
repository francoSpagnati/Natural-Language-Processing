# Step 11 — La valutazione: che cosa sopravvive al campione

**Stato:** completato.
**Riproducibilità:** `python3 src/valuta_gerarchica.py --pieghe 5` (gratis); `--sostanza` per l'unità a 7 caratteri; `--stratifica` per le pieghe stratificate; `--cartella-b data/processed/pipeline_a` per la pipeline A; `--llm openrouter` per il ranker remoto (in cache: non costa)

Lo step 9 aveva misurato i ranker su una divisione singola (597 addestramento,
244 prova) con il richiamo esatto sulla classe. Qui si mette dietro ogni
numero ciò che gli mancava: la **gerarchia** ATC (un antenato del codice
giusto vale qualcosa), un **controllo casuale**, la **validazione incrociata**
su tutti gli 841 ricoveri, gli **intervalli** al 95%, l'unità di misura
alternativa, l'effetto dell'estrazione, e una misura della spiegabilità.
Codice: [`src/valuta_gerarchica.py`](../src/valuta_gerarchica.py).

---

## 1. Il protocollo

- **Compito**: le 2 075 classi ATC aggiunte alla dimissione su 841 ricoveri
  (le sole aggiunte, non la terapia intera: copiare l'ingresso fa già 63,6%).
- **Unità**: la classe a 5 caratteri (`C07AB`); nel §9 la sostanza a 7.
- **Validazione incrociata a 5 pieghe**: pieghe deterministiche per hash del
  ricovero (`ranker.pieghe`), il ranker impara sulle altre quattro, l'insieme
  candidato è ricostruito a ogni piega (nessuna classe presente solo nella
  prova può entrare), ogni ricovero misurato una volta.
- **Bootstrap**: 1 000 ricampionamenti *dei ricoveri* (non delle
  prescrizioni, che non sono indipendenti) con seme fisso; le differenze fra
  ranker sono calcolate dentro lo stesso ricampionamento (**appaiate**).
- **Controllo**: un ranker casuale con seme 20260916, scritto prima dei
  risultati.
- **Gerarchia**: l'ATC è un albero (`C` → `C07` → `C07A` → `C07AB` → `C07AB07`);
  il richiamo per livello tronca proposte e bersagli; hP/hR/hF sono
  precisione, richiamo e F sull'insieme degli antenati (Kiritchenko, Matwin,
  Famili, *Functional annotation of genes using hierarchical text
  categorization*, BioLINK SIG 2005; Silla & Freitas, *A survey of
  hierarchical classification across different application domains*, Data
  Mining and Knowledge Discovery 22, 2011, doi:10.1007/s10618-010-0175-9).
- **Rumore di fondo**: due punti percentuali (step 6bis).

## 2. Il risultato principale

| ranker · 5 pieghe, 841 ricoveri | ric@3 | **ric@5** | ric@10 | prec@5 | MAP | intervallo ric@5 | hF |
| --- | --- | --- | --- | --- | --- | --- | --- |
| casuale, seme fisso | 3,2% | 5,3% | 10,8% | 2,8% | 0,075 | [4,0%, 6,5%] | 14,6% |
| continuità della terapia | 10,1% | 10,6% | 13,2% | 6,6% | 0,108 | [9,1%, 12,2%] | 12,1% |
| simbolico, 27 indicazioni ESC | 15,8% | 23,7% | 29,2% | 13,6% | 0,185 | [21,5%, 25,8%] | 28,6% |
| frequenza, non guarda il paziente | 32,6% | 47,5% | 65,2% | 26,5% | 0,402 | [44,8%, 50,3%] | **45,5%** |
| **ibrido** | **36,8%** | **48,5%** | **67,2%** | 26,6% | **0,425** | [45,7%, 51,1%] | 44,8% |
| `deepseek-v4.1-flash` (§10) | 15,8% | 21,7% | 33,7% | 12,0% | 0,205 | [19,4%, 24,0%] | 24,5% |

| differenza appaiata | richiamo@5 | hF | |
| --- | --- | --- | --- |
| **ibrido − frequenza** | **[−1,5%, +3,4%]** | [−1,8%, +0,4%] | include lo zero: **indistinguibili** |
| ibrido − simbolico | [+21,7%, +28,0%] | [+14,6%, +17,9%] | esclude lo zero |
| frequenza − simbolico | [+20,9%, +26,9%] | [+15,2%, +18,7%] | esclude lo zero |
| `deepseek` − frequenza | [−29,2%, −22,5%] | [−23,1%, −19,0%] | esclude lo zero |
| `deepseek` − simbolico | [−4,2%, +0,3%] | [−5,6%, −2,4%] | alla pari sul richiamo |

Tre cose si possono dire e una no. **Il simbolico è sotto entrambi** di 21–28
punti: le linee guida da sole sono un ranker peggiore del sapere che cosa si
prescrive in questo reparto. **Il modello linguistico è sotto il contatore**
di 22–29 punti, e alla pari con il simbolico: si comporta come un ranker di
linee guida. **L'ibrido e la frequenza sono indistinguibili** a livello di
classe: un punto sul richiamo, e sotto hF è avanti la frequenza. Quello che
non si può dire è «l'ibrido è il migliore».

La divisione singola dello step 9 (ibrido 53,1%, frequenza 49,5%, «coerente
su cinque metriche») era un campione favorevole a chi impara: con tutti gli
841 le cifre si assestano più in basso e il vantaggio sparisce.

## 3. Il controllo casuale: i punti gerarchici erano aritmetica

| richiamo@5 per livello, 5 pieghe | 1° `C` | 2° `C07` | 3° `C07A` | 4° `C07AB` | sopra il caso, 4° → 1° |
| --- | --- | --- | --- | --- | --- |
| **casuale** | **54,6%** | 17,9% | 12,3% | 5,3% | — |
| continuità | 20,7% | 11,7% | 11,0% | 10,6% | +5,3 → −33,9 |
| simbolico | 58,2% | 36,6% | 32,1% | 23,7% | +18,4 → +3,6 |
| `deepseek` | **45,1%** | 31,4% | 26,4% | 21,7% | +16,4 → **−9,4** |
| frequenza | 77,1% | 55,3% | 55,0% | 47,5% | +42,2 → +22,5 |
| ibrido | 80,0% | 58,7% | 56,2% | 48,5% | +43,2 → +25,4 |

Lo step 9 anticipava che contare gli antenati avrebbe valso 4–7 punti. Li
vale — ma li guadagna anche il ranker casuale, perché con meno foglie è più
facile indovinarne una. Il vantaggio dell'ibrido *sul caso* passa da +43,2 a
+43,9 salendo di un livello, e crolla ai livelli alti dove il caso arriva al
54,6%. La metrica gerarchica non regala niente a chi non lo merita; senza il
controllo, quei punti sarebbero stati raccontati come un risultato.

**Al primo livello `deepseek` sta sotto il caso** (45,1% contro 54,6%). Non
legge male: propone la cardiologia giusta, e il 40,4% dei bersagli non è
cardiologia. È lo stesso tetto del ranker simbolico, preso da un motore molto
più costoso.

**Dove cadono le proposte sbagliate.** Fra le proposte non esatte, la quota
che sbaglia «di poco» (stesso gruppo farmacologico, foglia diversa) è 16,0%
per la frequenza e 12,5% per l'ibrido, 6,3% per il simbolico, 5,6% per
`deepseek`: il caso della statina (§4) non riguarda i ranker a linee guida.
Simbolico e modello linguistico sbagliano invece **famiglia** (39,7% e 46,0%
di errori al primo livello): propongono cardiologia dove serviva altro.

## 4. Il caso della statina, contato

Lo step 9 raccontava un paziente con aterosclerosi a cui il simbolico
proponeva `C10AA` statina e il medico prescriveva `C10BA` statina in
associazione: un quasi-centro contato come errore. Contato su tutti i
ricoveri, l'aneddoto indicava il ranker sbagliato: il simbolico è quello che
fa **meno** quasi-centri di tutti (6,3%); ne fanno la frequenza e l'ibrido,
che propongono più molecole vicine. E il 40% dei suoi errori è di famiglia:
non «statina sbagliata», ma «cardiologia dove non serviva».

## 5. Una trappola trovata misurando

**Troncare i codici può *abbassare* il richiamo.** Su 15 ricoveri reali:

```text
bersagli: A10BK, C03CA, C03DA, N02BF
prime 5:  C03DA, B01AC, C03CA, B01AX, B01AA
          richiamo a 5 caratteri = 2/4 = 50%
          richiamo a 3 caratteri = 1/3 = 33%
```

`C03CA` e `C03DA` collassano entrambi in `C03`: due bersagli distinti centrati
diventano uno solo, e il denominatore scende. È il motivo per cui le righe
del §3 non sono monotone; un test lo fissa, così la prossima
«semplificazione» non lo cancella.

## 6. Con l'unità = sostanza, «il migliore» cambia

Il brief chiede il quinto livello ATC (la sostanza, 7 caratteri). Con
`--sostanza` candidati, bersagli e proposte lavorano a 7 caratteri:

| 5 pieghe, unità sostanza | ric@3 | **ric@5** | ric@10 | MAP | hF |
| --- | --- | --- | --- | --- | --- |
| casuale | 2,9% | 4,2% | 7,3% | 0,056 | 15,0% |
| simbolico | 6,9% | 9,4% | 14,4% | 0,098 | 19,6% |
| frequenza | 25,0% | 38,0% | 56,2% | 0,336 | 42,9% |
| **ibrido** | **33,1%** | **44,3%** | **58,5%** | **0,402** | **44,4%** |

| differenza appaiata, sostanza | richiamo@5 | hF | |
| --- | --- | --- | --- |
| **ibrido − frequenza** | **[+4,1%, +8,7%]** | [+0,5%, +2,6%] | **esclude lo zero** |
| ibrido − simbolico | [+32,4%, +37,8%] | [+22,9%, +26,7%] | esclude lo zero |

A livello di classe l'ibrido e la frequenza sono indistinguibili; a livello
di sostanza l'ibrido è avanti di 4–9 punti. Il simbolico crolla dal 23,7% al
9,4%: **una linea guida indica la classe, non la molecola**, e fra le
molecole di una classe il simbolico non sa ordinare, mentre la co-occorrenza
sì. Il richiamo assoluto è più basso (44% contro 48%) perché il bersaglio è
più fine. La risposta a «qual è il ranker migliore?» dipende dall'unità, e
va detta così.

## 7. L'estrazione conta poco sul ranking

La metrica secondaria del brief: la stessa valutazione con lo stato paziente
estratto da ciascuna pipeline (i farmaci dei campi di terapia sono identici;
cambiano le condizioni).

| ric@5, 5 pieghe | da A (gazetteer) | da B (modello) | da C (NER) |
| --- | --- | --- | --- |
| frequenza | 47,4% | 47,5% | 47,5% |
| simbolico | 21,2% | **23,7%** | 21,2% |
| ibrido | 48,9% | 48,5% | 49,0% |
| ibrido − frequenza | [−0,9%, +3,7%] | [−1,5%, +3,4%] | [−0,9%, +3,7%] |

Il richiamo di B sulle condizioni (70% contro 20%) vale **2,5 punti al
ranker simbolico** — al pavimento di rumore — e nulla all'ibrido, dominato
dalla frequenza. Quel che l'estrazione migliore aggiunge lo assorbe la
statistica di reparto.

## 8. La spiegabilità, contata invece che affermata

Se l'ibrido non batte la frequenza sul richiamo, ciò che lo distingue va
misurato: quante proposte fra le prime cinque hanno almeno un'indicazione
ESC che scatta per quel paziente, e quante fra quelle **centrate**.

| 5 pieghe, classe | proposte motivate | centri | centri motivati |
| --- | --- | --- | --- |
| casuale | 4,5% | 96 | 26,0% |
| frequenza | 20,9% | 900 | 30,8% |
| ibrido | 29,5% | 904 | 34,8% |
| simbolico | 68,4% | 464 | 81,7% |
| `deepseek` | 46,8% | 407 | 65,8% |

Il vantaggio dell'ibrido sulla frequenza è di quattro punti, non una
differenza di categoria: due terzi dei suoi centri sono co-occorrenza — «in
questo reparto si fa» — e il sistema lo dichiara per ogni proposta. Il ranker
davvero spiegabile è il simbolico, che centra la metà; il modello linguistico
sta in mezzo, come un ranker di linee guida imperfetto.

## 9. Il ranker LLM su tutti gli 841

Il ranker con modello linguistico non impara dai casi, quindi le pieghe non
gli servono: è misurato su tutti gli 841 ricoveri con l'insieme candidato
della divisione singola, così le 244 risposte già pagate allo step 9 arrivano
dalla cache. Costo delle 597 nuove: **0,34 $** (tetto di spesa nel codice;
totale del progetto 4,79 $). 68 codici fuori elenco scartati.

Richiamo@5 **21,7%** [19,4%, 24,0%], contro frequenza [−29,2%, −22,5%], contro
ibrido [−30,1%, −23,7%], contro simbolico [−4,2%, +0,3%]. Il modello locale
(`qwen3.5:4b`, 19,7% sulla divisione singola) non è stato rimisurato: quattro
ore di CPU per confermare un numero che sta sotto.

## 10. Pieghe stratificate, e tre casi reali per codici

**Stratificazione.** Il brief chiede pieghe stratificate per patologia
principale. Con `--stratifica` (strati I50, I48, I25, I10, altro; dentro ogni
strato i casi vanno nelle pieghe a turno in ordine di impronta): ibrido
46,8%, frequenza 47,1%, simbolico 22,7%; ibrido − frequenza **[−3,0%,
+2,0%]** sul richiamo, [−2,8%, −0,4%] su hF. La conclusione non dipende
dalle pieghe: indistinguibili sul richiamo, e sotto hF la frequenza è avanti.

**Tre ricoveri di prova, solo per codici** (il testo non si mostra; le prime
cinque proposte dell'ibrido a 5 pieghe, con il livello ATC a cui ogni
proposta incontra un bersaglio: 4 = classe esatta, 0 = nessuna famiglia in
comune).

| ricovero | condizioni estratte | terapia in atto | aggiunte vere | ibrido, prime 5 → livello |
| --- | --- | --- | --- | --- |
| 10235556 | *nessuna* | *nessuna* | A02BC, A10BK, B01AC, C03CA, C03DA, C07AB, C09CA, C10BA | A02BC → 4, C03DA → 4, C07AB → 4, C03CA → 4, B01AC → 4 |
| 9799541 | I31.3, J95, N19, R56.0 | *nessuna* | A02BC, B01AC, J01DD, M02AA | C03DA → 0, D07AC → 0, A02BC → 4, M04AC → 1, B01AX → 3 |
| 10067375 | E11, I10, I42.6, I48, I48.1 | A10BK, B01AF, C01BD, C03DA, C07AB, C09AA, C10AA | M04AC | B01AX → 0, A02BC → 0, B01AA → 0, C08CA → 0, C09CA → 0 |

Il primo è il caso più istruttivo: **l'estrazione non ha trovato nulla** e il
ranker centra 5 su 5 — perché con zero fatti l'ibrido ricade sulla frequenza,
e in questo reparto un ricovero senza terapia d'ingresso riceve i quattro
pilastri più il gastroprotettore. È la tesi 4 in un ricovero solo. Il
simbolico, senza fatti, restituisce i candidati in ordine alfabetico
(`A02AD`, `A02BC`, …): un artefatto della parità, che vale la pena vedere. Il
secondo è un paziente non cardiologico (versamento pericardico, insufficienza
respiratoria e renale): il medico aggiunge un antibiotico e un antiinfiammatorio
topico, che nessun ranker può prevedere dal profilo. Il terzo sbaglia a ogni
livello: un paziente in fibrillazione già trattato con tutto, a cui viene
aggiunta la colchicina `M04AC` — la ragione (una pericardite? la gotta?) non
è fra le condizioni estratte. Il sistema sbaglia dove il fatto che decide non
c'è, ed è coerente con tutto il resto del progetto.

## 11. Che cosa resta aperto

- **Il riferimento è una decisione di un medico** per ricovero: la precisione
  non è interpretabile come correttezza.
- **Il dosaggio non è modellato.**
- **Frazione di eiezione, punteggio CHA₂DS₂-VA, valori di laboratorio e
  dispositivi** restano i fatti non estratti che limitano le regole.
