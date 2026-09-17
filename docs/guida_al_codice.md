# Guida al codice

Per chi deve leggere il repository senza aver seguito il progetto: che cosa fa
ogni modulo, con quali strutture dati, in quale ordine viene chiamato, dove è
testato. L'ordine è quello degli strati dell'architettura, dal dato grezzo
all'esposizione. Ogni modulo in `src/` è eseguibile da solo (`python3
src/<modulo>.py`) e ha il suo file in `tests/`; nessun test usa la rete.

```
dati e knowledge base ──▶ contratto dati ──▶ estrazione (A · B · C) ──▶ codifica condivisa
                                                                              │
     valutazione ◀── esposizione (MCP) ◀── decisione (filtro, ranker) ◀── grafo (conoscenza, provenienza)
```

Convenzioni: **italiano** ovunque (nomi, commenti, commit); nessuna lettera
accentata negli identificatori (`e'`, `piu'` nei commenti e nei docstring);
`RADICE = Path(__file__).resolve().parents[1]` in testa a ogni modulo per
trovare `data/` e `kb/` senza dipendere dalla directory corrente; i percorsi
dei dati sono costanti in maiuscolo, mai stringhe sparse.

---

## 1. Dati e knowledge base

### `data_loading.py` — il caricatore

L'unico punto che legge `data/raw/anamnesiterapie.txt` (un array JSON).

```python
@dataclass class Referto:        tipo, data, report_oid, testo
@dataclass class RecordPaziente: enc_oid, referti
    .testo(tipo) · .testo_anamnesi · .testo_terapia_ingresso · .testo_terapia_dimissione
    .ha_terapia_dimissione
@dataclass class Anomalia:       enc_oid, tipo_problema, dettaglio

carica_dataset(percorso) -> (list[RecordPaziente], list[Anomalia])
```

Non interpreta niente e **non solleva** su un record difettoso: accumula
`Anomalia`, perché su dati reali serve misurare quanti record hanno un
problema. `RecordPaziente` non è legato al file: la demo ne costruisce uno da
due stringhe (`demo.paziente_da_testo`).

### `explore_dataset.py` — le sonde dello step 0

Regex **a livelli** per i campi di terapia (`sonda_terapia_ingresso`,
`sonda_terapia_dimissione`: ogni voce esce con il livello che l'ha
interpretata), `sonda_allergie`, `sonda_intestazioni`,
`nome_farmaco_plausibile` come guardia sui livelli laschi. Scrive
`reports/00_esplorazione.txt` e i CSV grezzi dei vocabolari in `data/interim/`.
Le sonde misurano la regolarità dei campi; il parser di produzione è in
`extract_a.farmaci_da_campo_strutturato`, che le riusa.

### `fetch_external_kb.py` — le fonti esterne, con manifest

`FONTI` è una lista di dizionari (nome, URL, file, a che cosa serve).
`scarica()` salva il file e restituisce la voce di manifest con byte, SHA-256
e data; `kb/manifest_fonti.json` è il registro. Sono i CSV AIFA (registro ATC,
anagrafica confezioni, principi attivi, classi A/H). Il PDF ICD-10 è
scaricato a mano (il portale ha una sfida anti-bot).

### `build_vocabularies.py` — i vocabolari chiusi (step 1)

Dal dataset ricava le forme di farmaco osservate nei due campi di terapia e
le condizioni candidate dalla prosa (`costruisci_vocabolario_farmaci`,
`costruisci_vocabolario_condizioni`), le confronta con gli indici AIFA
(`carica_indici_aifa`, `conferma_principio_attivo`) e scrive
`data/interim/vocabolario_farmaci.json` (1 329 voci) e
`vocabolario_condizioni.json` (249 candidate). Il vocabolario chiuso è lo
**scope** del progetto (brief sez. 3.1): definisce quali farmaci contano, non le
loro relazioni.

### `extract_icd10.py` — la terminologia ICD-10 (step 2)

`estrai_testo` converte il PDF con `pdftotext -layout`; `analizza` percorre il
testo e ricostruisce le `VoceICD` (codice, titolo, livello, capitolo, inclusi,
esclusi) con le regex `PATTERN_CATEGORIA`, `PATTERN_SOTTOCATEGORIA`,
`PATTERN_INCLUSI`…; `espandi_parentetici` applica la convenzione ICD dei
modificatori fra parentesi («ipertrofia (benigna) della prostata» → due
forme); `costruisci_indice_termini` produce termine → codici. Uscita:
`data/interim/terminologia_icd10.json`, 10 803 codici, 14 898 termini.

### `normalize_drugs.py` — farmaco → ATC (step 2b)

`IndiciAIFA.carica()` costruisce gli indici dalle anagrafiche; `risolvi(nome,
tipo, occorrenze, indici)` applica la **cascata** di sei
`strategia_*` (principio esatto, associazione, forma salina, commerciale
esatto, commerciale abbreviato, suffisso salino) e restituisce una
`VoceMappaturaATC` con codice, candidati, **metodo** e stato (`risolto`,
`ambiguo`, `nil`). Le abbreviazioni dei produttori non sono una lista scritta
a mano: vengono dai titolari AIC delle liste A/H. Uscita:
`data/interim/mappatura_atc.json`, letta da `risolutori.RisolutoreATC`.

---

## 2. Il contratto dati: `schema.py` (step 1)

Modelli Pydantic v2. `StatoPaziente` è l'oggetto che le tre pipeline
producono e che filtro, ranker, grafo e tool MCP consumano.

```python
class StatoConoscenza(str, Enum):     AFFERMATO · NEGATO · INCERTO · IGNOTO
class Soggetto(str, Enum):            PAZIENTE · FAMILIARE · ALTRO
class MomentoTerapia(str, Enum):      INGRESSO · DIMISSIONE · NARRATIVO
class StatoNormalizzazione(str, Enum):RISOLTO · AMBIGUO · NIL · NON_TENTATO
class Pipeline(str, Enum):            A_DETERMINISTICA · B_LLM · C_NER_EL · CAMPO_STRUTTURATO

class Provenienza(BaseModel):
    pipeline, campo_sorgente, testo_originale, inizio, fine, regola

class CondizioneEstratta(BaseModel):
    testo_grezzo, concetto, codice, sistema_codifica, stato_normalizzazione,
    stato: StatoConoscenza, soggetto: Soggetto, provenienza
class FarmacoEstratto(BaseModel):
    nome_grezzo, principio_attivo, codice_atc, stato_normalizzazione,
    fonte_normalizzazione, momento: MomentoTerapia, stato, posologia, provenienza
class AllergiaEstratta(BaseModel):
    allergene, categoria, codice_atc, stato_normalizzazione, provenienza

class StatoPaziente(BaseModel):
    enc_oid, versione_schema ("1.1.0"), pipeline, generato_il,
    condizioni: list[CondizioneEstratta], farmaci: list[FarmacoEstratto],
    allergie: list[AllergiaEstratta], stato_sezione_allergie: StatoConoscenza,
    testo_supporto, note_estrazione
    .farmaci_in_corso()  ·  .condizioni_affermate()
```

Le scelte che contano: **tre stati di conoscenza** e non un booleano
(«non riferisce angina» è la stessa parola con verità opposta);
**soggetto separato dallo stato** (la malattia del padre è vera e non è del
paziente — asse aggiunto nella 1.1.0 dopo lo step 6); `stato_sezione_allergie`
separato dalla lista (sezione assente ≠ «non note» ≠ lista vuota);
**provenienza obbligatoria** con offset e regola su ogni entità; `NIL`
distinto da `NON_TENTATO`; il grezzo (`testo_grezzo`, `nome_grezzo`) mai
sovrascritto. `EstrazioneLLM` è lo schema più povero che il modello
linguistico riceve: senza campi per i codici (un test lo verifica).
`json_schema()` e `schema_estrazione_llm()` generano gli JSON Schema.

---

## 3. Estrazione: le tre pipeline

Tutte e tre producono `StatoPaziente`; i farmaci dei campi di terapia li legge
sempre `extract_a.farmaci_da_campo_strutturato` (una lettura sola nel
progetto); la codifica è condivisa (sez. 4). Uscite in
`data/processed/pipeline_{a,b_v3,c}/<enc_oid>.json`.

### `gazetteer.py` + `context_it.py` + `extract_a.py` — pipeline A (step 3)

`GazetteerClinico` costruisce un `PhraseMatcher` spaCy (`it_core_news_sm`)
dalle forme dei vocabolari chiusi — `carica_forme_farmaci` da
`mappatura_atc.json`, `carica_forme_condizioni` dalla terminologia ICD
filtrata da `termine_ammissibile` e arricchita da `varianti_derivate` — e
`trova(testo)` restituisce `Menzione(testo, forma_vocabolario, etichetta,
inizio, fine, inizio_token, fine_token, codici)`. `forma_farmaco_ammissibile`
scarta i residui di parsing (`5 mg`, `ore 17`) che come voci di gazetteer
facevano danno (difetto trovato allo step 5).

`context_it.py` è ConText riscritto per l'italiano: `Marcatore(espressione,
attributo, direzione, ampiezza)` in tre liste (`MARCATORI_NEGAZIONE`,
`_INCERTEZZA`, `_STORICITA`, ricavate contando nel corpus: `non` 2 665,
`nega` 522…), `TERMINATORI` che chiudono l'ambito, `trova_ambiti(doc)` →
`AmbitoAttivo`, `attributi_per_entita(ambiti, inizio, fine)`. L'asse del
soggetto è a parte: `ambiti_familiarita(testo)` e `soggetto_familiare(testo,
inizio, fine)` con `PATTERN_SOGGETTO_FAMILIARE` («familiarità per»,
«madre», «padre deceduto per»…) e una massima ampiezza.

`extract_a.estrai(record, gazetteer, risolutore, collegatore) ->
StatoPaziente`: farmaci dai campi strutturati, condizioni e farmaci narrati
dalla prosa via gazetteer + ConText (`stato_da_attributi`,
`regola_provenienza`), allergie con `allergie_dal_referto` (regex sulla
sottosezione «Allergie e intolleranze», più lo stato della sezione).

### `llm_backend.py` + `extract_b.py` — pipeline B (step 4)

```python
@dataclass class Richiesta:  istruzioni, testo, schema, temperatura, livello_ragionamento
    .impronta(modello) -> sha256     # la chiave di cache
@dataclass class Risposta:   contenuto (dict), modello, token_ingresso, token_uscita,
                             token_ragionamento, tentativi, da_cache, secondi, costo
class BackendLLM:            genera(richiesta) -> Risposta       # interfaccia
class BackendOllama, BackendOpenRouter, BackendGemini, BackendFittizio
class CacheRisposte:         leggi(impronta, modello) · scrivi(impronta, risposta)   # data/interim/cache_llm/
ERRORI_DI_RETE, ErroreRitentabile, ErroreQuotaGiornaliera, ErroreLLM
chiave_api(nome) -> str      # dall'ambiente o da .env.local
```

`extract_b`: `ISTRUZIONI` (il prompt con le regole numerate), `componi_testo`
(la **sola** anamnesi), `estrai(record, backend, …)` chiama il modello con
`EstrazioneLLM` come schema e `converti` traduce l'uscita in `StatoPaziente`:
ogni citazione viene cercata nel testo con `ancora` (se non c'è, la menzione
è *non ancorata* e conta), i codici li assegnano i risolutori, il soggetto lo
calcola ConText. `main` è una corsa **riprendibile**: `prepara_cartella`
verifica che la configurazione (`impronta_configurazione`) sia la stessa,
`salva_registro` scrive l'avanzamento, `misura_produzione` riassume.

### `silver_labels.py` + `ner_train.py` + `ner_infer.py` + `entity_linking.py` + `extract_c.py` — pipeline C (step 5)

`silver_labels`: dall'uscita di A, `Segmento(enc_oid, inizio_nel_referto,
testo, entita: list[EntitaSilver])` di al più 1 000 caratteri tagliati a fine
frase; `dividi` per ricovero (700/150/150) con seme. `ner_train`: `allinea`
(offset di carattere → etichette BIO per sottotoken, con la mappa del
tokenizzatore veloce), addestramento di `IVN-RIN/bioBIT` per token
classification, `valuta` **per entità**, salva in `data/processed/ner_it/`.
`ner_infer.RiconoscitoreNER.trova(testo) -> list[MenzioneNER]` riporta gli
offset al testo intero. `entity_linking.CollegatoreICD.collega(menzione)`
prova i metodi esatti di `RisolutoreICD` e poi `IndiceSimilarita.migliore`
(trigrammi di caratteri): la similarità restituisce sempre `AMBIGUO`, con
termine e punteggio nella provenienza, perché sbaglia 3 volte su 6.
`extract_c.estrai` = NER + ConText + codifica condivisa.
`sonda_ner_preaddestrato.py` esegue l'unico NER clinico italiano pubblico sui
25 referti del riferimento, con la stessa `riferimento.valuta`.

---

## 4. Codifica condivisa: `risolutori.py`

```python
class RisolutoreATC:  risolvi(nome) -> (codice, StatoNormalizzazione, fonte)
                      risolvi_menzione(menzione) -> (codice, stato, fonte, forma_usata)
class RisolutoreICD:  risolvi(testo) -> EsitoICD(codice, stato, concetto, candidati, metodo)
                      categoria(codice)            # la categoria a tre caratteri di un codice
soggetto_della_menzione(testo_campo, inizio, fine) -> Soggetto
```

`RisolutoreATC` legge `mappatura_atc.json` (il vocabolario chiuso risolto:
per forma, non per ricerca in AIFA a runtime — è il motivo per cui
«aspirina», mai vista nei campi di terapia, non risolve).
`risolvi_menzione` prova le scomposizioni di una menzione composta
(«Furosemide (Lasix cpr. 25 mg)») e, se due vie danno codici diversi,
restituisce `AMBIGUO`. `RisolutoreICD` cerca nell'indice dei termini (esatto,
poi con i qualificatori tolti, poi la categoria se nominata nel concetto).
Identica per A, B e C: lo step 6 confronta l'estrazione, non la codifica.

---

## 5. Confronto e riferimento (step 6, 6bis)

`confronto.py`: `Menzione` (enc_oid, sigla, tipo, campo, inizio, fine, testo,
codice, stato, soggetto, strutturata, regola) è la forma ridotta comune;
`carica(sigla, encs)` legge le uscite; `ripulisci` toglie i duplicati e
riclassifica i farmaci finiti fra le condizioni; `raggruppa(menzioni)` unisce
per **sovrapposizione di intervalli** nello stesso campo (componenti
connesse) in `Gruppo` (`.sigle`, `.ambiguo`, `.una`); `venn`, `accordo(a, b,
attributo)`, `copertura`, `solo_di(sigla)`; `confronta()` restituisce tutte le
misure. `rianalizza.py` confronta due corse della pipeline B sugli stessi
record. `riferimento.py`: `Entita` del riferimento risolta sugli offset,
`carica(anamnesi)`, `valuta(riferimento, menzioni, tipo)` → precisione,
richiamo, F1 con la regola «un'entità coperta da una sola menzione».

---

## 6. I due grafi (step 7, 9ter)

### `conoscenza.py` + `kb_build.py` — la knowledge base clinica

```python
class Esito(str, Enum):  AMMESSO · DA_VERIFICARE · VIETATO
@dataclass class Indicazione:       atc, icd: tuple, classe_racc, motivo, fonte, atc_richiesto, fatto_non_estratto   .uri
@dataclass class Controindicazione: atc, icd, esito: Esito, motivo, fonte, revocata_da, fatto_non_estratto        .uri
scrivi(indicazioni, controindicazioni, etichette_atc, etichette_icd, percorso) -> Graph
carica(percorso) -> (tuple[Indicazione], tuple[Controindicazione])
INDICAZIONI, REGOLE_CONTROINDICAZIONE = carica()     # letti da kb/conoscenza.ttl all'import
```

`kb_build.py` **dichiara** le 27 indicazioni e le 12 controindicazioni
(curatela con fonte), le scrive in `kb/conoscenza.ttl` con `scrivi` (nodi
`ct:Drug` con `atcCode` e etichetta AIFA, `ct:Condition` con etichetta ICD,
`ct:Guideline` con `dcterms:source`; relazioni reificate
`ct:Indicazione`/`ct:Controindicazione` più le scorciatoie `hasIndication`,
`hasContraindication`), aggiorna il manifest, disegna la figura bipartita
(`--figura`) e misura la copertura di Wikidata (`--sonda-wikidata`). Il
ranker e il filtro importano le regole da `conoscenza`; un test verifica che
il Turtle nel repository sia quello rigenerato.

### `grafo.py` + `interroga.py` + `traccia.py` — la provenienza

`grafo.costruisci()` legge le uscite delle tre pipeline, le riduce a
`confronto.Menzione`, le raggruppa con `confronto.raggruppa` e scrive
`data/processed/grafo.ttl` (1,2 M triple): `aggiungi_atc`/`aggiungi_icd`
(SKOS, con `skos:broader` ricavato dai codici), `aggiungi_menzione`
(campo e offset, **mai il testo**; `agente(m)` distingue le pipeline dal
parser condiviso), `aggiungi_gruppo` (una `AsserzioneClinica` per gruppo,
`prov:wasDerivedFrom` le menzioni, `ct:numeroPipeline` = agenti distinti).
`interroga.py` esegue le SPARQL di `PREDEFINITO`. `traccia.py` fa lo stesso
per **un** paziente: `grafo_del_paziente(stati, enc_oid, …)`,
`sostegno_del_concetto(g, codice)` (SPARQL: agente, campo, offset, regola,
testo riletto dal referto), `traccia_raccomandazione(g, classe, caso,
simbolico)` che unisce la regola (`Indicazione.uri` in `kb/`) al fatto
(l'asserzione nel grafo) tramite il codice ICD, `stampa_traccia`.

---

## 7. Decisione (step 8, 9)

### `filtro.py`

```python
@dataclass class StatoPerFiltro:  enc_oid, condizioni: list[{codice, testo, agenti}], allergie_atc: set, terapia_atc: set
@dataclass class Regola:          codice, descrizione, fonte
@dataclass class Verdetto:        atc, esito: Esito, motivi: list[dict]     .aggiungi(esito, regola, **dettagli)
valuta(stato, atc, regole=REGOLE_CONTROINDICAZIONE, esclusa_dalla_terapia=None) -> Verdetto
stato_da_file(percorsi, enc_oid) -> StatoPerFiltro
```

`valuta` applica in sequenza: allergia alla stessa sostanza (`VIETATO`),
allergia al sottogruppo ATC (`DA_VERIFICARE`), duplicazione di sostanza o
gruppo con la terapia in atto, controindicazioni per condizione (prefisso ATC
× prefisso ICD, solo su condizioni affermate del paziente), e le due regole
di declassamento: `fatto_non_estratto` sulla regola o condizione vista dal
solo gazetteer → un `VIETATO` scende a `DA_VERIFICARE`
(`PRINCIPIO_DEL_FATTO_MANCANTE`). Il verdetto è il massimo dei motivi (un
divieto vince su un dubbio). `main` prova il filtro sulle 5 863 prescrizioni
reali. Nessun modello, nessun dato di addestramento.

### `ranker.py` + `valuta_ranker.py`

```python
LIVELLO_CLASSE = 5;  classe(atc) -> atc[:LIVELLO_CLASSE]
@dataclass class Caso:            enc_oid, condizioni, terapia_ingresso, allergie, dimissione (frozenset)   .aggiunte
@dataclass class Raccomandazione: classe_atc, punteggio, motivo, fonte
class Ranker:  addestra(casi) · ordina(caso, candidati) -> list[Raccomandazione]
class RankerContinuita · RankerFrequenza · RankerSimbolico(indicazioni) · RankerIbrido(peso_guida) · RankerLLM(backend)
carica_casi(cartella) · pieghe(casi, quante, seme) · dividi(casi, quota_prova, seme)
insieme_candidato(casi, soglia=3) · applica_filtro(caso, candidati) · allerta_di_classe · annota
```

`RankerSimbolico.motivazioni(caso, cls)` = le indicazioni il cui prefisso
ATC copre `cls` e che scattano (prefisso ICD fra le condizioni del caso, o
`atc_richiesto` nella terapia); il punteggio è il **massimo** dei pesi
(`PESO_CLASSE`: I 1,0 · IIa 0,6 · IIb 0,3). `RankerIbrido.addestra` stima su
i casi di addestramento `log P(classe)` e la PMI condizione→classe (solo con
almeno 3 co-occorrenze e 5 casi); `ordina` somma `log P(classe) +
max PMI + peso_guida × punteggio simbolico` — a evidenza zero ricade sulla
frequenza, per costruzione. `RankerLLM` manda `descrivi_caso` con
`ISTRUZIONI_LLM` e `SCHEMA_LLM` (con `maxItems`), scarta e conta i codici
fuori dai candidati. `valuta_ranker.misura(ordini, bersagli)` calcola
richiamo@k, precisione@k, MAP.

### `demo.py`

`paziente_da_testo(anamnesi, terapia)` → `RecordPaziente`;
`estrai_deterministico` / `estrai_con_modello`; **`analizza(anamnesi, terapia,
motore, quante, modello, con_traccia) -> dict`** = estrazione +
`analizza_stati(stati, quante, con_traccia)`, che dallo `StatoPaziente` in
poi costruisce `StatoPerFiltro` e `Caso`, applica il filtro ai candidati,
ordina con l'ibrido, annota le indicazioni e gli avvertimenti, e se richiesto
la traccia. `esegui` stampa la stessa catena passo per passo. CLI:
`--esempio N`, `--interattivo`, `--anamnesi/--terapia file`, `--stato
file.json`, `--json`, `--traccia`, `--confronta`.

---

## 8. Esposizione: `mcp_server.py`, `mcp_client_locale.py`, `valuta_mcp.py` (step 10)

`mcp_server`: `MCPServer(name="cardio_mcp")` dell'SDK `mcp` 2.x; sei funzioni
decorate con `@mcp.tool(name, annotations=SOLA_LETTURA, description)`; la
descrizione è ciò che il modello legge per decidere. `_analisi` (con
`lru_cache`) chiama `demo.analizza`; `_confeziona` costruisce la risposta
(proposte con `fondamento`, `fatti_mancanti`, `ranker`, `avvertenza`).
`proponi_da_stato(stato_paziente: StatoPaziente)` entra in
`demo.analizza_stati`; lo schema JSON del parametro lo genera l'SDK dal
modello Pydantic. `verifica_sicurezza` rifiuta gli argomenti che non sono
codici del registro. Nessun tool ha un argomento che indichi un ricovero.

`mcp_client_locale`: apre il server via stdio, traduce gli strumenti nel
formato di ollama (`_schema_per_ollama`, `input_schema` → `parameters`), fa
girare il ciclo modello → chiamata → risultato per al più `GIRI_MASSIMI`
turni; `testo_fedele(passato, originale)` normalizza i due testi e verifica
che il primo sia un pezzo del secondo (il controllo a valle contro la
parafrasi). `valuta_mcp`: `DOMANDE` (dieci `Domanda` con lo strumento atteso),
`giudica(domanda, esito)`, uscita `data/processed/valutazione_mcp.json`.

---

## 9. Valutazione: `valuta_gerarchica.py` (step 11)

```python
LIVELLI = (1, 3, 4, 5, 7)                 # i cinque livelli ATC, in caratteri di prefisso
livelli_misurabili() -> quelli <= ranker.LIVELLO_CLASSE   # a unita' classe il 5o non c'e'
class RankerCasuale(seme=20260916)        # il controllo
precisione_richiamo_f1(proposti, veri) -> (P, R, F1)      # su due insiemi gia' troncati
terapia_proposta(caso, ordine, k) -> ingresso | prime k nuove
misure_per_livello(ordini, casi, k) -> {livello: {"P", "R", "F1"}}   # medie sui ricoveri
top_k_per_livello(ordini, casi, k) -> {livello: quota ricoveri con almeno un'aggiunta centrata}
@dataclass class Esito: sigla, nome, per_livello, top_k, ordini, casi
proiezioni(ranker, casi, candidati) -> ordini            # le classi nuove, per ricovero
valuta_incrociata(fabbriche, casi, quante, k, stratifica) -> list[Esito]   # candidati ricostruiti per piega
bootstrap(esiti, k, giri, seme, coppie) -> intervalli di F1 + differenze appaiate (F1 e top-k)
spiegabilita(esiti, k) -> quante proposte (e quanti centri) hanno un'indicazione
esempio_svolto(esito, enc, k) -> la misura fatta a mano su un ricovero, livello per livello
```

`ordini` è `{enc_oid: [classi nuove nell'ordine del ranker]}`, `casi` è
`{enc_oid: Caso}` (ingresso e dimissione stanno nel `Caso`): tutte le misure
sono funzioni pure di questi due dizionari, e il bootstrap ricampiona le
chiavi senza rieseguire nessun ranker. Con `--sostanza` si cambia
`ranker.LIVELLO_CLASSE` prima di caricare i casi, e tutto — candidati,
proposte, verità — lavora a 7 caratteri. Con `--llm`, `_llm_su_tutti` misura
il ranker remoto su tutti i casi dalla cache (`--llm-solo-cache`, zero spesa)
o con un tetto (`--tetto-dollari`).

---

## 10. Test

Un file per modulo in `tests/`, `python3 -m unittest discover -s tests -q`.
Tutti su dati sintetici o fittizi: `BackendFittizio` per la pipeline B, testi
inventati per demo e MCP, grafi costruiti in memoria. Alcune classi di test
fissano **proprietà** invece di casi: l'ibrido non fa peggio della frequenza a
peso zero; una condizione negata non controindica; menzioni sovrapposte
diventano un'asserzione sola; il Turtle in `kb/` è identico a quello
rigenerato; il server MCP non ha argomenti che indichino un ricovero; le
pieghe sono disgiunte e coprono tutti i casi; troncare i codici può
abbassare il richiamo. `tests/test_filtro_avversario.py` tiene i casi che il
filtro manca come `expectedFailure` con la causa: sono una misura, non un
difetto da nascondere.
