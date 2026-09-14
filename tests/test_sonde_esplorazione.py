"""
Test delle sonde di parsing dello step 0.

Ogni test riproduce un caso **realmente osservato** nel dataset e documentato in
`docs/00_esplorazione_dati.md`. Servono come rete di sicurezza: le sonde sono
esplorative e verranno sostituite dai parser definitivi nello step 3, ma finche'
sono la fonte dei vocabolari chiusi una regressione qui si propagherebbe a tutti
gli step successivi.

Le stringhe di test sono formati, non dati clinici: contengono nomi di farmaci
in commercio, non informazioni su pazienti.

Esecuzione:
    python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from explore_dataset import (  # noqa: E402
    nome_farmaco_plausibile,
    radice_nome_commerciale,
    sonda_allergie,
    sonda_eco_questionario,
    sonda_terapia_dimissione,
    sonda_terapia_ingresso,
)


class TestSondaTerapiaIngresso(unittest.TestCase):
    def test_formato_prevalente(self):
        testo = "Atorvastatina sa: 80 mg cp.riv. /die (ore 22) ; Congescor: 1,25 mg cp.riv. /die (ore 8) ;"
        nomi, scarti, livelli = sonda_terapia_ingresso(testo)

        self.assertEqual(nomi, ["Atorvastatina sa", "Congescor"])
        self.assertEqual(scarti, [])
        self.assertEqual(livelli["1_nome_posologia"], 2)

    def test_assenza_di_terapia_dichiarata(self):
        nomi, scarti, livelli = sonda_terapia_ingresso("Nessuna terapia domiciliare.")

        self.assertEqual(nomi, [])
        self.assertEqual(scarti, [])
        self.assertEqual(livelli["nessuna_terapia_dichiarata"], 1)

    def test_prescrizione_infusionale(self):
        """Secondo formato: il farmaco segue la dose invece di precederla.

        Il suffisso del produttore ("salf" = SALF S.p.A.) viene conservato,
        coerentemente con il resto del campo ingresso, dove i nomi arrivano
        sempre in questa forma ("Atorvastatina sa"). Toglierlo e' compito della
        normalizzazione dello step 2, non della sonda.
        """
        testo = "125 mg di Furosemide salf*5fl 250mg/25ml in 100 ml Fisiologica ;"
        nomi, _, livelli = sonda_terapia_ingresso(testo)

        self.assertEqual(nomi, ["Furosemide salf"])
        self.assertEqual(livelli["2_infusionale"], 1)

    def test_ossigenoterapia_esclusa(self):
        """Ossigeno e ventilazione non sono farmaci e non hanno codice ATC."""
        nomi, scarti, livelli = sonda_terapia_ingresso(
            "Ossigeno, Cannula nasale, continuo, Oss.=2 l/min ;"
        )

        self.assertEqual(nomi, [])
        self.assertEqual(scarti, [])
        self.assertEqual(livelli["escluso_non_farmacologico"], 1)

    def test_blocco_in_prosa_finisce_negli_scarti(self):
        """Alcuni clinici scrivono la terapia a mano: non va nel vocabolario."""
        testo = "cardirene 75 mg, ansimar 400 mg, paxabel 1 busta/die, lucen 20 mg ;"
        nomi, scarti, _ = sonda_terapia_ingresso(testo)

        self.assertEqual(nomi, [])
        self.assertEqual(len(scarti), 1)

    def test_nome_con_punti_e_cifre_accettato(self):
        """'Furosemide l.f.m.' e 'Natecal d3' sono nomi legittimi."""
        nomi, _, _ = sonda_terapia_ingresso("Furosemide l.f.m.: 25 mg cpr. /die ; Natecal d3: 1 cpr /die ;")

        self.assertEqual(nomi, ["Furosemide l.f.m.", "Natecal d3"])


class TestSondaTerapiaDimissione(unittest.TestCase):
    def test_livello_1_formato_pieno(self):
        testo = '"Furosemide (Lasix cpr. 25 mg): da assumere 50 mg (ore 8)"'
        voci, scarti, livelli = sonda_terapia_dimissione(testo)

        self.assertEqual(scarti, [])
        self.assertEqual(livelli["1_completo"], 1)
        self.assertEqual(voci[0]["principio"], "Furosemide")
        self.assertEqual(voci[0]["commerciale"], "Lasix cpr. 25 mg")

    def test_livello_2_cattura_il_sinonimo(self):
        """Il secondo inciso e' un sinonimo del principio, non il commerciale."""
        testo = '"Tiamazolo (metimazolo) (Tapazole cpr. divisibili 5 mg): da assumere 5 mg (ore 8)"'
        voci, _, livelli = sonda_terapia_dimissione(testo)

        self.assertEqual(livelli["2_con_sinonimo"], 1)
        self.assertEqual(voci[0]["principio"], "Tiamazolo")
        self.assertEqual(voci[0]["sinonimo"], "metimazolo")
        self.assertEqual(voci[0]["commerciale"], "Tapazole cpr. divisibili 5 mg")

    def test_livello_4_senza_posologia(self):
        testo = '"Denosumab (Prolia soluz. iniett. 60 mg)"'
        voci, _, livelli = sonda_terapia_dimissione(testo)

        self.assertEqual(livelli["4_senza_posologia"], 1)
        self.assertEqual(voci[0]["principio"], "Denosumab")

    def test_associazione_precostituita_resta_intera(self):
        """Spezzare 'Sacubitril/valsartan' perderebbe il suo codice ATC proprio."""
        testo = '"Sacubitril/valsartan (Entresto cp.riv. 24/26 mg): da assumere 24/26 mg (ore 8)"'
        voci, _, _ = sonda_terapia_dimissione(testo)

        self.assertEqual(voci[0]["principio"], "Sacubitril/valsartan")

    def test_posologia_incollata_al_nome_viene_separata(self):
        """Regressione: i due punti di '08:00' fingevano da separatore, e il
        vocabolario acquisiva voci come 'Bisoprololo 3.75 mg 1 cp alle ore 08'.

        La prima risposta fu **scartare** la voce intera. Costava un farmaco per
        salvare il vocabolario, e nel corpus costava 40 prescrizioni di
        dimissione. Il livello 6 la interpreta invece di scartarla: il nome resta
        pulito — che era l'intento della guardia — e la posologia va al suo posto.
        """
        testo = '"Bisoprololo 3.75 mg 1 cp alle ore 08:00"'
        voci, scarti, _ = sonda_terapia_dimissione(testo)

        self.assertEqual(len(voci), 1)
        self.assertEqual(voci[0]["principio"], "Bisoprololo")
        self.assertEqual(voci[0]["posologia"], "3.75 mg 1 cp alle ore 08:00")
        self.assertEqual(scarti, [])

    def test_la_forma_farmaceutica_non_resta_attaccata_al_nome(self):
        """'Spironolattone cps 25 mg': la forma va tolta, non il farmaco."""
        voci, scarti, _ = sonda_terapia_dimissione(
            '"Spironolattone cps 25 mg: da assumere 6,25 mg (ore 18)"')

        self.assertEqual(len(voci), 1)
        self.assertEqual(voci[0]["principio"], "Spironolattone")

    def test_il_commerciale_con_parentesi_annidata_viene_letto(self):
        """Un farmaco estero porta la provenienza fra parentesi dentro la
        descrizione della confezione, e `[^()]*` non puo' attraversarla."""
        voci, _, livelli = sonda_terapia_dimissione(
            '"Propiltiouracile (Propycil 50mg recordati ilac (estero) cpr.): '
            'da assumere 50 mg (ore 8)"')

        self.assertEqual(len(voci), 1)
        self.assertEqual(voci[0]["principio"], "Propiltiouracile")
        self.assertEqual(livelli["5_commerciale_annidato"], 1)

    def test_un_fluido_non_e_un_farmaco_prescritto(self):
        """'500 ml Fisiologica' comincia con una cifra: il livello 6 non lo
        accetta, ed e' corretto. Resta fra i non interpretati invece di entrare
        nel vocabolario come sostanza."""
        voci, scarti, _ = sonda_terapia_dimissione('"500 ml Fisiologica"')

        self.assertEqual(voci, [])
        self.assertEqual(len(scarti), 1)

    def test_segnaposto_non_entra_nel_vocabolario(self):
        """'Nessun principio attivo' e' un segnaposto dell'EHR, non un farmaco.

        Regressione: compariva 22 volte alla dimissione ed entrava nel
        vocabolario chiuso come se fosse una sostanza reale.
        """
        testo = '"Nessun principio attivo (Sideral oro 14mg 20bust grat.): da assumere 1 bust"'
        voci, _, _ = sonda_terapia_dimissione(testo)

        self.assertEqual(voci, [])

    def test_dispositivo_escluso(self):
        testo = '"Cicli notturni di CPAP (PEEP=8), con maschera oro-nasale"'
        voci, scarti, livelli = sonda_terapia_dimissione(testo)

        self.assertEqual(voci, [])
        self.assertEqual(scarti, [])
        self.assertEqual(livelli["escluso_non_farmacologico"], 1)

    def test_cicli_di_ventilazione_esclusi(self):
        """Regressione: il filtro copriva solo 'cicli notturni'.

        'Cicli di NIV con auto C-PAP' sfuggiva ed entrava nel vocabolario.
        """
        testo = '"Cicli di NIV con auto C-PAP" "Cicli di ventilazione notturna con maschera"'
        voci, scarti, livelli = sonda_terapia_dimissione(testo)

        self.assertEqual(voci, [])
        self.assertEqual(scarti, [])
        self.assertEqual(livelli["escluso_non_farmacologico"], 2)

    def test_principio_che_contiene_cicli_non_e_escluso(self):
        """La guardia non deve essere troppo avida: 'Doxiciclina' e' un farmaco."""
        testo = '"Doxiciclina (Bassado cpr. 100 mg): da assumere 100 mg (ore 8)"'
        voci, _, _ = sonda_terapia_dimissione(testo)

        self.assertEqual(voci[0]["principio"], "Doxiciclina")


class TestGuardiaNomeFarmaco(unittest.TestCase):
    def test_accetta_nomi_legittimi(self):
        for nome in ("Bisoprololo", "Furosemide l.f.m.", "Natecal d3", "Sacubitril/valsartan"):
            with self.subTest(nome=nome):
                self.assertTrue(nome_farmaco_plausibile(nome))

    def test_rifiuta_prosa_e_posologie(self):
        for nome in (
            "Bisoprololo 3.75 mg 1 cp alle ore 08",   # posologia incollata
            "Insulina Toujeo 8-12 UI la sera, come da schema",  # virgola: prosa
            "125 mg di Furosemide",                    # inizia con una cifra
        ):
            with self.subTest(nome=nome):
                self.assertFalse(nome_farmaco_plausibile(nome))

    def test_soglia_parole_parametrica(self):
        """Alla dimissione i nomi possono essere piu' lunghi che in ingresso.

        La soglia conta le parole separate da SPAZIO: le barre delle
        associazioni ("Macrogol 3350/sodio bicarbonato/...") non creano
        confini di parola. Serve quindi un nome realmente prolisso per
        distinguere le due soglie. Alzarla da 4 a 12 recupera 5 principi
        attivi legittimi e dimezza i frammenti scartati (106 -> 56),
        misurato sul dataset.
        """
        lungo = "Insulina lispro da dna ricombinante"

        self.assertFalse(nome_farmaco_plausibile(lungo))          # soglia ingresso
        self.assertTrue(nome_farmaco_plausibile(lungo, 12))       # soglia dimissione


class TestRadiceNomeCommerciale(unittest.TestCase):
    def test_taglia_forma_farmaceutica_e_dose(self):
        self.assertEqual(radice_nome_commerciale("Lasix cpr. 25 mg"), "lasix")
        self.assertEqual(radice_nome_commerciale("Congescor cp.riv. 1.25 mg"), "congescor")

    def test_conserva_le_cifre_che_fanno_parte_del_nome(self):
        self.assertEqual(radice_nome_commerciale("Cacit 1000"), "cacit 1000")


class TestSondaAllergie(unittest.TestCase):
    def test_tre_stati_distinti(self):
        """'Non sappiamo' e 'sappiamo che non ce ne sono' non vanno confusi."""
        self.assertEqual(sonda_allergie("Anamnesi Remota: nulla.")["stato"], "sezione_assente")
        self.assertEqual(
            sonda_allergie("Allergie e intolleranze: Allergie e intolleranze non note Anamnesi Remota: y")["stato"],
            "assenza_dichiarata",
        )
        self.assertEqual(
            sonda_allergie("Allergie e intolleranze: Allergie: Principi attivi (Xantolide) Anamnesi Remota: x")["stato"],
            "allergie_presenti",
        )

    def test_estrae_il_principio_attivo_allergenico(self):
        esito = sonda_allergie(
            "Allergie e intolleranze: Allergie: Principi attivi (Xantolide) Note (FANS) Anamnesi Remota: x"
        )

        self.assertEqual(esito["categorie"]["principi attivi"], ["Xantolide"])


class TestEcoQuestionario(unittest.TestCase):
    def test_riconosce_polarita(self):
        coppie = sonda_eco_questionario("Ipertensione arteriosa si. Obesita no.")

        self.assertIn(("ipertensione arteriosa", "si"), coppie)
        self.assertIn(("obesita", "no"), coppie)


if __name__ == "__main__":
    unittest.main()
