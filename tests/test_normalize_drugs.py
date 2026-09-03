"""
Test della risoluzione ATC (step 2).

Ogni test usa un indice AIFA in miniatura, costruito nel test stesso con le
stesse convenzioni di scrittura della fonte reale (maiuscolo, congiunzione "E"
per le associazioni, forme saline per esteso). Cosi' i test girano senza gli
82 MB di anagrafica, che non sono versionati.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from normalize_drugs import (  # noqa: E402
    IndiciAIFA,
    normalizza,
    risolvi,
    strategia_associazione,
    strategia_commerciale_abbreviato,
    strategia_forma_salina,
    strategia_suffisso_salino,
)
from schema import MetodoRisoluzione, StatoNormalizzazione  # noqa: E402


def indice_di_prova() -> IndiciAIFA:
    """Un indice AIFA in miniatura con le convenzioni della fonte reale."""
    indici = IndiciAIFA()
    sostanze = {
        "C07AB07": "BISOPROLOLO",
        "C10BA06": "ROSUVASTATINA E EZETIMIBE",
        "C10BX07": "ROSUVASTATINA, AMLODIPINA E LISINOPRIL",
        "B01AA03": "WARFARIN",
        "B01AB05": "ENOXAPARINA SODICA",
        "A02BC02": "PANTOPRAZOLO",
        "B03AA03": "FERROSO GLUCONATO",
    }
    for codice, descrizione in sostanze.items():
        indici.atc_a_descrizione[codice] = descrizione
        indici.descrizione_a_atc[normalizza(descrizione)] = codice

    commerciali = {
        "pantoprazolo sandoz": {"A02BC02"},
        "congescor": {"C07AB07"},
        "lyrica": {"N02BF02", "N03AX16"},
    }
    for denominazione, codici in commerciali.items():
        indici.denominazione_a_atc[denominazione] = set(codici)
        indici.per_primo_token[denominazione.split()[0]].append(denominazione)
    return indici


class TestStrategie(unittest.TestCase):
    def setUp(self):
        self.indici = indice_di_prova()

    def test_associazione_barra_diventa_congiunzione(self):
        """Il dataset scrive '/', AIFA scrive ' E '."""
        esito = strategia_associazione("rosuvastatina/ezetimibe", self.indici)

        self.assertEqual(esito[0], ["C10BA06"])

    def test_associazione_a_tre_usa_le_virgole(self):
        """AIFA scrive 'A, B E C' per le associazioni con tre sostanze."""
        esito = strategia_associazione(
            "rosuvastatina/amlodipina/lisinopril", self.indici
        )

        self.assertEqual(esito[0], ["C10BX07"])

    def test_suffisso_salino_richiede_corrispondenza_esatta(self):
        """'Warfarin sodico' -> 'warfarin' -> B01AA03."""
        esito = strategia_suffisso_salino("warfarin sodico", self.indici)

        self.assertEqual(esito[0], ["B01AA03"])

    def test_suffisso_salino_non_accosta_sostanze_diverse(self):
        """Il vincolo di esattezza e' cio' che rende sicura la regola.

        'Ferroso solfato' non deve finire su 'Ferroso gluconato': troncato
        diventa 'ferroso', che non e' una sostanza, quindi non risolve.
        """
        self.assertIsNone(strategia_suffisso_salino("ferroso solfato", self.indici))

    def test_forma_salina_completa_il_nome_abbreviato(self):
        """Direzione opposta: il referto abbrevia, AIFA scrive per esteso."""
        esito = strategia_forma_salina("enoxaparina", self.indici)

        self.assertEqual(esito[0], ["B01AB05"])

    def test_commerciale_abbreviato_per_prefisso_di_token(self):
        """'pantoprazolo sand' -> 'pantoprazolo sandoz', senza liste di sigle."""
        esito = strategia_commerciale_abbreviato("pantoprazolo sand", self.indici)

        self.assertEqual(esito[0], ["A02BC02"])

    def test_commerciale_abbreviato_non_accorcia_il_nome_aifa(self):
        """Un nome piu' lungo della denominazione AIFA non deve corrispondere."""
        self.assertIsNone(
            strategia_commerciale_abbreviato("congescor plus forte", self.indici)
        )


class TestCascata(unittest.TestCase):
    def setUp(self):
        self.indici = indice_di_prova()

    def test_il_metodo_registrato_riflette_la_strategia_giusta(self):
        """Regressione sull'ordine delle strategie.

        Con i sali prima dei commerciali, "pantoprazolo sand" risolveva
        troncando la sigla del produttore: stesso codice, ma provenienza
        registrata falsa. L'ordine attuale attribuisce il match alla strategia
        che lo spiega davvero.
        """
        voce = risolvi("pantoprazolo sand", "nome_commerciale", 10, self.indici)

        self.assertEqual(voce.codice_atc, "A02BC02")
        self.assertEqual(voce.metodo, MetodoRisoluzione.COMMERCIALE_ABBREVIATO)

    def test_piu_candidati_danno_ambiguo_non_una_scelta_arbitraria(self):
        """Scegliere qui produrrebbe un errore silenzioso a valle."""
        voce = risolvi("lyrica", "nome_commerciale", 5, self.indici)

        self.assertEqual(voce.stato, StatoNormalizzazione.AMBIGUO)
        self.assertIsNone(voce.codice_atc)
        self.assertEqual(voce.atc_candidati, ["N02BF02", "N03AX16"])

    def test_voce_sconosciuta_diventa_nil_esplicito(self):
        """Fuori dalla KB si dichiara, non si forza sul match piu' vicino."""
        voce = risolvi("sostanza inesistente", "principio_attivo", 1, self.indici)

        self.assertEqual(voce.stato, StatoNormalizzazione.NIL)
        self.assertIsNone(voce.codice_atc)

    def test_ogni_voce_risolta_porta_la_sua_fonte(self):
        voce = risolvi("Bisoprololo", "principio_attivo", 400, self.indici)

        self.assertEqual(voce.codice_atc, "C07AB07")
        self.assertIsNotNone(voce.fonte)
        self.assertIn("AIFA", voce.fonte)


if __name__ == "__main__":
    unittest.main()
