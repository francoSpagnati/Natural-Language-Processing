"""Step 2 - Estrazione della terminologia ICD-10 italiana dal PDF ufficiale.

Fonte: "ICD-10 2019 in italiano - Volume 1, Elenco sistematico" (Centro
Collaboratore Italiano OMS, reteclassificazioni.it), l'unica terminologia
autorevole e in italiano disponibile (alternative misurate in docs/02). Il
PDF ha testo estraibile: `pdftotext -layout`, poi un parser a stati che
raccoglie titoli e termini "Incl." (i sinonimi che servono al gazetteer); gli
"Escl." sono rimandi e restano a parte.

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

# La graffa del volume ("* adenofibromatosa       della prostata"): il
# suffisso comune vale per tutto il gruppo; tre o piu' spazi lo segnalano.
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
    """PDF -> testo con `pdftotext -layout` (la spaziatura distingue categorie e sottocategorie); salvato su disco."""
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
    """Espande i modificatori opzionali fra parentesi dell'ICD, nella loro posizione.

    "diabete (mellito) (non obeso) ..." -> senza modificatori, con ciascuno da
    solo, con tutti; non tutte le combinazioni. Le parentesi con un codice
    sono rimandi e si tolgono.
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
    """Parser a stati sul testo estratto: voce corrente, blocco Incl./Escl., sotto-elenchi ricomposti col prefisso."""
    voci: dict[str, VoceICD] = {}
    corrente: VoceICD | None = None
    blocco: str | None = None      # "inclusi" | "esclusi" | None
    prefisso_elenco = ""           # termine che introduce un sotto-elenco
    gruppo_corrente: list[tuple] = []   # bullet in attesa del suffisso di graffa
    suffisso_graffa = ""
    # Le note istruttive vanno a capo: si scarta anche la coda.
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
                # Le categorie compaiono due volte nel PDF: si arricchisce la prima.
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
    """Registra i termini di un gruppo, applicando a tutti il suffisso della graffa."""
    for voce_icd, blocco, prefisso, termine in gruppo:
        parti = [prefisso, termine, suffisso]
        completo = " ".join(p for p in parti if p).strip()
        _aggiungi(voce_icd, blocco, pulisci_termine(completo))


# Istruzioni al codificatore, non termini clinici.
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
    """Indice termine -> codici con i parentetici espansi; la disambiguazione e' delle pipeline."""
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
