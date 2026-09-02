"""
Test della costruzione dei vocabolari (step 1).

Coprono le funzioni di normalizzazione, che sono il punto in cui una svista
produce silenziosamente voci duplicate o mancate nel vocabolario chiuso — e il
vocabolario chiuso e' il fondamento di tutti gli step successivi.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from build_vocabularies import (  # noqa: E402
    conferma_principio_attivo,
    normalizza,
    ripulisci_frammento,
)
from schema import EsitoConfermaEsterna  # noqa: E402


class TestNormalizzazione(unittest.TestCase):
    def test_neutralizza_i_separatori_delle_associazioni(self):
        """Le due fonti separano diversamente le associazioni precostituite."""
        self.assertEqual(normalizza("Rosuvastatina/ezetimibe"), "rosuvastatina/ezetimibe")
        self.assertEqual(normalizza("  ACIDO   ACETILSALICILICO "), "acido acetilsalicilico")


class TestRipulisciFrammento(unittest.TestCase):
    def test_rimuove_intestazione_di_sezione(self):
        """Senza questo, la stessa condizione genera piu' voci distinte."""
        self.assertEqual(ripulisci_frammento("Fattori di rischio: obesita si"), "obesita si")
        self.assertEqual(
            ripulisci_frammento("Interventi pregressi: ernioplastica inguinale"),
            "ernioplastica inguinale",
        )

    def test_rimuove_punteggiatura_di_coda(self):
        """'nega episodi sincopali' e '...sincopali.' erano due voci separate."""
        self.assertEqual(
            ripulisci_frammento("nega episodi sincopali."), "nega episodi sincopali"
        )

    def test_non_tocca_un_termine_gia_pulito(self):
        self.assertEqual(ripulisci_frammento("ipertensione arteriosa"), "ipertensione arteriosa")


class TestConfermaPrincipioAttivo(unittest.TestCase):
    # Indice ATC ridotto, con le stesse convenzioni di scrittura di AIFA.
    INDICE = {
        "bisoprololo": "C07AB07",
        "enoxaparina sodica": "B01AB05",
        "rosuvastatina e ezetimibe": "C10BA06",
    }

    def test_corrispondenza_esatta(self):
        esito, codici = conferma_principio_attivo("Bisoprololo", self.INDICE)

        self.assertEqual(esito, EsitoConfermaEsterna.CONFERMATA)
        self.assertEqual(codici, ["C07AB07"])

    def test_forma_salina_riconosciuta_per_prefisso(self):
        """Il referto abbrevia, AIFA scrive per esteso: 'Enoxaparina sodica'."""
        esito, codici = conferma_principio_attivo("Enoxaparina", self.INDICE)

        self.assertEqual(esito, EsitoConfermaEsterna.CONFERMATA)
        self.assertEqual(codici, ["B01AB05"])

    def test_voce_assente_e_marcata_non_trovata(self):
        """Non si inventa un codice: si dichiara che non e' stato trovato."""
        esito, codici = conferma_principio_attivo("Silodosina", self.INDICE)

        self.assertEqual(esito, EsitoConfermaEsterna.NON_TROVATA)
        self.assertEqual(codici, [])

    def test_associazione_con_barra_non_matcha_la_convenzione_aifa(self):
        """Limite noto e documentato: AIFA usa ' E ', il dataset '/'.

        Questo test fissa il comportamento *attuale* per rendere visibile il
        problema; la conversione e' lavoro dello step 2.
        """
        esito, _ = conferma_principio_attivo("Rosuvastatina/ezetimibe", self.INDICE)

        self.assertEqual(esito, EsitoConfermaEsterna.NON_TROVATA)


if __name__ == "__main__":
    unittest.main()
