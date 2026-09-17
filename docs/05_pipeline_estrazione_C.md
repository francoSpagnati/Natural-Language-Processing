# Step 5 — Pipeline C: NER + Entity Linking

**Stato:** completato.
**Riproducibilità:** `python3 src/sonda_ner_preaddestrato.py` (la prova sul pre-addestrato), poi `python3 src/silver_labels.py && python3 src/ner_train.py && python3 src/extract_c.py`

Terza pipeline di estrazione. La domanda è precisa: **un modello a token
addestrato sulle annotazioni della pipeline A trova menzioni che il
gazetteer non trova?** Se no, la pipeline C non aggiunge nulla — e anche
quello è un risultato da riportare. La risposta è: trova qualcosa in più, non
sa codificarlo.

---

## 0. Che cos'è un NER, e perché va addestrato

Un modello NER (*Named Entity Recognition*) legge il testo e marca gli
intervalli che sono entità di un certo tipo — qui `DRUG` e `CONDITION`. A
differenza del gazetteer (che cerca stringhe di un elenco) e del modello
linguistico (che risponde a un prompt), un NER è un classificatore di token:
per ogni parola decide «inizio di entità / dentro / fuori». Per farlo deve
aver **visto esempi etichettati**: bioBIT, il modello di base usato qui, è un
BERT addestrato su testo biomedico italiano, che conosce la lingua ma non sa
che cosa sia un farmaco finché non lo si addestra.

Le etichette possono essere **gold** (scritte a mano da un annotatore) o
**silver** (prodotte automaticamente da un altro sistema). Il brief esclude
l'annotazione manuale e prescrive testualmente la seconda via: *«fine-tuning
di un modello NER italiano… usando come training set silver le annotazioni
prodotte dalla pipeline A su tutto il dataset (weak supervision)»*. È quello
che questo step fa. La domanda che ne segue — se un modello addestrato su
etichette del gazetteer possa trovare più del gazetteer — è la sez. 1.

### Prima: esiste un NER clinico italiano già addestrato?

Il brief chiede di verificarlo prima di addestrare. Cercato su Hugging Face il
17 settembre 2026 («italian medical ner», filtro *token-classification*): **un
solo modello italiano**, [`HUMADEX/italian_medical_ner`](https://huggingface.co/HUMADEX/italian_medical_ner)
— BERT base, supervisione debole su testo clinico tradotto, etichette
`PROBLEM` / `TEST` / `TREATMENT`, Apache 2.0 (Sallauka et al. 2025,
doi:10.3390/app15105585). Nessuno con etichette farmaco/condizione ancorate a
un vocabolario. Eseguito sui 25 referti del riferimento annotato con la stessa
funzione di valutazione delle tre pipeline
([`src/sonda_ner_preaddestrato.py`](../src/sonda_ner_preaddestrato.py)):

| sul riferimento, 25 referti | attese | trovate | precisione | richiamo | F1 |
|---|---|---|---|---|---|
| `PROBLEM` → condizioni | 559 | 932 | 31,0% | **51,7%** | 38,8% |
| `TREATMENT` → farmaci in prosa | 60 | 967 | 3,6% | 58,3% | 6,8% |
| *per confronto:* A gazetteer, condizioni | 559 | 136 | 80,1% | 19,5% | 31,4% |
| *per confronto:* C su silver, condizioni | 559 | 136 | 81,6% | 19,9% | 31,9% |

Vede **due volte e mezzo** le condizioni del gazetteer, ma due su tre di ciò
che marca non è una condizione attesa, e `TREATMENT` copre qualunque
intervento (967 menzioni per 60 farmaci). Soprattutto **non collega a nulla**:
restituisce intervalli, non codici, e lo step 5 sez. 3 mostra che il collegamento
per similarità ortografica sbaglia 3 volte su 6. Un pre-addestrato generico
sposta il problema dal riconoscimento al linking senza risolverlo; il
fine-tuning su silver resta la via del brief, con il risultato negativo che
segue.

---


## 1. Le etichette silver, e perché non è un circolo vizioso

Etichette BIO dall'uscita della pipeline A: 1 000 referti, 7 649 menzioni,
tutte con offset esatti. Sembra circolare — un modello addestrato sul
gazetteer dovrebbe al massimo reimpararne il vocabolario — ma i due
generalizzano diversamente: il gazetteer riconosce **stringhe**, un modello a
token impara **contesti e morfologia** (dopo «in anamnesi», «nota»,
«pregressa» compare una diagnosi; le patologie finiscono in -emia, -patia,
-osi, -ite). La divisione è **per ricovero** (700 / 150 / 150), così nessun
segmento di un referto di prova è mai stato visto in addestramento.

## 2. Il modello

**`IVN-RIN/bioBIT`** (Buonocore et al., *Localizing in-domain adaptation of
transformer-based biomedical language models*, Journal of Biomedical
Informatics 144, 2023, doi:10.1016/j.jbi.2023.104431): un BERT italiano che
continua il pre-addestramento su testo biomedico. Il lessico dei referti è
quello su cui ha imparato, dove un generalista frammenta in sottotoken rari.
Fine-tuning su CPU (la build di torch è CUDA su una macchina AMD): tre epoche
su 1 795 segmenti, circa un'ora. Allineamento caratteri → sottotoken con la
mappa di offset del tokenizzatore veloce, esatto anche quando «ipertensione»
diventa `iperten` + `##sione`. **Valutazione per entità, non per token.**

Sviluppo F1 0,878, prova **F1 0,869** (precisione 0,824, richiamo 0,918):
coerenti, nessun sovradattamento. Il richiamo più alto della precisione è il
dato da leggere: il NER trova più di ciò che il gazetteer etichetta.

## 3. Che cosa il NER aggiunge davvero

| sui 150 referti di prova | |
| --- | --- |
| menzioni trovate dal NER e assenti dal gazetteer | **228**, in larga parte corrette: farmaci fuori vocabolario (`claritromicina`, `dronedarone`, `bosutinib`), condizioni fuori vocabolario (`pericardite`, `idronefrosi`, `cuore polmonare cronico`) |
| menzioni del gazetteer perse dal NER | 95, molte sono errori del gazetteer che il NER evita (`caduta` ×8, `del cuore`, `furosemide.`) |

L'ipotesi regge: il modello ha imparato il contesto, non il vocabolario. Ma
sul corpus intero, a normalizzazione identica:

| | A gazetteer | C NER | differenza |
| --- | --- | --- | --- |
| condizioni trovate | 5 237 | **5 420** | +183 |
| con codice ICD | **5 206** (99,4%) | 5 064 (93,4%) | −142 |
| ambigue | 31 | 262 | +231 |
| farmaci in prosa | 2 332 | **2 542** | +210 |
| farmaci con ATC | **13 308** | 13 273 | −35 |

**Ciò che il NER trova in più, non lo sa codificare.** E sul riferimento
annotato (step 6bis) il richiamo sulle condizioni è 19,9% contro 19,5% di A:
il collo di bottiglia non è il riconoscimento, è il collegamento.

## 4. Due esiti negativi, verificati

**Gli acronimi non sono risolvibili da fonti citabili.** `BPCO`, `FA`, `IRC`
non sono nel volume ICD. Provate due strade: l'algoritmo di Schwartz & Hearst
sul corpus (105 coppie da mille referti, in larga parte rumore: i clinici
scrivono la sigla e basta) e Wikidata (voci con ICD-10 e alias italiano in
maiuscolo: **zero**). Inventare le espansioni violerebbe il vincolo di
provenienza. L'unica pipeline che le scioglie è la B — con conoscenza
interna usata solo come chiave di ricerca nell'indice ufficiale.

**La similarità ortografica non funziona come collegatore.**

| punteggio | menzione → termine agganciato | esito |
| --- | --- | --- |
| **0,600** | insufficienza mitralica moderata → …congenita (Q23.3) | **sbagliato** |
| 0,463 | extrasistolia sopraventricolare → tachicardia sopraventricolare (I47.1) | **sbagliato** |
| 0,424 | cardiopatia ipocinetica → cardiomiopatia ischemica (I25.5) | **sbagliato** |
| 0,409 | precordialgie → dolore precordiale (R07.2) | corretto |
| 0,340 | aneurisma dell'aorta ascendente → aneurisma e dissezione dell'aorta (I71) | corretto |

Il punteggio più alto è l'errore peggiore: in italiano medico una parola di
differenza («congenita» / «moderata») è ortograficamente vicina e
clinicamente lontanissima. **Nessuna soglia separa i due gruppi.** Il
componente è **declassato**, non buttato: restituisce sempre `AMBIGUO`, con
il termine e il punteggio nella provenienza, e non arriva mai al filtro.

## 5. Un difetto che attraversava tre step

La pipeline C produceva farmaci chiamati `5 mg`, `2.5 mg`, `2`. L'origine non
era il NER: il vocabolario dei farmaci, costruito dal campo di terapia,
conteneva **residui di parsing** (`5 mg`, `ore 17`, `cpr.`, `td`), il
gazetteer li trovava ovunque, le etichette silver li propagavano, il NER li
riproduceva su scala maggiore. `forma_farmaco_ammissibile` chiude la falla
(resta un pezzo alfabetico di tre lettere dopo aver tolto cifre, unità e
forme farmaceutiche; sopravvivono `mag 2`, `omega 3 aur`, `cacit 1000`): 55
etichette errate rimosse, test di regressione. Terzo caso in cui costruire il
passo successivo ha rivelato un difetto del precedente.

## 6. Limiti

* Le etichette sono silver: il NER eredita gli errori di A, e la precisione
  misurata è contro il gazetteer, non contro la verità.
* Nessuna disambiguazione contestuale: una menzione compatibile con più
  codici resta ambigua.
* Addestramento su CPU, un'ora per tre epoche; la terza migliorava ancora.

## 7. Componenti

| file | ruolo |
| --- | --- |
| `src/sonda_ner_preaddestrato.py` | il pre-addestrato italiano sui 25 referti del riferimento |
| `src/silver_labels.py` | etichette BIO da A, segmentazione, divisione per ricovero |
| `src/ner_train.py`, `src/ner_infer.py` | addestramento con allineamento esatto, valutazione per entità; inferenza con offset riportati al testo intero |
| `src/entity_linking.py` | collegamento a ICD-10: metodi esatti, più la proposta per similarità (declassata) |
| `src/extract_c.py` | orchestratore: NER + ConText + codifica condivisa |
