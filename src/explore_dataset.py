"""Step 0 - Esplorazione del dataset.

Sonde (non parser definitivi) per misurare quanto i campi siano regolari e
produrre i vocabolari grezzi in `data/interim/`. I parser di produzione sono
nello step 3. Risultati e decisioni: docs/00_esplorazione_dati.md.

    python3 src/explore_dataset.py
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from data_loading import (  # noqa: E402
    TIPI_ATTESI,
    carica_dataset,
)

RADICE = Path(__file__).resolve().parent.parent
PERCORSO_DATASET = RADICE / "data" / "raw" / "anamnesiterapie.txt"
CARTELLA_REPORT = RADICE / "reports"
CARTELLA_INTERIM = RADICE / "data" / "interim"


# --- Sonde di parsing (esplorative, non definitive) ---

# --- Pattern e guardie condivisi dalle due sonde ----------------------------

# Gas medicali e dispositivi (ossigenoterapia, NIV): non hanno ATC, si escludono.
# `cicli` ancorato a inizio stringa per non toccare "Doxiciclina".
PATTERN_NON_FARMACOLOGICO = re.compile(
    r"^\s*(ossigeno|cicli|cpap|c-pap|niv|ventilazione|maschera)\b", re.IGNORECASE
)

# Segnaposto del sistema ospedaliero per principio attivo non valorizzato.
PATTERN_PRINCIPIO_SEGNAPOSTO = re.compile(
    r"^\s*(nessun\s+principio\s+attivo|n\.?d\.?|non\s+specificat\w*|-+)\s*$",
    re.IGNORECASE,
)

# Frasi che indicano esplicitamente l'assenza di terapia domiciliare: vanno
# riconosciute, altrimenti finirebbero nel vocabolario come se fossero farmaci.
PATTERN_NESSUNA_TERAPIA = re.compile(
    r"^\s*(nessuna\s+terapia|non\s+assume|nessun\s+farmaco|nulla)\b", re.IGNORECASE
)


# Unita', forme e orari nel candidato = posologia incollata al nome.
PATTERN_POSOLOGIA_NEL_NOME = re.compile(
    r"\b(mg|mcg|gr?|ml|ui|u|cp|cpr|cps|cpz|gtt|fl|bust|puff|ore|die|al|alle)\b",
    re.IGNORECASE,
)


def nome_farmaco_plausibile(candidato: str, massimo_parole: int = 4) -> bool:
    """Guardia sui livelli laschi: il candidato somiglia a un nome di farmaco e non a prosa?

    Inizia con una lettera, niente virgole, al piu' `massimo_parole` parole,
    nessuna unita' / forma / orario incollati, non un segnaposto ("N.D.").
    """
    candidato = candidato.strip()
    if not candidato or not candidato[0].isalpha():
        return False
    if PATTERN_PRINCIPIO_SEGNAPOSTO.match(candidato):
        return False
    if "," in candidato:
        return False
    if PATTERN_POSOLOGIA_NEL_NOME.search(candidato):
        return False
    return len(candidato.split()) <= massimo_parole


# --- Terapia all'ingresso ---
# Formato prevalente: "Nome commerciale: 5 mg cp.riv. /die (ore 8) ; Altro: ... ;"
SEPARATORE_VOCI_INGRESSO = ";"

# Livello 3: il nome e' cio' che precede la prima cifra (manca il ':' o e' di un orario).
PATTERN_ING_NOME_E_DOSE = re.compile(r"^\s*(?P<principio>[^\d:]+?)\s*(?=\d)")

# Prescrizione infusionale: il nome segue la dose ("125 mg di Furosemide ...").
PATTERN_INFUSIONE = re.compile(
    r"^\s*[\d.,/]+\s*(?:mg|g|ml|mcg|UI|U)\s+di\s+(?P<farmaco>[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\-]*?)"
    r"\s*(?:\*|\s+in\s+\d|$)",
    re.IGNORECASE,
)


# Una virgola fra due cifre e' un separatore decimale, non un elenco.
PATTERN_VIRGOLA_DECIMALE = re.compile(r"(?<=\d),(?=\d)")


def _virgola_di_elenco(voce: str) -> bool:
    """True se la voce contiene una virgola che separa voci, non decimali."""
    return "," in PATTERN_VIRGOLA_DECIMALE.sub("", voce)


def sonda_terapia_ingresso(testo: str) -> tuple[list[str], list[str], Counter]:
    """Nomi commerciali dal campo terapia in ingresso: (nomi, scarti, conteggio per livello)."""
    nomi: list[str] = []
    scarti: list[str] = []
    livelli: Counter = Counter()

    if not testo:
        return nomi, scarti, livelli
    if PATTERN_NESSUNA_TERAPIA.match(testo):
        livelli["nessuna_terapia_dichiarata"] += 1
        return nomi, scarti, livelli

    for voce in testo.split(SEPARATORE_VOCI_INGRESSO):
        voce = voce.strip()
        if not voce:
            continue

        if PATTERN_NON_FARMACOLOGICO.match(voce):
            livelli["escluso_non_farmacologico"] += 1
            continue

        infusione = PATTERN_INFUSIONE.match(voce)
        if infusione:
            nomi.append(infusione.group("farmaco").strip())
            livelli["2_infusionale"] += 1
            continue

        nome = voce.split(":", 1)[0].strip() if ":" in voce else ""
        if nome and nome_farmaco_plausibile(nome):
            nomi.append(nome)
            livelli["1_nome_posologia"] += 1
            continue

        # Livello 3: nome = cio' che precede la prima cifra, ripulito della
        # forma in coda e ripresentato alla stessa guardia. Non si applica se
        # c'e' una virgola di elenco (piu' farmaci in un segmento: meglio lo
        # scarto che perderne); la virgola decimale ("2,5 mg") non e' un elenco.
        alternativo = (None if _virgola_di_elenco(voce)
                       else PATTERN_ING_NOME_E_DOSE.match(voce))
        if alternativo:
            candidato = PATTERN_FORMA_IN_CODA.sub(
                "", alternativo.group("principio").strip()).strip()
            if candidato and nome_farmaco_plausibile(candidato):
                nomi.append(candidato)
                livelli["3_nome_e_dose"] += 1
                continue

        scarti.append(voce)
        livelli["non_interpretato"] += 1

    return nomi, scarti, livelli


# --- Terapia alla dimissione ---
# Formato prevalente, fra virgolette:
#   "Principio attivo (Nome commerciale forma dose): da assumere 5 mg (ore 8)"
# Sonda a livelli, dal piu' stringente al piu' lasco, contando le voci per livello.
PATTERN_VOCE_DIMISSIONE = re.compile(r'"(.*?)"', re.DOTALL)

# Livello 1 - formato pieno: principio, commerciale tra parentesi, ':' e posologia.
PATTERN_DIM_COMPLETO = re.compile(
    r"^\s*(?P<principio>[^(:]+?)\s*\((?P<commerciale>[^()]*)\)\s*:\s*(?P<posologia>.+)$",
    re.DOTALL,
)

# Livello 2: con un sinonimo del principio fra parentesi
#   "Idrossiclorochina (idroxiclorochina) (Plaquenil cp.riv. 200 mg): ..."
PATTERN_DIM_CON_SINONIMO = re.compile(
    r"^\s*(?P<principio>[^(:]+?)\s*\((?P<sinonimo>[^()]*)\)\s*"
    r"\((?P<commerciale>[^()]*)\)\s*:?\s*(?P<posologia>.*)$",
    re.DOTALL,
)

# Livello 3 - manca il nome commerciale: "Furosemide: da assumere 125 mg (ore 8)".
PATTERN_DIM_SENZA_COMMERCIALE = re.compile(
    r"^\s*(?P<principio>[^(:]+?)\s*:\s*(?P<posologia>.+)$", re.DOTALL
)

# Livello 4 - c'e' il commerciale ma manca il ':' della posologia, che e'
# scritta in prosa: "Denosumab (Prolia soluz. iniett. 60 mg)".
PATTERN_DIM_SENZA_POSOLOGIA = re.compile(
    r"^\s*(?P<principio>[^(:]+?)\s*\((?P<commerciale>[^()]*)\)\s*(?P<posologia>.*)$",
    re.DOTALL,
)

# Livello 5: come il 1, con una parentesi annidata nel nome commerciale (un
# solo annidamento, quanto il corpus mostra). Si prova dopo gli altri.
PATTERN_DIM_COMMERCIALE_ANNIDATO = re.compile(
    r"^\s*(?P<principio>[^(:]+?)\s*"
    r"\((?P<commerciale>(?:[^()]|\([^()]*\))*)\)\s*:\s*(?P<posologia>.+)$",
    re.DOTALL,
)

# Livello 6: nome e dose senza commerciale ne' ':' ("Rosuvastatina 5 mg (ore 22)").
# Il piu' generico, si prova per ultimo.
PATTERN_DIM_NOME_E_DOSE = re.compile(
    r"^\s*(?P<principio>[^\d(:]+?)\s*(?:da assumere\s*)?(?P<posologia>\d.*)$",
    re.DOTALL,
)

# Forma farmaceutica in coda al nome ("Spironolattone cps"): si toglie e si
# ripresenta il nome alla guardia, che resta invariata.
PATTERN_FORMA_IN_CODA = re.compile(
    r"\s+(?:cp|cpr|cps|cpz|cp\.riv|cpr\.riv|compresse?|capsule?|"
    r"gtt|fl|fiale?|bust|puff|soluz|scir|crema|cerotti?)\.?$",
    re.IGNORECASE,
)

# Alla dimissione ammettiamo nomi piu' lunghi che in ingresso: le associazioni
# precostituite sono un unico principio anche se elencano molte sostanze.
MASSIME_PAROLE_PRINCIPIO = 12


def sonda_terapia_dimissione(testo: str) -> tuple[list[dict], list[str], Counter]:
    """Voci di terapia alla dimissione con sonda a livelli: (voci, scarti, conteggio per livello)."""
    voci: list[dict] = []
    scarti: list[str] = []
    livelli: Counter = Counter()
    if not testo:
        return voci, scarti, livelli

    for grezza in PATTERN_VOCE_DIMISSIONE.findall(testo):
        grezza = grezza.strip()
        if not grezza:
            continue

        if PATTERN_NON_FARMACOLOGICO.match(grezza):
            livelli["escluso_non_farmacologico"] += 1
            continue

        # Il segnaposto e' una voce interpretata, non uno scarto.
        if PATTERN_PRINCIPIO_SEGNAPOSTO.match(grezza.split("(")[0].strip()):
            livelli["escluso_segnaposto"] += 1
            continue

        # Dal piu' specifico al piu' generico.
        for livello, pattern in (
            ("2_con_sinonimo", PATTERN_DIM_CON_SINONIMO),
            ("1_completo", PATTERN_DIM_COMPLETO),
            ("3_senza_commerciale", PATTERN_DIM_SENZA_COMMERCIALE),
            ("4_senza_posologia", PATTERN_DIM_SENZA_POSOLOGIA),
            ("5_commerciale_annidato", PATTERN_DIM_COMMERCIALE_ANNIDATO),
            ("6_nome_e_dose", PATTERN_DIM_NOME_E_DOSE),
        ):
            match = pattern.match(grezza)
            if not match:
                continue
            principio = match.group("principio").strip()
            if livello == "6_nome_e_dose":
                principio = PATTERN_FORMA_IN_CODA.sub("", principio).strip()
            if not nome_farmaco_plausibile(principio, MASSIME_PAROLE_PRINCIPIO):
                continue
            gruppi = match.groupdict()
            voci.append(
                {
                    "principio": principio,
                    "sinonimo": (gruppi.get("sinonimo") or "").strip(),
                    "commerciale": (gruppi.get("commerciale") or "").strip(),
                    "posologia": (gruppi.get("posologia") or "").strip(),
                    "livello": livello,
                }
            )
            livelli[livello] += 1
            break
        else:
            scarti.append(grezza)
            livelli["non_interpretato"] += 1

    return voci, scarti, livelli


# --- Condizioni nel testo libero ---
# L'eco del questionario dell'EHR: "<Condizione> si." / "<Condizione> no.".
PATTERN_ECO_QUESTIONARIO = re.compile(
    r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'\- ]{2,45}?)\s+(si|no)\s*(?=[.,;]|$)", re.IGNORECASE
)


def sonda_eco_questionario(testo: str) -> list[tuple[str, str]]:
    """Trova le coppie (condizione, polarita') scritte come '<termine> si/no'."""
    if not testo:
        return []
    return [
        (termine.strip().lower(), polarita.lower())
        for termine, polarita in PATTERN_ECO_QUESTIONARIO.findall(testo)
    ]


# --- Allergie ---
#   "Allergie e intolleranze: Allergie: Principi attivi (<sostanza>) Note (<classe>)"
PATTERN_SEZIONE_ALLERGIE = re.compile(
    r"Allergie e intolleranze\s*:\s*(?P<contenuto>.*?)"
    r"(?=\s(?:Anamnesi|Fattori|Comorbidit|Interventi|Diagnosi|APR|APF|Terapia)\b|$)",
    re.IGNORECASE | re.DOTALL,
)

# Dichiarazione esplicita di assenza: e' un'informazione positiva (sappiamo che
# il clinico ha verificato), diversa dall'assenza della sezione (non sappiamo).
PATTERN_ALLERGIE_ASSENTI = re.compile(
    r"allergie e intolleranze non (note|compilate)", re.IGNORECASE
)

# Sottocategorie: "Principi attivi (...)", "Alimenti (...)", "Altro (...)".
PATTERN_SOTTOCATEGORIA_ALLERGIA = re.compile(
    r"(?P<categoria>Principi attivi|Alimenti|Mezzo di contrasto|Altro|Note)"
    r"\s*(?:\((?P<valore>[^)]*)\))?",
    re.IGNORECASE,
)


# Il «ponte» ingresso <-> dimissione: stesso nome commerciale, con e senza coda.
PATTERN_CODA_FORMA_FARMACEUTICA = re.compile(
    r"\s+(cp|cpr|cps|cpz|compresse|soluz|grat|scir|gtt|spray|puff|polv|"
    r"cerotto|fl|bust|crema|ung|collirio|sosp|sciroppo)\b.*$",
    re.IGNORECASE,
)


def radice_nome_commerciale(nome: str) -> str:
    """Radice confrontabile di un nome commerciale: "Lasix cpr. 25 mg" -> "lasix"."""
    radice = PATTERN_CODA_FORMA_FARMACEUTICA.sub("", nome).strip()
    # Rimuove un eventuale dosaggio residuo in coda ("Cacit 1000" resta intero,
    # ma "Lasix 25 mg" perde la dose): togliamo solo cifre seguite da unita'.
    radice = re.sub(r"\s+[\d.,/]+\s*(mg|mcg|g|ml|ui|u)\b.*$", "", radice, flags=re.IGNORECASE)
    return radice.lower().strip()


def sonda_allergie(testo: str) -> dict:
    """Stato della sezione allergie: assente, assenza dichiarata, o presenti (con sottocategorie)."""
    esito = {"stato": "sezione_assente", "categorie": {}}
    if not testo:
        return esito

    match = PATTERN_SEZIONE_ALLERGIE.search(testo)
    if not match:
        return esito

    contenuto = match.group("contenuto").strip()
    if PATTERN_ALLERGIE_ASSENTI.search(contenuto):
        esito["stato"] = "assenza_dichiarata"
        return esito

    esito["stato"] = "allergie_presenti"
    for sotto in PATTERN_SOTTOCATEGORIA_ALLERGIA.finditer(contenuto):
        categoria = sotto.group("categoria").lower()
        esito["categorie"].setdefault(categoria, []).append(
            (sotto.group("valore") or "").strip()
        )
    return esito


# --- Anamnesi narrativa: censimento delle intestazioni di sezione ---
PATTERN_INTESTAZIONE = re.compile(
    r"(?:^|\s)([A-ZÀÈÉÌÒÙ][A-Za-zÀ-ÿ' ]{2,40}?)\s*:\s"
)


def sonda_intestazioni(testo: str) -> list[str]:
    """Censisce le possibili intestazioni di sezione nell'anamnesi narrativa."""
    if not testo:
        return []
    return [m.strip() for m in PATTERN_INTESTAZIONE.findall(testo)]


# --- Report ---


class Report:
    """Accumula il report e lo stampa a schermo mentre lo costruisce."""

    def __init__(self) -> None:
        self.righe: list[str] = []

    def __call__(self, riga: str = "") -> None:
        print(riga)
        self.righe.append(riga)

    def titolo(self, testo: str) -> None:
        self("")
        self("=" * 78)
        self(testo)
        self("=" * 78)

    def salva(self, percorso: Path) -> None:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_text("\n".join(self.righe) + "\n", encoding="utf-8")


def scrivi_csv(percorso: Path, intestazione: list[str], righe) -> None:
    """Salva una tabella in CSV UTF-8 (delimitatore virgola, quoting minimo)."""
    percorso.parent.mkdir(parents=True, exist_ok=True)
    with percorso.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(intestazione)
        writer.writerows(righe)


def statistiche_lunghezza(valori: list[int]) -> str:
    """Riassunto min/mediana/media/max, per descrivere la lunghezza dei testi."""
    if not valori:
        return "n/d"
    ordinati = sorted(valori)
    mediana = ordinati[len(ordinati) // 2]
    return (
        f"min={ordinati[0]} mediana={mediana} "
        f"media={sum(ordinati) / len(ordinati):.0f} max={ordinati[-1]}"
    )


def main() -> None:
    rep = Report()

    rep.titolo("STEP 0 - ESPLORAZIONE DATI")
    rep(f"File analizzato: {PERCORSO_DATASET.relative_to(RADICE)}")

    record, anomalie = carica_dataset(PERCORSO_DATASET)
    rep(f"Record caricati: {len(record)}")
    rep(f"Anomalie di caricamento: {len(anomalie)}")

    # --- 1. Struttura ------------------------------------------------------
    rep.titolo("1. STRUTTURA DEL FILE")
    rep("Il file .txt contiene un unico array JSON valido.")
    rep("Schema per record: {encOid: int, referti: [{tipo, data, reportOid, testo}]}")
    rep("")
    conteggio_tipi = Counter(r.tipo for rec in record for r in rec.referti)
    for tipo in TIPI_ATTESI:
        rep(f"  referti di tipo {tipo!r}: {conteggio_tipi[tipo]}")
    numero_referti = Counter(len(rec.referti) for rec in record)
    rep(f"  n. referti per record: {dict(sorted(numero_referti.items()))}")
    rep(f"  encOid distinti: {len({rec.enc_oid for rec in record})}")
    rep("")
    con_dimissione = sum(1 for rec in record if rec.ha_terapia_dimissione)
    rep("Il dataset si divide in due coorti:")
    rep(f"  con terapia alla dimissione: {con_dimissione} "
        "-> utilizzabili come ground truth nella valutazione")
    rep(f"  senza terapia alla dimissione: {len(record) - con_dimissione} "
        "-> solo testo, utili per collaudare l'estrazione")

    for etichetta, estrattore in (
        ("Anamnesi", lambda r: r.testo_anamnesi),
        ("Terapia ingresso", lambda r: r.testo_terapia_ingresso),
        ("Terapia dimissione", lambda r: r.testo_terapia_dimissione),
    ):
        # Solo i record in cui il referto e' presente: includere gli assenti
        # come lunghezza 0 falserebbe minimo e mediana.
        lunghezze = [len(t) for rec in record if (t := estrattore(rec)) is not None]
        rep(f"  lunghezza testo {etichetta}: {statistiche_lunghezza(lunghezze)} "
            f"(su {len(lunghezze)} record)")

    # --- 2. Affidabilita' dei campi ---------------------------------------
    rep.titolo("2. AFFIDABILITA' DEI CAMPI (regex/JSON-estraibili vs prosa libera)")

    # 2a. Terapia in ingresso
    nomi_ingresso: Counter = Counter()
    scarti_ingresso: list[tuple[int, str]] = []
    livelli_ingresso: Counter = Counter()
    record_senza_terapia_ingresso = 0
    for rec in record:
        testo = rec.testo_terapia_ingresso or ""
        nomi, scarti, livelli = sonda_terapia_ingresso(testo)
        livelli_ingresso.update(livelli)
        if not nomi and not scarti:
            record_senza_terapia_ingresso += 1
        nomi_ingresso.update(nomi)
        scarti_ingresso.extend((rec.enc_oid, s) for s in scarti)

    rep("")
    rep("[Terapia medica all'ingresso]  formato: 'Nome: dose forma /die (ore h) ;'")
    rep(f"  record senza terapia in ingresso: {record_senza_terapia_ingresso}")
    rep(f"  voci riconosciute: {sum(nomi_ingresso.values())}")
    rep(f"  nomi distinti: {len(nomi_ingresso)}")
    rep(f"  frammenti NON interpretati: {len(scarti_ingresso)}")
    rep("  copertura per livello di pattern:")
    totale_ingresso = sum(livelli_ingresso.values())
    for livello, n in sorted(livelli_ingresso.items()):
        rep(f"    {livello:28} {n:5d}  ({100 * n / totale_ingresso:5.2f}%)")
    rep("  esempi di frammenti residui non interpretati:")
    for enc_oid, scarto in scarti_ingresso[:5]:
        rep(f"    encOid={enc_oid}: {scarto[:110]!r}")

    # 2b. Terapia alla dimissione
    principi_dimissione: Counter = Counter()
    commerciali_dimissione: Counter = Counter()
    sinonimi_dimissione: Counter = Counter()
    # Coppie (nome commerciale -> principio attivo) osservate nel dataset:
    # sono il materiale grezzo per il dizionario di normalizzazione dello step 2.
    coppie_commerciale_principio: dict[str, Counter] = defaultdict(Counter)
    scarti_dimissione: list[tuple[int, str]] = []
    livelli_dimissione: Counter = Counter()
    # Referto assente (143 record) e referto senza voci sono due cose diverse.
    record_senza_referto_dimissione = 0
    record_dimissione_senza_voci = 0
    for rec in record:
        if not rec.ha_terapia_dimissione:
            record_senza_referto_dimissione += 1
            continue
        testo = rec.testo_terapia_dimissione or ""
        voci, scarti, livelli = sonda_terapia_dimissione(testo)
        livelli_dimissione.update(livelli)
        if not voci and not scarti:
            record_dimissione_senza_voci += 1
        for voce in voci:
            principi_dimissione[voce["principio"]] += 1
            if voce["sinonimo"]:
                sinonimi_dimissione[(voce["principio"], voce["sinonimo"])] += 1
            if voce["commerciale"]:
                commerciali_dimissione[voce["commerciale"]] += 1
                coppie_commerciale_principio[voce["commerciale"]][voce["principio"]] += 1
        scarti_dimissione.extend((rec.enc_oid, s) for s in scarti)

    rep("")
    rep("[Terapia alla Dimissione]  formato: '\"Principio (Commerciale forma dose): "
        "da assumere ...\"'")
    rep(f"  record privi del referto: {record_senza_referto_dimissione}")
    rep(f"  record col referto ma senza alcuna voce estratta: {record_dimissione_senza_voci}")
    rep(f"  voci riconosciute: {sum(principi_dimissione.values())}")
    rep(f"  principi attivi distinti: {len(principi_dimissione)}")
    rep(f"  nomi commerciali distinti: {len(commerciali_dimissione)}")
    rep(f"  frammenti NON interpretati: {len(scarti_dimissione)}")
    rep("  copertura per livello di pattern (dal piu' stringente al piu' lasco):")
    totale_voci = sum(livelli_dimissione.values())
    for livello, n in sorted(livelli_dimissione.items()):
        rep(f"    {livello:28} {n:5d}  ({100 * n / totale_voci:5.2f}%)")
    rep(f"  sinonimi di principio attivo catturati (livello 2): {len(sinonimi_dimissione)}")
    for (principio, sinonimo), n in sinonimi_dimissione.most_common(5):
        rep(f"    {principio} == {sinonimo}  (x{n})")
    rep("  esempi di frammenti residui non interpretati:")
    for enc_oid, scarto in scarti_dimissione[:5]:
        rep(f"    encOid={enc_oid}: {scarto[:110]!r}")

    # 2c. Anamnesi narrativa
    intestazioni: Counter = Counter()
    for rec in record:
        intestazioni.update(sonda_intestazioni(rec.testo_anamnesi or ""))
    rep("")
    rep("[Anamnesi]  prosa libera con intestazioni di sezione NON standardizzate.")
    rep(f"  intestazioni candidate distinte: {len(intestazioni)}")
    rep("  le 20 piu' frequenti:")
    for testa, n in intestazioni.most_common(20):
        rep(f"    {n:5d}  {testa!r}")

    # 2c-bis. Allergie (sottosezione dell'anamnesi narrativa)
    stati_allergie: Counter = Counter()
    categorie_allergie: Counter = Counter()
    allergie_a_principi_attivi: Counter = Counter()
    for rec in record:
        esito = sonda_allergie(rec.testo_anamnesi or "")
        stati_allergie[esito["stato"]] += 1
        for categoria, valori in esito["categorie"].items():
            categorie_allergie[categoria] += 1
            if categoria == "principi attivi":
                for valore in valori:
                    if valore:
                        allergie_a_principi_attivi[valore] += 1

    rep("")
    rep("[Allergie]  sottosezione semi-strutturata dentro l'anamnesi narrativa.")
    for stato, n in stati_allergie.most_common():
        rep(f"  {stato:24} {n:5d}  ({100 * n / len(record):5.2f}%)")
    rep("  sottocategorie osservate: "
        + ", ".join(f"{c}({n})" for c, n in categorie_allergie.most_common()))
    rep(f"  allergie a principi attivi distinte: {len(allergie_a_principi_attivi)}")
    for valore, n in allergie_a_principi_attivi.most_common(10):
        rep(f"    {n:3d}  {valore!r}")

    # 2d. Condizioni: solo prosa libera
    rep("")
    rep("[Condizioni]  nell'export grezzo NON esiste alcun campo strutturato:")
    rep("  le patologie sono esclusivamente nella prosa dell'anamnesi.")

    eco_termini: Counter = Counter()
    eco_polarita: Counter = Counter()
    record_con_eco = 0
    for rec in record:
        coppie = sonda_eco_questionario(rec.testo_anamnesi or "")
        if coppie:
            record_con_eco += 1
        for termine, polarita in coppie:
            eco_termini[termine] += 1
            eco_polarita[polarita] += 1

    rep("  Parte del questionario dell'EHR sopravvive come eco testuale")
    rep("  ('<Condizione> si.'), ma la copertura e' limitata:")
    rep(f"    record con almeno un'eco: {record_con_eco}/{len(record)} "
        f"({100 * record_con_eco / len(record):.1f}%)")
    rep(f"    polarita osservate: {dict(eco_polarita)}")
    rep(f"    condizioni distinte cosi' riconoscibili: {len(eco_termini)}")
    for termine, n in eco_termini.most_common(10):
        rep(f"      {n:5d}  {termine}")
    rep("  => l'appiglio regolare copre pochissime condizioni: il vocabolario")
    rep("     delle patologie NON e' ricavabile dal dataset e dovra' venire da")
    rep("     una terminologia esterna citabile (step 1/2).")

    # --- 3. Vocabolari grezzi ---------------------------------------------
    rep.titolo("3. VOCABOLARI CHIUSI GREZZI (materiale per lo step 1)")

    scrivi_csv(
        CARTELLA_INTERIM / "vocab_grezzo_farmaci_ingresso.csv",
        ["nome_ingresso", "occorrenze"],
        nomi_ingresso.most_common(),
    )
    scrivi_csv(
        CARTELLA_INTERIM / "vocab_grezzo_farmaci_dimissione.csv",
        ["principio_attivo", "occorrenze"],
        principi_dimissione.most_common(),
    )
    scrivi_csv(
        CARTELLA_INTERIM / "vocab_grezzo_nomi_commerciali.csv",
        ["nome_commerciale", "occorrenze", "principi_attivi_associati"],
        [
            (nome, n, " | ".join(f"{p} x{c}" for p, c in coppie_commerciale_principio[nome].most_common()))
            for nome, n in commerciali_dimissione.most_common()
        ],
    )
    scrivi_csv(
        CARTELLA_INTERIM / "eco_questionario_condizioni.csv",
        ["condizione", "occorrenze"],
        eco_termini.most_common(),
    )

    rep("Scritti in data/interim/:")
    rep(f"  vocab_grezzo_farmaci_ingresso.csv   ({len(nomi_ingresso)} nomi commerciali)")
    rep(f"  vocab_grezzo_farmaci_dimissione.csv ({len(principi_dimissione)} principi attivi)")
    rep(f"  vocab_grezzo_nomi_commerciali.csv   ({len(commerciali_dimissione)} nomi commerciali)")
    rep(f"  eco_questionario_condizioni.csv     ({len(eco_termini)} condizioni, copertura parziale)")

    rep("")
    rep("--- 25 principi attivi piu' frequenti alla dimissione ---")
    for principio, n in principi_dimissione.most_common(25):
        rep(f"  {n:5d}  {principio}")

    # --- 3-bis. Ponte ingresso <-> dimissione: (principio, commerciale) dal dataset stesso ---
    rep.titolo("3-bis. PONTE INGRESSO <-> DIMISSIONE (base del dizionario di normalizzazione)")

    radice_a_principio: dict[str, Counter] = defaultdict(Counter)
    for commerciale, principi in coppie_commerciale_principio.items():
        radice = radice_nome_commerciale(commerciale)
        if radice:
            radice_a_principio[radice].update(principi)

    risolti = {n for n in nomi_ingresso if radice_nome_commerciale(n) in radice_a_principio}
    non_risolti = sorted(set(nomi_ingresso) - risolti)
    rep(f"  radici di nome commerciale ricavate dalla dimissione: {len(radice_a_principio)}")
    rep(f"  nomi distinti in ingresso: {len(nomi_ingresso)}")
    rep(f"    risolvibili a un principio attivo via dataset: {len(risolti)} "
        f"({100 * len(risolti) / len(nomi_ingresso):.1f}%)")
    rep(f"    NON risolvibili (serviranno fonti esterne o mapping manuale): {len(non_risolti)}")
    ambigue = {r: p for r, p in radice_a_principio.items() if len(p) > 1}
    rep(f"  radici ambigue (piu' di un principio attivo associato): {len(ambigue)}")
    for radice, principi in list(ambigue.items())[:5]:
        rep(f"    {radice!r}: {dict(principi)}")
    rep("  esempi di nomi in ingresso non risolvibili dal solo dataset:")
    for nome in non_risolti[:15]:
        rep(f"    {nome!r}")

    scrivi_csv(
        CARTELLA_INTERIM / "ponte_commerciale_principio.csv",
        ["radice_commerciale", "principio_attivo_prevalente", "occorrenze", "alternative"],
        [
            (
                radice,
                principi.most_common(1)[0][0],
                sum(principi.values()),
                " | ".join(f"{p} x{c}" for p, c in principi.most_common()[1:]),
            )
            for radice, principi in sorted(
                radice_a_principio.items(), key=lambda kv: -sum(kv[1].values())
            )
        ],
    )
    rep("  Scritto data/interim/ponte_commerciale_principio.csv")

    # --- 4. Anomalie -------------------------------------------------------
    rep.titolo("4. ANOMALIE")
    if anomalie:
        for tipo, n in Counter(a.tipo_problema for a in anomalie).most_common():
            rep(f"  {n:5d}  {tipo}")
    else:
        rep("  Nessuna anomalia strutturale di caricamento.")
    rep("")
    rep("Anomalie a livello di contenuto (rilevate dalle sonde):")
    rep(f"  frammenti non interpretati, terapia ingresso:   {len(scarti_ingresso)}")
    rep(f"  frammenti non interpretati, terapia dimissione: {len(scarti_dimissione)}")
    rep(f"  record senza terapia in ingresso:               {record_senza_terapia_ingresso}")
    rep(f"  record privi del referto di dimissione:          {record_senza_referto_dimissione}")
    rep(f"  record col referto ma senza voci estratte:       {record_dimissione_senza_voci}")

    rep.salva(CARTELLA_REPORT / "00_esplorazione.txt")
    rep("")
    rep(f"Report salvato in reports/00_esplorazione.txt")


if __name__ == "__main__":
    main()
