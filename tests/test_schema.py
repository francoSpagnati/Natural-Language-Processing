"""Test dello schema dello stato paziente (step 1)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pydantic import ValidationError  # noqa: E402

from schema import (  # noqa: E402
    CondizioneEstratta,
    FarmacoEstratto,
    MomentoTerapia,
    Pipeline,
    Provenienza,
    StatoConoscenza,
    StatoNormalizzazione,
    StatoPaziente,
    json_schema,
)


def provenienza() -> Provenienza:
    return Provenienza(
        pipeline=Pipeline.A_DETERMINISTICA,
        campo_sorgente="Anamnesi",
        testo_originale="test",
    )


class TestStatiDiConoscenza(unittest.TestCase):
    def test_negato_e_ignoto_restano_distinti(self):
        """"Il paziente non e' iperteso" e "non se ne parla" sono cose diverse."""
        self.assertNotEqual(StatoConoscenza.NEGATO, StatoConoscenza.IGNOTO)
        self.assertEqual(StatoConoscenza.NEGATO.value, "negato")

    def test_lo_stato_della_sezione_allergie_e_indipendente_dalla_lista(self):
        paziente_verificato = StatoPaziente(
            enc_oid=1,
            pipeline=Pipeline.A_DETERMINISTICA,
            stato_sezione_allergie=StatoConoscenza.NEGATO,
        )
        paziente_ignoto = StatoPaziente(enc_oid=2, pipeline=Pipeline.A_DETERMINISTICA)

        # Entrambi hanno zero allergie, ma non significano la stessa cosa.
        self.assertEqual(paziente_verificato.allergie, [])
        self.assertEqual(paziente_ignoto.allergie, [])
        self.assertNotEqual(
            paziente_verificato.stato_sezione_allergie,
            paziente_ignoto.stato_sezione_allergie,
        )
        self.assertEqual(paziente_ignoto.stato_sezione_allergie, StatoConoscenza.IGNOTO)


class TestFiltriDelloStatoPaziente(unittest.TestCase):
    def _paziente(self) -> StatoPaziente:
        return StatoPaziente(
            enc_oid=1,
            pipeline=Pipeline.A_DETERMINISTICA,
            farmaci=[
                FarmacoEstratto(
                    nome_grezzo="Lasix",
                    momento=MomentoTerapia.INGRESSO,
                    provenienza=provenienza(),
                ),
                FarmacoEstratto(
                    nome_grezzo="Bisoprololo",
                    momento=MomentoTerapia.DIMISSIONE,
                    provenienza=provenienza(),
                ),
            ],
            condizioni=[
                CondizioneEstratta(
                    testo_grezzo="ipertensione arteriosa",
                    stato=StatoConoscenza.AFFERMATO,
                    provenienza=provenienza(),
                ),
                CondizioneEstratta(
                    testo_grezzo="diabete mellito",
                    stato=StatoConoscenza.NEGATO,
                    provenienza=provenienza(),
                ),
            ],
        )

    def test_farmaci_in_corso_esclude_la_dimissione(self):
        """La terapia alla dimissione e' cio' che il sistema deve predire.

        Usarla come input sarebbe una fuga di informazione dalla ground truth:
        il modello "indovinerebbe" leggendo la risposta.
        """
        in_corso = self._paziente().farmaci_in_corso

        self.assertEqual([f.nome_grezzo for f in in_corso], ["Lasix"])

    def test_condizioni_affermate_esclude_negate(self):
        affermate = self._paziente().condizioni_affermate

        self.assertEqual([c.testo_grezzo for c in affermate], ["ipertensione arteriosa"])


class TestValidazione(unittest.TestCase):
    def test_campo_obbligatorio_mancante_viene_rifiutato(self):
        """E' il vantaggio concreto di Pydantic: l'errore emerge subito."""
        with self.assertRaises(ValidationError):
            FarmacoEstratto(nome_grezzo="Lasix")  # manca `momento` e `provenienza`

    def test_default_prudenti(self):
        """Senza informazione esplicita, lo stato di normalizzazione non mente."""
        farmaco = FarmacoEstratto(
            nome_grezzo="Lasix", momento=MomentoTerapia.INGRESSO, provenienza=provenienza()
        )

        self.assertEqual(farmaco.stato_normalizzazione, StatoNormalizzazione.NON_TENTATO)
        self.assertIsNone(farmaco.codice_atc)

    def test_nil_e_distinto_da_non_tentato(self):
        """"Nessun candidato affidabile" non e' "non ho ancora provato"."""
        self.assertNotEqual(StatoNormalizzazione.NIL, StatoNormalizzazione.NON_TENTATO)


class TestJsonSchema(unittest.TestCase):
    def test_lo_schema_si_genera_e_documenta_i_tipi(self):
        schema = json_schema()

        self.assertIn("enc_oid", schema["properties"])
        self.assertIn("StatoConoscenza", schema["$defs"])
        self.assertEqual(
            sorted(schema["$defs"]["StatoConoscenza"]["enum"]),
            ["affermato", "ignoto", "incerto", "negato"],
        )

    def test_round_trip_json(self):
        """Lo stato deve sopravvivere a serializzazione e rilettura."""
        originale = StatoPaziente(enc_oid=42, pipeline=Pipeline.B_LLM)

        ricostruito = StatoPaziente.model_validate_json(originale.model_dump_json())

        self.assertEqual(ricostruito.enc_oid, 42)
        self.assertEqual(ricostruito.pipeline, Pipeline.B_LLM)


if __name__ == "__main__":
    unittest.main()
