"""
Test della pipeline B (step 4): backend LLM, ancoraggio e conversione.

Girano tutti senza rete e senza chiave: il backend reale e' sostituito da
`BackendFittizio` e i risolutori da doppi minimi. E' una scelta deliberata --
una suite che dipendesse dall'API sarebbe lenta, costosa e verde o rossa a
seconda del carico dei server, quindi inutile come rete di sicurezza.

Cio' che qui si verifica non e' la bravura del modello, che non e'
deterministica, ma il contratto che gli sta intorno: che una citazione inventata
venga riconosciuta come tale, che il codice non provenga mai dal modello, e che
la cache non restituisca la risposta di una domanda diversa.
"""

import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import extract_b  # noqa: E402
import schema  # noqa: E402
from data_loading import RecordPaziente, Referto  # noqa: E402
from llm_backend import (  # noqa: E402
    BackendFittizio,
    BackendGemini,
    BackendOllama,
    BackendOpenRouter,
    ErroreLLM,
    ErroreQuotaGiornaliera,
    ErroreRitentabile,
    Richiesta,
    _dettagli_errore,
    schema_stretto,
)
from schema import (  # noqa: E402
    CampoReferto,
    EstrazioneLLM,
    MomentoTerapia,
    Pipeline,
    StatoConoscenza,
    StatoNormalizzazione,
    schema_estrazione_llm,
)
from pydantic import ValidationError  # noqa: E402


def record_di_prova(anamnesi="", ingresso="", dimissione=None) -> RecordPaziente:
    referti = [
        Referto("Anamnesi", None, None, anamnesi),
        Referto("Terapia medica all'ingresso", None, None, ingresso),
    ]
    if dimissione is not None:
        referti.append(Referto("Terapia alla Dimissione", None, None, dimissione))
    return RecordPaziente(enc_oid=1, referti=referti)


class RisolutoreATCFinto:
    """Conosce un solo farmaco: basta a distinguere risolto da NIL."""

    def risolvi(self, nome):
        if nome.strip().lower() == "bisoprololo":
            return "C07AB07", StatoNormalizzazione.RISOLTO, "AIFA"
        return None, StatoNormalizzazione.NIL, None

    def risolvi_menzione(self, menzione):
        codice, stato, fonte = self.risolvi(menzione)
        if stato is not StatoNormalizzazione.NIL:
            return codice, stato, fonte, menzione.strip()
        principio = menzione.partition("(")[0].strip()
        codice, stato, fonte = self.risolvi(principio)
        return codice, stato, fonte, principio if codice else menzione.strip()


class RisolutoreICDFinto:
    def risolvi(self, testo):
        from risolutori import EsitoICD

        chiave = testo.strip().lower()
        if chiave == "broncopneumopatia cronica ostruttiva":
            return EsitoICD(
                "J44.9", StatoNormalizzazione.RISOLTO, chiave, ("J44.9",), "termine_esatto"
            )
        if chiave == "cardiopatia ischemica":
            return EsitoICD(
                None, StatoNormalizzazione.AMBIGUO, chiave, ("I25.1", "I34.0"), "generalizzazione_ambigua"
            )
        return EsitoICD(None, StatoNormalizzazione.NIL, None, (), "non_risolto")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSchemaEstrazione(unittest.TestCase):
    def test_schema_senza_riferimenti_ne_default(self):
        """L'API rifiuta o ignora $ref e default: devono sparire prima dell'invio."""
        testo = json.dumps(schema_estrazione_llm())
        for chiave in ("$defs", "$ref", '"default"', '"title"'):
            self.assertNotIn(chiave, testo)

    def test_schema_conserva_le_descrizioni(self):
        """Le descrizioni sono istruzioni per il modello, non ornamento."""
        condizione = schema_estrazione_llm()["properties"]["condizioni"]["items"]
        self.assertIn("acronimi", condizione["properties"]["concetto"]["description"])

    def test_schema_non_prevede_codici(self):
        """Il vincolo di provenienza: il modello non ha un posto dove mettere un codice."""
        proprieta = schema_estrazione_llm()["properties"]
        for entita in ("condizioni", "farmaci"):
            campi = proprieta[entita]["items"]["properties"].keys()
            self.assertNotIn("codice", campi)
            self.assertNotIn("codice_atc", campi)


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


class TestImprontaRichiesta(unittest.TestCase):
    def _richiesta(self, **modifiche):
        base = {"istruzioni": "istr", "testo": "testo", "schema": {"type": "object"}}
        return Richiesta(**{**base, **modifiche})

    def test_impronta_stabile(self):
        self.assertEqual(
            self._richiesta().impronta("m"), self._richiesta().impronta("m")
        )

    def test_impronta_cambia_col_modello(self):
        """Cambiare modello deve invalidare la cache, non riusarne le risposte."""
        self.assertNotEqual(
            self._richiesta().impronta("modello-a"), self._richiesta().impronta("modello-b")
        )

    def test_impronta_cambia_col_prompt(self):
        self.assertNotEqual(
            self._richiesta().impronta("m"), self._richiesta(istruzioni="altre").impronta("m")
        )

    def test_impronta_cambia_col_ragionamento(self):
        self.assertNotEqual(
            self._richiesta().impronta("m"),
            self._richiesta(livello_ragionamento="high").impronta("m"),
        )


class TestCache(unittest.TestCase):
    """La cache e' cio' che rende ripetibile la valutazione: va verificata."""

    class BackendConteggio(BackendGemini):
        chiamate = 0

        def _invia(self, corpo):
            type(self).chiamate += 1
            return {
                "candidates": [
                    {"content": {"parts": [{"text": '{"ok": true}'}]}, "finishReason": "STOP"}
                ],
                "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 4},
            }

    def test_seconda_chiamata_non_tocca_la_rete(self):
        with tempfile.TemporaryDirectory() as cartella:
            self.BackendConteggio.chiamate = 0
            backend = self.BackendConteggio(
                modello="finto", chiave="x", cartella_cache=Path(cartella)
            )
            richiesta = Richiesta(istruzioni="i", testo="t", schema={"type": "object"})

            prima = backend.genera(richiesta)
            seconda = backend.genera(richiesta)

            self.assertEqual(self.BackendConteggio.chiamate, 1)
            self.assertFalse(prima.da_cache)
            self.assertTrue(seconda.da_cache)
            self.assertEqual(prima.contenuto, seconda.contenuto)

    def test_richiesta_diversa_non_riusa_la_cache(self):
        with tempfile.TemporaryDirectory() as cartella:
            self.BackendConteggio.chiamate = 0
            backend = self.BackendConteggio(
                modello="finto", chiave="x", cartella_cache=Path(cartella)
            )
            backend.genera(Richiesta(istruzioni="i", testo="uno", schema={}))
            backend.genera(Richiesta(istruzioni="i", testo="due", schema={}))
            self.assertEqual(self.BackendConteggio.chiamate, 2)



class TestQuota(unittest.TestCase):
    """La quota gratuita e' giornaliera, non al minuto: la distinzione conta.

    Un limite al minuto si supera aspettando; uno al giorno no. Trattarli allo
    stesso modo significa spendere minuti in ritentativi gia' persi e nascondere
    la vera causa dell'interruzione.
    """

    CORPO_GIORNALIERO = json.dumps(
        {
            "error": {
                "code": 429,
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {
                                "quotaId": (
                                    "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
                                ),
                                "quotaValue": "20",
                            }
                        ],
                    },
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "49s",
                    },
                ],
            }
        }
    )

    CORPO_AL_MINUTO = json.dumps(
        {
            "error": {
                "code": 429,
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {"quotaId": "GenerateRequestsPerMinutePerProject-FreeTier"}
                        ],
                    },
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "12s",
                    },
                ],
            }
        }
    )

    def test_riconosce_la_quota_giornaliera(self):
        giornaliera, attesa = _dettagli_errore(self.CORPO_GIORNALIERO)
        self.assertTrue(giornaliera)
        self.assertEqual(attesa, 49.0)

    def test_quota_al_minuto_non_e_giornaliera(self):
        giornaliera, attesa = _dettagli_errore(self.CORPO_AL_MINUTO)
        self.assertFalse(giornaliera)
        self.assertEqual(attesa, 12.0)

    def test_corpo_non_json(self):
        self.assertEqual(_dettagli_errore("<html>errore</html>"), (False, None))

    def test_quota_giornaliera_non_viene_ritentata(self):
        """Cinque ritentativi contro un limite giornaliero sono tempo buttato."""
        chiamate = []

        class BackendEsaurito(BackendGemini):
            def _invia(self, corpo):
                chiamate.append(corpo)
                raise _errore_http(429, TestQuota.CORPO_GIORNALIERO)

        backend = BackendEsaurito(modello="finto", chiave="x", cartella_cache=None)
        with self.assertRaises(ErroreQuotaGiornaliera):
            backend.genera(Richiesta(istruzioni="i", testo="t", schema={}))
        self.assertEqual(len(chiamate), 1)


def _errore_http(codice: int, corpo: str) -> urllib.error.HTTPError:
    """Un HTTPError con il corpo leggibile, come quelli che arrivano davvero."""
    return urllib.error.HTTPError(
        "https://esempio", codice, "errore", {}, io.BytesIO(corpo.encode("utf-8"))
    )


class TestInterpretazioneRisposta(unittest.TestCase):
    def _backend(self):
        return BackendGemini(modello="finto", chiave="x", cartella_cache=None)

    def test_generazione_troncata_e_un_errore(self):
        """Un JSON troncato per MAX_TOKENS non deve passare per estrazione parziale."""
        grezza = {
            "candidates": [
                {"content": {"parts": [{"text": '{"a":'}]}, "finishReason": "MAX_TOKENS"}
            ]
        }
        with self.assertRaises(ErroreLLM):
            self._backend()._interpreta(grezza, 1, 0.0)

    def test_le_parti_di_ragionamento_sono_escluse(self):
        """I token di pensiero non fanno parte della risposta da decodificare."""
        grezza = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "ragiono...", "thought": True},
                            {"text": '{"ok": 1}'},
                        ]
                    },
                    "finishReason": "STOP",
                }
            ]
        }
        self.assertEqual(self._backend()._interpreta(grezza, 1, 0.0).contenuto, {"ok": 1})

    def test_risposta_senza_candidati(self):
        with self.assertRaises(ErroreLLM):
            self._backend()._interpreta({}, 1, 0.0)


# ---------------------------------------------------------------------------
# Ancoraggio delle citazioni
# ---------------------------------------------------------------------------



class TestBackendLocale(unittest.TestCase):
    """Il backend locale deve essere intercambiabile con quello remoto.

    Non si verifica la bravura del modello ma il contratto: stessa interfaccia,
    stessa cache, schema imposto al decodificatore, e un errore leggibile quando
    la risposta non e' utilizzabile.
    """

    class BackendFinto(BackendOllama):
        risposte: list = []
        corpi: list = []

        def _invia(self, corpo):
            type(self).corpi.append(corpo)
            prossima = type(self).risposte.pop(0)
            # Una risposta puo' essere un'eccezione: serve a provare che i
            # guasti di rete vengono ritentati invece che propagati.
            if isinstance(prossima, Exception):
                raise prossima
            return prossima

    def _backend(self, risposte, **kw):
        self.BackendFinto.risposte = list(risposte)
        self.BackendFinto.corpi = []
        return self.BackendFinto(modello="finto", cartella_cache=None, **kw)

    def test_lo_schema_viene_imposto_al_decodificatore(self):
        """E' cio' che rende utilizzabile un modello locale piccolo: la validita'
        del JSON e' garantita dal motore, non sperata dal prompt."""
        backend = self._backend([{"response": '{"ok": true}', "eval_count": 4}])
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
        backend.genera(Richiesta(istruzioni="i", testo="t", schema=schema))
        self.assertEqual(self.BackendFinto.corpi[0]["format"], schema)

    def test_le_istruzioni_finiscono_nel_prompt(self):
        """Regressione. Con le istruzioni nel campo `system` di Ollama, qwen3:4b
        generava 39 token e restituiva liste vuote; con le stesse istruzioni in
        testa al prompt ne generava 3.063 e trovava 40 condizioni. Il campo
        `system` non deve essere usato."""
        backend = self._backend([{"response": "{}", "eval_count": 1}])
        backend.genera(Richiesta(istruzioni="REGOLE-QUI", testo="referto", schema={}))
        corpo = self.BackendFinto.corpi[0]
        self.assertNotIn("system", corpo)
        self.assertIn("REGOLE-QUI", corpo["prompt"])
        self.assertIn("referto", corpo["prompt"])

    def test_ragionamento_disattivato_per_impostazione(self):
        """Su CPU i token di pensiero decidono se una corsa dura ore o giorni."""
        backend = self._backend([{"response": "{}", "eval_count": 1}])
        backend.genera(Richiesta(istruzioni="i", testo="t", schema={}))
        self.assertFalse(self.BackendFinto.corpi[0]["think"])

    def test_conta_i_token(self):
        backend = self._backend(
            [{"response": "{}", "prompt_eval_count": 120, "eval_count": 340}]
        )
        risposta = backend.genera(Richiesta(istruzioni="i", testo="t", schema={}))
        self.assertEqual(risposta.token_ingresso, 120)
        self.assertEqual(risposta.token_uscita, 340)

    def test_risposta_vuota_e_un_errore(self):
        backend = self._backend([{"response": "", "done_reason": "length"}])
        with self.assertRaises(ErroreLLM):
            backend.genera(Richiesta(istruzioni="i", testo="t", schema={}))

    def test_condivide_la_cache_col_backend_remoto(self):
        """Stessa cache per i due motori: cambiare motore non cambia il modo in
        cui i risultati vengono conservati. Il modello entra nell'impronta,
        quindi le risposte dei due non si confondono."""
        with tempfile.TemporaryDirectory() as cartella:
            self.BackendFinto.risposte = [{"response": '{"a": 1}', "eval_count": 2}]
            self.BackendFinto.corpi = []
            backend = self.BackendFinto(
                modello="finto", cartella_cache=Path(cartella)
            )
            richiesta = Richiesta(istruzioni="i", testo="t", schema={})
            prima = backend.genera(richiesta)
            seconda = backend.genera(richiesta)
            self.assertEqual(len(self.BackendFinto.corpi), 1)
            self.assertTrue(seconda.da_cache)
            self.assertEqual(prima.contenuto, seconda.contenuto)


class TestSchemaStretto(unittest.TestCase):
    """La modalita' strict pretende uno schema di forma precisa.

    Senza `additionalProperties: false` su ogni oggetto la richiesta viene
    rifiutata con un 400, e lo schema che Pydantic genera non lo mette.
    """

    def test_aggiunge_additional_properties_a_ogni_oggetto(self):
        stretto = schema_stretto({
            "type": "object",
            "properties": {
                "voci": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"a": {"type": "string"}}},
                }
            },
        })
        self.assertFalse(stretto["additionalProperties"])
        self.assertFalse(stretto["properties"]["voci"]["items"]["additionalProperties"])

    def test_ogni_proprieta_diventa_obbligatoria(self):
        stretto = schema_stretto(
            {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}}
        )
        self.assertEqual(sorted(stretto["required"]), ["a", "b"])

    def test_non_tocca_lo_schema_originale(self):
        originale = {"type": "object", "properties": {"a": {"type": "string"}}}
        schema_stretto(originale)
        self.assertNotIn("additionalProperties", originale)

    def test_conserva_maxitems(self):
        """Il tetto di 60 elementi e' una delle correzioni che hanno eliminato i
        timeout: toglierlo in silenzio perderebbe la protezione senza dirlo."""
        stretto = schema_stretto(
            {"type": "object", "properties": {"v": {"type": "array", "maxItems": 60}}}
        )
        self.assertEqual(stretto["properties"]["v"]["maxItems"], 60)

    def test_lo_schema_vero_della_pipeline_resta_valido(self):
        stretto = schema_stretto(schema_estrazione_llm())
        self.assertFalse(stretto["additionalProperties"])
        for nome in ("condizioni", "farmaci", "allergie"):
            voce = stretto["properties"][nome]
            self.assertEqual(voce["maxItems"], 60)
            self.assertFalse(voce["items"]["additionalProperties"])


class TestBackendOpenRouter(unittest.TestCase):
    """Stesso contratto degli altri due backend, piu' il vincolo di instradamento."""

    class BackendFinto(BackendOpenRouter):
        risposte: list = []
        corpi: list = []

        def _invia(self, corpo):
            type(self).corpi.append(corpo)
            prossima = type(self).risposte.pop(0)
            # Una risposta puo' essere un'eccezione: serve a provare che i
            # guasti di rete vengono ritentati invece che propagati.
            if isinstance(prossima, Exception):
                raise prossima
            return prossima

    def _backend(self, risposte, **kw):
        self.BackendFinto.risposte = list(risposte)
        self.BackendFinto.corpi = []
        return self.BackendFinto(
            modello="finto", chiave="x", cartella_cache=None, **kw
        )

    @staticmethod
    def _ok(contenuto='{"ok": true}', **uso):
        return {
            "choices": [{"finish_reason": "stop", "message": {"content": contenuto}}],
            "usage": uso,
        }

    def test_una_risposta_troncata_viene_ritentata(self):
        """Regressione costata 490 record su 1 000.

        `IncompleteRead` — la connessione chiusa a meta' risposta — discende da
        `http.client.HTTPException` e NON da `URLError`. Il ciclo dei tentativi
        catturava solo la seconda famiglia, quindi il guasto piu' transitorio
        che esista usciva dal ciclo come se fosse definitivo e abbatteva la
        corsa dopo 75 minuti di lavoro.
        """
        import http.client

        backend = self._backend([http.client.IncompleteRead(b"met"), self._ok()])
        risposta = backend.genera(Richiesta(
            istruzioni="i", testo="t", schema={"type": "object"}))

        self.assertEqual(risposta.contenuto, {"ok": True})
        self.assertEqual(len(self.BackendFinto.corpi), 2)

    def test_una_connessione_chiusa_viene_ritentata(self):
        backend = self._backend([ConnectionResetError("reset"), self._ok()])
        risposta = backend.genera(Richiesta(
            istruzioni="i", testo="t", schema={"type": "object"}))

        self.assertEqual(risposta.contenuto, {"ok": True})

    def test_un_errore_che_non_e_di_rete_non_viene_ritentato(self):
        """Non si cattura `OSError` intero: un permesso negato e' un difetto da
        vedere subito, non un guasto da assorbire."""
        backend = self._backend([PermissionError("niente permessi"), self._ok()])

        with self.assertRaises(PermissionError):
            backend.genera(Richiesta(
                istruzioni="i", testo="t", schema={"type": "object"}))

    def test_lo_schema_viaggia_in_modalita_strict(self):
        backend = self._backend([self._ok()])
        backend.genera(Richiesta(
            istruzioni="i", testo="t",
            schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        ))
        formato = self.BackendFinto.corpi[0]["response_format"]
        self.assertEqual(formato["type"], "json_schema")
        self.assertTrue(formato["json_schema"]["strict"])
        self.assertFalse(formato["json_schema"]["schema"]["additionalProperties"])

    def test_instrada_solo_verso_chi_applica_i_parametri(self):
        """Il test che conta piu' di tutti gli altri.

        OpenRouter puo' servire la stessa richiesta da fornitori diversi, e non
        tutti applicano `response_format`. Uno che lo ignora restituisce
        comunque un JSON plausibile, generato senza vincolo, e nulla nella
        pipeline se ne accorgerebbe: la garanzia strutturale diventerebbe una
        speranza, in silenzio. `require_parameters` lo impedisce.
        """
        backend = self._backend([self._ok()])
        backend.genera(Richiesta(istruzioni="i", testo="t", schema={}))
        self.assertTrue(self.BackendFinto.corpi[0]["provider"]["require_parameters"])

    def test_ragionamento_disattivato_per_impostazione(self):
        """Con `response_format` attivo piu' modelli applicano il vincolo dello
        schema al canale di ragionamento e restituiscono `content` vuoto."""
        backend = self._backend([self._ok()])
        backend.genera(Richiesta(istruzioni="i", testo="t", schema={}))
        self.assertFalse(self.BackendFinto.corpi[0]["reasoning"]["enabled"])

    def test_conta_token_e_costo(self):
        backend = self._backend([self._ok(
            prompt_tokens=2700, completion_tokens=2100, cost=0.0014,
            completion_tokens_details={"reasoning_tokens": 0},
        )])
        r = backend.genera(Richiesta(istruzioni="i", testo="t", schema={}))
        self.assertEqual(r.token_ingresso, 2700)
        self.assertEqual(r.token_uscita, 2100)
        self.assertAlmostEqual(r.costo, 0.0014)

    def test_un_errore_dentro_una_risposta_200_e_un_errore(self):
        """OpenRouter riporta gli errori del fornitore dentro una 200."""
        backend = self._backend([{"error": {"message": "no capacity", "code": 503}}])
        with self.assertRaises(ErroreLLM):
            backend.genera(Richiesta(istruzioni="i", testo="t", schema={}))

    def test_generazione_troncata_non_viene_mai_propagata(self):
        """`length` produce JSON troncato: propagarlo darebbe un'estrazione
        parziale indistinguibile da una completa. E' pero' transitorio, quindi
        l'errore e' della classe che il ciclo dei ritentativi riprova."""
        backend = self._backend([
            {"choices": [{"finish_reason": "length", "message": {"content": "{"}}]}
        ], tentativi_massimi=1)
        with self.assertRaises(ErroreLLM):
            backend.genera(Richiesta(istruzioni="i", testo="t", schema={}))
        with self.assertRaises(ErroreRitentabile):
            backend._interpreta(
                {"choices": [{"finish_reason": "length", "message": {"content": "{"}}]}, 1, 0.0
            )

    def test_una_generazione_interrotta_viene_ritentata(self):
        """Regressione dalla corsa vera.

        Su 200 record due sono falliti — uno con JSON troncato a meta' di una
        stringa, uno con `finish_reason=error` — e **rilanciandoli sono riusciti
        entrambi al primo colpo**. Erano guasti transitori del fornitore, ma
        uscivano dal ciclo dei ritentativi e richiedevano una mano.
        """
        backend = self._backend([
            {"choices": [{"finish_reason": "error", "message": {"content": ""}}]},
            self._ok('{"a": 1}'),
        ], attesa_iniziale=0)
        risposta = backend.genera(Richiesta(istruzioni="i", testo="t", schema={}))
        self.assertEqual(risposta.contenuto, {"a": 1})
        self.assertEqual(risposta.tentativi, 2)

    def test_un_json_troncato_viene_ritentato(self):
        """Con `response_format` attivo un JSON malformato non puo' venire da un
        errore del modello: viene da una generazione interrotta a meta'."""
        backend = self._backend([
            self._ok('{"voci": [{"nome": "iperten'),
            self._ok('{"a": 1}'),
        ], attesa_iniziale=0)
        self.assertEqual(
            backend.genera(Richiesta(istruzioni="i", testo="t", schema={})).contenuto,
            {"a": 1},
        )

    def test_i_ritentativi_non_sono_infiniti(self):
        backend = self._backend(
            [{"choices": [{"finish_reason": "error", "message": {"content": ""}}]}] * 3,
            tentativi_massimi=3, attesa_iniziale=0,
        )
        with self.assertRaises(ErroreLLM):
            backend.genera(Richiesta(istruzioni="i", testo="t", schema={}))

    def test_condivide_la_cache_con_gli_altri_motori(self):
        with tempfile.TemporaryDirectory() as cartella:
            self.BackendFinto.risposte = [self._ok('{"a": 1}')]
            self.BackendFinto.corpi = []
            backend = self.BackendFinto(
                modello="finto", chiave="x", cartella_cache=Path(cartella)
            )
            richiesta = Richiesta(istruzioni="i", testo="t", schema={})
            prima = backend.genera(richiesta)
            seconda = backend.genera(richiesta)
            self.assertEqual(len(self.BackendFinto.corpi), 1)
            self.assertTrue(seconda.da_cache)
            self.assertEqual(prima.contenuto, seconda.contenuto)


class TestAncoraggio(unittest.TestCase):
    def test_citazione_esatta(self):
        self.assertEqual(extract_b.ancora("Paziente con diabete mellito.", "diabete"), (13, 20))

    def test_citazione_con_maiuscole_diverse(self):
        """L'unica difformita' tollerata: non cambia l'identita' della menzione."""
        inizio, fine = extract_b.ancora("Paziente con Diabete mellito.", "diabete")
        self.assertEqual((inizio, fine), (13, 20))

    def test_citazione_assente(self):
        self.assertEqual(extract_b.ancora("Paziente con diabete.", "ipertensione"), (None, None))

    def test_citazione_vuota(self):
        self.assertEqual(extract_b.ancora("qualcosa", "   "), (None, None))


# ---------------------------------------------------------------------------
# Conversione nello schema comune
# ---------------------------------------------------------------------------


class TestConversione(unittest.TestCase):
    def _converti(self, estrazione, **record):
        return extract_b.converti(
            record_di_prova(**record),
            estrazione,
            "modello-di-prova",
            RisolutoreATCFinto(),
            RisolutoreICDFinto(),
        )

    def test_acronimo_espanso_viene_codificato(self):
        """Il caso che la pipeline A non sa risolvere: BPCO non e' nel volume ICD."""
        stato = self._converti(
            EstrazioneLLM.model_validate(
                {
                    "condizioni": [
                        {
                            "testo_grezzo": "BPCO",
                            "concetto": "broncopneumopatia cronica ostruttiva",
                            "campo": "Anamnesi",
                            "stato": "affermato",
                        }
                    ]
                }
            ),
            anamnesi="Paziente con BPCO in ossigenoterapia.",
        )
        condizione = stato.condizioni[0]
        self.assertEqual(condizione.codice, "J44.9")
        self.assertEqual(condizione.stato_normalizzazione, StatoNormalizzazione.RISOLTO)
        self.assertEqual(condizione.provenienza.inizio, 13)

    def test_espansione_del_modello_sempre_tracciata(self):
        """Anche quando non risolve, cio' che il modello ha proposto resta visibile."""
        stato = self._converti(
            EstrazioneLLM.model_validate(
                {
                    "condizioni": [
                        {
                            "testo_grezzo": "FA",
                            "concetto": "fibrillazione atriale",
                            "campo": "Anamnesi",
                            "stato": "affermato",
                        }
                    ]
                }
            ),
            anamnesi="Riscontro di FA.",
        )
        self.assertIn("fibrillazione atriale", stato.condizioni[0].provenienza.regola)

    def test_condizione_ambigua_non_riceve_un_codice(self):
        stato = self._converti(
            EstrazioneLLM.model_validate(
                {
                    "condizioni": [
                        {
                            "testo_grezzo": "cardiopatia ischemica",
                            "concetto": "cardiopatia ischemica",
                            "campo": "Anamnesi",
                            "stato": "affermato",
                        }
                    ]
                }
            ),
            anamnesi="Nota cardiopatia ischemica.",
        )
        self.assertIsNone(stato.condizioni[0].codice)
        self.assertEqual(
            stato.condizioni[0].stato_normalizzazione, StatoNormalizzazione.AMBIGUO
        )

    def test_citazione_inventata_e_segnalata(self):
        """Il rilevatore di allucinazioni: senza ancoraggio niente offset e una nota."""
        stato = self._converti(
            EstrazioneLLM.model_validate(
                {
                    "condizioni": [
                        {
                            "testo_grezzo": "insufficienza mitralica severa",
                            "concetto": "insufficienza mitralica",
                            "campo": "Anamnesi",
                            "stato": "affermato",
                        }
                    ]
                }
            ),
            anamnesi="Paziente iperteso.",
        )
        condizione = stato.condizioni[0]
        self.assertIsNone(condizione.provenienza.inizio)
        self.assertIn("non ritrovata", condizione.provenienza.regola)
        self.assertTrue(any("non ritrovate" in n for n in stato.note_estrazione))

    def test_un_farmaco_del_modello_e_sempre_narrativo(self):
        """Il modello vede solo l'anamnesi, quindi ogni farmaco che segnala e'
        un farmaco raccontato, non una voce di terapia.

        Se dichiarasse un altro campo — lo schema ammette ancora i tre valori,
        perche' e' condiviso con le altre pipeline — la citazione verrebbe
        cercata nel campo sbagliato, dove potrebbe perfino trovarsi per caso.
        `campo_del_modello` rende quell'errore impossibile invece che raro.
        """
        stato = self._converti(
            EstrazioneLLM.model_validate(
                {
                    "farmaci": [
                        {
                            "testo_grezzo": "Bisoprololo",
                            "campo": "Terapia alla Dimissione",   # dichiarato a torto
                            "stato": "affermato",
                            "posologia": "2,5 mg/die",
                        }
                    ]
                }
            ),
            anamnesi="Bisoprololo sospeso per bradicardia.",
            dimissione="",
        )
        farmaco = next(f for f in stato.farmaci if f.provenienza.pipeline.value != "campo_strutturato")
        self.assertEqual(farmaco.momento, MomentoTerapia.NARRATIVO)
        self.assertEqual(farmaco.provenienza.campo_sorgente, "Anamnesi")
        self.assertIsNotNone(farmaco.provenienza.inizio)
        self.assertEqual(farmaco.codice_atc, "C07AB07")

    def test_negazione_conservata(self):
        stato = self._converti(
            EstrazioneLLM.model_validate(
                {
                    "condizioni": [
                        {
                            "testo_grezzo": "diabete",
                            "concetto": "diabete mellito",
                            "campo": "Anamnesi",
                            "stato": "negato",
                        }
                    ]
                }
            ),
            anamnesi="Nega diabete e ipertensione.",
        )
        self.assertEqual(stato.condizioni[0].stato, StatoConoscenza.NEGATO)

    def test_pipeline_dichiarata_in_ogni_provenienza(self):
        stato = self._converti(
            EstrazioneLLM.model_validate(
                {
                    "farmaci": [
                        {
                            "testo_grezzo": "Bisoprololo",
                            "campo": "Anamnesi",
                            "stato": "affermato",
                        }
                    ]
                }
            ),
            anamnesi="In terapia con Bisoprololo.",
        )
        self.assertEqual(stato.pipeline, Pipeline.B_LLM)
        self.assertEqual(stato.farmaci[0].provenienza.pipeline, Pipeline.B_LLM)

    def test_dimissione_assente_annotata(self):
        stato = self._converti(EstrazioneLLM(), anamnesi="Testo.")
        self.assertTrue(any("ground truth" in n for n in stato.note_estrazione))


# ---------------------------------------------------------------------------
# Composizione del prompt ed estrazione completa
# ---------------------------------------------------------------------------



@unittest.skipUnless(
    (Path(__file__).resolve().parent.parent / "data/interim/mappatura_atc.json").exists(),
    "mappatura ATC non generata",
)
class TestMenzioniComposte(unittest.TestCase):
    """Scomposizione di "principio (commerciale forma dose)", il formato del
    referto di dimissione. Sono i casi che hanno fatto salire la copertura ATC
    della pipeline B dal 59% all'87%: la stringa intera non risolve mai perche'
    il vocabolario ha voci separate per il principio e per il commerciale."""

    @classmethod
    def setUpClass(cls):
        from risolutori import RisolutoreATC

        cls.risolutore = RisolutoreATC()

    def test_menzione_composta_risolve_dal_principio_attivo(self):
        codice, stato, _, forma = self.risolutore.risolvi_menzione(
            "Furosemide (Lasix cpr. 25 mg)"
        )
        self.assertEqual(codice, "C03CA01")
        self.assertEqual(stato, StatoNormalizzazione.RISOLTO)
        self.assertEqual(forma, "Furosemide")

    def test_forma_usata_e_veritiera(self):
        """La provenienza deve dire quale forma ha risolto, non quella citata."""
        _, _, _, forma = self.risolutore.risolvi_menzione("Lasix")
        self.assertEqual(forma, "Lasix")

    def test_nome_ignoto_resta_nil(self):
        codice, stato, _, _ = self.risolutore.risolvi_menzione("diuretico")
        self.assertIsNone(codice)
        self.assertEqual(stato, StatoNormalizzazione.NIL)


    def test_formato_ingresso_col_due_punti(self):
        """Regressione. Il campo di terapia all'ingresso ha formato
        "Nome: dose forma /die (ore N)" e il modello ne cita la riga intera.
        Sui due record di verifica, 14 farmaci su 14 restavano senza ATC."""
        codice, stato, _, forma = self.risolutore.risolvi_menzione(
            "Medrol: 4 mg cpr. /die (ore 8)"
        )
        self.assertEqual(stato, StatoNormalizzazione.RISOLTO)
        self.assertEqual(forma, "Medrol")
        self.assertIsNotNone(codice)

    def test_nome_con_punti_interni_conservato(self):
        """"Furosemide l.f.m." contiene punti ma il taglio e' sui due punti."""
        _, stato, _, forma = self.risolutore.risolvi_menzione(
            "Furosemide l.f.m.: 25 mg cpr. mar-gio (ore 8)"
        )
        self.assertEqual(stato, StatoNormalizzazione.RISOLTO)
        self.assertEqual(forma, "Furosemide l.f.m.")

    def test_le_due_vie_concordano(self):
        """Principio attivo e nome commerciale devono portare allo stesso ATC."""
        da_principio, _, _, _ = self.risolutore.risolvi_menzione("Bisoprololo")
        da_composta, _, _, _ = self.risolutore.risolvi_menzione(
            "Bisoprololo (Congescor cp.riv. 2.5 mg)"
        )
        self.assertEqual(da_principio, da_composta)



@unittest.skipUnless(
    (
        Path(__file__).resolve().parent.parent / "data/interim/terminologia_icd10.json"
    ).exists(),
    "terminologia ICD-10 non generata",
)
class TestGeneralizzazioneICD(unittest.TestCase):
    """Il lessico clinico e quello del volume ICD divergono.

    Il volume elenca la fibrillazione atriale nelle sue varie forme ma
    non "fibrillazione atriale" da sola. Quando tutte le forme qualificate
    ricadono in un'unica categoria, quella categoria e' cio' che la menzione
    generica denota, e il suo codice a 3 caratteri e' una codifica ICD-10 valida.
    """

    @classmethod
    def setUpClass(cls):
        from risolutori import RisolutoreICD

        cls.risolutore = RisolutoreICD()

    def test_menzione_generica_risolve_alla_categoria(self):
        esito = self.risolutore.risolvi("fibrillazione atriale")
        self.assertEqual(esito.codice, "I48")
        self.assertEqual(esito.stato, StatoNormalizzazione.RISOLTO)
        self.assertEqual(esito.metodo, "generalizzazione_a_categoria")
        # I candidati restano visibili: si vede da cosa e' stata generalizzata.
        self.assertIn("I48.0", esito.candidati)

    def test_categorie_diverse_restano_ambigue(self):
        """"diabete mellito" copre tipo 1, tipo 2 e quello gestazionale."""
        esito = self.risolutore.risolvi("diabete mellito")
        self.assertIsNone(esito.codice)
        self.assertEqual(esito.stato, StatoNormalizzazione.AMBIGUO)
        self.assertGreater(len(esito.candidati), 1)

    def test_una_sola_forma_qualificata_non_generalizza(self):
        """Regressione. L'unica forma indicizzata che estende "insufficienza
        mitralica" e' "insufficienza mitralica congenita" (Q23.3): generalizzare
        avrebbe dato a una valvulopatia acquisita un codice congenito. Con una
        sola forma non si distingue un concetto padre da un fratello piu'
        specifico, quindi non si generalizza."""
        esito = self.risolutore.risolvi("insufficienza mitralica")
        self.assertNotEqual(esito.codice, "Q23")
        self.assertIsNone(esito.codice)

    def test_termine_esatto_ha_la_precedenza(self):
        esito = self.risolutore.risolvi("ipertensione arteriosa")
        self.assertEqual(esito.metodo, "termine_esatto")
        self.assertEqual(esito.codice, "I10")

    def test_menzione_ignota_resta_nil(self):
        esito = self.risolutore.risolvi("qwertyuiop asdfgh")
        self.assertEqual(esito.stato, StatoNormalizzazione.NIL)
        self.assertIsNone(esito.codice)

    def test_categoria_di_un_codice(self):
        from risolutori import RisolutoreICD

        self.assertEqual(RisolutoreICD.categoria("I48.0"), "I48")
        self.assertEqual(RisolutoreICD.categoria("I10"), "I10")


class TestTerapiaDalParserDeterministico(unittest.TestCase):
    """I farmaci di terapia entrano in B senza passare dal modello.

    E' la stessa lettura che fanno le pipeline A e C: il progetto ha una sola
    interpretazione dei due campi strutturati, non tre che possono divergere.
    """

    def _stato(self, **campi):
        return extract_b.converti(
            record_di_prova(**campi),
            EstrazioneLLM.model_validate({}),
            "m",
            RisolutoreATCFinto(),
            RisolutoreICDFinto(),
        )

    def test_i_farmaci_di_terapia_ci_sono_anche_se_il_modello_tace(self):
        stato = self._stato(
            anamnesi="Nessuna nota.",
            ingresso="Bisoprololo: 2,5 mg cpr. /die (ore 8) ;",
            dimissione='"Ramipril (Triatec cpr. 5 mg): da assumere 5 mg (ore 8)"',
        )
        nomi = {f.nome_grezzo for f in stato.farmaci}
        self.assertIn("Bisoprololo", nomi)
        self.assertIn("Ramipril", nomi)

    def test_portano_la_provenienza_del_parser_non_quella_del_modello(self):
        """Il filtro dello step 8 deve poter distinguere un dato letto da un
        campo strutturato da uno riconosciuto nella prosa: sono affidabilita'
        diverse, e nel grafo diventano due agenti diversi."""
        stato = self._stato(anamnesi="x", ingresso="Bisoprololo: 2,5 mg ;")
        farmaco = stato.farmaci[0]
        self.assertEqual(farmaco.provenienza.pipeline.value, "campo_strutturato")
        self.assertEqual(farmaco.provenienza.regola, "sonda_terapia_ingresso")
        self.assertEqual(farmaco.momento, MomentoTerapia.INGRESSO)

    def test_il_momento_distingue_i_due_campi(self):
        stato = self._stato(
            anamnesi="x",
            ingresso="Bisoprololo: 2,5 mg ;",
            dimissione='"Ramipril (Triatec cpr. 5 mg): da assumere 5 mg"',
        )
        momenti = {f.nome_grezzo: f.momento for f in stato.farmaci}
        self.assertEqual(momenti["Bisoprololo"], MomentoTerapia.INGRESSO)
        self.assertEqual(momenti["Ramipril"], MomentoTerapia.DIMISSIONE)


class TestComposizioneTesto(unittest.TestCase):
    """Al modello arriva la sola anamnesi.

    I due campi di terapia sono liste con delimitatori, che un parser
    deterministico legge col 100% di precisione e richiamo contro il campo
    stesso, mentre il modello si fermava al 99,3%. Mandarceli costava circa un
    terzo della corsa per rifare peggio un lavoro gia' fatto.
    """

    def test_i_campi_di_terapia_non_arrivano_al_modello(self):
        testo = extract_b.componi_testo(
            record_di_prova(anamnesi="Anamnesi del paziente.",
                            ingresso="Bisoprololo: 2,5 mg",
                            dimissione='"Ramipril (Triatec): 5 mg"')
        )
        self.assertEqual(testo, "Anamnesi del paziente.")
        self.assertNotIn("Bisoprololo", testo)
        self.assertNotIn("Ramipril", testo)

    def test_un_record_senza_anamnesi_da_testo_vuoto(self):
        self.assertEqual(
            extract_b.componi_testo(record_di_prova(anamnesi="", ingresso="X: 1 mg")), "")


class TestEstrazioneCompleta(unittest.TestCase):
    def test_percorso_completo_con_backend_fittizio(self):
        backend = BackendFittizio(
            lambda richiesta: {
                "condizioni": [
                    {
                        "testo_grezzo": "BPCO",
                        "concetto": "broncopneumopatia cronica ostruttiva",
                        "campo": "Anamnesi",
                        "stato": "affermato",
                    }
                ],
                "farmaci": [],
                "allergie": [],
                "stato_sezione_allergie": "ignoto",
            }
        )
        stato, risposta = extract_b.estrai(
            record_di_prova(anamnesi="Nota BPCO.", dimissione="nulla"),
            backend,
            RisolutoreATCFinto(),
            RisolutoreICDFinto(),
        )
        self.assertEqual(stato.condizioni[0].codice, "J44.9")
        self.assertFalse(risposta.da_cache)
        # Le istruzioni inviate contengono le regole, non solo il testo del referto.
        self.assertIn("acronimi sciolti", backend.ricevute[0].istruzioni)

    def test_risposta_non_conforme_allo_schema_fallisce(self):
        """Lo schema vincola la generazione, ma la validazione resta la seconda rete."""
        backend = BackendFittizio(lambda r: {"condizioni": [{"testo_grezzo": "x"}]})
        with self.assertRaises(Exception):
            extract_b.estrai(
                record_di_prova(anamnesi="x"),
                backend,
                RisolutoreATCFinto(),
                RisolutoreICDFinto(),
            )


class TestCampionamento(unittest.TestCase):
    def test_selezione_riproducibile(self):
        record = [record_di_prova() for _ in range(50)]
        for indice, rec in enumerate(record):
            rec.enc_oid = indice
        prima = [r.enc_oid for r in extract_b.scegli_record(record, 10, seme=7)]
        seconda = [r.enc_oid for r in extract_b.scegli_record(record, 10, seme=7)]
        self.assertEqual(prima, seconda)
        self.assertEqual(len(prima), 10)

    def test_richiesta_maggiore_del_disponibile(self):
        record = [record_di_prova() for _ in range(3)]
        self.assertEqual(len(extract_b.scegli_record(record, 99, seme=7)), 3)



class TestRipresaDellaCorsa(unittest.TestCase):
    """Il checkpoint serve proprio quando qualcosa va storto.

    Una corsa di undici ore verra' interrotta: quello che conta e' che
    riprenderla non rifaccia il lavoro e, soprattutto, che non mescoli nella
    stessa cartella risultati ottenuti con modelli o prompt diversi -- una
    cartella cosi' non sarebbe piu' interpretabile da nessuno.
    """

    class Opzioni:
        motore = "locale"
        ragionamento = "low"
        seme = 1
        record = 200

    class BackendFinto:
        modello = "modello-a"

    def _configurazione(self, modello="modello-a"):
        backend = self.BackendFinto()
        backend.modello = modello
        return extract_b.impronta_configurazione(backend, self.Opzioni(), {"tipo": "oggetto"})

    def test_cartella_vuota_si_puo_usare(self):
        with tempfile.TemporaryDirectory() as cartella:
            extract_b.prepara_cartella(Path(cartella), self._configurazione(), rifai=False)

    def test_ripresa_con_stessa_configurazione(self):
        with tempfile.TemporaryDirectory() as cartella:
            percorso = Path(cartella)
            configurazione = self._configurazione()
            extract_b.salva_registro(percorso, configurazione, 3, 10)
            (percorso / "1.json").write_text("{}", encoding="utf-8")
            extract_b.prepara_cartella(percorso, configurazione, rifai=False)  # non solleva

    def test_modello_diverso_blocca_la_ripresa(self):
        with tempfile.TemporaryDirectory() as cartella:
            percorso = Path(cartella)
            extract_b.salva_registro(percorso, self._configurazione("modello-a"), 3, 10)
            with self.assertRaises(SystemExit) as errore:
                extract_b.prepara_cartella(percorso, self._configurazione("modello-b"), rifai=False)
            self.assertIn("modello", str(errore.exception))

    def test_risultati_senza_registro_bloccano(self):
        """File prodotti da una corsa sconosciuta non vanno ne' riusati ne'
        cancellati in silenzio."""
        with tempfile.TemporaryDirectory() as cartella:
            percorso = Path(cartella)
            (percorso / "1.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(SystemExit):
                extract_b.prepara_cartella(percorso, self._configurazione(), rifai=False)

    def test_rifai_ripulisce(self):
        with tempfile.TemporaryDirectory() as cartella:
            percorso = Path(cartella)
            (percorso / "1.json").write_text("{}", encoding="utf-8")
            extract_b.salva_registro(percorso, self._configurazione("altro"), 1, 10)
            extract_b.prepara_cartella(percorso, self._configurazione(), rifai=True)
            self.assertFalse((percorso / "1.json").exists())

    def test_il_registro_conserva_l_avanzamento(self):
        with tempfile.TemporaryDirectory() as cartella:
            percorso = Path(cartella)
            extract_b.salva_registro(percorso, self._configurazione(), 42, 200)
            salvato = json.loads((percorso / extract_b.NOME_REGISTRO).read_text(encoding="utf-8"))
            self.assertEqual(salvato["record_completati"], 42)
            self.assertEqual(salvato["record_totali"], 200)


class TestMisuraProduzione(unittest.TestCase):
    def test_conta_dai_file_e_non_dalla_memoria(self):
        """Su una corsa ripresa piu' volte i contatori in memoria coprono solo
        l'ultimo tratto: le misure vere si ricavano da cio' che e' su disco."""
        with tempfile.TemporaryDirectory() as cartella:
            percorso = Path(cartella)
            stato = extract_b.converti(
                record_di_prova(anamnesi="Nota BPCO.", dimissione="x"),
                EstrazioneLLM.model_validate(
                    {
                        "condizioni": [
                            {
                                "testo_grezzo": "BPCO",
                                "concetto": "broncopneumopatia cronica ostruttiva",
                                "campo": "Anamnesi",
                                "stato": "affermato",
                            }
                        ],
                        "farmaci": [
                            {
                                "testo_grezzo": "Bisoprololo",
                                "campo": "Terapia alla Dimissione",
                                "stato": "affermato",
                            }
                        ],
                    }
                ),
                "m",
                RisolutoreATCFinto(),
                RisolutoreICDFinto(),
            )
            (percorso / "1.json").write_text(stato.model_dump_json(), encoding="utf-8")
            (percorso / "_corsa.json").write_text("{}", encoding="utf-8")

            m = extract_b.misura_produzione(percorso)
            self.assertEqual(m["record"], 1)  # il file con underscore non e' un record
            self.assertEqual(m["condizioni"], 1)
            self.assertEqual(m["condizioni_con_codice"], 1)
            self.assertEqual(m["farmaci"], 1)
            self.assertEqual(m["per_stato"]["affermato"], 1)

    def test_conta_anche_le_allergie_non_ancorate(self):
        """Le allergie contavano nel denominatore ma non nel numeratore.

        Il tasso di menzioni non ritrovate risultava piu' basso del vero, e su
        200 record ha nascosto il difetto piu' grave della pipeline: allergie a
        farmaci che il paziente sta assumendo, inventate su referti che di
        allergie non parlano. Sono anzi il tipo di menzione che il modello
        parafrasa piu' spesso.
        """
        with tempfile.TemporaryDirectory() as cartella:
            percorso = Path(cartella)
            stato = extract_b.converti(
                record_di_prova(anamnesi="Nessuna nota.", dimissione="x"),
                EstrazioneLLM.model_validate(
                    {
                        "allergie": [
                            # Non compare nel referto: e' una menzione inventata.
                            {"allergene": "Penicillina", "categoria": "principi attivi", "campo": "Anamnesi"}
                        ]
                    }
                ),
                "m",
                RisolutoreATCFinto(),
                RisolutoreICDFinto(),
            )
            (percorso / "1.json").write_text(stato.model_dump_json(), encoding="utf-8")

            m = extract_b.misura_produzione(percorso)
            self.assertEqual(m["allergie"], 1)
            self.assertEqual(m["menzioni_non_ancorate"], 1)


class TestTettoElementi(unittest.TestCase):
    """Il tetto agli elementi degli array e' un vincolo, non un consiglio.

    Due record su 200 hanno esaurito trenta minuti di generazione perche' il
    modello trasformava ogni proposizione della narrazione in una "condizione" e
    l'array non si chiudeva mai. Un'istruzione nel prompt il modello puo'
    ignorarla; `maxItems` lo applica il decodificatore vincolato.
    """

    def test_lo_schema_dichiara_il_tetto_al_decodificatore(self):
        grezzo = schema_estrazione_llm()
        for elenco in ("condizioni", "farmaci", "allergie"):
            self.assertEqual(
                grezzo["properties"][elenco]["maxItems"], schema.MASSIMI_ELEMENTI
            )

    def test_il_tetto_e_generoso_rispetto_alla_produzione_reale(self):
        # Mediana misurata sulla corsa: 25 condizioni per record. Un tetto
        # troppo stretto taglierebbe i record sani invece dei patologici.
        self.assertGreaterEqual(schema.MASSIMI_ELEMENTI, 50)

    def test_oltre_il_tetto_la_validazione_rifiuta(self):
        troppe = [
            {"testo_grezzo": f"c{i}", "concetto": f"c{i}", "campo": "Anamnesi",
             "stato": "affermato"}
            for i in range(schema.MASSIMI_ELEMENTI + 1)
        ]
        with self.assertRaises(ValidationError):
            EstrazioneLLM.model_validate({"condizioni": troppe})


class TestCampoDelleAllergie(unittest.TestCase):
    """Le allergie devono dichiarare da quale campo vengono, come le altre entita'.

    Prima la pipeline le attribuiva d'ufficio all'anamnesi: quando il modello
    citava correttamente un altro campo l'ancoraggio falliva per costruzione, e
    59 delle 111 allergie non ancorate della prima corsa erano testo che nel
    record esisteva davvero, altrove.
    """

    def test_un_allergia_si_ancora_sempre_sull_anamnesi(self):
        """Regressione al contrario. Prima il modello leggeva anche le terapie e
        poteva citarle; ora vede solo l'anamnesi, e un campo diverso dichiarato
        nell'uscita e' un errore da neutralizzare, non da assecondare."""
        stato = extract_b.converti(
            record_di_prova(anamnesi="Allergia ad Amoxicillina.",
                            ingresso="Amoxicillina 1 g"),
            EstrazioneLLM.model_validate(
                {
                    "allergie": [
                        {
                            "allergene": "Amoxicillina",
                            "categoria": "principi attivi",
                            "campo": "Terapia medica all'ingresso",
                        }
                    ]
                }
            ),
            "m",
            RisolutoreATCFinto(),
            RisolutoreICDFinto(),
        )
        provenienza = stato.allergie[0].provenienza
        self.assertEqual(provenienza.campo_sorgente, "Anamnesi")
        self.assertIsNotNone(provenienza.inizio)


if __name__ == "__main__":
    unittest.main()
