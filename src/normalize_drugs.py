"""Step 2 - Risoluzione dei farmaci del vocabolario al codice ATC.

Una cascata di strategie su AIFA, dalla piu' stringente alla piu' permissiva
(esatta, associazioni con la barra, forma salina, produttore abbreviato per
prefisso di token, suffisso salino); la prima che riesce vince e ogni voce
registra metodo ed evidenza. Nessuna sigla scritta a mano: i collegamenti
vengono dai dati AIFA. Vedi docs/02b_risoluzione_atc.md.

    python3 src/normalize_drugs.py   (dopo build_vocabularies.py e fetch_external_kb.py)
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
    """Gli indici AIFA delle strategie, costruiti una volta sola (82 MB di anagrafica)."""

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


# --- Le strategie: (codici, evidenza, fonte) oppure None ---


def strategia_principio_esatto(nome: str, indici: IndiciAIFA):
    """Il nome coincide con la descrizione ufficiale di una sostanza ATC."""
    codice = indici.descrizione_a_atc.get(nome)
    if codice:
        return [codice], indici.atc_a_descrizione[codice], FONTE_ATC
    return None


def strategia_associazione(nome: str, indici: IndiciAIFA):
    """Associazioni: "Rosuvastatina/ezetimibe" -> "rosuvastatina e ezetimibe" (anche con la virgola)."""
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
    """"Enoxaparina" -> "ENOXAPARINA SODICA": il nome del dataset e' prefisso di AIFA; piu' sostanze = ambiguo."""
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
    """Token del dataset prefissi dei token AIFA: "pantoprazolo sand" -> "pantoprazolo sandoz"."""
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
    """"Warfarin sodico" -> "WARFARIN": tolto l'ultimo token, serve corrispondenza esatta."""
    token = nome.split()
    if len(token) < 2:
        return None
    codice = indici.descrizione_a_atc.get(" ".join(token[:-1]))
    if codice:
        return [codice], indici.atc_a_descrizione[codice], FONTE_ATC
    return None


# L'ordine conta: dalla piu' stringente alla piu' permissiva, sostanze prima dei commerciali.
STRATEGIE = [
    (MetodoRisoluzione.PRINCIPIO_ESATTO, strategia_principio_esatto),
    (MetodoRisoluzione.ASSOCIAZIONE, strategia_associazione),
    (MetodoRisoluzione.COMMERCIALE_ESATTO, strategia_commerciale_esatto),
    (MetodoRisoluzione.COMMERCIALE_ABBREVIATO, strategia_commerciale_abbreviato),
    # I sali in fondo, o ruberebbero i match ai commerciali con una provenienza falsa.
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
            # Piu' sostanze compatibili: non si sceglie.
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
    # Copertura pesata sulle occorrenze: quanta parte del testo reale si normalizza.
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
