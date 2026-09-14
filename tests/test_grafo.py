"""Test del knowledge graph (step 7).

Il grafo non calcola numeri: costruisce la struttura su cui lo step 8 deciderà
che cosa è sicuro prescrivere. Un errore qui non produce una cifra sbagliata,
produce una decisione clinica sbagliata che sembra giustificata. Questi test
fissano le proprietà da cui quelle decisioni dipendono.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rdflib import Graph, Literal  # noqa: E402
from rdflib.namespace import SKOS  # noqa: E402

import grafo  # noqa: E402
from confronto import Menzione  # noqa: E402
from grafo import ASSERZIONE, ATC, CT, ICD, PIPELINE, PROV, RICOVERO  # noqa: E402


def menzione(sigla, inizio, fine, tipo="condizione", enc=1, codice=None,
             stato="affermato", soggetto="paziente", campo="Anamnesi",
             strutturata=False):
    return Menzione(enc_oid=enc, sigla=sigla, tipo=tipo, campo=campo,
                    inizio=inizio, fine=fine, testo="x", codice=codice,
                    stato=stato, soggetto=soggetto, strutturata=strutturata)


class TestAsserzioniEProvenienza(unittest.TestCase):
    """Il cuore dello step 7: chi dice cosa, e quante pipeline lo dicono."""

    def _costruisci(self, menzioni):
        g = Graph()
        grafo.aggiungi_ricoveri(g, {1: menzioni})
        return g

    def test_menzioni_sovrapposte_fanno_una_sola_asserzione(self):
        """Se A e B riconoscono la stessa porzione di testo, è **un** fatto
        clinico visto due volte, non due fatti clinici."""
        g = self._costruisci([menzione("A", 10, 20), menzione("B", 12, 25)])
        asserzioni = set(g.subjects(grafo.RDF.type, CT.AsserzioneClinica))
        self.assertEqual(len(asserzioni), 1)
        nodo = asserzioni.pop()
        self.assertEqual(g.value(nodo, CT.numeroPipeline), Literal(2))

    def test_menzioni_disgiunte_fanno_asserzioni_distinte(self):
        g = self._costruisci([menzione("A", 10, 20), menzione("B", 40, 50)])
        self.assertEqual(len(set(g.subjects(grafo.RDF.type, CT.AsserzioneClinica))), 2)

    def test_lo_stesso_punto_in_campi_diversi_non_si_fonde(self):
        """Gli offset ripartono da zero in ogni campo: senza questa separazione
        una condizione dell'anamnesi si fonderebbe con un farmaco della terapia."""
        g = self._costruisci([
            menzione("A", 10, 20, campo="Anamnesi"),
            menzione("B", 10, 20, campo="Terapia alla Dimissione"),
        ])
        self.assertEqual(len(set(g.subjects(grafo.RDF.type, CT.AsserzioneClinica))), 2)

    def test_ogni_menzione_e_attribuita_alla_sua_pipeline(self):
        """È la proprietà che rende possibile ogni interrogazione dello step 8."""
        g = self._costruisci([menzione("A", 10, 20), menzione("C", 12, 25)])
        attribuzioni = set(g.objects(None, PROV.wasAttributedTo))
        self.assertEqual(attribuzioni, {PIPELINE["A"], PIPELINE["C"]})

    def test_l_asserzione_deriva_dalle_sue_menzioni(self):
        g = self._costruisci([menzione("A", 10, 20), menzione("B", 12, 25)])
        nodo = next(iter(g.subjects(grafo.RDF.type, CT.AsserzioneClinica)))
        self.assertEqual(len(set(g.objects(nodo, PROV.wasDerivedFrom))), 2)

    def test_il_gruppo_ambiguo_e_segnalato(self):
        """Se una pipeline porta due menzioni allo stesso punto non si sa quale
        con quale: l'asserzione resta valida per dire *chi* ha visto, non per
        confrontare stato e codice."""
        g = self._costruisci([menzione("A", 10, 20), menzione("A", 15, 25),
                              menzione("B", 12, 30)])
        nodo = next(iter(g.subjects(grafo.RDF.type, CT.AsserzioneClinica)))
        self.assertEqual(g.value(nodo, CT.allineamentoAmbiguo), Literal(True))
        self.assertEqual(g.value(nodo, CT.numeroPipeline), Literal(2))

    def test_l_asserzione_e_legata_al_suo_ricovero(self):
        g = self._costruisci([menzione("A", 10, 20, enc=1)])
        nodo = next(iter(g.subjects(grafo.RDF.type, CT.AsserzioneClinica)))
        self.assertEqual(g.value(nodo, CT.riguarda), RICOVERO["1"])


class TestAgenteDelParser(unittest.TestCase):
    """I campi di terapia hanno UNA lettura, non tre.

    Le tre pipeline leggono i due campi strutturati con lo stesso parser
    deterministico. Se il grafo le attribuisse a tre agenti diversi,
    `ct:numeroPipeline` direbbe 3 dove c'e' una sola lettura ripetuta, e il
    filtro dello step 8 scambierebbe quella ridondanza per una conferma
    indipendente — cioe' si fiderebbe di piu' proprio dove non ha imparato nulla.
    """

    def _costruisci(self, menzioni):
        g = Graph()
        grafo.aggiungi_ricoveri(g, {1: menzioni})
        return g

    def test_tre_letture_dello_stesso_parser_fanno_una_sola_voce(self):
        g = self._costruisci([
            menzione("A", 0, 10, tipo="farmaco", campo="Terapia alla Dimissione",
                     strutturata=True),
            menzione("B", 0, 10, tipo="farmaco", campo="Terapia alla Dimissione",
                     strutturata=True),
            menzione("C", 0, 10, tipo="farmaco", campo="Terapia alla Dimissione",
                     strutturata=True),
        ])
        nodo = next(iter(g.subjects(grafo.RDF.type, CT.AsserzioneClinica)))
        self.assertEqual(g.value(nodo, CT.numeroPipeline), Literal(1))
        self.assertEqual(set(g.objects(None, PROV.wasAttributedTo)),
                         {PIPELINE[grafo.SIGLA_PARSER]})

    def test_tre_riconoscimenti_indipendenti_valgono_tre(self):
        """Il contrasto che rende il test precedente significativo."""
        g = self._costruisci([menzione("A", 0, 10), menzione("B", 2, 12),
                              menzione("C", 4, 14)])
        nodo = next(iter(g.subjects(grafo.RDF.type, CT.AsserzioneClinica)))
        self.assertEqual(g.value(nodo, CT.numeroPipeline), Literal(3))

    def test_il_parser_e_un_agente_dichiarato(self):
        g = Graph()
        grafo.aggiungi_pipeline(g)
        self.assertIn(PIPELINE[grafo.SIGLA_PARSER],
                      set(g.subjects(grafo.RDF.type, PROV.SoftwareAgent)))


class TestConservazioneDeiDati(unittest.TestCase):
    """Il vincolo del progetto: non si cancella nulla, si segna."""

    def test_una_menzione_irrisolta_resta_nel_grafo(self):
        """Buttarla nasconderebbe proprio i casi da esaminare."""
        g = Graph()
        grafo.aggiungi_ricoveri(g, {1: [menzione("B", 10, 20, codice=None)]})
        nodi = list(g.subjects(CT.irrisolta, Literal(True)))
        self.assertEqual(len(nodi), 1)
        self.assertIsNone(g.value(nodi[0], CT.risolveA))

    def test_il_testo_clinico_non_entra_nel_grafo(self):
        """Il grafo è un artefatto che può circolare; il testo dei referti no.
        Gli offset bastano a ritrovarlo a chi ha i dati grezzi."""
        g = Graph()
        m = Menzione(enc_oid=1, sigla="A", tipo="condizione", campo="Anamnesi",
                     inizio=10, fine=20, testo="STRINGA_CLINICA_RISERVATA",
                     codice="I48", stato="affermato", soggetto="paziente",
                     strutturata=False)
        grafo.aggiungi_ricoveri(g, {1: [m]})
        self.assertNotIn("STRINGA_CLINICA_RISERVATA", g.serialize(format="turtle"))

    def test_stato_e_soggetto_sopravvivono_sulla_menzione(self):
        """Una condizione negata e una del padre non devono diventare una
        condizione del paziente per il solo fatto di essere entrate nel grafo."""
        g = Graph()
        grafo.aggiungi_ricoveri(g, {1: [
            menzione("A", 10, 20, stato="negato", soggetto="familiare")]})
        nodo = next(iter(g.subjects(grafo.RDF.type, CT.Menzione)))
        self.assertEqual(g.value(nodo, CT.stato), Literal("negato"))
        self.assertEqual(g.value(nodo, CT.soggetto), Literal("familiare"))

    def test_il_codice_porta_con_se_chi_lo_ha_prodotto(self):
        """Lo step 6 ha mostrato che gli errori esclusivi del gazetteer arrivano
        già codificati: lo step 8 deve poter distinguere quella provenienza."""
        g = Graph()
        grafo.aggiungi_ricoveri(g, {1: [menzione("A", 10, 20, codice="I48")]})
        nodo = next(iter(g.subjects(grafo.RDF.type, CT.AsserzioneClinica)))
        self.assertEqual(g.value(nodo, CT.codiceDa), PIPELINE["A"])
        self.assertEqual(g.value(nodo, CT.concetto), ICD["I48"])

    def test_un_farmaco_risolve_su_atc_e_una_condizione_su_icd(self):
        g = Graph()
        grafo.aggiungi_ricoveri(g, {1: [
            menzione("A", 10, 20, tipo="farmaco", codice="B01AC06"),
            menzione("A", 40, 50, tipo="condizione", codice="I48"),
        ]})
        self.assertIn(ATC["B01AC06"], set(g.objects(None, CT.risolveA)))
        self.assertIn(ICD["I48"], set(g.objects(None, CT.risolveA)))


class TestTerminologie(unittest.TestCase):
    def setUp(self):
        self.g = Graph()
        radice = Path(__file__).resolve().parent.parent
        grafo.aggiungi_atc(self.g, radice / "data" / "external" / "aifa" / "atc.csv")

    def test_la_gerarchia_atc_risale_fino_al_livello_anatomico(self):
        """La metrica gerarchica dello step 11 misura la distanza fra codici:
        senza i livelli superiori non c'è nulla rispetto a cui misurarla."""
        catena = list(self.g.transitive_objects(ATC["B01AC06"], SKOS.broader))
        self.assertIn(ATC["B01AC"], catena)
        self.assertIn(ATC["B"], catena)

    def test_ogni_concetto_cita_la_sua_fonte(self):
        """Il vincolo di provenienza del progetto vale anche dentro il grafo."""
        senza_fonte = [c for c in self.g.subjects(grafo.RDF.type, SKOS.Concept)
                       if self.g.value(c, grafo.DCTERMS.source) is None]
        self.assertEqual(senza_fonte, [])

    def test_il_livello_anatomico_non_ha_un_padre(self):
        self.assertEqual(list(self.g.objects(ATC["B"], SKOS.broader)), [])


if __name__ == "__main__":
    unittest.main()
