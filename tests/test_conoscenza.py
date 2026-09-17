"""Il grafo di conoscenza: cio' che il motore usa e' cio' che il Turtle dichiara."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from rdflib import RDF, Graph

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE / "src"))

import conoscenza  # noqa: E402
import kb_build  # noqa: E402
from conoscenza import CT, Esito, Indicazione, Controindicazione  # noqa: E402


def _piatta(regole):
    return sorted(
        (r.atc, tuple(sorted(r.icd)), getattr(r, "classe_racc", None) or r.esito,
         r.motivo, r.fonte,
         tuple(sorted(getattr(r, "atc_richiesto", ()) or getattr(r, "revocata_da", ()))),
         r.fatto_non_estratto)
        for r in regole)


class TestAndataERitorno(unittest.TestCase):

    def test_scrittura_e_lettura_restituiscono_le_stesse_regole(self):
        with tempfile.TemporaryDirectory() as d:
            percorso = Path(d) / "kb.ttl"
            conoscenza.scrivi(kb_build.INDICAZIONI, kb_build.REGOLE_CONTROINDICAZIONE,
                              {}, {}, percorso)
            ind, con = conoscenza.carica(percorso)
        self.assertEqual(_piatta(ind), _piatta(kb_build.INDICAZIONI))
        self.assertEqual(_piatta(con), _piatta(kb_build.REGOLE_CONTROINDICAZIONE))

    def test_il_turtle_nel_repository_e_quello_che_il_motore_usa(self):
        """`kb/conoscenza.ttl` va rigenerato con `python3 src/kb_build.py`
        ogni volta che una regola cambia: il ranker e il filtro leggono da li'."""
        self.assertEqual(_piatta(conoscenza.INDICAZIONI), _piatta(kb_build.INDICAZIONI))
        self.assertEqual(_piatta(conoscenza.REGOLE_CONTROINDICAZIONE),
                         _piatta(kb_build.REGOLE_CONTROINDICAZIONE))

    def test_due_citazioni_diverse_sono_due_nodi_guideline(self):
        """Successo davvero: due fonti con gli stessi primi 80 caratteri
        finivano nello stesso nodo, e una sovrascriveva l'altra."""
        a = Indicazione("X01", ("A00",), "I", "m", "F" * 80 + " uno")
        b = Indicazione("X02", ("A00",), "I", "m", "F" * 80 + " due")
        with tempfile.TemporaryDirectory() as d:
            g = conoscenza.scrivi((a, b), (), {}, {}, Path(d) / "kb.ttl")
        self.assertEqual(len(set(g.subjects(RDF.type, CT.Guideline))), 2)


class TestContenuto(unittest.TestCase):

    def test_ogni_regola_ha_una_fonte_e_un_motivo(self):
        for r in kb_build.INDICAZIONI + kb_build.REGOLE_CONTROINDICAZIONE:
            with self.subTest(atc=r.atc, icd=r.icd):
                self.assertTrue(r.fonte.strip() and r.motivo.strip())

    def test_ogni_uri_e_unico(self):
        uri = [r.uri for r in kb_build.INDICAZIONI + kb_build.REGOLE_CONTROINDICAZIONE]
        self.assertEqual(len(uri), len(set(uri)))

    def test_il_turtle_e_interrogabile_in_sparql(self):
        g = Graph().parse(conoscenza.PERCORSO, format="turtle")
        righe = list(g.query("""
            PREFIX ct: <https://example.org/terapia-cardiaca/schema#>
            SELECT ?farmaco WHERE { ?farmaco ct:hasIndication ?c . ?c skos:notation "I50" }"""))
        self.assertGreaterEqual(len(righe), 4, "i quattro pilastri dello scompenso")


if __name__ == "__main__":
    unittest.main()
