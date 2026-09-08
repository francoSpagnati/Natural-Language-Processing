"""Step 4 - Pipeline B: estrazione dello stato paziente con un modello linguistico.

Cosa fa il modello e cosa non fa
--------------------------------
Il modello riceve il referto e restituisce un elenco di menzioni: condizioni,
farmaci, allergie, ciascuna con il proprio stato clinico. **Non produce codici.**
ATC e ICD-10 vengono assegnati dopo, dagli stessi risolutori che usa la pipeline
A (`risolutori.py`), che poggiano su AIFA e sul volume ICD-10 italiano. Sono due
scelte di progetto, non un dettaglio implementativo:

* il vincolo di provenienza del progetto vieta che un codice nasca dalla
  conoscenza interna di un LLM, per quanto plausibile sembri;
* a normalizzazione identica, il confronto dello step 6 misura la sola
  differenza di *estrazione*, che e' cio' che si vuole confrontare.

Come si verifica che il modello non stia inventando
---------------------------------------------------
Ogni menzione deve riportare la porzione di referto da cui proviene, copiata
alla lettera. La pipeline la ricerca nel testo originale: se non la trova, la
menzione e' segnalata come non ancorata e l'entita' resta senza offset. E' un
rilevatore di allucinazioni automatico e quantificabile, e il suo tasso e' una
delle metriche riportate allo step 6.

Costo e riproducibilita'
------------------------
Ogni chiamata passa dalla cache su disco di `llm_backend`: una seconda
esecuzione sugli stessi record non consuma quota e restituisce esattamente gli
stessi risultati, il che rende ripetibile la valutazione dello step 11.
"""

from __future__ import annotations

import argparse
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from data_loading import RecordPaziente, carica_dataset
from gazetteer import GazetteerClinico
from llm_backend import (
    BackendGemini,
    BackendLLM,
    BackendOllama,
    ErroreLLM,
    ErroreQuotaGiornaliera,
    Richiesta,
)
from risolutori import RisolutoreATC, RisolutoreICD
from schema import (
    AllergiaEstratta,
    CampoReferto,
    CondizioneEstratta,
    EstrazioneLLM,
    FarmacoEstratto,
    MomentoTerapia,
    Pipeline,
    Provenienza,
    StatoConoscenza,
    StatoNormalizzazione,
    StatoPaziente,
    schema_estrazione_llm,
)

RADICE = Path(__file__).resolve().parent.parent
PERCORSO_DATASET = RADICE / "data" / "raw" / "anamnesiterapie.txt"
CARTELLA_USCITA = RADICE / "data" / "processed" / "pipeline_b"

# Il campo dichiarato dal modello determina il momento della terapia: dedurlo
# dalla struttura del record invece di chiederlo elimina una possibile
# incoerenza fra i due valori.
MOMENTO_PER_CAMPO = {
    CampoReferto.ANAMNESI: MomentoTerapia.NARRATIVO,
    CampoReferto.TERAPIA_INGRESSO: MomentoTerapia.INGRESSO,
    CampoReferto.TERAPIA_DIMISSIONE: MomentoTerapia.DIMISSIONE,
}


ISTRUZIONI = """\
Estrai le entita' cliniche dai referti di un ricovero cardiologico italiano.

REGOLA 1 - LO STATO VA NEL CAMPO `stato`, MAI NEL TESTO
Quando il referto nega o mette in dubbio qualcosa, questo si registra nel campo
`stato`. Non si scrive mai la negazione dentro `concetto`.

  "Non noto distiroidismo"  ->  concetto "distiroidismo",  stato "negato"
  "no diabete"              ->  concetto "diabete mellito", stato "negato"
  "nega iperuricemia"       ->  concetto "iperuricemia",   stato "negato"
  "sospetta angina"         ->  concetto "angina",         stato "incerto"

  SBAGLIATO: concetto "non diabete" con stato "affermato".

Una negazione copre tutto l'elenco che la segue: in "Nega diabete, ipertensione
e dislipidemia" sono negate tutte e tre.

REGOLA 2 - COSA E' UNA CONDIZIONE
Solo diagnosi, patologie e fattori di rischio del paziente.

  SI:  ipertensione arteriosa, fibrillazione atriale, BPCO, diabete, obesita',
       fumo, stenosi aortica, insufficienza renale cronica
  NO:  stato civile, professione, valori di laboratorio ("108 glicemia"),
       esami e referti strumentali ("ecocardiogramma normale", "coro-CT"),
       ricoveri e visite, terapie, "asintomatico", "alvo regolare"

REGOLA 3 - NIENTE FAMILIARITA'
Cio' che il referto attribuisce a un familiare non e' una condizione del
paziente. "Familiarita' per ipertensione" e "il padre e' cardiopatico" non
vanno elencati.

REGOLA 4 - UNA VOLTA SOLA
Se la stessa condizione compare piu' volte nel referto, elencala una volta
sola. "Ipertensione arteriosa essenziale" e "ipertensione da 15 aa" sono la
stessa condizione.

REGOLA 5 - CITAZIONE ALLA LETTERA
`testo_grezzo` (per le allergie `allergene`) e' una porzione del referto
copiata carattere per carattere: stessa grafia, stesse abbreviazioni, stessi
errori di battitura. Serve a ritrovare la menzione nel testo, quindi non
correggerla e non tradurla. Cita la menzione, non la frase intera.

REGOLA 6 - CONCETTO ESTESO
In `concetto` scrivi lo stesso termine in forma estesa e standard, con gli
acronimi sciolti:

  "BPCO" -> "broncopneumopatia cronica ostruttiva"
  "FA"   -> "fibrillazione atriale"
  "IRC"  -> "insufficienza renale cronica"
  "OSAS" -> "sindrome delle apnee ostruttive del sonno"

Se il referto usa gia' la forma estesa, ripetila identica.

REGOLA 7 - FARMACI
Elenca ogni farmaco separatamente, anche dentro un elenco di terapia. In
`posologia` riporta dose e frequenza come sono scritte. Le condizioni pregresse
o risolte restano "affermato": fanno parte della storia clinica.

REGOLA 8 - NON DEDURRE
Non aggiungere il farmaco che tratterebbe una condizione presente, ne' la
condizione che giustificherebbe un farmaco. Solo cio' che e' scritto. Se un
campo non contiene entita', lascia la lista vuota.
"""


def componi_testo(record: RecordPaziente) -> str:
    """Assembla i referti del record marcandone i confini.

    I nomi delle sezioni coincidono con i valori ammessi per `campo`: il modello
    non deve inventare un'etichetta, deve ricopiare quella sotto cui sta
    leggendo.
    """
    sezioni = [
        (CampoReferto.ANAMNESI, record.testo_anamnesi),
        (CampoReferto.TERAPIA_INGRESSO, record.testo_terapia_ingresso),
        (CampoReferto.TERAPIA_DIMISSIONE, record.testo_terapia_dimissione),
    ]
    parti = [
        f"### {campo.value}\n{(testo or '').strip()}"
        for campo, testo in sezioni
        if testo and testo.strip()
    ]
    return "\n\n".join(parti)


def _testo_del_campo(record: RecordPaziente, campo: CampoReferto) -> str:
    return {
        CampoReferto.ANAMNESI: record.testo_anamnesi,
        CampoReferto.TERAPIA_INGRESSO: record.testo_terapia_ingresso,
        CampoReferto.TERAPIA_DIMISSIONE: record.testo_terapia_dimissione,
    }[campo] or ""


def ancora(testo_campo: str, citazione: str) -> tuple[int | None, int | None]:
    """Posizione della citazione nel campo di origine.

    Prima si cerca la corrispondenza esatta; se fallisce si riprova ignorando
    maiuscole e minuscole, perche' e' l'unica differenza che il modello introduce
    con qualche regolarita' e non intacca l'identita' della menzione. Ogni altra
    difformita' lascia la menzione senza ancoraggio, e questo viene contato.
    """
    citazione = citazione.strip()
    if not citazione or not testo_campo:
        return None, None
    posizione = testo_campo.find(citazione)
    if posizione < 0:
        posizione = testo_campo.lower().find(citazione.lower())
    if posizione < 0:
        return None, None
    return posizione, posizione + len(citazione)


def _provenienza(
    record: RecordPaziente, campo: CampoReferto, citazione: str, regola: str
) -> tuple[Provenienza, bool]:
    """Provenienza dell'entita' e indicazione se la citazione e' stata ritrovata."""
    inizio, fine = ancora(_testo_del_campo(record, campo), citazione)
    ancorata = inizio is not None
    return (
        Provenienza(
            pipeline=Pipeline.B_LLM,
            campo_sorgente=campo.value,
            testo_originale=citazione,
            inizio=inizio,
            fine=fine,
            regola=regola if ancorata else f"{regola} [citazione non ritrovata nel referto]",
        ),
        ancorata,
    )


def converti(
    record: RecordPaziente,
    estrazione: EstrazioneLLM,
    modello: str,
    risolutore_atc: RisolutoreATC,
    risolutore_icd: RisolutoreICD,
) -> StatoPaziente:
    """Traduce l'uscita del modello nello schema comune, normalizzando i codici."""
    regola = f"llm:{modello}"
    non_ancorate = 0

    condizioni: list[CondizioneEstratta] = []
    for voce in estrazione.condizioni:
        # L'espansione proposta dal modello resta sempre nella regola, anche
        # quando il risolutore aggancia un termine diverso: e' un dato prodotto
        # dalla pipeline e deve restare ispezionabile, non essere sovrascritto
        # dall'esito della normalizzazione.
        # Si tenta prima il concetto esteso e poi la citazione letterale: la
        # forma estesa e' quella che ha qualche possibilita' di comparire
        # nell'indice ICD, il letterale e' il ripiego quando l'espansione
        # allontana dal lessico del volume.
        esito = risolutore_icd.risolvi(voce.concetto)
        if esito.stato is StatoNormalizzazione.NIL:
            esito = risolutore_icd.risolvi(voce.testo_grezzo)
        provenienza, ancorata = _provenienza(
            record,
            voce.campo,
            voce.testo_grezzo,
            f"{regola} concetto='{voce.concetto}' icd:{esito.metodo}",
        )
        non_ancorate += not ancorata
        condizioni.append(
            CondizioneEstratta(
                testo_grezzo=voce.testo_grezzo,
                concetto=esito.concetto or voce.concetto,
                codice=esito.codice,
                sistema_codifica="ICD-10" if esito.codice else None,
                stato_normalizzazione=esito.stato,
                stato=voce.stato,
                provenienza=provenienza,
            )
        )

    farmaci: list[FarmacoEstratto] = []
    for voce in estrazione.farmaci:
        # La menzione puo' essere composta ("Furosemide (Lasix cpr. 25 mg)"):
        # `risolvi_menzione` la scompone e dice quale forma ha risolto, che
        # finisce nella regola perche' la provenienza resti veritiera.
        codice, stato_norm, fonte, forma = risolutore_atc.risolvi_menzione(voce.testo_grezzo)
        regola_farmaco = regola if forma == voce.testo_grezzo.strip() else f"{regola} forma='{forma}'"
        provenienza, ancorata = _provenienza(
            record, voce.campo, voce.testo_grezzo, regola_farmaco
        )
        non_ancorate += not ancorata
        farmaci.append(
            FarmacoEstratto(
                nome_grezzo=voce.testo_grezzo,
                codice_atc=codice,
                stato_normalizzazione=stato_norm,
                fonte_normalizzazione=fonte,
                momento=MOMENTO_PER_CAMPO[voce.campo],
                stato=voce.stato,
                posologia=voce.posologia,
                provenienza=provenienza,
            )
        )

    allergie: list[AllergiaEstratta] = []
    for voce in estrazione.allergie:
        provenienza, ancorata = _provenienza(
            record, CampoReferto.ANAMNESI, voce.allergene, regola
        )
        non_ancorate += not ancorata
        codice, stato_norm, _ = risolutore_atc.risolvi(voce.allergene)
        allergie.append(
            AllergiaEstratta(
                allergene=voce.allergene,
                categoria=voce.categoria,
                codice_atc=codice,
                stato_normalizzazione=stato_norm,
                provenienza=provenienza,
            )
        )

    note: list[str] = []
    if non_ancorate:
        note.append(f"{non_ancorate} menzioni non ritrovate alla lettera nel referto")
    if not record.ha_terapia_dimissione:
        note.append("referto di dimissione assente: record non utilizzabile come ground truth")

    return StatoPaziente(
        enc_oid=record.enc_oid,
        pipeline=Pipeline.B_LLM,
        condizioni=condizioni,
        farmaci=farmaci,
        allergie=allergie,
        stato_sezione_allergie=estrazione.stato_sezione_allergie,
        testo_supporto=record.testo_anamnesi,
        note_estrazione=note,
    )


def estrai(
    record: RecordPaziente,
    backend: BackendLLM,
    risolutore_atc: RisolutoreATC,
    risolutore_icd: RisolutoreICD,
    livello_ragionamento: str = "low",
) -> tuple[StatoPaziente, object]:
    """Estrae lo stato paziente di un record. Restituisce anche la risposta grezza."""
    richiesta = Richiesta(
        istruzioni=ISTRUZIONI,
        testo=componi_testo(record),
        schema=schema_estrazione_llm(),
        livello_ragionamento=livello_ragionamento,
    )
    risposta = backend.genera(richiesta)
    # La validazione Pydantic e' la seconda rete: lo schema vincola la
    # generazione, ma un enum fuori posto o un campo assente devono comunque
    # fallire qui e non propagarsi nello stato paziente.
    estrazione = EstrazioneLLM.model_validate(risposta.contenuto)
    stato = converti(record, estrazione, risposta.modello, risolutore_atc, risolutore_icd)
    return stato, risposta


# ---------------------------------------------------------------------------
# Esecuzione su un insieme di record
# ---------------------------------------------------------------------------


def scegli_record(record: list[RecordPaziente], quanti: int | None, seme: int):
    """Sottoinsieme casuale ma riproducibile, per contenere il consumo di quota."""
    if quanti is None or quanti >= len(record):
        return record
    generatore = random.Random(seme)
    return sorted(generatore.sample(record, quanti), key=lambda r: r.enc_oid)


def _elabora(rec, backend, risolutore_atc, risolutore_icd, ragionamento, interruzione):
    """Un record, in un thread. Restituisce l'errore invece di sollevarlo.

    Un record che fallisce non deve fermare gli altri: viene contato, segnalato
    e la corsa prosegue. Con la cache, rilanciare il comando ritenta solo quelli.

    L'esaurimento della quota giornaliera fa eccezione: da quel momento ogni
    altra richiesta e' destinata a fallire, quindi alza `interruzione` e i
    record ancora in coda vengono saltati senza chiamare l'API. Cosi' la corsa
    si ferma in pochi secondi invece di consumare minuti in errori annunciati.
    """
    if interruzione.is_set():
        return rec, None, None, None
    try:
        stato, risposta = estrai(rec, backend, risolutore_atc, risolutore_icd, ragionamento)
        return rec, stato, risposta, None
    except ErroreQuotaGiornaliera as errore:
        interruzione.set()
        return rec, None, None, errore
    except (ErroreLLM, ValueError) as errore:
        return rec, None, None, errore


def main() -> None:
    argomenti = argparse.ArgumentParser(description="Pipeline B: estrazione con LLM.")
    argomenti.add_argument(
        "--motore",
        default="locale",
        choices=["locale", "gemini"],
        help="Dove gira il modello. 'locale' usa Ollama sulla macchina; 'gemini' "
        "usa Google AI Studio, che sul piano gratuito concede 20 richieste al "
        "giorno per modello.",
    )
    argomenti.add_argument(
        "--modello", default=None, help="Modello da usare, se diverso dal predefinito del motore."
    )
    argomenti.add_argument(
        "--record", type=int, default=None, help="Numero di record da elaborare."
    )
    argomenti.add_argument("--seme", type=int, default=20260904, help="Seme del campionamento.")
    argomenti.add_argument(
        "--ragionamento", default="low", choices=["low", "high"], help="Livello di ragionamento."
    )
    argomenti.add_argument(
        "--parallele",
        type=int,
        default=None,
        help="Richieste contemporanee. Predefinito 8 sul motore remoto, dove il "
        "tempo e' attesa di rete; 1 sul motore locale, dove e' calcolo e "
        "parallelizzare non aggiunge nulla se non consumo di memoria.",
    )
    opzioni = argomenti.parse_args()

    record, _ = carica_dataset(PERCORSO_DATASET)
    selezione = scegli_record(record, opzioni.record, opzioni.seme)
    parallele = opzioni.parallele or (1 if opzioni.motore == "locale" else 8)

    classe = BackendOllama if opzioni.motore == "locale" else BackendGemini
    backend = classe(**({"modello": opzioni.modello} if opzioni.modello else {}))
    risolutore_atc = RisolutoreATC()
    # Stesso gazetteer della pipeline A: la normalizzazione deve essere
    # identica nelle due pipeline, altrimenti il confronto dello step 6
    # misurerebbe anche la differenza di risoluzione dei codici.
    risolutore_icd = RisolutoreICD(gazetteer=GazetteerClinico())

    CARTELLA_USCITA.mkdir(parents=True, exist_ok=True)
    print(
        f"Pipeline B su {len(selezione)} record con {backend.modello}, "
        f"{parallele} richieste in parallelo."
    )

    totali = {"condizioni": 0, "farmaci": 0, "allergie": 0, "menzioni_non_ancorate": 0}
    token = {"ingresso": 0, "uscita": 0, "ragionamento": 0}
    da_cache = falliti = ritentati = saltati = 0
    interruzione = threading.Event()
    avvio = time.monotonic()

    with ThreadPoolExecutor(max_workers=parallele) as pool:
        futuri = [
            pool.submit(
                _elabora,
                rec,
                backend,
                risolutore_atc,
                risolutore_icd,
                opzioni.ragionamento,
                interruzione,
            )
            for rec in selezione
        ]
        for indice, futuro in enumerate(as_completed(futuri), start=1):
            rec, stato, risposta, errore = futuro.result()
            if stato is None:
                if errore is None:
                    saltati += 1
                else:
                    falliti += 1
                    print(f"  [{rec.enc_oid}] fallito: {errore}", file=sys.stderr)
                continue

            (CARTELLA_USCITA / f"{rec.enc_oid}.json").write_text(
                stato.model_dump_json(indent=2), encoding="utf-8"
            )
            totali["condizioni"] += len(stato.condizioni)
            totali["farmaci"] += len(stato.farmaci)
            totali["allergie"] += len(stato.allergie)
            totali["menzioni_non_ancorate"] += sum(
                int(nota.split(maxsplit=1)[0])
                for nota in stato.note_estrazione
                if "non ritrovate" in nota
            )
            token["ingresso"] += risposta.token_ingresso
            token["uscita"] += risposta.token_uscita
            token["ragionamento"] += risposta.token_ragionamento
            da_cache += risposta.da_cache
            ritentati += risposta.tentativi > 1

            if indice % 25 == 0 or indice == len(selezione):
                trascorso = time.monotonic() - avvio
                print(f"  {indice}/{len(selezione)} record ({trascorso:.0f}s)", flush=True)

    durata = time.monotonic() - avvio
    riusciti = len(selezione) - falliti - saltati
    menzioni = totali["condizioni"] + totali["farmaci"] + totali["allergie"]
    print(
        f"\nCompletati {riusciti}/{len(selezione)} record in {durata:.0f}s "
        f"({da_cache} da cache, {ritentati} con ritentativi, {falliti} falliti)."
    )
    if interruzione.is_set():
        print(
            f"Corsa interrotta: quota giornaliera esaurita per {backend.modello}. "
            f"{saltati} record non tentati. I risultati gia' ottenuti sono in cache: "
            f"rilanciando lo stesso comando non verranno richiesti di nuovo.",
            file=sys.stderr,
        )
    print(
        f"Entita': {totali['condizioni']} condizioni, {totali['farmaci']} farmaci, "
        f"{totali['allergie']} allergie."
    )
    if menzioni:
        quota = 100 * totali["menzioni_non_ancorate"] / menzioni
        print(
            f"Menzioni non ritrovate alla lettera nel referto: "
            f"{totali['menzioni_non_ancorate']}/{menzioni} ({quota:.2f}%)."
        )
    print(
        f"Token: {token['ingresso']} in ingresso, {token['uscita']} in uscita, "
        f"{token['ragionamento']} di ragionamento."
    )
    print(f"Uscita in {CARTELLA_USCITA.relative_to(RADICE)}/")


if __name__ == "__main__":
    main()
