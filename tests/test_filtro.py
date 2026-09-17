"""Test del filtro di sicurezza simbolico (step 8)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from filtro import (  # noqa: E402
    Controindicazione,
    Esito,
    StatoPerFiltro,
    valuta,
)


def stato(condizioni=(), allergie=(), terapia=()):
    return StatoPerFiltro(
        enc_oid=1,
        condizioni=[{"codice": c, "testo": c, "agenti": list(a)}
                    for c, a in condizioni],
        allergie_atc=set(allergie),
        terapia_atc=set(terapia),
    )


class TestAllergia(unittest.TestCase):
    def test_la_stessa_sostanza_e_vietata(self):
        v = valuta(stato(allergie={"C07AB07"}), "C07AB07")
        self.assertEqual(v.esito, Esito.VIETATO)
        self.assertEqual(v.motivi[0]["regola"], "ALLERGIA_SOSTANZA")

    def test_lo_stesso_sottogruppo_e_da_verificare_non_vietato(self):
        """La reattivita' crociata entro sottogruppo e' un'ipotesi, non un
        fatto: trattarla come divieto negherebbe intere classi di farmaci."""
        v = valuta(stato(allergie={"C07AB07"}), "C07AB12")
        self.assertEqual(v.esito, Esito.DA_VERIFICARE)

    def test_un_altro_sottogruppo_non_tocca_nulla(self):
        self.assertEqual(valuta(stato(allergie={"C07AB07"}), "C09AA05").esito,
                         Esito.AMMESSO)


class TestDuplicazione(unittest.TestCase):
    def test_la_stessa_sostanza_gia_in_terapia(self):
        v = valuta(stato(terapia={"C07AB07"}), "C07AB07")
        self.assertEqual(v.esito, Esito.DA_VERIFICARE)

    def test_un_farmaco_puo_essere_valutato_senza_duplicare_se_stesso(self):
        """Serve a provare il filtro sulla terapia reale: ogni farmaco
        prescritto e' gia' nella terapia del paziente, e senza questa esclusione
        ognuno risulterebbe duplicato di se stesso."""
        v = valuta(stato(terapia={"C07AB07"}), "C07AB07", esclusa_dalla_terapia="C07AB07")
        self.assertEqual(v.esito, Esito.AMMESSO)


class TestControindicazione(unittest.TestCase):
    REGOLA = (Controindicazione(
        "M01A", ("I50",), Esito.VIETATO, "FANS in scompenso", "fonte di prova"),)

    def test_la_condizione_affermata_del_paziente_fa_scattare_la_regola(self):
        v = valuta(stato(condizioni=[("I50.0", "ABC")]), "M01AE01", self.REGOLA)
        self.assertEqual(v.esito, Esito.VIETATO)

    def test_il_prefisso_icd_aggancia_le_sottocategorie(self):
        self.assertEqual(valuta(stato(condizioni=[("I50.9", "B")]),
                                "M01AE01", self.REGOLA).esito, Esito.VIETATO)

    def test_una_condizione_di_un_altro_capitolo_non_scatta(self):
        self.assertEqual(valuta(stato(condizioni=[("I48.0", "ABC")]),
                                "M01AE01", self.REGOLA).esito, Esito.AMMESSO)

    def test_la_fonte_viaggia_nel_verdetto(self):
        """Una regola di sicurezza che non dice su cosa si basa non e'
        contestabile da un clinico, ed e' il motivo per cui il filtro non usa un
        modello linguistico."""
        v = valuta(stato(condizioni=[("I50.0", "ABC")]), "M01AE01", self.REGOLA)
        self.assertEqual(v.motivi[0]["fonte"], "fonte di prova")


class TestGliAssiDelloSchemaProteggonoIlPaziente(unittest.TestCase):
    """Le due righe per cui l'asse del soggetto e quello dello stato esistono.

    Senza, il sistema negherebbe un antinfiammatorio a chi ha il padre
    scompensato, o a chi lo scompenso e' stato esplicitamente escluso.
    """

    REGOLA = TestControindicazione.REGOLA

    def _stato_grezzo(self, stato_clinico, soggetto):
        return StatoPerFiltro(
            enc_oid=1,
            condizioni=([{"codice": "I50.0", "testo": "scompenso", "agenti": ["B"]}]
                        if stato_clinico == "affermato" and soggetto == "paziente"
                        else []),
            allergie_atc=set(), terapia_atc=set(),
        )

    def test_una_condizione_negata_non_controindica(self):
        v = valuta(self._stato_grezzo("negato", "paziente"), "M01AE01", self.REGOLA)
        self.assertEqual(v.esito, Esito.AMMESSO)

    def test_la_condizione_di_un_familiare_non_controindica(self):
        v = valuta(self._stato_grezzo("affermato", "familiare"), "M01AE01", self.REGOLA)
        self.assertEqual(v.esito, Esito.AMMESSO)


class TestIlPrincipioDelFattoMancante(unittest.TestCase):
    """Una regola che ha bisogno di un fatto non estraibile non puo' vietare."""

    def test_una_regola_con_fatto_mancante_segnala_ma_non_vieta(self):
        regola = (Controindicazione(
            "C07", ("I44.1",), Esito.VIETATO, "betabloccante in BAV", "fonte",
            revocata_da=("Z95.0",), fatto_non_estratto="presenza di pacemaker"),)
        v = valuta(stato(condizioni=[("I44.1", "ABC")]), "C07AB07", regola)
        self.assertEqual(v.esito, Esito.DA_VERIFICARE)
        self.assertIn("fatto_mancante", v.motivi[0])

    def test_se_il_fatto_revocante_c_e_la_regola_non_scatta_affatto(self):
        regola = (Controindicazione(
            "C07", ("I44.1",), Esito.VIETATO, "betabloccante in BAV", "fonte",
            revocata_da=("Z95.0",), fatto_non_estratto="presenza di pacemaker"),)
        v = valuta(stato(condizioni=[("I44.1", "ABC"), ("Z95.0", "ABC")]),
                   "C07AB07", regola)
        self.assertEqual(v.esito, Esito.AMMESSO)


class TestLaProvenienzaModulaLEsito(unittest.TestCase):
    REGOLA = TestControindicazione.REGOLA

    def test_una_condizione_vista_dal_solo_gazetteer_non_basta_a_vietare(self):
        """Lo step 6bis ha misurato per il gazetteer una precisione dell'80%
        contro il 95% del modello. Un divieto che poggia solo su di lui e' un
        sospetto, e il falso blocco fa danno quanto il falso permesso."""
        v = valuta(stato(condizioni=[("I50.0", "A")]), "M01AE01", self.REGOLA)
        self.assertEqual(v.esito, Esito.DA_VERIFICARE)
        self.assertIn("EVIDENZA_DA_UNA_SOLA_FONTE",
                      [m["regola"] for m in v.motivi])

    def test_due_pipeline_concordi_bastano(self):
        v = valuta(stato(condizioni=[("I50.0", "AB")]), "M01AE01", self.REGOLA)
        self.assertEqual(v.esito, Esito.VIETATO)

    def test_il_solo_modello_basta_a_vietare(self):
        """Non e' una questione di numero ma di precisione misurata: B da sola
        e' piu' precisa di A da sola."""
        v = valuta(stato(condizioni=[("I50.0", "B")]), "M01AE01", self.REGOLA)
        self.assertEqual(v.esito, Esito.VIETATO)


class TestComposizioneDelVerdetto(unittest.TestCase):
    def test_un_divieto_vince_su_un_dubbio(self):
        v = valuta(stato(allergie={"C07AB07"}, terapia={"C07AB07"}), "C07AB07")
        self.assertEqual(v.esito, Esito.VIETATO)
        self.assertGreaterEqual(len(v.motivi), 2)

    def test_un_dubbio_non_declassa_un_divieto_gia_emesso(self):
        v = valuta(stato(allergie={"C07AB07", "C07AB12"}), "C07AB07")
        self.assertEqual(v.esito, Esito.VIETATO)

    def test_senza_motivi_il_farmaco_e_ammesso(self):
        v = valuta(stato(), "C09AA05")
        self.assertEqual(v.esito, Esito.AMMESSO)
        self.assertEqual(v.motivi, [])


if __name__ == "__main__":
    unittest.main()
