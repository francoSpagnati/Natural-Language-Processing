"""
Step 3 - Pipeline A: estrazione deterministica dello stato paziente.

E' la baseline del progetto: nessuna libertà interpretativa, ogni entità
riconducibile alla regola che l'ha prodotta. Serve a tre cose insieme:

1. essere il riferimento contro cui misurare le pipeline B (LLM) e C (NER+EL);
2. produrre le **etichette silver** con cui addestrare il modello NER dello
   step 5, senza annotazione manuale;
3. essere l'estrattore predefinito del sistema, perché è l'unico i cui errori
   si possono spiegare uno per uno.

DA DOVE VIENE OGNI PARTE DELLO STATO PAZIENTE

| Parte | Fonte | Metodo |
|---|---|---|
| farmaci in ingresso | campo semi-strutturato | parsing a livelli |
| farmaci alla dimissione | campo semi-strutturato | parsing a livelli |
| condizioni | prosa dell'anamnesi | gazetteer + ConText |
| farmaci citati in prosa | prosa dell'anamnesi | gazetteer + ConText |
| allergie | sottosezione dell'anamnesi | regex dedicata |

SULLE SONDE DELLO STEP 0
    Nel documento dello step 0 avevo scritto che le sonde esplorative sarebbero
    state sostituite da parser definitivi qui. Le riuso invece così come sono, e
    la ragione è che si sono rivelate migliori dell'attesa: interpretano il 99%
    delle voci di dimissione e il 98% di quelle di ingresso, sono organizzate a
    livelli con la provenienza di ogni match, e sono coperte da 29 test.
    Riscriverle avrebbe prodotto codice equivalente con meno collaudo. Restano
    in `explore_dataset.py` — il nome non è più esatto, ma spostarle avrebbe
    rotto i riferimenti nella documentazione degli step precedenti.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from context_it import Attributo, attributi_per_entita, trova_ambiti  # noqa: E402
from data_loading import RecordPaziente  # noqa: E402
from explore_dataset import (  # noqa: E402
    sonda_allergie,
    sonda_terapia_dimissione,
    sonda_terapia_ingresso,
)
from gazetteer import ETICHETTA_CONDIZIONE, ETICHETTA_FARMACO, GazetteerClinico  # noqa: E402
from schema import (  # noqa: E402
    AllergiaEstratta,
    CondizioneEstratta,
    FarmacoEstratto,
    MomentoTerapia,
    Pipeline,
    Provenienza,
    StatoConoscenza,
    StatoNormalizzazione,
    StatoPaziente,
)

from entity_linking import CollegatoreICD
from risolutori import (  # RisolutoreATC ri-esportato: gia' usato come extract_a.RisolutoreATC
    RisolutoreATC,
    RisolutoreICD,
)

RADICE = Path(__file__).resolve().parent.parent

CAMPO_ANAMNESI = "Anamnesi"
CAMPO_INGRESSO = "Terapia medica all'ingresso"
CAMPO_DIMISSIONE = "Terapia alla Dimissione"


def stato_da_attributi(attributi: dict) -> StatoConoscenza:
    """Traduce gli attributi ConText nello stato di conoscenza dello schema.

    La negazione prevale sull'incertezza: "non si esclude" a parte, quando un
    referto nega qualcosa lo fa in modo assertivo. La storicità non compare
    qui perché non cambia la polarità — resta `affermato` e viaggia nella
    regola registrata in `Provenienza`, così l'informazione non si perde.
    """
    if Attributo.NEGAZIONE in attributi:
        return StatoConoscenza.NEGATO
    if Attributo.INCERTEZZA in attributi:
        return StatoConoscenza.INCERTO
    return StatoConoscenza.AFFERMATO


def regola_provenienza(attributi: dict, base: str) -> str:
    """Descrive in una stringa la regola che ha prodotto l'entità.

    È il requisito di tracciabilità del brief: per ogni entità si deve poter
    dire *quale* regola l'ha generata, non solo che è stata generata.
    """
    if not attributi:
        return base
    dettagli = ", ".join(
        f"{attributo.value}:{marcatore.espressione}"
        for attributo, marcatore in attributi.items()
    )
    return f"{base} + ConText({dettagli})"


def farmaci_da_campo_strutturato(
    record: RecordPaziente, risolutore: RisolutoreATC
) -> list[FarmacoEstratto]:
    """Estrae i farmaci dai due campi terapia semi-strutturati."""
    farmaci: list[FarmacoEstratto] = []

    testo_ingresso = record.testo_terapia_ingresso or ""
    nomi, _, _ = sonda_terapia_ingresso(testo_ingresso)
    for nome in nomi:
        codice, stato, fonte = risolutore.risolvi(nome)
        posizione = testo_ingresso.find(nome)
        farmaci.append(
            FarmacoEstratto(
                nome_grezzo=nome,
                principio_attivo=None,
                codice_atc=codice,
                stato_normalizzazione=stato,
                fonte_normalizzazione=fonte,
                momento=MomentoTerapia.INGRESSO,
                provenienza=Provenienza(
                    pipeline=Pipeline.CAMPO_STRUTTURATO,
                    campo_sorgente=CAMPO_INGRESSO,
                    testo_originale=nome,
                    inizio=posizione if posizione >= 0 else None,
                    fine=posizione + len(nome) if posizione >= 0 else None,
                    regola="sonda_terapia_ingresso",
                ),
            )
        )

    testo_dimissione = record.testo_terapia_dimissione or ""
    voci, _, _ = sonda_terapia_dimissione(testo_dimissione)
    for voce in voci:
        principio = voce["principio"]
        codice, stato, fonte = risolutore.risolvi(principio)
        posizione = testo_dimissione.find(principio)
        farmaci.append(
            FarmacoEstratto(
                nome_grezzo=principio,
                principio_attivo=principio,
                codice_atc=codice,
                stato_normalizzazione=stato,
                fonte_normalizzazione=fonte,
                momento=MomentoTerapia.DIMISSIONE,
                posologia=voce["posologia"] or None,
                provenienza=Provenienza(
                    pipeline=Pipeline.CAMPO_STRUTTURATO,
                    campo_sorgente=CAMPO_DIMISSIONE,
                    testo_originale=principio,
                    inizio=posizione if posizione >= 0 else None,
                    fine=posizione + len(principio) if posizione >= 0 else None,
                    regola=f"sonda_terapia_dimissione:{voce['livello']}",
                ),
            )
        )

    return farmaci


def _entita_dalla_prosa(
    record: RecordPaziente,
    gazetteer: GazetteerClinico,
    risolutore: RisolutoreATC,
    collegatore: CollegatoreICD,
) -> tuple[list[CondizioneEstratta], list[FarmacoEstratto]]:
    """Riconosce condizioni e farmaci nella prosa, con negazione e incertezza."""
    testo = record.testo_anamnesi or ""
    condizioni: list[CondizioneEstratta] = []
    farmaci: list[FarmacoEstratto] = []
    if not testo.strip():
        return condizioni, farmaci

    documento = gazetteer.nlp(testo)
    ambiti = trova_ambiti(documento)

    for menzione in gazetteer.trova(documento):
        attributi = attributi_per_entita(ambiti, menzione.inizio_token, menzione.fine_token)
        provenienza = Provenienza(
            pipeline=Pipeline.A_DETERMINISTICA,
            campo_sorgente=CAMPO_ANAMNESI,
            testo_originale=menzione.testo,
            inizio=menzione.inizio,
            fine=menzione.fine,
            regola=regola_provenienza(attributi, f"gazetteer:{menzione.forma_vocabolario}"),
        )

        if menzione.etichetta == ETICHETTA_CONDIZIONE:
            # La codifica passa dallo stesso collegatore usato dalla pipeline C.
            # Prendere qui i codici direttamente dal gazetteer sarebbe piu'
            # semplice ma renderebbe le due pipeline diverse anche nella
            # normalizzazione, e il confronto dello step 6 misurerebbe la somma
            # di due differenze invece del solo riconoscimento delle menzioni.
            esito = collegatore.collega(menzione.testo)
            codice, stato_norm = esito.codice, esito.stato
            condizioni.append(
                CondizioneEstratta(
                    testo_grezzo=menzione.testo,
                    concetto=esito.concetto or menzione.forma_vocabolario,
                    codice=codice,
                    sistema_codifica="ICD-10" if codice else None,
                    stato_normalizzazione=stato_norm,
                    stato=stato_da_attributi(attributi),
                    provenienza=provenienza,
                )
            )
        elif menzione.etichetta == ETICHETTA_FARMACO:
            codice, stato_norm, fonte = risolutore.risolvi(menzione.forma_vocabolario)
            farmaci.append(
                FarmacoEstratto(
                    nome_grezzo=menzione.testo,
                    codice_atc=codice,
                    stato_normalizzazione=stato_norm,
                    fonte_normalizzazione=fonte,
                    momento=MomentoTerapia.NARRATIVO,
                    stato=stato_da_attributi(attributi),
                    provenienza=provenienza,
                )
            )

    return condizioni, farmaci


def allergie_dal_referto(record: RecordPaziente) -> tuple[list[AllergiaEstratta], StatoConoscenza]:
    """Estrae le allergie e lo *stato* della sezione, che sono cose diverse.

    Una lista vuota può voler dire "il clinico ha verificato che non ce ne sono"
    oppure "il referto non ne parla": senza distinguerle il filtro di sicurezza
    non saprebbe quanto fidarsi.
    """
    testo = record.testo_anamnesi or ""
    esito = sonda_allergie(testo)

    stato_sezione = {
        "sezione_assente": StatoConoscenza.IGNOTO,
        "assenza_dichiarata": StatoConoscenza.NEGATO,
        "allergie_presenti": StatoConoscenza.AFFERMATO,
    }[esito["stato"]]

    allergie: list[AllergiaEstratta] = []
    for categoria, valori in esito["categorie"].items():
        for valore in valori:
            for allergene in (v.strip() for v in re.split(r"[,;]", valore)):
                if not allergene:
                    continue
                posizione = testo.find(allergene)
                allergie.append(
                    AllergiaEstratta(
                        allergene=allergene,
                        categoria=categoria,
                        provenienza=Provenienza(
                            pipeline=Pipeline.A_DETERMINISTICA,
                            campo_sorgente=CAMPO_ANAMNESI,
                            testo_originale=allergene,
                            inizio=posizione if posizione >= 0 else None,
                            fine=posizione + len(allergene) if posizione >= 0 else None,
                            regola=f"sonda_allergie:{categoria}",
                        ),
                    )
                )
    return allergie, stato_sezione


def estrai(
    record: RecordPaziente,
    gazetteer: GazetteerClinico,
    risolutore: RisolutoreATC,
    collegatore: CollegatoreICD | None = None,
) -> StatoPaziente:
    """Costruisce lo stato paziente strutturato a partire da un record."""
    if collegatore is None:
        collegatore = CollegatoreICD(RisolutoreICD(gazetteer=gazetteer))
    condizioni, farmaci_prosa = _entita_dalla_prosa(
        record, gazetteer, risolutore, collegatore
    )
    farmaci = farmaci_da_campo_strutturato(record, risolutore) + farmaci_prosa
    allergie, stato_sezione = allergie_dal_referto(record)

    note: list[str] = []
    _, scarti_ingresso, _ = sonda_terapia_ingresso(record.testo_terapia_ingresso or "")
    if scarti_ingresso:
        note.append(
            f"{len(scarti_ingresso)} frammenti non interpretati nella terapia in ingresso"
        )
    if not record.ha_terapia_dimissione:
        note.append("referto di dimissione assente: record non utilizzabile come ground truth")

    return StatoPaziente(
        enc_oid=record.enc_oid,
        pipeline=Pipeline.A_DETERMINISTICA,
        condizioni=condizioni,
        farmaci=farmaci,
        allergie=allergie,
        stato_sezione_allergie=stato_sezione,
        testo_supporto=record.testo_anamnesi,
        note_estrazione=note,
    )


# ---------------------------------------------------------------------------
# Esecuzione su tutto il dataset
# ---------------------------------------------------------------------------

PERCORSO_DATASET = RADICE / "data" / "raw" / "anamnesiterapie.txt"
CARTELLA_USCITA = RADICE / "data" / "processed" / "pipeline_a"


def main() -> None:
    """Applica la pipeline A a tutti i record e salva uno stato per ciascuno.

    Un file per record invece di un unico JSON: gli stati vanno letti e
    confrontati singolarmente negli step successivi (il confronto fra pipeline,
    il motore, la valutazione), e un file da centinaia di MB andrebbe caricato
    per intero ogni volta.
    """
    import time
    from collections import Counter

    from data_loading import carica_dataset

    record, _ = carica_dataset(PERCORSO_DATASET)
    print(f"Record da processare: {len(record)}")

    print("Costruzione del gazetteer...")
    gazetteer = GazetteerClinico()
    risolutore = RisolutoreATC()
    collegatore = CollegatoreICD(RisolutoreICD(gazetteer=gazetteer))
    print(f"  forme farmaci: {len(gazetteer.forme_farmaci)}")
    print(f"  forme condizioni: {len(gazetteer.forme_condizioni)}")

    CARTELLA_USCITA.mkdir(parents=True, exist_ok=True)
    conteggi: Counter = Counter()
    inizio = time.time()

    for indice, rec in enumerate(record, 1):
        stato = estrai(rec, gazetteer, risolutore, collegatore)
        (CARTELLA_USCITA / f"{rec.enc_oid}.json").write_text(
            stato.model_dump_json(indent=2), encoding="utf-8"
        )

        conteggi["condizioni"] += len(stato.condizioni)
        conteggi["farmaci"] += len(stato.farmaci)
        conteggi["allergie"] += len(stato.allergie)
        for condizione in stato.condizioni:
            conteggi[f"condizione_{condizione.stato.value}"] += 1
            conteggi[f"condizione_norm_{condizione.stato_normalizzazione.value}"] += 1
        for farmaco in stato.farmaci:
            conteggi[f"farmaco_{farmaco.momento.value}"] += 1
            conteggi[f"farmaco_norm_{farmaco.stato_normalizzazione.value}"] += 1
        conteggi[f"sezione_allergie_{stato.stato_sezione_allergie.value}"] += 1

        if indice % 200 == 0:
            print(f"  {indice}/{len(record)}  ({time.time() - inizio:.0f}s)")

    durata = time.time() - inizio
    print(f"\nCompletato in {durata:.0f}s ({1000 * durata / len(record):.0f} ms/record)")
    print(f"Stati scritti in {CARTELLA_USCITA.relative_to(RADICE)}/\n")
    for chiave, valore in sorted(conteggi.items()):
        print(f"  {chiave:38} {valore}")
    print(f"\n  media per record: {conteggi['condizioni'] / len(record):.1f} condizioni, "
          f"{conteggi['farmaci'] / len(record):.1f} farmaci")


if __name__ == "__main__":
    main()
