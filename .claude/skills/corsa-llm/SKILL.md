---
name: corsa-llm
description: Eseguire o rimisurare qualsiasi componente del progetto che chiama un modello linguistico (pipeline B, ranker dello step 9, demo con --motore), e rifare un'analisi sulle risposte gia' pagate senza spendere. Usare PRIMA di lanciare uno script con --llm, --motore locale/openrouter, BackendOllama o BackendOpenRouter, e prima di stimare o riportare un costo.
---

# Corse con modello linguistico: cache, modelli, costo

Una corsa sbagliata qui non costa un errore: costa ore di CPU o denaro vero.
Il budget del progetto e' **5 $** e ne sono gia' stati spesi **4,4494**.

## La regola che governa tutto

**Locale per primo; si paga solo con numeri misurati alla mano.** Prima di
proporre una corsa a pagamento servono i token *misurati* su una prova gia'
fatta, il costo per candidato, e il confronto con quanto costa il locale in ore.
Senza quei numeri la risposta e' no. Mai l'API Anthropic: si paga a consumo e il
piano Pro non la copre.

## Gotcha: il modello predefinito NON e' quello delle corse fatte

`src/llm_backend.py` definisce `MODELLO_LOCALE_PREDEFINITO = "qwen3:4b"`, ma la
corsa dello step 9 e' stata fatta con **`qwen3.5:4b`**, passato da riga di
comando. La chiave di cache e' `sha256(modello + istruzioni + testo + schema +
temperatura + livello_ragionamento)`: **cambiare modello invalida tutta la
cache in silenzio.**

Costruire un backend senza nominare il modello ricalcola 244 risposte gia'
pagate — un'ora e mezza di CPU — senza nessun messaggio d'errore. Il sintomo e'
`ollama runner` al 190% di CPU e nessun output.

```python
BackendOllama(ragionamento="no", contesto=4096, modello="qwen3.5:4b")  # step 9
BackendOpenRouter(ragionamento="no")                                    # deepseek-v4.1-flash
```

Prima di lanciare una rianalisi, **verificare che la cache risponda** su un solo
record: se `risposta.da_cache` e' falso, il modello e' quello sbagliato.

## Rimisurare senza spendere

Ogni risposta e' in `data/interim/cache_llm/<impronta>.json` e **porta dentro il
proprio costo**. Quindi:

- una metrica nuova sulle stesse risposte e' **gratis**: si ricostruisce il
  ranker o la pipeline e si rilegge dalla cache, non si richiama il modello;
- il costo totale del progetto si **somma dai file di cache**, non si ristima
  dai token con un listino che puo' essere cambiato.

Lo schema di una corsa del ranker (`data/processed/ranker_step9*.json`) porta
gia' modello, chiamate, token, costo, codici scartati e contatori di qualita':
leggere quello prima di rilanciare qualsiasi cosa.

## Gotcha: uno schema JSON senza `maxItems` non termina

Sotto decodifica vincolata allo schema, un `array` di stringhe senza tetto
permette al modello di emettere voci all'infinito. Il modello locale lo fa: 310
voci da 91 candidati, fino a saturare il contesto, e il JSON torna troncato. **Il
sintomo si presenta come lentezza, non come errore.** Con `maxItems` e un
contesto adeguato: da oltre 240 s a 24 s per ricovero.

Ogni schema mandato a un modello deve avere un tetto su ogni array.

## Gotcha: l'uscita di un modello va vincolata all'insieme ammesso

Misurato sullo step 9: il modello remoto nomina 18 codici fuori elenco, quello
locale 40, di cui 15 inesistenti nel registro ATC dell'AIFA (`R05AA`…`R05AG`,
sette suffissi consecutivi: enumera l'albero invece di scegliere). Un codice
fuori elenco **scavalca il filtro di sicurezza dello step 8**, e un codice che
non esiste non puo' essere ne' vietato ne' verificato.

Scartare le uscite fuori insieme, e **contare quante volte succede**: e' la
misura di quanto il vincolo serva.

## Prima di dire «il modello fa X»

Due volte in questo progetto un difetto attribuito al modello era nel prompt o
nello schema, e una terza volta un'affermazione («non ordina, ricopia l'ordine
d'ingresso») veniva da una singola chiamata che era essa stessa in avaria:
misurata sulla corsa intera, 2 risposte su 239.

Quindi: **un comportamento si riporta solo se contato su tutta la corsa**, e una
cifra estrema (0% o 100%) si verifica sui dati grezzi e sulla potenza del
campione prima di scriverla. Se e' gia' stata scritta, si ritira nel testo — non
si cancella.

## Checklist di una corsa nuova

- [ ] il campo e' davvero testo libero? Un campo con delimitatori si legge con
      un parser: il deterministico fa 100% sulla terapia d'ingresso, il modello
      99,3% pagando.
- [ ] modello nominato esplicitamente, e cache verificata su un record
- [ ] ogni array dello schema ha `maxItems`
- [ ] l'uscita e' vincolata all'insieme ammesso, con contatore degli scarti
- [ ] avanzamento stampato per record (una corsa locale dura ore: senza
      avanzamento non si distingue «lento» da «bloccato»)
- [ ] il sottoinsieme di prova e' un **prefisso ordinato per `enc_oid`**, non un
      campione casuale: cosi' una corsa ripresa riusa la cache di quella prima
- [ ] token e costo scritti nel JSON di uscita
