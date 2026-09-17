"""Accesso ai modelli linguistici dietro un'interfaccia comune, con cache su disco.

Tre backend con la stessa interfaccia e la stessa cache: Gemini (AI Studio),
Ollama in locale, OpenRouter (protocollo OpenAI); piu' `BackendFittizio` per i
test. Tutto con `urllib`: una POST JSON, senza SDK. Ogni risposta e' vincolata
a uno JSON Schema. Scelte, protocolli e misure: docs/04_pipeline_estrazione_B.md.
"""

from __future__ import annotations

import hashlib
import http.client
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

# Scelto per disponibilita' misurata (docs/04), non perche' il piu' recente.
MODELLO_PREDEFINITO = "gemini-3.5-flash"

# Modello locale: con 11 GiB di RAM e senza GPU il tetto e' ~4 miliardi di parametri.
MODELLO_LOCALE_PREDEFINITO = "qwen3:4b"
OLLAMA_HOST = "http://127.0.0.1:11434"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{modello}:generateContent"

# Modello OpenRouter predefinito: dichiara `structured_outputs` (verificato su /api/v1/models).
ENDPOINT_OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
MODELLO_OPENROUTER_PREDEFINITO = "deepseek/deepseek-v4.1-flash"

# Guasti transitori da ritentare. `HTTPException` copre `IncompleteRead`, che
# non discende da `URLError`; non si cattura `OSError` intero (file mancanti
# non sono guasti di rete).
ERRORI_DI_RETE = (
    urllib.error.URLError,
    http.client.HTTPException,
    ConnectionError,
    TimeoutError,
    json.JSONDecodeError,
)

CODICI_RITENTABILI = frozenset({429, 500, 502, 503, 504})


class ErroreLLM(RuntimeError):
    """Chiamata fallita in modo definitivo, dopo aver esaurito i ritentativi."""


class ErroreRitentabile(ErroreLLM):
    """Risposta inutilizzabile per una ragione transitoria (troncata, `finish_reason=error`): si ritenta."""


class ErroreQuotaGiornaliera(ErroreLLM):
    """Quota giornaliera esaurita: a differenza degli altri 429, ritentare non serve."""


def _dettagli_errore(corpo: str) -> tuple[bool, float | None]:
    """Legge un corpo di errore 429: (quota giornaliera esaurita, attesa suggerita dall'API)."""
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
    """Legge la chiave dall'ambiente, con ripiego su `.env.local` (non versionato)."""
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
    """Una domanda al modello; `schema` e' lo JSON Schema a cui la risposta e' vincolata."""

    istruzioni: str
    testo: str
    schema: dict
    temperatura: float = 0.0
    livello_ragionamento: str = "low"

    def impronta(self, modello: str) -> str:
        """Chiave di cache: modello e ogni parametro che cambia la risposta."""
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
    # Costo dichiarato dal fornitore, conservato in cache: non si ristima da un listino.
    costo: float = 0.0


class BackendLLM(ABC):
    """Interfaccia minima che la pipeline B usa per parlare con un modello."""

    @abstractmethod
    def genera(self, richiesta: Richiesta) -> Risposta:
        """Restituisce la risposta del modello, gia' decodificata da JSON."""


class CacheRisposte:
    """Risposte su disco per impronta della richiesta, condivisa fra i backend: niente doppi pagamenti, valutazione ripetibile."""

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
            except ERRORI_DI_RETE as errore:
                ultimo_errore = ErroreLLM(f"{type(errore).__name__}: {errore}")
            else:
                risposta = self._interpreta(grezza, tentativo, time.monotonic() - avvio)
                self.cache.scrivi(impronta, risposta)
                return risposta

            if tentativo < self.tentativi_massimi:
                # Attesa suggerita dall'API, altrimenti esponenziale con jitter.
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
            # JSON troncato (MAX_TOKENS o blocco): meglio fallire che propagarlo.
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
    """Backend su un modello locale via Ollama; lo schema va nel campo `format`. Inferenza su CPU: timeout generoso."""

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
        # Ragionamento (qwen3): su CPU decide se la corsa dura ore o giorni.
        # Accetta anche le stringhe della riga di comando.
        if isinstance(ragionamento, str):
            ragionamento = False if ragionamento in ("no", "") else ragionamento
        self.ragionamento = ragionamento

    def _corpo(self, richiesta: Richiesta) -> dict:
        # Istruzioni nel prompt, non in `system`: con `format` attivo il campo
        # `system` di Ollama non arriva al modello (misurato, docs/04).
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
                # Modello assente o richiesta malformata: non si ritenta.
                raise ErroreLLM(f"HTTP {errore.code}: {dettaglio}") from errore
            except ERRORI_DI_RETE as errore:
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
    """Aggiunge `additionalProperties: false` a ogni oggetto (modalita' strict). Non toglie `maxItems`, di proposito."""
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
    """Backend su OpenRouter (protocollo OpenAI): un conto, molti modelli.

    `provider.require_parameters` e' essenziale: senza, la richiesta puo'
    finire a un fornitore che ignora `response_format` e restituisce JSON non
    vincolato. Protocollo: https://openrouter.ai/docs/features/structured-outputs.
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
        # Ragionamento spento: con `response_format` attivo alcuni modelli
        # tornano `content` vuoto.
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
                # 402 = credito esaurito: non si ritenta.
                if errore.code == 402:
                    raise ErroreQuotaGiornaliera(
                        f"Credito OpenRouter esaurito: {dettaglio[:200]}"
                    ) from errore
                if errore.code not in CODICI_RITENTABILI:
                    raise ultimo_errore from errore
            except ERRORI_DI_RETE as errore:
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
        # OpenRouter riporta gli errori del fornitore anche dentro un 200.
        if "error" in grezza and not grezza.get("choices"):
            raise ErroreLLM(f"Errore dal fornitore: {json.dumps(grezza['error'])[:300]}")

        scelte = grezza.get("choices") or []
        if not scelte:
            raise ErroreLLM(f"Risposta senza scelte: {json.dumps(grezza)[:300]}")

        scelta = scelte[0]
        motivo = scelta.get("finish_reason")
        if motivo not in (None, "stop"):
            # `length` o `error` danno un JSON monco: transitorio, si ritenta.
            raise ErroreRitentabile(f"Generazione interrotta (finish_reason={motivo}).")

        testo = (scelta.get("message") or {}).get("content") or ""
        if not testo.strip():
            raise ErroreRitentabile("Risposta con contenuto vuoto.")
        try:
            contenuto = json.loads(testo)
        except json.JSONDecodeError as errore:
            # JSON malformato con `response_format` attivo = generazione interrotta.
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
    """Backend per i test: `risposte` e' un dizionario per testo o una funzione; le richieste restano in `ricevute`."""

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
