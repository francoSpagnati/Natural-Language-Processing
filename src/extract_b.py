"""Step 4 - Pipeline B: estrazione dello stato paziente con un modello linguistico.

Il modello riceve la sola anamnesi e restituisce menzioni (condizioni, farmaci,
allergie) citate alla lettera, mai codici: ATC e ICD-10 li assegnano i
risolutori della pipeline A. La citazione viene cercata nel testo: se non c'e',
la menzione e' «non ancorata» (rilevatore di allucinazioni). I campi di terapia
li legge il parser deterministico, come in A e C. Ogni chiamata passa dalla
cache su disco. Scelte e misure: docs/04_pipeline_estrazione_B.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import threading
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from data_loading import RecordPaziente, carica_dataset
from extract_a import farmaci_da_campo_strutturato
from gazetteer import GazetteerClinico
from llm_backend import (
    BackendGemini,
    BackendOpenRouter,
    BackendLLM,
    BackendOllama,
    ErroreLLM,
    ErroreQuotaGiornaliera,
    Richiesta,
)
from risolutori import RisolutoreATC, RisolutoreICD, soggetto_della_menzione
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
# Registro della corsa: per riprendere, e per non mescolare configurazioni.
NOME_REGISTRO = "_corsa.json"
NOME_RIEPILOGO = "_riepilogo.json"

# Il momento della terapia si deduce dal campo, non si chiede al modello.
MOMENTO_PER_CAMPO = {
    CampoReferto.ANAMNESI: MomentoTerapia.NARRATIVO,
    CampoReferto.TERAPIA_INGRESSO: MomentoTerapia.INGRESSO,
    CampoReferto.TERAPIA_DIMISSIONE: MomentoTerapia.DIMISSIONE,
}


ISTRUZIONI = """\
Estrai le entita' cliniche dall'anamnesi di un ricovero cardiologico italiano.

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
Solo diagnosi, patologie e fattori di rischio del paziente. Una condizione ha un
nome: se non sapresti dirlo a un altro medico in due parole, non e' una
condizione.

  SI:  diabete, stenosi aortica, ipertensione arteriosa, obesita', BPCO,
       insufficienza renale cronica, fumo, fibrillazione atriale
  NO:  stato civile, professione, valori di laboratorio ("108 glicemia"),
       esami e referti strumentali ("ecocardiogramma normale", "coro-CT"),
       ricoveri e visite, terapie, "asintomatico", "alvo regolare"

NON spezzare la narrazione in condizioni. Un frammento di frase non e' una
diagnosi, anche se descrive qualcosa di clinico.

  SBAGLIATO: "con lenta risoluzione" con concetto "risoluzione lenta"
  SBAGLIATO: "dimesso con ossigenoterapia a basso flusso"
             con concetto "ossigenoterapia a basso flusso"
  SBAGLIATO: "nel 2024 accesso in pronto soccorso con riscontro di
             insufficienza respiratoria acuta"
  GIUSTO:    da quella stessa frase, "insufficienza respiratoria acuta"

Un referto lungo non contiene piu' diagnosi di uno corto: contiene piu' racconto.
Un'anamnesi tipica ha fra le cinque e le venticinque condizioni. Se ne stai
elencando molte di piu', stai estraendo narrazione.

CRITERIO OPERATIVO: `testo_grezzo` di una condizione e' quasi sempre di UNA-CINQUE
PAROLE. Se stai per scrivere una frase con un verbo, una data o un valore
numerico, non e' una condizione.

  SBAGLIATO: "in reparto la FA e' stata cardiovertita"
  GIUSTO:    "FA"

  SBAGLIATO: "eseguito studio elettrofisiologico con esito nei limiti"
  GIUSTO:    niente, e' il risultato di un esame

  SBAGLIATO: "anticoagulante non prescritto, da rivalutare al controllo"
  GIUSTO:    niente, e' una decisione terapeutica

  SBAGLIATO: "RM encefalo con aree di alterato segnale da gliosi"
  GIUSTO:    "gliosi"

REGOLA 3 - FAMILIARITA'
Elenca anche le condizioni che il referto attribuisce a un familiare
("Familiarita' per ipertensione"): a distinguere il paziente dai suoi parenti ci
pensa la pipeline, che lo calcola sul testo. Metti in `testo_grezzo` la
citazione completa, marcatore compreso.

  GIUSTO: testo_grezzo "Familiarita' per cardiopatia ischemica (padre)"
          concetto "cardiopatia ischemica", stato "affermato"

Lo `stato` descrive l'affermazione cosi' com'e': "familiarita' per X" e'
affermata, "familiarita' negativa per X" e' negata.

REGOLA 4 - UNA VOLTA SOLA
Se la stessa condizione compare piu' volte nel referto, elencala una volta
sola. "Ipertensione arteriosa essenziale" e "ipertensione da 15 aa" sono la
stessa condizione. Non ripetere mai due volte lo stesso oggetto identico.

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

REGOLA 7 - FARMACI: SOLO QUELLI CHE L'ANAMNESI RACCONTA
Riceverai **solo l'anamnesi**, non gli elenchi di terapia. Quegli elenchi sono
gia' letti da un parser che non sbaglia, quindi non e' tuo compito ricostruirli:
il tuo compito e' cio' che un elenco non puo' contenere.

Un elenco di terapia dice che cosa il paziente assume ADESSO. L'anamnesi dice
che cosa ha assunto, perche' ha smesso, che cosa non ha tollerato e che cosa
ha rifiutato. **Questa e' l'unica informazione sui farmaci che ti si chiede.**

Elenca un farmaco quando l'anamnesi gli attribuisce un FATTO:
  - e' stato sospeso, ridotto, interrotto, scalato;
  - non e' tollerato, ha dato una reazione o un'allergia;
  - ha causato un evento (emorragia, effetto collaterale, complicanza);
  - il paziente lo rifiuta o non lo assume;
  - e' stato assunto in passato e ora non piu'.

  SBAGLIATO: ricopiare nella lista un farmaco solo perche' e' nominato
  SBAGLIATO: dedurre il farmaco dalla condizione che tratterebbe
  SBAGLIATO: elencare un farmaco senza che l'anamnesi dica nulla di lui

Il fatto va nel campo `stato` quando e' una negazione o un dubbio; il nome va in
`testo_grezzo` copiato come e' scritto, refusi compresi, senza correggerlo.

Un farmaco nominato come allergene va in `allergie` secondo la REGOLA 9 **e**
in `farmaci`: e' la stessa sostanza vista da due lati.

Se l'anamnesi non racconta nulla di alcun farmaco, la lista va **vuota**. E'
il caso piu' frequente, e una lista vuota e' la risposta giusta.

REGOLA 8 - NON DEDURRE
Non aggiungere il farmaco che tratterebbe una condizione presente, ne' la
condizione che giustificherebbe un farmaco. Solo cio' che e' scritto. Se un
campo non contiene entita', lascia la lista vuota.

REGOLA 9 - ALLERGIE: SOLO SE IL REFERTO LE NOMINA
Un'allergia va elencata **solo** se il referto dice che il paziente e' allergico
o intollerante a qualcosa. Cerca le parole: "allergia", "allergico",
"intolleranza", "reazione a", "anafilassi".

Trovata una di quelle parole, guarda che cosa la segue, perche' la parola da
sola non basta:
  - se il referto nomina la sostanza, copiala in `allergene` **esattamente come
    e' scritta nel referto**, senza abbreviarla e senza espanderla;
  - se il referto dice che le allergie non sono note, o che non ne sono
    riferite, la lista va **vuota**. La parola c'e', l'allergia no.

Un farmaco che il paziente **assume** non e' un'allergia: e' l'esatto
contrario.

  SBAGLIATO: allergene "Bisoprololo" preso da un referto che di allergie
             non parla, solo perche' il paziente lo assume

Se il referto non nomina allergie, lascia la lista **vuota** e metti
`stato_sezione_allergie` a "ignoto". Non metterla ad "affermato" per una lista
che hai costruito da altro.

`allergene` deve essere una stringa che TU HAI LETTO nel referto. Se non riesci a
indicare il punto esatto in cui compare, quell'allergia non va elencata. Non
aggiungere le allergie tipiche di un cardiopatico perche' sono plausibili: una
sostanza che questo referto non nomina non va scritta, per quanto sia attesa.

In `categoria` va una fra "principi attivi", "alimenti", "altro": non il nome
della sostanza e non il nome del campo.
"""


def componi_testo(record: RecordPaziente) -> str:
    """Il testo inviato al modello: la sola anamnesi.

    I campi di terapia sono liste con delimitatori: il parser li legge al 100%,
    il modello al 99,3% pagando (docs/04). Al modello resta la prosa.
    """
    return (record.testo_anamnesi or "").strip()


def campo_del_modello(dichiarato: CampoReferto) -> CampoReferto:
    """Il campo di una menzione del modello e' sempre l'anamnesi: e' l'unico testo che riceve."""
    return CampoReferto.ANAMNESI


def _testo_del_campo(record: RecordPaziente, campo: CampoReferto) -> str:
    return {
        CampoReferto.ANAMNESI: record.testo_anamnesi,
        CampoReferto.TERAPIA_INGRESSO: record.testo_terapia_ingresso,
        CampoReferto.TERAPIA_DIMISSIONE: record.testo_terapia_dimissione,
    }[campo] or ""


def ancora(testo_campo: str, citazione: str) -> tuple[int | None, int | None]:
    """Posizione della citazione nel campo: esatta, poi senza maiuscole; altrimenti non ancorata."""
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
        voce.campo = campo_del_modello(voce.campo)
        # Prima il concetto esteso, poi la citazione letterale; l'espansione
        # resta nella regola per ispezione.
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
        # Il soggetto si calcola sul testo con la regola comune alle tre pipeline.
        soggetto, nota_soggetto = soggetto_della_menzione(
            _testo_del_campo(record, voce.campo) or "",
            provenienza.inizio,
            provenienza.fine,
        )
        if nota_soggetto:
            provenienza = provenienza.model_copy(
                update={"regola": f"{provenienza.regola} {nota_soggetto}"}
            )
        condizioni.append(
            CondizioneEstratta(
                testo_grezzo=voce.testo_grezzo,
                concetto=esito.concetto or voce.concetto,
                codice=esito.codice,
                sistema_codifica="ICD-10" if esito.codice else None,
                stato_normalizzazione=esito.stato,
                stato=voce.stato,
                soggetto=soggetto,
                provenienza=provenienza,
            )
        )

    farmaci: list[FarmacoEstratto] = []
    for voce in estrazione.farmaci:
        voce.campo = campo_del_modello(voce.campo)
        # Menzione composta ("Furosemide (Lasix cpr. 25 mg)"): la forma risolta va nella regola.
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
        voce.campo = campo_del_modello(voce.campo)
        provenienza, ancorata = _provenienza(
            record, voce.campo, voce.allergene, regola
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

    # I campi di terapia li legge il parser deterministico, come in A e C.
    farmaci = farmaci_da_campo_strutturato(record, risolutore_atc) + farmaci

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
    # Seconda rete: la validazione Pydantic dopo il vincolo di generazione.
    estrazione = EstrazioneLLM.model_validate(risposta.contenuto)
    stato = converti(record, estrazione, risposta.modello, risolutore_atc, risolutore_icd)
    return stato, risposta


# --- Esecuzione su un insieme di record ---


def scegli_record(record: list[RecordPaziente], quanti: int | None, seme: int,
                  solo: list[int] | None = None):
    """Sottoinsieme riproducibile; `solo` seleziona per identificativo (esperimenti mirati)."""
    if solo:
        voluti = set(solo)
        scelti = [r for r in record if r.enc_oid in voluti]
        mancanti = voluti - {r.enc_oid for r in scelti}
        if mancanti:
            sys.exit(f"Record assenti dal dataset: {sorted(mancanti)}")
        return sorted(scelti, key=lambda r: r.enc_oid)
    if quanti is None or quanti >= len(record):
        return record
    generatore = random.Random(seme)
    return sorted(generatore.sample(record, quanti), key=lambda r: r.enc_oid)


def _ragionamento_effettivo(backend, opzioni) -> str:
    """Il livello di ragionamento che arriva davvero al modello."""
    valore = getattr(backend, "ragionamento", None)
    if valore is None:  # backend remoto: il livello viaggia nella richiesta
        return opzioni.ragionamento
    return valore if isinstance(valore, str) else ("no" if not valore else "low")


def impronta_configurazione(backend, opzioni, schema: dict) -> dict:
    """Tutto cio' che, cambiando, renderebbe i risultati di una cartella non confrontabili."""
    def breve(testo: str) -> str:
        return hashlib.sha256(testo.encode("utf-8")).hexdigest()[:16]

    return {
        "motore": opzioni.motore,
        "modello": backend.modello,
        # Si legge dal backend, non dalle opzioni: e' cio' che raggiunge davvero
        # il modello, e l'impronta deve descrivere la corsa, non l'intenzione.
        "ragionamento": _ragionamento_effettivo(backend, opzioni),
        "seme": opzioni.seme,
        "record_richiesti": opzioni.record,
        # Una corsa mirata non e' confrontabile con una campionata: l'impronta lo dice.
        "record_scelti": sorted(opzioni.solo) if getattr(opzioni, "solo", None) else None,
        "impronta_istruzioni": breve(ISTRUZIONI),
        "impronta_schema": breve(json.dumps(schema, sort_keys=True, ensure_ascii=False)),
    }


def prepara_cartella(cartella, configurazione: dict, rifai: bool) -> None:
    """Cartella vuota: si parte; registro compatibile: si riprende; altrimenti ci si ferma."""
    cartella.mkdir(parents=True, exist_ok=True)
    registro = cartella / NOME_REGISTRO
    prodotti = [f for f in cartella.glob("*.json") if not f.name.startswith("_")]

    if rifai:
        for percorso in prodotti:
            percorso.unlink()
        registro.unlink(missing_ok=True)
        (cartella / NOME_RIEPILOGO).unlink(missing_ok=True)
        print(f"  --rifai: rimossi {len(prodotti)} risultati precedenti.")
        prodotti = []

    if registro.exists():
        precedente = json.loads(registro.read_text(encoding="utf-8")).get("configurazione", {})
        differenze = [
            f"{k}: {precedente.get(k)!r} -> {v!r}"
            for k, v in configurazione.items()
            if precedente.get(k) != v
        ]
        if differenze:
            raise SystemExit(
                "La cartella contiene una corsa con una configurazione diversa:\n  "
                + "\n  ".join(differenze)
                + f"\n\nRiprendere mescolerebbe risultati non confrontabili. Usa --rifai "
                f"per ricominciare, oppure --uscita per una cartella nuova."
            )
    elif prodotti:
        raise SystemExit(
            f"{len(prodotti)} risultati sono gia' presenti in {cartella} ma senza registro "
            f"di corsa: non e' possibile sapere con quale configurazione siano stati "
            f"prodotti.\nUsa --rifai per ricominciare, oppure --uscita per una cartella nuova."
        )


def salva_registro(cartella, configurazione: dict, fatti: int, totale: int) -> None:
    """Scrive lo stato della corsa. Chiamata di continuo: deve restare economica."""
    (cartella / NOME_REGISTRO).write_text(
        json.dumps(
            {
                "configurazione": configurazione,
                "record_totali": totale,
                "record_completati": fatti,
                "aggiornato_il": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _elabora(rec, backend, risolutore_atc, risolutore_icd, ragionamento, interruzione):
    """Un record, in un thread: restituisce l'errore invece di sollevarlo. La quota esaurita alza `interruzione`."""
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
        choices=["locale", "gemini", "openrouter"],
        help="Dove gira il modello. 'locale' usa Ollama sulla macchina; 'gemini' "
        "usa Google AI Studio, che sul piano gratuito concede 20 richieste al "
        "giorno per modello; 'openrouter' usa OpenRouter a consumo, con la "
        "decodifica vincolata allo schema (richiede OPENROUTER_API_KEY).",
    )
    argomenti.add_argument(
        "--modello", default=None, help="Modello da usare, se diverso dal predefinito del motore."
    )
    argomenti.add_argument(
        "--record", type=int, default=None, help="Numero di record da elaborare."
    )
    argomenti.add_argument("--seme", type=int, default=20260904, help="Seme del campionamento.")
    argomenti.add_argument(
        "--solo",
        type=int,
        nargs="+",
        default=None,
        help="Elabora solo questi enc_oid, invece di campionarli. Serve a "
        "provare una modifica su un insieme noto — per esempio i referti del "
        "riferimento annotato — senza rifare il corpus.",
    )
    argomenti.add_argument(
        "--ragionamento",
        default="no",
        choices=["no", "low", "high"],
        help="Livello di ragionamento ('no' lo disattiva).",
    )
    argomenti.add_argument(
        "--parallele",
        type=int,
        default=None,
        help="Richieste contemporanee. Predefinito 8 sul motore remoto, dove il "
        "tempo e' attesa di rete; 1 sul motore locale, dove e' calcolo e "
        "parallelizzare non aggiunge nulla se non consumo di memoria.",
    )
    argomenti.add_argument(
        "--uscita", type=Path, default=CARTELLA_USCITA, help="Cartella dei risultati."
    )
    argomenti.add_argument(
        "--rifai",
        action="store_true",
        help="Cancella i risultati precedenti e ricomincia da zero invece di riprendere.",
    )
    opzioni = argomenti.parse_args()

    record, _ = carica_dataset(PERCORSO_DATASET)
    selezione = scegli_record(record, opzioni.record, opzioni.seme, opzioni.solo)
    parallele = opzioni.parallele or (1 if opzioni.motore == "locale" else 8)

    classe = {
        "locale": BackendOllama,
        "gemini": BackendGemini,
        "openrouter": BackendOpenRouter,
    }[opzioni.motore]
    argomenti_backend: dict = {}
    if opzioni.modello:
        argomenti_backend["modello"] = opzioni.modello
    # Gemini riceve il livello di ragionamento dentro la Richiesta; gli altri due
    # lo tengono sul backend, ed e' da li' che l'impronta della corsa lo rilegge.
    if opzioni.motore in ("locale", "openrouter"):
        argomenti_backend["ragionamento"] = opzioni.ragionamento
    backend = classe(**argomenti_backend)
    risolutore_atc = RisolutoreATC()
    # Stesso gazetteer della pipeline A: normalizzazione identica.
    risolutore_icd = RisolutoreICD(gazetteer=GazetteerClinico())

    cartella = opzioni.uscita
    configurazione = impronta_configurazione(backend, opzioni, schema_estrazione_llm())
    prepara_cartella(cartella, configurazione, opzioni.rifai)

    gia_fatti = {r.enc_oid for r in selezione if (cartella / f"{r.enc_oid}.json").exists()}
    da_fare = [r for r in selezione if r.enc_oid not in gia_fatti]
    salva_registro(cartella, configurazione, len(gia_fatti), len(selezione))

    print(
        f"Pipeline B su {len(selezione)} record con {backend.modello}, "
        f"{parallele} richieste in parallelo."
    )
    if gia_fatti:
        print(f"  ripresa: {len(gia_fatti)} gia' completati, {len(da_fare)} da fare.")
    if not da_fare:
        print("  nulla da fare: la corsa e' gia' completa.")

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
            for rec in da_fare
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

            (cartella / f"{rec.enc_oid}.json").write_text(
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

            if indice % 5 == 0 or indice == len(da_fare):
                # Il registro viene aggiornato spesso: se la corsa viene
                # interrotta, cio' che si e' gia' prodotto resta ritrovabile.
                salva_registro(cartella, configurazione, len(gia_fatti) + indice, len(selezione))
            if indice % 25 == 0 or indice == len(da_fare):
                trascorso = time.monotonic() - avvio
                rimasti = len(da_fare) - indice
                stima = (trascorso / max(indice, 1)) * rimasti
                print(
                    f"  {indice}/{len(da_fare)} record ({trascorso / 60:.0f} min, "
                    f"stimati {stima / 60:.0f} min alla fine)",
                    flush=True,
                )

    durata = time.monotonic() - avvio
    riusciti = len(da_fare) - falliti - saltati
    salva_registro(cartella, configurazione, len(gia_fatti) + riusciti, len(selezione))

    print(
        f"\nSessione: {riusciti}/{len(da_fare)} record in {durata / 60:.0f} min "
        f"({da_cache} da cache, {ritentati} con ritentativi, {falliti} falliti)."
    )
    if interruzione.is_set():
        print(
            f"Corsa interrotta: quota giornaliera esaurita per {backend.modello}. "
            f"{saltati} record non tentati. Rilanciando lo stesso comando la corsa "
            f"riprende da dove si e' fermata.",
            file=sys.stderr,
        )
    if token["uscita"]:
        print(
            f"Token: {token['ingresso']} in ingresso, {token['uscita']} in uscita "
            f"({token['uscita'] / max(durata, 1):.1f} token/s)."
        )

    riepilogo = misura_produzione(cartella)
    riepilogo["configurazione"] = configurazione
    riepilogo["secondi_per_record_sessione"] = round(durata / max(riusciti, 1), 1)
    (cartella / NOME_RIEPILOGO).write_text(
        json.dumps(riepilogo, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    stampa_riepilogo(riepilogo)
    # `relative_to` solleva su percorsi fuori dalla radice o relativi.
    try:
        dove = cartella.resolve().relative_to(RADICE)
    except ValueError:
        dove = cartella.resolve()
    print(f"\nRisultati in {dove}/  ·  riepilogo in {NOME_RIEPILOGO}")


def misura_produzione(cartella) -> dict:
    """Misure dai file prodotti, non dai contatori della sola sessione corrente."""
    percorsi = sorted(f for f in cartella.glob("*.json") if not f.name.startswith("_"))
    misure = {
        "record": len(percorsi),
        "condizioni": 0,
        "condizioni_con_codice": 0,
        "condizioni_ambigue": 0,
        "farmaci": 0,
        "farmaci_con_atc": 0,
        "allergie": 0,
        "menzioni_non_ancorate": 0,
        "per_stato": {},
        "per_momento": {},
    }
    for percorso in percorsi:
        stato = json.loads(percorso.read_text(encoding="utf-8"))
        for condizione in stato["condizioni"]:
            misure["condizioni"] += 1
            misure["condizioni_con_codice"] += bool(condizione["codice"])
            misure["condizioni_ambigue"] += condizione["stato_normalizzazione"] == "ambiguo"
            chiave = condizione["stato"]
            misure["per_stato"][chiave] = misure["per_stato"].get(chiave, 0) + 1
            if condizione["provenienza"]["inizio"] is None:
                misure["menzioni_non_ancorate"] += 1
        for farmaco in stato["farmaci"]:
            misure["farmaci"] += 1
            misure["farmaci_con_atc"] += bool(farmaco["codice_atc"])
            chiave = farmaco["momento"]
            misure["per_momento"][chiave] = misure["per_momento"].get(chiave, 0) + 1
            if farmaco["provenienza"]["inizio"] is None:
                misure["menzioni_non_ancorate"] += 1
        for allergia in stato["allergie"]:
            # Anche le allergie contano nell'ancoraggio: sono le piu' parafrasate.
            misure["allergie"] += 1
            if allergia["provenienza"]["inizio"] is None:
                misure["menzioni_non_ancorate"] += 1
    return misure


def stampa_riepilogo(m: dict) -> None:
    """Le misure che dicono se la produzione e' utilizzabile."""
    def quota(parte, tutto):
        return f"{100 * parte / tutto:.1f}%" if tutto else "n/d"

    menzioni = m["condizioni"] + m["farmaci"] + m["allergie"]
    print(f"\nPRODUZIONE COMPLESSIVA — {m['record']} record")
    print(
        f"  condizioni {m['condizioni']:6d}   con codice ICD {m['condizioni_con_codice']:6d} "
        f"({quota(m['condizioni_con_codice'], m['condizioni'])}), ambigue {m['condizioni_ambigue']}"
    )
    print(
        f"  farmaci    {m['farmaci']:6d}   con codice ATC {m['farmaci_con_atc']:6d} "
        f"({quota(m['farmaci_con_atc'], m['farmaci'])})"
    )
    print(f"  allergie   {m['allergie']:6d}")
    print(
        f"  stato clinico: "
        + ", ".join(f"{k} {v}" for k, v in sorted(m["per_stato"].items(), key=lambda x: -x[1]))
    )
    print(
        f"  momento terapia: "
        + ", ".join(f"{k} {v}" for k, v in sorted(m["per_momento"].items(), key=lambda x: -x[1]))
    )
    # E' il controllo di allucinazione: una citazione che non si ritrova nel
    # referto e' una menzione inventata dal modello.
    print(
        f"  menzioni non ancorate: {m['menzioni_non_ancorate']}/{menzioni} "
        f"({quota(m['menzioni_non_ancorate'], menzioni)})"
    )


if __name__ == "__main__":
    main()
