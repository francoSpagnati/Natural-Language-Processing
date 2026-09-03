"""
Step 2 - Risoluzione dei farmaci del vocabolario al codice ATC.

Il brief richiede che la risoluzione ATC sia **obbligatoria**, perche' il codice
serve sia a interrogare le knowledge base esterne (step 7) sia a calcolare la
metrica gerarchica sui 5 livelli (step 11). Questo modulo la esegue, e per ogni
voce registra **con quale metodo** e **su quale evidenza** l'ha ottenuta.

PERCHE' UNA CASCATA DI STRATEGIE E NON UN SOLO CONFRONTO
    Lo step 1 aveva risolto il 70% dei principi attivi con la corrispondenza
    esatta, e l'ispezione delle voci mancanti ha mostrato che il residuo non era
    rumore ma tre cause sistematiche, ciascuna con una regola propria:

    1. le associazioni precostituite, che il dataset scrive con la barra
       ("Rosuvastatina/ezetimibe") e AIFA con la congiunzione
       ("ROSUVASTATINA E EZETIMIBE");
    2. le forme saline, che il referto abbrevia ("Enoxaparina") e AIFA scrive
       per esteso ("ENOXAPARINA SODICA");
    3. le sigle dei produttori nei generici ("pantoprazolo sand"), che AIFA
       riporta per esteso ("PANTOPRAZOLO SANDOZ").

    Le strategie sono quindi provate in ordine di affidabilita' decrescente, e
    la prima che riesce vince. Ogni voce porta il metodo che l'ha risolta, cosi'
    chi legge puo' dare peso diverso a una corrispondenza esatta e a un
    accostamento per prefisso, e chi valuta puo' escludere i metodi deboli per
    misurarne l'effetto.

PERCHE' NESSUNA LISTA DI SIGLE SCRITTA A MANO
    La terza causa si risolverebbe con un elenco di abbreviazioni dei
    produttori ("sand" -> Sandoz, "eg" -> EG S.p.A.). Compilarlo a mano sarebbe
    pero' proprio il tipo di dato inventato che il progetto vuole evitare.
    Usiamo invece una regola che ricava il collegamento dai dati AIFA stessi: i
    token del nome nel dataset devono essere **prefissi** dei token della
    denominazione AIFA. "pantoprazolo sand" corrisponde a "pantoprazolo
    sandoz" perche' "sand" e' prefisso di "sandoz"; nessuna sigla e' scritta da
    noi, e la stessa regola risolve anche i principi attivi troncati
    ("acido acetils eg" -> "acido acetilsalicilico eg").

Esecuzione (richiede `build_vocabularies.py` e `fetch_external_kb.py`):
    python3 src/normalize_drugs.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from schema import (  # noqa: E402
    MappaturaATC,
    MetodoRisoluzione,
    StatoNormalizzazione,
    VoceMappaturaATC,
)

RADICE = Path(__file__).resolve().parent.parent
PERCORSO_VOCABOLARIO = RADICE / "data" / "interim" / "vocabolario_farmaci.json"
PERCORSO_AIFA_CONFEZIONI = RADICE / "data" / "external" / "aifa" / "confezioni_fornitura.csv"
PERCORSO_AIFA_ATC = RADICE / "data" / "external" / "aifa" / "atc.csv"
PERCORSO_USCITA = RADICE / "data" / "interim" / "mappatura_atc.json"

FONTE_ATC = "AIFA - registro ATC (atc.csv), CC-BY 4.0"
FONTE_CONFEZIONI = "AIFA - anagrafica confezioni (confezioni_fornitura.csv), CC-BY 4.0"

csv.field_size_limit(10**7)

# Un ATC di 5o livello ha 7 caratteri (es. C07AB07) e denota una sostanza; i
# livelli superiori sono classi e non vanno usati come risoluzione di un farmaco.
LUNGHEZZA_ATC_SOSTANZA = 7


def normalizza(testo: str) -> str:
    """Minuscolo, punteggiatura in spazi, spazi collassati."""
    testo = re.sub(r"[^a-z0-9/ ]", " ", testo.strip().lower())
    return re.sub(r"\s+", " ", testo).strip()


class IndiciAIFA:
    """Gli indici AIFA usati dalle strategie di risoluzione.

    Raccolti in una classe perche' costruirli costa qualche secondo (82 MB di
    anagrafica) e vanno costruiti una volta sola.
    """

    def __init__(self) -> None:
        # descrizione della sostanza -> codice ATC di 5o livello
        self.descrizione_a_atc: dict[str, str] = {}
        # denominazione commerciale -> codici ATC
        self.denominazione_a_atc: dict[str, set[str]] = defaultdict(set)
        # primo token della denominazione -> denominazioni che iniziano cosi',
        # per non dover scandire 10 000 denominazioni a ogni ricerca
        self.per_primo_token: dict[str, list[str]] = defaultdict(list)
        self.atc_a_descrizione: dict[str, str] = {}

    def carica(self) -> None:
        with PERCORSO_AIFA_ATC.open(encoding="utf-8", errors="replace") as f:
            for riga in csv.DictReader(f, delimiter=";"):
                codice = riga["CODICE_ATC"].strip()
                descrizione = riga["DESCRIZIONE"].strip()
                self.atc_a_descrizione[codice] = descrizione
                if len(codice) == LUNGHEZZA_ATC_SOSTANZA:
                    self.descrizione_a_atc[normalizza(descrizione)] = codice

        with PERCORSO_AIFA_CONFEZIONI.open(encoding="utf-8", errors="replace") as f:
            for riga in csv.DictReader(f, delimiter=";"):
                denominazione = normalizza(riga.get("DENOMINAZIONE") or "")
                atc = (riga.get("CODICE_ATC") or "").strip()
                if denominazione and len(atc) == LUNGHEZZA_ATC_SOSTANZA:
                    self.denominazione_a_atc[denominazione].add(atc)

        for denominazione in self.denominazione_a_atc:
            primo = denominazione.split()[0]
            self.per_primo_token[primo].append(denominazione)


# --- Le strategie ----------------------------------------------------------
# Ognuna riceve il nome normalizzato e restituisce (codici, evidenza, fonte)
# oppure None. Sono funzioni separate e non rami di un `if` gigante perche'
# ciascuna e' testabile da sola e il loro ordine e' una decisione esplicita.


def strategia_principio_esatto(nome: str, indici: IndiciAIFA):
    """Il nome coincide con la descrizione ufficiale di una sostanza ATC."""
    codice = indici.descrizione_a_atc.get(nome)
    if codice:
        return [codice], indici.atc_a_descrizione[codice], FONTE_ATC
    return None


def strategia_associazione(nome: str, indici: IndiciAIFA):
    """Le associazioni: il dataset usa la barra, AIFA la congiunzione.

    "Rosuvastatina/ezetimibe" -> "rosuvastatina e ezetimibe" (C10BA06).
    Proviamo anche la virgola, che AIFA usa per le associazioni a tre
    ("ROSUVASTATINA, AMLODIPINA E LISINOPRIL").
    """
    if "/" not in nome:
        return None

    parti = [p.strip() for p in nome.split("/") if p.strip()]
    if len(parti) < 2:
        return None

    varianti = [" e ".join(parti)]
    if len(parti) > 2:
        varianti.append(", ".join(parti[:-1]) + " e " + parti[-1])

    for variante in varianti:
        codice = indici.descrizione_a_atc.get(normalizza(variante))
        if codice:
            return [codice], indici.atc_a_descrizione[codice], FONTE_ATC
    return None


def strategia_forma_salina(nome: str, indici: IndiciAIFA):
    """Il referto abbrevia la sostanza, AIFA la scrive con la forma salina.

    "Enoxaparina" -> "ENOXAPARINA SODICA" (B01AB05). Il confronto e' per
    prefisso e solo in questa direzione: il nome del dataset deve essere
    l'inizio della descrizione AIFA. Al contrario si accosterebbero sostanze
    diverse ("Acido folico" non deve risolvere su "Acido").

    Se il prefisso porta a piu' sostanze diverse la voce resta ambigua: e' il
    caso di "Insulina", che prefissa decine di insuline distinte.
    """
    candidati = {
        codice
        for descrizione, codice in indici.descrizione_a_atc.items()
        if descrizione.startswith(nome + " ")
    }
    if not candidati:
        return None
    evidenza = ", ".join(sorted(indici.atc_a_descrizione[c] for c in candidati)[:3])
    return sorted(candidati), evidenza, FONTE_ATC


def strategia_commerciale_esatto(nome: str, indici: IndiciAIFA):
    """Il nome coincide con una denominazione commerciale autorizzata."""
    codici = indici.denominazione_a_atc.get(nome)
    if codici:
        return sorted(codici), nome, FONTE_CONFEZIONI
    return None


def strategia_commerciale_abbreviato(nome: str, indici: IndiciAIFA):
    """I token del dataset sono prefissi dei token della denominazione AIFA.

    Risolve i generici con la sigla del produttore ("pantoprazolo sand" ->
    "pantoprazolo sandoz") e i principi attivi troncati ("acido acetils eg" ->
    "acido acetilsalicilico eg"), senza che nessuna sigla sia scritta da noi.

    Il vincolo che la denominazione AIFA abbia **almeno** tanti token quanti il
    nome del dataset evita che un nome lungo corrisponda a uno corto per caso.
    """
    token = nome.split()
    if not token:
        return None

    corrispondenze = [
        denominazione
        for denominazione in indici.per_primo_token.get(token[0], ())
        if len(denominazione.split()) >= len(token)
        and all(
            token_aifa.startswith(token_dataset)
            for token_dataset, token_aifa in zip(token, denominazione.split())
        )
    ]
    if not corrispondenze:
        return None

    codici: set[str] = set()
    for denominazione in corrispondenze:
        codici |= indici.denominazione_a_atc[denominazione]
    if not codici:
        return None
    return sorted(codici), ", ".join(sorted(corrispondenze)[:3]), FONTE_CONFEZIONI


def strategia_suffisso_salino(nome: str, indici: IndiciAIFA):
    """Il dataset aggiunge la forma salina che AIFA non riporta.

    E' la direzione opposta a `strategia_forma_salina`: qui il nome del dataset
    e' piu' lungo. "Warfarin sodico" non compare in AIFA, che registra la
    sostanza come "WARFARIN" (B01AA03); lo stesso vale per "Candesartan
    cilexetil" -> "CANDESARTAN".

    Togliamo l'ultimo token e pretendiamo una corrispondenza **esatta**: e' il
    vincolo che rende la regola sicura senza bisogno di un elenco di sali
    scritto a mano. Un troncamento che non corrisponde esattamente a una
    sostanza esistente non produce nulla, quindi "Ferroso solfato" (che in AIFA
    non c'e' in nessuna forma) resta correttamente non risolto invece di essere
    accostato a "Ferroso gluconato".
    """
    token = nome.split()
    if len(token) < 2:
        return None
    codice = indici.descrizione_a_atc.get(" ".join(token[:-1]))
    if codice:
        return [codice], indici.atc_a_descrizione[codice], FONTE_ATC
    return None


# L'ordine e' la decisione centrale del modulo: dalla corrispondenza piu'
# stringente alla piu' permissiva. Le strategie sui principi attivi precedono
# quelle sui nomi commerciali perche' l'ATC e' definito sulla sostanza.
STRATEGIE = [
    (MetodoRisoluzione.PRINCIPIO_ESATTO, strategia_principio_esatto),
    (MetodoRisoluzione.ASSOCIAZIONE, strategia_associazione),
    (MetodoRisoluzione.COMMERCIALE_ESATTO, strategia_commerciale_esatto),
    (MetodoRisoluzione.COMMERCIALE_ABBREVIATO, strategia_commerciale_abbreviato),
    # Le due strategie sui sali vanno in fondo. Non perche' siano deboli, ma
    # perche' altrimenti rubano i match ai nomi commerciali: "pantoprazolo
    # sand" troncato diventa "pantoprazolo", che e' una sostanza esistente.
    # Il codice ATC sarebbe lo stesso, ma la voce risulterebbe risolta "per
    # forma salina" quando in realta' e' un generico riconosciuto per nome
    # commerciale — e la provenienza registrata sarebbe falsa.
    (MetodoRisoluzione.SUFFISSO_SALINO, strategia_suffisso_salino),
    (MetodoRisoluzione.FORMA_SALINA, strategia_forma_salina),
]


def risolvi(nome_grezzo: str, tipo: str, occorrenze: int, indici: IndiciAIFA) -> VoceMappaturaATC:
    """Applica la cascata di strategie a una voce del vocabolario."""
    nome = normalizza(nome_grezzo)
    voce = VoceMappaturaATC(forma_grezza=nome_grezzo, tipo=tipo, occorrenze=occorrenze)

    for metodo, strategia in STRATEGIE:
        esito = strategia(nome, indici)
        if not esito:
            continue
        codici, evidenza, fonte = esito
        voce.metodo = metodo
        voce.atc_candidati = codici
        voce.evidenza = evidenza
        voce.fonte = fonte
        if len(codici) == 1:
            voce.codice_atc = codici[0]
            voce.descrizione_atc = indici.atc_a_descrizione.get(codici[0])
            voce.stato = StatoNormalizzazione.RISOLTO
        else:
            # Piu' sostanze compatibili: non scegliamo noi. Forzare un codice
            # qui produrrebbe un errore silenzioso a valle, dove nessuno
            # saprebbe piu' che la scelta era arbitraria.
            voce.stato = StatoNormalizzazione.AMBIGUO
        return voce

    # Nessuna strategia ha funzionato: la voce e' fuori dalla KB, e va detto.
    voce.stato = StatoNormalizzazione.NIL
    return voce


def main() -> None:
    if not PERCORSO_VOCABOLARIO.exists():
        sys.exit("Manca il vocabolario: esegui prima `python3 src/build_vocabularies.py`.")
    if not PERCORSO_AIFA_CONFEZIONI.exists():
        sys.exit("Mancano le fonti AIFA: esegui prima `python3 src/fetch_external_kb.py`.")

    print("Carico gli indici AIFA...")
    indici = IndiciAIFA()
    indici.carica()
    print(f"  sostanze ATC di 5o livello: {len(indici.descrizione_a_atc)}")
    print(f"  denominazioni commerciali:  {len(indici.denominazione_a_atc)}")

    vocabolario = json.loads(PERCORSO_VOCABOLARIO.read_text(encoding="utf-8"))
    voci = [
        risolvi(v["forma_grezza"], v["tipo"], v["occorrenze_totali"], indici)
        for v in vocabolario["farmaci"]
    ]

    conteggi: Counter = Counter()
    for voce in voci:
        conteggi[f"{voce.tipo}__{voce.stato.value}"] += 1
        conteggi[f"metodo__{voce.metodo.value}"] += 1
    # Copertura pesata sulle occorrenze: dice quanta parte del *testo reale*
    # riusciamo a normalizzare, che conta piu' del numero di voci distinte,
    # dominato dalla coda rara.
    occorrenze_totali = sum(v.occorrenze for v in voci)
    occorrenze_risolte = sum(
        v.occorrenze for v in voci if v.stato is StatoNormalizzazione.RISOLTO
    )
    conteggi["occorrenze_totali"] = occorrenze_totali
    conteggi["occorrenze_risolte"] = occorrenze_risolte

    mappatura = MappaturaATC(
        fonti_esterne=[FONTE_ATC, FONTE_CONFEZIONI],
        conteggi=dict(sorted(conteggi.items())),
        voci=sorted(voci, key=lambda v: -v.occorrenze),
    )
    PERCORSO_USCITA.parent.mkdir(parents=True, exist_ok=True)
    PERCORSO_USCITA.write_text(
        mappatura.model_dump_json(indent=2), encoding="utf-8"
    )

    print("\nEsito della risoluzione:")
    for chiave, valore in mappatura.conteggi.items():
        print(f"  {chiave:46} {valore}")
    print(
        f"\n  copertura pesata sulle occorrenze: "
        f"{100 * occorrenze_risolte / occorrenze_totali:.1f}%"
    )
    print(f"\nScritto {PERCORSO_USCITA.relative_to(RADICE)}")


if __name__ == "__main__":
    main()
