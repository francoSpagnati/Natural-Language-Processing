"""
Step 1 - Costruzione dei vocabolari chiusi (farmaci e condizioni).

Il vocabolario chiuso definisce lo *scope* del progetto: quali farmaci e quali
condizioni sono rilevanti. Non definisce le relazioni cliniche fra loro, che
verranno dalle knowledge base esterne allo step 7.

PRINCIPIO SEGUITO: NON SI BUTTA VIA NIENTE
    I file prodotti contengono ogni voce osservata, comprese quelle che nessuna
    fonte esterna conferma. Una voce non confermata non viene scartata ne'
    "aggiustata": viene marcata. Questo perche' il vocabolario serve anche a
    ispezionare cosa il sistema ha mancato, e una voce cancellata in silenzio e'
    invisibile, mentre una voce marcata `non_trovata` e' una domanda aperta che
    si puo' andare a guardare.

DIFFERENZA FRA I DUE VOCABOLARI
    I farmaci sono elencati esplicitamente in due campi semi-strutturati del
    dataset, quindi il loro vocabolario e' *osservato* e poi confermato contro
    AIFA. Le condizioni non sono in nessun campo strutturato (verificato nello
    step 0): il loro vocabolario e' solo *candidato*, ricavato dalla prosa, e
    andra' validato contro una terminologia esterna nello step 2. La differenza
    e' esplicita nei modelli: `VoceCondizione.codice` resta nullo per
    costruzione in questo step.

Esecuzione (richiede `src/explore_dataset.py` e `src/fetch_external_kb.py`):
    python3 src/build_vocabularies.py
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from data_loading import carica_dataset  # noqa: E402
from explore_dataset import (  # noqa: E402
    radice_nome_commerciale,
    sonda_terapia_dimissione,
    sonda_terapia_ingresso,
)
from schema import (  # noqa: E402
    EsitoConfermaEsterna,
    OccorrenzaVoce,
    StatoNormalizzazione,
    Vocabolario,
    VoceCondizione,
    VoceFarmaco,
    json_schema,
)

RADICE = Path(__file__).resolve().parent.parent
PERCORSO_DATASET = RADICE / "data" / "raw" / "anamnesiterapie.txt"
PERCORSO_AIFA_CONFEZIONI = RADICE / "data" / "external" / "aifa" / "confezioni_fornitura.csv"
PERCORSO_AIFA_ATC = RADICE / "data" / "external" / "aifa" / "atc.csv"
CARTELLA_USCITA = RADICE / "data" / "interim"

FONTE_AIFA = "AIFA - anagrafica confezioni (confezioni_fornitura.csv), CC-BY 4.0"

# L'anagrafica AIFA ha campi liberi molto lunghi (URL dei fogli illustrativi).
csv.field_size_limit(10**7)


# ---------------------------------------------------------------------------
# Indici AIFA
# ---------------------------------------------------------------------------


def normalizza(testo: str) -> str:
    """Minuscolo, punteggiatura ridotta a spazi, spazi collassati.

    La punteggiatura va neutralizzata perche' le due fonti separano
    diversamente le associazioni: "Rosuvastatina/ezetimibe" contro
    "rosuvastatina ezetimibe".
    """
    testo = re.sub(r"[^a-z0-9/ ]", " ", testo.strip().lower())
    return re.sub(r"\s+", " ", testo).strip()


def carica_indici_aifa() -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, str]]:
    """Costruisce gli indici AIFA usati per confermare le voci del vocabolario.

    Restituisce:
      - denominazione commerciale -> principi attivi;
      - denominazione commerciale -> codici ATC;
      - descrizione ATC (5o livello) -> codice ATC.
    Il terzo permette di confermare i principi attivi, che nel dataset compaiono
    per nome e non per codice.
    """
    den_a_principi: dict[str, set[str]] = defaultdict(set)
    den_a_atc: dict[str, set[str]] = defaultdict(set)

    with PERCORSO_AIFA_CONFEZIONI.open(encoding="utf-8", errors="replace") as f:
        for riga in csv.DictReader(f, delimiter=";"):
            denominazione = normalizza(riga.get("DENOMINAZIONE") or "")
            if not denominazione:
                continue
            principi = (riga.get("PA_ASSOCIATI") or "").strip().lower()
            atc = (riga.get("CODICE_ATC") or "").strip()
            if principi:
                den_a_principi[denominazione].add(principi)
            if atc:
                den_a_atc[denominazione].add(atc)

    descrizione_a_atc: dict[str, str] = {}
    with PERCORSO_AIFA_ATC.open(encoding="utf-8", errors="replace") as f:
        for riga in csv.DictReader(f, delimiter=";"):
            codice = riga["CODICE_ATC"].strip()
            # Solo il 5o livello (7 caratteri) denota una sostanza; i livelli
            # superiori sono classi e non vanno confusi con un principio attivo.
            if len(codice) == 7:
                descrizione_a_atc[normalizza(riga["DESCRIZIONE"])] = codice

    return den_a_principi, den_a_atc, descrizione_a_atc


def conferma_principio_attivo(
    principio: str, descrizione_a_atc: dict[str, str]
) -> tuple[EsitoConfermaEsterna, list[str]]:
    """Cerca il principio attivo fra le descrizioni ATC di 5o livello.

    Prima si tenta la corrispondenza esatta; se fallisce, si cerca una
    descrizione ATC che *inizi* con il termine. Serve per le forme saline, che
    AIFA scrive per esteso mentre il referto abbrevia: "Enoxaparina" contro
    "ENOXAPARINA SODICA". Il prefisso e' sicuro nella direzione giusta
    (dataset piu' corto di AIFA) e non nell'altra, quindi non genera falsi
    accoppiamenti fra sostanze diverse.
    """
    chiave = normalizza(principio)
    if chiave in descrizione_a_atc:
        return EsitoConfermaEsterna.CONFERMATA, [descrizione_a_atc[chiave]]

    candidati = [
        codice
        for descrizione, codice in descrizione_a_atc.items()
        if descrizione.startswith(chiave + " ")
    ]
    if candidati:
        return EsitoConfermaEsterna.CONFERMATA, sorted(set(candidati))
    return EsitoConfermaEsterna.NON_TROVATA, []


# ---------------------------------------------------------------------------
# Vocabolario dei farmaci
# ---------------------------------------------------------------------------


def costruisci_vocabolario_farmaci(record, indici) -> Vocabolario:
    den_a_principi, den_a_atc, descrizione_a_atc = indici

    # Conteggi separati per campo: sapere che una voce viene solo dall'ingresso
    # o solo dalla dimissione cambia quanto ci si puo' fidare della sua forma.
    occorrenze_principi: Counter = Counter()
    record_principi: dict[str, set[int]] = defaultdict(set)
    occorrenze_commerciali_dim: Counter = Counter()
    record_commerciali_dim: dict[str, set[int]] = defaultdict(set)
    occorrenze_ingresso: Counter = Counter()
    record_ingresso: dict[str, set[int]] = defaultdict(set)
    # Evidenza interna: quale principio attivo il dataset associa a una radice.
    radice_a_principio: dict[str, Counter] = defaultdict(Counter)

    for rec in record:
        nomi, _, _ = sonda_terapia_ingresso(rec.testo_terapia_ingresso or "")
        for nome in nomi:
            occorrenze_ingresso[nome] += 1
            record_ingresso[nome].add(rec.enc_oid)

        if not rec.ha_terapia_dimissione:
            continue
        voci, _, _ = sonda_terapia_dimissione(rec.testo_terapia_dimissione or "")
        for voce in voci:
            occorrenze_principi[voce["principio"]] += 1
            record_principi[voce["principio"]].add(rec.enc_oid)
            if voce["commerciale"]:
                occorrenze_commerciali_dim[voce["commerciale"]] += 1
                record_commerciali_dim[voce["commerciale"]].add(rec.enc_oid)
                radice = radice_nome_commerciale(voce["commerciale"])
                if radice:
                    radice_a_principio[radice][voce["principio"]] += 1

    voci_farmaco: list[VoceFarmaco] = []

    # --- principi attivi (dalla dimissione) --------------------------------
    for principio, n in occorrenze_principi.most_common():
        esito, atc = conferma_principio_attivo(principio, descrizione_a_atc)
        voci_farmaco.append(
            VoceFarmaco(
                forma_grezza=principio,
                tipo="principio_attivo",
                occorrenze_totali=n,
                occorrenze_per_campo=[
                    OccorrenzaVoce(
                        campo="terapia_dimissione",
                        occorrenze=n,
                        record_distinti=len(record_principi[principio]),
                    )
                ],
                principio_attivo_dataset=principio,
                conferma_aifa=esito,
                atc_candidati=atc,
                fonte=FONTE_AIFA if esito is EsitoConfermaEsterna.CONFERMATA else None,
            )
        )

    # --- nomi commerciali (ingresso + dimissione) --------------------------
    # Uniti in una sola voce quando la radice coincide: "Lasix" in ingresso e
    # "Lasix cpr. 25 mg" alla dimissione sono lo stesso medicinale, e tenerli
    # separati gonfierebbe il vocabolario con duplicati.
    commerciali: dict[str, dict] = {}
    for nome, n in occorrenze_ingresso.most_common():
        radice = radice_nome_commerciale(nome)
        voce = commerciali.setdefault(radice, {"varianti": set(), "campi": []})
        voce["varianti"].add(nome)
        voce["campi"].append(
            OccorrenzaVoce(
                campo="terapia_ingresso", occorrenze=n, record_distinti=len(record_ingresso[nome])
            )
        )
    for nome, n in occorrenze_commerciali_dim.most_common():
        radice = radice_nome_commerciale(nome)
        voce = commerciali.setdefault(radice, {"varianti": set(), "campi": []})
        voce["varianti"].add(nome)
        voce["campi"].append(
            OccorrenzaVoce(
                campo="terapia_dimissione",
                occorrenze=n,
                record_distinti=len(record_commerciali_dim[nome]),
            )
        )

    for radice, dati in sorted(
        commerciali.items(), key=lambda kv: -sum(c.occorrenze for c in kv[1]["campi"])
    ):
        principi_aifa = sorted(den_a_principi.get(radice, ()))
        atc_aifa = sorted(den_a_atc.get(radice, ()))
        principio_dataset = (
            radice_a_principio[radice].most_common(1)[0][0]
            if radice_a_principio.get(radice)
            else None
        )

        if not principi_aifa:
            esito = EsitoConfermaEsterna.NON_TROVATA
        elif principio_dataset is None:
            # AIFA conosce il medicinale ma il dataset non ne dichiara mai il
            # principio attivo: non c'e' nulla da confrontare, non e' un
            # disaccordo.
            esito = EsitoConfermaEsterna.NON_VERIFICATA
        else:
            testo_aifa = " | ".join(principi_aifa)
            token = [t for t in re.split(r"[/ ]+", normalizza(principio_dataset)) if len(t) >= 5]
            esito = (
                EsitoConfermaEsterna.CONFERMATA
                if token and all(t[:6] in testo_aifa for t in token)
                else EsitoConfermaEsterna.DISCORDANTE
            )

        voci_farmaco.append(
            VoceFarmaco(
                forma_grezza=radice,
                tipo="nome_commerciale",
                occorrenze_totali=sum(c.occorrenze for c in dati["campi"]),
                occorrenze_per_campo=dati["campi"],
                principio_attivo_dataset=principio_dataset,
                varianti_osservate=sorted(dati["varianti"]),
                conferma_aifa=esito,
                principi_attivi_aifa=principi_aifa,
                atc_candidati=atc_aifa,
                fonte=FONTE_AIFA if principi_aifa else None,
            )
        )

    conteggi = Counter()
    for voce in voci_farmaco:
        conteggi[f"{voce.tipo}_totali"] += 1
        conteggi[f"{voce.tipo}_{voce.conferma_aifa.value}"] += 1
        if voce.atc_candidati:
            conteggi[f"{voce.tipo}_con_atc_candidato"] += 1

    return Vocabolario(
        nome="vocabolario_farmaci",
        dataset_sorgente=PERCORSO_DATASET.name,
        fonti_esterne=[FONTE_AIFA, "AIFA - registro ATC (atc.csv), CC-BY 4.0"],
        conteggi=dict(sorted(conteggi.items())),
        farmaci=voci_farmaco,
    )


# ---------------------------------------------------------------------------
# Vocabolario (candidato) delle condizioni
# ---------------------------------------------------------------------------

# Marcatori di negazione e incertezza osservati nel corpus. Qui servono solo a
# *annotare* le voci candidate, cosi' si vede subito quali compaiono spesso in
# contesto negato; la logica ConText vera e propria e' materiale dello step 3.
INDIZI_NEGAZIONE = [
    "nega", "non ", "assenza di", "esclude", "si esclude", "escluso",
    "negativo per", "no ", "mai ",
]
INDIZI_INCERTEZZA = ["sospetta", "sospetto", "possibile", "probabile", "verosimile", "dubbio"]

# Frasi che non sono condizioni ma frammenti narrativi ricorrenti: iniziano con
# un verbo o descrivono il ricovero invece del paziente. Escluderle a monte
# tiene il vocabolario candidato leggibile.
PATTERN_FRAMMENTO_NARRATIVO = re.compile(
    r"^(si ricovera|ricovero|si esegue|esegue|eseguit|effettuat|in data|"
    r"viene |veniva |prosegue|riferisce|si segnala|come da|nella norma|"
    r"paziente di|anamnesi|terapia|indicazione)",
    re.IGNORECASE,
)

# Intestazione di sezione rimasta attaccata al frammento: nelle anamnesi il
# testo e' scritto come "Fattori di rischio: obesita si", e senza rimuovere il
# prefisso la stessa condizione genererebbe piu' voci distinte a seconda della
# sezione in cui compare.
PATTERN_INTESTAZIONE_INCOLLATA = re.compile(
    r"^(fattori di rischio|comorbidit[aà]|interventi pregressi|anamnesi\s*\w*|"
    r"diagnosi|allergie e intolleranze|apr|apf|terapia domiciliare|"
    r"motivo del ricovero)\s*:\s*",
    re.IGNORECASE,
)


def ripulisci_frammento(frammento: str) -> str:
    """Toglie intestazione di sezione e punteggiatura di coda.

    Senza questa normalizzazione lo stesso concetto si presenta piu' volte:
    "nega episodi sincopali" e "nega episodi sincopali." erano due voci
    separate, e "obesita si" compariva sia nuda sia preceduta da
    "Fattori di rischio:".
    """
    frammento = PATTERN_INTESTAZIONE_INCOLLATA.sub("", frammento.strip())
    return frammento.strip(" .,;:-").strip()


# Una condizione plausibile: abbastanza corta da essere un termine e non una
# frase, senza date ne' misure (che indicano un referto strumentale).
LUNGHEZZA_MASSIMA_CONDIZIONE = 45
PATTERN_MISURA_O_DATA = re.compile(r"\d{2}[./]\d{2}|\d+\s*(mg|ml|mm|cm|%|mmhg|bpm)")


def costruisci_vocabolario_condizioni(record, occorrenze_minime: int = 3) -> Vocabolario:
    """Ricava dalla prosa le condizioni candidate, con contesti e indizi.

    `occorrenze_minime` filtra la coda: sotto le 3 occorrenze il rapporto fra
    condizioni reali e rumore narrativo peggiora molto, e queste voci vanno
    comunque validate a mano contro una terminologia. La soglia e' un parametro
    proprio per poterla abbassare quando la terminologia sara' disponibile.
    """
    occorrenze: Counter = Counter()
    record_per_voce: dict[str, set[int]] = defaultdict(set)
    contesti: dict[str, list[str]] = defaultdict(list)
    negazioni: dict[str, Counter] = defaultdict(Counter)

    for rec in record:
        testo = rec.testo_anamnesi or ""
        # Segmentiamo su punto e virgola: nelle anamnesi le condizioni sono
        # elencate come proposizioni brevi separate cosi'.
        for frammento in re.split(r"[.;]\s+", testo):
            frammento = ripulisci_frammento(frammento)
            if not (3 < len(frammento) <= LUNGHEZZA_MASSIMA_CONDIZIONE):
                continue
            if PATTERN_FRAMMENTO_NARRATIVO.match(frammento):
                continue
            if PATTERN_MISURA_O_DATA.search(frammento):
                continue

            chiave = frammento.lower()
            occorrenze[chiave] += 1
            record_per_voce[chiave].add(rec.enc_oid)
            if len(contesti[chiave]) < 3:
                contesti[chiave].append(frammento)
            for indizio in INDIZI_NEGAZIONE + INDIZI_INCERTEZZA:
                if chiave.startswith(indizio):
                    negazioni[chiave][indizio.strip()] += 1

    voci = [
        VoceCondizione(
            testo_grezzo=testo,
            occorrenze=n,
            record_distinti=len(record_per_voce[testo]),
            esempi_contesto=contesti[testo],
            indizi_negazione=sorted(negazioni[testo]),
            # Nullo per costruzione: nessuna terminologia esterna e' ancora
            # stata scelta, e inventare un codice sarebbe esattamente il tipo di
            # ambiguita' che il progetto vuole evitare.
            codice=None,
            sistema_codifica=None,
            stato_normalizzazione=StatoNormalizzazione.NON_TENTATO,
        )
        for testo, n in occorrenze.most_common()
        if n >= occorrenze_minime
    ]

    conteggi = {
        "candidate_totali": len(voci),
        "candidate_con_indizio_negazione": sum(1 for v in voci if v.indizi_negazione),
        "occorrenze_minime_richieste": occorrenze_minime,
        "candidate_scartate_sotto_soglia": sum(
            1 for n in occorrenze.values() if n < occorrenze_minime
        ),
    }

    return Vocabolario(
        nome="vocabolario_condizioni_candidate",
        dataset_sorgente=PERCORSO_DATASET.name,
        fonti_esterne=[],  # nessuna: e' il punto aperto dello step 2
        conteggi=conteggi,
        condizioni=voci,
    )


def scrivi_json(modello, percorso: Path) -> None:
    """Serializza un modello Pydantic in JSON indentato e leggibile.

    `indent=2` e `ensure_ascii` disattivato non sono estetica: questi file vanno
    ispezionati a mano per capire cosa il sistema ha mancato, e un JSON su una
    riga sola con gli accenti sfuggiti non e' ispezionabile.
    """
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(
        modello.model_dump_json(indent=2, exclude_none=False), encoding="utf-8"
    )
    print(f"  scritto {percorso.relative_to(RADICE)}  ({percorso.stat().st_size / 1e3:.0f} kB)")


def main() -> None:
    if not PERCORSO_AIFA_CONFEZIONI.exists():
        sys.exit("Mancano le fonti AIFA: esegui prima `python3 src/fetch_external_kb.py`.")

    record, _ = carica_dataset(PERCORSO_DATASET)
    print(f"Record caricati: {len(record)}")

    print("Carico gli indici AIFA (~82 MB, qualche secondo)...")
    indici = carica_indici_aifa()
    print(f"  denominazioni commerciali: {len(indici[0])}")
    print(f"  descrizioni ATC di 5o livello: {len(indici[2])}")

    print("\nVocabolario dei farmaci:")
    vocabolario_farmaci = costruisci_vocabolario_farmaci(record, indici)
    for chiave, valore in vocabolario_farmaci.conteggi.items():
        print(f"  {chiave:48} {valore}")
    scrivi_json(vocabolario_farmaci, CARTELLA_USCITA / "vocabolario_farmaci.json")

    print("\nVocabolario candidato delle condizioni:")
    vocabolario_condizioni = costruisci_vocabolario_condizioni(record)
    for chiave, valore in vocabolario_condizioni.conteggi.items():
        print(f"  {chiave:48} {valore}")
    scrivi_json(vocabolario_condizioni, CARTELLA_USCITA / "vocabolario_condizioni.json")

    print("\nJSON Schema dello stato paziente:")
    percorso_schema = CARTELLA_USCITA / "schema_stato_paziente.json"
    import json

    percorso_schema.write_text(
        json.dumps(json_schema(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  scritto {percorso_schema.relative_to(RADICE)}")


if __name__ == "__main__":
    main()
