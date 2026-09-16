# Indice architetturale

Documento vivo, aggiornato **a ogni step**. Dà la visione d'insieme di come i
componenti si collegano; il dettaglio di ogni step sta nel documento dedicato.

**Ultimo step completato: 9 — I tre ranker.**

Il filtro dello step 8 dice che cosa *non* si può dare; il ranker dice che cosa
conviene dare. E la verità di riferimento non è stata annotata: **era già nei
dati.** La terapia alla dimissione è la decisione che un cardiologo ha davvero
preso, su **841 ricoveri**, esatta e gratuita — la stessa proprietà che allo
step 7 aveva permesso di misurare il parser deterministico contro il campo
stesso.

**Due numeri decidono la forma dello step**, entrambi misurati prima di
scrivere una riga di ranker:

| | |
|---|---|
| copiare la terapia d'ingresso azzecca | **63,6%** della terapia di dimissione |
| prescrizioni di dimissione **non** cardiovascolari | **40,4%** |

Il primo obbliga a separare due compiti: prevedere la terapia completa è quasi
risolto senza ragionare, e il compito vero sono le **2 075 classi aggiunte**
durante il ricovero. Il secondo dà al ranker simbolico un tetto intorno al 60%
**per costruzione** — gastroprotettori, allopurinolo, levotiroxina e potassio
non stanno in nessuna linea guida cardiologica. Non ho colmato quel divario
inventando regole: sarebbe stata conoscenza di un modello travestita da linea
guida.

Sulle sole aggiunte, 244 ricoveri di prova:

| ranker | ric@3 | ric@5 | ric@10 | MAP |
|---|---|---|---|---|
| continuità della terapia | 10,4% | 11,7% | 12,5% | 0,114 |
| frequenza (non guarda il paziente) | 36,8% | 49,5% | 67,2% | 0,426 |
| simbolico (27 indicazioni ESC citate) | 20,3% | 28,0% | 31,0% | 0,210 |
| **ibrido** | **38,8%** | **53,1%** | **70,2%** | **0,456** |

**Le linee guida cardiologiche, da sole, sono un ranker peggiore del sapere
quali farmaci si prescrivono in questo reparto.** Tarando il peso delle
indicazioni su una parte di validazione ritagliata dall'addestramento, l'ottimo
è **piccolo ma non zero**: a peso nullo il richiamo@3 scende da 31,2% a 28,3%.

**E il ranker con modello linguistico perde contro un contatore, in locale come
in remoto.** Due modelli, stesso prompt, stessi 244 ricoveri:

| | ric@5 sulle aggiunte | costo | tempo |
|---|---|---|---|
| `deepseek-v4.1-flash` (remoto) | 24,0% | 0,1425 $ | 22 min |
| `qwen3.5:4b` (locale) | 19,7% | 0 $ | 1 h 34 min |
| frequenza (un contatore) | **49,5%** | 0 $ | istantaneo |

I 4,3 punti fra i due modelli sono sopra il rumore di fondo del progetto, ma
**sono molto meno dei 25 che li separano entrambi da un contatore che non guarda
nemmeno il paziente.** La ragione è misurata e conferma la tesi: l'**84,5%**
delle prime cinque proposte di `deepseek` è cardiovascolare (82,6% per `qwen`),
contro il 74,3% dell'ibrido. Propongono la cardiologia giusta — betabloccanti,
ACE-inibitori, sartani, statine — e mancano il 40% che cardiologia non è. Su
questo compito **sapere che cosa si prescrive in questo reparto vale più che
sapere la medicina**, non perché la medicina conti meno, ma perché il bersaglio
è una decisione reale e le decisioni reali contengono molto che le linee guida
non regolano.

Il vincolo all'insieme candidato separa i due modelli meglio delle metriche.
Sul remoto è scattato 18 volte, e **18 su 18 sono codici ATC reali che il
paziente sta già prendendo**: non allucina, ricopia dalla sezione «terapia in
atto» del prompt. Sul locale è scattato 40 volte, e **15 occorrenze non esistono
nel registro ATC dell'AIFA** — fra queste i sette suffissi consecutivi `R05AA`…
`R05AG`. Il modello piccolo non sceglie: enumera l'albero ATC scorrendo le
lettere. Per il modello remoto il vincolo è igiene; per quello locale è la cosa
che lo rende utilizzabile.

**Il filtro dello step 8 non esclude nulla, e la ragione è corretta.** Avevo
scritto che i due step «si incastrano»; la misura lo ha smentito. I due parlano
a livelli diversi dell'ATC — il filtro giudica un farmaco, il ranker propone una
classe — le allergie codificate sono **57 in 841 ricoveri**, e le due regole che
avrebbero potuto scattare erano già state declassate dal principio del fatto
mancante. Il tentativo di far incontrare i livelli per prefisso ha prodotto
subito un falso blocco esemplare: un paziente allergico all'**aspirina** a cui
il medico aveva prescritto **clopidogrel**, che è l'alternativa corretta proprio
per lui. È la terza volta nel progetto che una regola di sicurezza troppo larga
nega una terapia invece di proteggere, e la forma giusta è di nuovo quella dello
step 8: **avvertire, non vietare.** Dettagli in `09`.

---

**Step 11 — La valutazione gerarchica, e i punti che erano aritmetica.**
Lo step 9 conta una proposta giusta o sbagliata: proporre `C10AA` (statina) dove
il medico ha prescritto `C10BA` (statina in associazione) vale come proporre un
antibiotico. Lo step 11 misura quanto costa, e la risposta e' **molto meno di
quanto sembrava**.

Tre misure — richiamo per livello ATC, metriche gerarchiche classiche (hP, hR,
hF; Kiritchenko et al. 2005), quota degli errori di famiglia — e **un controllo
che viene prima di tutte: un ranker casuale a seme fisso**. Troncare i codici
alza il richiamo di chiunque, quindi un numero che sale dopo il troncamento non
dimostra niente da solo.

- **I 4-7 punti anticipati dallo step 9 sono un effetto del denominatore.**
  L'ibrido sale di ~5 punti salendo di un livello, ma **il caso ne sale 6,4**:
  al netto, il vantaggio dell'ibrido **cala** da +45,9 a +44,4. La metrica
  gerarchica non premia il ranker bravo, premia di piu' chi tira a sorte.
- **Il quasi-centro e' reale ma minoritario**, e l'aneddoto dello step 9
  indicava il ranker sbagliato: una proposta errata su sette dell'ibrido manca
  solo il sottogruppo chimico (14,2%, contro il 3,4% del caso), mentre il
  simbolico ne fa **4,8%** e sbaglia soprattutto dentro l'apparato giusto (43%).
- **I due modelli linguistici sbagliano come il simbolico**: 51,6% degli errori
  nel solo apparato. Propongono quasi sempre cardiologia e quasi mai la classe
  giusta — la stessa conclusione dello step 9, raggiunta da una misura
  indipendente.
- **`deepseek` al primo livello sta sotto il caso (-7,5 punti):** concentrarsi
  sul cuore costa, quando il 40,4% delle prescrizioni non e' cardiologia.

**Il bootstrap corregge lo step 9.** Su 1 000 ricampionamenti dei ricoveri — non
delle prescrizioni, che dentro un ricovero non sono indipendenti — la differenza
**ibrido meno frequenza sta in [-0,2%, +7,5%] e include lo zero**: il miglior
ranker del progetto **non e' misurabilmente migliore di un contatore che non
guarda il paziente**. Reggono invece le altre due affermazioni dello step 9: il
modello linguistico perde davvero contro il contatore (da -20 a -31 punti) e il
modello grande ordina davvero meglio del piccolo ([+0,1%, +8,2%], per un soffio).
Dettagli in `11`.

**Step 10 — Il tool MCP: il sistema diventa uno strumento per un altro agente.**
Cinque strumenti di sola lettura (`cardio_proponi_terapia`,
`cardio_sostegno_del_concetto`, `cardio_verifica_sicurezza`,
`cardio_cerca_codice`, `cardio_statistiche_corpus`), due client: Claude Code via
`claude mcp add` e un host locale con ollama.

La domanda che ha deciso il disegno non e' «quali strumenti esporre» ma **che
cosa un modello non deve poter fare**. Due vincoli, entrambi fissati da un test:

- **sola lettura**, dichiarata con `read_only_hint` perche' il client possa
  verificarla. Lo step 8 e' simbolico per vincolo: un modello che potesse
  toccare regole, grafo o insieme candidato scavalcherebbe l'unico strato che
  decide che cosa e' ammissibile;
- **il corpus non passa di qui.** Un client MCP puo' essere remoto — Claude Code
  manda il risultato di uno strumento a un modello che gira altrove — quindi un
  tool che leggesse un referto per `enc_oid` spedirebbe testo clinico fuori
  dalla macchina senza violare nessuna riga di `.gitignore`. La difesa sta nella
  **firma** degli strumenti, e un test verifica che nessuno accetti un
  identificativo di ricovero.

Il costo dice dove sta il collo di bottiglia: uno strumento risponde in
0,007-1,6 s, un giro del modello ne costa 12-52. L'orchestrazione costa due
ordini di grandezza piu' degli strumenti.

**Quattro corse col modello locale, e tre hanno trovato difetti — due miei.**
`qwen3.5:4b` sceglie lo strumento giusto quando la domanda e' in prosa, ma:

1. ricevendo proposte con `fonte: null` ha **inventato la motivazione**, con un
   «profilo nefroprotettivo» e `A02BC` (gastroprotettori) presentato come
   «betabloccante selettivo». Causa: lo strumento restituiva il tasso di base del
   reparto senza dire che non aveva estratto niente — la quarta ricorrenza del
   **principio del fatto mancante**, e la prima a questa frontiera. Ora ogni
   proposta dichiara il proprio `fondamento` e le estrazioni vuote sono
   segnalate;
2. passando il testo allo strumento **lo ha riscritto invertendo un fatto**:
   «iperteso» e' diventato «Ipotensione». Il server non ha modo di accorgersene,
   estrae correttamente dalla parafrasi, e produce offset di provenienza che
   puntano a parole che nessuno ha scritto. **La provenienza vale quanto il testo
   che arriva allo strumento**, e questo resta il limite non risolto dello step:
   la difesa e' un'istruzione, quindi e' debole.

Dopo le correzioni, sullo stesso testo, il modello **dichiara di non avere i
fatti e chiede quelli che gli servono** invece di fabbricare una raccomandazione.
Il merito non e' suo: e' del campo `fatti_mancanti`. Un modello conversazionale
riempie i vuoti che gli si lasciano, e l'unico modo di impedirglielo e' non
lasciarne. Dettagli in `10`.

**Step 9ter — La traccia: il grafo smette di essere un artefatto parallelo.**

Una domanda ha messo in luce un difetto architetturale vero: **il knowledge
graph dello step 7 non lo consumava nessuno.** Lo leggevano `interroga.py`, il
suo notebook e i suoi test; il filtro, il ranker e la demo leggevano i JSON
delle pipeline e lo scavalcavano. Un milione e duecentomila triple fuori dalla
catena.

Non era inutile — il numero che ha deciso il disegno dello step 8 (76,3% di
asserzioni su un solo agente, 14,8% di ridondanza vera contro il 46,6%
apparente) è uscito interrogando quel grafo. Ma era un artefatto **di analisi**,
non uno strato del sistema.

`src/traccia.py` lo rende uno strato. Ogni proposta si percorre all'indietro
fino alle parole esatte del referto, **interrogando il grafo in SPARQL**:

```
C03DA  ← indicazione ESC 2021, classe I
       ← condizione I50.9  (ICD-10 2019, Elenco Sistematico)
       ← asserzione, 1 agente
       ← menzione  A  Anamnesi 21–39  «scompenso cardiaco»
          regola: gazetteer:scompenso cardiaco
```

L'anello `ct:regola` è nuovo, e dice **come** il codice è stato assegnato:
`icd:termine_esatto` contro `icd:generalizzazione_ambigua` è la differenza fra
un codice certo e uno da guardare — e lo step 6 aveva misurato che gli errori
esclusivi della pipeline A arrivano già codificati, 9 su 9.

**Filtro e ranker continuano a non passare dal grafo, e la ragione è misurata**:
un'interrogazione SPARQL costa 12,43 ms contro 0,073 µs di una lettura da
dizionario, e le 5 863 valutazioni dello step 8 diventerebbero 73 secondi di
sole interrogazioni per ottenere gli stessi fatti. Gli strati che **decidono**
leggono la proiezione compatta; lo strato che **spiega** interroga il grafo. Un
test impedisce alle due proiezioni di divergere in silenzio — se lo facessero,
la traccia mostrerebbe la provenienza di una raccomandazione decisa su altro.
Dettagli in `09c`.

---

**Step 9bis — La demo, e i tre difetti che ha trovato.**

`src/demo.py` prende un'anamnesi scritta a mano e le fa attraversare l'intera
catena: riconoscimento, codifica ICD-10/ATC, filtro di sicurezza, ranker, con la
linea guida citata accanto a ogni proposta. Gira **senza rete, senza chiavi e
senza costo** — gazetteer e ConText — perché chi guarda deve poterla rieseguire.

Il progetto era arrivato allo step 9 senza che nessuno avesse mai **usato** il
contratto dati: ogni step lo produceva, lo misurava o lo confrontava. La demo è
il primo consumatore, e ha trovato subito tre difetti che nessuna metrica
mostrava:

| difetto | effetto sul corpus |
|---|---|
| `Non riferisce X` registrato come **affermato** — `riferisce` è un terminatore e chiudeva la negazione aperta da `non` | 4 attribuzioni su 5 237 |
| la pipeline A estraeva le allergie ma **non le codificava mai in ATC**, e il filtro confronta codici: lo strato di sicurezza era cieco | 46 allergeni ora codificati, **nessun numero dello step 8 si muove** |
| la **virgola decimale** («Bisoprololo 2,5 mg») scartava la voce, confusa con la virgola di elenco dei blocchi in prosa | 5 536 → 5 540 voci, 98,77% → 98,84% |

Presi uno per uno sono rumore in qualunque tabella. Guardati da dove il sistema
viene usato sono una negazione letta al contrario, uno strato di sicurezza cieco
e una prescrizione italiana normale che non viene letta. **Una metrica aggregata
misura la media, e i difetti di un supporto alla decisione non stanno nella
media.** Dettagli in `09b`.

---

**Step 8 — Il filtro di sicurezza simbolico.**

Provato contro la terapia che i cardiologi hanno davvero prescritto — la
verifica più severa disponibile senza dati nuovi: su **5 863 prescrizioni di
dimissione**, 91,3% ammesse, 8,6% da verificare, **4 vietate** (0,07%), tutte e
quattro farmaci prescritti a pazienti che il referto dichiara allergici a quella
stessa sostanza.

La prima versione ne vietava 28. Guardando i 24 di troppo uno per uno è uscito
**il risultato dello step 8**: lo strato di sicurezza ha bisogno di fatti che
nessuna pipeline era stata progettata per produrre. In **12 casi su 14** il
betabloccante bloccato per blocco atrioventricolare era prescritto a un paziente
con un **pacemaker** — che rende quella terapia sicura. `Z95.0` esiste nella
terminologia, ma un dispositivo non è una malattia e nessuno lo cerca. Ne segue
il principio, applicato in codice: *una regola che richiede un fatto che il
sistema non sa stabilire non può emettere un divieto; può segnalare.*

È la stessa forma di scoperta dello step 6, che rivelò l'asse mancante
dell'*experiencer*: **un difetto del contratto dati si vede solo quando qualcuno
prova a consumarlo.** Dettagli in `08`.

---

**Step 7 — Il knowledge graph RDF, con la provenienza come
struttura.**

> **Disegno dell'estrazione, rivisto.** A ogni campo il metodo più semplice che
> lo risolve: i due campi di terapia hanno delimitatori e li legge un **parser
> deterministico** (precisione e richiamo del 100% contro il campo stesso, dove
> il modello linguistico si fermava al 99,3%); al modello resta la sola prosa —
> condizioni, allergie, familiarità, e i farmaci di cui l'anamnesi racconta un
> fatto. Mandare un modello su un campo strutturato non aggiungeva capacità:
> aggiungeva costo e una sorgente di errore. Dettagli in `04` § 7duodecies.

Il grafo tiene le tre descrizioni dello stesso paziente senza fonderle, ciascuna
con l'indicazione di chi l'ha prodotta. Su 1 000 ricoveri: **68 120 menzioni,
32 907 asserzioni cliniche, 1 215 906 triple**, più le due terminologie intere
(7 211 codici ATC, 10 803 voci ICD-10) come schemi di concetti SKOS.

La decisione di modellazione è che **la menzione è un nodo**: le menzioni che si
sovrappongono nello stesso punto del referto diventano *una* asserzione sostenuta
da più menzioni, e `ct:numeroPipeline` diventa interrogabile in SPARQL.

**Il numero che decide lo step 8**, ottenuto interrogando il grafo:

| asserzioni che esistono solo grazie a quell'agente | |
|---|---|
| **B** (modello linguistico) | **12 819** |
| `campo_strutturato` (il parser condiviso) | 11 833 |
| C (riconoscitore neurale) | 192 |
| A (gazetteer) | 122 |

**Il 76,3% delle asserzioni poggia su un solo agente**, e una soglia di consenso
a due scarterebbe tre quarti del grafo: il contributo esclusivo della sola
pipeline con un richiamo alto, e per di più l'intera terapia dei pazienti.

Quel 76,3% è il risultato di una **correzione**. Il documento riportava prima
41,2%, con un «consenso a tre» del 46,6% che era falso: i dodicimila farmaci di
terapia comparivano in tutte e tre le pipeline, ma le tre li leggono con lo
**stesso** parser deterministico. Era una sola lettura contata tre volte, e il
filtro dello step 8 l'avrebbe scambiata per una conferma indipendente — fidandosi
di più proprio dove non aveva imparato nulla. Ora `ct:numeroPipeline` conta gli
**agenti distinti**, e la ridondanza vera è il 14,8%, non il 46,6%.

Altri due numeri che lo step 8 dovrà usare: **il 12,2% delle menzioni di
condizione non è una condizione attuale del paziente** (negata, incerta o di un
familiare), e le asserzioni codificate **dal solo gazetteer sono 129** — poche,
ma sono la categoria che lo step 6 ha identificato come la più insidiosa, perché
sbagliata e già codificata.

Vocabolari standard dove esistono: **PROV-O** per la provenienza, **SKOS** per le
terminologie, **DCMI** per citare le fonti — il vincolo di provenienza del
progetto vale anche per l'ontologia. Dettagli in `07`.

### Il richiamo, misurato allo step 6bis

Su 25 referti annotati a mano (619 entità) le due pipeline simboliche **mancano
quattro condizioni su cinque**:

| condizioni | precisione | **richiamo** | F1 |
|---|---|---|---|
| A (gazetteer) | 80,1% | **19,5%** | 31,4% |
| B (LLM) | 95,5% | **68,7%** | **79,9%** |
| C (NER) | 81,6% | **19,9%** | 31,9% |

| farmaci nella prosa | precisione | **richiamo** | F1 |
|---|---|---|---|
| A | 95,1% | 65,0% | 77,2% |
| B | 95,3% | 68,3% | 79,6% |
| C | 95,5% | 70,0% | 80,8% |

La ragione è strutturale: il vocabolario di A è costruito dai termini ICD-10 e C
è addestrata sulle etichette che A produce, quindi entrambe trovano **solo ciò
che la knowledge base già conosce**. Nella prosa cardiologica la maggior parte
delle condizioni non è scritta in forma da nomenclatura — «insufficienza paraprotesica» — e resta invisibile. La copertura ICD del 99,4% di A, che sembrava un
punto di forza, è il sintomo: il suo denominatore è ristretto a un quinto della
realtà clinica.

**Sui farmaci citati nella prosa la prima misura diceva B zero su sessanta, ed
era un mio difetto, non del modello.** La regola del prompt definiva i farmaci
come il contenuto delle due sezioni di terapia e non diceva mai che la prosa ne
contiene altri. È la seconda volta nel progetto che un difetto attribuito al
modello si rivela un difetto del prompt, e le due volte sono simmetriche: la
prima il modello *inventava* per via di un esempio positivo, qui *ometteva* per
via di una definizione troppo stretta. Racconto completo in `06b` § 8.

La correzione ha poi cambiato forma dopo una domanda che ha rimesso in
discussione l'obiettivo: **i farmaci vanno presi dai campi di terapia, che sono
strutturati; l'anamnesi serve ad altro.** Misurato, era esatto — e la conseguenza
è il disegno riportato in cima a questo documento. Dettagli in `04`
§ 7duodecies.

Quella indagine ha prodotto anche il **pavimento di rumore** del progetto: tre
corse dello stesso modello sugli stessi 25 referti danno 70,1%, 68,2% e 70,1% di
richiamo sulle condizioni. Nessuna differenza inferiore a **due punti** fra due
corse della pipeline B va letta come un effetto di qualcosa.

La decisione per lo step 7 — il knowledge graph da **tutte e tre le pipeline, con
la provenienza** — resta quindi giustificata, ma dall'argomento più solido:
**le condizioni**, dove il divario fra 20% e 70% di richiamo è strutturale,
misurato, e di un ordine di grandezza oltre il rumore.

Il riferimento ha **un solo annotatore**, che ha anche scritto le pipeline. I
limiti — cecità imperfetta, una passata di correzione dopo aver visto i
disaccordi, e linee guida che non decidono se una classe di farmaci sia un
farmaco — sono documentati uno per uno in `06b`, non nascosti.

### Una violazione di privacy trovata e corretta

Il controllo che vieta testo clinico verbatim nei file versionati esisteva ma
**guardava solo i file appena modificati**. Esteso a tutto il repository ha
trovato **28 frasi** in 8 file, fra cui esempi dentro il prompt della pipeline B.
Tutte sostituite con equivalenti sintetici. Il controllo è ora un modulo
versionato, `src/privacy.py`, che scandisce l'intero repository ed esce con
codice di errore se trova qualcosa, e sa distinguere il vocabolario pubblicato
(un titolo ICD-10 non è il dato di un paziente) da una frase narrativa.

---

**Step 6 — Confronto fra le tre pipeline, su tutti e 1 000 i record.**

Il risultato che conta non è quale pipeline vinca — nessuna vince, e le tre
precisioni distano fra loro meno dell'errore standard del campione. Conta che i
tre **profili di errore** sono qualitativamente diversi: **tutti gli errori
esclusivi della pipeline A portano con sé un codice ICD assegnato con sicurezza
(9 su 9)**, contro uno solo fra quelli di B e nessuno fra quelli di C. Il
gazetteer riconosce e codifica in un solo passo, quindi un match sbagliato è già
codificato; le altre due riconoscono prima e collegano dopo, e un riconoscimento
sbagliato resta visibile come irrisolto. È la distinzione che il filtro di
sicurezza dello step 8 deve tenere presente.

**La pipeline B è stata rieseguita** dopo le correzioni, e `src/rianalizza.py`
affianca le due corse segnando riga per riga l'esito su bersagli dichiarati
*prima* del rilancio. **199 record su 200** (erano 198), sette bersagli su otto
migliorati: i record oltre il tetto di 60 elementi passano da 14 a **zero**, la
terapia di dimissione recuperata da 376 a **756 voci** (dal 32,3% al 50,5%), le
menzioni non ancorate dal 13,0% al **9,5%**.

L'unica riga peggiorata è la più istruttiva. Le allergie non ancorate salgono al
65,2%, e sono **il mio esempio nel prompt che il modello ricopia**: la stringa
`mdc` compare 105 volte fra le allergie e 45 volte, per intero, fra le
condizioni, senza esistere in nessuno di quei referti. Su 64 record che dichiarano
«allergie non note», 56 (88%) hanno comunque un'allergia estratta. L'esempio
*negativo* accanto non è mai trapelato: **un esempio positivo offre un modello da
ricopiare, e il divieto scritto sotto non lo neutralizza**. Corretto in
`04` § 7nonies; l'impronta delle istruzioni è cambiata, quindi la prossima corsa
non si mescola con questa.

L'aggiudicazione ha trovato anche un **buco vero nell'asse experiencer**: «Zia e
nonna fibrillanti» viene attribuito al paziente con codice `I48`, perché il
lessico riconosce `familiarità per` e `anamnesi familiare` ma non i nomi di
parentela diretti. È il tipo di errore peggiore per lo step 8 — condizione
giusta, codice giusto, persona sbagliata — e va chiuso prima del filtro.

**È stato aggiunto un terzo backend, `BackendOpenRouter`**, dietro la stessa
interfaccia e la stessa cache degli altri due. Il collo di bottiglia non è mai
stato il denaro ma il tempo: 235 secondi per record significano 65 ore per il
corpus intero. Il campo che rende il backend sicuro è
`provider.require_parameters`: senza di esso OpenRouter può instradare verso un
fornitore che ignora `response_format`, e la garanzia strutturale della pipeline B
diventerebbe una speranza senza che nulla lo segnali.

**La pipeline B esiste ora in due versioni, e nessuna sostituisce l'altra:**
`qwen3:4b` in locale su 199 record (13 ore, gratis) e
`deepseek/deepseek-v4.1-flash` su **1 000 record (39 minuti, 2,42 $)**. È la
prima corsa completa del progetto, e rende le tre pipeline confrontabili
sull'intero corpus.

Tenere entrambe non è ridondanza: è ciò che permette di separare **quanto di una
differenza sia del metodo e quanto della taglia del modello**. Sugli stessi 199
record, con le regole di prompt sulle condizioni identiche, la versione remota
dimezza le condizioni per record (24,3 → 17,2), azzera i duplicati da generazione
degenere (13,2% → 0,3%) e le menzioni non ancorate (7,9% → 0,5%).

**Una conclusione dello step 6 è stata ritirata.** Avevo scritto che i campi
strutturati restano al parser perché *«non è un problema di capacità ma di
affidabilità»*: il modello locale leggeva la terapia di dimissione al 50%, in
modo bimodale, e non avevo trovato nessuna discriminante fra i record letti e
quelli saltati. Il modello remoto la legge al **99,6%**. La discriminante non era
nei record ma nel modello, e cercandola solo fra le proprietà dei dati non potevo
trovarla. I campi strutturati restano comunque al parser — non più perché il
modello sbagli, ma perché una regex fa lo stesso lavoro gratis, in 0,02 secondi e
in modo deterministico.

**L'aggiudicazione è stata rifatta su 60 menzioni** della versione remota: 91,7%
± 3,6 contro il 66,7% ± 8,6 della locale. È l'unico confronto di precisione del
progetto in cui gli intervalli **non** si sovrappongono; quelli di A, B-locale e
C si sovrappongono tutti fra loro e non ordinano nulla.

**Il buco dell'asse experiencer è chiuso.** «Zia e nonna fibrillanti» riceveva
`I48` attribuito al paziente. La regola nuova è stretta di proposito, costruita
sul corpus: il 4% delle occorrenze di un termine di parentela è l'*informatore*
(«la madre riferisce»), e marcarle familiari nasconderebbe al filtro una
condizione vera del paziente — un errore peggiore, perché in direzione opposta.
Effetto: 39 condizioni su 16 639 cambiano soggetto, 17 delle quali portavano un
codice ICD.

## Indice dei documenti

| Step | Documento | Stato |
|---|---|---|
| 0 | [`notebooks/01_analisi_esplorativa.ipynb`](../notebooks/01_analisi_esplorativa.ipynb) | ✅ analisi esplorativa eseguita |
| 6 | [`notebooks/02_confronto_pipeline.ipynb`](../notebooks/02_confronto_pipeline.ipynb) | ✅ confronto con aggiudicazione manuale |
| 0 | [`00_esplorazione_dati.md`](00_esplorazione_dati.md) | ✅ completato |
| 1 | [`01_schema_e_vocabolari.md`](01_schema_e_vocabolari.md) | ✅ completato, da validare |
| 2 | [`02_terminologia_icd10.md`](02_terminologia_icd10.md) | ✅ terminologia ICD-10 estratta |
| 2 | [`02b_risoluzione_atc.md`](02b_risoluzione_atc.md) | ✅ ATC dei farmaci risolto |
| 3 | [`03_pipeline_estrazione_A.md`](03_pipeline_estrazione_A.md) | ✅ completato |
| 4 | [`04_pipeline_estrazione_B.md`](04_pipeline_estrazione_B.md) | ✅ completato |
| 5 | [`05_pipeline_estrazione_C.md`](05_pipeline_estrazione_C.md) | ✅ completato |
| 6 | [`06_confronto_pipeline.md`](06_confronto_pipeline.md) | ✅ completato |
| 6bis | [`06b_riferimento_annotato.md`](06b_riferimento_annotato.md) | ✅ richiamo misurato su 25 referti |
| 7 | [`07_knowledge_graph.md`](07_knowledge_graph.md) | ✅ grafo RDF con la provenienza |
| 8 | [`08_filtro_sicurezza.md`](08_filtro_sicurezza.md) | ✅ filtro provato sulla terapia reale |
| 9 | [`09_ranker.md`](09_ranker.md) | ✅ tre ranker misurati sulle decisioni dei medici |
| 9bis | [`09b_demo.md`](09b_demo.md) | ✅ demo end-to-end su pazienti nuovi |
| 9ter | [`09c_traccia.md`](09c_traccia.md) | ✅ traccia di provenienza interrogata sul grafo |
| 7 | [`notebooks/03_knowledge_graph.ipynb`](../notebooks/03_knowledge_graph.ipynb) | ✅ interrogazioni SPARQL |
| 9 | [`notebooks/04_ranker.ipynb`](../notebooks/04_ranker.ipynb) | ✅ analisi del confronto fra ranker |
| 10 | [`10_tool_mcp.md`](10_tool_mcp.md) | ✅ server MCP di sola lettura, due client |
| 11 | [`11_valutazione.md`](11_valutazione.md) | ✅ metrica gerarchica, controllo casuale, bootstrap |

## Architettura di destinazione

```
                          data/raw/anamnesiterapie.txt
                       (export grezzo: 857 + 143 record)
                                        │
                                 [src/data_loading.py]          ← step 0 ✅
                                        │
                          ┌─────────────┴─────────────┐
                          ▼                           ▼
                 vocabolari chiusi              testo per paziente
                 farmaci: 406 principi + 923 marchi    │
                 condizioni: 249 candidate             │
                     step 1 ✅                          │
                          │                            │
                 [normalizzazione]                     │
                  ATC via AIFA: 94% ✅                  │
                  ICD-10 italiano estratto ✅           │
                     step 2                             │
                          │                            │
                          └───────────┬────────────────┘
                                      ▼
                    ┌─────────── tre pipeline di estrazione ───────────┐
                    ▼                 ▼                                ▼
             A: deterministica   B: LLM (locale)         C: NER + Entity Linking
                 step 3 ✅          step 4 ✅                    step 5 ✅
                    │                 │                                │
                    └────── etichette silver ────────────────────────►─┘
                                      │
                                      ▼
                    StatoPaziente (src/schema.py)             ← definito allo step 1 ✅
                                      │              confronto pipeline: step 6 ✅
                                      ▼
                    ┌───── motore di raccomandazione ─────┐
                    │  Fase 1 — filtro simbolico (step 8) │ ← mai LLM, mai dataset
                    │        │                            │
                    │        ▼                            │
                    │  Fase 2 — Ranker (step 9)           │
                    │   Symbolic / Hybrid / LLM           │
                    └────────────────┬────────────────────┘
                                     │        ▲
                                     │        └── grafo.ttl (rdflib) ← step 7 ✅
                                     ▼            PROV-O + SKOS, 1,2 M triple
                          Tool MCP (step 10 ⬜)
                                     │
                                     ▼
                          Valutazione ATC gerarchica (step 11 ⬜)
```

## Moduli esistenti e dipendenze

| Modulo | Dipende da | Usato da | Step |
|---|---|---|---|
| `src/data_loading.py` | solo stdlib (`json`, `dataclasses`, `pathlib`) | tutti gli step successivi | 0 |
| `src/explore_dataset.py` | `data_loading` | nessuno (usa-e-getta, non importato dalle pipeline) | 0 |
| `src/fetch_external_kb.py` | solo stdlib (`urllib`, `hashlib`) | step 2 (normalizzazione), step 7 (KG) | 0 |
| `src/verifica_ponte_aifa.py` | fonti AIFA + output di `explore_dataset` | nessuno (verifica di provenienza) | 0 |
| `src/schema.py` | `pydantic` | **tutti** gli step successivi: e' il contratto dati | 1 |
| `src/build_vocabularies.py` | `data_loading`, `explore_dataset`, `schema`, fonti AIFA | step 2 (normalizzazione), step 3 (gazetteer) | 1 |
| `src/extract_icd10.py` | `pdftotext` (poppler), PDF ICD-10 | step 3 (gazetteer condizioni), step 5 (entity linking) | 2 |
| `src/normalize_drugs.py` | `schema`, vocabolario, fonti AIFA | step 7 (KG), step 8 (filtro), step 11 (metrica ATC) | 2 |
| `src/gazetteer.py` | `spacy`, vocabolari chiusi | step 3, step 5 (candidati per l'EL) | 3 |
| `src/context_it.py` | nessuna (solo stdlib) | step 3, step 5, **tutte le pipeline** (asse experiencer) | 3 |
| `src/extract_a.py` | tutti i precedenti | step 5 (etichette silver), step 6, step 8 | 3 |
| `src/risolutori.py` | `schema`, mappatura ATC, terminologia ICD | **tutte** le pipeline: la normalizzazione dev'essere identica | 4 |
| `src/llm_backend.py` | solo stdlib (`urllib`, `hashlib`) | step 4, step 9 (LLMRanker), step 10 | 4 |
| `src/extract_b.py` | `llm_backend`, `risolutori`, `gazetteer`, `schema` | step 6 (confronto) | 4 |
| `src/entity_linking.py` | `risolutori`, terminologia ICD | pipeline A e C: la codifica dev'essere identica | 5 |
| `src/silver_labels.py` | uscita di `extract_a` | `ner_train`, `ner_infer` | 5 |
| `src/ner_train.py` | `torch`, `transformers`, bioBIT | produce il modello in `data/processed/ner_it/` | 5 |
| `src/ner_infer.py` | il modello addestrato | `extract_c` | 5 |
| `src/extract_c.py` | `ner_infer`, `entity_linking`, `extract_a` (parti condivise) | step 6 (confronto) | 5 |
| `src/migra_soggetto.py` | `data_loading`, `risolutori`, `schema` | migrazione una-tantum dello schema 1.0.0 → 1.1.0 | 5 |
| `src/confronto.py` | `risolutori`, uscite delle tre pipeline | step 6, notebook 02; lo step 7 ne riusa l'allineamento | 6 |
| `src/rianalizza.py` | `data_loading`, uscite di B | rimisura e affianca due corse qualsiasi di B | 6 |
| `src/riferimento.py` | `confronto`, annotazioni a mano | step 6bis, step 11 (valutazione) | 6bis |
| `src/privacy.py` | `data_loading`, terminologie | controllo che nessun file versionato contenga testo clinico | 6bis |
| `src/grafo.py` | `rdflib`, `confronto`, `risolutori`, ATC, ICD-10 | step 8 (filtro), step 9 (ranker), step 11 (metrica ATC) | 7 |
| `src/interroga.py` | `rdflib`, il grafo serializzato | le domande dello step 8, poste in SPARQL | 7 |
| `src/filtro.py` | `schema`, ATC, ICD-10 | step 9 (ranker), step 10 (tool MCP) | 8 |
| `tests/test_data_loading.py` | `data_loading` | — | 0 |
| `tests/test_sonde_esplorazione.py` | `explore_dataset` | — | 0 |
| `tests/test_pipeline_b.py` | `llm_backend`, `extract_b`, `risolutori` | — | 4 |
| `tests/test_pipeline_c.py` | `silver_labels`, `ner_train`, `entity_linking` | — | 5 |
| `tests/test_confronto.py` | `confronto` | — | 6 |
| `tests/test_riferimento.py` | `riferimento` | — | 6bis |
| `tests/test_grafo.py` | `grafo`, `rdflib` | — | 7 |
| `tests/test_filtro.py` | `filtro` | — | 8 |
| `notebooks/01_analisi_esplorativa.ipynb` | `data_loading` | analisi esplorativa: conteggi, distribuzioni, regex commentate | 0 |
| `notebooks/02_confronto_pipeline.ipynb` | `confronto` | il confronto con i grafici e l'aggiudicazione manuale | 6 |
| `notebooks/03_knowledge_graph.ipynb` | `grafo`, `rdflib` | il grafo esplorato: costo di ogni soglia di consenso, assi stato/soggetto, gerarchia ATC | 7 |

I test sono 301 in tutto e **nessuno usa la rete**: la pipeline B e' provata
con un backend fittizio, perche' una suite dipendente dall'API sarebbe lenta,
costosa e verde o rossa a seconda del carico dei server.

## Dati

| Percorso | Contenuto | Origine |
|---|---|---|
| `data/raw/anamnesiterapie.txt` | 1000 record (857 con terapia alla dimissione) | **export grezzo** del sistema ospedaliero, pseudonimizzato |
| `data/external/aifa/*.csv` | registro ATC in italiano, anagrafica confezioni, titolari AIC | **AIFA**, CC-BY 4.0, scaricate da `src/fetch_external_kb.py` |
| `kb/manifest_fonti.json` | URL, data, SHA-256 e scopo di ogni fonte esterna | versionato: la tracciabilità sopravvive al clone |
| `data/interim/*.csv` | vocabolari grezzi e ponte commerciale→principio | rigenerati da `src/explore_dataset.py` |
| `data/interim/vocabolario_farmaci.json` | 1 329 voci con esito del confronto AIFA e ATC candidati | `src/build_vocabularies.py` |
| `data/interim/vocabolario_condizioni.json` | 249 condizioni candidate con contesti e indizi di negazione | `src/build_vocabularies.py` |
| `data/interim/schema_stato_paziente.json` | JSON Schema generato dai modelli Pydantic | `src/build_vocabularies.py` |
| `data/external/ICD-10 2019 vol1...pdf` | ICD-10 2019 italiano, Centro Collaboratore OMS (FVG) | scaricato a mano da reteclassificazioni.it |
| `data/interim/terminologia_icd10.json` | 10 803 codici + indice di 13 642 termini italiani | `src/extract_icd10.py` |
| `data/interim/mappatura_atc.json` | 1 329 voci con ATC, metodo di risoluzione, fonte ed evidenza | `src/normalize_drugs.py` |
| `data/processed/pipeline_a/*.json` | uno `StatoPaziente` per record (1 000) | `src/extract_a.py` |
| `data/processed/pipeline_b/*.json` | uno `StatoPaziente` per record elaborato dall'LLM, più `_corsa.json` (registro con l'impronta della configurazione, che rende la corsa riprendibile) e `_riepilogo.json` (produzione misurata) | `src/extract_b.py` |
| `data/interim/cache_llm/*.json` | risposte del modello indicizzate per impronta: rendono ripetibile la valutazione | `src/llm_backend.py` |
| `data/interim/silver_ner/*.json` | etichette BIO divise per ricovero (700/150/150) | `src/silver_labels.py` |
| `data/processed/ner_it/` | modello NER addestrato e sue misure su sviluppo | `src/ner_train.py` |
| `data/processed/pipeline_c/*.json` | uno `StatoPaziente` per record dalla pipeline C | `src/extract_c.py` |
| `.env.local` | chiave API di Google AI Studio | **non versionato**, escluso da `.gitignore` |
| `data/processed/pipeline_a/*.json` | 1 000 stati paziente estratti dalla pipeline A | `src/extract_a.py` |
| `reports/00_esplorazione.txt` | report completo dello step 0 | rigenerato da `src/explore_dataset.py` |

## Test

`python3 -m unittest discover -s tests -v` — 219 test.

I test usano dati **sintetici** costruiti nel test stesso, mai il file clinico:
il dataset non è versionato, quindi chi clona il repository deve poter eseguire
i test lo stesso, e nessun dato di paziente finisce in un file su GitHub.

## Principi architetturali adottati

1. **Nessun dato derivato da LLM come fonte.** Il dataset canonico è l'export
   grezzo dell'ospedale. Le varianti già filtrate e strutturate da un LLM sono
   scartate: costruirci sopra significherebbe ereditare un'estrazione fatta da
   un altro modello, che è proprio ciò che il progetto deve implementare e
   misurare. Vale anche per il questionario clinico che quelle varianti
   aggiungevano.
2. **Ogni mapping deve venire da una knowledge base citabile.** Le conversioni
   nome commerciale → principio attivo → ATC, e condizione → ICD-10, si
   ancorano a fonti esterne riportate esplicitamente (WHO ATC/DDD, AIFA,
   openFDA, Wikidata). Le regolarità osservate nel dataset valgono come
   evidenza empirica da verificare, mai come fonte autorevole; le voci non
   coperte da alcuna fonte vanno segnalate come mapping manuali citati, non
   riempite silenziosamente.
3. **Separare caricamento e interpretazione.** `data_loading.py` non fa scelte
   cliniche: così un bug di parsing non si confonde mai con un bug di
   modellazione clinica.
4. **Misurare invece di assumere.** Le sonde di parsing sono organizzate a
   livelli e contano quante voci cadono in ciascuno: l'irregolarità dei campi è
   un numero nel report, non un'impressione.
5. **Le anomalie si accumulano, non si sollevano.** Su dati clinici reali serve
   sapere *quanti* record sono difettosi, non fermarsi al primo.
6. **Precisione prima della copertura sui vocabolari.** Il vocabolario chiuso è
   il fondamento di ogni step successivo: un nome sporco si propaga ovunque.
7. **Tre stati di conoscenza, non due.** Affermato / negato / ignoto. Il
   questionario li fornisce nativamente e collassarli perderebbe informazione
   clinica rilevante.
8. **Sicurezza clinica sempre simbolica.** La Fase 1 del motore dipenderà solo
   dalla Knowledge Graph, mai dall'LLM né dal dataset di training (step 8).
