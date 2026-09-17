"""Step 7 - Lo script di import della knowledge base clinica (brief sez. 3.3).

Scrive `kb/conoscenza.ttl` a partire da tre cose:

1. le **indicazioni** (27) e le **controindicazioni** (12) dichiarate qui
   sotto — curatela manuale con la fonte puntuale per ogni riga, come il brief
   ammette per il layer delle linee guida, che sono documenti e non API;
2. le etichette italiane dei codici ATC (registro AIFA) e ICD-10 (Elenco
   Sistematico 2019), lette dalle knowledge base scaricate;
3. il manifest `kb/manifest_fonti.json`, dove registra data di generazione e
   conteggi, cosi' il grafo si rigenera rieseguendo lo script.

Perche' le regole sono curate a mano e non importate da openFDA o Wikidata:
openFDA pubblica le schede tecniche americane in inglese e come testo libero,
non come relazioni; Wikidata ha `P2175` (condizione trattata) e `P769`
(interazione), ma la sonda `--sonda-wikidata` misura quanto coprono i nostri
principi attivi — il numero e' nel manifest, e la decisione nel doc 7.

Uso:

    python3 src/kb_build.py                  # scrive kb/conoscenza.ttl
    python3 src/kb_build.py --figura         # + docs/img/conoscenza.png
    python3 src/kb_build.py --sonda-wikidata # copertura di Wikidata, in rete
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))

from conoscenza import (  # noqa: E402
    PERCORSO, Controindicazione, Esito, Indicazione, scrivi,
)

MANIFEST = RADICE / "kb" / "manifest_fonti.json"


# ---------------------------------------------------------------------------
# LE INDICAZIONI CLINICHE
#
# Stessa disciplina delle controindicazioni dello step 8: ogni riga porta la
# fonte, e la fonte e' un documento pubblicato, non la conoscenza di un modello.
# La granularita' della citazione e' **documento + sezione**, deliberatamente
# non la pagina: ho trascritto a mano dalle tabelle di raccomandazione, e un
# numero di pagina che non posso verificare sarebbe una precisione falsa.
#
# Il perimetro e' la cardiologia, perche' e' li' che ho linee guida citabili.
# Cio' che resta fuori resta fuori: vedi il tetto del 60% nel docstring.
# ---------------------------------------------------------------------------

INDICAZIONI: tuple[Indicazione, ...] = (
    # --- Scompenso cardiaco -------------------------------------------------
    # I quattro pilastri della terapia dello scompenso a frazione di eiezione
    # ridotta. Il sistema non estrae la frazione di eiezione, quindi non sa
    # distinguere HFrEF da HFpEF: le regole valgono per I50 nel suo insieme e
    # questo e' dichiarato, non nascosto.
    Indicazione(
        "C09A", ("I50",), "I",
        "ACE-inibitore nello scompenso a frazione di eiezione ridotta: riduce "
        "mortalita' e ricoveri. Primo dei quattro pilastri.",
        "ESC 2021, Guidelines for the diagnosis and treatment of acute and "
        "chronic heart failure, terapia farmacologica dell'HFrEF.",
        fatto_non_estratto="frazione di eiezione: nessuna pipeline la estrae, "
                           "quindi HFrEF e HFpEF non sono distinguibili",
    ),
    Indicazione(
        "C09DX04", ("I50",), "I",
        "Sacubitril/valsartan in sostituzione dell'ACE-inibitore nei pazienti "
        "che restano sintomatici.",
        "ESC 2021, Guidelines for heart failure, terapia dell'HFrEF.",
        fatto_non_estratto="persistenza dei sintomi in terapia ottimale",
    ),
    Indicazione(
        "C07AB", ("I50",), "I",
        "Betabloccante nello scompenso a frazione di eiezione ridotta, in "
        "paziente stabile. Secondo pilastro.",
        "ESC 2021, Guidelines for heart failure, terapia dell'HFrEF.",
    ),
    Indicazione(
        "C03DA", ("I50",), "I",
        "Antagonista del recettore mineralcorticoide. Terzo pilastro.",
        "ESC 2021, Guidelines for heart failure, terapia dell'HFrEF.",
    ),
    Indicazione(
        "A10BK", ("I50",), "I",
        "Inibitore di SGLT2 nello scompenso, indipendentemente dal diabete. "
        "Quarto pilastro, aggiunto dall'aggiornamento del 2023.",
        "ESC 2023, Focused update of the 2021 heart failure guidelines, "
        "raccomandazioni su dapagliflozin ed empagliflozin.",
    ),
    Indicazione(
        "C03CA", ("I50",), "I",
        "Diuretico dell'ansa per il controllo della congestione: migliora i "
        "sintomi, non la sopravvivenza.",
        "ESC 2021, Guidelines for heart failure, trattamento della congestione.",
    ),
    Indicazione(
        "C09C", ("I50",), "IIa",
        "Sartano come alternativa all'ACE-inibitore quando questo non e' "
        "tollerato, tipicamente per tosse.",
        "ESC 2021, Guidelines for heart failure, alternative all'ACE-inibitore.",
    ),

    # --- Fibrillazione atriale ----------------------------------------------
    # L'anticoagulazione dipende dal punteggio CHA2DS2-VA, che il sistema non
    # calcola: mancano eta' e sesso, che non sono nello schema. La regola resta
    # di classe I perche' nella popolazione di questo corpus — ricoverati in
    # cardiologia — il punteggio e' quasi sempre sopra la soglia, ma il fatto
    # mancante e' dichiarato.
    Indicazione(
        "B01AF", ("I48",), "I",
        "Anticoagulante orale diretto nella fibrillazione atriale: prevenzione "
        "del cardioembolismo. Preferito agli antagonisti della vitamina K.",
        "ESC 2024, Guidelines for the management of atrial fibrillation, "
        "raccomandazioni sulla prevenzione del tromboembolismo.",
        fatto_non_estratto="punteggio CHA2DS2-VA: richiede eta' e sesso, che "
                           "lo schema non contiene",
    ),
    Indicazione(
        "B01AA", ("I48",), "IIa",
        "Antagonista della vitamina K quando l'anticoagulante diretto e' "
        "controindicato: protesi valvolare meccanica, stenosi mitralica "
        "reumatica.",
        "ESC 2024, Guidelines for atrial fibrillation, scelta "
        "dell'anticoagulante.",
    ),
    Indicazione(
        "C07AB", ("I48",), "I",
        "Betabloccante per il controllo della frequenza nella fibrillazione "
        "atriale.",
        "ESC 2024, Guidelines for atrial fibrillation, controllo della frequenza.",
    ),
    Indicazione(
        "C01AA", ("I48",), "IIa",
        "Digossina per il controllo della frequenza, in aggiunta o quando i "
        "betabloccanti non bastano.",
        "ESC 2024, Guidelines for atrial fibrillation, controllo della frequenza.",
    ),
    Indicazione(
        "C01BD", ("I48",), "IIa",
        "Amiodarone per il mantenimento del ritmo sinusale nei pazienti in cui "
        "si sceglie la strategia di controllo del ritmo.",
        "ESC 2024, Guidelines for atrial fibrillation, controllo del ritmo.",
    ),

    # --- Ipertensione arteriosa ---------------------------------------------
    # La classe piu' frequente del corpus fra le condizioni: I10 compare in 486
    # ricoveri su 841.
    Indicazione(
        "C09AA", ("I10", "I11", "I12", "I13", "I15"), "I",
        "ACE-inibitore come farmaco di prima linea nell'ipertensione.",
        "ESC/ESH 2024, Guidelines for the management of elevated blood pressure "
        "and hypertension, strategia di trattamento farmacologico.",
    ),
    Indicazione(
        "C09CA", ("I10", "I11", "I12", "I13", "I15"), "I",
        "Sartano come farmaco di prima linea nell'ipertensione, alternativo "
        "all'ACE-inibitore.",
        "ESC/ESH 2024, Guidelines for hypertension, trattamento farmacologico.",
    ),
    Indicazione(
        "C08CA", ("I10", "I11", "I12", "I13", "I15"), "I",
        "Calcioantagonista diidropiridinico come farmaco di prima linea, "
        "tipicamente in associazione a un bloccante del sistema "
        "renina-angiotensina.",
        "ESC/ESH 2024, Guidelines for hypertension, trattamento farmacologico.",
    ),
    Indicazione(
        "C03AA", ("I10", "I11", "I12", "I13", "I15"), "I",
        "Diuretico tiazidico o simil-tiazidico come farmaco di prima linea.",
        "ESC/ESH 2024, Guidelines for hypertension, trattamento farmacologico.",
    ),
    Indicazione(
        "C07AB", ("I10", "I11", "I12", "I13", "I15"), "IIa",
        "Betabloccante nell'ipertensione: non di prima linea in assenza di "
        "un'indicazione specifica, ma indicato quando coesistono cardiopatia "
        "ischemica, scompenso o fibrillazione atriale.",
        "ESC/ESH 2024, Guidelines for hypertension, ruolo dei betabloccanti.",
    ),

    # --- Malattia aterosclerotica e dislipidemia ----------------------------
    Indicazione(
        "C10AA", ("I20", "I21", "I22", "I23", "I24", "I25", "I63", "I65",
                  "I66", "I67", "I70", "I73", "E78"), "I",
        "Statina ad alta intensita' nella malattia aterosclerotica accertata e "
        "nella dislipidemia: riduzione del colesterolo LDL.",
        "ESC/EAS 2019, Guidelines for the management of dyslipidaemias, "
        "raccomandazioni sul trattamento ipolipemizzante.",
    ),
    Indicazione(
        "C10BA", ("I20", "I21", "I22", "I23", "I24", "I25", "I70", "E78"), "IIa",
        "Associazione con ezetimibe quando la statina da sola non porta il "
        "colesterolo LDL all'obiettivo.",
        "ESC/EAS 2019, Guidelines for dyslipidaemias, terapia di associazione.",
        fatto_non_estratto="valore del colesterolo LDL: non e' nello schema, "
                           "quindi non si sa se l'obiettivo sia raggiunto",
    ),
    Indicazione(
        "B01AC", ("I20", "I21", "I22", "I23", "I24", "I25", "I63", "I65",
                  "I66", "I70", "I73"), "I",
        "Antiaggregante piastrinico nella malattia aterosclerotica accertata.",
        "ESC 2024, Guidelines for the management of chronic coronary syndromes, "
        "terapia antitrombotica.",
    ),
    Indicazione(
        "C07AB", ("I21", "I22", "I23", "I25.2"), "I",
        "Betabloccante dopo infarto miocardico.",
        "ESC 2023, Guidelines for the management of acute coronary syndromes, "
        "terapia a lungo termine.",
    ),
    Indicazione(
        "C09AA", ("I21", "I22", "I23", "I25.2"), "I",
        "ACE-inibitore dopo infarto miocardico, in particolare con disfunzione "
        "ventricolare sinistra.",
        "ESC 2023, Guidelines for acute coronary syndromes, terapia a lungo "
        "termine.",
    ),

    # --- Diabete ------------------------------------------------------------
    Indicazione(
        "A10BK", ("E10", "E11", "E13", "E14"), "I",
        "Inibitore di SGLT2 nel diabete di tipo 2 con malattia cardiovascolare "
        "accertata: beneficio cardiovascolare indipendente dal controllo "
        "glicemico.",
        "ESC 2023, Guidelines for the management of cardiovascular disease in "
        "patients with diabetes.",
    ),
    Indicazione(
        "A10BJ", ("E10", "E11", "E13", "E14"), "I",
        "Agonista del recettore del GLP-1 nel diabete di tipo 2 con malattia "
        "cardiovascolare accertata.",
        "ESC 2023, Guidelines for cardiovascular disease in patients with "
        "diabetes.",
    ),
    Indicazione(
        "A10BA", ("E10", "E11", "E13", "E14"), "IIa",
        "Metformina come terapia di fondo del diabete di tipo 2.",
        "ESC 2023, Guidelines for cardiovascular disease in patients with "
        "diabetes, controllo glicemico.",
    ),

    # --- Malattia renale cronica --------------------------------------------
    Indicazione(
        "A10BK", ("N18",), "I",
        "Inibitore di SGLT2 nella malattia renale cronica: rallenta la "
        "progressione del danno renale.",
        "ESC 2023, Guidelines for cardiovascular disease in patients with "
        "diabetes, sezione sulla malattia renale cronica.",
    ),

    # --- Gastroprotezione: innescata dalla terapia, non dalla diagnosi ------
    Indicazione(
        "A02BC", (), "IIa",
        "Inibitore di pompa protonica in paziente in terapia antitrombotica: "
        "riduce il rischio di sanguinamento gastrointestinale. La linea guida "
        "la raccomanda in classe I nei pazienti ad alto rischio emorragico, che "
        "questo sistema non sa identificare.",
        "ESC 2023, Guidelines for acute coronary syndromes, e ESC 2024, "
        "Guidelines for atrial fibrillation, prevenzione del sanguinamento "
        "gastrointestinale.",
        atc_richiesto=("B01A",),
        fatto_non_estratto="rischio emorragico gastrointestinale: richiede "
                           "anamnesi di ulcera, eta' e uso concomitante di FANS",
    ),
)


REGOLE_CONTROINDICAZIONE: tuple[Controindicazione, ...] = (
    Controindicazione(
        "C07", ("J45", "J44"), Esito.DA_VERIFICARE,
        "Betabloccante in asma o broncopneumopatia: rischio di broncospasmo. "
        "I cardioselettivi sono spesso tollerati, quindi la decisione e' clinica.",
        "ESC/ESH 2024, Guidelines for the management of elevated blood pressure "
        "and hypertension, sezione sui betabloccanti.",
    ),
    Controindicazione(
        "C07", ("I44.1", "I44.2", "I44.3"), Esito.VIETATO,
        "Betabloccante in blocco atrioventricolare di grado avanzato: rischio di "
        "bradicardia grave e asistolia. La controindicazione cade se il paziente "
        "porta un pacemaker.",
        "Riassunto delle Caratteristiche del Prodotto dei betabloccanti "
        "(AIFA/EMA), sezione 4.3 Controindicazioni.",
        revocata_da=("Z95.0", "Z95"),
        fatto_non_estratto="presenza di pacemaker o defibrillatore (ICD-10 Z95.0)",
    ),
    Controindicazione(
        "C08D", ("I50",), Esito.VIETATO,
        "Calcioantagonista non diidropiridinico (verapamil, diltiazem) in "
        "scompenso cardiaco a frazione di eiezione ridotta: effetto inotropo "
        "negativo.",
        "ESC 2021, Guidelines for the diagnosis and treatment of acute and "
        "chronic heart failure, raccomandazioni sui farmaci da evitare.",
    ),
    Controindicazione(
        "M01A", ("I50",), Esito.VIETATO,
        "Antinfiammatorio non steroideo in scompenso cardiaco: ritenzione idrica "
        "e peggioramento dello scompenso.",
        "ESC 2021, Guidelines for heart failure, farmaci da evitare.",
    ),
    Controindicazione(
        "M01A", ("N18.4", "N18.5"), Esito.VIETATO,
        "Antinfiammatorio non steroideo in insufficienza renale cronica "
        "avanzata: ulteriore riduzione della filtrazione glomerulare.",
        "RCP dei FANS (AIFA/EMA), sezione 4.3.",
    ),
    Controindicazione(
        "C09", ("O00", "O09", "O10", "O11", "O12", "O13", "O14", "O15",
                "O16", "O20", "O21"), Esito.VIETATO,
        "ACE-inibitore o sartano in gravidanza: tossicita' fetale documentata "
        "nel secondo e terzo trimestre.",
        "RCP degli ACE-inibitori e dei sartani (AIFA/EMA), sezione 4.3 e 4.6.",
    ),
    Controindicazione(
        "C09", ("I70.1",), Esito.VIETATO,
        "ACE-inibitore o sartano in stenosi bilaterale delle arterie renali: "
        "rischio di insufficienza renale acuta.",
        "RCP degli ACE-inibitori (AIFA/EMA), sezione 4.3.",
    ),
    Controindicazione(
        "A10BA02", ("N18.4", "N18.5"), Esito.VIETATO,
        "Metformina in insufficienza renale grave: rischio di acidosi lattica.",
        "RCP della metformina (AIFA/EMA), sezione 4.3, soglia di filtrato "
        "glomerulare.",
    ),
    Controindicazione(
        "B01A", ("I60", "I61", "I62"), Esito.VIETATO,
        "Antitrombotico in emorragia intracranica: rischio di risanguinamento. "
        "Vale per l'emorragia in atto o recente; un'emorragia remota e' una "
        "cautela, non un divieto.",
        "RCP degli anticoagulanti orali (AIFA/EMA), sezione 4.3; ESC 2020, "
        "Guidelines for atrial fibrillation.",
        fatto_non_estratto=(
            "storicita' della condizione: ConText la calcola, ma lo schema non "
            "ha un campo per registrarla e finisce in una stringa di provenienza"
        ),
    ),
    Controindicazione(
        "C01BD01", ("E05", "E03"), Esito.DA_VERIFICARE,
        "Amiodarone in tireopatia: il farmaco contiene iodio e altera la "
        "funzione tiroidea; richiede monitoraggio o alternativa.",
        "RCP dell'amiodarone (AIFA/EMA), sezioni 4.3 e 4.4.",
    ),
    Controindicazione(
        "C10AA", ("K70", "K71", "K72", "K74"), Esito.DA_VERIFICARE,
        "Statina in epatopatia attiva: richiede valutazione della funzione "
        "epatica prima e durante il trattamento.",
        "RCP delle statine (AIFA/EMA), sezione 4.3.",
    ),
    Controindicazione(
        "C03A", ("M10",), Esito.DA_VERIFICARE,
        "Diuretico tiazidico in gotta: riduce l'escrezione di acido urico e puo' "
        "precipitare un attacco.",
        "RCP dei tiazidici (AIFA/EMA), sezione 4.4.",
    ),
)


# ---------------------------------------------------------------------------
# Etichette dei codici, dalle knowledge base scaricate
# ---------------------------------------------------------------------------

def etichette_atc() -> dict[str, str]:
    percorso = RADICE / "data" / "external" / "aifa" / "atc.csv"
    if not percorso.exists():
        return {}
    with percorso.open(encoding="utf-8-sig") as f:
        return {r["CODICE_ATC"].strip(): r["DESCRIZIONE"].strip().lower()
                for r in csv.DictReader(f, delimiter=";")}


def etichette_icd() -> dict[str, str]:
    percorso = RADICE / "data" / "interim" / "terminologia_icd10.json"
    if not percorso.exists():
        return {}
    voci = json.loads(percorso.read_text(encoding="utf-8"))["voci"]
    return {v["codice"]: v["titolo"] for v in voci}


def codici_citati() -> set[str]:
    codici = set()
    for i in INDICAZIONI:
        codici.update((i.atc,) + i.icd + i.atc_richiesto)
    for c in REGOLE_CONTROINDICAZIONE:
        codici.update((c.atc,) + c.icd + c.revocata_da)
    return codici


# ---------------------------------------------------------------------------
# Figura: il grafo di conoscenza come immagine (brief sez. 3.3, networkx + matplotlib)
# ---------------------------------------------------------------------------

def figura(percorso: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import networkx as nx

    g = nx.DiGraph()
    for i in INDICAZIONI:
        for c in i.icd:
            g.add_edge(c, i.atc, tipo="indicazione", classe=i.classe_racc)
        for a in i.atc_richiesto:
            g.add_edge(a, i.atc, tipo="indicazione", classe=i.classe_racc)
    for c in REGOLE_CONTROINDICAZIONE:
        for k in c.icd:
            g.add_edge(k, c.atc, tipo=c.esito.value)
    condizioni = sorted(n for n in g if n[0] in "IJKENMO" and not n[1:2].isalpha())
    farmaci = sorted(n for n in g if n not in condizioni)
    # Bipartito: condizioni a sinistra, classi ATC a destra, ordinate per codice.
    # Un layout a molla su 100 nodi e' una palla di pelo; questo si legge.
    pos = {n: (0, -i) for i, n in enumerate(condizioni)}
    passo = len(condizioni) / max(1, len(farmaci))
    pos.update({n: (1, -i * passo) for i, n in enumerate(farmaci)})
    colori_archi = {"indicazione": "#2f6b4f", "vietato": "#963025", "da_verificare": "#8a5a0c"}
    fig, ax = plt.subplots(figsize=(11, 0.28 * len(condizioni) + 1))
    nx.draw_networkx_nodes(g, pos, nodelist=condizioni, node_color="#eceffa",
                           edgecolors="#2b3f8c", node_size=900, node_shape="s", ax=ax)
    nx.draw_networkx_nodes(g, pos, nodelist=farmaci, node_color="#ffffff",
                           edgecolors="#5a616e", node_size=900, node_shape="s", ax=ax)
    for tipo, colore in colori_archi.items():
        archi = [(u, v) for u, v, d in g.edges(data=True) if d["tipo"] == tipo]
        nx.draw_networkx_edges(g, pos, edgelist=archi, edge_color=colore, width=1.2,
                               arrows=False, alpha=0.8, ax=ax,
                               style="dashed" if tipo == "da_verificare" else "solid")
    nx.draw_networkx_labels(g, pos, font_size=7, font_family="monospace", ax=ax)
    ax.set_xlim(-0.15, 1.15)
    ax.set_title("kb/conoscenza.ttl — condizioni ICD-10 (sinistra) e classi ATC (destra). "
                 "Verde: indicazione; rosso: vietato; ambra tratteggiato: da verificare",
                 fontsize=9)
    ax.axis("off")
    percorso.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(percorso, dpi=130, bbox_inches="tight")
    print(f"figura: {percorso}")


# ---------------------------------------------------------------------------
# Sonda: quanto Wikidata coprirebbe (brief sez. 3.3: «valuta empiricamente»)
# ---------------------------------------------------------------------------

def sonda_wikidata() -> dict:
    """Per i principi attivi risolti ad ATC (step 2b), quanti hanno su Wikidata
    P267 (codice ATC), P2175 (condizione trattata) e P769 (interazione)."""
    import urllib.parse
    import urllib.request

    mappatura = json.loads((RADICE / "data" / "interim" / "mappatura_atc.json")
                           .read_text(encoding="utf-8"))
    codici = sorted({v["codice_atc"] for v in mappatura["voci"]
                     if v.get("codice_atc") and len(v["codice_atc"]) == 7})
    valori = " ".join(f'"{c}"' for c in codici)
    query = f"""
    SELECT ?atc (COUNT(DISTINCT ?ind) AS ?indicazioni) (COUNT(DISTINCT ?int) AS ?interazioni) WHERE {{
      VALUES ?atc {{ {valori} }}
      ?farmaco wdt:P267 ?atc .
      OPTIONAL {{ ?farmaco wdt:P2175 ?ind }}
      OPTIONAL {{ ?farmaco wdt:P769 ?int }}
    }} GROUP BY ?atc"""
    # POST: con centinaia di codici in VALUES la query non sta in una URL.
    req = urllib.request.Request(
        "https://query.wikidata.org/sparql",
        data=urllib.parse.urlencode({"query": query, "format": "json"}).encode(),
        headers={"User-Agent": "progetto-nlp-cardio/1.0",
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=120) as risposta:
        righe = json.load(risposta)["results"]["bindings"]
    con_atc = {r["atc"]["value"]: (int(r["indicazioni"]["value"]), int(r["interazioni"]["value"]))
               for r in righe}
    esito = {
        "interrogato_il": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "principi_attivi_con_atc": len(codici),
        "trovati_su_wikidata_P267": len(con_atc),
        "con_almeno_una_indicazione_P2175": sum(1 for i, _ in con_atc.values() if i),
        "con_almeno_una_interazione_P769": sum(1 for _, k in con_atc.values() if k),
        "indicazioni_totali": sum(i for i, _ in con_atc.values()),
        "interazioni_totali": sum(k for _, k in con_atc.values()),
    }
    print(json.dumps(esito, indent=1, ensure_ascii=False))
    return esito


# ---------------------------------------------------------------------------

def costruisci() -> None:
    atc, icd = etichette_atc(), etichette_icd()
    g = scrivi(INDICAZIONI, REGOLE_CONTROINDICAZIONE, atc, icd)
    manca = sorted(c for c in codici_citati() if c not in atc and c not in icd)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    manifest["conoscenza"] = {
        "file": "kb/conoscenza.ttl",
        "generato_il": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "indicazioni": len(INDICAZIONI),
        "controindicazioni": len(REGOLE_CONTROINDICAZIONE),
        "triple": len(g),
        "curatela": "manuale, una fonte puntuale per regola (ESC, RCP AIFA/EMA)",
        "codici_senza_etichetta": manca,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{PERCORSO}: {len(g)} triple, {len(INDICAZIONI)} indicazioni, "
          f"{len(REGOLE_CONTROINDICAZIONE)} controindicazioni; senza etichetta: {manca or 'nessuno'}")


def main() -> None:
    argomenti = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    argomenti.add_argument("--figura", action="store_true")
    argomenti.add_argument("--sonda-wikidata", action="store_true")
    opzioni = argomenti.parse_args()
    costruisci()
    if opzioni.figura:
        figura(RADICE / "docs" / "img" / "conoscenza.png")
    if opzioni.sonda_wikidata:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["conoscenza"]["sonda_wikidata"] = sonda_wikidata()
        MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
