"""
Test della pipeline C (step 5): etichette silver e allineamento del NER.

Le parti che qui si verificano sono quelle dove un errore e' silenzioso e
distruttivo: un allineamento sbagliato fra intervalli di caratteri e sottotoken
non fa fallire nulla, addestra semplicemente il modello sulle etichette sbagliate
e si manifesta molto piu' tardi come "il NER non funziona".

Nessun test scarica un modello: l'allineamento e' provato su offset costruiti a
mano, che e' anche il modo per controllarne i casi limite.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from entity_linking import IndiceSimilarita, Proposta, trigrammi  # noqa: E402
from ner_train import IGNORA, allinea, menzioni_da_bio  # noqa: E402
from silver_labels import (  # noqa: E402
    ETICHETTA_CONDIZIONE,
    ETICHETTA_FARMACO,
    ETICHETTE_BIO,
    EntitaSilver,
    _senza_sovrapposizioni,
    dividi,
    segmenta,
)


class TestSchemaEtichette(unittest.TestCase):
    def test_bio_completo_e_ordinato(self):
        self.assertEqual(ETICHETTE_BIO[0], "O")
        for etichetta in (ETICHETTA_CONDIZIONE, ETICHETTA_FARMACO):
            self.assertIn(f"B-{etichetta}", ETICHETTE_BIO)
            self.assertIn(f"I-{etichetta}", ETICHETTE_BIO)

    def test_nessuna_etichetta_ripetuta(self):
        self.assertEqual(len(ETICHETTE_BIO), len(set(ETICHETTE_BIO)))


class TestSovrapposizioni(unittest.TestCase):
    """Lo schema BIO non sa rappresentare due entita' sovrapposte."""

    def test_vince_la_piu_lunga(self):
        entita = [
            EntitaSilver(0, 12, ETICHETTA_CONDIZIONE, "ipertensione"),
            EntitaSilver(0, 22, ETICHETTA_CONDIZIONE, "ipertensione arteriosa"),
        ]
        tenute = _senza_sovrapposizioni(entita)
        self.assertEqual(len(tenute), 1)
        self.assertEqual(tenute[0].fine, 22)

    def test_entita_disgiunte_sopravvivono_entrambe(self):
        entita = [
            EntitaSilver(0, 6, ETICHETTA_CONDIZIONE, "gotta"),
            EntitaSilver(10, 20, ETICHETTA_FARMACO, "bisoprololo"),
        ]
        self.assertEqual(len(_senza_sovrapposizioni(entita)), 2)

    def test_ordinate_per_posizione(self):
        entita = [
            EntitaSilver(30, 40, ETICHETTA_FARMACO, "b"),
            EntitaSilver(0, 10, ETICHETTA_CONDIZIONE, "a"),
        ]
        self.assertEqual([e.inizio for e in _senza_sovrapposizioni(entita)], [0, 30])


class TestSegmentazione(unittest.TestCase):
    def test_testo_breve_resta_intero(self):
        segmenti, perse = segmenta(1, "Paziente iperteso.", [], massimo=1000)
        self.assertEqual(len(segmenti), 1)
        self.assertEqual(perse, 0)

    def test_offset_delle_entita_diventano_relativi(self):
        testo = "Prima frase lunga. " * 60 + "Nota gotta cronica."
        posizione = testo.index("gotta")
        entita = [EntitaSilver(posizione, posizione + 5, ETICHETTA_CONDIZIONE, "gotta")]
        segmenti, perse = segmenta(1, testo, entita, massimo=200)
        self.assertEqual(perse, 0)
        trovate = [(s, e) for s in segmenti for e in s.entita]
        self.assertEqual(len(trovate), 1)
        segmento, elemento = trovate[0]
        # L'offset relativo deve ritagliare esattamente la stessa stringa.
        self.assertEqual(segmento.testo[elemento.inizio : elemento.fine], "gotta")

    def test_risalire_al_referto_e_sempre_possibile(self):
        testo = "Frase una. " * 80
        segmenti, _ = segmenta(7, testo, [], massimo=150)
        self.assertGreater(len(segmenti), 1)
        for segmento in segmenti:
            self.assertEqual(segmento.enc_oid, 7)
            self.assertEqual(
                testo[segmento.inizio_nel_referto : segmento.inizio_nel_referto + len(segmento.testo)],
                segmento.testo,
            )

    def test_nessun_testo_perso(self):
        testo = "Prima. Seconda. Terza. " * 40
        segmenti, _ = segmenta(1, testo, [], massimo=100)
        self.assertEqual("".join(s.testo for s in segmenti), testo)


class TestDivisione(unittest.TestCase):
    def test_partizioni_disgiunte_e_complete(self):
        identificativi = list(range(1000))
        partizioni = dividi(identificativi)
        unione = set().union(*partizioni.values())
        self.assertEqual(unione, set(identificativi))
        self.assertEqual(
            sum(len(p) for p in partizioni.values()), len(identificativi)
        )
        for nome_a, ids_a in partizioni.items():
            for nome_b, ids_b in partizioni.items():
                if nome_a != nome_b:
                    self.assertFalse(ids_a & ids_b)

    def test_riproducibile(self):
        self.assertEqual(dividi(list(range(200))), dividi(list(range(200))))

    def test_un_referto_non_finisce_in_due_partizioni(self):
        """La divisione e' per ricovero: e' cio' che evita la fuga di informazione
        fra frasi quasi identiche dello stesso referto."""
        partizioni = dividi(list(range(300)))
        conteggio = {}
        for nome, ids in partizioni.items():
            for identificativo in ids:
                conteggio[identificativo] = conteggio.get(identificativo, 0) + 1
        self.assertTrue(all(v == 1 for v in conteggio.values()))


class TestAllineamento(unittest.TestCase):
    """Intervalli di caratteri -> etichette per sottotoken.

    Gli offset sono costruiti a mano perche' e' l'unico modo di controllare i
    casi limite senza dipendere da un tokenizzatore scaricato.
    """

    def _indice(self, etichetta):
        return ETICHETTE_BIO.index(etichetta)

    def test_token_speciali_esclusi_dalla_perdita(self):
        offsets = [(0, 0), (0, 5), (0, 0)]
        etichette = allinea(offsets, [])
        self.assertEqual(etichette[0], IGNORA)
        self.assertEqual(etichette[-1], IGNORA)

    def test_primo_sottotoken_riceve_B_gli_altri_I(self):
        """"ipertensione" spezzata in tre sottotoken deve dare B, I, I."""
        offsets = [(0, 0), (0, 5), (5, 9), (9, 12), (0, 0)]
        entita = [{"inizio": 0, "fine": 12, "etichetta": ETICHETTA_CONDIZIONE}]
        etichette = allinea(offsets, entita)
        self.assertEqual(
            etichette[1:4],
            [
                self._indice(f"B-{ETICHETTA_CONDIZIONE}"),
                self._indice(f"I-{ETICHETTA_CONDIZIONE}"),
                self._indice(f"I-{ETICHETTA_CONDIZIONE}"),
            ],
        )

    def test_fuori_da_ogni_entita_e_O(self):
        offsets = [(0, 5), (6, 10)]
        entita = [{"inizio": 20, "fine": 25, "etichetta": ETICHETTA_FARMACO}]
        self.assertEqual(allinea(offsets, entita), [0, 0])

    def test_sovrapposizione_parziale_conta(self):
        """Un sottotoken che entra anche solo in parte nell'entita' va etichettato.

        Se contiene l'inizio dell'entita' e' il suo primo sottotoken, quindi `B-`
        anche se comincia prima: il tokenizzatore puo' fondere la fine della
        parola precedente con l'inizio della menzione.
        """
        offsets = [(0, 8)]
        entita = [{"inizio": 4, "fine": 12, "etichetta": ETICHETTA_CONDIZIONE}]
        self.assertEqual(allinea(offsets, entita), [self._indice(f"B-{ETICHETTA_CONDIZIONE}")])

    def test_sottotoken_interno_riceve_I(self):
        offsets = [(6, 10)]
        entita = [{"inizio": 4, "fine": 12, "etichetta": ETICHETTA_CONDIZIONE}]
        self.assertEqual(allinea(offsets, entita), [self._indice(f"I-{ETICHETTA_CONDIZIONE}")])


class TestRicostruzioneMenzioni(unittest.TestCase):
    def test_andata_e_ritorno(self):
        """Etichettare e poi ricostruire deve restituire l'intervallo di partenza."""
        offsets = [(0, 0), (0, 5), (5, 12), (13, 20), (0, 0)]
        entita = [{"inizio": 0, "fine": 12, "etichetta": ETICHETTA_CONDIZIONE}]
        indici = allinea(offsets, entita)
        etichette = [ETICHETTE_BIO[i] if i != IGNORA else "O" for i in indici]
        menzioni = menzioni_da_bio(etichette, offsets)
        self.assertEqual(len(menzioni), 1)
        self.assertEqual((menzioni[0].inizio, menzioni[0].fine), (0, 12))

    def test_due_entita_adiacenti_restano_separate(self):
        """E' la ragione per cui serve lo schema BIO invece di IO."""
        offsets = [(0, 5), (5, 10)]
        etichette = [f"B-{ETICHETTA_CONDIZIONE}", f"B-{ETICHETTA_CONDIZIONE}"]
        self.assertEqual(len(menzioni_da_bio(etichette, offsets)), 2)

    def test_I_orfana_non_apre_una_menzione(self):
        """Una sequenza malformata prodotta dal modello non deve inventare entita'."""
        offsets = [(0, 5), (5, 10)]
        etichette = ["O", f"I-{ETICHETTA_CONDIZIONE}"]
        self.assertEqual(menzioni_da_bio(etichette, offsets), [])

    def test_cambio_di_etichetta_chiude_la_menzione(self):
        offsets = [(0, 5), (5, 10)]
        etichette = [f"B-{ETICHETTA_CONDIZIONE}", f"I-{ETICHETTA_FARMACO}"]
        menzioni = menzioni_da_bio(etichette, offsets)
        self.assertEqual(len(menzioni), 1)
        self.assertEqual(menzioni[0].etichetta, ETICHETTA_CONDIZIONE)



class TestTrigrammi(unittest.TestCase):
    def test_bordi_marcati(self):
        """Gli spazi ai bordi fanno pesare inizio e fine della parola, dove in
        italiano sta l'informazione morfologica."""
        self.assertIn(" ab", trigrammi("abc"))
        self.assertIn("bc ", trigrammi("abc"))

    def test_stringa_piu_corta_del_trigramma(self):
        self.assertTrue(trigrammi("a"))


class TestIndiceSimilarita(unittest.TestCase):
    INDICE = {
        "ipertensione arteriosa essenziale": ["I10"],
        "insufficienza mitralica congenita": ["Q23.3"],
        "dolore precordiale": ["R07.2"],
        "fibrillazione atriale parossistica": ["I48.0"],
    }

    def setUp(self):
        self.indice = IndiceSimilarita(self.INDICE)

    def test_trova_il_termine_quasi_uguale(self):
        proposta = self.indice.migliore("ipertensione arteriosa essenziali", soglia=0.5)
        self.assertIsNotNone(proposta)
        self.assertEqual(proposta.termine, "ipertensione arteriosa essenziale")

    def test_sotto_soglia_non_propone(self):
        self.assertIsNone(self.indice.migliore("frattura del femore", soglia=0.5))

    def test_menzione_troppo_corta_esclusa(self):
        """Una sigla condivide trigrammi con qualunque cosa: confrontarla non
        porta informazione, porta solo falsi positivi."""
        self.assertIsNone(self.indice.migliore("FA"))

    def test_restituisce_un_punteggio(self):
        proposta = self.indice.migliore("dolore precordiali", soglia=0.4)
        self.assertIsInstance(proposta, Proposta)
        self.assertGreater(proposta.punteggio, 0.4)
        self.assertLessEqual(proposta.punteggio, 1.0)


@unittest.skipUnless(
    (
        Path(__file__).resolve().parent.parent / "data/interim/terminologia_icd10.json"
    ).exists(),
    "terminologia ICD-10 non generata",
)
class TestCollegatoreICD(unittest.TestCase):
    """Il punto piu' delicato dello step 5.

    La similarita' ortografica NON separa i collegamenti corretti da quelli
    sbagliati: misurata sul lessico reale, il punteggio piu' alto (0,60) e'
    l'errore "insufficienza mitralica moderata" -> "...congenita", mentre il
    collegamento corretto "precordialgie" -> "dolore precordiale" sta a 0,41.
    Per questo la similarita' propone e non risolve mai.
    """

    @classmethod
    def setUpClass(cls):
        from entity_linking import CollegatoreICD
        from risolutori import RisolutoreICD

        cls.collegatore = CollegatoreICD(RisolutoreICD())

    def test_la_similarita_non_produce_mai_un_codice(self):
        """Regressione sul caso pericoloso: un codice congenito attribuito a una
        valvulopatia acquisita alimenterebbe il filtro di sicurezza dello step 8."""
        esito = self.collegatore.collega("insufficienza mitralica moderata")
        self.assertIsNone(esito.codice)
        self.assertIn("proposta_similarita", esito.metodo)
        # I candidati restano comunque visibili per l'ispezione.
        self.assertTrue(esito.candidati)

    def test_la_corrispondenza_esatta_ha_la_precedenza(self):
        esito = self.collegatore.collega("ipertensione arteriosa")
        self.assertEqual(esito.codice, "I10")
        self.assertEqual(esito.metodo, "termine_esatto")

    def test_la_generalizzazione_precede_la_similarita(self):
        esito = self.collegatore.collega("fibrillazione atriale")
        self.assertEqual(esito.codice, "I48")
        self.assertNotIn("similarita", esito.metodo)

    def test_menzione_lontana_da_tutto_resta_nil(self):
        esito = self.collegatore.collega("qwertyuiop asdfghjkl")
        self.assertIsNone(esito.codice)
        self.assertEqual(esito.metodo, "non_risolto")


if __name__ == "__main__":
    unittest.main()
