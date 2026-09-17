# Step 6bis — Il riferimento annotato: il richiamo, misurato per la prima volta

**Stato:** completato.
**Riproducibilità:** `python3 src/riferimento.py` (il riferimento sta in `data/processed/riferimento/`, non versionato)

Lo step 6 confrontava le pipeline fra loro e ne misurava la precisione a
campione; nessuno sapeva che cosa **mancasse**. Questo step costruisce un
riferimento annotato a mano su 25 referti e misura precisione, richiamo e F1
di ciascuna pipeline contro di esso. Il brief non prevede l'annotazione
manuale: qui è una **verifica del metodo**, non parte del metodo — senza un
riferimento non c'è modo di sapere se il sistema funzioni.

---

## 1. Che cosa è, e che cosa non è

È il giudizio di **un solo annotatore**, che è anche l'autore delle pipeline.
Il conflitto è reale e va mitigato, non negato: i 25 referti (estratti a caso
con seme `20260914`, lunghezze rappresentative del corpus: mediana 1 786
caratteri contro 1 664) sono stati annotati **alla cieca**, leggendo solo il
testo grezzo, con linee guida **fissate prima** di annotare. Un'eccezione
dichiarata: dopo i primi cinque referti ho visto le metriche aggregate per
verificare il caricatore, non le singole menzioni.

Senza un secondo annotatore non c'è misura di accordo (in letteratura, fra
professionisti, κ 0,7–0,9). Il progetto è individuale e il limite resta
dichiarato: il riferimento è **utilizzabile e dichiarato**, non una verità.

## 2. Le linee guida, in breve

**Condizione**: malattie e diagnosi anche pregresse, sintomi e segni, reperti
strumentali anomali, fattori di rischio riconosciuti, stati rilevanti («in
dialisi», «portatore di pacemaker»). **Non** condizione: procedure, esami
normali, misure nude senza giudizio, abitudini. **Farmaco nella prosa**: ogni
principio o nome commerciale citato nell'anamnesi, fuori dai campi di
terapia. **Confini**: il grado si annota (`stenosi aortica severa`), i
marcatori di contesto no. **Attributi**: stato (affermato / negato /
incerto) e soggetto (paziente / familiare). Ripetizioni: ogni occorrenza.

**Allineamento**: un'entità del riferimento è coperta da **una sola**
menzione sovrapposta; una pipeline che frammenta paga in precisione. Totale
atteso: **559 condizioni, 60 farmaci narrati**.

## 3. Il risultato

| condizioni | attese | trovate | VP | FP | FN | precisione | **richiamo** | F1 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A · gazetteer | 559 | 136 | 109 | 27 | 450 | 80,1% | **19,5%** | 31,4% |
| B · modello linguistico | 559 | 408 | 392 | 16 | 167 | **96,1%** | **70,1%** | **81,1%** |
| C · NER su silver | 559 | 136 | 111 | 25 | 448 | 81,6% | **19,9%** | 31,9% |

| farmaci nella prosa | attese | trovate | VP | FP | FN | precisione | **richiamo** | F1 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 60 | 41 | 39 | 2 | 21 | 95,1% | 65,0% | 77,2% |
| B, prima corsa | 60 | **0** | 0 | 0 | 60 | 0,0% | **0,0%** | 0,0% |
| B, prompt corretto (§5) | 60 | 55 | 50 | 5 | 10 | 90,9% | **83,3%** | **87,0%** |
| C | 60 | 44 | 42 | 2 | 18 | 95,5% | 70,0% | 80,8% |

**Sulle condizioni il divario è strutturale**: A e C mancano quattro
condizioni su cinque perché il loro vocabolario è la loro definizione di
realtà clinica, e nessuna correzione lo cambia. È la ragione dello step 7:
il grafo tiene insieme tre descrizioni parziali con la provenienza.

**Un controllo indipendente che torna.** La precisione di B qui (96,1%) e
quella dello step 6 su 60 menzioni esclusive aggiudicate a mano (91,7% ± 3,6)
sono due misure su insiemi diversi, e cadono a un paio di punti l'una
dall'altra.

## 4. Una seconda passata, dichiarata

Alla prima misura B aveva 25 falsi positivi; letti uno per uno, **nove erano
miei errori di annotazione** («MAV», «SARS CoV2», «emorragia cerebrale
post-traumatica» non annotate; «angor» con un indice troppo stretto). Il
riferimento è stato corretto **solo** dove le linee guida scritte prima lo
dicevano senza ambiguità; i casi opinabili («protesi ginocchio» è uno stato
rilevante?) restano contati come errori di B. Effetto: precisione di B da
93,9% a 96,1%, richiamo da 69,8% a 70,1%. Correggere il riferimento dopo aver
visto un'uscita è il punto più fragile del documento, e le correzioni sono
tracciabili una per una proprio per questo.

## 5. Lo zero sui farmaci non era del modello: era mio

Lo 0/60 di B sui farmaci narrati sembrava una cecità. Verificato in tre
passi, che valgono come metodo per ogni cifra estrema:

1. **Sui dati grezzi**: nel corpus intero B estraeva farmaci dalla prosa in 20
   referti su 1 000. Con un tasso del 2%, vederne zero in 25 referti ha
   probabilità 60%: era campionamento, non cecità.
2. **Nelle istruzioni**: la regola del prompt definiva i farmaci come «il
   contenuto delle sezioni di terapia». Il modello faceva ciò che gli era
   chiesto. Seconda volta nello step 4 che un difetto attribuito al modello
   era nel prompt.
3. **Con un esperimento economico**: regola riscritta («il fatto, non il
   nome»), rimisurata sui soli 30 referti del riferimento invece che sul
   corpus. Richiamo **0% → 83,3%**, precisione 90,9%, e 3,0 farmaci per
   referto contro i 2,4 attesi.

Il prezzo sulle condizioni sembrava di due punti (70,1% → 68,2%) e non lo
era: una terza corsa rende 70,1%. Quello che si è misurato è il **rumore fra
corse dello stesso modello sugli stessi record: circa due punti di richiamo**.
È il pavimento di rumore del progetto: nessuna differenza sotto i due punti
va letta come un effetto.

## 6. Limiti

* Un annotatore, nessun accordo inter-annotatore: limite dichiarato del
  progetto individuale.
* Gli attributi (stato, soggetto) sono annotati ma non valutati contro il
  riferimento.
* 25 referti dicono l'ordine di grandezza del richiamo (20% contro 70%), non
  il secondo decimale: l'intervallo su 559 condizioni è di circa ±4 punti.
