"""Step 10 - L'host MCP locale: il secondo client, quello che non paga e non esce.

Claude Code e' il client comodo, ma e' remoto: il risultato di uno strumento
viene mandato a un modello che gira altrove. Questo secondo client chiude il
cerchio — **modello locale, server locale, dati locali** — e serve a tre cose
che il primo non puo' dare.

1. **Dimostra che il server non e' legato a un fornitore.** Il protocollo MCP e'
   uno standard: se gli strumenti funzionano con `qwen3.5:4b` su una macchina
   senza GPU, funzionano con qualunque host conforme.
2. **Rende misurabile il costo dell'orchestrazione.** Un giro di chiamata a
   strumento con il modello locale si cronometra qui, senza spendere.
3. **E' l'unica configurazione in cui un referto potrebbe entrare senza uscire
   dalla macchina.** Non la usiamo — il server non espone il corpus, per la
   ragione scritta in `mcp_server.py` — ma e' la strada aperta se un domani
   servisse.

## Perche' il ciclo e' scritto a mano

Sono sessanta righe invece di un framework, e valgono la stessa scelta gia'
fatta allo step 5 per il ciclo di addestramento: ogni passaggio resta visibile.
Qui in particolare si vede **quante volte il modello chiama uno strumento**,
**con quali argomenti**, e **quanto ci mette**, che sono le tre cose che un
lettore vuole poter contestare.

## Uso

    python3 src/mcp_client_locale.py "Paziente con scompenso cardiaco. Che terapia?"
    python3 src/mcp_client_locale.py --strumenti          # elenca e basta
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]

MODELLO = "qwen3.5:4b"
GIRI_MASSIMI = 6

ISTRUZIONI = (
    "Sei un assistente per cardiologi, in italiano. Hai strumenti che "
    "interrogano un sistema deterministico: usali invece di rispondere a "
    "memoria, perche' le tue risposte non sono verificabili e le loro si'. "
    "Quando proponi una terapia riporta la fonte che lo strumento ti da'. "
    "Non inventare codici ATC o ICD: se ti serve un codice, cercalo. "
    "Il testo clinico e' gia' nel messaggio dell'utente: non chiederglielo di "
    "nuovo. Quando TU lo passi a uno strumento, copialo dal messaggio "
    "carattere per carattere, senza riassumerlo: una riscrittura cambia i "
    "fatti (misurato: «iperteso» e' diventato «ipotensione»)."
)


def _normalizza(testo: str) -> str:
    """Minuscole, spazi compressi, punteggiatura via: cio' che resta e' il contenuto."""
    import re

    return re.sub(r"[^\w]+", " ", testo.lower()).strip()


def testo_fedele(passato: str, originale: str) -> bool:
    """Il testo passato allo strumento e' un pezzo di quello dell'utente?

    E' il controllo a valle contro la parafrasi. Non puo' impedirla — il modello
    scrive quello che vuole — ma la rende **visibile**: misurato, una parafrasi
    ha trasformato «iperteso» in «Ipotensione», e senza questo controllo nessuno
    se ne sarebbe accorto. Il confronto e' su testo normalizzato, cosi' una
    maiuscola o una virgola in piu' non contano come riscrittura.
    """
    return _normalizza(passato) in _normalizza(originale)


def _compatta(argomenti: dict, larghezza: int = 38) -> str:
    """Gli argomenti veri, accorciati: e' cio' che si vuole poter contestare.

    Stampare solo i nomi dei parametri nasconde proprio l'errore piu' comune di
    un modello piccolo — chiamare lo strumento giusto con l'argomento sbagliato,
    o lo stesso due volte.
    """
    parti = []
    for chiave, valore in argomenti.items():
        testo = str(valore).replace("\n", " ")
        if len(testo) > larghezza:
            testo = testo[:larghezza - 1] + "…"
        parti.append(f"{chiave}={testo!r}")
    return ", ".join(parti)


def _schema_per_ollama(strumenti) -> list[dict]:
    """Traduce l'elenco MCP nel formato che `ollama.chat` si aspetta.

    Sono due dialetti della stessa idea (nome, descrizione, JSON Schema degli
    argomenti); la traduzione e' tutta qui, in un punto solo, cosi' se uno dei
    due cambia si vede subito dove.
    """
    return [{
        "type": "function",
        "function": {
            "name": s.name,
            "description": (s.description or "").strip(),
            "parameters": s.input_schema,
        },
    } for s in strumenti]


async def conversa(domanda: str, modello: str = MODELLO,
                   verboso: bool = True) -> dict:
    """Un giro completo: elenco strumenti, chiamate, risposta finale."""
    import ollama
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parametri = StdioServerParameters(
        command=sys.executable,
        args=[str(RADICE / "src" / "mcp_server.py")],
    )

    chiamate: list[dict] = []
    gia_viste: set[tuple[str, str]] = set()
    secondi_totali = 0.0
    async with stdio_client(parametri) as (lettura, scrittura):
        async with ClientSession(lettura, scrittura) as sessione:
            await sessione.initialize()
            elenco = (await sessione.list_tools()).tools
            strumenti = _schema_per_ollama(elenco)
            if verboso:
                print(f"Strumenti offerti dal server: {len(elenco)}")
                for s in elenco:
                    print(f"  - {s.name}")
                print()

            messaggi: list[dict] = [
                {"role": "system", "content": ISTRUZIONI},
                {"role": "user", "content": domanda},
            ]

            for giro in range(GIRI_MASSIMI):
                avvio = time.time()
                risposta = ollama.chat(model=modello, messages=messaggi,
                                       tools=strumenti, think=False)
                secondi = time.time() - avvio
                secondi_totali += secondi
                messaggio = risposta["message"]
                messaggi.append(messaggio)
                richieste = messaggio.get("tool_calls") or []
                if verboso:
                    print(f"[giro {giro + 1}] {secondi:.1f}s, "
                          f"{len(richieste)} chiamate a strumenti")

                if not richieste:
                    return {"risposta": messaggio.get("content", ""),
                            "chiamate": chiamate, "giri": giro + 1,
                            "secondi": secondi_totali}

                for richiesta in richieste:
                    nome = richiesta["function"]["name"]
                    argomenti = richiesta["function"]["arguments"]
                    if isinstance(argomenti, str):
                        argomenti = json.loads(argomenti or "{}")
                    if verboso:
                        print(f"          -> {nome}("
                              f"{_compatta(argomenti)})")

                    # Un modello piccolo puo' rifare la stessa chiamata giro
                    # dopo giro senza accorgersene: e' successo sul serio, su
                    # una domanda scritta in forma telegrafica. Ripetere la
                    # stessa risposta lo lascerebbe nel ciclo fino ai giri
                    # massimi; dirglielo e' l'unica informazione nuova che si
                    # puo' dare, e costa una riga.
                    # Controllo a valle: se lo strumento riceve un'anamnesi, deve
                    # essere un pezzo del testo dell'utente, non una riscrittura.
                    fedele = None
                    if "anamnesi" in argomenti and isinstance(argomenti["anamnesi"], str):
                        fedele = testo_fedele(argomenti["anamnesi"], domanda)
                        if not fedele and verboso:
                            print("          !! anamnesi PARAFRASATA: il testo passato "
                                  "non e' contenuto in quello dell'utente")

                    firma = (nome, json.dumps(argomenti, sort_keys=True))
                    if firma in gia_viste:
                        testo = (f"Hai gia' chiamato {nome} con questi stessi "
                                 "argomenti e la risposta e' quella di prima. "
                                 "Usa un altro strumento, oppure rispondi con "
                                 "cio' che hai gia'.")
                        chiamate.append({"strumento": nome,
                                         "argomenti": argomenti,
                                         "ripetuta": True,
                                         "caratteri_risposta": len(testo)})
                        messaggi.append({"role": "tool", "content": testo,
                                         "tool_name": nome})
                        continue
                    gia_viste.add(firma)

                    try:
                        esito = await sessione.call_tool(nome, argomenti)
                        testo = "\n".join(c.text for c in esito.content
                                          if getattr(c, "text", None))
                    except Exception as errore:      # noqa: BLE001
                        # Un errore torna al modello come contenuto, non come
                        # eccezione: e' l'unica forma in cui puo' correggersi,
                        # ed e' cio' che il protocollo si aspetta.
                        testo = f"errore dallo strumento: {errore}"
                    if fedele is False:
                        # Al modello si dice che ha riscritto: e' l'unica
                        # informazione che puo' fargli ripassare il testo vero.
                        testo += ("\n\nAVVISO DEL CLIENT: l'anamnesi che hai passato "
                                  "non coincide con il testo dell'utente. Ripeti la "
                                  "chiamata copiando il testo alla lettera.")
                    chiamate.append({"strumento": nome, "argomenti": argomenti,
                                     "caratteri_risposta": len(testo),
                                     **({} if fedele is None else {"testo_fedele": fedele})})
                    messaggi.append({"role": "tool", "content": testo,
                                     "tool_name": nome})

    return {"risposta": "(nessuna risposta finale entro i giri previsti)",
            "chiamate": chiamate, "giri": GIRI_MASSIMI, "secondi": secondi_totali}


async def elenca() -> list[str]:
    """Solo l'handshake: verifica che il server parli il protocollo."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parametri = StdioServerParameters(
        command=sys.executable,
        args=[str(RADICE / "src" / "mcp_server.py")])
    async with stdio_client(parametri) as (lettura, scrittura):
        async with ClientSession(lettura, scrittura) as sessione:
            await sessione.initialize()
            return [s.name for s in (await sessione.list_tools()).tools]


def main() -> None:
    argomenti = argparse.ArgumentParser(
        description="Host MCP locale: un modello su ollama usa gli strumenti "
                    "del server cardio.")
    argomenti.add_argument("domanda", nargs="?", default=None)
    argomenti.add_argument("--modello", default=MODELLO)
    argomenti.add_argument("--strumenti", action="store_true",
                           help="Elenca gli strumenti e esci.")
    opzioni = argomenti.parse_args()

    if opzioni.strumenti or not opzioni.domanda:
        for nome in asyncio.run(elenca()):
            print(nome)
        return

    esito = asyncio.run(conversa(opzioni.domanda, opzioni.modello))
    print("\n--- risposta ---")
    print(esito["risposta"])
    print(f"\n{len(esito['chiamate'])} chiamate a strumenti in "
          f"{esito['giri']} giri.")


if __name__ == "__main__":
    main()
