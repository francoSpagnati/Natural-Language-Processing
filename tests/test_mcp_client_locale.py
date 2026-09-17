"""L'host MCP locale: il controllo a valle contro la parafrasi."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE / "src"))

from mcp_client_locale import _schema_per_ollama, testo_fedele  # noqa: E402

DOMANDA = ("Anamnesi: «Scompenso cardiaco. Segue cura per ipertensione arteriosa "
           "dal 2004.» In terapia: Furosemide 25 mg; Ramipril 5 mg. Che aggiungeresti?")


class TestTestoFedele(unittest.TestCase):

    def test_un_pezzo_copiato_e_fedele(self) -> None:
        self.assertTrue(testo_fedele(
            "Scompenso cardiaco. Segue cura per ipertensione arteriosa dal 2004.",
            DOMANDA))

    def test_maiuscole_e_punteggiatura_non_contano(self) -> None:
        """Una virgola in piu' non e' una riscrittura dei fatti."""
        self.assertTrue(testo_fedele(
            "scompenso cardiaco, segue cura per ipertensione arteriosa dal 2004",
            DOMANDA))

    def test_la_parafrasi_che_inverte_un_fatto_NON_e_fedele(self) -> None:
        """Il caso vero della corsa 3."""
        self.assertFalse(testo_fedele(
            "Ipotensione con frazione di eiezione ridotta",
            "Paziente iperteso con frazione di eiezione ridotta"))

    def test_un_riassunto_NON_e_fedele(self) -> None:
        self.assertFalse(testo_fedele("Scompenso e ipertensione.", DOMANDA))

    def test_il_testo_intero_e_fedele(self) -> None:
        self.assertTrue(testo_fedele(DOMANDA, DOMANDA))


class TestTraduzioneDegliStrumenti(unittest.TestCase):
    """MCP e ollama parlano due dialetti; la traduzione sta in un punto solo."""

    def test_nome_descrizione_e_schema_passano_intatti(self) -> None:
        strumento = SimpleNamespace(
            name="cardio_cerca_codice", description="  Cerca un codice.  ",
            input_schema={"type": "object",
                          "properties": {"query": {"type": "string"}}})
        (tradotto,) = _schema_per_ollama([strumento])
        self.assertEqual(tradotto["type"], "function")
        self.assertEqual(tradotto["function"]["name"], "cardio_cerca_codice")
        self.assertEqual(tradotto["function"]["description"], "Cerca un codice.")
        self.assertEqual(tradotto["function"]["parameters"], strumento.input_schema)

    def test_usa_input_schema_e_non_inputSchema(self) -> None:
        """La trappola di mcp 2.x: l'attributo si chiama `input_schema`.

        Il client e' fallito al primo giro proprio qui.
        """
        strumento = SimpleNamespace(name="x", description=None,
                                    input_schema={"type": "object"})
        (tradotto,) = _schema_per_ollama([strumento])
        self.assertEqual(tradotto["function"]["parameters"], {"type": "object"})
        self.assertEqual(tradotto["function"]["description"], "")


if __name__ == "__main__":
    unittest.main()
