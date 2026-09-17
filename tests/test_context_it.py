"""Test della logica ConText italiana (step 3)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import spacy  # noqa: E402

from context_it import (  # noqa: E402
    Attributo,
    Direzione,
    ambiti_familiarita,
    attributi_per_entita,
    soggetto_familiare,
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


class TestNonRiferisce(BaseConText):
    """«Non riferisce X» e' una negazione, non un'affermazione."""

    def test_non_riferisce_nega(self):
        self.assertIn(Attributo.NEGAZIONE,
                      self.attributi("Non riferisce angina da sforzo.", "angina"))

    def test_nega_l_elenco_intero(self):
        testo = "Non riferisce angina ne' cardiopatia ischemica."
        self.assertIn(Attributo.NEGAZIONE, self.attributi(testo, "angina"))
        self.assertIn(Attributo.NEGAZIONE,
                      self.attributi(testo, "cardiopatia ischemica"))

    def test_le_varianti_al_participio(self):
        for frase, entita in (
            ("Non riferiti episodi di angina.", "angina"),
            ("Non riferita angina da sforzo.", "angina"),
            ("Non riferito diabete mellito.", "diabete mellito"),
        ):
            with self.subTest(frase=frase):
                self.assertIn(Attributo.NEGAZIONE, self.attributi(frase, entita))

    def test_riferisce_da_solo_resta_un_terminatore(self):
        """La correzione non deve rompere cio' per cui il terminatore esiste."""
        testo = "Nega diabete ma riferisce ipertensione arteriosa."
        self.assertIn(Attributo.NEGAZIONE, self.attributi(testo, "diabete"))
        self.assertNotIn(Attributo.NEGAZIONE,
                         self.attributi(testo, "ipertensione arteriosa"))

    def test_una_affermazione_semplice_resta_affermata(self):
        self.assertNotIn(Attributo.NEGAZIONE,
                         self.attributi("Riferisce angina da sforzo.", "angina"))


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
            "Pregressa tachicardia sopraventricolare parossistica.",
            "tachicardia sopraventricolare parossistica",
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
            "Ipertensione arteriosa ben compensata dai farmaci.", "Ipertensione arteriosa"
        )

        self.assertEqual(attributi, {})


class TestSoggettoFamiliare(unittest.TestCase):
    """L'asse *experiencer*: distinguere il paziente dai suoi parenti."""

    def ambito(self, testo: str) -> str | None:
        ambiti = ambiti_familiarita(testo)
        return testo[ambiti[0].inizio:ambiti[0].fine].strip() if ambiti else None

    def test_la_forma_piu_frequente_del_corpus(self):
        # "familiarita per" ricorre 431 volte nelle 1000 anamnesi.
        testo = "Familiarita per cardiopatia ischemica (padre)."
        self.assertEqual(self.ambito(testo), "cardiopatia ischemica (padre)")

    def test_la_menzione_dentro_l_ambito_e_di_un_familiare(self):
        testo = "Familiarita per ipotiroidismo (madre)."
        inizio = testo.index("ipotiroidismo")
        trovato = soggetto_familiare(testo, inizio, inizio + len("ipotiroidismo"))
        self.assertIsNotNone(trovato)
        self.assertEqual(trovato.espressione.lower(), "familiarita per")

    def test_la_menzione_fuori_dall_ambito_resta_del_paziente(self):
        # Il punto chiude l'ambito: l'ipertensione e' del paziente.
        testo = "Familiarita per ipotiroidismo. Ipertensione arteriosa in cura."
        inizio = testo.index("Ipertensione")
        self.assertIsNone(soggetto_familiare(testo, inizio, inizio + 12))

    def test_i_due_assi_sono_indipendenti(self):
        # "familiarita negativa per cad" e' insieme familiare e negata: sono
        # due domande diverse, e comprimerle in `stato` perdeva l'una o l'altra.
        testo = "Familiarita negativa per CAD."
        inizio = testo.index("CAD")
        self.assertIsNotNone(soggetto_familiare(testo, inizio, inizio + 3))

    def test_l_elenco_separato_da_virgole_resta_nell_ambito(self):
        testo = "Familiarita positiva per ipotiroidismo (madre), cardiopatia ischemica (padre)."
        inizio = testo.index("cardiopatia")
        self.assertIsNotNone(soggetto_familiare(testo, inizio, inizio + 11))

    def test_una_nuova_affermazione_in_maiuscola_chiude_l_ambito(self):
        # Nel corpus i referti incollano affermazioni senza punteggiatura. Senza
        # questo terminatore "Ex fumatore" diventerebbe un'abitudine del padre.
        testo = ("Familiarita per cardiopatia ischemica ed ipotiroidismo "
                 "Ex fumatore, poche sigarette al giorno")
        inizio = testo.index("Ex fumatore")
        self.assertIsNone(soggetto_familiare(testo, inizio, inizio + 11))

    def test_gli_acronimi_non_chiudono_l_ambito(self):
        # CAD, IMA, MCV, HCM sono ovunque nel corpus: un terminatore che si
        # attivasse su ogni maiuscola li spezzerebbe tutti.
        testo = "Familiarita per CAD (padre, fratello IMA)."
        inizio = testo.index("IMA")
        self.assertIsNotNone(soggetto_familiare(testo, inizio, inizio + 3))

    def test_il_taglio_non_avviene_dentro_una_parentesi(self):
        testo = "Familiarita per ipotiroidismo (padre, in cura per Parkinson, madre ETP)"
        inizio = testo.index("Parkinson")
        self.assertIsNotNone(soggetto_familiare(testo, inizio, inizio + 9))

    def test_una_menzione_non_ancorata_non_riceve_soggetto(self):
        # Le citazioni che il modello non ha copiato alla lettera non hanno
        # offset: senza posizione la regola di prossimita' non e' applicabile.
        self.assertIsNone(soggetto_familiare("Familiarita per CAD.", None, None))

    def test_una_frase_senza_marcatori_non_apre_ambiti(self):
        self.assertEqual(ambiti_familiarita("Nega diabete e ipertensione."), [])


class TestParenteNominatoDirettamente(unittest.TestCase):
    """Il secondo modo di parlare di un parente: nominarlo, senza dire "familiarita'"."""

    def _familiari(self, testo):
        return [testo[a.inizio:a.fine] for a in ambiti_familiarita(testo)]

    def test_il_caso_che_ha_fatto_nascere_la_regola(self):
        testo = "Nega familiarita per cardiopatia. Zia e nonna fibrillanti. Ex fumatore."
        self.assertIn("Zia e nonna fibrillanti", self._familiari(testo))

    def test_parente_deceduto_per_una_causa(self):
        testo = "APF: Madre deceduta a 76 anni per fibrillazione atriale."
        self.assertIn("Madre deceduta a 76 anni per fibrillazione atriale",
                      self._familiari(testo))

    def test_l_ambito_si_ferma_a_fine_frase(self):
        """Regressione dalla misura vera: con una finestra a lunghezza fissa
        invece che a fine frase, «appendicite» e «alluce valgo» — che sono
        interventi DEL PAZIENTE — finivano marcati come familiari."""
        testo = ("Padre deceduto per IMA a 70 anni. "
                 "Interventi pregressi: ernia inguinale, alluce valgo.")
        familiari = " ".join(self._familiari(testo))
        self.assertIn("Padre deceduto per IMA", familiari)
        self.assertNotIn("ernia inguinale", familiari)
        self.assertNotIn("alluce valgo", familiari)


    def test_la_regola_registrata_nomina_il_parente_giusto(self):
        """La conclusione non cambia (familiare in ogni caso), ma la provenienza
        deve permettere di risalire al parente giusto. Trovato rileggendo i dati:
        la silicosi del padre risultava attribuita a «madre deceduta»."""
        testo = ("APF: Madre deceduta a 76 anni per fibrillazione atriale, "
                 "padre deceduto per complicanze di silicosi.")
        inizio = testo.index("silicosi")
        ambito = soggetto_familiare(testo, inizio, inizio + len("silicosi"))
        self.assertIsNotNone(ambito)
        self.assertIn("padre", ambito.espressione.lower())
        self.assertNotIn("madre", ambito.espressione.lower())

    def test_il_parente_che_riferisce_non_e_il_malato(self):
        """«La madre riferisce» introduce chi racconta, non chi e' malato:
        l'ipertensione e' del paziente e deve restare sua."""
        testo = "La madre riferisce tendenza alle lipotimie. Ipertensione arteriosa in cura."
        self.assertEqual(self._familiari(testo), [])

    def test_un_parente_senza_malattia_non_apre_nulla(self):
        for testo in ("Vive con il fratello, autonomi. Ipotiroidismo in cura.",
                      "Due fratelli in buona salute.",
                      "Nato a termine (madre secondigravida)."):
            with self.subTest(testo=testo):
                self.assertEqual(self._familiari(testo), [])

    def test_convive_con_il_marcatore_esplicito(self):
        testo = ("Familiarita per cardiopatia ischemica (padre). "
                 "Madre affetta da diabete mellito.")
        familiari = " ".join(self._familiari(testo))
        self.assertIn("cardiopatia ischemica", familiari)
        self.assertIn("Madre affetta da diabete mellito", familiari)


if __name__ == "__main__":
    unittest.main()
