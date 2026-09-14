"""Step 8 - Il filtro di sicurezza simbolico.

CHE COSA DECIDE
    Dato lo stato di un paziente e un farmaco candidato, dice se quel farmaco
    puo' essere raccomandato. E' il punto in cui il sistema smette di descrivere
    e comincia a consigliare, quindi e' il punto in cui un errore fa danno.

PERCHE' E' SIMBOLICO, E PERCHE' NON TOCCA IL DATASET
    Due vincoli del progetto si incontrano qui.

    **Mai un modello linguistico.** Una regola di sicurezza deve poter essere
    letta, discussa e contestata da un clinico. Un modello che risponde «questo
    farmaco e' controindicato» non e' contestabile: non si puo' chiedergli su
    quale riga di quale linea guida si basa. Ogni regola qui porta la sua fonte
    nel codice, e la fonte finisce nella spiegazione che il filtro restituisce.

    **Mai il dataset.** Le regole non si imparano dai referti. Se le imparassimo,
    misureremmo cosa i cardiologi di quel reparto hanno prescritto — non cosa e'
    sicuro — e il sistema raccomanderebbe di ripetere le abitudini del reparto,
    inclusi i suoi errori. Il dataset serve a *provare* il filtro, mai a
    costruirlo.

LE QUATTRO FAMIGLIE DI REGOLE
    1. **Allergia.** Il paziente e' allergico alla sostanza, o a una sostanza
       dello stesso sottogruppo chimico. Fonte: il referto stesso piu' la
       gerarchia ATC.
    2. **Duplicazione terapeutica.** Due farmaci con lo stesso ATC di 5o livello
       sono la stessa sostanza due volte; con lo stesso ATC di 4o livello sono lo
       stesso sottogruppo farmacologico. Fonte: la definizione OMS dell'ATC, dove
       il livello si legge dalla lunghezza del codice.
    3. **Controindicazione per condizione.** Il paziente ha una condizione in cui
       quel farmaco e' controindicato. E' l'unica famiglia che richiede una
       conoscenza esterna al progetto, ed e' quindi la piu' delicata: vedi
       `REGOLE_CONTROINDICAZIONE` e la nota sulla sua natura.
    4. **Provenienza.** Non e' una regola clinica ma epistemica: dice *quanto
       fidarsi* dell'evidenza su cui le altre tre poggiano.

I TRE ESITI, E PERCHE' NON SONO DUE
    Un filtro che risponde solo «si» o «no» nasconde che i suoi due errori sono
    entrambi dannosi e non simmetrici:

    * un **falso blocco** nega al paziente una terapia che potrebbe assumere;
    * un **falso permesso** lascia passare una controindicazione.

    «Nel dubbio blocca» tratta il secondo come grave e il primo come gratuito, e
    non e' vero: negare un anticoagulante a chi ha la fibrillazione atriale fa
    danno quanto darlo a chi sanguina. Gli esiti sono quindi tre —
    `AMMESSO`, `DA_VERIFICARE`, `VIETATO` — e il secondo esiste perche' ci sono
    casi in cui la risposta onesta e' «guarda tu», con il motivo e l'evidenza
    allegati.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent


class Esito(str, Enum):
    AMMESSO = "ammesso"
    DA_VERIFICARE = "da_verificare"
    VIETATO = "vietato"


@dataclass(frozen=True)
class Regola:
    """Una regola di sicurezza, con la fonte che la sostiene.

    `fonte` non e' documentazione: viaggia nella spiegazione restituita al
    chiamante, cosi' che chi legge un blocco possa risalire a chi lo prescrive
    senza aprire il codice.
    """

    codice: str
    descrizione: str
    fonte: str


@dataclass
class Verdetto:
    """L'esito per un farmaco candidato, con tutto cio' che lo motiva."""

    atc: str
    esito: Esito
    motivi: list[dict] = field(default_factory=list)

    def aggiungi(self, esito: Esito, regola: Regola, **dettagli) -> None:
        self.motivi.append({
            "esito": esito.value,
            "regola": regola.codice,
            "descrizione": regola.descrizione,
            "fonte": regola.fonte,
            **dettagli,
        })
        # Il verdetto e' il massimo dei motivi: un solo divieto vince su ogni
        # permesso, ma un dubbio non annulla un divieto gia' emesso.
        ordine = {Esito.AMMESSO: 0, Esito.DA_VERIFICARE: 1, Esito.VIETATO: 2}
        if ordine[esito] > ordine[self.esito]:
            self.esito = esito


# ---------------------------------------------------------------------------
# Le regole
# ---------------------------------------------------------------------------

FONTE_ATC = ("Struttura della classificazione ATC dell'OMS, come pubblicata da "
             "AIFA nel registro atc.csv (CC-BY 4.0). Il livello di un codice si "
             "legge dalla sua lunghezza: 1, 3, 4, 5, 7 caratteri.")

R_ALLERGIA_STESSA = Regola(
    "ALLERGIA_SOSTANZA",
    "Il paziente e' allergico o intollerante a questa stessa sostanza.",
    "Anamnesi del paziente (sezione allergie), codificata ad ATC di 5o livello.",
)
R_ALLERGIA_GRUPPO = Regola(
    "ALLERGIA_SOTTOGRUPPO",
    "Il paziente e' allergico a una sostanza dello stesso sottogruppo chimico "
    "(ATC di 4o livello): possibile reattivita' crociata.",
    FONTE_ATC + " La reattivita' crociata entro sottogruppo e' un'ipotesi da "
    "verificare, non un fatto: per questo l'esito e' 'da verificare'.",
)
R_DUPLICATO_SOSTANZA = Regola(
    "DUPLICATO_SOSTANZA",
    "Il paziente assume gia' questa stessa sostanza.",
    FONTE_ATC,
)
R_DUPLICATO_GRUPPO = Regola(
    "DUPLICATO_SOTTOGRUPPO",
    "Il paziente assume gia' un farmaco dello stesso sottogruppo farmacologico "
    "(ATC di 4o livello).",
    FONTE_ATC + " L'associazione entro sottogruppo e' talvolta voluta "
    "(due diuretici a meccanismo diverso), quindi non e' un divieto.",
)
R_PROVENIENZA_DEBOLE = Regola(
    "EVIDENZA_DA_UNA_SOLA_FONTE",
    "La condizione che motiva questa decisione e' stata riconosciuta da una sola "
    "pipeline, e per di piu' da quella con la precisione piu' bassa.",
    "Step 6bis del progetto: precisione misurata contro il riferimento annotato.",
)


# --- La famiglia che richiede conoscenza esterna ---------------------------
#
# ATTENZIONE, E VA LETTO PRIMA DI USARE QUESTA TABELLA.
#
# Queste sono controindicazioni **ampiamente riconosciute** in cardiologia, e
# ciascuna porta la fonte puntuale. Non sono pero' una base di conoscenza
# clinica completa: sono dodici regole scelte per essere rappresentative dei
# meccanismi che un filtro deve saper esprimere (classe di farmaco contro
# categoria di condizione), non l'insieme delle controindicazioni esistenti.
#
# Il vincolo del progetto dice che una voce non coperta da una fonte esterna va
# **segnalata come mappatura manuale con la fonte puntuale usata**, invece di
# essere riempita in silenzio. E' esattamente cio' che questa tabella e': una
# mappatura manuale dichiarata, non un estratto automatico di una KB.
#
# Un sistema reale sostituirebbe questa tabella con una base di conoscenza
# completa e mantenuta. La struttura del filtro non cambierebbe: cambierebbe
# solo il contenuto di questa costante, ed e' il motivo per cui e' isolata qui.

@dataclass(frozen=True)
class Controindicazione:
    atc: str              # prefisso ATC del farmaco (qualunque livello)
    icd: tuple[str, ...]  # prefissi ICD-10 della condizione
    esito: Esito
    motivo: str
    fonte: str
    # Fatti che, se presenti, tolgono o attenuano la controindicazione: un
    # pacemaker rende sicuro un betabloccante in blocco atrioventricolare.
    revocata_da: tuple[str, ...] = ()
    # Perche' questa regola NON puo' emettere un divieto con i dati attuali.
    # Vedi `PRINCIPIO_DEL_FATTO_MANCANTE`.
    fatto_non_estratto: str | None = None


# IL PRINCIPIO CHE LO STEP 8 HA RESO NECESSARIO
#
# Una regola la cui applicazione corretta richiede un fatto che il sistema non
# sa stabilire **non puo' emettere un divieto**. Puo' segnalare, non decidere.
#
# Non e' prudenza generica: e' una conseguenza misurata. La regola
# «betabloccante in blocco atrioventricolare» ha bloccato 14 prescrizioni reali,
# e in **12 su 14** il referto nomina un pacemaker o un defibrillatore — che
# rende quella terapia sicura. Un divieto con l'86% di falsi blocchi non e' un
# presidio di sicurezza: e' un guasto che nega terapie.
#
# Il fatto mancante non e' un difetto di estrazione. `Z95.0 Presenza di
# dispositivi cardiaci elettronici` esiste nella terminologia, ma **nessuna
# delle tre pipeline lo estrae**, e per una ragione di progetto: un dispositivo
# non e' una malattia, e tutte e tre cercano diagnosi. Il filtro ha scoperto che
# lo strato di sicurezza ha bisogno di fatti che nessuno degli strati sotto era
# stato progettato per produrre.
PRINCIPIO_DEL_FATTO_MANCANTE = (
    "Regola declassata: la sua applicazione corretta richiede un fatto che "
    "nessuna pipeline estrae. Segnala, non vieta."
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
# Lo stato del paziente, ridotto a cio' che il filtro guarda
# ---------------------------------------------------------------------------

@dataclass
class StatoPerFiltro:
    """Cio' che il filtro legge di un paziente, gia' ripulito.

    E' costruito dallo stato prodotto dalle pipeline, e la costruzione applica
    l'unica regola che il grafo rende possibile e che un sistema ingenuo
    sbaglierebbe: **solo le condizioni affermate e del paziente** contano come
    controindicazioni.
    """

    enc_oid: int
    condizioni: list[dict]   # {codice, testo, agenti}
    allergie_atc: set[str]
    terapia_atc: set[str]

    @property
    def icd(self) -> set[str]:
        return {c["codice"] for c in self.condizioni if c["codice"]}


def _prefisso(codice: str, quanti: int) -> str:
    return codice[:quanti]


def stato_da_file(percorsi: dict[str, Path], enc_oid: int) -> StatoPerFiltro:
    """Costruisce lo stato leggendo le uscite delle pipeline.

    `percorsi` mappa la sigla della pipeline alla sua cartella. Le condizioni di
    pipeline diverse che portano lo stesso codice ICD sono **lo stesso fatto**,
    e il numero di pipeline che lo sostengono viene conservato: e' l'evidenza su
    cui poggia la regola di provenienza.
    """
    per_codice: dict[str, dict] = {}
    allergie: set[str] = set()
    terapia: set[str] = set()

    for sigla, cartella in percorsi.items():
        percorso = cartella / f"{enc_oid}.json"
        if not percorso.exists():
            continue
        stato = json.loads(percorso.read_text(encoding="utf-8"))

        for c in stato["condizioni"]:
            # LA riga che il grafo ha reso ovvia: una condizione negata non e'
            # una controindicazione, e quella di un familiare non e' nemmeno del
            # paziente. Senza questo filtro il sistema negherebbe un betabloccante
            # a chi ha il padre asmatico.
            if c["stato"] != "affermato" or c.get("soggetto", "paziente") != "paziente":
                continue
            if not c.get("codice"):
                continue
            voce = per_codice.setdefault(
                c["codice"], {"codice": c["codice"], "testo": c["testo_grezzo"],
                              "agenti": set()})
            voce["agenti"].add(sigla)

        for a in stato["allergie"]:
            if a.get("codice_atc"):
                allergie.add(a["codice_atc"])
        for f in stato["farmaci"]:
            if f.get("codice_atc") and f["stato"] == "affermato":
                terapia.add(f["codice_atc"])

    condizioni = [{**v, "agenti": sorted(v["agenti"])} for v in per_codice.values()]
    return StatoPerFiltro(enc_oid, condizioni, allergie, terapia)


# ---------------------------------------------------------------------------
# Il filtro
# ---------------------------------------------------------------------------

def valuta(stato: StatoPerFiltro, atc: str,
           regole: tuple[Controindicazione, ...] = REGOLE_CONTROINDICAZIONE,
           esclusa_dalla_terapia: str | None = None) -> Verdetto:
    """Il verdetto per un farmaco candidato.

    `esclusa_dalla_terapia` serve a valutare un farmaco che il paziente gia'
    assume senza che risulti duplicato di se stesso: e' il modo in cui si prova
    il filtro sulla terapia reale (vedi `main`).
    """
    verdetto = Verdetto(atc, Esito.AMMESSO)

    # --- 1. allergia ---------------------------------------------------
    if atc in stato.allergie_atc:
        verdetto.aggiungi(Esito.VIETATO, R_ALLERGIA_STESSA, allergene_atc=atc)
    else:
        gruppo = _prefisso(atc, 5)
        crociate = sorted(a for a in stato.allergie_atc
                          if len(a) >= 5 and _prefisso(a, 5) == gruppo and a != atc)
        if crociate:
            verdetto.aggiungi(Esito.DA_VERIFICARE, R_ALLERGIA_GRUPPO,
                              allergeni_atc=crociate, sottogruppo=gruppo)

    # --- 2. duplicazione -----------------------------------------------
    terapia = {t for t in stato.terapia_atc if t != esclusa_dalla_terapia}
    if atc in terapia:
        verdetto.aggiungi(Esito.DA_VERIFICARE, R_DUPLICATO_SOSTANZA, atc_in_terapia=atc)
    else:
        gruppo = _prefisso(atc, 5)
        simili = sorted(t for t in terapia
                        if len(t) >= 5 and _prefisso(t, 5) == gruppo)
        if simili:
            verdetto.aggiungi(Esito.DA_VERIFICARE, R_DUPLICATO_GRUPPO,
                              atc_in_terapia=simili, sottogruppo=gruppo)

    # --- 3. controindicazione per condizione ---------------------------
    for regola in regole:
        if not atc.startswith(regola.atc):
            continue
        colpite = [c for c in stato.condizioni
                   if c["codice"] and any(c["codice"].startswith(p) for p in regola.icd)]
        # Il fatto che revoca la controindicazione, se il paziente ce l'ha.
        revoca = [c for c in stato.condizioni
                  if c["codice"] and any(c["codice"].startswith(p)
                                         for p in regola.revocata_da)]
        if revoca:
            continue

        for c in colpite:
            # --- 4. la provenienza e i fatti mancanti modulano l'esito ---
            # Due ragioni indipendenti per non emettere un divieto:
            #
            # (a) il fatto che lo revocherebbe non e' estraibile — e' il
            #     PRINCIPIO_DEL_FATTO_MANCANTE, misurato: 12 blocchi su 14 erano
            #     pazienti con un pacemaker;
            # (b) la condizione e' vista dalla sola pipeline con la precisione
            #     piu' bassa. Un falso blocco fa danno quanto un falso permesso,
            #     quindi si declassa invece di insistere.
            solo_gazetteer = c["agenti"] == ["A"]
            declassa = regola.fatto_non_estratto is not None or solo_gazetteer
            esito = (Esito.DA_VERIFICARE
                     if declassa and regola.esito is Esito.VIETATO
                     else regola.esito)
            verdetto.aggiungi(
                esito,
                Regola(f"CONTROINDICAZIONE:{regola.atc}->{'|'.join(regola.icd)}",
                       regola.motivo, regola.fonte),
                condizione_icd=c["codice"], condizione=c["testo"],
                vista_da=c["agenti"],
                **({"declassata": PRINCIPIO_DEL_FATTO_MANCANTE,
                    "fatto_mancante": regola.fatto_non_estratto}
                   if regola.fatto_non_estratto and regola.esito is Esito.VIETATO
                   else {}),
            )
            if solo_gazetteer and regola.esito is Esito.VIETATO:
                verdetto.aggiungi(Esito.DA_VERIFICARE, R_PROVENIENZA_DEBOLE,
                                  condizione_icd=c["codice"], vista_da=c["agenti"])
    return verdetto


def main() -> None:
    """Prova il filtro sulla terapia che i cardiologi hanno davvero prescritto.

    E' la verifica piu' severa disponibile senza dati nuovi: la terapia alla
    dimissione e' cio' che un medico ha deciso per quel paziente. Un filtro che
    ne vieta una quota consistente **non ha trovato errori dei cardiologi**: ha
    un difetto proprio, e il confronto lo rende visibile senza bisogno di
    annotare nulla.
    """
    import argparse
    from collections import Counter

    argomenti = argparse.ArgumentParser(
        description="Step 8: prova il filtro di sicurezza sulla terapia reale.")
    argomenti.add_argument("--cartella-b", type=Path,
                           default=RADICE / "data" / "processed" / "pipeline_b_v3")
    argomenti.add_argument("--uscita", type=Path,
                           default=RADICE / "data" / "processed" / "filtro_step8.json")
    opzioni = argomenti.parse_args()

    percorsi = {
        "A": RADICE / "data" / "processed" / "pipeline_a",
        "B": opzioni.cartella_b,
        "C": RADICE / "data" / "processed" / "pipeline_c",
    }
    encs = sorted(int(p.stem) for p in percorsi["B"].glob("*.json")
                  if not p.stem.startswith("_"))

    esiti = Counter()
    per_regola = Counter()
    casi: list[dict] = []
    for enc in encs:
        stato = stato_da_file(percorsi, enc)
        stato_b = json.loads((percorsi["B"] / f"{enc}.json").read_text(encoding="utf-8"))
        dimissione = sorted({f["codice_atc"] for f in stato_b["farmaci"]
                             if f["codice_atc"] and f["momento"] == "dimissione"})
        for atc in dimissione:
            v = valuta(stato, atc, esclusa_dalla_terapia=atc)
            esiti[v.esito.value] += 1
            for m in v.motivi:
                per_regola[m["regola"]] += 1
            if v.esito is not Esito.AMMESSO:
                casi.append({"enc_oid": enc, "atc": atc, "esito": v.esito.value,
                             "motivi": v.motivi})

    totale = sum(esiti.values())
    print(f"FILTRO DI SICUREZZA — {len(encs)} ricoveri, {totale} prescrizioni di dimissione\n")
    for e in ("ammesso", "da_verificare", "vietato"):
        n = esiti[e]
        print(f"   {e:16} {n:6}  ({n/totale:5.2%})")
    print("\nregole che sono scattate:")
    for r, n in per_regola.most_common():
        print(f"   {n:5}  {r}")

    opzioni.uscita.write_text(
        json.dumps({"ricoveri": len(encs), "prescrizioni": totale,
                    "esiti": dict(esiti), "per_regola": dict(per_regola),
                    "casi": casi}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"\nDettaglio in {opzioni.uscita}")


if __name__ == "__main__":
    main()
