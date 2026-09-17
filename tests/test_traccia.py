"""Test della traccia di provenienza sul grafo (step 9ter).

La traccia e' la risposta alla domanda «da dove viene questa raccomandazione»,
e la sua proprieta' fondante e' che **la risposta viene dal grafo**, non dai
dizionari da cui il grafo e' stato costruito. Se qualcuno la riscrivesse come
un attraversamento di strutture Python i test continuerebbero a passare sui
valori ma la proprieta' sarebbe persa — per questo alcuni di questi test
verificano la *forma del grafo*, non solo il risultato.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from grafo import CT, ICD, PIPELINE, PROV  # noqa: E402
from ranker import Caso, Indicazione, RankerSimbolico  # noqa: E402
from schema import (  # noqa: E402
    CondizioneEstratta,
    FarmacoEstratto,
    MomentoTerapia,
    Pipeline,
    Provenienza,
    Soggetto,
    StatoConoscenza,
    StatoNormalizzazione,
    StatoPaziente,
)
from traccia import (  # noqa: E402
    grafo_del_paziente,
    menzioni_da_stato,
    sostegno_del_concetto,
    traccia_raccomandazione,
)


def condizione(testo, codice, inizio, fine, pipeline=Pipeline.A_DETERMINISTICA,
               stato=StatoConoscenza.AFFERMATO, soggetto=Soggetto.PAZIENTE,
               regola="gazetteer:x"):
    return CondizioneEstratta(
        testo_grezzo=testo, concetto=testo, codice=codice,
        sistema_codifica="ICD-10" if codice else None,
        stato_normalizzazione=(StatoNormalizzazione.RISOLTO if codice
                               else StatoNormalizzazione.NIL),
        stato=stato, soggetto=soggetto,
        provenienza=Provenienza(pipeline=pipeline, campo_sorgente="Anamnesi",
                                testo_originale=testo, inizio=inizio, fine=fine,
                                regola=regola))


def stato_paziente(condizioni=(), farmaci=(), pipeline=Pipeline.A_DETERMINISTICA):
    return StatoPaziente(
        enc_oid=0, pipeline=pipeline, condizioni=list(condizioni),
        farmaci=list(farmaci), allergie=[],
        stato_sezione_allergie=StatoConoscenza.IGNOTO)


class TestGrafoDelPaziente(unittest.TestCase):

    def test_una_menzione_diventa_un_asserzione_con_il_suo_concetto(self):
        g = grafo_del_paziente(
            {"A": stato_paziente([condizione("scompenso", "I50.9", 0, 9)])},
            0, {"I50.9": "Scompenso cardiaco"}, {})
        asserzioni = list(g.subjects(CT.concetto, ICD["I50.9"]))
        self.assertEqual(len(asserzioni), 1)

    def test_le_menzioni_sovrapposte_di_due_pipeline_fanno_UNA_asserzione(self):
        """E' la decisione di modellazione dello step 7.

        Due pipeline che riconoscono lo stesso punto del referto non producono
        due fatti: producono un fatto sostenuto da due menzioni, e il numero di
        agenti diventa interrogabile.
        """
        g = grafo_del_paziente({
            "A": stato_paziente([condizione("scompenso", "I50.9", 0, 9)]),
            "B": stato_paziente([condizione("scompenso cardiaco", "I50.9", 0, 18,
                                            Pipeline.B_LLM, regola="llm:x")]),
        }, 0, {}, {})
        asserzioni = set(g.subjects(CT.concetto, ICD["I50.9"]))
        self.assertEqual(len(asserzioni), 1)
        nodo = asserzioni.pop()
        self.assertEqual(int(next(g.objects(nodo, CT.numeroPipeline))), 2)
        self.assertEqual(len(list(g.objects(nodo, PROV.wasDerivedFrom))), 2)

    def test_menzioni_lontane_restano_asserzioni_distinte(self):
        g = grafo_del_paziente({
            "A": stato_paziente([condizione("scompenso", "I50.9", 0, 9),
                                 condizione("ipertensione", "I10", 60, 72)]),
        }, 0, {}, {})
        self.assertEqual(len(set(g.subjects(CT.riguarda, None))), 2)

    def test_la_menzione_non_ancorata_e_esclusa(self):
        """Senza offset non c'e' niente da tracciare, e includerla darebbe una
        catena che finisce nel vuoto."""
        senza = condizione("scompenso", "I50.9", 0, 9)
        senza.provenienza.inizio = None
        senza.provenienza.fine = None
        self.assertEqual(menzioni_da_stato(stato_paziente([senza]), "A"), [])

    def test_il_concetto_porta_la_sua_fonte(self):
        """Il vincolo di provenienza del progetto: nessun codice senza fonte."""
        g = grafo_del_paziente(
            {"A": stato_paziente([condizione("scompenso", "I50.9", 0, 9)])},
            0, {"I50.9": "Scompenso cardiaco"}, {})
        fonti = list(g.objects(ICD["I50.9"], None))
        self.assertTrue(any("ICD-10" in str(f) for f in fonti))

    def test_la_regola_finisce_nel_grafo(self):
        """Non solo CHI ha prodotto la menzione, ma COME.

        E' la differenza fra `icd:termine_esatto` e
        `icd:generalizzazione_ambigua`, cioe' fra un codice certo e uno che
        qualcuno dovrebbe guardare.
        """
        g = grafo_del_paziente(
            {"A": stato_paziente([condizione("scompenso", "I50.9", 0, 9,
                                             regola="icd:generalizzazione_ambigua")])},
            0, {}, {})
        regole = [str(r) for r in g.objects(None, CT.regola)]
        self.assertIn("icd:generalizzazione_ambigua", regole)


class TestSostegnoInterrogato(unittest.TestCase):

    def grafo(self):
        return grafo_del_paziente({
            "A": stato_paziente([condizione("scompenso", "I50.9", 0, 9)]),
            "B": stato_paziente([condizione("scompenso cardiaco", "I50.9", 0, 18,
                                            Pipeline.B_LLM, regola="llm:m")]),
        }, 0, {"I50.9": "Scompenso cardiaco"}, {})

    def test_riporta_agente_campo_e_offset_di_ogni_menzione(self):
        sostegno = sostegno_del_concetto(self.grafo(), "I50.9")
        self.assertEqual(len(sostegno), 2)
        for s in sostegno:
            self.assertIn(s["agente"], ("A", "B"))
            self.assertEqual(s["campo"], "Anamnesi")
            self.assertEqual(s["inizio"], 0)
            self.assertEqual(s["agenti_distinti"], 2)

    def test_riporta_etichetta_e_fonte_della_terminologia(self):
        s = sostegno_del_concetto(self.grafo(), "I50.9")[0]
        self.assertEqual(s["etichetta"], "Scompenso cardiaco")
        self.assertIn("ICD-10", s["fonte_terminologia"])

    def test_un_codice_assente_non_ha_sostegno(self):
        self.assertEqual(sostegno_del_concetto(self.grafo(), "Z99.9"), [])


class TestTracciaDellaRaccomandazione(unittest.TestCase):
    """L'anello fra la regola citata e il fatto estratto e' il codice ICD."""

    def setUp(self):
        self.g = grafo_del_paziente(
            {"A": stato_paziente([condizione("scompenso", "I50.9", 0, 9)])},
            0, {"I50.9": "Scompenso cardiaco"}, {})
        self.caso = Caso(0, frozenset({"I50.9"}), frozenset(), frozenset(),
                         frozenset())

    def test_la_catena_arriva_dalla_regola_fino_agli_offset(self):
        regole = (Indicazione("C03DA", ("I50",), "I", "terzo pilastro",
                              "ESC 2021, heart failure"),)
        t = traccia_raccomandazione(self.g, "C03DA", self.caso,
                                    RankerSimbolico(regole))
        self.assertEqual(len(t["indicazioni"]), 1)
        ind = t["indicazioni"][0]
        self.assertEqual(ind["classe_raccomandazione"], "I")
        self.assertIn("ESC 2021", ind["fonte"])
        self.assertEqual(ind["condizioni"][0]["codice"], "I50.9")
        menzione = ind["condizioni"][0]["sostegno"][0]
        self.assertEqual((menzione["inizio"], menzione["fine"]), (0, 9))

    def test_una_proposta_senza_regola_lo_dichiara(self):
        """Il 40% delle prescrizioni che nessuna linea guida regola.

        Dirlo e' parte della risposta: «non so perche', ma in questo reparto si
        fa» e' un'informazione diversa da una raccomandazione citata, e
        confonderle sarebbe la bugia piu' facile da raccontare.
        """
        t = traccia_raccomandazione(self.g, "D07AC", self.caso,
                                    RankerSimbolico(()))
        self.assertEqual(t["indicazioni"], [])

    def test_due_indicazioni_indipendenti_compaiono_entrambe(self):
        regole = (
            Indicazione("A10BK", ("I50",), "I", "quarto pilastro", "ESC 2023 HF"),
            Indicazione("A10BK", ("E11",), "I", "diabete con malattia CV",
                        "ESC 2023 diabete"),
        )
        caso = Caso(0, frozenset({"I50.9", "E11"}), frozenset(), frozenset(),
                    frozenset())
        g = grafo_del_paziente({"A": stato_paziente([
            condizione("scompenso", "I50.9", 0, 9),
            condizione("diabete", "E11", 30, 37)])}, 0, {}, {})
        t = traccia_raccomandazione(g, "A10BK", caso, RankerSimbolico(regole))
        self.assertEqual(len(t["indicazioni"]), 2)

    def test_il_fatto_non_estratto_viaggia_nella_traccia(self):
        """Chi legge deve sapere su che cosa la linea guida avrebbe deciso."""
        regole = (Indicazione("C09A", ("I50",), "I", "primo pilastro", "ESC 2021",
                              fatto_non_estratto="frazione di eiezione"),)
        t = traccia_raccomandazione(self.g, "C09A", self.caso,
                                    RankerSimbolico(regole))
        self.assertEqual(t["indicazioni"][0]["fatto_non_estratto"],
                         "frazione di eiezione")


class TestLeDueProiezioniNonDivergono(unittest.TestCase):
    """Il grafo e lo stato compatto devono dire gli stessi fatti.

    Il sistema legge le uscite delle pipeline in due forme: lo **stato
    compatto** (dizionari) che usano il filtro dello step 8 e il ranker dello
    step 9, e il **grafo** che usa la traccia. La divisione e' voluta e
    misurata — un'interrogazione SPARQL costa 12,4 ms contro 0,073 µs di una
    lettura da dizionario, e le 5 863 valutazioni dello step 8 diventerebbero
    73 secondi di sole interrogazioni — ma apre un rischio: due proiezioni
    della stessa sorgente che si allontanano in silenzio.

    Questo test e' la guardia. Se si rompe, una delle due proiezioni ha
    cominciato a vedere fatti che l'altra non vede, e la traccia mostrerebbe la
    provenienza di una raccomandazione decisa su altro.
    """

    def test_i_codici_del_grafo_sono_quelli_dello_stato_compatto(self):
        condizioni = [condizione("scompenso", "I50.9", 0, 9),
                      condizione("ipertensione", "I10", 40, 52),
                      condizione("angina", "I20", 80, 86,
                                 stato=StatoConoscenza.NEGATO),
                      condizione("diabete", "E11", 100, 107,
                                 soggetto=Soggetto.FAMILIARE),
                      condizione("dolore", None, 120, 126)]
        stato = stato_paziente(condizioni)

        # La proiezione compatta: la regola dello step 8 — solo affermate e
        # del paziente, solo codificate.
        compatta = {c.codice for c in stato.condizioni
                    if c.codice and c.stato.value == "affermato"
                    and c.soggetto.value == "paziente"}

        # La proiezione a grafo: gli stessi filtri applicati al sostegno.
        g = grafo_del_paziente({"A": stato}, 0, {}, {})
        dal_grafo = set()
        for codice in {c.codice for c in condizioni if c.codice}:
            for s in sostegno_del_concetto(g, codice):
                if s["stato"] == "affermato" and s["soggetto"] == "paziente":
                    dal_grafo.add(codice)

        self.assertEqual(compatta, dal_grafo)
        self.assertEqual(compatta, {"I50.9", "I10"})

    def test_il_grafo_conserva_anche_cio_che_lo_stato_scarta(self):
        """Conservare, non cancellare: il vincolo del progetto.

        La condizione negata non e' un fatto del paziente e il filtro non deve
        vederla, ma deve restare **nel grafo**, marcata. E' il modo in cui si
        puo' controllare che sia stata scartata per la ragione giusta.
        """
        g = grafo_del_paziente({"A": stato_paziente([
            condizione("angina", "I20", 0, 6, stato=StatoConoscenza.NEGATO)])},
            0, {}, {})
        sostegno = sostegno_del_concetto(g, "I20")
        self.assertEqual(len(sostegno), 1)
        self.assertEqual(sostegno[0]["stato"], "negato")


if __name__ == "__main__":
    unittest.main()
