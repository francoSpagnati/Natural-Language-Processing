# Step 11 — La valutazione: precisione, richiamo e F1 per livello ATC

**Stato:** completato.
**Riproducibilità:** `python3 src/valuta_gerarchica.py --sostanza --esempi 4` (gratis, un minuto); `--llm --llm-solo-cache` per aggiungere il ranker LLM dalla cache (unità classe); `--stratifica` per le pieghe stratificate; `--cartella data/processed/pipeline_a` per un'altra pipeline.
Codice: [`src/valuta_gerarchica.py`](../src/valuta_gerarchica.py). Uscita: `data/processed/valutazione_step11.json`.

---

## 0. Le prove fatte, in una tabella

| sez. | prova | che cosa si misura | risultato in una riga |
| --- | --- | --- | --- |
| 3 | 5 ranker su 841 ricoveri, 5 pieghe | P / R / F1 a ogni livello ATC | ibrido e frequenza alla pari a ogni livello; alla sostanza staccano gli altri di 8–11 |
| 4 | stessi ranker | top-5: almeno un'aggiunta centrata | l'ibrido è avanti a ogni livello, [+4,7, +10,8] alla sostanza |
| 5 | + ranker LLM, dalla cache (unità classe) | P / R / F1, 4 livelli | LLM sotto la frequenza di 7–9 punti, alla pari col simbolico |
| 6 | ranker casuale a seme fisso | F1 di chi tira a sorte | 70,9 al 1° livello, 44,9 alla sostanza: la distanza dal caso è il guadagno vero |
| 7 | ibrido con lo stato da A, B e C | F1 per livello | identico a meno di mezzo punto |
| 8 | proposte con un'indicazione citabile | quota fra tutte e fra le centrate | ibrido 37,2 % contro 33,9 % della frequenza: tre punti |
| 9 | pieghe stratificate; tre casi reali | F1 per livello; proposte a mano | conclusione invariata; un caso sbagliato a ogni livello |

## 1. La misura, in una pagina

Per ogni ricovero il sistema produce una **terapia proposta**: la terapia
d'ingresso continuata, più le **5 classi nuove** che il ranker mette in cima.
La si confronta con la **terapia di dimissione** scritta dal medico, che è la
verità e che nessun ranker riceve. Il confronto si fa a ognuno dei cinque
livelli dell'ATC, troncando entrambi gli insiemi a quel livello:

| livello | esempio | che cosa conta come «giusto» |
| --- | --- | --- |
| 1° gruppo anatomico | `C` | stesso apparato |
| 2° gruppo terapeutico | `C07` | stessa area terapeutica (beta-bloccanti) |
| 3° gruppo farmacologico | `C07A` | stessa famiglia farmacologica |
| 4° sottogruppo chimico | `C07AB` | stessa classe chimica (beta-bloccanti selettivi) |
| 5° sostanza | `C07AB07` | stesso principio attivo (bisoprololo) |

A ogni livello, sui due insiemi troncati:

- **precisione** = quota delle proposte che il medico ha prescritto davvero
  («quanto di ciò che propongo è giusto»);
- **richiamo** = quota delle prescrizioni che il sistema aveva proposto
  («quanto di ciò che serviva ho proposto»);
- **F1** = media armonica delle due: alta solo se lo sono entrambe.

Le cifre sono medie sui ricoveri: ogni paziente pesa uno. È la metrica
primaria del brief (sezione 4), calcolata come chiede: codici risolti al 5°
livello, poi troncati livello per livello.

**Svolta a mano su un ricovero vero** (9764312; ingresso 5 sostanze, il
medico ne ha prescritte 9 alla dimissione, l'ibrido propone 5 nuove):

```text
ingresso           A02BC01 B01AC06 B05BA10 C09AA05 C10BA06
proposte nuove     A02BC02 B01AC04 C07AB07 C03CA01 B01AX06
dimissione (vera)  A02BC02 B01AA03 B01AC06 C03CA01 C03DA04 C07AB07 C08CA01 C09AA05 C10BA06

livello                   proposti  veri  comuni     P     R    F1
1° gruppo anatomico              3     3       3  100%  100%  100%
2° gruppo terapeutico            7     7       6   86%   86%   86%
3° gruppo farmacologico          7     8       6   86%   75%   80%
4° sottogruppo chimico           8     9       6   75%   67%   71%
5° sostanza                     10     9       6   60%   67%   63%
```

Al 5° livello il sistema centra 6 sostanze su 9: le 4 continuate più
`A02BC02`, `C07AB07`, `C03CA01` fra le nuove. Mancano `B01AA03` (warfarin),
`C03DA04` e `C08CA01`; le proposte `A02BC02` al posto di `A02BC01` e
`B01AC04` al posto di `B01AC06` sono giuste fino al 4° livello e sbagliate
al 5°: è esattamente ciò che la misura per livello deve mostrare.

E un ricovero in cui il sistema sbaglia (9092833): il medico non ha aggiunto
nulla (dimissione = ingresso, `C09CA06`), il sistema propone comunque 5
classi nuove, tutte sbagliate: P 17 %, R 100 %, F1 29 % a ogni livello dal 2°
in giù. Vale per il **15 % dei ricoveri** (127 su 841) in cui non c'è nessuna
aggiunta: il sistema propone sempre 5, e lì sbaglia sempre. È il limite
principale della misura, discusso nella sezione 10.

## 2. Il protocollo, comune a tutte le prove

- **Casi**: gli 841 ricoveri con terapia di dimissione codificata (media 7,0
  sostanze alla dimissione, 2,7 aggiunte). Stato del paziente dalla
  pipeline B (la sezione 7 mostra che la scelta non conta).
- **Unità del ranker**: la sostanza a 7 caratteri, come vuole il brief. I
  ranker ordinano sostanze e la tabella ha tutti e cinque i livelli. Il ranker
  LLM è stato interrogato a livello di classe (5 caratteri) e il budget è
  chiuso: sta in una tabella a parte (sezione 5), con quattro livelli.
- **k = 5** proposte nuove per ricovero, sempre.
- **Validazione incrociata a 5 pieghe**: pieghe deterministiche per hash del
  ricovero, il ranker impara sulle altre quattro, l'insieme candidato è
  ricostruito a ogni piega, ogni ricovero misurato una volta.
- **Bootstrap**: 1 000 ricampionamenti *dei ricoveri* con seme fisso; le
  differenze fra ranker sono calcolate dentro lo stesso ricampionamento
  (appaiate). Un intervallo che include lo zero = non distinguibile.
- **Controllo**: un ranker casuale con seme fisso, scritto prima dei risultati.
- **Rumore di fondo**: due punti percentuali (step 6bis). Una differenza
  minore, anche se il suo intervallo esclude lo zero, non si racconta.

## 3. La prova principale: cinque ranker, cinque livelli

**Che cosa si è provato.** I cinque ranker (casuale, continuità, frequenza,
simbolico, ibrido) su tutti gli 841 ricoveri in validazione incrociata a 5
pieghe, unità = sostanza.

**Che cosa si misura.** Precisione, richiamo e F1 della terapia proposta
contro la dimissione, a ogni livello ATC; intervalli al 95 % e differenze
appaiate di F1 dal bootstrap.

**Risultato.** P / R / F1 in %:

| ranker | 1° `C` | 2° `C07` | 3° `C07A` | 4° `C07AB` | 5° `C07AB07` |
| --- | --- | --- | --- | --- | --- |
| casuale (controllo) | 63,3 / 86,4 / 70,9 | 51,0 / 74,9 / 58,9 | 46,1 / 71,0 / 54,3 | 40,9 / 65,4 / 48,9 | 37,0 / 61,2 / 44,9 |
| continuità (copia l'ingresso) | 85,8 / 82,6 / 81,5 | 78,7 / 73,6 / 72,9 | 62,7 / 71,0 / 64,4 | 59,5 / 66,6 / 60,7 | 39,4 / 64,1 / 47,5 |
| frequenza, non guarda il paziente | 84,2 / 92,3 / **86,1** | 71,3 / 84,6 / **74,8** | 65,6 / 82,6 / **70,5** | 53,0 / 78,6 / 61,0 | 47,4 / 75,3 / 56,2 |
| simbolico, linee guida ESC | **90,0** / 80,8 / 82,5 | **77,0** / 73,2 / 72,2 | **68,6** / 70,3 / 67,1 | **62,3** / 65,7 / **61,8** | 38,8 / 63,5 / 46,9 |
| **ibrido**, indicazioni + co-occorrenza | 79,8 / **92,8** / 83,7 | 68,3 / **85,2** / 73,3 | 63,2 / **82,9** / 69,2 | 53,7 / **79,2** / 61,7 | 47,9 / **76,2** / **56,9** |

Intervalli al 95 % di F1 al 5° livello: ibrido [55,8, 58,1], frequenza
[55,1, 57,3], continuità [46,2, 48,7], simbolico [45,5, 48,2], casuale
[43,5, 46,4]. Tutti gli intervalli sono nel JSON.

Differenze appaiate di F1, in punti (stesso campione a ogni giro):

| coppia | 1° | 2° | 3° | 4° | 5° |
| --- | --- | --- | --- | --- | --- |
| ibrido − frequenza | [−2,9, −2,0] | [−2,0, −1,1] | [−1,8, −0,8] | [+0,1, +1,3] | [+0,1, +1,2] |
| ibrido − simbolico | [−0,1, +2,6] | [−0,1, +2,4] | [+1,0, +3,4] | [−1,2, +1,2] | **[+9,2, +10,9]** |
| frequenza − simbolico | [+2,4, +4,9] | [+1,4, +3,9] | [+2,2, +4,7] | [−1,9, +0,6] | **[+8,5, +10,3]** |
| frequenza − continuità | [+3,5, +5,7] | [+0,8, +3,1] | [+5,1, +7,1] | [−0,6, +1,3] | **[+8,0, +9,6]** |

**Lettura.**

1. **Ibrido e frequenza sono alla pari a ogni livello.** Le differenze di
   F1 stanno fra −3 e +1,3 punti, cambiano segno e restano dentro il rumore:
   un ranker che guarda il paziente non fa meglio di un contatore che non lo
   guarda. È il risultato negativo principale del progetto, confermato con
   le pieghe stratificate (sezione 9). La frequenza ha la precisione più alta
   dei due (84,2 contro 79,8 al 1°), l'ibrido il richiamo (92,8 contro 92,3):
   l'ibrido propone classi più sparse fra gli apparati, la frequenza le
   concentra in `C`.
2. **Alla sostanza frequenza e ibrido staccano tutto il resto di 8–11
   punti.** Simbolico e continuità hanno F1 da controllo casuale sulla
   sostanza (46,9 e 47,5 contro 44,9): le regole ESC nominano classi, non
   principi attivi, e sulla sostanza scelgono a caso dentro la classe.
3. **Il simbolico ha la precisione più alta a ogni livello dal 1° al 4°**
   (90,0 % al 1°, 62,3 % al 4°) e il richiamo più basso (80,8 % al 1°):
   propone poco e giusto. Fino al 3° livello il suo F1 sta sotto la
   frequenza di 1–5 punti, al 4° è indistinguibile. Il vantaggio della
   frequenza sta nel richiamo (+12 al 1°), non nella precisione.
4. **La continuità è un pavimento alto**: copiare l'ingresso dà già F1 81,5
   al 1° livello e 60,7 al 4°. Ogni ranker va letto come «quanto aggiunge
   sopra la copia»: al 4° livello +0,3 la frequenza, +1,0 l'ibrido, +1,1 il
   simbolico — niente. Il guadagno dei ranker sta tutto al 5° livello
   (+8/+9), cioè nello scegliere la molecola dentro la classe.

## 4. La prova top-5 del brief

**Che cosa si è provato.** Stessi ranker, stesse pieghe.

**Che cosa si misura.** Per ogni livello, la quota dei ricoveri (fra i 714
con almeno un'aggiunta) in cui **almeno una** delle 5 proposte nuove coincide
con un'aggiunta reale; differenze appaiate dal bootstrap.

**Risultato.**

| ranker | 1° | 2° | 3° | 4° | 5° |
| --- | --- | --- | --- | --- | --- |
| casuale | 81,2 | 47,6 | 39,5 | 23,8 | 10,8 |
| continuità | 49,0 | 32,6 | 32,6 | 32,6 | 31,7 |
| frequenza | 92,3 | 79,7 | 78,6 | 72,8 | 66,8 |
| simbolico | 74,2 | 46,1 | 40,9 | 27,7 | 25,4 |
| **ibrido** | **95,1** | **85,7** | **84,5** | **80,5** | **74,5** |

Differenza appaiata ibrido − frequenza: [+1,4, +4,1] al 1°, [+4,0, +8,2] al
2°, [+3,9, +8,1] al 3°, **[+5,1, +10,6]** al 4°, **[+4,7, +10,8]** al 5°.

**Lettura.** Qui l'ibrido è avanti, e sopra il rumore. Le due prove non si
contraddicono: l'ibrido **centra più spesso almeno una** aggiunta (tre
ricoveri su quattro al 5° livello, contro due su tre), ma sull'insieme
completo della terapia le sue proposte sbagliate pesano quanto quelle della
frequenza, e l'F1 non lo premia. Per un medico che guarda la prima riga
giusta, l'ibrido è il ranker migliore; per chi conta tutte le proposte, i
due sono uguali.

## 5. La prova col ranker LLM, dalla cache

**Che cosa si è provato.** Il ranker LLM (`deepseek-v4.1-flash` via
OpenRouter, 841 risposte già in cache: 0,48 $ registrati, nessuna spesa
nuova) ordina classi a 5 caratteri, quindi la prova è **a unità classe**,
stessi 841 ricoveri, gli altri ranker ricalcolati nella stessa unità.

**Che cosa si misura.** P / R / F1 ai quattro livelli misurabili a unità
classe, top-5, differenze appaiate. I numeri non sono confrontabili cifra
per cifra con la sezione 3 (unità diversa → insiemi diversi), la graduatoria
sì.

**Risultato.** P / R / F1 in %, unità = classe:

| ranker | 1° `C` | 2° `C07` | 3° `C07A` | 4° `C07AB` | top-5 al 4° |
| --- | --- | --- | --- | --- | --- |
| casuale | 59,1 / 87,5 / 68,5 | 47,9 / 74,2 / 56,5 | 42,7 / 69,7 / 51,5 | 38,0 / 63,7 / 46,3 | 13,4 % |
| continuità | 85,8 / 82,6 / 81,5 | 56,6 / 73,8 / 62,2 | 43,4 / 71,1 / 52,4 | 40,2 / 66,7 / 48,8 | 32,4 % |
| frequenza | 83,6 / 92,3 / **85,8** | 69,4 / 85,2 / **74,0** | 60,5 / 84,2 / **68,0** | 49,7 / 80,2 / **59,3** | 75,0 % |
| simbolico | 86,9 / 84,8 / 83,3 | 63,2 / 78,1 / 67,8 | 48,7 / 75,3 / 57,4 | 43,2 / 70,8 / 52,1 | 51,7 % |
| ibrido | 77,8 / 92,5 / 82,4 | 64,3 / 85,7 / 71,2 | 57,8 / 83,7 / 66,2 | 49,3 / 79,7 / 58,9 | **78,4 %** |
| **modello linguistico** | **88,8** / 81,1 / 82,1 | 62,9 / 77,2 / 67,0 | 50,1 / 74,3 / 58,0 | 42,2 / 69,5 / 51,0 | 45,8 % |

Differenze appaiate di F1: LLM − frequenza **[−5,1, −2,4]** al 1°, [−8,1,
−5,9] al 2°, [−11,1, −8,9] al 3°, **[−9,3, −7,3]** al 4°; LLM − simbolico
[−2,2, −0,2] al 1°, [−1,7, −0,5] al 4°. Top-5 al 4°: LLM − frequenza
[−33,5, −24,9].

**Lettura.** Il modello linguistico, vincolato all'insieme candidato e con lo
stesso stato del paziente degli altri, sta **sotto la frequenza a ogni
livello**, di 7–9 punti di F1 al 4°, e alla pari del simbolico. La sua
precisione al 1° livello (88,8 %) è la più alta della tabella: come il
simbolico, propone poco e cardiologico, e manca il 40,4 % che cardiologia non
è. Ha scartato 68 codici fuori elenco su 841 risposte.

## 6. Il controllo casuale

**Che cosa si è provato.** Un ranker che permuta i candidati con seme fisso
(20260916), scritto prima dei risultati, nelle stesse pieghe.

**Che cosa si misura.** Le stesse misure delle sezioni 3 e 4: è la riga
«casuale» di quelle tabelle.

**Risultato.** F1 70,9 al 1° livello, 44,9 alla sostanza; top-5 81,2 % al
1°, 10,8 % alla sostanza.

**Lettura.** Il 1° livello è generoso con chiunque: in un reparto di
cardiologia quasi tutto sta in `C`, e troncare lì fa coincidere proposte e
prescrizioni per aritmetica. Il guadagno vero di un ranker è la sua distanza
dal caso: +12 di F1 alla sostanza per l'ibrido, non i 57 punti della cifra
assoluta; +64 di top-5. Senza questa riga la tabella sembrerebbe migliore di
quanto è.

## 7. La prova per pipeline (metrica secondaria del brief)

**Che cosa si è provato.** Gli stessi ranker con lo stato del paziente
estratto dalle tre pipeline (A deterministica, B modello linguistico, C NER +
entity linking), stesse pieghe, unità sostanza.

**Che cosa si misura.** F1 per livello.

**Risultato.** F1 dell'ibrido:

| pipeline | 1° | 2° | 3° | 4° | 5° |
| --- | --- | --- | --- | --- | --- |
| A, deterministica | 83,6 | 73,2 | 68,9 | 61,6 | 56,9 |
| B, modello linguistico | 83,7 | 73,3 | 69,2 | 61,7 | 56,9 |
| C, NER + entity linking | 83,7 | 73,2 | 68,9 | 61,6 | 56,9 |

**Lettura.** Meno di mezzo punto a ogni livello. Il simbolico, che dipende
solo dai fatti estratti, varia di 1,5 punti al 3° livello (65,6 con A e C,
67,1 con B: B estrae più condizioni). Frequenza e continuità non leggono lo
stato e sono identiche per costruzione. La scelta della pipeline non decide
il risultato: la B è quella usata perché è l'unica con la cache del ranker
LLM.

## 8. La prova di spiegabilità

**Che cosa si è provato.** Le prime 5 proposte di ogni ranker su ogni
ricovero (4 205 proposte per ranker), unità sostanza.

**Che cosa si misura.** Una proposta è «motivata» se almeno un'indicazione
ESC del grafo di conoscenza scatta su quel paziente. Si conta la quota di
motivate fra tutte le proposte e fra quelle **centrate** (prescritte
davvero), perché è lì che una motivazione vale.

**Risultato.**

| ranker | proposte motivate | centri | centri motivati |
| --- | --- | --- | --- |
| frequenza | 27,3 % | 799 | 33,9 % |
| ibrido | 35,8 % | 866 | 37,2 % |
| simbolico | 86,1 % | 193 | 74,1 % |
| LLM (unità classe) | 46,8 % | 407 | 65,8 % |

**Lettura.** L'ibrido spiega 3 punti di centri in più della frequenza: un
vantaggio, non una categoria. Il simbolico spiega tre proposte su quattro,
ma a unità sostanza ne centra poche (193 contro 866).

## 9. Pieghe stratificate, e tre casi reali per codici

**Che cosa si è provato.** (a) Le stesse prove con pieghe stratificate per
patologia principale (strati I50, I48, I25, I10, altro), come chiede il
brief. (b) Tre ricoveri letti per codici, con le proposte dell'ibrido.

**Che cosa si misura.** (a) F1 per livello e differenze appaiate. (b) Il
livello ATC a cui ogni proposta incontra un'aggiunta reale (4 = classe
esatta, 0 = nessun gruppo in comune).

**Risultato (a).** F1 al 5° livello: ibrido 56,7, frequenza 56,1, simbolico
46,8; ibrido − frequenza [+0,0, +1,1] al 5°, [−2,7, −1,8] al 1°. Identico
alle pieghe per hash: la conclusione non dipende dalle pieghe.

**Risultato (b)**, prime cinque proposte dell'ibrido a unità classe:

| ricovero | condizioni estratte | terapia in atto | aggiunte vere | ibrido, prime 5 → livello |
| --- | --- | --- | --- | --- |
| 10235556 | *nessuna* | *nessuna* | A02BC, A10BK, B01AC, C03CA, C03DA, C07AB, C09CA, C10BA | A02BC → 4, C03DA → 4, C07AB → 4, C03CA → 4, B01AC → 4 |
| 9799541 | I31.3, J95, N19, R56.0 | *nessuna* | A02BC, B01AC, J01DD, M02AA | C03DA → 0, D07AC → 0, A02BC → 4, M04AC → 1, B01AX → 3 |
| 10067375 | E11, I10, I42.6, I48, I48.1 | A10BK, B01AF, C01BD, C03DA, C07AB, C09AA, C10AA | M04AC | B01AX → 0, A02BC → 0, B01AA → 0, C08CA → 0, C09CA → 0 |

**Lettura.** Il primo: l'estrazione non ha trovato nulla e il ranker centra
5 su 5, perché senza fatti l'ibrido ricade sulla frequenza, e in questo
reparto un ricovero senza terapia d'ingresso riceve i quattro pilastri più
il gastroprotettore. Il secondo è un paziente non cardiologico: il medico
aggiunge un antibiotico e un antiinfiammatorio topico, che nessun ranker può
prevedere dal profilo (F1 al 5° livello: 22 %). Il terzo sbaglia a ogni
livello: un paziente in fibrillazione già trattato con tutto, a cui viene
aggiunta la colchicina `M04AC`; la ragione non è fra le condizioni estratte.
Il sistema sbaglia dove il fatto che decide non c'è.

## 10. I limiti della misura

- **k è fisso a 5.** Nel 15 % dei ricoveri il medico non aggiunge nulla e il
  sistema propone comunque 5 classi: precisione 17 % garantita. Un sistema
  che sapesse *quando non proporre* guadagnerebbe su tutta la tabella; qui
  non c'è, e la misura lo paga onestamente.
- **Il riferimento è la decisione di un medico** per ricovero, non l'insieme
  delle terapie accettabili: una proposta ragionevole non prescritta conta
  come errore. La precisione è «accordo col medico», non correttezza.
- **Il 40,4 % delle prescrizioni non è cardiologico** (antibiotici,
  gastroprotettori, insuline): nessun ranker di questo progetto le prevede
  dal profilo, ed è il tetto del richiamo.
- **Le unità non si confrontano fra tabelle**: a unità sostanza due proposte
  della stessa classe collassano in una al 4° livello, e i numeri delle
  sezioni 3 e 5 non sono la stessa misura. La graduatoria sì.
- **Il dosaggio non è modellato**; frazione di eiezione, punteggio
  CHA₂DS₂-VA, laboratorio e dispositivi restano i fatti non estratti che
  limitano le regole.
