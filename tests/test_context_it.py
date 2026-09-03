"""
Test della logica ConText italiana (step 3).

Ogni caso riproduce una formulazione realmente presente nelle anamnesi. Sono i
test piu' importanti del progetto finora: un errore qui inverte il significato
clinico di un'affermazione, e lo step 2 ha gia' mostrato dove porta — una
menzione di "versamento pericardico" collegata al codice del versamento quando
il referto dice che NON c'e'.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import spacy  # noqa: E402

from context_it import (  # noqa: E402
    Attributo,
    Direzione,
    attributi_per_entita,
    trova_ambiti,
)


class BaseConText(unittest.TestCase):
    """Carica il modello una volta sola: e' l'operazione piu' lenta dei test."""

    @classmethod
    def setUpClass(cls):
        cls.nlp = spacy.load("it_core_news_sm", exclude=["ner", "parser", "lemmatizer"])
        cls.nlp.add_pipe("sentencizer")

    def attributi(self, testo: str, entita: str) -> dict:
        """Attributi assegnati alla sottostringa `entita` dentro `testo`."""
        documento = self.nlp(testo)
        inizio_carattere = testo.index(entita)
        fine_carattere = inizio_carattere + len(entita)
        inizio = fine = None
        for token in documento:
            if token.idx <= inizio_carattere < token.idx + len(token.text):
                inizio = token.i
            if token.idx < fine_carattere <= token.idx + len(token.text):
                fine = token.i + 1
        self.assertIsNotNone(inizio, "entita' non allineata ai token")
        return attributi_per_entita(trova_ambiti(documento), inizio, fine)


class TestNegazione(BaseConText):
    def test_nega_semplice(self):
        attributi = self.attributi("Nega diabete mellito.", "diabete mellito")

        self.assertIn(Attributo.NEGAZIONE, attributi)

    def test_negazione_si_estende_su_un_elenco(self):
        """In italiano clinico la negazione copre l'elenco intero.

        Per questo virgola e congiunzione NON terminano l'ambito.
        """
        testo = "Nega diabete mellito, ipertensione arteriosa e dislipidemia."

        self.assertIn(Attributo.NEGAZIONE, self.attributi(testo, "ipertensione arteriosa"))

    def test_il_terminatore_ferma_la_negazione(self):
        """'ma' apre un'affermazione nuova: cio' che segue non e' negato."""
        testo = "Nega diabete mellito ma riferisce ipertensione arteriosa."

        self.assertNotIn(
            Attributo.NEGAZIONE, self.attributi(testo, "ipertensione arteriosa")
        )
        self.assertIn(Attributo.NEGAZIONE, self.attributi(testo, "diabete mellito"))

    def test_non_nega_cio_che_segue(self):
        """Regressione dal difetto trovato allo step 2.

        Il confronto di stringhe collegava "non versamento pericardico" al
        codice del versamento pericardico, invertendo il significato clinico.
        """
        attributi = self.attributi("Non versamento pericardico.", "versamento pericardico")

        self.assertIn(Attributo.NEGAZIONE, attributi)

    def test_assenza_di(self):
        attributi = self.attributi(
            "Assenza di versamento pericardico.", "versamento pericardico"
        )

        self.assertIn(Attributo.NEGAZIONE, attributi)

    def test_la_negazione_non_scavalca_la_frase(self):
        """Il confine di frase e' il limite piu' forte di un ambito."""
        testo = "Nega diabete mellito. Ipertensione arteriosa in terapia."

        self.assertNotIn(
            Attributo.NEGAZIONE, self.attributi(testo, "Ipertensione arteriosa")
        )

    def test_marcatore_composto_vince_su_quello_semplice(self):
        """'negativo per' deve essere riconosciuto prima di 'non'."""
        ambiti = trova_ambiti(self.nlp("Negativo per ischemia miocardica."))
        espressioni = {a.marcatore.espressione for a in ambiti}

        self.assertIn("negativo per", espressioni)


class TestIncertezza(BaseConText):
    def test_sospetta(self):
        attributi = self.attributi(
            "Sospetta cardiopatia ischemica cronica.", "cardiopatia ischemica cronica"
        )

        self.assertIn(Attributo.INCERTEZZA, attributi)
        self.assertNotIn(Attributo.NEGAZIONE, attributi)


class TestStoricita(BaseConText):
    def test_pregressa_non_cambia_la_polarita(self):
        """La storicita' non nega: la condizione c'e' stata davvero.

        Resta pero' registrata, perche' una fibrillazione atriale pregressa e
        una in atto portano a terapie diverse.
        """
        attributi = self.attributi(
            "Pregressa fibrillazione atriale parossistica.",
            "fibrillazione atriale parossistica",
        )

        self.assertIn(Attributo.STORICITA, attributi)
        self.assertNotIn(Attributo.NEGAZIONE, attributi)

    def test_negazione_e_storicita_convivono(self):
        """Gli attributi non si escludono: servono entrambi."""
        attributi = self.attributi(
            "Nega pregressa fibrillazione atriale.", "fibrillazione atriale"
        )

        self.assertIn(Attributo.NEGAZIONE, attributi)
        self.assertIn(Attributo.STORICITA, attributi)


class TestAmbitoIndietro(BaseConText):
    def test_marcatore_all_indietro(self):
        """'assente' qualifica cio' che lo precede."""
        attributi = self.attributi("Versamento pericardico assente.", "Versamento pericardico")

        self.assertIn(Attributo.NEGAZIONE, attributi)
        self.assertEqual(
            attributi[Attributo.NEGAZIONE].direzione, Direzione.INDIETRO
        )


class TestNessunAttributo(BaseConText):
    def test_affermazione_semplice_resta_pulita(self):
        """Il rischio opposto: marcatori che scattano dove non devono."""
        attributi = self.attributi(
            "Ipertensione arteriosa in terapia con ramipril.", "Ipertensione arteriosa"
        )

        self.assertEqual(attributi, {})


if __name__ == "__main__":
    unittest.main()
