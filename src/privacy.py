"""Controllo che nessun file versionato contenga testo clinico identificabile.

PERCHE' ESISTE
    I dati clinici non entrano nel repository: `.gitignore` esclude
    `data/raw/`, `data/interim/`, `data/processed/`. Resta però un canale che
    nessun `.gitignore` intercetta: **le citazioni dentro documenti, commenti e
    test**. Un esempio copiato da un referto per illustrare una regola è testo
    clinico che finisce su GitHub.

    Questo controllo ha già trovato violazioni tre volte, sempre mie, e l'ultima
    solo perché è stato esteso a tutto il repository invece che ai file appena
    modificati. Va eseguito su tutto, sempre.

LA REGOLA
    Nessuna finestra di 40 caratteri di un file versionato deve comparire in meno
    di 5 referti del corpus. Una frase che compare in molti referti è
    boilerplate del modulo, non il racconto di un paziente.

PERCHE' IL CONFRONTO E' SULLA FINESTRA RIPULITA
    Una versione precedente confrontava la finestra grezza, e uno spazio iniziale
    prima di un'intestazione di modulo bastava a far sembrare «rara» una stringa
    presente in 344 referti. Si confronta la finestra con `strip()`.

L'ECCEZIONE: IL VOCABOLARIO PUBBLICO
    «insufficienza mitralica congenita» compare nei referti, ma è un titolo
    dell'ICD-10: è vocabolario pubblicato, non il racconto di un paziente, e un
    progetto di codifica clinica deve poterlo scrivere. Sono esclusi i titoli
    ICD-10, i termini dell'indice analitico e le descrizioni ATC.

    L'eccezione vale per il termine **e per ogni sua porzione**, non per una
    frase che lo contiene: «diabete mellito» è vocabolario e «ficienza mitralica
    congeni» lo è altrettanto, perché la finestra scorrevole taglia i termini a
    metà e una porzione di vocabolario resta vocabolario. Una frase che intreccia
    più termini con i legamenti del racconto — una familiarità, un parente
    nominato, una data — non lo è, e nessun termine pubblicato la contiene.

    Questo controllo ha segnalato **la propria docstring**: l'esempio che usava
    per illustrare la regola era una frase vera, presente in un referto solo. È
    la prova che serviva: la regola non fa eccezioni per chi la scrive.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

from data_loading import carica_dataset

RADICE = Path(__file__).resolve().parent.parent
FINESTRA = 40
SOGLIA_REFERTI = 5
LUNGHEZZA_MINIMA = 25
ESTENSIONI = {".py", ".md", ".ipynb", ".txt", ".json", ".csv", ".ttl"}


def vocabolario_pubblico(radice: Path = RADICE) -> str:
    """I termini pubblicati, concatenati in un unico blocco.

    Un blocco e non un insieme perché la verifica dev'essere «questa finestra è
    contenuta in un termine pubblicato?», non «coincide con uno?»: la finestra
    scorrevole di 40 caratteri taglia i termini a metà, e chiedere l'uguaglianza
    lascerebbe passare per dato clinico ogni mezzo titolo dell'ICD-10.
    """
    termini: set[str] = set()
    icd = radice / "data" / "interim" / "terminologia_icd10.json"
    if icd.exists():
        dati = json.loads(icd.read_text(encoding="utf-8"))
        termini |= {v["titolo"].lower() for v in dati["voci"]}
        termini |= {t.lower() for t in dati.get("indice_termini", {})}
    atc = radice / "data" / "external" / "aifa" / "atc.csv"
    if atc.exists():
        with atc.open(encoding="utf-8-sig") as f:
            termini |= {r["DESCRIZIONE"].lower() for r in csv.DictReader(f, delimiter=";")}
    # Separate da un carattere che non compare nei termini, così una finestra non
    # può risultare «contenuta» accavallando la fine di un termine e l'inizio
    # del successivo.
    return "\n".join(sorted(termini))


def file_versionati(radice: Path = RADICE) -> list[Path]:
    elenco = subprocess.run(["git", "ls-files"], cwd=radice,
                            capture_output=True, text=True, check=True).stdout.split()
    return [radice / f for f in elenco if Path(f).suffix in ESTENSIONI]


def controlla(radice: Path = RADICE) -> list[tuple[Path, str, int]]:
    """Le frasi di file versionati che compaiono in troppo pochi referti.

    Le finestre sovrapposte vengono fuse, così il rapporto elenca frasi e non
    centinaia di finestre scorrevoli della stessa frase.
    """
    record, _ = carica_dataset(radice / "data" / "raw" / "anamnesiterapie.txt")
    testi = [(r.testo_anamnesi or "") for r in record]
    corpus = "\n".join(testi)
    pubblici = vocabolario_pubblico(radice)

    def rara(finestra: str) -> bool:
        if len(finestra) < LUNGHEZZA_MINIMA or finestra not in corpus:
            return False
        if finestra.strip(" .,\"'()-").lower() in pubblici:
            return False
        return sum(1 for t in testi if finestra in t) < SOGLIA_REFERTI

    trovate: list[tuple[Path, str, int]] = []
    for percorso in file_versionati(radice):
        try:
            testo = percorso.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        inizio = fine = None
        for i in range(0, max(0, len(testo) - FINESTRA)):
            if rara(testo[i:i + FINESTRA].strip()):
                if inizio is None:
                    inizio = i
                fine = i + FINESTRA
            elif inizio is not None:
                frase = testo[inizio:fine].strip()
                trovate.append((percorso.relative_to(radice), frase,
                                sum(1 for t in testi if frase[:FINESTRA] in t)))
                inizio = None
        if inizio is not None:
            frase = testo[inizio:fine].strip()
            trovate.append((percorso.relative_to(radice), frase,
                            sum(1 for t in testi if frase[:FINESTRA] in t)))
    return trovate


def main() -> None:
    trovate = controlla()
    for percorso, frase, quanti in trovate:
        print(f"{percorso}\n    ({quanti} referti) {frase[:140]!r}")
    print(f"\nfrasi specifiche: {len(trovate)}")
    if trovate:
        print("\nSostituirle con equivalenti sintetici, oppure accorciarle sotto")
        print(f"i {FINESTRA} caratteri. Il repository non deve contenere testo clinico.")
    sys.exit(1 if trovate else 0)


if __name__ == "__main__":
    main()
