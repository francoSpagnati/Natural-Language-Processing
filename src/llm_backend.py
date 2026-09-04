"""Accesso ai modelli linguistici, isolato dietro un'interfaccia astratta.

Perche' un'astrazione e non chiamate dirette
--------------------------------------------
La pipeline B usa un LLM, ma il resto del progetto non deve dipendere ne' dal
fornitore ne' dalla rete. Tre esigenze concrete lo impongono:

1. i test devono girare senza chiamate remote e senza chiave (`BackendFittizio`);
2. la valutazione dello step 11 deve essere riproducibile, quindi le risposte
   vanno messe in cache su disco e riusate invece di essere richieste di nuovo;
3. il fornitore puo' cambiare: qui si usa Google AI Studio perche' l'API
   Anthropic non rientra nel piano a disposizione.

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
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{modello}:generateContent"

# 429 = quota esaurita, 5xx = capacita' del servizio. Entrambi transitori: durante
# le prove il 503 e' comparso di frequente e su modelli diversi nello stesso minuto.
CODICI_RITENTABILI = frozenset({429, 500, 502, 503, 504})


class ErroreLLM(RuntimeError):
    """Chiamata fallita in modo definitivo, dopo aver esaurito i ritentativi."""


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


class BackendLLM(ABC):
    """Interfaccia minima che la pipeline B usa per parlare con un modello."""

    @abstractmethod
    def genera(self, richiesta: Richiesta) -> Risposta:
        """Restituisce la risposta del modello, gia' decodificata da JSON."""


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
        self.cartella_cache = cartella_cache
        self.tentativi_massimi = tentativi_massimi
        self.attesa_iniziale = attesa_iniziale
        self.timeout = timeout
        if self.cartella_cache is not None:
            self.cartella_cache.mkdir(parents=True, exist_ok=True)

    # -- cache -------------------------------------------------------------

    def _percorso_cache(self, impronta: str) -> Path | None:
        if self.cartella_cache is None:
            return None
        return self.cartella_cache / f"{impronta}.json"

    def _leggi_cache(self, impronta: str) -> Risposta | None:
        percorso = self._percorso_cache(impronta)
        if percorso is None or not percorso.exists():
            return None
        salvato = json.loads(percorso.read_text(encoding="utf-8"))
        return Risposta(
            contenuto=salvato["contenuto"],
            modello=salvato.get("modello", self.modello),
            token_ingresso=salvato.get("token_ingresso", 0),
            token_uscita=salvato.get("token_uscita", 0),
            token_ragionamento=salvato.get("token_ragionamento", 0),
            da_cache=True,
        )

    def _scrivi_cache(self, impronta: str, risposta: Risposta) -> None:
        percorso = self._percorso_cache(impronta)
        if percorso is None:
            return
        percorso.write_text(
            json.dumps(
                {
                    "modello": risposta.modello,
                    "contenuto": risposta.contenuto,
                    "token_ingresso": risposta.token_ingresso,
                    "token_uscita": risposta.token_uscita,
                    "token_ragionamento": risposta.token_ragionamento,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

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
        in_cache = self._leggi_cache(impronta)
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
                self._scrivi_cache(impronta, risposta)
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
