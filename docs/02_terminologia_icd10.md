# Step 2 (parte 1) — Terminologia ICD-10 italiana

**Stato:** completato. La decisione del sez. 6 è stata presa come proposto: il
collegamento delle condizioni ai codici sta negli step 3 e 5
(`src/entity_linking.py`), dove ci sono negazione e riconoscimento.
**Riproducibilità:** `python3 src/extract_icd10.py`

---

## 1. La fonte

`ICD-10 2019 in italiano — Volume 1, Elenco sistematico`, pubblicato dal
**Centro Collaboratore Italiano dell'OMS per la Famiglia delle Classificazioni
Internazionali** (Regione Autonoma Friuli Venezia Giulia — Azienda Sanitaria
Universitaria Giuliano Isontina), distribuito da
[reteclassificazioni.it](https://www.reteclassificazioni.it/). È la traduzione
italiana ufficiale dell'ICD-10 dell'OMS.

Il PDF (890 pagine, 12 MB) è stato scaricato manualmente perché l'API del
portale richiede credenziali. Il file non è versionato; la citazione completa è
dentro `src/extract_icd10.py` e finisce nel JSON prodotto.

**Perché partire da un PDF.** Non è la strada che si sceglierebbe potendo, ma è
l'unica fonte verificata che soddisfi entrambi i vincoli del progetto: essere
autorevole e citabile, ed essere **in italiano** come i referti. Le alternative
sono state misurate, non ipotizzate (vedi `docs/01`, sez. 6): Wikidata copre 8 dei
20 termini cardiologici che servono, SNOMED CT non è licenziabile in Italia.
Il PDF è generato da Word, non scansionato, quindi l'estrazione è deterministica
e ripetibile — non un OCR probabilistico.

## 2. Cosa è stato estratto

| | |
|---|---|
| Codici totali | **10 803** |
| di cui categorie (3 caratteri, es. `I10`) | 1 970 |
| di cui sottocategorie (4 caratteri, es. `I11.0`) | 8 833 |
| Voci con termini inclusi | 602 |
| **Termini distinti nell'indice** | **14 898** |

Prodotto: `data/interim/terminologia_icd10.json` (4,3 MB), con per ogni codice
titolo, capitolo, termini inclusi ed esclusi, più un **indice termine → codici**
già pronto per il gazetteer.

### I termini `Incl.` sono il vero valore

Oltre al titolo ufficiale, l'ICD elenca i *termini inclusi*: i sinonimi con cui
la stessa condizione compare nella pratica clinica. Sono esattamente ciò che
serve al gazetteer della pipeline A e alla generazione dei candidati per
l'entity linking della pipeline C.

I termini `Escl.` **non** vengono raccolti come sinonimi. Per definizione
rimandano ad *altri* codici: usarli qui produrrebbe raccomandazioni fondate su
una diagnosi che il paziente non ha. Sono conservati a parte come rimandi, e un
test lo verifica.

### L'espansione dei parentetici

Nell'ICD le parole fra parentesi sono **modificatori opzionali**:

```
I10   Incl.: ipertensione (arteriosa) (benigna) (essenziale) (maligna) (primaria)
```

vale sia come «ipertensione» sia come «ipertensione arteriosa» e così via. È il
meccanismo che collega il nostro candidato più frequente — *ipertensione
arteriosa*, 103 occorrenze — al codice **I10**, e funziona.

Generiamo la forma senza modificatori più una per ciascun modificatore preso
singolarmente, **non** tutte le combinazioni: con sette parentetici sarebbero
128 forme, quasi tutte mai scritte da nessuno, e gonfierebbero il gazetteer di
rumore. I parentetici che contengono un codice (`(I27.2)`) sono rimandi, non
modificatori, e vengono rimossi.

## 3. Un bug di estrazione trovato e corretto: la graffa a due colonne

Il volume cartaceo raccoglie i sotto-elenchi con una **graffa tipografica** che
porta un suffisso comune a destra:

```
Incl.: ipertrofia:
        • adenofibromatosa            della prostata
        • (benigna)
        • del lobo medio
```

`della prostata` vale per tutte e tre le voci, ma `pdftotext` appiattisce la
graffa accodando il suffisso solo alla prima riga. Senza gestirlo, due termini
su tre perdevano la parte che li rende identificabili: `ipertrofia (benigna)`
invece di `ipertrofia (benigna) della prostata` — un termine inutilizzabile,
perché «ipertrofia benigna» da sola non individua nessuna condizione.

Il parser ora accumula i punti di un gruppo e applica il suffisso a tutti alla
chiusura. Coperto da un test di regressione.

## 4. Copertura sulle condizioni del dataset — il risultato che conta

Confronto delle 249 condizioni candidate (step 1) con l'indice ICD-10,
normalizzando accenti, maiuscole e articoli:

| Esito | Voci | % |
|---|---|---|
| match esatto | 19 | 7,6 % |
| match per contenimento | 26 | 10,4 % |
| **nessun match** | **204** | **81,9 %** |

**18,1 % collegabile con il puro confronto di stringhe.** È un risultato
negativo ed è bene averlo misurato adesso, perché dice due cose precise.

### 4.1 Il confronto di stringhe produce collegamenti *sbagliati*

Fra i match per contenimento:

| Candidato | Collegato a | Giudizio |
|---|---|---|
| `ipercolesterolemia` | E78.0 «ipercolesterolemia pura» | ragionevole |
| `ipotiroidismo` | E03 «altro ipotiroidismo» | ragionevole |
| **`asintomatica`** | **A52.2 «neurosifilide asintomatica»** | **palesemente sbagliato** |
| **`non versamento pericardico`** | **I31.3 «versamento pericardico»** | **polarità invertita** |

Gli ultimi due sono esattamente il tipo di errore che il brief chiede di
evitare: una menzione senza un candidato affidabile deve diventare **NIL**, non
essere forzata sul match più vicino. E il secondo mostra che **linkare senza
prima risolvere la negazione produce l'opposto del significato clinico**.

### 4.2 Molti candidati non sono diagnosi

Guardando i 204 non collegati per frequenza: `nega allergie` (37), `obesita si`
(31), `ex fumatore` (28), `nega episodi sincopali` (26), `asintomatico` (26),
`non recenti eventi infettivi` (20). Non sono patologie: sono **affermazioni di
negazione**, **fattori di rischio comportamentali** e **frammenti narrativi**.

Restano però anche condizioni vere non collegate, per differenze di
terminologia fra pratica clinica e ICD:

| Nel referto | Nell'ICD-10 |
|---|---|
| `scompenso cardiaco` | `Insufficienza cardiaca` (I50) |
| `dislipidemia` | `Disturbi del metabolismo delle lipoproteine e altre dislipidemie` (E78) |
| `fibrillazione atriale permanente` | `Fibrillazione e flutter atriali` (I48) + sottocodici |
| `ipertrofia prostatica benigna` | `ipertrofia (benigna) della prostata` (N40) |
| `sclerosi valvolare aortica` | area `I35` (disturbi valvolari aortici) |

## 5. Conseguenza architetturale

Il collegamento delle condizioni **non è un problema di normalizzazione a monte,
risolvibile con una tabella**. Richiede:

1. la **risoluzione della negazione** (`non versamento pericardico` non è I31.3);
2. il **riconoscimento delle entità**, per isolare la menzione dalla frase che
   la contiene, invece di trattare l'intero frammento come un termine;
3. una **generazione di candidati tollerante** con soglia di confidenza e
   gestione esplicita del NIL.

Che sono, nell'ordine, la logica ConText della pipeline A (step 3), il NER
(step 5) e l'entity linking (step 5). In altre parole: **il collegamento
condizione → ICD va spostato dentro le pipeline, non tenuto come passo
preliminare**.

Per i farmaci il discorso resta diverso e la strada dello step 2 è valida: sono
elencati in campi semi-strutturati, e il collegamento nome → ATC è una vera
normalizzazione da tabella (sez. 4 di `docs/01`).

## 6. Decisione richiesta (presa: vedi Stato)

Propongo di **riordinare gli step**: chiudere lo step 2 sui soli farmaci
(risoluzione ATC, dove le tre cause dei mancati match sono già diagnosticate e
hanno una fonte citabile), e spostare il collegamento delle condizioni dentro
gli step 3 e 5, dove ci sono negazione e NER.

L'alternativa è forzare ora una tabella condizione → ICD costruita a mano, che
sarebbe più veloce ma introdurrebbe proprio l'arbitrarietà non verificabile che
il progetto vuole evitare.

## 7. Componenti creati

| Modulo | Responsabilità |
|---|---|
| `src/extract_icd10.py` | Converte il PDF con `pdftotext -layout`, ricostruisce codici, titoli, inclusi/esclusi e capitoli, espande i parentetici e produce l'indice termine → codici. |

| File | Contenuto |
|---|---|
| `data/interim/terminologia_icd10.json` | 10 803 codici + indice di 14 898 termini + citazione della fonte |
| `data/interim/icd10_testo_estratto.txt` | testo grezzo del PDF, conservato per non riconvertire 890 pagine e per ispezionare cosa il parser legge |

**Test:** 9 nuovi (55 in totale), su frammenti sintetici che riproducono le
forme reali del volume, così girano senza il PDF, che non è versionato.

## 8. Limiti noti

- `-layout` è sensibile alla spaziatura: è il componente più fragile del
  progetto finora, ed è il motivo per cui i test coprono ogni forma di riga.
- L'indice non disambigua: un termine può puntare a più codici, e la scelta è
  lasciata all'entity linking, che ha il contesto.
- Restano voci spurie dalle tabelle di mortalità in coda al volume (codici
  `U85` con termini come «077 tumore maligno della prostata c61»): sono
  riconoscibili dal prefisso numerico e vanno filtrate quando l'indice verrà
  usato davvero.
- `aumento di volume (benigno)` sotto N40 non riceve il suffisso della graffa
  perché nel PDF precede il sotto-elenco: nel volume cartaceo la graffa
  probabilmente lo comprende. Caso isolato, lasciato com'è e segnalato qui.
