"""La metrica gerarchica dello step 11, e le sue trappole.

Una metrica nuova e' un pezzo di codice che produce numeri che nessuno puo'
controllare a occhio: se sbaglia, sbaglia in silenzio e la conclusione dello
step e' falsa. Questi test fissano il comportamento su esempi calcolati a mano,
comprese **due proprieta' controintuitive** che ho scoperto misurando e che
vanno protette dalla prossima «semplificazione»:

1. troncare i codici puo' **abbassare** il richiamo, non solo alzarlo;
2. il ranker casuale guadagna anche lui salendo di livello, ed e' il motivo per
   cui senza la sua riga le altre tabelle non dimostrano niente.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE / "src"))

from ranker import Caso  # noqa: E402
from valuta_gerarchica import (  # noqa: E402
    LIVELLI, Esito, RankerCasuale, antenati, bootstrap, errori_di_famiglia,
    intervallo, misure_gerarchiche, profondita_comune, richiamo_per_livello,
)


class TestLAlberoATC(unittest.TestCase):
    """I livelli non sono inventati: sono quelli del registro AIFA."""

    def test_gli_antenati_di_una_classe(self) -> None:
        self.assertEqual(antenati("C07AB"), ("C", "C07", "C07A", "C07AB"))

    def test_un_codice_piu_corto_ha_meno_antenati(self) -> None:
        """Meno specifico davvero, non per un errore di troncamento."""
        self.assertEqual(antenati("C07"), ("C", "C07"))

    def test_profondita_fra_due_statine(self) -> None:
        """Il caso che ha motivato lo step: statina semplice contro associata."""
        self.assertEqual(profondita_comune("C10AA", "C10BA"), 2)   # C, C10

    def test_profondita_fra_apparati_diversi(self) -> None:
        self.assertEqual(profondita_comune("C10AA", "A02BC"), 0)

    def test_profondita_massima_e_identita(self) -> None:
        self.assertEqual(profondita_comune("C07AB", "C07AB"), len(LIVELLI))


class TestIlRichiamoPerLivello(unittest.TestCase):

    def test_salendo_di_livello_una_quasi_giusta_diventa_giusta(self) -> None:
        ordini = {1: ["C10AA"]}
        bersagli = {1: frozenset({"C10BA"})}
        self.assertEqual(richiamo_per_livello(ordini, bersagli, 5, 5), 0.0)
        self.assertEqual(richiamo_per_livello(ordini, bersagli, 3, 5), 1.0)

    def test_troncare_puo_ABBASSARE_il_richiamo(self) -> None:
        """La trappola, misurata su 15 ricoveri di prova reali.

        `C03CA` (diuretici dell'ansa) e `C03DA` (antialdosteronici) collassano
        entrambi in `C03`. Due bersagli distinti centrati diventano **un solo**
        bersaglio centrato, e il denominatore scende da 4 a 3: 2/4 = 50% diventa
        1/3 = 33%.

        E' la ragione per cui il richiamo troncato da solo non basta e servono
        anche le metriche sugli antenati: chi guardasse solo la prima tabella
        concluderebbe che la metrica gerarchica e' sempre piu' generosa, e non
        e' vero.
        """
        ordini = {1: ["C03CA", "C03DA"]}
        bersagli = {1: frozenset({"C03CA", "C03DA", "A10BK", "N02BF"})}
        self.assertEqual(richiamo_per_livello(ordini, bersagli, 5, 5), 0.5)
        self.assertAlmostEqual(richiamo_per_livello(ordini, bersagli, 3, 5),
                               1 / 3)

    def test_il_taglio_a_k_avviene_prima_del_troncamento(self) -> None:
        """Troncare e poi deduplicare regalerebbe proposte dentro la stessa k."""
        ordini = {1: ["C03CA", "C03DA", "C07AB"]}       # k=2 -> C03CA, C03DA
        bersagli = {1: frozenset({"C07AB"})}
        self.assertEqual(richiamo_per_livello(ordini, bersagli, 3, 2), 0.0)

    def test_un_ricovero_senza_bersagli_non_conta(self) -> None:
        """Contarlo misurerebbe l'assenza di una domanda, non una risposta."""
        ordini = {1: ["C07AB"], 2: ["C07AB"]}
        bersagli = {1: frozenset({"C07AB"}), 2: frozenset()}
        self.assertEqual(richiamo_per_livello(ordini, bersagli, 5, 5), 1.0)


class TestLeMetricheGerarchiche(unittest.TestCase):

    def test_calcolate_a_mano(self) -> None:
        # proposta C10AA -> antenati {C, C10, C10A, C10AA}
        # bersaglio C10BA -> antenati {C, C10, C10B, C10BA}
        # comuni = {C, C10} = 2; hP = 2/4, hR = 2/4
        ordini = {1: ["C10AA"]}
        bersagli = {1: frozenset({"C10BA"})}
        g = misure_gerarchiche(ordini, bersagli, 5)
        self.assertAlmostEqual(g["hP"], 0.5)
        self.assertAlmostEqual(g["hR"], 0.5)
        self.assertAlmostEqual(g["hF"], 0.5)

    def test_una_proposta_di_un_altro_apparato_non_prende_credito(self) -> None:
        g = misure_gerarchiche({1: ["A02BC"]}, {1: frozenset({"C10BA"})}, 5)
        self.assertEqual(g["hP"], 0.0)
        self.assertEqual(g["hR"], 0.0)

    def test_la_proposta_esatta_prende_tutto(self) -> None:
        g = misure_gerarchiche({1: ["C10BA"]}, {1: frozenset({"C10BA"})}, 5)
        self.assertEqual(g["hF"], 1.0)


class TestGliErroriDiFamiglia(unittest.TestCase):

    def test_riconosce_la_quasi_giusta(self) -> None:
        esito = errori_di_famiglia({1: ["C10AA"]},
                                   {1: frozenset({"C10BA"})}, 5)
        self.assertEqual(esito["proposte_non_esatte"], 1)
        self.assertEqual(esito["quote"][2], 1.0)      # condivide C e C10

    def test_la_proposta_esatta_non_e_un_errore(self) -> None:
        esito = errori_di_famiglia({1: ["C10BA"]},
                                   {1: frozenset({"C10BA"})}, 5)
        self.assertEqual(esito["proposte_non_esatte"], 0)


class TestIlRankerCasuale(unittest.TestCase):
    """Il controllo dello step: senza, le altre tabelle non dimostrano niente."""

    def caso(self, enc: int) -> Caso:
        return Caso(enc, frozenset({"I50.9"}), frozenset(), frozenset(),
                    frozenset())

    def test_due_corse_danno_lo_stesso_ordine(self) -> None:
        """Altrimenti la differenza fra due metodi si confonde col sorteggio."""
        candidati = ["C07AB", "C03DA", "A02BC", "B01AC", "C10AA"]
        primo = [r.classe_atc for r in
                 RankerCasuale().ordina(self.caso(1), candidati)]
        secondo = [r.classe_atc for r in
                   RankerCasuale().ordina(self.caso(1), candidati)]
        self.assertEqual(primo, secondo)

    def test_pazienti_diversi_hanno_ordini_diversi(self) -> None:
        """Un ordine uguale per tutti sarebbe un ranker di frequenza, non il caso."""
        candidati = [f"C0{i}AA" for i in range(9)]
        primo = [r.classe_atc for r in
                 RankerCasuale().ordina(self.caso(1), candidati)]
        secondo = [r.classe_atc for r in
                   RankerCasuale().ordina(self.caso(2), candidati)]
        self.assertNotEqual(primo, secondo)

    def test_propone_tutti_i_candidati(self) -> None:
        candidati = ["C07AB", "C03DA", "A02BC"]
        proposte = RankerCasuale().ordina(self.caso(1), candidati)
        self.assertEqual({r.classe_atc for r in proposte}, set(candidati))


class TestLIncertezza(unittest.TestCase):
    """Il bootstrap: quali differenze sopravvivono al campione."""

    def esito(self, sigla: str, proposte: dict[int, list[str]]) -> Esito:
        bersagli = {enc: frozenset({"C07AB"}) for enc in proposte}
        return Esito(sigla, sigla, {}, {}, {}, proposte, bersagli)

    def test_i_percentili_di_una_distribuzione_nota(self) -> None:
        valori = [float(x) for x in range(100)]
        basso, alto = intervallo(valori, 0.95)
        self.assertEqual((basso, alto), (2.0, 97.0))

    def test_due_corse_danno_lo_stesso_intervallo(self) -> None:
        """Un intervallo che cambia a ogni corsa non si puo' riportare."""
        esiti = [self.esito("ibr", {i: ["C07AB"] for i in range(20)}),
                 self.esito("freq", {i: ["C03DA"] for i in range(20)})]
        primo = bootstrap(esiti, 5, giri=50)
        secondo = bootstrap(esiti, 5, giri=50)
        self.assertEqual(primo["per_ranker"], secondo["per_ranker"])

    def test_una_differenza_netta_esclude_lo_zero(self) -> None:
        """Il controllo di sanita': se un ranker centra sempre e l'altro mai,
        l'intervallo della differenza non deve contenere lo zero."""
        esiti = [self.esito("ibr", {i: ["C07AB"] for i in range(30)}),
                 self.esito("freq", {i: ["A02BC"] for i in range(30)})]
        esito = bootstrap(esiti, 5, giri=200)
        basso, _ = esito["differenze_appaiate"]["ibr-freq"]["hF"]
        self.assertGreater(basso, 0)

    def test_le_coppie_da_confrontare_sono_esplicite(self) -> None:
        """Le differenze si chiedono per nome: `a-b`.

        La prima versione confrontava solo ibrido e frequenza, con una chiave
        fissa; generalizzandola a coppie arbitrarie la chiave e' cambiata e un
        test e' rimasto indietro. Questo fissa la forma.
        """
        esiti = [self.esito("ibr", {i: ["C07AB"] for i in range(10)}),
                 self.esito("freq", {i: ["C03DA"] for i in range(10)}),
                 self.esito("llm_rem", {i: ["A02BC"] for i in range(10)})]
        esito = bootstrap(esiti, 5, giri=20,
                          coppie=[("ibr", "freq"), ("ibr", "llm_rem")])
        self.assertEqual(set(esito["differenze_appaiate"]),
                         {"ibr-freq", "ibr-llm_rem"})

    def test_una_coppia_con_un_ranker_assente_viene_saltata(self) -> None:
        """Chiedere `--llm locale` senza il remoto non deve far esplodere nulla."""
        esiti = [self.esito("ibr", {i: ["C07AB"] for i in range(5)})]
        esito = bootstrap(esiti, 5, giri=10, coppie=[("ibr", "freq")])
        self.assertEqual(esito["differenze_appaiate"], {})

    def test_ricampiona_i_pazienti_non_le_prescrizioni(self) -> None:
        """L'unita' e' il ricovero: le prescrizioni dello stesso paziente non
        sono indipendenti, e trattarle come tali stringerebbe gli intervalli
        fino a farli mentire."""
        esiti = [self.esito("ibr", {i: ["C07AB"] for i in range(7)})]
        self.assertEqual(bootstrap(esiti, 5, giri=10)["ricoveri_ricampionati"], 7)


if __name__ == "__main__":
    unittest.main()
