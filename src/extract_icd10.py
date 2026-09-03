"""
Step 2 - Estrazione della terminologia ICD-10 italiana dal PDF ufficiale.

FONTE
    "ICD-10 2019 in italiano - Volume 1, Elenco sistematico", pubblicato dal
    Centro Collaboratore Italiano dell'OMS per la Famiglia delle Classificazioni
    Internazionali (Regione Autonoma Friuli Venezia Giulia - Azienda Sanitaria
    Universitaria Giuliano Isontina), distribuito da reteclassificazioni.it.
    E' la traduzione italiana ufficiale dell'ICD-10 dell'OMS.

PERCHE' PARTIRE DA UN PDF
    Non e' la strada che si sceglierebbe potendo. E' pero' l'unica fonte
    verificata che soddisfi i due vincoli del progetto: essere una terminologia
    autorevole e citabile, e essere **in italiano** come i referti. Le
    alternative sono state misurate e scartate (vedi docs/02): Wikidata copre 8
    su 20 dei termini cardiologici che ci servono, SNOMED CT non e' licenziabile
    in Italia, e l'API del portale delle classificazioni richiede credenziali.
    Il PDF ha testo estraibile (e' generato da Word, non scansionato), quindi
    l'estrazione e' deterministica e ripetibile, non un OCR probabilistico.

I TERMINI "Incl." SONO IL VERO VALORE
    Oltre al titolo ufficiale di ogni codice, l'ICD elenca i termini inclusi:
    sono i sinonimi con cui la stessa condizione compare nella pratica clinica,
    ed e' esattamente cio' che serve al gazetteer della pipeline A e alla
    generazione dei candidati per l'entity linking della pipeline C.

    I termini "Escl." NON vengono raccolti come sinonimi: per definizione
    rimandano ad *altri* codici, quindi usarli qui produrrebbe collegamenti
    sbagliati. Vengono conservati a parte come rimandi.

Esecuzione:
    python3 src/extract_icd10.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
PERCORSO_PDF = RADICE / "data" / "external" / "ICD-10 2019 vol1 Elenco Sistematico DEF-1.pdf"
PERCORSO_TESTO = RADICE / "data" / "interim" / "icd10_testo_estratto.txt"
PERCORSO_USCITA = RADICE / "data" / "interim" / "terminologia_icd10.json"

CITAZIONE = {
    "titolo": "ICD-10 2019 in italiano - Volume 1, Elenco sistematico",
    "editore": "Centro Collaboratore Italiano dell'OMS per la Famiglia delle "
               "Classificazioni Internazionali - Regione Autonoma Friuli Venezia Giulia",
    "anno": 2019,
    "distribuito_da": "https://www.reteclassificazioni.it/",
    "nota": "Traduzione italiana ufficiale della classificazione ICD-10 dell'OMS.",
}

# --- Riconoscimento delle righe -------------------------------------------

# Categoria a 3 caratteri: rientrata di 1-3 spazi. "  I10          Ipertensione..."
PATTERN_CATEGORIA = re.compile(r"^ {1,3}([A-Z]\d{2})(?:†)?\s{2,}(\S.*)$")

# Sottocategoria a 4 caratteri, a inizio riga. "I11.0         Cardiopatia..."
PATTERN_SOTTOCATEGORIA = re.compile(r"^([A-Z]\d{2}\.\d)(?:†)?\s{2,}(\S.*)$")

# Inizio di un blocco di termini inclusi o esclusi.
PATTERN_INCLUSI = re.compile(r"^\s*Incl\.\s*:\s*(.*)$")
PATTERN_ESCLUSI = re.compile(r"^\s*Escl\.\s*:\s*(.*)$")

# Marcatori di elenco puntato usati nel PDF (font Symbol, area a uso privato).
MARCATORI_ELENCO = "⚬•"
PATTERN_ELENCO = re.compile(rf"^\s*[{MARCATORI_ELENCO}]\s*(.*)$")

# Nel volume cartaceo i sotto-elenchi sono spesso raccolti da una *graffa* che
# porta un suffisso comune a destra, cosi':
#     ipertrofia:
#      * adenofibromatosa            della prostata
#      * (benigna)
#      * del lobo medio
# dove "della prostata" vale per tutte e tre le voci. `pdftotext` appiattisce la
# graffa accodando il suffisso alla prima riga del gruppo, separato da molti
# spazi. Senza riconoscerlo, due termini su tre perderebbero la parte che li
# rende identificabili ("ipertrofia benigna" invece di "ipertrofia benigna
# della prostata"). Tre o piu' spazi interni segnalano questa situazione.
PATTERN_SUFFISSO_GRAFFA = re.compile(r"^(.*?\S)\s{3,}(\S.*)$")

# Rimandi ad altri codici in coda a un termine: "(I27.2)", "(O10-O11, O13-O16)".
# Vanno rimossi dal termine, altrimenti il sinonimo conterrebbe un codice.
PATTERN_RIMANDO = re.compile(r"\s*\([A-Z]\d{2}[^)]*\)\s*$")

# Righe di servizio: piede di pagina, intestazione corrente, numero di pagina.
PATTERN_SERVIZIO = re.compile(
    r"^\s*(\d+\s+)?Centro Collaboratore|^\s*Capitolo [IVXL]+\s*-|^\s*ICD-10 2019\s*$|^\s*$"
)

# Un parentetico e' un *modificatore opzionale* secondo la convenzione ICD solo
# se e' fatto di parole; se contiene un codice e' un rimando e non va espanso.
PATTERN_PARENTETICO = re.compile(r"\(([^()]+)\)")
PATTERN_SEMBRA_CODICE = re.compile(r"[A-Z]\d{2}")


@dataclass
class VoceICD:
    """Un codice ICD-10 con il suo titolo e i suoi sinonimi."""

    codice: str
    titolo: str
    livello: str  # "categoria" (3 caratteri) o "sottocategoria" (4)
    capitolo: str | None = None
    inclusi: list[str] = field(default_factory=list)
    esclusi: list[str] = field(default_factory=list)


def estrai_testo(pdf: Path, destinazione: Path) -> str:
    """Converte il PDF in testo con `pdftotext -layout`.

    L'opzione `-layout` conserva la spaziatura delle colonne: e' cio' che
    permette di distinguere una categoria a 3 caratteri (rientrata) da una
    sottocategoria a 4 (a margine), che altrimenti sarebbero indistinguibili.
    Il testo estratto viene salvato per non dover riconvertire 890 pagine a
    ogni esecuzione e per poter ispezionare a mano cosa il parser ha letto.
    """
    if destinazione.exists():
        return destinazione.read_text(encoding="utf-8")

    destinazione.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pdftotext", "-layout", str(pdf), str(destinazione)],
        check=True,
        capture_output=True,
    )
    return destinazione.read_text(encoding="utf-8")


def espandi_parentetici(termine: str) -> list[str]:
    """Espande la convenzione ICD dei modificatori fra parentesi.

    Nell'ICD le parole fra parentesi sono *opzionali*: il termine
        "diabete (mellito) (non obeso) a esordio nell'eta' adulta"
    vale come "diabete a esordio nell'eta' adulta", come "diabete mellito a
    esordio nell'eta' adulta", e cosi' via.

    I modificatori vanno reinseriti **nella posizione in cui stanno**, non
    accodati in fondo. Accodarli funzionava per i casi in cui la parentesi e'
    gia' finale ("ipertensione (arteriosa)") ma produceva forme prive di senso
    quando e' in mezzo, e soprattutto **non generava** la forma piu' comune di
    tutte: da "diabete (mellito) ..." non usciva mai "diabete mellito".

    Generiamo tre gruppi di forme: nessun modificatore, ciascun modificatore
    preso singolarmente, e tutti insieme. Non l'insieme delle combinazioni:
    con sette parentetici sarebbero 128 forme, quasi tutte mai scritte da
    nessuno, e gonfierebbero il gazetteer di rumore.

    I parentetici che contengono un codice sono rimandi, non modificatori, e
    vengono rimossi in ogni forma.
    """
    # Segmenta il termine alternando testo fisso e parentetici, cosi' la
    # ricostruzione puo' decidere per ciascuno se tenerlo o toglierlo.
    segmenti: list[tuple[str, str]] = []   # ("fisso"|"opzionale", testo)
    posizione = 0
    for trovato in PATTERN_PARENTETICO.finditer(termine):
        if trovato.start() > posizione:
            segmenti.append(("fisso", termine[posizione:trovato.start()]))
        contenuto = trovato.group(1)
        # Un parentetico con un codice e' un rimando: si scarta sempre.
        tipo = "scarto" if PATTERN_SEMBRA_CODICE.search(contenuto) else "opzionale"
        segmenti.append((tipo, contenuto))
        posizione = trovato.end()
    if posizione < len(termine):
        segmenti.append(("fisso", termine[posizione:]))

    indici_opzionali = [i for i, (tipo, _) in enumerate(segmenti) if tipo == "opzionale"]

    def ricostruisci(da_tenere: set[int]) -> str:
        parti = [
            testo
            for i, (tipo, testo) in enumerate(segmenti)
            if tipo == "fisso" or (tipo == "opzionale" and i in da_tenere)
        ]
        unito = re.sub(r"\s+", " ", " ".join(parti))
        return unito.strip(" ,;:")

    selezioni: list[set[int]] = [set()]
    selezioni.extend({i} for i in indici_opzionali)
    if len(indici_opzionali) > 1:
        selezioni.append(set(indici_opzionali))

    forme = []
    for selezione in selezioni:
        forma = ricostruisci(selezione)
        if forma and forma not in forme:
            forme.append(forma)
    return forme


def pulisci_termine(testo: str) -> str:
    """Toglie rimandi a codici, dagger/asterisco e punteggiatura di contorno."""
    testo = PATTERN_RIMANDO.sub("", testo)
    testo = testo.replace("†", "").replace("*", "")
    return re.sub(r"\s+", " ", testo).strip(" ,;:.")


def analizza(testo: str) -> list[VoceICD]:
    """Percorre il testo estratto e ricostruisce le voci della classificazione.

    Il parser e' a stati: tiene traccia della voce corrente e del blocco
    (inclusi/esclusi) in cui si trova, perche' un termine puo' occupare piu'
    righe e i sotto-elenchi puntati vanno ricomposti con il loro prefisso
    ("malattia:" + "cardiorenale" -> "malattia cardiorenale").
    """
    voci: dict[str, VoceICD] = {}
    corrente: VoceICD | None = None
    blocco: str | None = None      # "inclusi" | "esclusi" | None
    prefisso_elenco = ""           # termine che introduce un sotto-elenco
    gruppo_corrente: list[tuple] = []   # bullet in attesa del suffisso di graffa
    suffisso_graffa = ""
    # Le note istruttive dell'ICD ("Utilizzare un codice aggiuntivo...") vanno
    # a capo. Filtrare solo la prima riga lascerebbe passare la coda come se
    # fosse un termine: da "...manifestazione in atto del diabete / mellito."
    # sopravviveva "mellito", che nel gazetteer diventava un falso positivo
    # verso il diabete in gravidanza.
    dentro_nota = False
    capitolo: str | None = None

    for riga in testo.split("\n"):
        riga = riga.replace("\x0c", "")

        intestazione_capitolo = re.match(r"^\s*Capitolo ([IVXL]+)\s*-\s*(.+?)\s*$", riga)
        if intestazione_capitolo:
            capitolo = f"{intestazione_capitolo.group(1)} - {intestazione_capitolo.group(2)}"
            continue

        if PATTERN_SERVIZIO.match(riga):
            continue

        # Nuova sottocategoria o categoria: chiude qualunque blocco aperto.
        for pattern, livello in (
            (PATTERN_SOTTOCATEGORIA, "sottocategoria"),
            (PATTERN_CATEGORIA, "categoria"),
        ):
            match = pattern.match(riga)
            if match:
                _chiudi_gruppo(gruppo_corrente, suffisso_graffa)
                gruppo_corrente = []
                suffisso_graffa = ""
                dentro_nota = False
                codice, titolo = match.group(1), pulisci_termine(match.group(2))
                # Il PDF ripete le categorie nell'indice iniziale e poi
                # nell'elenco sistematico: teniamo la prima occorrenza con un
                # titolo e arricchiamo quella, invece di creare doppioni.
                if codice not in voci:
                    voci[codice] = VoceICD(
                        codice=codice, titolo=titolo, livello=livello, capitolo=capitolo
                    )
                corrente = voci[codice]
                blocco = None
                prefisso_elenco = ""
                break
        else:
            if corrente is None:
                continue

            inclusi = PATTERN_INCLUSI.match(riga)
            esclusi = PATTERN_ESCLUSI.match(riga)
            if inclusi or esclusi:
                _chiudi_gruppo(gruppo_corrente, suffisso_graffa)
                gruppo_corrente = []
                suffisso_graffa = ""
                dentro_nota = False
                blocco = "inclusi" if inclusi else "esclusi"
                resto = (inclusi or esclusi).group(1).strip()
                prefisso_elenco = resto[:-1].strip() if resto.endswith(":") else ""
                if resto and not resto.endswith(":"):
                    _aggiungi(corrente, blocco, pulisci_termine(resto))
                continue

            if blocco is None:
                continue

            elemento = PATTERN_ELENCO.match(riga)
            if elemento:
                dentro_nota = False
                voce = elemento.group(1).strip()
                if voce.endswith(":"):
                    # Sotto-elenco annidato: diventa il nuovo prefisso.
                    prefisso_elenco = f"{prefisso_elenco} {voce[:-1]}".strip()
                    gruppo_corrente = []
                    suffisso_graffa = ""
                    continue

                # Il suffisso della graffa, se presente, vale per tutto il
                # gruppo: lo mettiamo da parte e lo applichiamo alla chiusura.
                graffa = PATTERN_SUFFISSO_GRAFFA.match(voce)
                if graffa:
                    voce = graffa.group(1).strip()
                    suffisso_graffa = graffa.group(2).strip()

                gruppo_corrente.append((corrente, blocco, prefisso_elenco, voce))
                continue

            # Qualunque riga non puntata chiude il gruppo di bullet aperto.
            _chiudi_gruppo(gruppo_corrente, suffisso_graffa)
            gruppo_corrente = []
            suffisso_graffa = ""

            # Riga di continuazione dentro un blocco, senza marcatore di elenco.
            testo_riga = riga.strip()
            if not testo_riga or testo_riga.startswith(("Incl", "Escl")):
                continue

            if PATTERN_NOTA_ISTRUTTIVA.match(testo_riga):
                dentro_nota = True
                continue
            if dentro_nota:
                # Coda della nota istruttiva: non e' un termine clinico.
                continue

            if testo_riga.endswith(":"):
                prefisso_elenco = testo_riga[:-1].strip()
            else:
                _aggiungi(corrente, blocco, pulisci_termine(testo_riga))

    _chiudi_gruppo(gruppo_corrente, suffisso_graffa)
    return list(voci.values())


def _chiudi_gruppo(gruppo: list[tuple], suffisso: str) -> None:
    """Registra i termini di un gruppo di elenco, applicando il suffisso comune.

    Il suffisso della graffa si applica a *tutte* le voci del gruppo, non solo a
    quella su cui `pdftotext` lo ha appiattito.
    """
    for voce_icd, blocco, prefisso, termine in gruppo:
        parti = [prefisso, termine, suffisso]
        completo = " ".join(p for p in parti if p).strip()
        _aggiungi(voce_icd, blocco, pulisci_termine(completo))


# Righe che nell'ICD sono istruzioni al codificatore, non termini clinici.
# Finivano fra i sinonimi ("Utilizzare un codice aggiuntivo se si desidera
# identificare...") e da li' nel gazetteer.
PATTERN_NOTA_ISTRUTTIVA = re.compile(
    r"^(utilizzare|usare|codificare|questa categoria|questo capitolo|nota|"
    r"include|comprende|per |se si desidera|i codici|il codice)\b",
    re.IGNORECASE,
)


def _aggiungi(voce: VoceICD, blocco: str, termine: str) -> None:
    """Aggiunge un termine al blocco giusto, scartando i vuoti e i duplicati."""
    if not termine or len(termine) < 3:
        return
    if PATTERN_NOTA_ISTRUTTIVA.match(termine):
        return
    destinazione = voce.inclusi if blocco == "inclusi" else voce.esclusi
    if termine not in destinazione:
        destinazione.append(termine)


def costruisci_indice_termini(voci: list[VoceICD]) -> dict[str, list[str]]:
    """Costruisce l'indice termine -> codici, con i parentetici espansi.

    E' la struttura che servira' davvero al gazetteer e all'entity linking: dato
    un testo, quali codici puo' denotare. Un termine puo' mappare a piu' codici;
    non scegliamo qui, la disambiguazione e' compito della pipeline.
    """
    indice: dict[str, set[str]] = {}
    for voce in voci:
        for termine in [voce.titolo, *voce.inclusi]:
            for forma in espandi_parentetici(termine):
                chiave = forma.lower().strip()
                if len(chiave) >= 4:
                    indice.setdefault(chiave, set()).add(voce.codice)
    return {termine: sorted(codici) for termine, codici in sorted(indice.items())}


def main() -> None:
    if not PERCORSO_PDF.exists():
        sys.exit(f"PDF non trovato: {PERCORSO_PDF}")

    print("Estrazione del testo dal PDF (890 pagine)...")
    testo = estrai_testo(PERCORSO_PDF, PERCORSO_TESTO)
    print(f"  {len(testo.splitlines())} righe")

    voci = analizza(testo)
    categorie = [v for v in voci if v.livello == "categoria"]
    sottocategorie = [v for v in voci if v.livello == "sottocategoria"]
    con_inclusi = [v for v in voci if v.inclusi]
    print(f"\nVoci estratte: {len(voci)}")
    print(f"  categorie (3 caratteri):     {len(categorie)}")
    print(f"  sottocategorie (4 caratteri): {len(sottocategorie)}")
    print(f"  voci con termini inclusi:     {len(con_inclusi)}")

    indice = costruisci_indice_termini(voci)
    print(f"  termini distinti nell'indice: {len(indice)}")

    documento = {
        "citazione": CITAZIONE,
        "conteggi": {
            "voci_totali": len(voci),
            "categorie": len(categorie),
            "sottocategorie": len(sottocategorie),
            "voci_con_inclusi": len(con_inclusi),
            "termini_indice": len(indice),
        },
        "voci": [
            {
                "codice": v.codice,
                "titolo": v.titolo,
                "livello": v.livello,
                "capitolo": v.capitolo,
                "inclusi": v.inclusi,
                "esclusi": v.esclusi,
            }
            for v in sorted(voci, key=lambda v: v.codice)
        ],
        "indice_termini": indice,
    }
    PERCORSO_USCITA.parent.mkdir(parents=True, exist_ok=True)
    PERCORSO_USCITA.write_text(
        json.dumps(documento, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nScritto {PERCORSO_USCITA.relative_to(RADICE)} "
          f"({PERCORSO_USCITA.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
