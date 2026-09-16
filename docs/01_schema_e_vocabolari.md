# Step 1 — Schema dello stato paziente e vocabolari chiusi

**Stato:** completato. Lo schema è stato validato dall'uso: è il contratto
dati di tutte le pipeline e del filtro, ed è passato alla versione 1.1.0 allo
step 5 (asse del soggetto).
**Riproducibilità:** `python3 src/build_vocabularies.py`

---

## 1. Cosa è stato fatto

Due cose distinte, che è utile non confondere:

1. **Lo schema** `StatoPaziente`: il contratto dati del progetto, cioè l'unica
   struttura che le tre pipeline di estrazione devono produrre e l'unico input
   che il motore di raccomandazione e il tool MCP accettano.
2. **I vocabolari chiusi**: quali farmaci e quali condizioni sono nello scope.
   Definiscono il *perimetro*, non le relazioni cliniche — quelle verranno
   dalle knowledge base esterne allo step 7.

## 2. Perché Pydantic

È l'unica dipendenza esterna introdotta finora, quindi va giustificata:

- **Valida invece di descrivere.** Un file intermedio che non rispetta lo schema
  viene rifiutato quando lo si carica, non tre step dopo sotto forma di errore
  incomprensibile.
- **Genera lo JSON Schema.** I file intermedi sono documentati in modo
  verificabile a macchina (`data/interim/schema_stato_paziente.json`) invece che
  a parole in un README che si disallinea.
- **Serve comunque allo step 10.** Il brief richiede modelli Pydantic per il
  tool MCP: definire lo schema con altri strumenti significherebbe mantenerne
  due versioni allineate a mano.

Alternative scartate: `dataclass` (nessuna validazione, nessuno JSON Schema, e
poi da riscrivere allo step 10); dizionari nudi (nessun contratto: ogni pipeline
avrebbe finito per produrre una forma leggermente diversa, e il confronto dello
step 6 avrebbe misurato le differenze di formato invece che di estrazione).

## 3. Lo schema: le decisioni che contano

### 3.1 Tre stati di conoscenza, non un booleano

È la scelta di modellazione più importante. Nei referti *«il paziente nega
diabete»* e *«del diabete non si parla»* sono cose diverse: la prima è
un'informazione clinica (il medico ha verificato), la seconda è assenza di
informazione. `StatoConoscenza` ha quindi quattro valori — `affermato`,
`negato`, `incerto`, `ignoto` — e l'`incerto` esiste perché il corpus contiene
davvero formulazioni dubitative (`sospetta`, `verosimile`).

Collassare negato e ignoto in un booleano perderebbe esattamente ciò che serve
al filtro di sicurezza dello step 8.

### 3.1bis Il soggetto, separato dallo stato *(aggiunto in 1.1.0)*

`StatoConoscenza` misura la **polarità** di un'affermazione, e nella prima
versione dello schema era l'unico asse disponibile. Il confronto fra pipeline A
e B su 198 record ha mostrato cosa mancava: davanti a *«Familiarità per
cardiopatia ischemica (padre)»* la pipeline A rispondeva `affermato` e la
pipeline B `negato`, e **nessuna delle due aveva ragione**. La frase non parla
della polarità: parla del **soggetto**. Il paziente non ha quella cardiopatia,
ma non è nemmeno vero che il referto la neghi — la attribuisce a suo padre.

È l'asse *experiencer* dell'algoritmo ConText, che ne ha quattro e di cui lo
schema ne rappresentava tre. Il campo `soggetto` (`paziente` / `familiare`) lo
aggiunge, e resta **indipendente** da `stato`: il corpus contiene *«familiarità
negativa per CAD»*, che è insieme familiare e negata. Comprimere i due assi in
un campo solo perdeva sempre una delle due informazioni.

Il dettaglio della regola, dei marcatori contati sul corpus e della migrazione
dei dati già prodotti sta in [`04_pipeline_estrazione_B.md`](04_pipeline_estrazione_B.md) § 7quater.

### 3.2 `stato_sezione_allergie`, separato dalla lista delle allergie

Corollario diretto del punto precedente, ed emerso dai dati: nello step 0 si è
visto che il 52,5 % dei record non ha proprio la sezione allergie e il 34,6 %
dichiara «non note». Una lista di allergie vuota è quindi ambigua. Il campo
separato scioglie l'ambiguità: `negato` significa «il clinico ha verificato»,
`ignoto` significa «non lo sappiamo». Senza, il filtro di sicurezza non
saprebbe quanto fidarsi di una lista vuota.

### 3.3 Provenienza obbligatoria su ogni entità

Il brief chiede che la pipeline A sia tracciabile (posizione nel testo e regola
che ha generato l'entità). Lo stesso oggetto `Provenienza` serve però anche a B
e C, dove `regola` diventa rispettivamente il prompt e il modello: così l'audit
è **uniforme fra le tre pipeline** e il confronto dello step 6 può ragionare
sugli stessi campi. Gli offset sono opzionali perché un LLM generativo riscrive
invece di puntare, e fingere un offset sarebbe peggio che ammettere di non
averlo.

### 3.4 Il grezzo non viene mai sovrascritto

`nome_grezzo` e `principio_attivo`/`codice_atc` sono campi separati. È l'unico
modo per poter verificare a posteriori una normalizzazione sbagliata, e per non
perdere informazione se la fonte esterna cambia.

### 3.5 `StatoNormalizzazione`: NIL distinto da NON_TENTATO

Lo step 5 richiede che le menzioni non collegabili siano marcate come entità
fuori KB, non forzate su un match sbagliato. Servono quindi valori distinti per
«ho cercato e non c'è nulla di affidabile» (`nil`), «ci sono più candidati e
nessuno prevale» (`ambiguo`) e «non ho ancora provato» (`non_tentato`). Il
default è il terzo: senza informazione esplicita lo schema non mente.

### 3.6 `farmaci_in_corso` esclude la dimissione

La terapia alla dimissione è ciò che il sistema deve **predire**. Usarla come
input sarebbe una fuga di informazione dalla ground truth. La proprietà è
esposta sullo schema, così il vincolo è nel contratto dati e non affidato alla
disciplina di chi userà la classe. Coperta da test.

## 4. Vocabolario dei farmaci — osservato e poi confermato

I farmaci sono elencati esplicitamente nei due campi terapia, quindi il
vocabolario è **osservato** dal dataset e poi confrontato con AIFA.

| | Totali | Confermate AIFA | Discordanti | Non trovate | Non verificabili | Con ATC candidato |
|---|---|---|---|---|---|---|
| **Principi attivi** | 406 | **285 (70,2 %)** | 0 | 121 | — | 285 |
| **Nomi commerciali** | 923 | **528 (57,2 %)** | 21 | 277 | 97 | 646 |

«Non verificabile» non è un fallimento: sono i 97 nomi commerciali che AIFA
conosce ma per i quali il dataset non dichiara mai un principio attivo — non
c'è nulla da confrontare, quindi non è un disaccordo.

### Perché 121 principi attivi non sono stati trovati — diagnosi

Non è rumore: guardando le voci per frequenza il pattern è sistematico e la
soluzione è identificata. **Sono tre cause, tutte risolvibili nello step 2:**

| Causa | Esempio | Come lo scrive AIFA | Frequenza nel dataset |
|---|---|---|---|
| **Associazioni con `/`** | `Rosuvastatina/ezetimibe` | `ROSUVASTATINA E EZETIMIBE` (C10BA06) | 217 |
| | `Sacubitril/valsartan` | `SACUBITRIL E VALSARTAN` (C09DX04) | 80 |
| **Forme saline** | `Warfarin sodico` | `WARFARIN` (B01AA03) | 57 |
| | `Candesartan cilexetil` | `CANDESARTAN` (C09CA06) | 9 |
| **Assenti dal registro AIFA** | `Silodosina`, `Febuxostat` | — | 28, 14 |

Le prime due cause sono conversioni di forma e coprono la grande maggioranza
delle voci mancanti. La terza è diversa: sono sostanze che il registro ATC di
AIFA non elenca affatto, quindi richiederanno una **seconda fonte** — è il
motivo per cui lo step 2 non potrà appoggiarsi ad AIFA soltanto.

Un test (`test_associazione_con_barra_non_matcha_la_convenzione_aifa`) fissa il
comportamento attuale proprio per rendere il problema visibile invece che
lasciarlo implicito.

## 5. Vocabolario delle condizioni — solo candidato, e il perché

Qui la situazione è strutturalmente diversa e va detta chiaramente: **nessun
campo del dataset elenca le patologie** (verificato nello step 0). Il
vocabolario è quindi solo *candidato*, ricavato dalla prosa, e il campo `codice`
resta **nullo per costruzione**: inventare un identificatore sarebbe
esattamente il tipo di ambiguità che il progetto vuole evitare.

**249 condizioni candidate** con almeno 3 occorrenze (4 457 voci sotto soglia
scartate, numero riportato nel file per trasparenza). Le prime per frequenza
sono cliniche e sensate: ipertensione arteriosa (103), ipercolesterolemia (70),
dislipidemia (48), obesità (31+22), fibrillazione atriale parossistica (18) e
permanente (18), ipertrofia prostatica benigna (17), ipotiroidismo (17), diabete
mellito tipo 2 (16), sclerosi valvolare aortica (16).

**60 voci portano un indizio di negazione** (`nega allergie`, `non angor`,
`non versamento pericardico`). In questo step vengono solo *annotate*, non
risolte: sono il materiale grezzo per la logica ConText della pipeline A, e
vederle elencate serve a dimensionare quel lavoro.

Due difetti sono stati corretti in corso d'opera, entrambi visibili
nell'ispezione dei candidati: le intestazioni di sezione restavano incollate al
termine (`Fattori di rischio: obesita si`) e la punteggiatura finale generava
duplicati (`nega episodi sincopali` vs `nega episodi sincopali.`). Dopo la
correzione le occorrenze si sono fuse correttamente — l'ipertensione è passata
da 99 a 103, le sincopi negate da 14+12 a 26.

## 6. Il punto aperto: quale terminologia per le condizioni

È la decisione che blocca lo step 2 sul lato patologie, e non è risolvibile
senza scegliere una fonte. Le opzioni sono state verificate, non ipotizzate:

| Fonte | Esito della verifica | Giudizio |
|---|---|---|
| **Wikidata** (CC0, SPARQL) | 1 177 malattie con etichetta italiana, **solo 343 con ICD-10**. Su 20 termini cardiologici reali: 15 trovati, **8 con ICD-10** — e le mancanze sono proprio ipertensione arteriosa, scompenso cardiaco, cardiopatia ischemica, insufficienza renale cronica | **Insufficiente come fonte primaria** |
| **ICD-9-CM italiano**, Ministero della Salute | È la codifica **ufficiale delle schede di dimissione ospedaliera italiane** — cioè esattamente il tipo di dato che stiamo trattando. Disponibile solo come PDF/XLS, e il sito risponde con una pagina di sfida anti-bot al download automatico | **Il più pertinente, ma va estratto da PDF** |
| **ICD-10 italiano**, portale reteclassificazioni.it | Esiste un browser ufficiale con API ClaML; le chiamate rispondono **302 verso il login**: serve una registrazione gratuita | **Praticabile, richiede un account** |
| **SNOMED CT** | L'Italia non è membro dell'International | **Escluso: licenza** |

Le prime due righe sono il vero bivio. Serve una tua decisione, o
l'autorizzazione a procedere con una delle due.

## 7. Componenti creati

| Modulo | Responsabilità |
|---|---|
| `src/schema.py` | Contratto dati: `StatoPaziente` e le entità estratte, più i modelli dei vocabolari. Nessuna logica, solo struttura e vincoli. |
| `src/build_vocabularies.py` | Costruisce i due vocabolari dal dataset, li confronta con AIFA e li serializza in JSON. |

| File prodotto | Contenuto |
|---|---|
| `data/interim/vocabolario_farmaci.json` | 1 329 voci con occorrenze per campo, varianti, principio attivo secondo il dataset, esito del confronto AIFA, ATC candidati e fonte |
| `data/interim/vocabolario_condizioni.json` | 249 candidate con occorrenze, record distinti, esempi di contesto e indizi di negazione |
| `data/interim/schema_stato_paziente.json` | JSON Schema generato dai modelli |

**Test:** 46 in totale (`python3 -m unittest discover -s tests -v`), di cui 17
nuovi su schema e vocabolari.

## 8. Principio seguito nei file intermedi: non si butta via niente

I JSON contengono **ogni** voce osservata, comprese quelle che nessuna fonte
conferma. Una voce non confermata non viene scartata né «aggiustata»: viene
**marcata**. Il motivo è pratico — una voce cancellata in silenzio è invisibile
e non la si può controllare, mentre una voce marcata `non_trovata` è una domanda
aperta che si può andare a guardare. I file sono indentati e con gli accenti non
sfuggiti proprio perché vanno letti a mano.

## 9. Limiti noti

- Il vocabolario delle condizioni è candidato, non validato: nessun codice.
- La soglia di 3 occorrenze è arbitraria e parametrica; va riabbassata quando
  ci sarà una terminologia contro cui filtrare il rumore in modo motivato.
- `atc_candidati` non è una risoluzione: una stessa denominazione commerciale
  può avere più ATC per confezioni diverse. Disambiguarli è lo step 2.
- I 21 nomi commerciali discordanti restano tali: nello step 0 si è visto che
  sono quasi tutti falsi disaccordi dovuti alle associazioni precostituite, ma
  finché non sono verificati uno per uno restano marcati come discordanti.
