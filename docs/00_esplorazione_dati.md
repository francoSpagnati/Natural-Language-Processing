# Step 0 — Esplorazione dei dati

**Stato:** completato.
**Riproducibilità:** `python3 src/explore_dataset.py` rigenera integralmente
`reports/00_esplorazione.txt` e i CSV in `data/interim/`.

---

## 1. Cosa è stato fatto

Verifica empirica del formato reale del dataset **prima** di scrivere qualunque
pipeline, come richiesto dalla sezione 2 del brief. Nessuna assunzione sullo
schema è stata data per buona: ogni affermazione in questo documento corrisponde
a un numero stampato nel report rigenerabile.

## 2. Provenienza del dato — vincolo di progetto

Sulla macchina esistevano tre varianti dello stesso dataset. La scelta fra loro
**non è una questione di comodità ma di validità del progetto**:

| File | Record | Provenienza |
|---|---|---|
| **`anamnesiterapie.txt`** | **1000** | **export grezzo del sistema ospedaliero** |
| `anamnesiterapie_completo.txt` | 1000 | derivato, passato per un LLM |
| `pazienti_con_terapia_uscita.txt` | 857 | derivato, passato per un LLM |

I due file derivati sono stati prodotti facendo passare i dati grezzi attraverso
un LLM per filtrarli e strutturarli. Sono **scartati**: costruirci sopra la
pipeline significherebbe ereditare un'estrazione già fatta da un altro modello,
cioè esattamente ciò che questo progetto deve invece implementare e misurare.
Ne deriverebbe anche un'ambiguità non risolvibile in sede di discussione —
quanta parte del risultato è merito della pipeline e quanta del pre-processing
altrui?

**Dataset canonico: `data/raw/anamnesiterapie.txt`** (1000 record).

### Cosa avevano aggiunto i file derivati, e cosa si perde a scartarli

Il confronto è stato fatto campo per campo, non per ipotesi:

- I tre referti testuali (`Anamnesi`, `Terapia medica all'ingresso`,
  `Terapia alla Dimissione`) sono **identici byte per byte** fra file grezzo e
  file derivato su tutti gli 857 record comuni. **Non si perde nulla di
  testuale.**
- L'LLM aveva **selezionato** gli 857 record con terapia alla dimissione e
  **aggiunto** un referto `Anamnesi Strutturata`: un questionario clinico
  codificato (43 voci, con negazione esplicita e distinzione fra "negato" e "non
  compilato").

Quel questionario era la fonte più comoda per le condizioni del paziente, ma è
di origine LLM e **va scartato**. La conseguenza è architetturale e va detta
chiaramente: **le patologie dovranno essere estratte dal testo libero**, che è
poi esattamente lo scopo delle tre pipeline di estrazione (§ 4.5).

> Se il questionario provenisse in realtà dal database ospedaliero e l'LLM fosse
> stato usato solo per il join, sarebbe recuperabile come *gold standard* per la
> valutazione delle condizioni. **Punto aperto da confermare**; nel dubbio si
> procede senza.

### Knowledge base esterne: scelta e download riproducibile

La cartella conteneva anche due CSV del WHO ATC/DDD Index. Provenendo dalla
stessa cartella dei file derivati, **sono stati rimossi**: superavano un
controllo di integrità strutturale, ma "sembra autentico" non è una provenienza.

Le fonti sono state quindi riacquisite da zero con
[`src/fetch_external_kb.py`](../src/fetch_external_kb.py), che le scarica,
ne calcola lo SHA-256 e scrive `kb/manifest_fonti.json` con URL, data di
download, dimensione, impronta e **il motivo per cui ogni file serve**. Il
manifest sta in `kb/` e non in `data/` proprio perché `data/` non è versionato:
le citazioni devono sopravvivere a un clone.

**Fonte scelta: AIFA — Agenzia Italiana del Farmaco**, licenza **CC-BY 4.0**,
download senza autenticazione.

| File | Contenuto | Ruolo |
|---|---|---|
| `atc.csv` | 7 211 codici ATC con descrizione **in italiano** | gerarchia ATC e metrica dello step 11 |
| `confezioni_fornitura.csv` | 159 942 confezioni: denominazione, principi attivi, ATC, ditta | dizionario nome commerciale → principio attivo → ATC |
| `PA_confezioni.csv` | principi attivi per codice AIC | disambigua le associazioni |
| `Classe_A/H_per_nome_commerciale` | farmaci di classe A e H con **titolare AIC** | valida le abbreviazioni dei produttori |

Perché AIFA e non altro:

- **WHO ATC/DDD Index** è la fonte primaria della classificazione, ma l'indice
  ufficiale è consultabile via interfaccia web e il download massivo è soggetto
  a licenza; inoltre è in inglese e non contiene i nomi commerciali italiani,
  che sono precisamente ciò che il dataset contiene.
- **Wikidata** è libera (CC0) e interrogabile in SPARQL, ma ha appena **3 763**
  entità con codice ATC (proprietà `P267`) — verificato con una query diretta:
  copertura troppo bassa per fare da fonte primaria. Resta candidata per lo
  step 7, dove serve un compito diverso (relazioni farmaco↔condizione).

Il registro ATC AIFA è stato verificato: 14 gruppi anatomici, distribuzione dei
livelli 14 / 94 / 270 / 941 / 5 892, **15 codici orfani** (da documentare nello
step 2), e descrizioni in italiano — `C07AB07` → `BISOPROLOLO`,
`C07AB` → `BETABLOCCANTI, SELETTIVI`. Che siano in italiano è un vantaggio non
banale: le motivazioni prodotte dal sistema restano nella lingua delle anamnesi.

### Il ponte interno, verificato contro AIFA

Il ponte di § 4.3 è generato in modo deterministico dal dataset grezzo (nessun
LLM), ma resta un'**osservazione locale**: dice come un ospedale ha trascritto
le terapie, non cosa contiene un medicinale. È stato quindi confrontato con
l'anagrafica AIFA da [`src/verifica_ponte_aifa.py`](../src/verifica_ponte_aifa.py):

| Esito | Coppie | % |
|---|---|---|
| **confermate da AIFA** | 529 | 67,2 % |
| **discordanti** | 21 | 2,7 % |
| nome commerciale non presente in AIFA | 237 | 30,1 % |

Il disaccordo reale è quindi minimo, e ispezionando le 21 discordanze quasi
tutte si rivelano **falsi disaccordi** dovuti al confronto: AIFA registra la
confezione sotto il principio principale (`olmesartan medoxomil`) mentre il
dataset elenca l'associazione intera (`Olmesartan medoxomil/amlodipina`), oppure
usa una forma salina o il nome inglese (`levothyroxine sodium` per
`Levotiroxina`). Un caso è una divergenza sostanziale legittima: `cardirene`,
che il dataset chiama acido acetilsalicilico e AIFA `acetilsalicilato di lisina`
— un sale diverso della stessa molecola.

Il 31 % assente non significa "inventato": sono in larga parte galenici,
integratori, prodotti esteri, o radici estratte in modo troppo aggressivo dalla
denominazione. Lo step 2 dovrà trattarli caso per caso.

**Conclusione operativa:** il ponte serve a *ridurre il lavoro di verifica*, mai
a sostituirla. Nello step 2 il dizionario di normalizzazione si costruisce
sull'anagrafica AIFA; il ponte interviene solo come evidenza di supporto, e ogni
voce che resta priva di conferma esterna va marcata esplicitamente come tale.

## 3. Struttura reale del file

Il `.txt` è un **unico array JSON valido**, UTF-8, che si carica senza errori.

```
[ { "encOid": int,
    "referti": [ { "tipo": str, "data": str, "reportOid": int, "testo": str } ] } ]
```

1000 record, 1000 `encOid` distinti, `testo` **sempre** stringa, chiavi del
referto sempre le stesse quattro. **Zero anomalie strutturali di caricamento.**

Il dataset si divide in **due coorti**:

| Coorte | Record | Uso |
|---|---|---|
| con `Terapia alla Dimissione` | **857** | hanno la ground truth: valutazione (§ 4 del brief) |
| senza | **143** | solo testo: collaudo di estrazione, EL e KB, e testo non etichettato in più |

| `tipo` di referto | Presente in | Lunghezza (min / mediana / max) |
|---|---|---|
| `Anamnesi` | 1000 | 222 / 1 665 / 17 590 |
| `Terapia medica all'ingresso` | 1000 | 4 / 275 / 1 899 |
| `Terapia alla Dimissione` | 857 | 15 / 649 / 2 281 |

## 4. Affidabilità dei campi

Per misurare *quanto* ogni campo sia regolare, invece di nascondere le
irregolarità dietro una regex generosa, ogni sonda è organizzata a **livelli**,
dal pattern più stringente al più lasco, e conta quante voci cadono in ciascuno.
Il livello resta associato alla voce estratta, così a valle si può decidere
quanto fidarsi del dato.

### 4.1 `Terapia alla Dimissione` — il campo più ricco (99,1 % interpretato)

Formato prevalente:
`"Principio attivo (Nome commerciale forma dose): da assumere 5 mg (ore 8)"`

| Livello | Voci | % |
|---|---|---|
| 1 — formato pieno | 6 201 | 96,09 % |
| 2 — con sinonimo del principio attivo | 58 | 0,90 % |
| 3 — senza nome commerciale | 10 | 0,15 % |
| 4 — senza posologia | 60 | 0,93 % |
| escluso: non farmacologico (ossigeno, CPAP, NIV) | 46 | 0,71 % |
| escluso: segnaposto (`Nessun principio attivo`) | 22 | 0,34 % |
| **non interpretato** | **56** | **0,87 %** |

È il campo **più prezioso del dataset**: espone il **principio attivo**
(denominazione internazionale) come primo elemento, già separato dal nome
commerciale. Da qui: **406 principi attivi distinti** e **1 236 nomi
commerciali distinti**.

Due categorie sono escluse esplicitamente perché non denotano sostanze:
l'ossigenoterapia e la ventilazione (`Cicli di NIV con auto C-PAP`), e il
segnaposto `Nessun principio attivo` che l'EHR usa quando il campo non è
valorizzato — compariva 22 volte e sarebbe entrato nel vocabolario come se
fosse un farmaco. Sono contate come voci *riconosciute ed escluse*, non come
fallimenti del parsing: la voce è stata interpretata, semplicemente non è un
medicinale.

Il livello 2 cattura come effetto collaterale utile 8 coppie di **sinonimi** di
principio attivo (`Tiamazolo == metimazolo`, `Idrossiclorochina ==
idroxiclorochina`), materiale diretto per il dizionario di normalizzazione.

### 4.2 `Terapia medica all'ingresso` — solo nomi commerciali (98,1 % interpretato)

Formato prevalente: `Nome commerciale: 5 mg cp.riv. /die (ore 8) ;`

| Livello | Voci | % |
|---|---|---|
| 1 — nome + posologia | 5 480 | 95,62 % |
| 2 — prescrizione infusionale | 14 | 0,24 % |
| escluso: non farmacologico | 28 | 0,49 % |
| nessuna terapia dichiarata | 98 | 1,71 % |
| **non interpretato** | **111** | **1,94 %** |

Due differenze sostanziali rispetto alla dimissione, entrambe con conseguenze
architetturali: qui compare **solo il nome commerciale**, mai il principio
attivo (**827 nomi distinti**), e il nome porta spesso un'abbreviazione del
produttore (`Atorvastatina sa`, `Olmesartan medox al`, `Acido acetils au`).

È emerso un **secondo formato** non previsto, la prescrizione infusionale, dove
il farmaco segue la dose invece di precederla:
`125 mg di Furosemide salf*5fl 250mg/25ml in 100 ml Fisiologica`. Riconosciuto
con un pattern dedicato.

### 4.3 Il "ponte" fra i due campi terapia — risultato chiave per lo step 2

La dimissione espone la coppia *(principio attivo, nome commerciale)*; l'ingresso
espone solo il nome commerciale. Incrociandoli si copre gran parte del problema
di normalizzazione **senza inventare nulla**:

- 787 radici di nome commerciale ricavate dalla dimissione;
- **691 degli 827 nomi in ingresso (83,6 %) risolvibili a un principio attivo**;
- solo **7 radici ambigue**, tutte banali: `coumadin → {Warfarin, Warfarin
  sodico}`, `humalog → {Insulina lispro, Insulina lispro da dna ricombinante}`.

⚠️ **Questo ponte è un'osservazione interna al dataset, non una knowledge base.**
Vale come *evidenza empirica* ("in questo ospedale Lasix è stato dispensato come
furosemide"), non come fonte autorevole. Nello step 2 ogni coppia andrà
**confermata contro una KB citabile** (AIFA per i medicinali italiani, WHO
ATC/DDD per i codici); le coppie non confermate vanno segnalate come tali. Il
ponte serve a *ridurre il lavoro di verifica*, non a sostituirla.

Dei 136 nomi non risolti, molti sono **generici con suffisso del produttore**
(`Atorvastatina eg`, `Acido folico doc`, `Aciclovir my`): il principio attivo è
il primo token, quindi una regola aggiuntiva nello step 2 ne recupererà buona
parte. Il resto richiederà una fonte esterna o un mapping manuale citato.

> I suffissi osservati (`sa`, `au`, `eg`, `my`, `zen`, `doc`, `abc`, `auro`,
> `sand`, `l.f.m.`, `teva`, `mylan`, `ratiopharm`) sono abbreviazioni di aziende
> farmaceutiche. Anche questa lista, nello step 2, va **confermata contro
> l'elenco AIFA dei titolari AIC** invece che compilata a mano: è esattamente il
> tipo di dato che sembra ovvio ma va citato.

### Versione precedente del repository

Il repository conteneva una prima versione (`src/preprocess.py`), che partiva
dallo stesso file grezzo `anamnesiterapie.txt` — conferma indipendente che è la
fonte giusta. I suoi file sono stati lasciati cadere per ripartire da zero come
richiesto; l'unico contenuto utile, la lista dei suffissi dei produttori, è
riportato qui sopra e resta consultabile in `git show b823c0d:src/preprocess.py`.

Salvato in `data/interim/ponte_commerciale_principio.csv`.

### 4.4 Allergie — presenti, ma molto sparse

Sottosezione semi-strutturata dentro l'anamnesi narrativa, con sottocategorie
(`Principi attivi (…)`, `Alimenti (…)`, `Mezzo di contrasto`, `Altro`, `Note`):

| Stato | Record | % |
|---|---|---|
| sezione assente (informazione ignota) | 525 | 52,5 % |
| assenza dichiarata ("non note") | 346 | 34,6 % |
| allergie presenti | 129 | 12,9 % |

Ma solo **64 record (6,4 %)** documentano un'allergia a un **principio attivo**,
per **50 allergeni distinti**, quasi tutti antibiotici e FANS (`Diclofenac`,
`Levofloxacina`, `Trimetoprim/sulfametoxazolo`) — **quasi mai farmaci
cardiologici**. Ha una conseguenza diretta sul motore di raccomandazione
(§ 3.4 del brief): il filtro sulle allergie sarà corretto e implementato, ma
nella pratica scatterà su pochissimi pazienti. La sicurezza dovrà poggiare
soprattutto su controindicazioni e interazioni dalla KG.

Nota di modellazione già emersa: vanno tenuti distinti **sezione assente** e
**assenza dichiarata**. Il primo è "non sappiamo", il secondo è "il clinico ha
verificato che non ce ne sono".

### 4.5 Condizioni — solo prosa libera

Nell'export grezzo **non esiste alcun campo strutturato per le patologie**.
Sono tutte nell'anamnesi narrativa, che è poco regolare: **668 intestazioni di
sezione candidate distinte**, le più frequenti `Fattori di rischio` (558),
`Allergie e intolleranze` (474), `Anamnesi Remota` (468), `Anamnesi prossima`
(461), ma con una coda lunghissima di sigle (`APR`, `APF`, `EEC`) ed esami
(`RM cuore`, `Holter ECG`). **Non si può segmentare il testo in modo affidabile
sulle intestazioni.**

Parte del questionario dell'EHR sopravvive come **eco testuale** nella forma
`«Ipertensione arteriosa si.»`, ma la copertura è troppo scarsa per fondarci
sopra qualcosa: **268 record su 1000 (26,8 %)**, quasi solo polarità
affermativa (316 `si` contro 1 `no`), e appena **9 termini distinti**, di cui
solo 6 clinicamente reali (ipertensione arteriosa 149, obesità 130,
insufficienza renale 13, BPCO 13, scompenso cardiaco 5, distiroidismo 4).

Conseguenza: il **vocabolario delle patologie non è ricavabile dal dataset** —
a differenza di quello dei farmaci — e dovrà venire da una terminologia esterna
citabile (ICD-10 o equivalente), con il dataset a definire solo quali di quelle
voci sono pertinenti. È il campo che giustifica pienamente le tre pipeline di
estrazione: qui servono davvero gazetteer, gestione della negazione, LLM e NER.

## 5. Anomalie riscontrate

Nessuna anomalia **strutturale**: JSON valido, encoding UTF-8 coerente, nessun
`encOid` duplicato, nessun referto obbligatorio mancante, nessun campo vuoto.

Anomalie di **contenuto**, tutte quantificate e nessuna bloccante:

| Anomalia | Entità | Trattamento |
|---|---|---|
| Record senza terapia in ingresso | 98 (9,8 %) | legittimo ("Nessuna terapia domiciliare"), non è un errore |
| Record privi del referto di dimissione | 143 (14,3 %) | coorte separata, esclusa dalla valutazione |
| Record col referto ma senza voci estratte | 10 | da escludere dalla valutazione: ground truth inutilizzabile |
| Frammenti in prosa nel campo ingresso | 111 (1,9 %) | il clinico ha scritto la terapia a mano: `Rybelsus 14 mg 1 cpr la mattina, Jardiance…` |
| Frammenti non interpretati alla dimissione | 56 (0,9 %) | parentesi annidate: `(Propranololo 10 mg cps (galenico) cps.)` |
| Voci non farmacologiche | 74 | ossigenoterapia, CPAP/NIV: nessun codice ATC, escluse esplicitamente |
| Segnaposto `Nessun principio attivo` | 22 | campo non valorizzato dall'EHR, escluso dal vocabolario |
| **Duplicazione nei dati sorgente** | ≥ 2 record | il blocco di terapia è ripetuto verbatim (verificato su `encOid` 10223306 e 10219680) |
| Valore segnaposto `-` come nome commerciale | 15 voci | da trattare come mancante nello step 2 |

## 6. Decisioni tecniche prese in questo step

| Decisione | Motivazione | Alternativa scartata |
|---|---|---|
| Usare **solo** l'export grezzo `anamnesiterapie.txt` | i file derivati hanno l'estrazione già fatta da un LLM: costruirci sopra invaliderebbe il confronto fra le tre pipeline | i derivati, più comodi (campi separati, questionario codificato) ma non difendibili |
| Scartare il questionario `Anamnesi Strutturata` | di origine LLM, non verificabile | tenerlo come gold standard delle condizioni: sarebbe stato comodo ma ambiguo |
| Trattare il ponte commerciale→principio come **evidenza**, non come KB | è un'osservazione interna al dataset; le fonti autorevoli sono AIFA / WHO ATC | usarlo direttamente come dizionario: veloce, ma non citabile |
| Verificare il CSV ATC prima di tenerlo | proveniva dalla cartella dei file derivati | fidarsi del nome del file |
| Terapia alla dimissione **opzionale** nel loader | 143 record ne sono privi: è una caratteristica, non un difetto | segnalarla come anomalia: 143 falsi allarmi |
| Separare `data_loading.py` (loader) da `explore_dataset.py` (sonde) | il loader sarà riusato da tutti gli step; le sonde sono usa-e-getta | un unico script: avrebbe cristallizzato regex esplorative in codice riusato ovunque |
| Il loader **non solleva eccezioni**, accumula `Anomalia` | su dati clinici reali serve *misurare* quanti record sono difettosi | `raise` sul primo errore |
| Sonde a **livelli** con conteggio per livello | rende misurabile la regolarità del campo e lascia la voce annotata con la sua affidabilità | una singola regex permissiva: nasconderebbe le irregolarità |
| Guardia `nome_farmaco_plausibile()` sui livelli laschi | senza guardia il livello 3 accettava `Bisoprololo 3.75 mg 1 cp alle ore 08` (i due punti di `08:00` fingevano da separatore) | nessuna guardia: vocabolario inquinato alla radice |
| Escludere esplicitamente ossigeno/CPAP/NIV | non sono farmaci, non hanno codice ATC | includerli: entità spurie nel vocabolario |
| Preferire **precisione a copertura** nel vocabolario | il vocabolario chiuso è il fondamento di ogni step successivo: un nome sporco si propaga ovunque | la guardia ha alzato i non interpretati da 21 a 56: trade-off accettato consapevolmente |

## 7. Limiti noti e semplificazioni volute

- Le sonde di questo step **non sono i parser definitivi**: nascono nello step 3.
  Le regex qui misurano la regolarità dei campi, non estraggono per la produzione.
- I 56 frammenti non interpretati alla dimissione (parentesi annidate) sono
  lasciati irrisolti: 0,9 %, non giustificano un parser a stack in questa fase.
- Le sottocategorie di allergia sono censite ma non normalizzate ad ATC:
  è materiale per lo step 2.
- Il vocabolario delle patologie **non esiste ancora**: richiede una
  terminologia esterna (step 1/2), perché il dataset non lo fornisce.
- Il ponte commerciale→principio è **da validare contro una KB citabile** prima
  di poter essere usato come dizionario.

## 8. Componenti creati

| Modulo | Responsabilità |
|---|---|
| `src/data_loading.py` | Carica l'export grezzo in dataclass (`RecordPaziente`, `Referto`), distingue referti obbligatori e opzionali, raccoglie le `Anomalia` invece di sollevare eccezioni. **Nessuna interpretazione clinica.** Riusato da tutti gli step successivi. |
| `src/explore_dataset.py` | Sonde esplorative a livelli sui tre campi + generazione di report e vocabolari grezzi. Usa-e-getta: non sarà importato dalle pipeline. |

**Test** (`python3 -m unittest discover -s tests -v`, 29 test, nessuna dipendenza)

| File | Copre |
|---|---|
| `tests/test_data_loading.py` | caricamento: referto opzionale, `encOid` duplicato, accumulo delle anomalie senza eccezioni |
| `tests/test_sonde_esplorazione.py` | ogni livello delle sonde, la guardia sui nomi, le allergie a tre stati |

I test usano dati **sintetici** costruiti nel test stesso, mai il file clinico:
il dataset non è versionato, quindi chi clona il repository deve poter eseguire
i test lo stesso, e nessun dato di paziente deve finire in un file su GitHub.

Scriverli ha ripagato subito: hanno fatto emergere due difetti reali delle
sonde, il filtro `cicli notturni` che non intercettava `Cicli di NIV`, e il
segnaposto `Nessun principio attivo` che entrava nel vocabolario 22 volte.
Entrambi corretti, entrambi ora coperti da una regressione.

**Output rigenerabili**

| File | Contenuto |
|---|---|
| `reports/00_esplorazione.txt` | report completo, tutti i numeri citati qui |
| `data/interim/vocab_grezzo_farmaci_dimissione.csv` | 406 principi attivi + frequenze |
| `data/interim/vocab_grezzo_farmaci_ingresso.csv` | 827 nomi commerciali + frequenze |
| `data/interim/vocab_grezzo_nomi_commerciali.csv` | 1 236 nomi commerciali → principi attivi associati |
| `data/interim/ponte_commerciale_principio.csv` | 787 radici commerciali → principio attivo prevalente (67,2 % confermate da AIFA) |
| `data/interim/eco_questionario_condizioni.csv` | 9 condizioni riconoscibili a regola (copertura 26,8 %) |

## 9. Implicazioni per gli step successivi

1. **Step 1 (schema):** lo stato paziente deve distinguere tre stati di
   conoscenza — *affermato*, *negato*, *ignoto*. Le allergie lo richiedono già
   nativamente (sezione assente ≠ assenza dichiarata), e senza il questionario
   la distinzione va ricostruita dal testo, il che rende la logica di negazione
   della pipeline A un requisito, non un accessorio.
2. **Step 2 (normalizzazione):** ogni mapping va ancorato a una KB citabile.
   Il ponte interno (83,7 %) riduce il lavoro di verifica ma non la sostituisce.
   Il vocabolario delle patologie va costruito da una terminologia esterna.
3. **Step 3 (pipeline A):** le condizioni vengono **solo** dal testo libero;
   l'eco `«X si»` copre il 26,8 % dei record e 6 condizioni reali, quindi è un
   appiglio marginale, non una strategia. La segmentazione per intestazioni
   **non è affidabile** (668 varianti).
4. **Step 5 (pipeline C):** i 143 record senza dimissione sono testo aggiuntivo
   per il training silver e per collaudare estrazione ed entity linking.
5. **Step 11 (valutazione):** utilizzabili 847 record (857 − 10 con referto ma
   senza voci estratte). La ground truth sono i principi attivi del livello 1
   (96,1 %).
