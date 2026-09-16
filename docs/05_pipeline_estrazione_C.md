# Step 5 — Pipeline C: NER + Entity Linking

**Stato:** completato.
**Riproducibilità:** `python3 src/silver_labels.py && python3 src/ner_train.py && python3 src/extract_c.py`

Terza e ultima pipeline di estrazione. La domanda a cui risponde è precisa: **un
modello a token addestrato sulle annotazioni della pipeline A riesce a trovare
menzioni che il gazetteer non trova?** Se la risposta fosse no, la pipeline C
non aggiungerebbe nulla — e anche quello sarebbe un risultato da riportare.

---

## 1. Le etichette silver

Il brief esclude l'annotazione manuale. Le etichette di addestramento vengono
quindi dall'uscita della pipeline A: **1 000 referti, 7 649 menzioni**, tutte
con offset che ritagliano esattamente il testo dichiarato (verificato: le
annotazioni incoerenti verrebbero scartate, e non ce n'è nessuna).

### Perché non è un circolo vizioso

A prima vista sembra esserlo: il gazetteer riconosce solo ciò che sta nei
vocabolari chiusi, quindi un modello addestrato sulle sue annotazioni dovrebbe
al massimo reimparare il vocabolario. Le due cose però **generalizzano in modo
diverso**:

* il gazetteer riconosce **stringhe**: «dislipidemia» non è nel volume ICD-10,
  quindi per la pipeline A semplicemente non esiste;
* un modello a token impara **contesti e morfologia**: vede migliaia di volte
  che dopo «in anamnesi», «nota», «pregressa» compare una diagnosi, e che i nomi
  di patologia in italiano hanno terminazioni ricorrenti (-emia, -patia, -osi,
  -ite).

La sezione 5 misura se l'ipotesi regge.

### La divisione è per ricovero

Due frasi dello stesso referto si somigliano molto: la stessa patologia
ricompare nell'anamnesi remota e nella storia recente, spesso con le stesse
parole. Dividere per frase metterebbe frasi quasi identiche in addestramento e
in prova, gonfiando i risultati. La divisione è quindi a livello di ricovero:
**700 / 150 / 150**.

### Cosa viene etichettato, e cosa no

Solo i **confini** delle menzioni, con due etichette (`CONDIZIONE`, `FARMACO`).
Non lo stato clinico: negazione e incertezza restano affidate a ConText,
esattamente come nella pipeline A. Se anche l'attribuzione dello stato cambiasse
fra A e C, il confronto dello step 6 misurerebbe due differenze sommate invece
di quella che interessa.

---

## 2. Il modello

**`IVN-RIN/bioBIT`**: un BERT italiano adattato al dominio biomedico, che parte
da `dbmdz/bert-base-italian-xxl-cased` e prosegue il pre-addestramento su un
corpus biomedico italiano ottenuto traducendo abstract di PubMed.

> Buonocore et al., *Localizing in-domain adaptation of transformer-based
> biomedical language models*, Journal of Biomedical Informatics, 2023.
> Modello: <https://huggingface.co/IVN-RIN/bioBIT>

Il lessico dei referti — patologie, principi attivi, abbreviazioni cliniche — è
quello su cui bioBIT ha continuato ad addestrarsi, mentre un modello generalista
lo vede come vocabolario raro e lo frammenta in molti sottotoken. Il modello di
base resta comunque un parametro (`--modello-base`), così che il confronto con
la variante generalista sia una prova da eseguire e non un'opinione.

L'addestramento gira **su CPU**: `torch` installato è una build CUDA su una
macchina AMD, quindi la GPU non è utilizzabile da PyTorch (lo è invece da Ollama
per la pipeline B, che passa da ROCm). Tre epoche su 1 795 segmenti richiedono
circa un'ora.

### Allineamento delle etichette

Le annotazioni sono intervalli di **caratteri**, il modello ragiona in
**sottotoken**. L'allineamento usa la mappa di offset del tokenizzatore veloce
invece di riallineare per parole: è esatto anche quando il tokenizzatore spezza
«ipertensione» in `iperten` + `##sione`, e non dipende da una nozione di
"parola" che dovrebbe restare in accordo con quella di spaCy usata altrove.

### La valutazione è per entità, non per token

L'accuratezza per token è ingannevole: la stragrande maggioranza dei token è
fuori da ogni entità, quindi un modello che non trovasse nulla supererebbe
comunque il 90%. Una predizione conta come corretta solo se coincidono **inizio,
fine ed etichetta**.

---

## 3. Due esiti negativi, verificati e non supposti

### Gli acronimi non sono risolvibili da fonti citabili

`BPCO`, `FA`, `IRC` non compaiono nel volume ICD-10. Sono state provate due
strade, entrambe fallite:

* **il corpus non definisce le proprie sigle.** L'algoritmo di Schwartz & Hearst
  (PSB 2003), applicato con il suo vincolo di sottosequenza, produce 105 coppie
  da mille referti, in larga parte rumore e con errori veri
  (`FA = frequenza cardiaca non ottimale`): i clinici scrivono la sigla e basta;
* **Wikidata non le copre.** La query SPARQL per voci con codice ICD-10 (P494) e
  un alias italiano in maiuscolo restituisce **zero** risultati.

Inventare le espansioni violerebbe il vincolo di provenienza del progetto. Le
sigle restano quindi non collegate anche nella pipeline C — ed è un risultato
interessante per il confronto: **l'unica pipeline che le scioglie è la B**,
perché un LLM attinge alla propria conoscenza interna, che infatti viene usata
solo come chiave di ricerca nell'indice ufficiale e mai come fonte del codice.

### La similarità ortografica non funziona come collegatore

Per agganciare le menzioni che l'ICD non ha in quella forma è stato costruito un
collegamento per similarità di Jaccard sui trigrammi di caratteri. Misurato sul
lessico reale dei referti:

| punteggio | menzione → termine agganciato | esito |
|---|---|---|
| **0,600** | insufficienza mitralica moderata → …congenita (Q23.3) | **sbagliato** |
| 0,547 | broncopneumopatia cronica ostruttiva → altra pneumopatia… (J44.8) | categoria giusta |
| 0,463 | extrasistolia sopraventricolare → tachicardia sopraventricolare (I47.1) | **sbagliato** |
| 0,424 | cardiopatia ipocinetica → cardiomiopatia ischemica (I25.5) | **sbagliato** |
| 0,409 | precordialgie → dolore precordiale (R07.2) | corretto |
| 0,340 | aneurisma dell'aorta ascendente → aneurisma e dissezione dell'aorta (I71) | corretto |

Il punteggio più alto è l'errore più pericoloso — la stessa trappola
congenito/acquisito già incontrata nello step 4 — mentre i due collegamenti
corretti stanno in fondo. In italiano medico una parola di differenza
(«congenita» contro «moderata») è ortograficamente vicina e clinicamente
lontanissima, mentre i sinonimi sono ortograficamente distanti. **Nessuna soglia
separa i due gruppi.**

Il componente non è stato buttato ma **declassato**: la similarità restituisce
sempre `AMBIGUO`, con il termine agganciato e il punteggio scritti nella
provenienza. È una proposta da verificare, non una codifica, e non arriva mai al
filtro di sicurezza dello step 8, che consuma solo le condizioni risolte.

---

## 4. Un difetto che attraversava tre step

La pipeline C produceva menzioni di farmaco chiamate `5 mg`, `2.5 mg`, `2`.
Risalendo la catena, l'origine non era il NER:

```
referto:      "...introduceva Ramipril 2.5 mg. Nel 2016..."
pipeline A:   farmaco "2.5 mg", regola "gazetteer:2.5 mg"
```

Il vocabolario dei farmaci, costruito parsificando il campo semi-strutturato
della terapia, conteneva **residui di parsing**: `5 mg`, `2.5 mg`, `ore 17`,
`cpr.`, `td`, `-`. Da soli non sono nomi di farmaco, ma come forme del gazetteer
trovano riscontro ovunque. Da lì finivano nelle **etichette silver** dello step
5, e il NER li imparava e li riproduceva su scala maggiore.

Un filtro esisteva già (`nome_farmaco_plausibile`, step 0) ma veniva applicato
al *parsing*, non al **vocabolario** che alimenta il gazetteer.
`forma_farmaco_ammissibile` chiude la falla con una regola semplice: dopo aver
tolto cifre, punteggiatura e parole che sono solo unità di misura o forme
farmaceutiche, deve restare almeno un pezzo alfabetico di tre lettere. Cadono
`5 mg` e `ore 17`; restano i marchi legittimi con cifre come `mag 2`,
`omega 3 aur`, `cacit 1000`.

Effetto: **55 etichette di addestramento errate rimosse** (1 657 → 1 602
farmaci), e altrettante menzioni inesistenti in meno nella pipeline A. Fissato
in un test di regressione.

È il terzo caso in questo progetto in cui costruire davvero il passo successivo
ha rivelato un difetto del passo precedente, invisibile finché restava un file.

---

## 5. Che cosa il NER aggiunge davvero

*(misure sulla partizione di prova, 150 referti mai visti in addestramento)*

Il modello raggiunge **F1 0,878** su sviluppo e **0,869** sulla partizione di
prova (precisione 0,824, richiamo 0,918): la coerenza fra le due esclude il
sovradattamento. Il richiamo piu' alto della precisione e' il dato da leggere
con attenzione, ed e' il motivo della sezione che segue.

**228 menzioni trovate dal NER e assenti dalle etichette del gazetteer.** Non
sono errori: in larga parte sono riconoscimenti corretti che il vocabolario non
poteva fare.

* farmaci fuori vocabolario: `claritromicina`, `dronedarone`, `bosutinib`,
  `prulifloxacina`, `cotrimossazolo`, `spiramicina`, `amoxicillina`,
  `dasatinib`, `ciclofosfamide`;
* condizioni fuori vocabolario: `sinusite`, `leucemia mieloide cronica`,
  `spondiloartrosi`, `atopia`, `idronefrosi`, `pericardite`,
  `cuore polmonare cronico`, `infezione respiratoria`.

**95 menzioni del gazetteer perse dal NER**, e diverse sono **errori del
gazetteer che il NER evita**: `caduta` (8 volte), `del cuore` (3),
`furosemide.` con il punto attaccato. Le perdite genuine sono poche
(`trait talassemico`, `kcl retard`).

L'ipotesi della sezione 1 regge: il modello ha imparato il **contesto**, non il
vocabolario.

---

## 6. Confronto con la pipeline A, a normalizzazione identica

Perché il confronto misuri il solo riconoscimento, la pipeline A è stata
**allineata**: usa ora lo stesso `CollegatoreICD` della pipeline C. Prima
prendeva i codici direttamente dal gazetteer, e la differenza osservata avrebbe
mescolato riconoscimento e normalizzazione — esattamente ciò che il modulo
`risolutori.py` dichiara di voler evitare.

*(intero dataset, 1 000 referti)*

| | A (gazetteer) | C (NER) | |
|---|---|---|---|
| condizioni trovate | 5 237 | **5 420** | +183 |
| — con codice ICD | **5 206** (99,4%) | 5 064 (93,4%) | −142 |
| — ambigue | 31 | 262 | +231 |
| — senza codice | 0 | 94 | +94 |
| — negate | 299 | 302 | +3 |
| — incerte | 102 | 113 | +11 |
| farmaci trovati | 14 155 | **14 365** | +210 |
| — di cui nella prosa | 2 332 | **2 542** | +210 |
| — con codice ATC | **13 308** | 13 273 | −35 |

**La lettura corretta non è "C è meglio".** La pipeline A raggiunge il 99,4% di
copertura ICD *per costruzione*: il suo gazetteer è fatto di termini ICD, quindi
quasi tutto ciò che trova è codificabile per definizione. Il denominatore è
ristretto, e la percentuale lo riflette.

La pipeline C trova **183 condizioni e 210 farmaci in più**, ma in buona parte
sono menzioni che la knowledge base **non sa codificare**: `sinusite`,
`spondiloartrosi`, `claritromicina`. In termini assoluti A ne codifica 142 in
più. Le due pipeline stanno quindi su un compromesso diverso:

* **A** — alta precisione di codifica su ciò che sa vedere; cieca su tutto il
  resto;
* **C** — vede di più, e ciò che vede in più espone il limite della knowledge
  base invece di nasconderlo.

Per il knowledge graph dello step 7 e per il filtro di sicurezza dello step 8
contano le condizioni **codificate**, e lì A resta avanti. Per capire *cosa
manca alla knowledge base*, e per il confronto dello step 6, conta il
riconoscimento, e lì è avanti C. Un sistema di produzione le userebbe insieme:
il gazetteer per codificare, il NER per segnalare ciò che sfugge.

Le due pipeline concordano quasi perfettamente su negazione e incertezza (+3 e
+11 su ~400), il che è atteso: usano lo stesso ConText, e la differenza riflette
solo le menzioni in più.

Il costo: **0,32 s per record**, contro 0,02 s della pipeline A e 199 s della
pipeline B.

---

## 7. Limiti noti

* Le etichette sono **silver**: contengono gli errori della pipeline A, e il NER
  li eredita. Il difetto della sezione 4 è la dimostrazione che il meccanismo è
  reale, non teorico.
* La **precisione misurata è contro il gazetteer, non contro la verità**: un
  "falso positivo" può essere un riconoscimento corretto che il vocabolario non
  aveva. Le 228 menzioni nuove della sezione 5 vanno lette così.
* Il modello vede segmenti di al massimo 1 000 caratteri tagliati ai confini di
  frase; in inferenza si riusa la stessa funzione, altrimenti la coda dei referti
  lunghi verrebbe troncata in silenzio.
* Nessuna **disambiguazione contestuale**: una menzione compatibile con più
  codici resta ambigua. Era il compito che lo step 3 aveva rimandato qui, e resta
  risolto solo in parte — dalla generalizzazione a categoria dello step 4, non da
  un modello di entity linking addestrato.
* L'addestramento è **su CPU**: circa un'ora per tre epoche. Il miglioramento fra
  la seconda e la terza epoca era ancora positivo, quindi un addestramento più
  lungo darebbe probabilmente qualcosa in più.

---

## 8. Componenti creati

| File | Ruolo |
|---|---|
| `src/silver_labels.py` | etichette BIO dall'uscita della pipeline A, segmentazione e divisione per ricovero |
| `src/ner_train.py` | ciclo di addestramento esplicito, allineamento, valutazione per entità |
| `src/ner_infer.py` | riconoscimento con il modello addestrato, offset riportati al testo completo |
| `src/entity_linking.py` | collegamento a ICD-10: metodi esatti più proposta per similarità |
| `src/extract_c.py` | orchestratore: NER + ConText + codifica condivisa |
| `tests/test_pipeline_c.py` | test di allineamento, segmentazione, divisione e collegamento |

### Comandi

```bash
python3 src/silver_labels.py     # etichette dall'uscita della pipeline A
python3 src/ner_train.py         # addestra (circa un'ora su CPU)
python3 src/extract_c.py         # pipeline C su tutti i record
python3 src/extract_c.py --solo-prova   # solo i referti mai visti
```
