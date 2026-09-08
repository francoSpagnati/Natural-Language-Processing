"""
Test del gazetteer e della pipeline A (step 3).

I test sul gazetteer usano i vocabolari veri, perche' il loro comportamento
dipende dal contenuto: verificarne le regole su un vocabolario finto direbbe
poco. Vengono saltati se i file intermedi non sono stati generati, cosi' chi
clona il repository non vede fallimenti spuri.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gazetteer import (  # noqa: E402
    ETICHETTA_CONDIZIONE,
    ETICHETTA_FARMACO,
    PERCORSO_MAPPATURA_ATC,
    PERCORSO_TERMINOLOGIA_ICD,
    GazetteerClinico,
    termine_ammissibile,
    varianti_derivate,
)

VOCABOLARI_PRESENTI = PERCORSO_MAPPATURA_ATC.exists() and PERCORSO_TERMINOLOGIA_ICD.exists()


class TestFiltriDelVocabolario(unittest.TestCase):
    """Questi non hanno bisogno dei file: sono regole pure."""

    def test_scarta_le_voci_delle_tabelle_di_mortalita(self):
        """In coda al volume ICD ci sono tabelle con voci numerate."""
        self.assertFalse(termine_ammissibile("077 tumore maligno della prostata c61"))

    def test_scarta_i_marcatori_di_classificazione(self):
        """'S.A.I.' significa 'senza altra indicazione': non e' clinica."""
        self.assertFalse(termine_ammissibile("cardiopatia ipertensiva s.a.i"))

    def test_scarta_le_parole_troppo_generiche(self):
        self.assertFalse(termine_ammissibile("dolore"))
        self.assertFalse(termine_ammissibile("edema"))

    def test_accetta_un_termine_clinico_normale(self):
        self.assertTrue(termine_ammissibile("fibrillazione atriale parossistica"))

    def test_varianti_tolgono_i_qualificatori_residuali(self):
        """'Altro ipotiroidismo' e' il modo ICD di dire 'ipotiroidismo'."""
        self.assertIn("ipotiroidismo", varianti_derivate("altro ipotiroidismo"))

    def test_varianti_tolgono_il_non_specificato_finale(self):
        self.assertIn(
            "cardiopatia ischemica cronica",
            varianti_derivate("cardiopatia ischemica cronica, non specificata"),
        )

    def test_varianti_non_toccano_i_qualificatori_clinici(self):
        """'cronica' distingue condizioni diverse: non va rimossa."""
        self.assertEqual(varianti_derivate("cardiopatia ischemica cronica"), [])


@unittest.skipUnless(VOCABOLARI_PRESENTI, "vocabolari non generati")
class TestGazetteer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gazetteer = GazetteerClinico()

    def _menzioni(self, testo: str):
        return self.gazetteer.trova(self.gazetteer.nlp(testo))

    def test_riconosce_farmaci_e_condizioni_con_i_codici(self):
        menzioni = {m.testo: m for m in self._menzioni(
            "Ipertensione arteriosa in terapia con bisoprololo."
        )}

        self.assertEqual(menzioni["Ipertensione arteriosa"].etichetta, ETICHETTA_CONDIZIONE)
        self.assertEqual(menzioni["Ipertensione arteriosa"].codici, ["I10"])
        self.assertEqual(menzioni["bisoprololo"].etichetta, ETICHETTA_FARMACO)
        self.assertEqual(menzioni["bisoprololo"].codici, ["C07AB07"])

    def test_vince_la_menzione_piu_lunga(self):
        """Fra 'fibrillazione atriale' e la forma parossistica vince la seconda."""
        menzioni = self._menzioni("Fibrillazione atriale parossistica di recente riscontro.")

        self.assertEqual(len(menzioni), 1)
        self.assertEqual(menzioni[0].testo, "Fibrillazione atriale parossistica")

    def test_gli_offset_puntano_al_testo_originale(self):
        """La tracciabilita' richiesta dal brief: posizione esatta nel referto."""
        testo = "Paziente con ipotiroidismo in trattamento."
        menzione = self._menzioni(testo)[0]

        self.assertEqual(testo[menzione.inizio:menzione.fine], menzione.testo)

    def test_le_forme_monosillabiche_generiche_sono_escluse(self):
        """Regressione: l'espansione dei parentetici generava tronchi nudi.

        Da "insufficienza (cardiaca) (renale)" usciva "insufficienza", che
        estraeva 670 falsi positivi sul corpus.
        """
        self.assertNotIn("insufficienza", self.gazetteer.forme_condizioni)
        self.assertNotIn("malattia", self.gazetteer.forme_condizioni)
        # Ma i termini che l'ICD usa da soli come titolo restano.
        self.assertIn("ipotiroidismo", self.gazetteer.forme_condizioni)


@unittest.skipUnless(VOCABOLARI_PRESENTI, "vocabolari non generati")
class TestPipelineA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from extract_a import RisolutoreATC

        cls.gazetteer = GazetteerClinico()
        cls.risolutore = RisolutoreATC()

    def _stato(self, anamnesi: str, ingresso: str = "", dimissione: str | None = None):
        from data_loading import Referto, RecordPaziente

        referti = [
            Referto("Anamnesi", None, None, anamnesi),
            Referto("Terapia medica all'ingresso", None, None, ingresso),
        ]
        if dimissione is not None:
            referti.append(Referto("Terapia alla Dimissione", None, None, dimissione))

        from extract_a import estrai

        return estrai(
            RecordPaziente(enc_oid=1, referti=referti), self.gazetteer, self.risolutore
        )

    def test_la_negazione_arriva_fino_allo_stato_paziente(self):
        """Il pezzo che conta: ConText deve incidere sul contratto dati."""
        from schema import StatoConoscenza

        stato = self._stato("Nega diabete mellito. Ipertensione arteriosa in terapia.")
        per_testo = {c.testo_grezzo: c for c in stato.condizioni}

        self.assertEqual(per_testo["diabete mellito"].stato, StatoConoscenza.NEGATO)
        self.assertEqual(
            per_testo["Ipertensione arteriosa"].stato, StatoConoscenza.AFFERMATO
        )

    def test_le_condizioni_negate_non_entrano_fra_quelle_affermate(self):
        stato = self._stato("Nega diabete mellito.")

        self.assertEqual(stato.condizioni_affermate, [])

    def test_ogni_entita_porta_la_regola_che_l_ha_generata(self):
        """Requisito di tracciabilita' del brief."""
        stato = self._stato("Nega diabete mellito.")
        condizione = stato.condizioni[0]

        self.assertIn("gazetteer", condizione.provenienza.regola)
        self.assertIn("ConText", condizione.provenienza.regola)
        self.assertIsNotNone(condizione.provenienza.inizio)

    def test_i_farmaci_di_dimissione_non_sono_farmaci_in_corso(self):
        """Usarli come input sarebbe una fuga dalla ground truth."""
        stato = self._stato(
            "Paziente iperteso.",
            ingresso="Lasix: 25 mg cpr. /die (ore 8) ;",
            dimissione='"Bisoprololo (Congescor cp.riv. 1.25 mg): da assumere 1,25 mg (ore 8)"',
        )

        self.assertEqual([f.nome_grezzo for f in stato.farmaci_in_corso], ["Lasix"])
        self.assertIn("Bisoprololo", [f.nome_grezzo for f in stato.farmaci])

    def test_sezione_allergie_assente_resta_ignota(self):
        from schema import StatoConoscenza

        stato = self._stato("Paziente iperteso.")

        self.assertEqual(stato.stato_sezione_allergie, StatoConoscenza.IGNOTO)

    def test_assenza_dichiarata_di_allergie(self):
        from schema import StatoConoscenza

        stato = self._stato(
            "Allergie e intolleranze: Allergie e intolleranze non note Anamnesi Remota: nulla."
        )

        self.assertEqual(stato.stato_sezione_allergie, StatoConoscenza.NEGATO)

    def test_record_senza_dimissione_viene_annotato(self):
        stato = self._stato("Paziente iperteso.")

        self.assertTrue(any("ground truth" in nota for nota in stato.note_estrazione))


if __name__ == "__main__":
    unittest.main()


class TestFormeFarmacoAmmissibili(unittest.TestCase):
    """Regressione. Il parsing del campo semi-strutturato aveva lasciato nel
    vocabolario voci come "5 mg" e "2.5 mg". Come forme del gazetteer trovavano
    riscontro ovunque: "Ramipril 2.5 mg" faceva emergere un farmaco chiamato
    "2.5 mg", che finiva nelle etichette silver dello step 5 e veniva imparato
    dal NER."""

    def test_dosi_e_forme_farmaceutiche_respinte(self):
        from gazetteer import forma_farmaco_ammissibile

        for forma in ("5 mg", "2.5 mg", "ore 17", "cpr.", "-", "td"):
            self.assertFalse(forma_farmaco_ammissibile(forma), forma)

    def test_nomi_commerciali_con_cifre_conservati(self):
        """Il filtro non deve buttare via i marchi che contengono numeri."""
        from gazetteer import forma_farmaco_ammissibile

        for forma in ("mag 2", "omega 3 aur", "cacit 1000", "ciprofloxacina 500"):
            self.assertTrue(forma_farmaco_ammissibile(forma), forma)

