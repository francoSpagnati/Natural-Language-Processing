"""Accesso ai modelli linguistici, isolato dietro un'interfaccia astratta.

Perche' un'astrazione e non chiamate dirette
--------------------------------------------
La pipeline B usa un LLM, ma il resto del progetto non deve dipendere ne' dal
fornitore ne' dalla rete. Tre esigenze concrete lo impongono:

1. i test devono girare senza chiamate remote e senza chiave (`BackendFittizio`);
2. la valutazione dello step 11 deve essere riproducibile, quindi le risposte
   vanno messe in cache su disco e riusate invece di essere richieste di nuovo;
3. il fornitore puo' cambiare, e in questo progetto e' cambiato tre volte:
   Google AI Studio (gratuito ma 20 richieste al giorno), Ollama in locale
   (gratuito ma 235 secondi per record), OpenRouter (a consumo, ma l'intero
   corpus costa poco piu' di un dollaro). I tre backend hanno la stessa
   interfaccia e la stessa cache, quindi lo step 6 puo' confrontarli a parita'
   di prompt senza che il resto della pipeline se ne accorga.

Perche' `urllib` e non un SDK
-----------------------------
Il protocollo usato e' una singola POST JSON. Farla con la libreria standard
tiene il formato del messaggio visibile nel codice invece che nascosto dentro
una dipendenza, coerentemente con `fetch_external_kb.py`, ed evita di legare la
riproducibilita' dei risultati alla versione di un pacchetto esterno. Il costo e'
una trentina di righe fra ritentativi e decodifica degli errori.

Fonte del protocollo
--------------------
Google AI Studio -- Gemini API, endpoint `v1beta/models/{modello}:generateContent`
con `generationConfig.responseJsonSchema` per l'output vincolato a schema
(https://ai.google.dev/gemini-api/docs/structured-output). Forma della richiesta,
nomi dei campi e comportamento di `thinkingConfig` sono stati verificati contro
l'API reale, non dedotti dalla documentazione: vedi `docs/04_pipeline_estrazione_B.md`.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

RADICE = Path(__file__).resolve().parents[1]
PERCORSO_ENV = RADICE / ".env.local"
CARTELLA_CACHE = RADICE / "data" / "interim" / "cache_llm"

# Scelto per disponibilita' misurata, non per essere il piu' recente: su una
# raffica di prove ravvicinate gemini-3.8-flash ha risposto 1 volta su 4 e
# gemini-3.7-flash 2 su 4, mentre gemini-3.5-flash 4 su 4. Su una corsa di
# centinaia di record la reperibilita' conta piu' della versione, e restare
# su un modello stabile (non "preview") tiene i risultati confrontabili nel
# tempo. Si puo' comunque sceglierne un altro con --modello.
MODELLO_PREDEFINITO = "gemini-3.5-flash"

# Modello locale. La macchina ha 11 GiB di RAM e nessuna GPU utilizzabile,
# quindi il tetto pratico e' un modello da ~4 miliardi di parametri
# quantizzato: gemma2:9b (5,4 GB) ha fatto intervenire l'OOM killer.
MODELLO_LOCALE_PREDEFINITO = "qwen3:4b"
OLLAMA_HOST = "http://127.0.0.1:11434"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{modello}:generateContent"

# OpenRouter espone dietro un'unica chiave i modelli di molti fornitori con il
# protocollo di OpenAI. Serve a questo progetto per un motivo preciso: e' l'unico
# modo di provare piu' modelli sullo stesso prompt senza aprire un conto con
# ciascun fornitore. Il modello predefinito e' scelto perche' dichiara
# `structured_outputs` fra i parametri supportati (verificato interrogando
# https://openrouter.ai/api/v1/models): senza decodifica vincolata questa
# pipeline perde la proprieta' su cui e' costruita.
ENDPOINT_OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
MODELLO_OPENROUTER_PREDEFINITO = "deepseek/deepseek-v4.1-flash"

# 429 = quota esaurita, 5xx = capacita' del servizio. Entrambi transitori: durante
# le prove il 503 e' comparso di frequente e su modelli diversi nello stesso minuto.
CODICI_RITENTABILI = frozenset({429, 500, 502, 503, 504})


class ErroreLLM(RuntimeError):
    """Chiamata fallita in modo definitivo, dopo aver esaurito i ritentativi."""


class ErroreRitentabile(ErroreLLM):
    """Risposta inutilizzabile per una ragione transitoria del fornitore.

    Va distinta da un errore definitivo: una risposta troncata a meta' di una
    stringa, o chiusa con `finish_reason=error`, non dice che la richiesta e'
    sbagliata — dice che quella singola generazione e' andata male. Sulla corsa
    da 200 record ne sono capitate due, e **rilanciando sono riuscite entrambe
    al primo colpo**, il che e' la prova che erano transitorie. Prima questo
    errore usciva dal ciclo dei ritentativi e serviva una mano.
    """


class ErroreQuotaGiornaliera(ErroreLLM):
    """La quota giornaliera del modello e' esaurita.

    Va distinta dagli altri 429: un limite al minuto si supera aspettando, uno
    al giorno no. Ritentare sarebbe tempo perso e maschererebbe la vera causa,
    quindi questo errore interrompe la corsa invece di essere assorbito.
    """


def _dettagli_errore(corpo: str) -> tuple[bool, float | None]:
    """Legge un corpo di errore 429: (quota giornaliera esaurita, attesa suggerita).

    L'API indica nei dettagli sia la quota violata sia da quanto tempo riprovare.
    Usare l'attesa che suggerisce e' piu' affidabile che indovinarla con un
    ritardo esponenziale, che puo' essere tanto troppo corto quanto troppo lungo.
    """
    try:
        errore = json.loads(corpo).get("error", {})
    except json.JSONDecodeError:
        return False, None

    giornaliera = False
    attesa = None
    for dettaglio in errore.get("details", []):
        tipo = dettaglio.get("@type", "")
        if tipo.endswith("QuotaFailure"):
            for violazione in dettaglio.get("violations", []):
                if "PerDay" in violazione.get("quotaId", ""):
                    giornaliera = True
        elif tipo.endswith("RetryInfo"):
            testo = str(dettaglio.get("retryDelay", "")).rstrip("s")
            try:
                attesa = float(testo)
            except ValueError:
                attesa = None
    return giornaliera, attesa


def chiave_api(nome_variabile: str = "GEMINI_API_KEY") -> str:
    """Legge la chiave dall'ambiente, con ripiego su `.env.local` non versionato.

    La chiave non compare mai nel codice ne' nei file versionati: `.env.local` e'
    escluso da git.
    """
    valore = os.environ.get(nome_variabile)
    if valore:
        return valore
    if PERCORSO_ENV.exists():
        for riga in PERCORSO_ENV.read_text(encoding="utf-8").splitlines():
            riga = riga.strip()
            if not riga or riga.startswith("#") or "=" not in riga:
                continue
            nome, _, val = riga.partition("=")
            if nome.strip() == nome_variabile:
                return val.strip().strip("'\"")
    raise ErroreLLM(
        f"Chiave assente: definisci {nome_variabile} nell'ambiente "
        f"oppure in {PERCORSO_ENV.name}."
    )


@dataclass(frozen=True)
class Richiesta:
    """Una domanda al modello, con la forma della risposta attesa.

    `schema` e' uno JSON Schema: il modello e' vincolato a produrre un JSON che
    lo rispetta, quindi la risposta non puo' essere malformata per costruzione e
    la pipeline non ha bisogno di ripescare il JSON dentro del testo libero.
    """

    istruzioni: str
    testo: str
    schema: dict
    temperatura: float = 0.0
    livello_ragionamento: str = "low"

    def impronta(self, modello: str) -> str:
        """Identificatore stabile della richiesta, usato come chiave di cache.

        Include il modello e ogni parametro che possa cambiare la risposta: se si
        modifica il prompt o si cambia modello la cache si invalida da sola.
        """
        materiale = json.dumps(
            {
                "modello": modello,
                "istruzioni": self.istruzioni,
                "testo": self.testo,
                "schema": self.schema,
                "temperatura": self.temperatura,
                "livello_ragionamento": self.livello_ragionamento,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(materiale.encode("utf-8")).hexdigest()


@dataclass
class Risposta:
    """Esito di una chiamata, con i contatori che servono a stimarne il costo."""

    contenuto: dict
    modello: str
    token_ingresso: int = 0
    token_uscita: int = 0
    token_ragionamento: int = 0
    tentativi: int = 1
    da_cache: bool = False
    secondi: float = 0.0
    # Costo in dollari dichiarato dal fornitore, quando lo dichiara. Tenerlo
    # nella risposta (e nella cache) evita di doverlo ristimare dai token con
    # un listino che nel frattempo puo' essere cambiato.
    costo: float = 0.0


class BackendLLM(ABC):
    """Interfaccia minima che la pipeline B usa per parlare con un modello."""

    @abstractmethod
    def genera(self, richiesta: Richiesta) -> Risposta:
        """Restituisce la risposta del modello, gia' decodificata da JSON."""


class CacheRisposte:
    """Risposte del modello su disco, indicizzate per impronta della richiesta.

    Serve a due cose diverse che si sostengono a vicenda: non ripagare (in
    denaro o in ore di CPU) una risposta gia' ottenuta, e rendere **ripetibile**
    la valutazione dello step 11, che altrimenti dipenderebbe da una generazione
    non deterministica.

    E' condivisa fra i backend: passare dal modello remoto a quello locale non
    deve cambiare il modo in cui i risultati vengono conservati.
    """

    def __init__(self, cartella: Path | None) -> None:
        self.cartella = cartella
        if self.cartella is not None:
            self.cartella.mkdir(parents=True, exist_ok=True)

    def leggi(self, impronta: str, modello: str) -> Risposta | None:
        if self.cartella is None:
            return None
        percorso = self.cartella / f"{impronta}.json"
        if not percorso.exists():
            return None
        salvato = json.loads(percorso.read_text(encoding="utf-8"))
        return Risposta(
            contenuto=salvato["contenuto"],
            modello=salvato.get("modello", modello),
            token_ingresso=salvato.get("token_ingresso", 0),
            token_uscita=salvato.get("token_uscita", 0),
            token_ragionamento=salvato.get("token_ragionamento", 0),
            costo=salvato.get("costo", 0.0),
            da_cache=True,
        )

    def scrivi(self, impronta: str, risposta: Risposta) -> None:
        if self.cartella is None:
            return
        (self.cartella / f"{impronta}.json").write_text(
            json.dumps(
                {
                    "modello": risposta.modello,
                    "contenuto": risposta.contenuto,
                    "token_ingresso": risposta.token_ingresso,
                    "token_uscita": risposta.token_uscita,
                    "token_ragionamento": risposta.token_ragionamento,
                    "costo": risposta.costo,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


class BackendGemini(BackendLLM):
    """Backend su Google AI Studio, con cache su disco e ritentativi."""

    def __init__(
        self,
        modello: str = MODELLO_PREDEFINITO,
        chiave: str | None = None,
        cartella_cache: Path | None = CARTELLA_CACHE,
        tentativi_massimi: int = 5,
        attesa_iniziale: float = 2.0,
        timeout: float = 120.0,
    ) -> None:
        self.modello = modello
        self._chiave = chiave or chiave_api()
        self.cache = CacheRisposte(cartella_cache)
        self.tentativi_massimi = tentativi_massimi
        self.attesa_iniziale = attesa_iniziale
        self.timeout = timeout

    # -- chiamata ----------------------------------------------------------

    def _corpo(self, richiesta: Richiesta) -> dict:
        return {
            "systemInstruction": {"parts": [{"text": richiesta.istruzioni}]},
            "contents": [{"role": "user", "parts": [{"text": richiesta.testo}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": richiesta.schema,
                "temperature": richiesta.temperatura,
                "thinkingConfig": {"thinkingLevel": richiesta.livello_ragionamento},
            },
        }

    def _invia(self, corpo: dict) -> dict:
        domanda = urllib.request.Request(
            ENDPOINT.format(modello=self.modello),
            data=json.dumps(corpo, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._chiave,
            },
            method="POST",
        )
        with urllib.request.urlopen(domanda, timeout=self.timeout) as risposta:
            return json.loads(risposta.read().decode("utf-8"))

    def genera(self, richiesta: Richiesta) -> Risposta:
        impronta = richiesta.impronta(self.modello)
        in_cache = self.cache.leggi(impronta, self.modello)
        if in_cache is not None:
            return in_cache

        corpo = self._corpo(richiesta)
        avvio = time.monotonic()
        ultimo_errore: Exception | None = None

        for tentativo in range(1, self.tentativi_massimi + 1):
            attesa_suggerita: float | None = None
            try:
                grezza = self._invia(corpo)
            except urllib.error.HTTPError as errore:
                with errore:
                    corpo_errore = errore.read().decode("utf-8", errors="replace")
                ultimo_errore = ErroreLLM(f"HTTP {errore.code}: {corpo_errore[:300]}")
                if errore.code == 429:
                    giornaliera, suggerita = _dettagli_errore(corpo_errore)
                    if giornaliera:
                        raise ErroreQuotaGiornaliera(
                            f"Quota giornaliera esaurita per {self.modello}."
                        ) from errore
                    attesa_suggerita = suggerita
                if errore.code not in CODICI_RITENTABILI:
                    raise ultimo_errore from errore
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as errore:
                ultimo_errore = ErroreLLM(f"{type(errore).__name__}: {errore}")
            else:
                risposta = self._interpreta(grezza, tentativo, time.monotonic() - avvio)
                self.cache.scrivi(impronta, risposta)
                return risposta

            if tentativo < self.tentativi_massimi:
                # Se l'API dice quanto aspettare, si aspetta quello. Altrimenti
                # attesa esponenziale con jitter: senza il termine casuale piu'
                # richieste respinte insieme ritenterebbero all'unisono.
                if attesa_suggerita is not None:
                    time.sleep(attesa_suggerita + random.uniform(0, 1))
                else:
                    attesa = self.attesa_iniziale * (2 ** (tentativo - 1))
                    time.sleep(attesa + random.uniform(0, attesa / 2))

        raise ErroreLLM(
            f"{self.tentativi_massimi} tentativi falliti su {self.modello}: {ultimo_errore}"
        )

    def _interpreta(self, grezza: dict, tentativi: int, secondi: float) -> Risposta:
        candidati = grezza.get("candidates") or []
        if not candidati:
            raise ErroreLLM(f"Risposta senza candidati: {json.dumps(grezza)[:300]}")

        candidato = candidati[0]
        motivo = candidato.get("finishReason")
        if motivo not in (None, "STOP"):
            # MAX_TOKENS o un blocco di sicurezza producono JSON troncato: meglio
            # fallire qui che propagare un'estrazione parziale silenziosamente.
            raise ErroreLLM(f"Generazione interrotta ({motivo}).")

        parti = candidato.get("content", {}).get("parts") or []
        testo = "".join(p.get("text", "") for p in parti if not p.get("thought"))
        try:
            contenuto = json.loads(testo)
        except json.JSONDecodeError as errore:
            raise ErroreLLM(f"JSON non valido nella risposta: {errore}") from errore

        uso = grezza.get("usageMetadata", {})
        return Risposta(
            contenuto=contenuto,
            modello=self.modello,
            token_ingresso=uso.get("promptTokenCount", 0),
            token_uscita=uso.get("candidatesTokenCount", 0),
            token_ragionamento=uso.get("thoughtsTokenCount", 0),
            tentativi=tentativi,
            secondi=secondi,
        )


class BackendOllama(BackendLLM):
    """Backend su un modello eseguito in locale tramite Ollama.

    Stessa interfaccia e stessa cache del backend remoto: la pipeline non sa
    quale dei due sta usando, e i due sono confrontabili a parita' di prompt.

    Anche qui la generazione e' **vincolata allo schema**: Ollama accetta uno
    JSON Schema nel campo `format` e lo impone al decodificatore, quindi un
    modello locale piccolo non puo' comunque produrre JSON malformato. E' la
    ragione per cui la pipeline regge il passaggio a un modello molto meno
    capace: la struttura e' garantita dal motore, non dalla bravura del modello.

    Vincoli reali della macchina su cui gira: l'inferenza e' su CPU (il
    rilevamento della GPU integrata fallisce) e la memoria disponibile e' poca,
    quindi il timeout predefinito e' generoso e il servizio va tenuto sotto un
    limite di memoria -- vedi `docs/04_pipeline_estrazione_B.md`.
    """

    def __init__(
        self,
        modello: str = MODELLO_LOCALE_PREDEFINITO,
        host: str = OLLAMA_HOST,
        cartella_cache: Path | None = CARTELLA_CACHE,
        tentativi_massimi: int = 3,
        attesa_iniziale: float = 2.0,
        timeout: float = 1800.0,
        contesto: int = 8192,
        ragionamento: bool | str = False,
    ) -> None:
        self.modello = modello
        self.host = host.rstrip("/")
        self.cache = CacheRisposte(cartella_cache)
        self.tentativi_massimi = tentativi_massimi
        self.attesa_iniziale = attesa_iniziale
        self.timeout = timeout
        self.contesto = contesto
        # I modelli a ragionamento ibrido (qwen3) altrimenti spendono la maggior
        # parte dei token generati a pensare. Su CPU e' il costo che decide se
        # una corsa sul dataset dura ore o giorni.
        #
        # Accetta anche le stringhe della riga di comando ("no", "low", "high")
        # perche' prima le ignorava in silenzio: il registro di una corsa
        # dichiarava `ragionamento: "low"` mentre il modello girava senza, e
        # l'impronta della configurazione registrava l'intenzione invece di cio'
        # che ha raggiunto il modello.
        if isinstance(ragionamento, str):
            ragionamento = False if ragionamento in ("no", "") else ragionamento
        self.ragionamento = ragionamento

    def _corpo(self, richiesta: Richiesta) -> dict:
        # Le istruzioni vanno nel prompt, non nel campo `system`. Misurato sullo
        # stesso record con qwen3:4b: con le istruzioni in `system` il modello
        # genera 39 token e restituisce liste vuote; con le stesse identiche
        # istruzioni in testa al prompt ne genera 3.063 e trova 40 condizioni e
        # 6 farmaci. Il campo `system` di Ollama non raggiunge il modello in modo
        # efficace, almeno con questo template e in presenza di `format`.
        return {
            "model": self.modello,
            "prompt": f"{richiesta.istruzioni}\n\nREFERTI DEL RICOVERO:\n{richiesta.testo}",
            "format": richiesta.schema,
            "stream": False,
            "think": self.ragionamento,
            "options": {
                "temperature": richiesta.temperatura,
                "num_ctx": self.contesto,
            },
        }

    def _invia(self, corpo: dict) -> dict:
        domanda = urllib.request.Request(
            f"{self.host}/api/generate",
            data=json.dumps(corpo, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(domanda, timeout=self.timeout) as risposta:
            return json.loads(risposta.read().decode("utf-8"))

    def genera(self, richiesta: Richiesta) -> Risposta:
        impronta = richiesta.impronta(self.modello)
        in_cache = self.cache.leggi(impronta, self.modello)
        if in_cache is not None:
            return in_cache

        corpo = self._corpo(richiesta)
        avvio = time.monotonic()
        ultimo_errore: Exception | None = None

        for tentativo in range(1, self.tentativi_massimi + 1):
            try:
                grezza = self._invia(corpo)
            except urllib.error.HTTPError as errore:
                with errore:
                    dettaglio = errore.read().decode("utf-8", errors="replace")[:300]
                # Un modello assente o una richiesta malformata non migliorano
                # ritentando: meglio dirlo subito e con il messaggio del server.
                raise ErroreLLM(f"HTTP {errore.code}: {dettaglio}") from errore
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as errore:
                ultimo_errore = ErroreLLM(f"{type(errore).__name__}: {errore}")
            else:
                risposta = self._interpreta(grezza, tentativo, time.monotonic() - avvio)
                self.cache.scrivi(impronta, risposta)
                return risposta

            if tentativo < self.tentativi_massimi:
                attesa = self.attesa_iniziale * (2 ** (tentativo - 1))
                time.sleep(attesa + random.uniform(0, attesa / 2))

        raise ErroreLLM(
            f"{self.tentativi_massimi} tentativi falliti su {self.modello}: {ultimo_errore}"
        )

    def _interpreta(self, grezza: dict, tentativi: int, secondi: float) -> Risposta:
        testo = grezza.get("response", "")
        if not testo.strip():
            motivo = grezza.get("done_reason", "sconosciuto")
            raise ErroreLLM(f"Risposta vuota dal modello locale (done_reason={motivo}).")
        try:
            contenuto = json.loads(testo)
        except json.JSONDecodeError as errore:
            raise ErroreLLM(f"JSON non valido nella risposta: {errore}") from errore

        return Risposta(
            contenuto=contenuto,
            modello=self.modello,
            token_ingresso=grezza.get("prompt_eval_count", 0),
            token_uscita=grezza.get("eval_count", 0),
            tentativi=tentativi,
            secondi=secondi,
        )


def schema_stretto(schema: dict) -> dict:
    """Rende uno JSON Schema accettabile dalla modalita' `strict`.

    La modalita' strict del protocollo OpenAI pretende `additionalProperties:
    false` su **ogni** oggetto, altrimenti rifiuta la richiesta con un 400. Lo
    schema generato da Pydantic non lo mette, quindi va aggiunto qui invece che
    sporcare i modelli del dominio con un dettaglio di un fornitore.

    Che cosa questa funzione NON fa, deliberatamente: non toglie `maxItems`. Il
    tetto di 60 elementi e' una delle correzioni che hanno eliminato i timeout
    della corsa locale, e non e' fra le parole chiave che il sottoinsieme strict
    garantisce. Toglierlo in silenzio perderebbe la protezione senza dirlo;
    lasciarlo fa emergere il problema come errore esplicito alla prima
    richiesta, dove lo si vede. Il pre-volo serve anche a questo.
    """
    if not isinstance(schema, dict):
        return schema

    fuori = {}
    for chiave, valore in schema.items():
        if isinstance(valore, dict):
            fuori[chiave] = schema_stretto(valore)
        elif isinstance(valore, list):
            fuori[chiave] = [schema_stretto(v) for v in valore]
        else:
            fuori[chiave] = valore

    if fuori.get("type") == "object":
        fuori.setdefault("additionalProperties", False)
        # Strict pretende che ogni proprieta' dichiarata sia anche richiesta.
        if "properties" in fuori:
            fuori["required"] = list(fuori["properties"])
    return fuori


class BackendOpenRouter(BackendLLM):
    """Backend su OpenRouter, protocollo OpenAI, con cache e ritentativi.

    Perche' OpenRouter e non l'API del singolo fornitore
    ----------------------------------------------------
    Lo step 6 confronta metodi di estrazione. Per confrontare piu' modelli sullo
    stesso prompt servirebbe un conto presso ciascun fornitore; qui ne basta uno,
    e il codice della pipeline non cambia fra un modello e l'altro. Il ricarico
    e' irrilevante ai volumi di questo progetto (l'intero corpus costa poco piu'
    di un dollaro sul modello predefinito).

    Il dettaglio che conta piu' del prezzo
    --------------------------------------
    OpenRouter instrada la stessa richiesta a fornitori diversi, e non tutti
    applicano `response_format`. Un fornitore che lo ignora restituisce comunque
    una risposta: JSON plausibile, prodotto senza vincolo, e **la pipeline non se
    ne accorgerebbe**. `provider.require_parameters` impedisce l'instradamento
    verso chi non supporta i parametri della richiesta. Senza quel campo la
    garanzia strutturale su cui e' costruita la pipeline B diventa una speranza.

    Fonte del protocollo
    --------------------
    https://openrouter.ai/docs/features/structured-outputs (forma di
    `response_format` e `provider.require_parameters`) e
    https://openrouter.ai/docs/use-cases/reasoning-tokens (campo `reasoning`).
    I nomi dei parametri supportati da ciascun modello sono verificabili su
    https://openrouter.ai/api/v1/models, campo `supported_parameters`.
    """

    def __init__(
        self,
        modello: str = MODELLO_OPENROUTER_PREDEFINITO,
        chiave: str | None = None,
        cartella_cache: Path | None = CARTELLA_CACHE,
        tentativi_massimi: int = 5,
        attesa_iniziale: float = 2.0,
        timeout: float = 300.0,
        ragionamento: bool | str = False,
    ) -> None:
        self.modello = modello
        self._chiave = chiave or chiave_api("OPENROUTER_API_KEY")
        self.cache = CacheRisposte(cartella_cache)
        self.tentativi_massimi = tentativi_massimi
        self.attesa_iniziale = attesa_iniziale
        self.timeout = timeout
        if isinstance(ragionamento, str):
            ragionamento = False if ragionamento in ("no", "") else ragionamento
        self.ragionamento = ragionamento

    def _corpo(self, richiesta: Richiesta) -> dict:
        # Il ragionamento e' spento per impostazione. Non e' una scelta di costo:
        # su piu' modelli e' documentato che, con `response_format` attivo, il
        # vincolo dello schema finisce applicato al canale di ragionamento e
        # `content` torna vuoto. Spento, il problema non si pone.
        corpo = {
            "model": self.modello,
            "messages": [
                {"role": "system", "content": richiesta.istruzioni},
                {"role": "user", "content": richiesta.testo},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "estrazione",
                    "strict": True,
                    "schema": schema_stretto(richiesta.schema),
                },
            },
            "provider": {"require_parameters": True},
            "temperature": richiesta.temperatura,
        }
        if self.ragionamento:
            corpo["reasoning"] = {"enabled": True, "effort": self.ragionamento}
        else:
            corpo["reasoning"] = {"enabled": False}
        return corpo

    def _invia(self, corpo: dict) -> dict:
        domanda = urllib.request.Request(
            ENDPOINT_OPENROUTER,
            data=json.dumps(corpo, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._chiave}",
            },
            method="POST",
        )
        with urllib.request.urlopen(domanda, timeout=self.timeout) as risposta:
            return json.loads(risposta.read().decode("utf-8"))

    def genera(self, richiesta: Richiesta) -> Risposta:
        impronta = richiesta.impronta(self.modello)
        in_cache = self.cache.leggi(impronta, self.modello)
        if in_cache is not None:
            return in_cache

        corpo = self._corpo(richiesta)
        avvio = time.monotonic()
        ultimo_errore: Exception | None = None

        for tentativo in range(1, self.tentativi_massimi + 1):
            try:
                grezza = self._invia(corpo)
            except urllib.error.HTTPError as errore:
                with errore:
                    dettaglio = errore.read().decode("utf-8", errors="replace")
                ultimo_errore = ErroreLLM(f"HTTP {errore.code}: {dettaglio[:400]}")
                # 402 = credito esaurito. Come la quota giornaliera di Gemini:
                # ritentare non lo ricarica, e insistere maschererebbe la causa.
                if errore.code == 402:
                    raise ErroreQuotaGiornaliera(
                        f"Credito OpenRouter esaurito: {dettaglio[:200]}"
                    ) from errore
                if errore.code not in CODICI_RITENTABILI:
                    raise ultimo_errore from errore
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as errore:
                ultimo_errore = ErroreLLM(f"{type(errore).__name__}: {errore}")
            else:
                try:
                    risposta = self._interpreta(grezza, tentativo, time.monotonic() - avvio)
                except ErroreRitentabile as errore:
                    ultimo_errore = errore
                else:
                    self.cache.scrivi(impronta, risposta)
                    return risposta

            if tentativo < self.tentativi_massimi:
                attesa = self.attesa_iniziale * (2 ** (tentativo - 1))
                time.sleep(attesa + random.uniform(0, attesa / 2))

        raise ErroreLLM(
            f"{self.tentativi_massimi} tentativi falliti su {self.modello}: {ultimo_errore}"
        )

    def _interpreta(self, grezza: dict, tentativi: int, secondi: float) -> Risposta:
        # OpenRouter riporta anche gli errori del fornitore dentro una risposta
        # 200, in un campo `error`. Senza questo controllo finirebbero in
        # `json.loads` come contenuto mancante, con un messaggio incomprensibile.
        if "error" in grezza and not grezza.get("choices"):
            raise ErroreLLM(f"Errore dal fornitore: {json.dumps(grezza['error'])[:300]}")

        scelte = grezza.get("choices") or []
        if not scelte:
            raise ErroreLLM(f"Risposta senza scelte: {json.dumps(grezza)[:300]}")

        scelta = scelte[0]
        motivo = scelta.get("finish_reason")
        if motivo not in (None, "stop"):
            # Mai propagare un'estrazione parziale come se fosse completa: sia
            # `length` (uscita troncata) sia `error` (guasto del fornitore)
            # danno un JSON monco. Sono pero' transitori, quindi si ritenta.
            raise ErroreRitentabile(f"Generazione interrotta (finish_reason={motivo}).")

        testo = (scelta.get("message") or {}).get("content") or ""
        if not testo.strip():
            raise ErroreRitentabile("Risposta con contenuto vuoto.")
        try:
            contenuto = json.loads(testo)
        except json.JSONDecodeError as errore:
            # Con `response_format` attivo un JSON malformato non puo' venire da
            # un errore del modello: viene da una generazione interrotta a meta'.
            raise ErroreRitentabile(f"JSON non valido nella risposta: {errore}") from errore

        uso = grezza.get("usage") or {}
        dettagli = uso.get("completion_tokens_details") or {}
        return Risposta(
            contenuto=contenuto,
            modello=grezza.get("model") or self.modello,
            token_ingresso=uso.get("prompt_tokens", 0),
            token_uscita=uso.get("completion_tokens", 0),
            token_ragionamento=dettagli.get("reasoning_tokens", 0),
            costo=float(uso.get("cost") or 0.0),
            tentativi=tentativi,
            secondi=secondi,
        )


class BackendFittizio(BackendLLM):
    """Backend deterministico per i test: nessuna rete, nessuna chiave.

    `risposte` puo' essere un dizionario indicizzato per testo, oppure una
    funzione che riceve la `Richiesta` e restituisce il contenuto. Le richieste
    ricevute restano in `ricevute`, cosi' i test possono verificare cosa e' stato
    effettivamente chiesto al modello.
    """

    def __init__(
        self,
        risposte: dict[str, dict] | Callable[[Richiesta], dict],
        modello: str = "fittizio",
    ) -> None:
        self._risposte = risposte
        self.modello = modello
        self.ricevute: list[Richiesta] = []

    def genera(self, richiesta: Richiesta) -> Risposta:
        self.ricevute.append(richiesta)
        if callable(self._risposte):
            contenuto = self._risposte(richiesta)
        else:
            if richiesta.testo not in self._risposte:
                raise ErroreLLM("Il backend fittizio non ha una risposta per questo testo.")
            contenuto = self._risposte[richiesta.testo]
        return Risposta(contenuto=contenuto, modello=self.modello)
