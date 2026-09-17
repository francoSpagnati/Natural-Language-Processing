"""Test della demo end-to-end e dei due difetti che ha fatto emergere.

La demo non e' una comodita' di presentazione: e' il primo punto del progetto in
cui qualcuno **usa** il contratto dati invece di misurarlo, ed e' per questo che
ha trovato due lacune che nessuna metrica aveva mostrato.

1. `Non riferisce X` veniva registrato come **affermato**, perche' `riferisce`
   e' un terminatore di ambito e chiudeva la negazione aperta da `non`.
2. La pipeline A estraeva le allergie ma **non le codificava mai in ATC**,
   quindi il filtro di sicurezza — che confronta codici, non nomi — era cieco
   su tutto cio' che quella pipeline produceva.

Questi test fissano entrambe le correzioni, piu' le proprieta' della demo che
un errore renderebbe una bugia davanti a chi guarda.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from demo import ESEMPI, estrai_deterministico, evidenzia, paziente_da_testo  # noqa: E402
from extract_a import allergie_dal_referto  # noqa: E402
from risolutori import RisolutoreATC  # noqa: E402


class TestAllergieCodificate(unittest.TestCase):
    """La pipeline A deve codificare in ATC le allergie a principi attivi.

    Senza codice il filtro dello step 8 non puo' confrontarle con nulla: il
    dato c'era, ma nella forma sbagliata per lo strato che doveva usarlo.
    """

    def record(self, testo_allergie: str):
        return paziente_da_testo(
            f"Paziente con ipertensione arteriosa. {testo_allergie}",
            "Amlodipina 5 mg: 1 cp")

    def test_un_principio_attivo_riceve_il_codice_atc(self):
        alle, _ = allergie_dal_referto(
            self.record("Allergie e intolleranze: Principi attivi "
                        "(acido acetilsalicilico)"),
            RisolutoreATC())
        self.assertEqual(len(alle), 1)
        self.assertEqual(alle[0].codice_atc, "B01AC06")

    def test_senza_risolutore_il_comportamento_resta_quello_di_prima(self):
        """Il parametro e' facoltativo: chi chiamava prima non cambia esito."""
        alle, _ = allergie_dal_referto(
            self.record("Allergie e intolleranze: Principi attivi "
                        "(acido acetilsalicilico)"))
        self.assertEqual(len(alle), 1)
        self.assertIsNone(alle[0].codice_atc)

    def test_gli_alimenti_non_vengono_codificati(self):
        """Un'allergia alimentare va conservata ma non vincola un farmaco.

        E' la distinzione che il campo `categoria` esiste per esprimere, e
        codificare un alimento come se fosse un principio attivo produrrebbe
        blocchi senza senso.
        """
        alle, _ = allergie_dal_referto(
            self.record("Allergie e intolleranze: Alimenti (crostacei)"),
            RisolutoreATC())
        self.assertEqual(len(alle), 1)
        self.assertIsNone(alle[0].codice_atc)

    def test_la_fonte_della_codifica_finisce_nella_provenienza(self):
        """Il vincolo di provenienza del progetto vale anche qui."""
        alle, _ = allergie_dal_referto(
            self.record("Allergie e intolleranze: Principi attivi "
                        "(acido acetilsalicilico)"),
            RisolutoreATC())
        self.assertIn("atc:", alle[0].provenienza.regola)


class TestCostruzioneDelPaziente(unittest.TestCase):

    def test_i_due_testi_diventano_un_ricovero_leggibile_dalle_pipeline(self):
        r = paziente_da_testo("Ipertensione arteriosa.", "Ramipril 5 mg: 1 cp")
        self.assertEqual(r.testo_anamnesi, "Ipertensione arteriosa.")
        self.assertEqual(r.testo_terapia_ingresso, "Ramipril 5 mg: 1 cp")

    def test_un_paziente_nuovo_non_ha_terapia_di_dimissione(self):
        """Non e' una dimenticanza: la dimissione e' cio' che il sistema deve
        prevedere, e metterla nell'ingresso sarebbe dare la risposta."""
        r = paziente_da_testo("Ipertensione.", "Ramipril 5 mg: 1 cp")
        self.assertFalse(r.ha_terapia_dimissione)


class TestEvidenziazione(unittest.TestCase):
    """Mostrare gli offset e' cio' che rende contestabile una raccomandazione."""

    def test_segna_gli_intervalli(self):
        self.assertEqual(evidenzia("abcdef", [(2, 4)]), "ab[cd]ef")

    def test_fonde_gli_intervalli_sovrapposti(self):
        """Due pipeline che riconoscono lo stesso punto non devono produrre
        parentesi annidate illeggibili."""
        self.assertEqual(evidenzia("abcdef", [(1, 4), (2, 5)]), "a[bcde]f")

    def test_senza_intervalli_restituisce_il_testo(self):
        self.assertEqual(evidenzia("abcdef", []), "abcdef")

    def test_intervalli_fuori_ordine(self):
        self.assertEqual(evidenzia("abcdef", [(4, 5), (0, 1)]), "[a]bcd[e]f")


class TestEsempiSintetici(unittest.TestCase):
    """Gli esempi vanno mostrati a terzi: non devono contenere testo del corpus."""

    def test_ogni_esempio_e_completo(self):
        for e in ESEMPI:
            with self.subTest(titolo=e.titolo):
                self.assertTrue(e.anamnesi.strip())
                self.assertTrue(e.terapia_ingresso.strip())
                self.assertTrue(e.mostra.strip())

    def test_il_gazetteer_riconosce_almeno_una_condizione_in_ogni_esempio(self):
        """Un esempio in cui l'estrazione non trova niente non dimostra niente."""
        for e in ESEMPI:
            with self.subTest(titolo=e.titolo):
                stato = estrai_deterministico(paziente_da_testo(e.anamnesi, e.terapia_ingresso))
                self.assertTrue(stato.condizioni, "nessuna condizione riconosciuta")


if __name__ == "__main__":
    unittest.main()
