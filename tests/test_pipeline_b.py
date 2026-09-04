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
from data_loading import RecordPaziente, Referto  # noqa: E402
from llm_backend import (  # noqa: E402
    BackendFittizio,
    BackendGemini,
    ErroreLLM,
    ErroreQuotaGiornaliera,
    Richiesta,
    _dettagli_errore,
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
        chiave = testo.strip().lower()
        if chiave == "broncopneumopatia cronica ostruttiva":
            return "J44.9", StatoNormalizzazione.RISOLTO, chiave, ["J44.9"]
        if chiave == "cardiopatia ischemica":
            return None, StatoNormalizzazione.AMBIGUO, chiave, ["I25.1", "I25.9"]
        return None, StatoNormalizzazione.NIL, None, []


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

    def test_momento_dedotto_dal_campo(self):
        """Il momento non si chiede al modello: si deduce dal campo, che e' verificabile."""
        stato = self._converti(
            EstrazioneLLM.model_validate(
                {
                    "farmaci": [
                        {
                            "testo_grezzo": "Bisoprololo",
                            "campo": "Terapia alla Dimissione",
                            "stato": "affermato",
                            "posologia": "2,5 mg/die",
                        }
                    ]
                }
            ),
            dimissione="Bisoprololo 2,5 mg/die",
        )
        farmaco = stato.farmaci[0]
        self.assertEqual(farmaco.momento, MomentoTerapia.DIMISSIONE)
        self.assertEqual(farmaco.codice_atc, "C07AB07")
        self.assertEqual(farmaco.posologia, "2,5 mg/die")

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

    def test_le_due_vie_concordano(self):
        """Principio attivo e nome commerciale devono portare allo stesso ATC."""
        da_principio, _, _, _ = self.risolutore.risolvi_menzione("Bisoprololo")
        da_composta, _, _, _ = self.risolutore.risolvi_menzione(
            "Bisoprololo (Congescor cp.riv. 2.5 mg)"
        )
        self.assertEqual(da_principio, da_composta)


class TestComposizioneTesto(unittest.TestCase):
    def test_solo_le_sezioni_presenti(self):
        testo = extract_b.componi_testo(record_di_prova(anamnesi="Anam.", ingresso=""))
        self.assertIn("### Anamnesi", testo)
        self.assertNotIn("### Terapia medica all'ingresso", testo)

    def test_le_intestazioni_coincidono_coi_valori_ammessi(self):
        """Il modello ricopia l'etichetta sotto cui legge invece di inventarla."""
        testo = extract_b.componi_testo(
            record_di_prova(anamnesi="A", ingresso="B", dimissione="C")
        )
        for campo in CampoReferto:
            self.assertIn(f"### {campo.value}", testo)


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


if __name__ == "__main__":
    unittest.main()
