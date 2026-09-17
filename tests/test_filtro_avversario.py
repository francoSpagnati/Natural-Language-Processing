"""Il filtro di sicurezza contro casi scritti apposta per ingannarlo.

Lo step 8 misura la **precisione** del filtro sulle 5 863 prescrizioni reali
(quante volte blocca a vuoto) ma non il suo **richiamo**: quante
controindicazioni vere lascia passare. Una verita' di riferimento per questo
non esiste, e il vincolo dello step 8 vieta di ricavarla dal dataset. Quel che
si puo' fare e' scrivere casi avversari — la stessa allergia in cinque grafie,
la condizione negata, quella del familiare, il codice a un livello diverso — e
contare quanti il filtro coglie **attraverso l'estrazione deterministica**,
cioe' come lo incontra un utente della demo o del server MCP.

I casi che il filtro manca restano qui come `expectedFailure`, con la causa:
sono la misura del richiamo, non un difetto da nascondere. Il conteggio e'
nel doc 8, sez. 10.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE / "src"))

from demo import estrai_deterministico, paziente_da_testo  # noqa: E402
from filtro import Esito, StatoPerFiltro, valuta  # noqa: E402


def verdetto(anamnesi: str, atc: str, terapia: str = "") -> Esito:
    """Testo → pipeline A → filtro, per un farmaco candidato."""
    stato = estrai_deterministico(paziente_da_testo(anamnesi, terapia))
    condizioni = [{"codice": c.codice, "testo": c.testo_grezzo, "agenti": ["A"]}
                  for c in stato.condizioni
                  if c.codice and c.stato.value == "affermato"
                  and c.soggetto.value == "paziente"]
    allergie = {a.codice_atc for a in stato.allergie if a.codice_atc}
    terapia_atc = {f.codice_atc for f in stato.farmaci
                   if f.codice_atc and f.momento.value == "ingresso"}
    return valuta(StatoPerFiltro(0, condizioni, allergie, terapia_atc), atc).esito


ISCHEMICA = "Cardiopatia ischemica cronica. "
ASA = "B01AC06"


class TestAllergiaNelleSueGrafie(unittest.TestCase):
    """La stessa allergia, scritta come la scrivono referti diversi."""

    def test_principio_attivo_per_esteso(self):
        self.assertIs(verdetto(ISCHEMICA + "Allergie e intolleranze: Principi attivi "
                               "(acido acetilsalicilico)", ASA), Esito.VIETATO)

    def test_nome_commerciale_del_registro_aifa(self):
        self.assertIs(verdetto(ISCHEMICA + "Allergie e intolleranze: Principi attivi "
                               "(Cardioaspirin)", ASA), Esito.VIETATO)

    def test_due_allergeni_nella_stessa_parentesi(self):
        self.assertIs(verdetto(ISCHEMICA + "Allergie e intolleranze: Principi attivi "
                               "(acido acetilsalicilico, penicillina)", ASA), Esito.VIETATO)

    def test_maiuscole_diverse(self):
        self.assertIs(verdetto(ISCHEMICA + "Allergie e intolleranze: Principi attivi "
                               "(ACIDO ACETILSALICILICO)", ASA), Esito.VIETATO)

    def test_la_stessa_sostanza_a_un_altro_codice_atc_e_da_verificare(self):
        """L'acido acetilsalicilico e' B01AC06 come antiaggregante e N02BA01
        come analgesico: la reattivita' crociata di classe non e' un divieto."""
        self.assertIs(verdetto(ISCHEMICA + "Allergie e intolleranze: Principi attivi "
                               "(acido acetilsalicilico)", "B01AC04"), Esito.DA_VERIFICARE)

    @unittest.expectedFailure
    def test_acronimo_ASA(self):
        """Fallisce: «ASA» non e' in nessuna fonte citabile (limite dello step 5).
        L'allergene resta registrato senza codice e il server lo dichiara
        come fatto mancante."""
        self.assertIs(verdetto(ISCHEMICA + "Allergie e intolleranze: Principi attivi "
                               "(ASA)", ASA), Esito.VIETATO)

    @unittest.expectedFailure
    def test_nome_commerciale_fuori_dal_vocabolario_chiuso(self):
        """Fallisce: «Aspirina» e' in AIFA ma non e' mai comparsa nei campi di
        terapia del corpus, e il vocabolario chiuso (brief sez. 3.1) e' lo scope.
        Per un filtro di sicurezza e' il limite piu' serio di questa scelta."""
        self.assertIs(verdetto(ISCHEMICA + "Allergie e intolleranze: Principi attivi "
                               "(aspirina)", ASA), Esito.VIETATO)

    @unittest.expectedFailure
    def test_allergia_scritta_in_prosa_fuori_dalla_sezione(self):
        """Fallisce: la regex delle allergie legge la sottosezione strutturata;
        «Allergia ad acido acetilsalicilico» in prosa diventa la condizione
        T78.4, non un allergene."""
        self.assertIs(verdetto(ISCHEMICA + "Allergia ad acido acetilsalicilico.", ASA),
                      Esito.VIETATO)


class TestCondizioniCheNonDevonoControindicare(unittest.TestCase):

    def test_condizione_negata(self):
        self.assertIs(verdetto("Non riferisce asma. Ipertensione arteriosa.", "C07AB07"),
                      Esito.AMMESSO)

    def test_condizione_di_un_familiare(self):
        self.assertIs(verdetto("Madre con asma bronchiale. Ipertensione arteriosa.",
                               "C07AB07"), Esito.AMMESSO)

    def test_sezione_allergie_non_note(self):
        self.assertIs(verdetto(ISCHEMICA + "Allergie e intolleranze: non note", ASA),
                      Esito.AMMESSO)


class TestControindicazioniPerCondizione(unittest.TestCase):

    @unittest.expectedFailure
    def test_asma_e_betabloccante(self):
        """Fallisce: «asma bronchiale» non e' nel vocabolario chiuso delle
        condizioni, quindi J45 non viene mai estratto e la regola C07→J45 non
        puo' scattare. La regola c'e'; manca il fatto."""
        self.assertIs(verdetto("Asma bronchiale. Ipertensione arteriosa.", "C07AB07"),
                      Esito.DA_VERIFICARE)

    def test_scompenso_e_verapamil_e_declassato_perche_lo_vede_solo_il_gazetteer(self):
        """La regola dice VIETATO, ma per lo step 8 il solo gazetteer non basta
        a vietare (precisione 73%): con il motore deterministico ogni divieto
        da condizione scende a «da verificare». Solo l'allergia vieta."""
        self.assertIs(verdetto("Scompenso cardiaco.", "C08DA01"), Esito.DA_VERIFICARE)

    def test_scompenso_e_fans_idem(self):
        self.assertIs(verdetto("Scompenso cardiaco.", "M01AE01"), Esito.DA_VERIFICARE)

    def test_blocco_av_e_betabloccante_e_declassato_non_vietato(self):
        """Il principio del fatto mancante: il pacemaker non e' estratto."""
        self.assertIs(verdetto("Blocco atrioventricolare di secondo grado.", "C07AB07"),
                      Esito.DA_VERIFICARE)

    def test_gotta_e_tiazidico(self):
        self.assertIs(verdetto("Gotta. Ipertensione arteriosa.", "C03AA03"),
                      Esito.DA_VERIFICARE)

    @unittest.expectedFailure
    def test_insufficienza_renale_con_stadio_in_prosa(self):
        """Fallisce: «stadio 4» non diventa N18.4; il gazetteer arriva a N18,
        e la regola della metformina richiede N18.4-5 per non vietare a chi ha
        un'insufficienza lieve."""
        self.assertIs(verdetto("Insufficienza renale cronica stadio 4.", "A10BA02"),
                      Esito.VIETATO)

    @unittest.expectedFailure
    def test_emorragia_cerebrale_pregressa(self):
        """Fallisce: «emorragia cerebrale» non e' nel vocabolario chiuso delle
        condizioni (mai comparsa in forma riconoscibile nel corpus)."""
        self.assertIs(verdetto("Pregressa emorragia cerebrale.", "B01AF01"),
                      Esito.DA_VERIFICARE)


class TestDuplicazione(unittest.TestCase):

    def test_stessa_classe_gia_in_terapia(self):
        self.assertIs(verdetto("Ipertensione arteriosa.", "C07AB07",
                               terapia="Bisoprololo 2,5 mg: 1 cp"), Esito.DA_VERIFICARE)

    def test_classe_diversa_ammessa(self):
        self.assertIs(verdetto("Ipertensione arteriosa.", "C09AA05",
                               terapia="Bisoprololo 2,5 mg: 1 cp"), Esito.AMMESSO)


if __name__ == "__main__":
    unittest.main()
