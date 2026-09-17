"""La misura dello step 11 — P, R e F1 per livello ATC — e le sue trappole."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE / "src"))

import ranker as modulo_ranker  # noqa: E402
from ranker import Caso, RankerFrequenza, pieghe  # noqa: E402
from valuta_gerarchica import (  # noqa: E402
    Esito, RankerCasuale, bootstrap, esempio_svolto, esito_da_proiezioni,
    intervallo, livelli_misurabili, misure_per_livello, precisione_richiamo_f1,
    spiegabilita, terapia_proposta, top_k_per_livello, valuta_incrociata,
)


def caso(enc: int, ingresso: set[str], dimissione: set[str],
         condizioni: set[str] = frozenset({"I50.9"})) -> Caso:
    return Caso(enc, frozenset(condizioni), frozenset(ingresso), frozenset(),
                frozenset(dimissione))


class TestLaMisuraSuUnInsieme(unittest.TestCase):

    def test_calcolata_a_mano(self) -> None:
        # proposti {C07, C03}, veri {C07, C10}: un comune su due e due.
        p, r, f = precisione_richiamo_f1({"C07", "C03"}, {"C07", "C10"})
        self.assertEqual((p, r, f), (0.5, 0.5, 0.5))

    def test_nessuna_proposta_vale_zero_non_un_errore(self) -> None:
        self.assertEqual(precisione_richiamo_f1(set(), {"C07"}), (0.0, 0.0, 0.0))

    def test_la_terapia_proposta_continua_l_ingresso(self) -> None:
        c = caso(1, {"A02BC"}, {"A02BC", "C07AB"})
        self.assertEqual(terapia_proposta(c, ["C07AB", "C03DA", "C10AA"], 2),
                         {"A02BC", "C07AB", "C03DA"})


class TestLaMisuraPerLivello(unittest.TestCase):
    """L'unita' e' la classe (5 caratteri): quattro livelli misurabili."""

    def setUp(self) -> None:
        modulo_ranker.LIVELLO_CLASSE = 5

    def test_i_livelli_seguono_l_unita(self) -> None:
        self.assertEqual(livelli_misurabili(), (1, 3, 4, 5))
        modulo_ranker.LIVELLO_CLASSE = 7
        self.assertEqual(livelli_misurabili(), (1, 3, 4, 5, 7))
        modulo_ranker.LIVELLO_CLASSE = 5

    def test_salendo_di_livello_una_quasi_giusta_diventa_giusta(self) -> None:
        # Proposta C10AA (statina), prescritta C10BA (statina in associazione):
        # sbagliata al 4o livello, giusta al 2o (C10).
        casi = {1: caso(1, set(), {"C10BA"})}
        m = misure_per_livello({1: ["C10AA"]}, casi, 5)
        self.assertEqual(m[5]["F1"], 0.0)
        self.assertEqual(m[3]["F1"], 1.0)

    def test_troncare_puo_ABBASSARE_la_precisione(self) -> None:
        """Due proposte distinte al 4o livello (C10AA, C10BA) contro due prescrizioni
        identiche: al 4o P = 1; al 2o le proposte collassano in {C10} e i veri pure, P
        resta 1. Ma con veri {C10AA, C07AB} e proposte {C10AA, C10BA}: al 4o P = 1/2, R
        = 1/2; al 2o proposte {C10}, veri {C10, C07}: P = 1, R = 1/2. Il richiamo non
        sale, la precisione si'. Il punto del test: la misura per livello non e'
        monotona per costruzione, quindi va calcolata, non dedotta.
        """
        casi = {1: caso(1, set(), {"C10AA", "C07AB"})}
        m = misure_per_livello({1: ["C10AA", "C10BA"]}, casi, 5)
        self.assertEqual((m[5]["P"], m[5]["R"]), (0.5, 0.5))
        self.assertEqual((m[3]["P"], m[3]["R"]), (1.0, 0.5))

    def test_il_taglio_a_k_avviene_prima_del_troncamento(self) -> None:
        # Con k = 1 la seconda proposta non entra, anche se al 1o livello
        # collasserebbe nella prima.
        casi = {1: caso(1, set(), {"C07AB"})}
        m = misure_per_livello({1: ["C10AA", "C07AB"]}, casi, 1)
        self.assertEqual(m[5]["R"], 0.0)

    def test_ogni_ricovero_pesa_uno(self) -> None:
        casi = {1: caso(1, set(), {"C07AB"}), 2: caso(2, set(), {"C07AB", "C03DA", "C10AA"})}
        m = misure_per_livello({1: ["C07AB"], 2: ["C07AB"]}, casi, 5)
        # ricovero 1: R = 1; ricovero 2: R = 1/3; media 2/3, non 2/4.
        self.assertAlmostEqual(m[5]["R"], 2 / 3)

    def test_la_continuita_conta_nella_proposta(self) -> None:
        """Un ranker che non propone niente prende comunque il credito
        dell'ingresso continuato: e' il pavimento della continuita'."""
        casi = {1: caso(1, {"A02BC", "C07AB"}, {"A02BC", "C07AB", "C10AA"})}
        m = misure_per_livello({1: []}, casi, 5)
        self.assertEqual(m[5]["P"], 1.0)
        self.assertAlmostEqual(m[5]["R"], 2 / 3)


class TestLaVersioneTopK(unittest.TestCase):

    def setUp(self) -> None:
        modulo_ranker.LIVELLO_CLASSE = 5

    def test_basta_una_proposta_centrata(self) -> None:
        casi = {1: caso(1, set(), {"C07AB", "C10AA"}), 2: caso(2, set(), {"C03DA"})}
        t = top_k_per_livello({1: ["A02BC", "C10AA"], 2: ["C07AB"]}, casi, 2)
        self.assertEqual(t[5], 0.5)

    def test_usa_la_chiave_del_dizionario_non_l_enc_oid(self) -> None:
        """Il bootstrap rinumera i ricoveri: lo stesso paziente puo' comparire
        due volte con chiavi diverse, e la misura deve seguire la chiave."""
        c = caso(99, set(), {"C07AB"})
        t = top_k_per_livello({0: ["C07AB"], 1: ["A02BC"]}, {0: c, 1: c}, 5)
        self.assertEqual(t[5], 0.5)

    def test_un_ricovero_senza_aggiunte_non_conta(self) -> None:
        casi = {1: caso(1, {"C07AB"}, {"C07AB"}), 2: caso(2, set(), {"C03DA"})}
        t = top_k_per_livello({1: [], 2: ["C03DA"]}, casi, 5)
        self.assertEqual(t[5], 1.0)


class TestLEsempioSvolto(unittest.TestCase):

    def test_riporta_i_conti_di_ogni_livello(self) -> None:
        modulo_ranker.LIVELLO_CLASSE = 5
        casi = {7: caso(7, {"A02BC"}, {"A02BC", "C07AB"})}
        e = esito_da_proiezioni("ibr", "ibrido", {7: ["C07AB", "C03DA"]}, casi, 2)
        testo = esempio_svolto(e, 7, 2)
        self.assertIn("ricovero 7", testo)
        self.assertIn("P 67% R 100% F1 80%", testo)


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

    def setUp(self) -> None:
        modulo_ranker.LIVELLO_CLASSE = 5

    def esito(self, sigla: str, proposte: dict[int, list[str]]) -> Esito:
        casi = {enc: caso(enc, set(), {"C07AB"}) for enc in proposte}
        return esito_da_proiezioni(sigla, sigla, proposte, casi, 5)

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
        basso, _ = esito["differenze_appaiate"]["ibr-freq"][5]
        self.assertGreater(basso, 0)

    def test_le_coppie_da_confrontare_sono_esplicite(self) -> None:
        """Le differenze si chiedono per nome: `a-b`."""
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


class TestLaValidazioneIncrociata(unittest.TestCase):
    """Ogni ricovero misurato una volta, da un ranker che non lo ha visto."""

    def casi(self, n: int = 40) -> list[Caso]:
        # Meta' dei pazienti ha I50.9 e riceve C03DA; l'altra meta' I10 e C07AB.
        # Cosi' un ranker che impara ha qualcosa da imparare, e la fuga di
        # informazione fra pieghe si vedrebbe.
        fuori = []
        for i in range(n):
            if i % 2:
                fuori.append(Caso(1000 + i, frozenset({"I50.9"}), frozenset(),
                                  frozenset(), frozenset({"C03DA"})))
            else:
                fuori.append(Caso(1000 + i, frozenset({"I10"}), frozenset(),
                                  frozenset(), frozenset({"C07AB"})))
        return fuori

    def test_le_pieghe_sono_disgiunte_e_coprono_tutto(self) -> None:
        casi = self.casi()
        divise = pieghe(casi, 5)
        visti = [c.enc_oid for p in divise for c in p]
        self.assertEqual(sorted(visti), sorted(c.enc_oid for c in casi))
        self.assertEqual(len(visti), len(set(visti)))

    def test_le_pieghe_sono_deterministiche(self) -> None:
        """Due corse, stesse pieghe: altrimenti due misure non si confrontano."""
        casi = self.casi()
        prime = [[c.enc_oid for c in p] for p in pieghe(casi, 5)]
        seconde = [[c.enc_oid for c in p] for p in pieghe(casi, 5)]
        self.assertEqual(prime, seconde)

    def test_ogni_ricovero_e_misurato_una_volta_sola(self) -> None:
        casi = self.casi()
        esiti = valuta_incrociata([RankerFrequenza], casi, 5, 5)
        self.assertEqual(len(esiti), 1)
        self.assertEqual(sorted(esiti[0].ordini), sorted(c.enc_oid for c in casi))

    def test_il_ranker_non_vede_il_paziente_su_cui_e_misurato(self) -> None:
        """Il controllo di fuga: un ranker che ricorda ogni paziente visto in
        addestramento e risponde solo su quelli deve fare ZERO in prova."""

        class Memorizza(RankerFrequenza):
            sigla = "mem"
            nome = "memorizza"

            def addestra(self, casi):
                self._visti = {c.enc_oid for c in casi}
                super().addestra(casi)

            def ordina(self, caso, candidati):
                if caso.enc_oid in self._visti:
                    return super().ordina(caso, candidati)
                return []

        esiti = valuta_incrociata([Memorizza], self.casi(), 5, 5)
        self.assertEqual(esiti[0].top_k[5], 0.0)



class TestLaSpiegabilita(unittest.TestCase):
    """Una proposta e' «motivata» se almeno un'indicazione ESC scatta per quel
    paziente. La frequenza non guarda il paziente, quindi le sue proposte sono
    motivate solo per coincidenza; lo si conta, non lo si afferma."""

    def test_conta_le_motivate_fra_tutte_e_fra_le_centrate(self):
        from conoscenza import Indicazione
        from ranker import RankerSimbolico

        regole = (Indicazione("C03DA", ("I50",), "I", "m", "f"),)
        casi = [Caso(1, frozenset({"I50.9"}), frozenset(), frozenset(),
                     frozenset({"C03DA", "A02BC"}))]
        esito = esito_da_proiezioni("x", "x", {1: ["C03DA", "A02BC", "C07AB"]},
                                    {1: casi[0]}, 3)
        q = spiegabilita([esito], k=3, simbolico=RankerSimbolico(regole))["x"]
        self.assertEqual((q["proposte"], q["motivate"]), (3, 1))
        self.assertEqual((q["centri"], q["centri_motivati"]), (2, 1))
        self.assertAlmostEqual(q["quota_centri_motivati"], 0.5)


class TestLePiegheStratificate(unittest.TestCase):

    def test_ogni_piega_ha_la_stessa_quota_di_scompensi(self):
        casi = [Caso(i, frozenset({"I50.9"} if i % 4 == 0 else {"I10"}), frozenset(),
                     frozenset(), frozenset({"C07AB"})) for i in range(200)]
        parti = pieghe(casi, 5, stratifica=True)
        quote = [sum(1 for c in p if "I50.9" in c.condizioni) for p in parti]
        self.assertEqual(quote, [10] * 5)
        self.assertEqual(sorted(c.enc_oid for p in parti for c in p), list(range(200)))


if __name__ == "__main__":
    unittest.main()
