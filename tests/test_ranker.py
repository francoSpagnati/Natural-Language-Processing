"""Test dei tre ranker (step 9)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from llm_backend import BackendFittizio  # noqa: E402
from ranker import (  # noqa: E402
    Caso,
    Raccomandazione,
    Indicazione,
    RankerContinuita,
    RankerFrequenza,
    RankerIbrido,
    RankerLLM,
    RankerSimbolico,
    allerta_di_classe,
    annota,
    applica_filtro,
    carica_casi,
    classe,
    descrivi_caso,
    dividi,
    insieme_candidato,
)
from valuta_ranker import misura, precisione_media  # noqa: E402


def caso(enc=1, condizioni=(), ingresso=(), dimissione=(), allergie=()):
    return Caso(enc, frozenset(condizioni), frozenset(ingresso),
                frozenset(allergie), frozenset(dimissione))


class TestUnitaDiRaccomandazione(unittest.TestCase):
    """La raccomandazione e' una classe ATC di livello 4, non un principio attivo."""

    def test_tronca_al_quarto_livello(self):
        self.assertEqual(classe("C07AB07"), "C07AB")
        self.assertEqual(classe("C07AB"), "C07AB")

    def test_codice_corto_resta_se_stesso(self):
        self.assertEqual(classe("C07"), "C07")


class TestRankerSimbolico(unittest.TestCase):

    def ordine(self, c, candidati):
        return [r.classe_atc for r in RankerSimbolico().ordina(c, candidati)]

    def test_i_pilastri_dello_scompenso_vengono_prima(self):
        c = caso(condizioni=["I50.9"])
        ordine = self.ordine(c, ["C09AA", "C07AB", "C03DA", "A10BK", "M04AA", "H03AA"])
        # Le quattro classi con una raccomandazione di classe I precedono quelle
        # senza alcuna indicazione citata.
        self.assertEqual(set(ordine[:4]), {"C09AA", "C07AB", "C03DA", "A10BK"})

    def test_classe_I_batte_classe_IIa(self):
        c = caso(condizioni=["I48"])
        ordine = self.ordine(c, ["B01AA", "B01AF"])
        # Anticoagulante diretto (classe I) prima dell'antagonista della
        # vitamina K (classe IIa), come dice la linea guida 2024.
        self.assertEqual(ordine[0], "B01AF")

    def test_gastroprotezione_innescata_dalla_terapia_non_dalla_diagnosi(self):
        """La regola che il campo `atc_richiesto` esiste per esprimere."""
        senza = caso(condizioni=["I10"])
        con = caso(condizioni=["I10"], ingresso=["B01AC"])
        self.assertEqual(self.ordine(senza, ["A02BC", "C09AA"])[0], "C09AA")
        punteggi = {r.classe_atc: r.punteggio
                    for r in RankerSimbolico().ordina(con, ["A02BC"])}
        self.assertGreater(punteggi["A02BC"], 0.0)

    def test_il_punteggio_e_il_massimo_non_la_somma(self):
        """Tre ragioni deboli non devono superare una forte.

        Sommare premierebbe le classi che compaiono in molte linee guida invece
        di quelle fortemente raccomandate per questo paziente.
        """
        regole = (
            Indicazione("X01", ("A00",), "IIa", "m", "f"),
            Indicazione("X01", ("A01",), "IIa", "m", "f"),
            Indicazione("X01", ("A02",), "IIa", "m", "f"),
            Indicazione("Y01", ("A00",), "I", "m", "f"),
        )
        r = RankerSimbolico(regole)
        c = caso(condizioni=["A00", "A01", "A02"])
        self.assertEqual([x.classe_atc for x in r.ordina(c, ["X01", "Y01"])][0], "Y01")

    def test_senza_indicazioni_il_punteggio_e_zero(self):
        c = caso(condizioni=["I50.9"])
        senza = [r for r in RankerSimbolico().ordina(c, ["M04AA"])]
        self.assertEqual(senza[0].punteggio, 0.0)
        self.assertEqual(senza[0].motivo, "")

    def test_ogni_indicazione_porta_la_sua_fonte(self):
        """Il vincolo di provenienza del progetto, applicato alle indicazioni."""
        from ranker import INDICAZIONI

        for ind in INDICAZIONI:
            self.assertTrue(ind.fonte.strip(), f"{ind.atc} senza fonte")
            self.assertIn(ind.classe_racc, ("I", "IIa", "IIb"))

    def test_la_raccomandazione_riporta_la_fonte_al_chiamante(self):
        c = caso(condizioni=["I48"])
        prima = RankerSimbolico().ordina(c, ["B01AF"])[0]
        self.assertIn("ESC 2024", prima.fonte)


class TestRankerIbrido(unittest.TestCase):

    def addestramento(self):
        """Venti ricoveri con `I50` -> `C03CA`, trenta con `Z99` -> `A02BC`."""
        casi = [caso(enc=i, condizioni=["I50.9"], dimissione=["C03CA"])
                for i in range(20)]
        casi += [caso(enc=20 + i, condizioni=["Z99"], dimissione=["A02BC"])
                 for i in range(30)]
        return casi

    def test_a_peso_zero_non_fa_peggio_della_frequenza(self):
        """La proprieta' che la correzione della PMI ha stabilito."""
        casi = self.addestramento()
        freq = RankerFrequenza()
        ibr = RankerIbrido(peso_guida=0.0)
        freq.addestra(casi)
        ibr.addestra(casi)
        c = caso(condizioni=["Q00"])           # condizione mai vista
        candidati = ["C03CA", "A02BC", "M04AA"]
        self.assertEqual([r.classe_atc for r in freq.ordina(c, candidati)],
                         [r.classe_atc for r in ibr.ordina(c, candidati)])

    def test_la_condizione_sposta_l_ordine(self):
        """Cio' che l'ibrido aggiunge alla frequenza: guarda il paziente."""
        casi = self.addestramento()
        ibr = RankerIbrido(peso_guida=0.0)
        freq = RankerFrequenza()
        ibr.addestra(casi)
        freq.addestra(casi)
        candidati = ["C03CA", "A02BC"]

        # La frequenza propone A02BC a chiunque, perche' e' la piu' aggiunta.
        self.assertEqual(
            [r.classe_atc for r in freq.ordina(caso(condizioni=["I50.9"]),
                                               candidati)][0], "A02BC")
        # L'ibrido, sullo stesso paziente, mette davanti il diuretico dell'ansa.
        self.assertEqual(
            [r.classe_atc for r in ibr.ordina(caso(condizioni=["I50.9"]),
                                              candidati)][0], "C03CA")
        self.assertEqual(
            [r.classe_atc for r in ibr.ordina(caso(condizioni=["Z99"]),
                                              candidati)][0], "A02BC")

    def test_la_terapia_in_atto_e_una_caratteristica(self):
        """La controparte appresa della gastroprotezione."""
        casi = [caso(enc=i, condizioni=["Z99"], ingresso=["B01AC"],
                     dimissione=["A02BC"]) for i in range(20)]
        casi += [caso(enc=100 + i, condizioni=["Z99"], dimissione=["M04AA"])
                 for i in range(20)]
        ibr = RankerIbrido(peso_guida=0.0)
        ibr.addestra(casi)
        con = [r.classe_atc for r in ibr.ordina(
            caso(condizioni=["Z99"], ingresso=["B01AC"]), ["A02BC", "M04AA"])]
        self.assertEqual(con[0], "A02BC")

    def test_ignora_evidenza_troppo_scarsa(self):
        """Due ricoveri non stabiliscono una co-occorrenza.

        La coppia abbondante resta, quella scarsa no: la soglia deve togliere
        l'evidenza debole, non spegnere il modello.
        """
        casi = [caso(enc=i, condizioni=["I50.9"], dimissione=["C03CA"])
                for i in range(2)]
        casi += [caso(enc=50 + i, condizioni=["Z99"], dimissione=["A02BC"])
                 for i in range(30)]
        ibr = RankerIbrido(peso_guida=0.0)
        ibr.addestra(casi)
        self.assertNotIn(("D:I50", "C03CA"), ibr.pmi)
        self.assertIn(("D:Z99", "A02BC"), ibr.pmi)

    def test_non_addestrato_non_esplode(self):
        ibr = RankerIbrido()
        ibr.addestra([])
        ordine = ibr.ordina(caso(condizioni=["I50.9"]), ["C03CA", "A02BC"])
        self.assertEqual(len(ordine), 2)


class TestLineeDiBase(unittest.TestCase):

    def test_la_continuita_mette_in_cima_la_terapia_in_atto(self):
        c = caso(ingresso=["C07AB"], dimissione=["C07AB", "A02BC"])
        ordine = [r.classe_atc for r in RankerContinuita().ordina(c, ["A02BC", "C07AB"])]
        self.assertEqual(ordine[0], "C07AB")

    def test_la_frequenza_impara_solo_le_aggiunte(self):
        """Non cio' che il paziente gia' prendeva: quello e' il compito 1."""
        casi = [caso(enc=i, ingresso=["C07AB"], dimissione=["C07AB", "A02BC"])
                for i in range(10)]
        freq = RankerFrequenza()
        freq.addestra(casi)
        self.assertEqual(freq.conteggio["A02BC"], 10)
        self.assertEqual(freq.conteggio["C07AB"], 0)


class TestRankerLLM(unittest.TestCase):
    """Il vincolo all'insieme candidato e' un requisito di sicurezza."""

    def ranker(self, ordine):
        return RankerLLM(BackendFittizio(lambda r: {"ordine": ordine}))

    def test_scarta_i_codici_fuori_dall_elenco_candidato(self):
        """L'errore osservato alla prima prova del modello locale."""
        r = self.ranker(["C09AA", "C07AB07", "B01AF"])
        ordine = [x.classe_atc for x in r.ordina(caso(), ["C09AA", "B01AF"])]
        self.assertEqual(ordine, ["C09AA", "B01AF"])
        self.assertEqual(r.scartati, 1)

    def test_normalizza_al_livello_di_classe(self):
        """Un principio attivo proposto al posto della classe non va perso."""
        r = self.ranker(["c09aa05"])
        ordine = [x.classe_atc for x in r.ordina(caso(), ["C09AA", "B01AF"])]
        self.assertEqual(ordine[0], "C09AA")
        self.assertEqual(r.scartati, 0)

    def test_i_duplicati_non_contano_due_volte(self):
        r = self.ranker(["C09AA", "C09AA", "B01AF"])
        ordine = [x.classe_atc for x in r.ordina(caso(), ["C09AA", "B01AF"])]
        self.assertEqual(ordine, ["C09AA", "B01AF"])

    def test_i_candidati_non_proposti_restano_in_coda(self):
        """Il ranker deve ordinare tutto: la valutazione conta il richiamo@k."""
        r = self.ranker(["B01AF"])
        ordine = [x.classe_atc for x in r.ordina(caso(), ["C09AA", "B01AF", "M04AA"])]
        self.assertEqual(ordine[0], "B01AF")
        self.assertEqual(set(ordine), {"C09AA", "B01AF", "M04AA"})

    def test_il_prompt_non_contiene_la_verita_di_riferimento(self):
        """Il test che impedisce la forma piu' silenziosa di imbroglio."""
        c = caso(condizioni=["I50.9"], ingresso=["C07AB"],
                 dimissione=["C03DA", "A10BK"])
        testo = descrivi_caso(c, ["C03DA", "A10BK", "M04AA"])
        # Le classi candidate compaiono tutte, per forza; cio' che non deve
        # comparire e' l'informazione di *quali* fossero quelle prescritte.
        self.assertNotIn("dimissione", testo.lower())
        self.assertIn("I50.9", testo)
        self.assertIn("C07AB", testo)

    def test_il_prompt_porta_i_nomi_accanto_ai_codici(self):
        testo = descrivi_caso(caso(condizioni=["I50.9"]), ["C03DA"],
                              nomi_icd={"I50.9": "Scompenso cardiaco"},
                              nomi_atc={"C03DA": "antagonisti dell'aldosterone"})
        self.assertIn("Scompenso cardiaco", testo)
        self.assertIn("antagonisti dell'aldosterone", testo)


class TestDivisioneEInsiemeCandidato(unittest.TestCase):

    def casi(self):
        return [caso(enc=i, dimissione=["C07AB"]) for i in range(200)]

    def test_la_divisione_e_riproducibile(self):
        a1, p1 = dividi(self.casi(), 0.3)
        a2, p2 = dividi(self.casi(), 0.3)
        self.assertEqual([c.enc_oid for c in p1], [c.enc_oid for c in p2])

    def test_gli_insiemi_sono_disgiunti_e_completi(self):
        a, p = dividi(self.casi(), 0.3)
        self.assertEqual(set(c.enc_oid for c in a) & set(c.enc_oid for c in p), set())
        self.assertEqual(len(a) + len(p), 200)

    def test_la_quota_e_approssimata_ma_plausibile(self):
        _, p = dividi(self.casi(), 0.3)
        self.assertGreater(len(p), 200 * 0.2)
        self.assertLess(len(p), 200 * 0.4)

    def test_l_insieme_candidato_esclude_le_classi_rare(self):
        casi = [caso(enc=i, dimissione=["C07AB"]) for i in range(10)]
        casi.append(caso(enc=99, dimissione=["C07AB", "X99XX"]))
        self.assertEqual(insieme_candidato(casi, soglia=3), ["C07AB"])

    def test_l_insieme_candidato_non_vede_i_casi_di_prova(self):
        """La proprieta' che impedisce la fuga di informazione.

        Costruirlo su tutti i casi farebbe entrare nell'elenco le classi
        presenti solo nella prova, e il richiamo misurato sarebbe gonfiato.
        """
        addestramento = [caso(enc=i, dimissione=["C07AB"]) for i in range(10)]
        prova = [caso(enc=100 + i, dimissione=["B01AF"]) for i in range(10)]
        self.assertNotIn("B01AF", insieme_candidato(addestramento))
        self.assertIn("B01AF", insieme_candidato(addestramento + prova))


class TestInnestoConIlFiltro(unittest.TestCase):
    """Lo step 8 decide che cosa e' ammissibile, lo step 9 ordina cio' che resta."""

    def test_toglie_la_classe_a_cui_il_paziente_e_allergico(self):
        c = caso(condizioni=["I48"], allergie=["B01AF"])
        self.assertNotIn("B01AF", applica_filtro(c, ["B01AF", "C07AB"]))

    def test_da_verificare_resta_candidato(self):
        """Un avvertimento non e' un'esclusione."""
        c = caso(condizioni=["J44"])
        self.assertIn("C07AB", applica_filtro(c, ["C07AB"]))

    def test_non_toglie_nulla_a_un_paziente_senza_controindicazioni(self):
        c = caso(condizioni=["I10"])
        candidati = ["C09AA", "C08CA", "C03AA"]
        self.assertEqual(applica_filtro(c, candidati), candidati)

    def test_l_allergia_a_una_sostanza_non_esclude_la_sua_classe(self):
        """Il caso reale che ha fermato una regola sbagliata."""
        c = caso(condizioni=["I25"], allergie=["B01AC06"])
        self.assertIn("B01AC", applica_filtro(c, ["B01AC", "C10AA"]))


class TestAvvertimentiDiClasse(unittest.TestCase):
    """Cio' che sostituisce l'esclusione: avvertire invece di negare."""

    def test_avverte_quando_la_classe_contiene_una_sostanza_vietata(self):
        c = caso(allergie=["B01AC06"])
        allerta = allerta_di_classe(c, "B01AC")
        self.assertIsNotNone(allerta)
        self.assertIn("B01AC06", allerta)

    def test_tace_sulle_classi_non_toccate(self):
        c = caso(allergie=["B01AC06"])
        self.assertIsNone(allerta_di_classe(c, "C10AA"))

    def test_l_annotazione_non_cambia_ordine_ne_punteggio(self):
        c = caso(allergie=["B01AC06"])
        prima = [Raccomandazione("B01AC", 2.0, "m"), Raccomandazione("C10AA", 1.0, "m")]
        dopo = annota(c, prima)
        self.assertEqual([r.classe_atc for r in dopo], ["B01AC", "C10AA"])
        self.assertEqual([r.punteggio for r in dopo], [2.0, 1.0])
        self.assertIn("ATTENZIONE", dopo[0].motivo)
        self.assertNotIn("ATTENZIONE", dopo[1].motivo)


class TestMetriche(unittest.TestCase):

    def test_richiamo_a_k(self):
        m = misura({1: ["A", "B", "C", "D"]}, {1: frozenset({"A", "D"})})
        self.assertAlmostEqual(m["richiamo@3"], 0.5)
        self.assertAlmostEqual(m["richiamo@5"], 1.0)

    def test_precisione_a_k_usa_k_come_denominatore(self):
        m = misura({1: ["A", "B", "C"]}, {1: frozenset({"A"})})
        self.assertAlmostEqual(m["precisione@3"], 1 / 3)

    def test_precisione_media_premia_le_posizioni_alte(self):
        alta = precisione_media(["A", "X", "Y"], frozenset({"A"}))
        bassa = precisione_media(["X", "Y", "A"], frozenset({"A"}))
        self.assertGreater(alta, bassa)
        self.assertAlmostEqual(alta, 1.0)
        self.assertAlmostEqual(bassa, 1 / 3)

    def test_i_casi_senza_bersaglio_sono_esclusi_dalla_media(self):
        """Un ricovero senza aggiunte non e' un ricovero su cui si e' sbagliato."""
        m = misura({1: ["A"], 2: ["A"]}, {1: frozenset({"A"}), 2: frozenset()})
        self.assertEqual(m["casi"], 1)
        self.assertAlmostEqual(m["richiamo@3"], 1.0)

    def test_nessun_bersaglio_affatto(self):
        self.assertEqual(misura({1: ["A"]}, {1: frozenset()}), {"casi": 0})


class TestCaricamentoDeiCasi(unittest.TestCase):

    def test_le_aggiunte_sono_la_differenza(self):
        c = caso(ingresso=["C07AB"], dimissione=["C07AB", "C03DA"])
        self.assertEqual(c.aggiunte, frozenset({"C03DA"}))

    def test_salta_i_file_di_servizio_e_i_record_senza_dimissione(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            cartella = Path(d)
            (cartella / "_corsa.json").write_text('{"record_totali": 1}')
            (cartella / "1.json").write_text(json.dumps({
                "enc_oid": 1, "condizioni": [], "allergie": [],
                "farmaci": [{"codice_atc": "C07AB07", "momento": "ingresso",
                             "stato": "affermato"}]}))
            (cartella / "2.json").write_text(json.dumps({
                "enc_oid": 2,
                "condizioni": [{"codice": "I50.9", "stato": "affermato",
                                "soggetto": "paziente"}],
                "allergie": [],
                "farmaci": [{"codice_atc": "C03DA01", "momento": "dimissione",
                             "stato": "affermato"}]}))
            casi = carica_casi(cartella)
        self.assertEqual([c.enc_oid for c in casi], [2])
        self.assertEqual(casi[0].dimissione, frozenset({"C03DA"}))

    def test_esclude_le_condizioni_negate_e_dei_familiari(self):
        """La regola dello step 8, che qui evita di raccomandare per il padre."""
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            cartella = Path(d)
            (cartella / "3.json").write_text(json.dumps({
                "enc_oid": 3, "allergie": [],
                "condizioni": [
                    {"codice": "I50.9", "stato": "affermato", "soggetto": "paziente"},
                    {"codice": "I48", "stato": "negato", "soggetto": "paziente"},
                    {"codice": "E11", "stato": "affermato", "soggetto": "familiare"}],
                "farmaci": [{"codice_atc": "C03DA01", "momento": "dimissione",
                             "stato": "affermato"}]}))
            casi = carica_casi(cartella)
        self.assertEqual(casi[0].condizioni, frozenset({"I50.9"}))


if __name__ == "__main__":
    unittest.main()
