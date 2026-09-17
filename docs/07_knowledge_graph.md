# Step 7 — Il knowledge graph: la conoscenza clinica e la provenienza

**Stato:** completato.
**Riproducibilità:** `python3 src/kb_build.py --figura` (conoscenza), `python3 src/grafo.py && python3 src/interroga.py` (provenienza)

Lo step 6bis ha misurato il richiamo delle tre pipeline sulle condizioni:
19,5%, 19,9%, 70,1%. **Nessuna descrive da sola il paziente.** Un grafo non è
quindi eleganza architetturale: è l'unica struttura in cui tre descrizioni
parziali e in parte contraddittorie convivono senza che qualcuno debba
scegliere fra loro *prima* di sapere quale sia giusta. La scelta resta
possibile, ma diventa una domanda da porre al grafo.

---

## 1. Due grafi, non uno: la conoscenza e la provenienza

Il brief §3.3 chiede un grafo di **conoscenza clinica** — `Drug`, `Condition`,
`Guideline`, `hasIndication`, `hasContraindication`, `recommendedBy` — in un
Turtle versionato in `kb/`, scritto da uno script di import rieseguibile. È
[`kb/conoscenza.ttl`](../kb/conoscenza.ttl), 805 triple, prodotto da
[`src/kb_build.py`](../src/kb_build.py) e letto da
[`src/conoscenza.py`](../src/conoscenza.py). **Il ranker e il filtro prendono
le regole da lì**: 27 indicazioni e 12 controindicazioni, ciascuna con motivo,
classe di raccomandazione o esito, e un nodo `Guideline` con la citazione. Un
test verifica che il Turtle nel repository sia identico a quello che lo script
rigenererebbe, così il motore non ha una copia privata della conoscenza.

Il resto di questo documento descrive il secondo grafo, quello della
**provenienza** (`data/processed/grafo.ttl`, 1,2 M triple, non versionato):
che cosa ogni pipeline ha letto in ogni referto. I due condividono i nodi
`icd:` e `atc:` — stesso spazio di nomi — e la traccia dello step 9ter li
percorre insieme: dalla regola in `kb/conoscenza.ttl` al codice ICD, dal codice
alle menzioni nel referto.

```
kb/conoscenza.ttl                           data/processed/grafo.ttl
kb:indicazione/C03DA-I50                    ric:10086915
  ct:farmaco     atc:C03DA                    ct:haAsserzione  ass:…
  ct:condizione  icd:I50  ◄──── stesso nodo ────  ct:concetto  icd:I50
  ct:classeRaccomandazione "I"                    prov:wasDerivedFrom men:… (pipe:A, 21–39)
  ct:recommendedBy kb:linea_guida/ESC-2021-…
```

![Il grafo di conoscenza: condizioni ICD-10 e classi ATC](img/conoscenza.png)

**Perché la curatela è manuale, misurato.** Il brief chiede di popolare il
grafo «primariamente da fonti esterne» e di valutarne la copertura. La sonda
`kb_build.py --sonda-wikidata` (17 settembre 2026, numeri nel manifest): dei
439 principi attivi risolti ad ATC, **372** hanno una voce Wikidata con quel
codice (P267); **273** hanno almeno una «condizione trattata» (P2175, 1 820
coppie); **158** almeno un'interazione (P769, 4 372 coppie). La copertura c'è,
ma manca ciò che rende una regola usabile qui: la classe di raccomandazione, il
documento citabile, e un codice ICD-10 per la condizione — lo step 1 aveva già
misurato che solo 343 malattie su 1 177 con etichetta italiana ne hanno uno.
Le 39 regole restano quindi una **mappatura manuale dichiarata** con fonte
puntuale, come il brief prevede per il layer delle linee guida; le
**interazioni farmaco-farmaco non ci sono**, e l'assenza è dichiarata: con 4 372
coppie Wikidata a livello di sostanza sarebbe la prima estensione, con lo stesso
script di import.

---


## 2. La decisione di modellazione che conta

La modellazione ovvia — `Ricovero ──haCondizione──▶ icd:I48` — perde **chi lo
dice**, cioè la distinzione fra una condizione vista da tre pipeline e una
vista dal solo gazetteer: quella che lo step 6 ha mostrato essere la più
pericolosa. Qui **la menzione è un nodo**, e il fatto clinico è derivato dalle
menzioni che lo sostengono:

```
Ricovero ─ct:haAsserzione─▶ AsserzioneClinica ─ct:concetto─▶ icd:I48 ─skos:broader─▶ …
                               │ ct:numeroPipeline 3
                               │ prov:wasDerivedFrom
                               ├──▶ Menzione (pipe:A, Anamnesi, 142–160, affermato, paziente)
                               ├──▶ Menzione (pipe:B, Anamnesi, 138–165, …)
                               └──▶ Menzione (pipe:C, Anamnesi, 142–172, …)
```

Le menzioni che si **sovrappongono** nello stesso campo dello stesso referto
diventano una sola asserzione, con la stessa logica di componenti connesse
dello step 6 (`confronto.raggruppa`, riusata e non riscritta: se il grafo
allineasse diversamente dal confronto, le due misure parlerebbero di oggetti
diversi con lo stesso nome). `ct:numeroPipeline` è quindi interrogabile: il
filtro può pretendere il consenso di due pipeline con tre righe di SPARQL.
Quando una pipeline porta più menzioni allo stesso punto, il gruppo resta
**ambiguo e marcato**, non risolto.

**Standard dove esistono.** PROV-O (W3C 2013, <https://www.w3.org/TR/prov-o/>)
per la provenienza — `prov:Entity`, `Activity`, `Agent`, `wasDerivedFrom`,
`wasAttributedTo`; SKOS per le terminologie — `Concept`, `broader`,
`notation`; DCMI `dcterms:source` per citare, dentro il grafo, da quale
knowledge base ogni concetto viene. Le gerarchie ATC e ICD si ricavano dai
codici (la lunghezza del codice ATC *è* il livello, per definizione OMS), non
si inventano. **Il testo clinico non entra nelle triple**: le menzioni
portano campo e offset, e chi ha il referto ritrova la citazione.

## 3. Che cosa c'è dentro

Costruito sui 1 000 ricoveri che tutte e tre le pipeline hanno elaborato — e
solo su quelli: un ricovero visto da due pipeline su tre falserebbe ogni
conteggio di consenso.

```
terminologie    ATC 7 211 concetti · ICD-10 10 803 voci
ricoveri         1 000        menzioni     69 533        asserzioni   32 716
  sostenute da 1 agente   24 966  (76,3%)
  sostenute da 2 agenti    2 907  ( 8,9%)
  sostenute da 3 agenti    4 843  (14,8%)
triple       1 210 305
```

**Perché «agente» e non «pipeline», e perché la differenza è enorme.** Una
versione precedente riportava 41,2% / 12,1% / **46,6%** di consenso a tre, ed
era falso. I farmaci dei campi di terapia — dodicimila menzioni, un terzo del
grafo — comparivano nell'uscita di tutte e tre le pipeline, che però li
leggono con lo *stesso* parser: **una sola lettura contata tre volte**. Il
filtro l'avrebbe scambiata per conferma indipendente proprio dove non aveva
imparato nulla. Ora esiste l'agente `campo_strutturato`, e `numeroPipeline`
conta gli agenti distinti: il consenso vero è 14,8%, e tre asserzioni su
quattro poggiano su un solo agente. Meno rassicurante, più vero.

## 4. Le interrogazioni, e che cosa hanno risposto

| domanda (SPARQL in `src/interroga.py`) | risposta |
| --- | --- |
| asserzioni codificate dal **solo** gazetteer | gli errori più pericolosi del progetto — un codice sbagliato che sembra certo (step 6: 7 errori su 8 di A arrivano codificati) — isolati come categoria che il filtro tratta a sé |
| contributo **esclusivo** di ciascun agente | B 12 819 asserzioni, parser 11 833, C 192, A 122 |
| negazione e familiarità sopravvivono? | affermato/paziente 23 574 · negato/paziente 1 433 · affermato/familiare 1 138 · incerto 489 · negato/familiare 190 |
| la gerarchia ATC percorsa (asserzioni per gruppo) | B01 antitrombotici 2 187 · C07 betabloccanti 1 338 · C03 diuretici 1 261 · C10 ipolipemizzanti 1 123 · C09 1 005 · A02 954 · A10 885 |
| quanto resta senza codice | condizioni **40,8%** (10 959 su 26 841), farmaci 8,8% — marcati, non rimossi |

## 5. Che cosa il grafo non fa, deliberatamente

**Non decide.** Non fonde le contraddizioni, non scioglie un `affermato`
contro un `negato`, non scarta le menzioni irrisolte, non sceglie un codice
quando due pipeline ne propongono due. La decisione appartiene allo step 8,
simbolico e ispezionabile, perché è il punto in cui il sistema smette di
descrivere e comincia a raccomandare. Il grafo conserva tutto e segna chi
dice cosa: è l'intero suo compito. Filtro e ranker non passano dal grafo
(una SPARQL costa 12,43 ms contro 0,073 µs di una lettura da dizionario,
step 9ter); la traccia sì, ed è così che risponde «da dove viene».

## 6. Test: le proprietà che, rompendosi, non si noterebbero

| proprietà | perché conta |
| --- | --- |
| menzioni sovrapposte → **una** asserzione | due pipeline d'accordo sembrerebbero due fatti distinti |
| lo stesso punto in **campi diversi** non si fonde | gli offset ripartono da zero in ogni campo |
| ogni menzione è attribuita al suo agente; il parser è un agente solo | nessuna interrogazione sulla provenienza darebbe la risposta giusta |
| il gruppo ambiguo è marcato; una menzione irrisolta **resta** | il grafo sembrerebbe più completo di quanto sia |
| stato e soggetto sopravvivono | una condizione negata, o del padre, diventerebbe del paziente |
| ogni concetto cita la fonte; la gerarchia ATC risale al livello anatomico | la metrica dello step 11 misurerebbe su un albero troncato |
| `kb/conoscenza.ttl` è identico a quello rigenerato da `kb_build.py` | il motore userebbe una copia diversa da quella dichiarata |
