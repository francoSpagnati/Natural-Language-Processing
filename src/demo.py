"""Demo end-to-end: da un'anamnesi scritta a mano a una terapia suggerita.

Le metriche degli step 6, 6bis e 9 dicono *quanto bene* il sistema funziona.
Questo modulo mostra *che cosa fa*, su un paziente che non esiste nel dataset:
si scrive un'anamnesi e una terapia in atto, e il sistema attraversa tutta la
catena davanti a chi guarda.

    testo libero
        |
        |  [step 3/4/5]  riconoscimento + codifica ICD-10 / ATC
        v
    stato del paziente
        |
        |  [step 8]      filtro di sicurezza: che cosa NON si puo' dare
        v
    candidati ammessi
        |
        |  [step 9]      ranker: che cosa conviene dare, e perche'
        v
    terapia suggerita, con le fonti

## Perche' il motore predefinito e' quello deterministico

La demo gira **senza rete, senza chiave API e senza costo**: l'estrazione usa la
pipeline A (gazetteer + ConText) e il parser deterministico della terapia. E'
una scelta di dimostrabilita' — chi guarda puo' rieseguirla — e non nasconde
nulla: `--motore locale` usa il modello linguistico via Ollama, e lo step 6bis
ha misurato che sulle condizioni il modello ha un richiamo di 68,7% contro il
19,5% del gazetteer. La demo con il motore deterministico mostra **meno** di
quello che il sistema sa fare, non di piu'.

## Che cosa la demo non e'

Non e' un dispositivo medico e non e' una validazione clinica. Il ranker e'
misurato contro *una* decisione presa da *un* medico su 244 ricoveri; il §1 di
`docs/09_ranker.md` spiega perche' la precisione di quella misura non e'
interpretabile come correttezza.
"""

from __future__ import annotations

import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_loading import (  # noqa: E402
    TIPO_ANAMNESI,
    TIPO_TERAPIA_INGRESSO,
    Referto,
    RecordPaziente,
)
from filtro import Esito, StatoPerFiltro, valuta  # noqa: E402
from ranker import (  # noqa: E402
    PESO_CLASSE,
    Caso,
    RankerIbrido,
    RankerSimbolico,
    allerta_di_classe,
    annota,
    carica_casi,
    classe,
    insieme_candidato,
    nomi_atc,
    nomi_icd,
)

LARGHEZZA = 78


# ---------------------------------------------------------------------------
# I pazienti d'esempio
#
# Tutti sintetici, scritti con la grammatica del corpus — le abbreviazioni, la
# punteggiatura, l'ordine delle sezioni. Ogni esempio e' costruito per mostrare **una** capacita' del sistema.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Esempio:
    titolo: str
    mostra: str
    anamnesi: str
    terapia_ingresso: str


ESEMPI: tuple[Esempio, ...] = (
    Esempio(
        "Scompenso e fibrillazione atriale",
        "la catena intera, dal testo alla proposta con le fonti",
        "Paziente di 71 anni, scompenso cardiaco cronico noto da tre anni. "
        "Fibrillazione atriale permanente, mai cardiovertita. Segue cura per "
        "ipertensione arteriosa dal 2004 e diabete mellito tipo 2 in terapia "
        "orale. Nell'ultimo mese dispnea da sforzo ingravescente.",
        "Furosemide 25 mg: 1 cp al mattino; Metformina 500 mg: 1 cp x 2; "
        "Pantoprazolo 20 mg: 1 cp",
    ),
    Esempio(
        "Negazione e familiarita'",
        "l'algoritmo ConText: cio' che il paziente NON ha, e cio' che ha suo padre",
        "Uomo di 58 anni. Non riferisce angina ne' cardiopatia ischemica. "
        "Padre deceduto a 60 anni per infarto miocardico; madre diabetica. "
        "Segue cura per ipertensione arteriosa dal 2019; colesterolo elevato "
        "ai controlli di laboratorio.",
        "Amlodipina 5 mg: 1 cp la sera",
    ),
    Esempio(
        "Allergia dichiarata",
        "l'avvertimento di classe: proporre la classe giusta, segnalare la molecola",
        "Donna di 66 anni, cardiopatia ischemica cronica; aterosclerosi "
        "carotidea documentata all'ecocolordoppler. Segue cura per ipertensione "
        "arteriosa dal 2011. "
        "Allergie e intolleranze: Principi attivi (acido acetilsalicilico)",
        "Bisoprololo 2,5 mg: 1 cp; Atorvastatina 20 mg: 1 cp la sera",
    ),
)


def paziente_da_testo(anamnesi: str, terapia_ingresso: str,
                      enc_oid: int = 0) -> RecordPaziente:
    """Costruisce un ricovero dai due testi, senza passare dal dataset.

    E' il punto che rende la demo possibile: `RecordPaziente` non e' legato al
    file grezzo, e le pipeline leggono **quello**, non il file. Se cosi' non
    fosse, provare il sistema su un paziente nuovo richiederebbe di scriverlo
    dentro il dataset.
    """
    return RecordPaziente(
        enc_oid=enc_oid,
        referti=[
            Referto(TIPO_ANAMNESI, None, None, anamnesi),
            Referto(TIPO_TERAPIA_INGRESSO, None, None, terapia_ingresso),
        ],
    )


# ---------------------------------------------------------------------------
# Presentazione
# ---------------------------------------------------------------------------

def titolo(testo: str, carattere: str = "=") -> None:
    print(f"\n{carattere * LARGHEZZA}\n{testo}\n{carattere * LARGHEZZA}")


def paragrafo(testo: str, rientro: str = "  ") -> None:
    for riga in textwrap.wrap(testo, LARGHEZZA - len(rientro)):
        print(f"{rientro}{riga}")


def evidenzia(testo: str, intervalli: list[tuple[int, int]]) -> str:
    """Segna nel testo i punti in cui il sistema ha riconosciuto qualcosa.

    Mostrare gli offset invece di un elenco di concetti e' la differenza fra
    «il sistema dice che il paziente ha lo scompenso» e «il sistema lo dice
    **per via di queste parole**». La seconda si puo' contestare, la prima no.
    """
    fusi: list[list[int]] = []
    for inizio, fine in sorted(intervalli):
        if fusi and inizio <= fusi[-1][1]:
            fusi[-1][1] = max(fusi[-1][1], fine)
        else:
            fusi.append([inizio, fine])
    fuori = []
    ultimo = 0
    for inizio, fine in fusi:
        fuori.append(testo[ultimo:inizio])
        fuori.append(f"[{testo[inizio:fine]}]")
        ultimo = fine
    fuori.append(testo[ultimo:])
    return "".join(fuori)


def mostra_estrazione(stato, anamnesi: str, icd: dict[str, str]) -> None:
    titolo("1. ESTRAZIONE — dal testo libero allo stato strutturato")

    intervalli = [(c.provenienza.inizio, c.provenienza.fine) for c in stato.condizioni
                  if c.provenienza.campo_sorgente == TIPO_ANAMNESI
                  and c.provenienza.inizio is not None]
    print("\nAnamnesi, con le menzioni riconosciute fra parentesi quadre:\n")
    paragrafo(evidenzia(anamnesi, intervalli))

    print(f"\nCondizioni riconosciute: {len(stato.condizioni)}\n")
    print(f"  {'testo':28} {'ICD-10':9} {'stato':10} {'soggetto':10}")
    print(f"  {'-' * 28} {'-' * 9} {'-' * 10} {'-' * 10}")
    for c in stato.condizioni:
        codice = c.codice or "—"
        segno = "  " if (c.stato.value == "affermato"
                         and c.soggetto.value == "paziente") else "x "
        print(f"{segno}{c.testo_grezzo[:28]:28} {codice:9} "
              f"{c.stato.value:10} {c.soggetto.value:10}")

    scartate = [c for c in stato.condizioni
                if c.stato.value != "affermato" or c.soggetto.value != "paziente"]
    if scartate:
        print(f"\n  Le {len(scartate)} righe marcate «x» NON diventano fatti del "
              f"paziente:")
        for c in scartate:
            print(f"    {c.testo_grezzo[:34]:34} -> {c.stato.value}, "
                  f"{c.soggetto.value}")
        paragrafo("Senza questa distinzione il sistema raccomanderebbe una "
                  "terapia per la malattia del padre, o per una malattia che il "
                  "referto dice esclusa. E' l'asse che lo step 6 ha dovuto "
                  "aggiungere dopo averne trovato il buco.", "    ")

    farmaci = [f for f in stato.farmaci if f.momento.value == "ingresso"]
    print(f"\nTerapia in atto riconosciuta dal parser deterministico: "
          f"{len(farmaci)} voci\n")
    for f in farmaci:
        print(f"  {f.nome_grezzo[:34]:34} {f.codice_atc or '—':9} "
              f"{(f.posologia or '')[:26]}")

    if stato.allergie:
        print(f"\nAllergie riconosciute: {len(stato.allergie)}\n")
        for a in stato.allergie:
            print(f"  {a.allergene[:34]:34} {a.categoria[:18]:18} "
                  f"{a.codice_atc or '— non codificata'}")
    elif stato.stato_sezione_allergie.value == "ignoto":
        print("\nAllergie: sezione non riconosciuta nel testo.")
        paragrafo("Il parser cerca la forma che il corpus usa davvero — "
                  "«Allergie e intolleranze: Principi attivi (...)» — e non una "
                  "frase libera. Una sezione non riconosciuta resta `ignoto`, "
                  "che e' diverso da «nessuna allergia»: il filtro deve sapere "
                  "se non ce ne sono o se nessuno l'ha chiesto.")
    else:
        print("\nAllergie: assenza dichiarata dal clinico (non e' un dato "
              "mancante).")


def mostra_filtro(stato_filtro: StatoPerFiltro, atc: dict[str, str]) -> None:
    titolo("2. FILTRO DI SICUREZZA — che cosa il paziente NON puo' ricevere")
    paragrafo("Applicato alla terapia che il paziente sta gia' assumendo: e' il "
              "controllo che un supporto alla decisione deve saper fare per "
              "primo, prima di proporre qualcosa di nuovo.")
    print()
    for a in sorted(stato_filtro.terapia_atc):
        v = valuta(stato_filtro, a, esclusa_dalla_terapia=a)
        simbolo = {"ammesso": "ok  ", "da_verificare": "??  ", "vietato": "STOP"}
        print(f"  {simbolo[v.esito.value]} {a:9} {atc.get(a, '')[:40]:42} "
              f"{v.esito.value}")
        for m in v.motivi:
            paragrafo(f"{m['motivo']}", "         ")
            paragrafo(f"fonte: {m['fonte']}", "         ")


def mostra_ranker(caso: Caso, candidati: list[str], ibrido: RankerIbrido,
                  simbolico: RankerSimbolico, atc: dict[str, str],
                  quante: int) -> None:
    titolo("3. SUGGERIMENTO — che cosa aggiungere, e perche'")
    paragrafo("Le classi gia' in terapia sono escluse dall'elenco: la domanda e' "
              "che cosa **aggiungere**. Le prime sono quelle che il ranker "
              "ibrido mette piu' in alto; accanto, la ragione citabile quando "
              "esiste.")

    ordine = annota(caso, ibrido.ordina(caso, candidati))
    nuovi = [r for r in ordine if r.classe_atc not in caso.terapia_ingresso]

    print()
    for i, r in enumerate(nuovi[:quante], 1):
        indicazioni = simbolico.motivazioni(caso, r.classe_atc)
        # La stessa indicazione che il ranker ha usato per il punteggio: quella
        # con il peso maggiore. Mostrarne un'altra racconterebbe una ragione
        # diversa da quella che ha deciso la posizione.
        ind = max(indicazioni, key=lambda x: PESO_CLASSE[x.classe_racc],
                  default=None)
        marchio = f"classe {ind.classe_racc}" if ind else "appresa dal corpus"
        print(f"\n  {i}. {r.classe_atc}  {atc.get(r.classe_atc, '')[:44]}")
        print(f"     [{marchio}]")
        if ind:
            paragrafo(ind.motivo, "     ")
            paragrafo(f"fonte: {ind.fonte}", "     ")
            if ind.fatto_non_estratto:
                paragrafo(f"NOTA: la linea guida deciderebbe su un fatto che il "
                          f"sistema non estrae — {ind.fatto_non_estratto}.",
                          "     ")
        else:
            paragrafo("Nessuna indicazione citabile per questo paziente: la "
                      "proposta viene dalla co-occorrenza misurata sul corpus. "
                      "E' il 40% delle prescrizioni che nessuna linea guida "
                      "cardiologica regola.", "     ")
        if allerta_di_classe(caso, r.classe_atc):
            paragrafo(f"ATTENZIONE: {allerta_di_classe(caso, r.classe_atc)}",
                      "     ")


# ---------------------------------------------------------------------------
# I due motori di estrazione
# ---------------------------------------------------------------------------

def estrai_deterministico(record: RecordPaziente):
    """Pipeline A: gazetteer + ConText. Nessuna rete, nessuna chiave, nessun costo."""
    from entity_linking import CollegatoreICD
    from extract_a import estrai
    from gazetteer import GazetteerClinico
    from risolutori import RisolutoreATC, RisolutoreICD

    gz = GazetteerClinico()
    return estrai(record, gz, RisolutoreATC(),
                  CollegatoreICD(RisolutoreICD(gazetteer=gz)))


def estrai_con_modello(record: RecordPaziente, motore: str,
                       modello: str | None = None):
    """Pipeline B: un modello linguistico legge l'anamnesi."""
    from extract_b import estrai
    from gazetteer import GazetteerClinico
    from llm_backend import BackendOllama, BackendOpenRouter
    from risolutori import RisolutoreATC, RisolutoreICD

    classe_backend = {"locale": BackendOllama, "openrouter": BackendOpenRouter}[motore]
    backend = classe_backend(**({"modello": modello} if modello else {}),
                             ragionamento="no")
    # Gli stessi risolutori della pipeline A: se differissero, il confronto fra
    # i due motori misurerebbe anche la differenza di codifica.
    stato, _ = estrai(record, backend, RisolutoreATC(),
                      RisolutoreICD(gazetteer=GazetteerClinico()),
                      livello_ragionamento="no")
    return stato


def confronta_motori(anamnesi: str, terapia: str, motore: str = "locale",
                     modello: str | None = None) -> None:
    """Gli stessi due testi letti dai due motori, affiancati.

    E' il risultato centrale del progetto reso tangibile su un paziente solo.
    Lo step 6bis lo ha misurato su 25 referti annotati a mano: sulle condizioni
    il gazetteer ha un richiamo del **19,5%**, il modello linguistico del
    **68,7%**. La ragione e' strutturale — il vocabolario del gazetteer e'
    costruito dai termini ICD-10, quindi trova **solo cio' che la nomenclatura
    gia' conosce**, e nella prosa cardiologica la maggior parte delle condizioni
    non e' scritta in forma da nomenclatura.
    """
    record = paziente_da_testo(anamnesi, terapia)
    icd = nomi_icd()

    titolo("CONFRONTO FRA I DUE MOTORI DI ESTRAZIONE")
    paragrafo("Stesso testo, stessi risolutori di codice. Cambia solo chi "
              "riconosce le entita' nella prosa.")

    risultati = []
    for etichetta, produci in (
        ("A — gazetteer + ConText (deterministico)",
         lambda: estrai_deterministico(record)),
        (f"B — modello linguistico ({motore})",
         lambda: estrai_con_modello(record, motore, modello)),
    ):
        stato = produci()
        trovate = {(c.testo_grezzo.lower(), c.codice) for c in stato.condizioni
                   if c.stato.value == "affermato" and c.soggetto.value == "paziente"}
        risultati.append((etichetta, stato, trovate))
        print(f"\n  {etichetta}")
        print(f"  {'-' * len(etichetta)}")
        for c in stato.condizioni:
            segno = "  " if (c.stato.value == "affermato"
                             and c.soggetto.value == "paziente") else "x "
            print(f"  {segno}{c.testo_grezzo[:40]:42} {c.codice or '—':9} "
                  f"{c.stato.value}")
        if not stato.condizioni:
            print("    nessuna condizione riconosciuta")

    solo_a = risultati[0][2] - risultati[1][2]
    solo_b = risultati[1][2] - risultati[0][2]
    print()
    titolo("Che cosa vede uno e non l'altro", "-")
    print(f"\n  solo il gazetteer ({len(solo_a)}):")
    for testo, codice in sorted(solo_a):
        print(f"    {testo[:44]:46} {codice or '—'}")
    print(f"\n  solo il modello ({len(solo_b)}):")
    for testo, codice in sorted(solo_b):
        print(f"    {testo[:44]:46} {codice or '—'}")
    paragrafo("Il gazetteer trova solo cio' che la nomenclatura ICD-10 gia' "
              "conosce: e' il suo vocabolario, ed e' il motivo per cui il suo "
              "richiamo misurato e' del 19,5% contro il 68,7% del modello. "
              "Quello che trova, pero', lo trova con precisione dell'80%, e non "
              "costa niente.")


def mostra_traccia(stati: dict, caso, candidati, ibrido, simbolico,
                   atc: dict, icd: dict, quante: int) -> None:
    """Da dove viene ogni proposta, interrogando il grafo.

    Il grafo del paziente viene costruito qui e interrogato in SPARQL: e' lo
    stesso modello di dati del grafo dei 1 000 ricoveri, e la stessa
    interrogazione gira su entrambi. Senza questo passaggio il knowledge graph
    dello step 7 resterebbe un artefatto parallelo che nessuno consuma.
    """
    from traccia import grafo_del_paziente, stampa_traccia, traccia_raccomandazione

    titolo("5. LA TRACCIA — da dove viene ogni proposta")
    g = grafo_del_paziente(stati, 0, icd, atc)
    agenti = ", ".join(sorted(stati))
    paragrafo(f"Grafo del paziente: {len(g)} triple, costruite dalle pipeline "
              f"{agenti}. Ogni catena qui sotto e' il risultato di "
              f"un'interrogazione SPARQL su quel grafo, non una ristampa del "
              f"JSON da cui il grafo e' stato costruito.")

    ordine = [r for r in ibrido.ordina(caso, candidati)
              if r.classe_atc not in caso.terapia_ingresso]
    for r in ordine[:quante]:
        stampa_traccia(traccia_raccomandazione(g, r.classe_atc, caso, simbolico),
                       atc.get(r.classe_atc, ""))


# ---------------------------------------------------------------------------
# La catena
# ---------------------------------------------------------------------------

def analizza(anamnesi: str, terapia: str, motore: str = "deterministico",
             quante: int = 6, modello: str | None = None,
             con_traccia: bool = False) -> dict:
    """La catena intera, come dato invece che come stampa.

    Separare il calcolo dalla presentazione serve a due cose: la pagina di
    dimostrazione mostra **l'uscita vera di questo comando** invece di numeri
    ricopiati a mano, e il tool MCP dello step 10 ha gia' la funzione che gli
    serve senza dover ricostruire la catena.
    """
    record = paziente_da_testo(anamnesi, terapia)
    stati = {"A": estrai_deterministico(record)}
    if motore != "deterministico":
        stati["B"] = estrai_con_modello(record, motore, modello)
    stato = stati.get("B", stati["A"])

    condizioni = [{"codice": c.codice, "testo": c.testo_grezzo, "agenti": ["demo"]}
                  for c in stato.condizioni
                  if c.codice and c.stato.value == "affermato"
                  and c.soggetto.value == "paziente"]
    allergie = {a.codice_atc for a in stato.allergie if a.codice_atc}
    terapia_atc = {f.codice_atc for f in stato.farmaci
                   if f.codice_atc and f.momento.value == "ingresso"}
    stato_filtro = StatoPerFiltro(0, condizioni, allergie, terapia_atc)

    casi = carica_casi(RADICE / "data" / "processed" / "pipeline_b_v3")
    candidati = insieme_candidato(casi)
    ibrido = RankerIbrido()
    ibrido.addestra(casi)
    simbolico = RankerSimbolico()

    caso = Caso(0, frozenset(c["codice"] for c in condizioni),
                frozenset(classe(a) for a in terapia_atc),
                frozenset(allergie), frozenset())
    ammessi = [c for c in candidati
               if valuta(stato_filtro, c, esclusa_dalla_terapia=c).esito
               is not Esito.VIETATO]

    atc = nomi_atc()
    icd = nomi_icd()
    grafo = traccia_mod = None
    if con_traccia:
        from traccia import grafo_del_paziente, traccia_raccomandazione as traccia_mod

        grafo = grafo_del_paziente(stati, 0, icd, atc)

    proposte = []
    for r in annota(caso, ibrido.ordina(caso, ammessi)):
        if r.classe_atc in caso.terapia_ingresso:
            continue
        ind = max(simbolico.motivazioni(caso, r.classe_atc),
                  key=lambda x: PESO_CLASSE[x.classe_racc], default=None)
        proposte.append({
            "classe_atc": r.classe_atc,
            "nome": atc.get(r.classe_atc, ""),
            "classe_raccomandazione": ind.classe_racc if ind else None,
            "motivo": ind.motivo if ind else None,
            "fonte": ind.fonte if ind else None,
            "fatto_non_estratto": ind.fatto_non_estratto if ind else None,
            "avvertimento": allerta_di_classe(caso, r.classe_atc),
            **({"traccia": traccia_mod(grafo, r.classe_atc, caso, simbolico)}
               if grafo is not None else {}),
        })
        if len(proposte) >= quante:
            break

    return {
        "motore": motore,
        "anamnesi": anamnesi,
        "terapia_ingresso": terapia,
        "condizioni": [{
            "testo": c.testo_grezzo, "codice": c.codice,
            "stato": c.stato.value, "soggetto": c.soggetto.value,
            "inizio": c.provenienza.inizio, "fine": c.provenienza.fine,
            "campo": c.provenienza.campo_sorgente,
        } for c in stato.condizioni],
        "farmaci": [{
            "nome": f.nome_grezzo, "codice_atc": f.codice_atc,
            "posologia": f.posologia,
        } for f in stato.farmaci if f.momento.value == "ingresso"],
        "allergie": [{"allergene": a.allergene, "categoria": a.categoria,
                      "codice_atc": a.codice_atc} for a in stato.allergie],
        "stato_sezione_allergie": stato.stato_sezione_allergie.value,
        "filtro": [{
            "atc": a, "nome": atc.get(a, ""),
            "esito": valuta(stato_filtro, a, esclusa_dalla_terapia=a).esito.value,
            "motivi": valuta(stato_filtro, a, esclusa_dalla_terapia=a).motivi,
        } for a in sorted(terapia_atc)],
        "candidati_ammessi": len(ammessi),
        "candidati_totali": len(candidati),
        "proposte": proposte,
        **({"triple_grafo": len(grafo), "agenti_grafo": sorted(stati)}
           if grafo is not None else {}),
    }


def esegui(anamnesi: str, terapia: str, motore: str = "deterministico",
           quante: int = 6, modello: str | None = None,
           traccia: bool = False) -> None:
    """Attraversa la catena intera e stampa ogni passaggio."""
    icd, atc = nomi_icd(), nomi_atc()
    record = paziente_da_testo(anamnesi, terapia)

    # --- estrazione ---
    # Il motore deterministico costa zero, quindi quando se ne chiede un altro
    # si tengono entrambi: il grafo della traccia mostra allora **due agenti**
    # dove le due pipeline vedono lo stesso punto, che e' esattamente cio' che
    # il grafo dello step 7 esiste per rendere interrogabile.
    stato_per_grafo = {"A": estrai_deterministico(record)}
    if motore != "deterministico":
        stato_per_grafo["B"] = estrai_con_modello(record, motore, modello)
    stato = stato_per_grafo.get("B", stato_per_grafo["A"])

    mostra_estrazione(stato, anamnesi, icd)

    # --- lo stato ridotto a cio' che gli strati decisionali guardano ---
    condizioni = [{"codice": c.codice, "testo": c.testo_grezzo, "agenti": ["demo"]}
                  for c in stato.condizioni
                  if c.codice and c.stato.value == "affermato"
                  and c.soggetto.value == "paziente"]
    allergie = {a.codice_atc for a in stato.allergie if a.codice_atc}
    terapia_atc = {f.codice_atc for f in stato.farmaci
                   if f.codice_atc and f.momento.value == "ingresso"}

    mostra_filtro(StatoPerFiltro(0, condizioni, allergie, terapia_atc), atc)

    # --- il ranker ---
    # Addestrato sul corpus **intero**: il paziente della demo non ne fa parte,
    # quindi non c'e' nulla da cui isolarlo. Nella valutazione dello step 9
    # l'addestramento e' invece ristretto, perche' li' i casi di prova sono
    # dentro il corpus.
    casi = carica_casi(RADICE / "data" / "processed" / "pipeline_b_v3")
    candidati = insieme_candidato(casi)
    ibrido = RankerIbrido()
    ibrido.addestra(casi)

    caso = Caso(0, frozenset(c["codice"] for c in condizioni),
                frozenset(classe(a) for a in terapia_atc),
                frozenset(allergie), frozenset())
    ammessi = [c for c in candidati
               if valuta(StatoPerFiltro(0, condizioni, allergie, terapia_atc), c,
                         esclusa_dalla_terapia=c).esito is not Esito.VIETATO]

    simbolico = RankerSimbolico()
    mostra_ranker(caso, ammessi, ibrido, simbolico, atc, quante)

    if traccia:
        mostra_traccia(stato_per_grafo, caso, ammessi, ibrido, simbolico,
                       atc, icd, quante)

    titolo("Questa non e' una validazione clinica", "-")
    paragrafo("Il ranker e' misurato contro UNA decisione presa da UN medico su "
              "244 ricoveri. Una proposta non prescritta non e' per forza un "
              "errore, e una prescritta e non proposta non e' per forza una "
              "svista. Vedi `docs/09_ranker.md` §1.")


def main() -> None:
    import argparse

    argomenti = argparse.ArgumentParser(
        description="Demo end-to-end: da un'anamnesi a una terapia suggerita.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            esempi d'uso:
              python3 src/demo.py --elenco
              python3 src/demo.py --esempio 1
              python3 src/demo.py --interattivo
              python3 src/demo.py --anamnesi mio.txt --terapia mia.txt
            """),
    )
    argomenti.add_argument("--esempio", type=int, default=None,
                           help="Usa uno dei pazienti sintetici d'esempio.")
    argomenti.add_argument("--elenco", action="store_true",
                           help="Elenca gli esempi disponibili ed esce.")
    argomenti.add_argument("--interattivo", action="store_true",
                           help="Chiede anamnesi e terapia da tastiera.")
    argomenti.add_argument("--anamnesi", type=Path, default=None,
                           help="File di testo con l'anamnesi.")
    argomenti.add_argument("--terapia", type=Path, default=None,
                           help="File di testo con la terapia all'ingresso.")
    argomenti.add_argument("--motore", default="deterministico",
                           choices=["deterministico", "locale", "openrouter"],
                           help="Come estrarre dalla prosa. Il predefinito non "
                                "usa rete ne' chiavi API.")
    argomenti.add_argument("--modello", default=None,
                           help="Modello, se il motore e' un LLM.")
    argomenti.add_argument("--traccia", action="store_true",
                           help="Aggiunge la traccia di provenienza: da quali "
                                "parole di quale referto, viste da quale "
                                "pipeline, viene ogni proposta. Interroga il "
                                "knowledge graph dello step 7 in SPARQL.")
    argomenti.add_argument("--json", action="store_true",
                           help="Stampa il risultato come JSON invece che come "
                                "rapporto leggibile.")
    argomenti.add_argument("--confronta", action="store_true",
                           help="Mostra i due motori di estrazione affiancati "
                                "sullo stesso paziente, invece della catena "
                                "completa. Richiede Ollama (o --motore openrouter).")
    argomenti.add_argument("--quante", type=int, default=6,
                           help="Quante classi proporre.")
    opzioni = argomenti.parse_args()

    if opzioni.elenco:
        print("Pazienti d'esempio (tutti sintetici):\n")
        for i, e in enumerate(ESEMPI, 1):
            print(f"  {i}. {e.titolo}")
            paragrafo(f"mostra: {e.mostra}", "     ")
        return

    if opzioni.interattivo:
        print("Incolla l'ANAMNESI, poi una riga vuota:")
        anamnesi = leggi_blocco()
        print("\nIncolla la TERAPIA ALL'INGRESSO, poi una riga vuota:")
        terapia = leggi_blocco()
    elif opzioni.anamnesi:
        anamnesi = opzioni.anamnesi.read_text(encoding="utf-8").strip()
        terapia = (opzioni.terapia.read_text(encoding="utf-8").strip()
                   if opzioni.terapia else "")
    else:
        indice = (opzioni.esempio or 1) - 1
        if not 0 <= indice < len(ESEMPI):
            print(f"Esempio inesistente. Ce ne sono {len(ESEMPI)}; "
                  f"usa --elenco per vederli.")
            raise SystemExit(2)
        esempio = ESEMPI[indice]
        if not opzioni.json:
            titolo(f"ESEMPIO {indice + 1} — {esempio.titolo}")
            paragrafo(f"Mostra: {esempio.mostra}")
        anamnesi, terapia = esempio.anamnesi, esempio.terapia_ingresso

    if not anamnesi.strip():
        print("Anamnesi vuota: non c'e' niente da estrarre.")
        raise SystemExit(2)

    if opzioni.json:
        import json

        print(json.dumps(analizza(anamnesi, terapia, opzioni.motore,
                                  opzioni.quante, opzioni.modello,
                                  opzioni.traccia),
                         ensure_ascii=False, indent=1))
    elif opzioni.confronta:
        motore = opzioni.motore if opzioni.motore != "deterministico" else "locale"
        confronta_motori(anamnesi, terapia, motore, opzioni.modello)
    else:
        esegui(anamnesi, terapia, opzioni.motore, opzioni.quante,
               opzioni.modello, opzioni.traccia)


def leggi_blocco() -> str:
    """Legge righe finche' non ne arriva una vuota (o finisce l'ingresso)."""
    righe: list[str] = []
    while True:
        try:
            riga = input()
        except EOFError:
            break
        if not riga.strip():
            break
        righe.append(riga)
    return "\n".join(righe)


if __name__ == "__main__":
    main()
