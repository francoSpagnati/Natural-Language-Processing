"""Test del riferimento annotato e delle misure che ne derivano (step 6bis).

Il conteggio di veri positivi, falsi positivi e falsi negativi decide ogni
numero di precisione e richiamo del progetto. Se sbaglia, i numeri restano
plausibili e nessuno se ne accorge: questi test lo fissano sui casi limite che
nei dati veri ricorrono davvero.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from riferimento import Entita, carica, valuta  # noqa: E402


class MenzioneFinta:
    """La forma minima che `valuta` usa di una menzione."""

    def __init__(self, enc_oid, tipo, inizio, fine, campo="Anamnesi", codice=None):
        self.enc_oid = enc_oid
        self.tipo = tipo
        self.inizio = inizio
        self.fine = fine
        self.campo = campo
        self.codice = codice


def entita(inizio, fine, tipo="condizione", enc=1, testo="x"):
    return Entita(enc, tipo, inizio, fine, testo, "affermato", "paziente")


class TestCaricamento(unittest.TestCase):
    """Le annotazioni sono stringhe: o si trovano nel referto o ci si ferma."""

    def _carica(self, blocco, anamnesi):
        with tempfile.TemporaryDirectory() as cartella:
            (Path(cartella) / "gold_test.json").write_text(
                json.dumps(blocco), encoding="utf-8"
            )
            return carica(anamnesi, Path(cartella))

    def test_ogni_occorrenza_diventa_un_entita(self):
        """Linea guida 3.5: una pipeline che trova la condizione tutte le volte
        che compare non va penalizzata."""
        fuori = self._carica(
            {"1": {"condizione": [["angina", "affermato", "paziente"]]}},
            {1: "angina da sforzo, poi angina a riposo"},
        )
        self.assertEqual(len(fuori), 2)

    def test_l_indice_seleziona_una_sola_occorrenza(self):
        """Serve dove la stessa stringa ha attributi diversi nello stesso
        referto: «episodio di FA» piu' avanti diventa «assenza di FA»."""
        fuori = self._carica(
            {"1": {"condizione": [["FA", "affermato", "paziente", 1]]}},
            {1: "episodio di FA nel 2019, successiva assenza di FA"},
        )
        self.assertEqual(len(fuori), 1)
        self.assertEqual(fuori[0].inizio, 12)

    def test_una_stringa_assente_ferma_tutto(self):
        """Un'annotazione che non si trova e' un errore di trascrizione, e
        lasciarla passare falserebbe il richiamo di ogni pipeline."""
        with self.assertRaises(SystemExit):
            self._carica(
                {"1": {"condizione": [["diabete", "affermato", "paziente"]]}},
                {1: "nessuna menzione qui"},
            )

    def test_un_indice_oltre_le_occorrenze_ferma_tutto(self):
        with self.assertRaises(SystemExit):
            self._carica(
                {"1": {"condizione": [["angina", "affermato", "paziente", 3]]}},
                {1: "angina da sforzo"},
            )

    def test_la_sigla_non_aggancia_l_interno_di_una_parola(self):
        """Senza confine di parola «TVS» si troverebbe dentro «TVSostenuta»."""
        fuori = self._carica(
            {"1": {"condizione": [["TVS", "affermato", "paziente"]]}},
            {1: "episodio di TVS, poi TVSostenuta"},
        )
        self.assertEqual(len(fuori), 1)


class TestMisure(unittest.TestCase):
    def test_la_sovrapposizione_basta_a_fare_un_vero_positivo(self):
        """I confini fra pipeline sono sistematicamente diversi: pretendere
        l'uguaglianza esatta misurerebbe la lunghezza delle citazioni."""
        r = valuta([entita(10, 20)], [MenzioneFinta(1, "condizione", 12, 30)], "condizione")
        self.assertEqual(r["veri_positivi"], 1)
        self.assertEqual(r["falsi_positivi"], 0)

    def test_intervalli_adiacenti_non_si_toccano(self):
        r = valuta([entita(10, 20)], [MenzioneFinta(1, "condizione", 20, 30)], "condizione")
        self.assertEqual(r["veri_positivi"], 0)
        self.assertEqual(r["falsi_negativi"], 1)

    def test_un_entita_puo_essere_coperta_una_volta_sola(self):
        """Senza questa regola una pipeline che frammenta guadagnerebbe
        richiamo senza pagarlo in precisione."""
        r = valuta(
            [entita(10, 30)],
            [MenzioneFinta(1, "condizione", 10, 15),
             MenzioneFinta(1, "condizione", 20, 25)],
            "condizione",
        )
        self.assertEqual(r["veri_positivi"], 1)
        self.assertEqual(r["falsi_positivi"], 1)

    def test_ricoveri_diversi_non_si_confondono(self):
        r = valuta([entita(10, 20, enc=1)],
                   [MenzioneFinta(2, "condizione", 10, 20)], "condizione")
        self.assertEqual(r["veri_positivi"], 0)

    def test_i_tipi_non_si_mescolano(self):
        r = valuta([entita(10, 20, tipo="condizione")],
                   [MenzioneFinta(1, "farmaco", 10, 20)], "condizione")
        self.assertEqual(r["veri_positivi"], 0)
        self.assertEqual(r["trovate"], 0)

    def test_le_menzioni_non_ancorate_sono_escluse(self):
        """Senza offset non c'e' niente da sovrapporre: contarle come falsi
        positivi punirebbe due volte un difetto gia' misurato altrove."""
        r = valuta([entita(10, 20)], [MenzioneFinta(1, "condizione", None, None)],
                   "condizione")
        self.assertEqual(r["trovate"], 0)

    def test_i_campi_strutturati_non_entrano(self):
        r = valuta([entita(10, 20)],
                   [MenzioneFinta(1, "condizione", 10, 20, campo="Terapia alla Dimissione")],
                   "condizione")
        self.assertEqual(r["trovate"], 0)

    def test_precisione_richiamo_e_f1(self):
        r = valuta(
            [entita(10, 20), entita(30, 40), entita(50, 60)],
            [MenzioneFinta(1, "condizione", 10, 20),
             MenzioneFinta(1, "condizione", 30, 40),
             MenzioneFinta(1, "condizione", 80, 90)],
            "condizione",
        )
        self.assertAlmostEqual(r["precisione"], 2 / 3)
        self.assertAlmostEqual(r["richiamo"], 2 / 3)
        self.assertAlmostEqual(r["f1"], 2 / 3)

    def test_una_pipeline_che_non_trova_nulla_non_esplode(self):
        r = valuta([entita(10, 20)], [], "condizione")
        self.assertEqual((r["precisione"], r["richiamo"], r["f1"]), (0.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
