# Step 6 — Il confronto fra le tre pipeline

**Stato:** completato.
**Riproducibilità:** `python3 src/confronto.py` (le uscite di A, B e C sono in `data/processed/`)

Le tre pipeline hanno prodotto lo stesso `StatoPaziente` sugli stessi 1 000
referti. Questo step le confronta: chi vede che cosa, quanto concordano sugli
attributi, chi ha ragione dove divergono. **Non è un confronto contro una
verità** — quella arriva allo step 6bis — ma un confronto **fra** metodi, con
un'aggiudicazione a mano di un campione delle menzioni esclusive, come il
brief §3.2 D chiede.

---

## 1. Tre decisioni di disegno, imposte dai dati

**Prosa e campi strutturati vanno separati.** Sui campi di terapia A e C
danno numeri identici perché usano lo stesso parser: confrontarli lì
misurerebbe zero per costruzione. Il confronto vale sulla prosa dell'anamnesi.

| sui 1 000 record | A | B | C |
| --- | --- | --- | --- |
| condizioni dalla prosa | 5 237 | 16 639 | 5 420 |
| farmaci dalla prosa | 2 332 | 62 (prima della correzione dello step 6bis) | 2 542 |
| farmaci dalla terapia d'ingresso | 5 494 | 5 761 | 5 494 |

**I farmaci che B elenca come condizioni si riclassificano**, non si
scartano: sono voci giuste nel tipo sbagliato, e cancellarle farebbe sembrare
B più precisa di quanto sia.

**L'allineamento non dipende dai confini.** Due menzioni sono la stessa quando
i loro intervalli di caratteri si sovrappongono nello stesso campo dello
stesso ricovero: il gazetteer aggancia il termine di vocabolario, il NER
l'estensione appresa, il modello spesso la frase intera. Le menzioni
collegate formano un grafo; ogni componente connessa è un «punto» del
referto. Le componenti in cui una pipeline mette più di una menzione restano
marcate come ambigue e non si confrontano sugli attributi.

## 2. Chi vede che cosa, nella prosa

| punti visti da | n |
| --- | --- |
| A, B e C | 3 626 |
| A e C | 3 683 |
| B e C | 231 |
| A e B | 52 |
| **solo B** | **12 511** |
| solo C | 325 |
| solo A | 145 |

A e C si sovrappongono quasi del tutto (C è addestrata sulle etichette di
A); B vede un mondo a parte, tre volte più grande. La domanda è quanto di
quel mondo sia vero.

## 3. L'aggiudicazione a mano: il risultato centrale

Un campione casuale delle menzioni esclusive di ciascuna pipeline, giudicato
a mano con linee guida scritte prima.

| | campione | corrette | precisione (±) | **errori che portano un codice** |
| --- | --- | --- | --- | --- |
| B (remota) | 60 | 55 | **91,7% ± 3,6** | 1 su 5 (20%) |
| A | 30 | 22 | 73,3% ± 8,1 | **7 su 8 (88%)** |
| C | 30 | 20 | 66,7% ± 8,6 | 0 su 10 (0%) |

Gli intervalli di A e C si sovrappongono: fra quelle due il numero non
ordina niente. **La riga che separa le pipeline è l'ultima**, e non dipende
dal campione: A riconosce e codifica in un passo solo, quindi un
riconoscimento sbagliato nasce già codificato — ed è esattamente ciò che il
filtro di sicurezza userebbe senza accorgersene. B e C riconoscono prima e
collegano dopo: un errore di norma non aggancia nulla e resta visibile.

Gli errori di B sono narrazione scambiata per diagnosi: procedure («pregresso
bypass gastrico»), confini che lasciano fuori la parola che nomina la
patologia, abitudini alimentari. Gli errori di A sono termini del vocabolario
riconosciuti nel contesto sbagliato. Quelli di C sono di confine.

**L'unico errore codificato di B ha scoperto un buco dello schema.**
`[I48] «fibrillanti»`, attribuito al paziente: nel referto l'aggettivo si
riferiva a due parenti nominate nella frase precedente («Madre e sorella
fibrillanti», esempio ricostruito). L'asse del soggetto riconosceva i
marcatori espliciti («familiarità per») e non una frase che nomina il parente
direttamente. Una condizione cardiologica con codice sicuro attribuita alla
persona sbagliata è il caso peggiore per il filtro dello step 8: da qui la
revisione 1.1.0 dello schema, con il soggetto calcolato da ConText per tutte
e tre le pipeline (508 menzioni di familiarità nel corpus).

## 4. Accordo sugli attributi e copertura dei codici

| coppia | stato | soggetto | codice |
| --- | --- | --- | --- |
| A–C (7 147 confrontabili) | 100,0% | 100,0% | 99,3% |
| A–B (3 534) | 97,7% | 99,9% | 95,8% |
| B–C (3 711) | 97,7% | 99,9% | 94,8% |

A e C concordano per costruzione (stesso ConText, stessa codifica). Con B il
disaccordo sullo stato è del 2,3%, e nei casi letti B capisce meglio il
contesto in alcune forme precise (`asintomatico per`, `non riferiti`) — è
da qui che nasce la correzione di «non riferisce» nello step 9bis.

| copertura dei codici | condizioni | con ICD | farmaci in prosa | con ATC |
| --- | --- | --- | --- | --- |
| A | 5 237 | **99,4%** | 2 332 | 96,1% |
| B | 16 561 | 34,8% | 61 → 2 174 dopo la correzione | 24,6% |
| C | 5 420 | 93,4% | 2 542 | 86,7% |

La copertura di A è alta per costruzione: riconosce solo ciò che sa
codificare. Quella di B è bassa perché trova ciò che il volume ICD non
indicizza («fibrillazione atriale» esiste solo nelle forme qualificate).

## 5. Un modello linguistico contro una regex

Sui campi di terapia, con il parser deterministico come riferimento, B
ritrova il 99,9% delle voci d'ingresso e il 99,6% di quelle di dimissione;
il modello locale 88,6% e 50,5%. È il numero che ha deciso il disegno dello
step 4: il modello non legge più quei campi, li legge il parser, per tutte e
tre le pipeline.

## 6. Una conclusione ritirata

La prima versione di questo documento concludeva che B «perde» sui farmaci
narrati (62 su 1 000 record contro 2 332 di A) e ne faceva una proprietà dei
metodi. Lo step 6bis ha mostrato che lo zero era mio: una regola del prompt
escludeva i farmaci fuori dai campi di terapia. Corretta, B ne trova 2 174
con richiamo 83,3%. La conclusione resta scritta qui con la correzione sotto:
si conserva anche l'errore.

## 7. Che cosa se ne porta via il progetto

| | A | B (remota) | C |
| --- | --- | --- | --- |
| precisione sulle esclusive | 73,3% ± 8,1 | **91,7% ± 3,6** | 66,7% ± 8,6 |
| errori già codificati | **88%** | 20% | 0% |
| copertura ICD | 99,4% | 34,8% | 93,4% |
| tempo per record | 0,02 s | 2,3 s | 0,31 s |
| costo per 1 000 record | 0 | 2,42 $ | 0 |

**Non c'è una pipeline che vince**, e cercarla era la domanda sbagliata: ci
sono tre profili di errore. A codifica, e i suoi errori sono i più
pericolosi; C segnala ciò che alla knowledge base manca, compresi i refusi,
senza codificarlo; B capisce il contesto e trova tre volte tanto, con un
terzo di narrazione. L'uso sensato è insieme, con la provenienza di ogni
menzione: è lo step 7. E mai il modello dove basta una regex.

## 8. Limiti

* L'aggiudicazione è di un solo giudice, su 120 menzioni.
* Il confronto è fra metodi, non contro una verità: il richiamo è allo step
  6bis.
* B esiste in due versioni (locale su 199 record, remota su 1 000); i numeri
  di questo documento sono della remota, salvo dove detto.
