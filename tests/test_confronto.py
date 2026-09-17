"""Test del confronto fra pipeline (step 6)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from confronto import (  # noqa: E402
    CAMPO_PROSA,
    Menzione,
    accordo,
    copertura,
    raggruppa,
    ripulisci,
    solo_di,
    venn,
)


def menzione(sigla, inizio, fine, *, tipo="condizione", campo=CAMPO_PROSA,
             testo="x", codice=None, stato="affermato", soggetto="paziente",
             enc=1) -> Menzione:
    return Menzione(enc, sigla, tipo, campo, inizio, fine, testo, codice,
                    stato, soggetto, False)


class RisolutoreFinto:
    """Conosce un solo farmaco: basta a provare la riclassificazione."""

    def risolvi(self, nome):
        if nome.lower() == "bisoprololo":
            return "C07AB07", "risolto", "finto"
        return None, "nil", None


class TestRaggruppamento(unittest.TestCase):
    def test_menzioni_disgiunte_restano_separate(self):
        gruppi = raggruppa([menzione("A", 0, 5), menzione("B", 10, 15)])
        self.assertEqual(len(gruppi), 2)

    def test_menzioni_sovrapposte_formano_un_gruppo(self):
        gruppi = raggruppa([menzione("A", 0, 10), menzione("B", 5, 15)])
        self.assertEqual(len(gruppi), 1)
        self.assertEqual(gruppi[0].sigle, {"A", "B"})
        self.assertFalse(gruppi[0].ambiguo)

    def test_intervalli_adiacenti_non_si_toccano(self):
        # La fine di una e l'inizio dell'altra coincidono: sono contigue, non
        # sovrapposte, e vanno tenute distinte o due entita' vicine diverse
        # verrebbero fuse.
        gruppi = raggruppa([menzione("A", 0, 5), menzione("B", 5, 10)])
        self.assertEqual(len(gruppi), 2)

    def test_una_citazione_lunga_ne_abbraccia_di_corte(self):
        # E' il caso vero della pipeline B, che spesso cita la frase intera.
        gruppi = raggruppa([menzione("A", 0, 5), menzione("A", 8, 12),
                            menzione("B", 0, 20)])
        self.assertEqual(len(gruppi), 1)
        self.assertTrue(gruppi[0].ambiguo)
        self.assertIsNone(gruppi[0].una("A"))  # non e' definito quale delle due

    def test_una_menzione_intermedia_collega_le_estreme(self):
        # A e C non si toccano fra loro, ma B tocca entrambe: e' una sola
        # componente connessa.
        gruppi = raggruppa([menzione("A", 0, 6), menzione("B", 4, 12),
                            menzione("C", 10, 16)])
        self.assertEqual(len(gruppi), 1)
        self.assertEqual(gruppi[0].sigle, {"A", "B", "C"})

    def test_campi_diversi_non_si_uniscono_mai(self):
        gruppi = raggruppa([
            menzione("A", 0, 10),
            menzione("B", 0, 10, campo="Terapia alla Dimissione"),
        ])
        self.assertEqual(len(gruppi), 2)

    def test_ricoveri_diversi_non_si_uniscono_mai(self):
        gruppi = raggruppa([menzione("A", 0, 10), menzione("B", 0, 10, enc=2)])
        self.assertEqual(len(gruppi), 2)


class TestRipulitura(unittest.TestCase):
    def test_i_duplicati_esatti_vengono_rimossi(self):
        doppia = [menzione("B", 0, 5, testo="diabete")] * 3
        fuori, conti = ripulisci({1: doppia}, RisolutoreFinto())
        self.assertEqual(len(fuori[1]), 1)
        self.assertEqual(conti["duplicati_rimossi"], 2)

    def test_un_farmaco_fra_le_condizioni_viene_spostato_non_scartato(self):
        """Scartarlo direbbe che la pipeline non l'ha visto, che e' falso.

        La menzione e' stata riconosciuta correttamente nel testo: l'errore sta
        nell'etichetta, e va registrato come tale.
        """
        fuori, conti = ripulisci(
            {1: [menzione("B", 0, 11, testo="bisoprololo")]}, RisolutoreFinto()
        )
        self.assertEqual(len(fuori[1]), 1)
        self.assertEqual(fuori[1][0].tipo, "farmaco")
        self.assertEqual(conti["farmaci_riclassificati"], 1)

    def test_una_condizione_vera_non_viene_toccata(self):
        fuori, conti = ripulisci(
            {1: [menzione("B", 0, 8, testo="diabete")]}, RisolutoreFinto()
        )
        self.assertEqual(fuori[1][0].tipo, "condizione")
        self.assertNotIn("farmaci_riclassificati", conti)


class TestMisure(unittest.TestCase):
    def test_il_venn_conta_le_combinazioni(self):
        gruppi = raggruppa([
            menzione("A", 0, 10), menzione("B", 2, 8), menzione("C", 4, 6),
            menzione("A", 20, 25),
        ])
        self.assertEqual(venn(gruppi), {"ABC": 1, "A": 1})

    def test_solo_di_restituisce_le_menzioni_esclusive(self):
        gruppi = raggruppa([menzione("A", 0, 10, testo="sola"),
                            menzione("B", 20, 25), menzione("C", 22, 24)])
        sole = solo_di(gruppi, "A")
        self.assertEqual([m.testo for m in sole], ["sola"])

    def test_l_accordo_ignora_i_gruppi_ambigui(self):
        """Dove una pipeline contribuisce piu' menzioni non c'e' un confronto.

        Forzarne uno produrrebbe un numero che sembra una misura senza esserlo.
        """
        gruppi = raggruppa([
            menzione("A", 0, 5, stato="negato"), menzione("A", 6, 9, stato="affermato"),
            menzione("B", 0, 12, stato="negato"),
        ])
        self.assertEqual(accordo(gruppi, "A", "B", "stato")["confrontabili"], 0)

    def test_l_accordo_misura_quel_che_deve(self):
        gruppi = raggruppa([
            menzione("A", 0, 5, stato="negato"), menzione("B", 1, 4, stato="negato"),
            menzione("A", 20, 25, stato="affermato"), menzione("B", 21, 24, stato="negato"),
        ])
        esito = accordo(gruppi, "A", "B", "stato")
        self.assertEqual(esito["confrontabili"], 2)
        self.assertEqual(esito["concordi"], 1)
        self.assertAlmostEqual(esito["quota_accordo"], 0.5)

    def test_la_copertura_separa_i_due_tipi(self):
        misure = copertura([
            menzione("A", 0, 5, codice="I10"),
            menzione("A", 6, 9),
            menzione("A", 10, 15, tipo="farmaco", codice="C07AB07"),
        ])
        self.assertEqual(misure["condizione"]["menzioni"], 2)
        self.assertAlmostEqual(misure["condizione"]["quota"], 0.5)
        self.assertAlmostEqual(misure["farmaco"]["quota"], 1.0)

    def test_la_copertura_di_un_tipo_assente_non_esplode(self):
        misure = copertura([menzione("A", 0, 5)])
        self.assertEqual(misure["farmaco"]["menzioni"], 0)
        self.assertEqual(misure["farmaco"]["quota"], 0.0)


if __name__ == "__main__":
    unittest.main()
