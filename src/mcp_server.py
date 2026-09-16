"""Step 10 - Il server MCP: il sistema diventa uno strumento per un altro agente.

Fino allo step 9 il sistema si usa da riga di comando. Qui diventa uno
**strumento che un modello conversazionale puo' chiamare**, e questo cambia due
cose che valgono piu' del codice.

## 1. Solo lettura, e non e' una cautela: e' il vincolo dello step 8

Nessuno strumento qui scrive, addestra o decide. Il filtro di sicurezza e'
simbolico per vincolo — «mai LLM, mai dataset» — e un modello che potesse
modificare le regole, il grafo o l'insieme candidato scavalcherebbe l'unico
strato che stabilisce che cosa e' ammissibile. Tutti gli strumenti dichiarano
`read_only_hint=True`, che e' la forma in cui il protocollo MCP rende
verificabile quella promessa dal lato del client.

Lo step 9 ha gia' mostrato come si rompe: vincolato all'insieme candidato, il
modello locale ha comunque nominato 40 codici fuori elenco, 15 dei quali non
esistono nel registro ATC dell'AIFA. Un codice che non esiste non puo' essere ne'
vietato ne' verificato. Qui la difesa e' la stessa: il modello **chiede**, il
codice deterministico **risponde**.

## 2. Il corpus non passa di qui

Gli strumenti lavorano solo su testo che l'utente incolla, mai sui 1 000 referti
di `data/raw/`. La ragione e' che un client MCP puo' essere remoto: Claude Code
manda il risultato di uno strumento a un modello che gira altrove, e un tool che
leggesse un referto per `enc_oid` spedirebbe testo clinico fuori dalla macchina
senza che nessuno se ne accorga.

E' la stessa regola del grafo dello step 7, applicata a un'altra frontiera: il
testo clinico non entra nelle triple, e non entra nemmeno in una risposta MCP.
Del corpus escono solo **aggregati** (`cardio_statistiche_corpus`), che non
identificano nessuno.

## Trasporto

stdio, non HTTP. Il server gira sulla macchina di Carlo e i dati che indicizza
non escono dal disco: stdio rende quella proprieta' vera per costruzione, invece
di affidarla alla configurazione di un firewall.

## Uso

    claude mcp add cardio -- python3 src/mcp_server.py

oppure, per l'host locale con ollama:

    python3 src/mcp_client_locale.py "Che terapia proporresti per ..."
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE / "src"))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

mcp = MCPServer(
    name="cardio_mcp",
    instructions=(
        "Supporto alla decisione terapeutica in cardiologia, in italiano. "
        "Tutti gli strumenti sono di sola lettura e lavorano sul testo che "
        "fornisci, non su un archivio di pazienti. Le proposte vengono da un "
        "ranker misurato e da indicazioni delle linee guida ESC citate una per "
        "una: non sono una prescrizione."
    ),
)

SOLA_LETTURA = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                               idempotent_hint=True, open_world_hint=False)

# La catena costa qualche secondo: legge 1 002 file JSON e addestra il ranker
# ibrido. Un server MCP risponde a molte chiamate nella stessa sessione, quindi
# la si paga una volta sola.
_CACHE: dict[str, object] = {}


def _catena():
    """Il modulo della demo, importato una volta sola.

    Lo step 9bis aveva gia' separato il calcolo dalla presentazione proprio
    perche' questo step potesse riusare `analizza` senza ricostruire nulla.
    """
    if "demo" not in _CACHE:
        import demo

        _CACHE["demo"] = demo
    return _CACHE["demo"]


@lru_cache(maxsize=32)
def _analisi(anamnesi: str, terapia_ingresso: str, con_traccia: bool) -> dict:
    """Una sola esecuzione della catena per coppia di testi.

    Il motore e' sempre quello deterministico: costa zero e lo step 6 lo ha
    misurato migliore del modello linguistico sui campi strutturati. Un server
    che chiamasse un LLM per rispondere a un LLM pagherebbe due volte la stessa
    estrazione.
    """
    return _catena().analizza(anamnesi, terapia_ingresso,
                              motore="deterministico", quante=8,
                              con_traccia=con_traccia)


@mcp.tool(
    name="cardio_proponi_terapia",
    annotations=SOLA_LETTURA,
    description=(
        "Da un'anamnesi e dalla terapia in atto, propone le classi di farmaci "
        "da aggiungere alla dimissione. Ogni proposta dichiara il proprio "
        "fondamento: `indicazione citata` (una linea guida ESC, con la fonte) "
        "oppure `co-occorrenza misurata` (nessuna regola: solo cio' che in quel "
        "reparto si prescrive insieme). Restituisce anche le condizioni "
        "codificate in ICD-10 e i farmaci riconosciuti in ATC, cosi' si vede su "
        "che cosa la proposta si fonda. "
        "FORMATO: le voci della terapia vanno separate da punto e virgola e "
        "ciascuna deve portare la dose: `Furosemide 25 mg; Ramipril 5 mg`. "
        "Senza dose la voce non viene letta. "
        "IMPORTANTE: il campo `anamnesi` va copiato dal messaggio dell'utente "
        "carattere per carattere, senza riassumere ne' riscrivere (non serve "
        "chiederlo di nuovo all'utente). Gli offset di provenienza si riferiscono "
        "al testo passato: una parafrasi indica parole che il clinico non ha "
        "scritto. Non e' una prescrizione."
    ),
)
def proponi_terapia(anamnesi: str, terapia_ingresso: str = "",
                    quante: int = 6) -> dict:
    """Propone le classi ATC da aggiungere.

    Args:
        anamnesi: il testo dell'anamnesi, in italiano.
        terapia_ingresso: le voci della terapia in atto, separate da `;`
            (per esempio `Furosemide 25 mg; Ramipril 5 mg`).
        quante: quante proposte restituire (1-15).
    """
    quante = max(1, min(int(quante), 15))
    esito = _analisi(anamnesi, terapia_ingresso, False)
    condizioni = [c for c in esito["condizioni"] if c["codice"]]
    farmaci = esito["farmaci"]

    # Il fondamento di ogni proposta, detto a parole invece che dedotto
    # dall'assenza di un campo. Un modello conversazionale che riceve una
    # proposta con `motivo: null` tende a **riempire il vuoto** con una
    # motivazione propria: misurato su questo server, `qwen3.5:4b` ha inventato
    # un «profilo nefroprotettivo» e ha chiamato A02BC «betabloccante
    # selettivo». Dire in chiaro che la proposta non ha una regola e' l'unica
    # difesa che il server puo' offrire, perche' la prosa finale non e' sua.
    proposte = []
    for p in esito["proposte"][:quante]:
        proposte.append({
            **p,
            "fondamento": ("indicazione citata" if p["classe_raccomandazione"]
                           else "co-occorrenza misurata nel corpus"),
            **({} if p["classe_raccomandazione"] else {
                "attenzione": ("Nessuna linea guida sostiene questa proposta: "
                               "viene dalla frequenza con cui in questo reparto "
                               "la classe compare insieme a questi fatti. Non "
                               "attribuirle una motivazione clinica che il "
                               "sistema non ha dato."),
            }),
        })

    fuori = {
        "condizioni": condizioni,
        "farmaci_ingresso": farmaci,
        "allergie": esito["allergie"],
        "candidati_ammessi": esito["candidati_ammessi"],
        "candidati_totali": esito["candidati_totali"],
        "proposte": proposte,
        "avvertenza": (
            "Ordinamento misurato: richiamo@5 del 53,1% sulle aggiunte reali di "
            "244 ricoveri. Il 40,4% delle prescrizioni di dimissione non e' "
            "cardiologia e nessuna linea guida cardiologica la regola: "
            "un'assenza qui non e' una controindicazione."
        ),
    }

    # Il principio del fatto mancante, che lo step 8 ha incontrato tre volte:
    # una risposta la cui premessa e' fallita non si presenta come se fosse
    # valida. Se non e' stato estratto nulla, le proposte sono il tasso di base
    # del reparto e non hanno niente a che vedere con questo paziente.
    note: list[str] = []
    if not condizioni:
        note.append("Nessuna condizione codificata dal testo: le proposte qui "
                    "sotto NON sono specifiche per questo paziente, sono le "
                    "classi piu' frequenti del reparto. Il gazetteer riconosce "
                    "le forme scritte per esteso: «ipertensione arteriosa» si', "
                    "«iperteso» no.")
    if terapia_ingresso.strip() and not farmaci:
        note.append("Nessun farmaco riconosciuto nella terapia. Il parser "
                    "vuole DUE cose: le voci separate da punto e virgola, e "
                    "**la dose dentro ogni voce**. `Furosemide, Ramipril` non "
                    "viene letto, e nemmeno `Furosemide; Ramipril`: serve "
                    "`Furosemide 25 mg; Ramipril 5 mg`. E' il formato del campo "
                    "«terapia all'ingresso» da cui il parser e' stato ricavato, "
                    "dove la dose c'e' sempre.")
    if note:
        fuori["fatti_mancanti"] = note
    return fuori


@mcp.tool(
    name="cardio_sostegno_del_concetto",
    annotations=SOLA_LETTURA,
    description=(
        "Da dove viene un fatto. Dato un codice ICD-10 o ATC estratto da un "
        "testo, restituisce la catena di provenienza interrogata in SPARQL sul "
        "knowledge graph: quale pipeline lo ha visto, con quale regola, e in "
        "quale punto del testo (offset di carattere). Serve a contestare una "
        "conclusione, non solo a crederle."
    ),
)
def sostegno_del_concetto(anamnesi: str, codice: str,
                          terapia_ingresso: str = "",
                          tipo: str = "condizione") -> dict:
    """La catena di provenienza di un concetto.

    Args:
        anamnesi: lo stesso testo passato a cardio_proponi_terapia.
        codice: il codice da giustificare, per esempio `I50.9` o `C07AB`.
        terapia_ingresso: le voci della terapia in atto, separate da `;`.
        tipo: `condizione` per un codice ICD-10, `farmaco` per un ATC.
    """
    if tipo not in ("condizione", "farmaco"):
        return {"errore": "tipo deve essere 'condizione' oppure 'farmaco'.",
                "tipo_ricevuto": tipo}

    from traccia import grafo_del_paziente, sostegno_del_concetto as sostegno

    demo = _catena()
    from ranker import nomi_atc, nomi_icd

    record = demo.paziente_da_testo(anamnesi, terapia_ingresso)
    stati = {"A": demo.estrai_deterministico(record)}
    g = grafo_del_paziente(stati, 0, nomi_icd(), nomi_atc())
    menzioni = sostegno(g, codice, tipo)
    if not menzioni:
        return {
            "codice": codice, "tipo": tipo, "menzioni": [],
            "nota": ("Nessuna menzione sostiene questo codice in questo testo. "
                     "Non significa che il fatto sia falso: significa che il "
                     "sistema non lo ha estratto."),
        }
    return {"codice": codice, "tipo": tipo, "triple_nel_grafo": len(g),
            "menzioni": menzioni}


@mcp.tool(
    name="cardio_verifica_sicurezza",
    annotations=SOLA_LETTURA,
    description=(
        "Chiede al filtro di sicurezza simbolico se un farmaco e' ammissibile "
        "per questo paziente. Tre esiti: ammesso, da_verificare, vietato — mai "
        "un si' o no secco, perche' un falso blocco nega una terapia e un falso "
        "permesso lascia passare una controindicazione. Ogni verdetto porta le "
        "sue regole con la fonte. `farmaco_atc` deve essere un CODICE ATC "
        "(C07AB, B01AC06), non un nome: per un nome usa prima cardio_cerca_codice."
    ),
)
def verifica_sicurezza(anamnesi: str, farmaco_atc: str,
                       terapia_ingresso: str = "") -> dict:
    """Il verdetto del filtro dello step 8 su un farmaco.

    Args:
        anamnesi: il testo dell'anamnesi, in italiano.
        farmaco_atc: il codice ATC del farmaco da verificare.
        terapia_ingresso: le voci della terapia in atto, separate da `;`.
    """
    import re

    from filtro import StatoPerFiltro, valuta
    from ranker import nomi_atc

    # Un verdetto la cui premessa e' fallita non si presenta come valido. Il
    # filtro confronta CODICI: una stringa che non e' un codice non incontra
    # nessuna regola e uscirebbe «ammesso» a vuoto — un falso permesso, che e'
    # l'errore peggiore di uno strato di sicurezza. Misurato: il modello locale
    # ha chiesto la sicurezza di «Bisoprololo» e «Spironolattone» per nome, e la
    # prima versione rispondeva ammesso a entrambi.
    codice = farmaco_atc.strip().upper()
    if "atc" not in _CACHE:
        _CACHE["atc"] = nomi_atc()
    if not re.fullmatch(r"[A-Z]\d{2}([A-Z]([A-Z](\d{2})?)?)?", codice) \
            or codice not in _CACHE["atc"]:
        return {
            "errore": ("`farmaco_atc` deve essere un codice ATC presente nel "
                       "registro AIFA (per esempio C07AB o C07AB07), non un nome. "
                       "Nessun verdetto emesso: cerca prima il codice con "
                       "cardio_cerca_codice."),
            "ricevuto": farmaco_atc,
        }

    demo = _catena()
    record = demo.paziente_da_testo(anamnesi, terapia_ingresso)
    stato = demo.estrai_deterministico(record)
    condizioni = [{"codice": c.codice, "testo": "", "agenti": ["demo"]}
                  for c in stato.condizioni
                  if c.codice and c.stato.value == "affermato"
                  and c.soggetto.value == "paziente"]
    allergie = {a.codice_atc for a in stato.allergie if a.codice_atc}
    terapia = {f.codice_atc for f in stato.farmaci
               if f.codice_atc and f.momento.value == "ingresso"}
    esito = valuta(StatoPerFiltro(0, condizioni, allergie, terapia),
                   codice, esclusa_dalla_terapia=codice)
    return {
        "farmaco_atc": codice, "nome": _CACHE["atc"].get(codice, ""),
        "esito": esito.esito.value,
        "motivi": esito.motivi,
        "condizioni_viste": sorted({c["codice"] for c in condizioni}),
        "allergie_viste": sorted(allergie),
        "nota": ("`da_verificare` non e' un divieto: e' una regola che "
                 "richiede un fatto che nessuna pipeline estrae, per esempio "
                 "la presenza di un pacemaker."),
    }


@mcp.tool(
    name="cardio_cerca_codice",
    annotations=SOLA_LETTURA,
    description=(
        "Cerca un codice ATC o ICD-10 per nome, o il nome di un codice. Le "
        "descrizioni vengono dalle knowledge base del progetto — registro ATC "
        "dell'AIFA e ICD-10 2019 Elenco Sistematico — non dalla memoria di un "
        "modello."
    ),
)
def cerca_codice(query: str, sistema: str = "atc", quanti: int = 10) -> dict:
    """Cerca nelle terminologie del progetto.

    Args:
        query: un codice (`C07AB`) o una parola del nome (`betabloccanti`).
        sistema: `atc` oppure `icd`.
        quanti: quanti risultati restituire (1-50).
    """
    from ranker import nomi_atc, nomi_icd

    # `ICD-10` e `ICD10` sono i nomi veri della classificazione: rifiutarli
    # costa un giro di modello per un cavillo lessicale. Misurato: il modello
    # locale ha speso una chiamata su `sistema='ICD-10'` prima di indovinare.
    ALIAS = {"atc": "atc", "icd": "icd", "icd-10": "icd", "icd10": "icd",
             "icd 10": "icd"}
    sistema = ALIAS.get(sistema.lower().strip(), sistema.lower().strip())
    if sistema not in ("atc", "icd"):
        return {"errore": "sistema deve essere 'atc' oppure 'icd'.",
                "sistema_ricevuto": sistema}
    quanti = max(1, min(int(quanti), 50))
    chiave = f"nomi_{sistema}"
    if chiave not in _CACHE:
        _CACHE[chiave] = nomi_atc() if sistema == "atc" else nomi_icd()
    nomi: dict[str, str] = _CACHE[chiave]  # type: ignore[assignment]

    q = query.strip().lower()
    esatti = [{"codice": c, "nome": n} for c, n in nomi.items() if c.lower() == q]
    per_prefisso = [{"codice": c, "nome": n} for c, n in sorted(nomi.items())
                    if c.lower().startswith(q) and c.lower() != q]
    per_nome = [{"codice": c, "nome": n} for c, n in sorted(nomi.items())
                if q in n.lower()]
    risultati = (esatti + per_prefisso + per_nome)[:quanti]
    return {
        "query": query, "sistema": sistema, "risultati": risultati,
        "fonte": ("AIFA - registro ATC, CC-BY 4.0" if sistema == "atc"
                  else "ICD-10 2019, Elenco Sistematico, edizione italiana"),
    }


@mcp.tool(
    name="cardio_statistiche_corpus",
    annotations=SOLA_LETTURA,
    description=(
        "I numeri misurati del progetto: dimensione del corpus, prestazioni dei "
        "ranker, esiti del filtro di sicurezza. Solo aggregati: nessun testo di "
        "referto esce da questo server."
    ),
)
def statistiche_corpus() -> dict:
    """Gli aggregati del progetto, letti dai file di risultato."""
    import json

    risultati = RADICE / "data" / "processed" / "ranker_step9.json"
    filtro = RADICE / "data" / "processed" / "filtro_step8.json"
    fuori: dict = {
        "referti": 1000,
        "con_terapia_di_dimissione_codificata": 841,
        "linea_di_base_continuita": ("copiare la terapia d'ingresso indovina "
                                     "il 63,6% della dimissione"),
        "tetto_di_dominio": ("il 40,4% delle prescrizioni di dimissione non e' "
                             "cardiologia"),
        "rumore_di_fondo": "differenze sotto i due punti percentuali non contano",
    }
    if risultati.exists():
        d = json.loads(risultati.read_text(encoding="utf-8"))
        fuori["ranker"] = [
            {"nome": r["nome"], "richiamo@5_aggiunte": r["aggiunte"]["richiamo@5"],
             "MAP_aggiunte": r["aggiunte"]["MAP"]}
            for r in d.get("risultati", [])
        ]
    if filtro.exists():
        d = json.loads(filtro.read_text(encoding="utf-8"))
        fuori["filtro"] = {k: v for k, v in d.items()
                           if isinstance(v, (int, float, str))}
    return fuori


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
