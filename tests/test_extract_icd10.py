"""
Test dell'estrazione della terminologia ICD-10 dal PDF ufficiale.

Il parser lavora su un layout tipografico ricostruito da `pdftotext`, quindi e'
il componente piu' fragile scritto finora: piccoli cambiamenti di spaziatura
possono spostare un termine sotto il codice sbagliato. I test lavorano su
frammenti di testo sintetici che riproducono le forme reali incontrate nel
volume, cosi' girano senza il PDF (che non e' versionato).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from extract_icd10 import (  # noqa: E402
    analizza,
    costruisci_indice_termini,
    espandi_parentetici,
)


class TestEspansioneParentetici(unittest.TestCase):
    def test_i_modificatori_sono_opzionali(self):
        """Convenzione ICD: le parole fra parentesi possono esserci o no.

        E' il meccanismo che collega "ipertensione arteriosa" — il termine piu'
        frequente nel nostro corpus — al codice I10.
        """
        forme = espandi_parentetici("ipertensione (arteriosa) (essenziale)")

        self.assertIn("ipertensione", forme)
        self.assertIn("ipertensione arteriosa", forme)
        self.assertIn("ipertensione essenziale", forme)

    def test_i_rimandi_a_codici_non_sono_modificatori(self):
        """'(I27.2)' e' un rimando, non una parola opzionale."""
        forme = espandi_parentetici("ipertensione polmonare (I27.2)")

        self.assertEqual(forme, ["ipertensione polmonare"])

    def test_termine_senza_parentesi_resta_invariato(self):
        self.assertEqual(espandi_parentetici("cardiopatia ischemica"), ["cardiopatia ischemica"])


class TestAnalisiStruttura(unittest.TestCase):
    def test_distingue_categoria_e_sottocategoria(self):
        """La rientranza distingue i 3 caratteri dai 4: per questo serve -layout."""
        testo = (
            " I11          Cardiopatia ipertensiva\n"
            "I11.0         Cardiopatia ipertensiva con scompenso cardiaco\n"
        )
        voci = {v.codice: v for v in analizza(testo)}

        self.assertEqual(voci["I11"].livello, "categoria")
        self.assertEqual(voci["I11.0"].livello, "sottocategoria")
        self.assertEqual(voci["I11"].titolo, "Cardiopatia ipertensiva")

    def test_i_termini_esclusi_non_diventano_sinonimi(self):
        """'Escl.' rimanda ad ALTRI codici: usarli come sinonimi sbaglierebbe.

        E' una distinzione di correttezza, non di completezza: un termine
        escluso associato al codice sbagliato produrrebbe raccomandazioni
        basate su una diagnosi che il paziente non ha.
        """
        testo = (
            " I10          Ipertensione essenziale\n"
            "              Incl.: pressione arteriosa alta\n"
            "              Escl.: ipertensione polmonare (I27.0)\n"
        )
        voce = analizza(testo)[0]

        self.assertIn("pressione arteriosa alta", voce.inclusi)
        self.assertNotIn("ipertensione polmonare", voce.inclusi)
        self.assertIn("ipertensione polmonare", voce.esclusi)

    def test_sottoelenco_ricomposto_col_prefisso(self):
        """'malattia:' + 'cardiorenale' -> 'malattia cardiorenale'."""
        testo = (
            " I13        Malattia ipertensiva cardiaca e renale\n"
            "            Incl.: malattia:\n"
            "                    cardiorenale\n"
            "                    cardiovascolare renale\n"
        )
        voce = analizza(testo)[0]

        self.assertIn("malattia cardiorenale", voce.inclusi)
        self.assertIn("malattia cardiovascolare renale", voce.inclusi)

    def test_suffisso_della_graffa_applicato_a_tutto_il_gruppo(self):
        """Regressione: la graffa a due colonne del volume cartaceo.

        Nel PDF il suffisso comune compare appiattito sulla prima riga del
        gruppo; senza questa gestione "ipertrofia (benigna)" perdeva
        "della prostata" e diventava un termine inutilizzabile.
        """
        testo = (
            " N40     Iperplasia della prostata\n"
            "         Incl.: ipertrofia:\n"
            "                 adenofibromatosa                della prostata\n"
            "                 (benigna)\n"
            "                 del lobo medio\n"
        )
        voce = analizza(testo)[0]

        self.assertIn("ipertrofia adenofibromatosa della prostata", voce.inclusi)
        self.assertIn("ipertrofia (benigna) della prostata", voce.inclusi)
        self.assertIn("ipertrofia del lobo medio della prostata", voce.inclusi)


class TestIndiceTermini(unittest.TestCase):
    def test_indice_collega_le_forme_espanse_al_codice(self):
        testo = (
            " I10          Ipertensione essenziale (primaria)\n"
            "              Incl.: ipertensione (arteriosa) (benigna)\n"
        )
        indice = costruisci_indice_termini(analizza(testo))

        self.assertEqual(indice["ipertensione arteriosa"], ["I10"])
        self.assertEqual(indice["ipertensione essenziale"], ["I10"])

    def test_un_termine_puo_avere_piu_codici(self):
        """L'indice non disambigua: raccoglie i candidati e lascia scegliere.

        La disambiguazione e' compito dell'entity linking, che ha il contesto;
        deciderla qui significherebbe buttare via alternative legittime.
        """
        testo = (
            " I48          Fibrillazione atriale\n"
            " I49          Fibrillazione atriale\n"
        )
        indice = costruisci_indice_termini(analizza(testo))

        self.assertEqual(indice["fibrillazione atriale"], ["I48", "I49"])


if __name__ == "__main__":
    unittest.main()
