# Step 4 — Pipeline B: estrazione con un modello linguistico

**Stato:** completato.
**Riproducibilità:** `python3 src/extract_b.py --motore openrouter` (la corsa completa è in cache: rieseguirla non chiama il modello e non costa)

Seconda delle tre pipeline di estrazione. Dove la pipeline A riconosce solo ciò
che è già nei vocabolari chiusi, questa legge la prosa dell'anamnesi come la
leggerebbe una persona: trova le menzioni, ne interpreta il contesto, scioglie
le abbreviazioni. È la pipeline con cui si misura quanto costa, in copertura,
la scelta deterministica dello step 3 — e quanto costa, in denaro e in errori,
la scelta opposta.

Questo documento è stato scritto passo per passo durante lo step ed è stato
poi **riscritto in forma breve**: le decisioni e i numeri sono gli stessi, la
cronaca è stata tolta.

---

## 1. Che cosa si chiede al modello, e che cosa no

Lo schema di uscita (`EstrazioneLLM` in `schema.py`) è più povero di
`StatoPaziente` per scelta: al modello si chiede solo ciò che sa fare in modo
verificabile.

**Non si chiedono i codici.** Un modello produrrebbe volentieri un ATC o un
ICD plausibile, ma sarebbe conoscenza interna, non tracciabile a una fonte.
ATC e ICD sono assegnati **dopo**, dagli stessi risolutori della pipeline A
(`risolutori.py`, su AIFA e sul volume ICD-10). Nello schema inviato al modello
non esiste un campo per un codice, e un test lo verifica. Effetto sul metodo:
a normalizzazione identica, il confronto dello step 6 misura la sola
differenza di *estrazione*.

**Si chiede la citazione letterale.** Ogni menzione riporta la porzione di
referto da cui viene, copiata carattere per carattere; la pipeline la cerca nel
testo e, se non la trova, l'entità resta senza offset e viene contata come
*non ancorata*. È il rilevatore di allucinazioni, ed è quantificabile: sulla
corsa finale, **0,3%** delle menzioni.

**Un solo campo interpretativo: `concetto`**, la forma estesa con gli acronimi
sciolti. Non è un codice e non viene creduto sulla parola: è la chiave di
ricerca nell'indice ICD, che resta l'unica autorità. È il punto in cui B può
superare A: `BBS` → «blocco di branca sinistra» → I44.7, dove il gazetteer non
ha appigli.

**Il modello non legge i campi di terapia.** Sono liste con delimitatori, e il
parser deterministico li legge al 100% (misurato sui 25 referti del
riferimento: 133/133 all'ingresso, 150/152 alla dimissione); il modello faceva
99,3% pagando, emetteva talvolta una voce per somministrazione invece che per
farmaco, e quei due campi erano il 28,6% del testo inviato e il 42,4% delle
voci prodotte. Ogni campo il suo metodo:

| campo | metodo | perché |
|---|---|---|
| terapia all'ingresso, alla dimissione | parser deterministico, condiviso dalle tre pipeline | ha delimitatori: non serve riconoscere, serve dividere |
| anamnesi — condizioni | modello linguistico | richiamo 70% contro il 20% di gazetteer e NER (step 6bis) |
| anamnesi — farmaci narrati («sospesa terapia con rivaroxaban») | modello linguistico | nessuna lista li contiene |
| anamnesi — allergie | modello linguistico | idem |

---

## 2. Backend intercambiabili, cache, ritentativi

`llm_backend.py` definisce un'interfaccia astratta e tre implementazioni —
Ollama (locale), OpenRouter (a consumo), fittizio (per i test) — dietro la
stessa `Richiesta` (istruzioni, testo, schema JSON, temperatura). Le chiamate
usano `urllib`, non un SDK: due funzioni in meno da spiegare, nessuna
dipendenza che cambia.

**Cache su disco per impronta della richiesta**: `sha256(modello +
istruzioni + testo + schema + temperatura + ragionamento)`. Ogni risposta
salvata porta dentro i propri token e il proprio costo. Conseguenze: una
metrica nuova sulle stesse risposte è gratis (la rianalisi dopo la correzione
dell'asse *soggetto* ha riletto 1 000 record in meno di un minuto, a costo
zero); il costo del progetto si somma dai file di cache, non si ristima. Il
modello fa parte della chiave: cambiarlo invalida la cache in silenzio, e la
skill `corsa-llm` lo ricorda.

**Ritentativi, provati facendoli fallire.** Due difetti dello stesso tipo, a
due livelli: `ErroreRitentabile` (JSON troncato dal modello) veniva sollevato
fuori dal `try` e non era mai ritentato; `IncompleteRead` (rete) discende da
`HTTPException` e non da `URLError`, e usciva dal ciclo come definitivo. La
seconda volta ha fermato la corsa finale a 510 record su 1 000. Ora c'è
`ERRORI_DI_RETE` su tutti i backend, con test di regressione che fanno fallire
davvero la cosa da assorbire; la ripresa ha ripagato solo 3 record su 491.

---

## 3. Quale modello, e perché

| tappa | modello | misura | decisione |
|---|---|---|---|
| prova del protocollo | Gemini flash via AI Studio, gratis | 20 richieste al giorno per modello | inutilizzabile per il corpus |
| locale | `qwen3:4b` via Ollama, GPU Radeon 860M | 159–235 s/record: 13 h per 199 record, 65 h per 1 000 | il corpus intero è fuori portata |
| locale, alternativa | `qwen3.5:4b` | più lento, citazioni ritrovate 60% contro 90,6% | scartato per l'estrazione |
| remoto | `deepseek/deepseek-v4.1-flash` via OpenRouter | 1 000 record in 39 min, **2,42 $** (0,5% non ancorate) | la corsa sul corpus |
| remoto, prompt finale | idem, senza i campi di terapia | 1 000 record, **1,65 $**, token in uscita −56% | la corsa definitiva (`pipeline_b_v3`) |

La scelta di pagare è stata presa con i token *misurati* sulla corsa locale
in cache, non con una stima: il confronto era 65 ore contro poco più di un
dollaro. Modelli locali specializzati ma non più mantenuti (medgemma) sono
stati esclusi a favore di un generalista recente.

Sugli stessi 199 record, a prompt identico, il passaggio da locale a remoto
dice che cosa era del modello e che cosa del compito:

| misura | `qwen3:4b` locale | `deepseek-v4.1-flash` |
|---|---|---|
| condizioni per record | 24,3 | 17,2 |
| duplicati fra le condizioni | 13,2% | **0,3%** |
| menzioni non ancorate | 7,9% | **0,5%** |
| farmaci elencati come condizioni | 44 | **0** |

---

## 4. I difetti trovati, e di chi erano

Sette difetti in questo step; cinque erano **miei**, del prompt o del codice,
non del modello. Ogni riga è stata trovata misurando, non ipotizzando.

| difetto | causa | correzione | misura |
|---|---|---|---|
| l'allergia `mdc` compare 105 volte in referti che non ne parlano | un esempio positivo nel prompt, ricopiato come contenuto | esempio tolto; regola senza esempi positivi | 105 → 0 |
| **zero** farmaci narrati nella prosa (0/60 sul riferimento) | una regola definiva i farmaci come contenuto delle sezioni di terapia | REGOLA 7 riscritta: il fatto, non il nome | 0% → **83,3%** di richiamo, 90,9% di precisione |
| «non noto distiroidismo» registrato come affermato | modello piccolo con le istruzioni nel campo `system`: 0 entità | istruzioni in testa al prompt; negazione misurata 2/4 → poi ConText a valle | vedi step 3 |
| il flutter atriale del **feto** attribuito alla paziente | lo schema non aveva l'asse del soggetto | `soggetto` (paziente / familiare / altro) nello schema 1.1.0, calcolato da ConText per tutte e tre le pipeline | 508 menzioni di familiarità nel corpus |
| 795 condizioni su 5 017 duplicate (15,8%), 529 in sei record | generazione degenere del modello locale sotto decodifica vincolata: JSON valido, semantica no | `maxItems` su ogni array; cambio modello | 13,2% → 0,3% |
| due record mai completati | uscita troppo lunga per il contesto (avevo attribuito la colpa al ciclo degenere: diagnosi ritirata nel testo) | tetto agli elementi, contesto adeguato | 240 s → 24 s per record |
| «terapia ritrovata da B: 100,0%» | A e C erano state prodotte prima delle correzioni al parser: 66 voci in meno | A e C rifatte (deterministiche, costo zero) | un 100% va verificato come uno 0% |

Il ripiego sulla **categoria ICD** (quando il termine esatto non esiste, la
categoria a tre caratteri) ha alzato le condizioni con codice dal 25,0% al
28,9%, con un vincolo imposto da un falso positivo: si applica solo quando la
categoria è nominata nel concetto stesso.

---

## 5. La corsa definitiva

`data/processed/pipeline_b_v3`, 1 000 record su 1 000, nessun fallimento:

| | |
|---|---|
| condizioni | 16 323, di cui **5 657 con codice** (34,6%), 1 223 ambigue |
| farmaci dai campi di terapia | 11 919, **dal parser**: identici alle altre pipeline per costruzione |
| farmaci narrati nella prosa | **2 174** (prima della REGOLA 7: 62) |
| allergie | 340 |
| menzioni non ancorate | 0,3% |
| costo | 1,65 $ (la prima corsa completa, con i campi di terapia, 2,42 $) |

Sul riferimento annotato (step 6bis): condizioni **richiamo 70,1%**,
precisione 96,1%; farmaci narrati richiamo 83,3%. Le condizioni senza codice
(65%) non sono errori del modello: sono il divario fra il lessico clinico e
quello del volume ICD («fibrillazione atriale» non è un termine indicizzato,
esistono solo le forme qualificate), cioè il problema di entity linking che lo
step 5 affronta.

---

## 6. Limiti

* **Nessuna verifica di correttezza clinica.** L'assenza di allucinazioni è
  provata nel senso letterale: le citazioni esistono nel testo. Che
  l'interpretazione sia giusta lo dice il riferimento dello step 6bis, su 25
  referti.
* **Il rumore fra corse.** A temperatura zero il modello remoto non è
  deterministico fra una corsa e l'altra: circa due punti di richiamo. È il
  rumore di fondo del progetto.
* **Il modello locale resta l'unica via senza spesa**, ed è 100 volte più
  lento: 13 ore per 200 record.

---

## 7. Componenti

| file | ruolo |
|---|---|
| `src/llm_backend.py` | interfaccia astratta; backend Ollama, OpenRouter, fittizio; cache per impronta; ritentativi |
| `src/extract_b.py` | prompt (le regole, con la citazione letterale), esecuzione concorrente e riprendibile, conversione in `StatoPaziente` |
| `src/risolutori.py` | `RisolutoreATC` e `RisolutoreICD`, condivisi con A e C |
| `schema.py` → `EstrazioneLLM` | lo schema che il modello riceve, senza campi per i codici |
| `tests/test_pipeline_b.py` | con il backend fittizio: il contratto intorno al modello, non la sua bravura |

```bash
python3 src/extract_b.py --motore locale --modello qwen3:4b --record 200   # 13 h
python3 src/extract_b.py --motore openrouter                              # cache: 0 $
```
