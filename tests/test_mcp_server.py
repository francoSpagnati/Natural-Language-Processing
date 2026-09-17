"""Il server MCP dello step 10: sola lettura, e il corpus non passa di qui.

I test importanti non sono quelli sul contenuto delle risposte — quello lo
misurano gli step 8 e 9 — ma quelli sulle **due promesse strutturali** che
rendono accettabile mettere un modello linguistico davanti a questo sistema:

1. nessuno strumento scrive o decide;
2. nessuno strumento fa uscire testo clinico del corpus.

Un test sul primo punto si scrive facilmente. Il secondo e' il piu' importante,
perche' e' l'unica frontiera dove un errore non produce un numero sbagliato ma
un dato di paziente spedito a un modello remoto.

Nessun test qui parla con la rete o con ollama: gli strumenti sono funzioni
Python e si chiamano direttamente.
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE / "src"))

import mcp_server  # noqa: E402

# Testo sintetico.
ANAMNESI = ("Scompenso cardiaco con frazione di eiezione ridotta. Segue cura "
            "per ipertensione arteriosa dal 2004.")
TERAPIA = "Furosemide 25 mg; Ramipril 5 mg"


def strumenti():
    return asyncio.run(mcp_server.mcp.list_tools())


class TestLeDuePromesseStrutturali(unittest.TestCase):
    """Cio' che rende accettabile esporre questo sistema a un modello."""

    def test_ogni_strumento_e_dichiarato_di_sola_lettura(self) -> None:
        """`read_only_hint` e' la forma verificabile dal client della promessa.

        Il filtro dello step 8 e' simbolico per vincolo: un modello che potesse
        modificare regole, grafo o insieme candidato scavalcherebbe l'unico
        strato che stabilisce che cosa e' ammissibile.
        """
        for s in strumenti():
            with self.subTest(strumento=s.name):
                self.assertIsNotNone(s.annotations, f"{s.name} senza annotazioni")
                self.assertTrue(s.annotations.read_only_hint)
                self.assertFalse(s.annotations.destructive_hint)

    def test_nessuno_strumento_accetta_un_identificativo_di_ricovero(self) -> None:
        """Il corpus non e' indirizzabile, e la difesa e' nella firma.

        Se uno strumento accettasse `enc_oid` potrebbe restituire il testo di un
        referto vero, e un client remoto lo spedirebbe fuori dalla macchina.
        Gli strumenti lavorano solo sul testo che l'utente incolla.
        """
        vietati = {"enc_oid", "record", "referto", "paziente_id", "id_ricovero"}
        for s in strumenti():
            argomenti = set(s.input_schema.get("properties", {}))
            with self.subTest(strumento=s.name):
                self.assertEqual(argomenti & vietati, set())

    def test_le_statistiche_del_corpus_non_contengono_prosa_clinica(self) -> None:
        """L'unico strumento che guarda il corpus restituisce solo aggregati."""
        testo = json.dumps(mcp_server.statistiche_corpus(), ensure_ascii=False)
        self.assertIn("referti", testo)
        # Le chiavi di un referto estratto: se comparissero, starebbe uscendo
        # uno stato paziente invece di un numero.
        for chiave in ("testo_grezzo", "anamnesi", "testo_supporto", "menzioni"):
            self.assertNotIn(chiave, testo)


class TestGliStrumentiSonoRegistrati(unittest.TestCase):

    def test_i_cinque_strumenti_ci_sono_col_prefisso(self) -> None:
        nomi = {s.name for s in strumenti()}
        self.assertEqual(nomi, {
            "cardio_proponi_terapia", "cardio_sostegno_del_concetto",
            "cardio_verifica_sicurezza", "cardio_cerca_codice",
            "cardio_statistiche_corpus"})
        for nome in nomi:
            self.assertTrue(nome.startswith("cardio_"))

    def test_ogni_strumento_ha_una_descrizione_non_vuota(self) -> None:
        """E' cio' che il modello legge per decidere se chiamarlo."""
        for s in strumenti():
            with self.subTest(strumento=s.name):
                self.assertTrue((s.description or "").strip())
                self.assertGreater(len(s.description), 80)


class TestProponiTerapia(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.esito = mcp_server.proponi_terapia(ANAMNESI, TERAPIA, 5)

    def test_codifica_le_condizioni_del_testo(self) -> None:
        codici = {c["codice"] for c in self.esito["condizioni"]}
        self.assertIn("I50.9", codici)
        self.assertIn("I10", codici)

    def test_propone_classi_non_gia_in_terapia(self) -> None:
        proposte = {p["classe_atc"] for p in self.esito["proposte"]}
        self.assertTrue(proposte)
        # Il ramipril e' un C09AA: proporlo di nuovo sarebbe continuita', non
        # una raccomandazione.
        self.assertNotIn("C09AA", proposte)

    def test_una_proposta_da_linea_guida_porta_la_fonte(self) -> None:
        """Una raccomandazione senza fonte non e' contestabile da un medico."""
        con_classe = [p for p in self.esito["proposte"]
                      if p["classe_raccomandazione"]]
        self.assertTrue(con_classe, "nessuna proposta da indicazione")
        for p in con_classe:
            with self.subTest(classe=p["classe_atc"]):
                self.assertTrue(p["fonte"])
                self.assertTrue(p["motivo"])

    def test_il_tetto_sulle_proposte_e_applicato(self) -> None:
        self.assertLessEqual(len(self.esito["proposte"]), 5)
        self.assertLessEqual(len(mcp_server.proponi_terapia(
            ANAMNESI, TERAPIA, 999)["proposte"]), 15)

    def test_dichiara_il_tetto_di_dominio(self) -> None:
        """Un'assenza dalle proposte non e' una controindicazione, e va detto."""
        self.assertIn("40,4%", self.esito["avvertenza"])


class TestIlFondamentoDiOgniProposta(unittest.TestCase):
    """La difesa contro l'unica cosa che il server non controlla: la prosa.

    Misurato con `qwen3.5:4b` davanti a questo server: ricevendo proposte con
    `motivo: null`, il modello ha **riempito il vuoto** con una motivazione
    propria — un «profilo nefroprotettivo» inventato, e A02BC (inibitori della
    pompa protonica) presentato come «betabloccante selettivo». Il server non
    puo' impedirgli di scrivere, ma puo' dirgli in chiaro che quella proposta
    non ha una regola dietro.
    """

    def test_ogni_proposta_dichiara_il_proprio_fondamento(self) -> None:
        esito = mcp_server.proponi_terapia(ANAMNESI, TERAPIA, 6)
        for p in esito["proposte"]:
            with self.subTest(classe=p["classe_atc"]):
                self.assertIn(p["fondamento"], ("indicazione citata",
                                                "co-occorrenza misurata nel corpus"))
                # Le due meta' non si possono confondere: con una fonte c'e'
                # una linea guida, senza fonte c'e' un avvertimento esplicito.
                if p["fondamento"] == "indicazione citata":
                    self.assertTrue(p["fonte"])
                    self.assertNotIn("attenzione", p)
                else:
                    self.assertIsNone(p["fonte"])
                    self.assertIn("Nessuna linea guida", p["attenzione"])


class TestIlPrincipioDelFattoMancante(unittest.TestCase):
    """Una risposta la cui premessa e' fallita non si presenta come valida.

    E' la terza ricorrenza nel progetto dello stesso principio, e la prima alla
    frontiera MCP: se il testo non produce nessun fatto, le proposte sono il
    tasso di base del reparto e non hanno niente a che vedere con il paziente.
    Restituirle senza dirlo e' il modo piu' rapido per far scrivere a un modello
    una raccomandazione clinica basata su nulla.
    """

    def test_senza_condizioni_estratte_lo_dichiara(self) -> None:
        # «iperteso» non e' nel gazetteer, che riconosce le forme per esteso.
        esito = mcp_server.proponi_terapia("Paziente iperteso.", "", 3)
        self.assertEqual(esito["condizioni"], [])
        self.assertIn("fatti_mancanti", esito)
        self.assertTrue(any("NON sono specifiche" in n
                            for n in esito["fatti_mancanti"]))

    def test_una_terapia_col_separatore_sbagliato_lo_dichiara(self) -> None:
        """Il caso vero: il modello ha usato la virgola e nessuno lo ha avvisato."""
        esito = mcp_server.proponi_terapia(ANAMNESI, "Furosemide, Ramipril", 3)
        self.assertEqual(esito["farmaci_ingresso"], [])
        self.assertTrue(any("punto e virgola" in n
                            for n in esito["fatti_mancanti"]))

    def test_col_testo_giusto_non_ci_sono_fatti_mancanti(self) -> None:
        esito = mcp_server.proponi_terapia(ANAMNESI, TERAPIA, 3)
        self.assertNotIn("fatti_mancanti", esito)

    def test_la_descrizione_chiede_il_testo_alla_lettera(self) -> None:
        """Il difetto piu' grave misurato, e l'unica difesa possibile.

        Passando dalla prosa allo strumento, il modello locale ha riscritto
        l'anamnesi e la riscrittura ha cambiato un fatto clinico: «iperteso» e'
        diventato «Ipotensione». Il server riceve la parafrasi del modello, non
        il testo del clinico, e non ha modo di accorgersene — quindi gli offset
        di provenienza indicherebbero parole che nessuno ha scritto. L'unica
        difesa e' chiederlo nella descrizione, e dichiarare il limite.
        """
        descrizione = next(s.description for s in strumenti()
                           if s.name == "cardio_proponi_terapia")
        self.assertIn("carattere per carattere", descrizione)
        self.assertIn("provenienza", descrizione)
        # La prima formulazione («passa l'anamnesi ALLA LETTERA») e' stata
        # letta dal modello come un obbligo dell'utente: ha chiesto di
        # riscrivere il testo invece di chiamare lo strumento. La descrizione
        # deve dire CHI copia e DA DOVE.
        self.assertIn("dal messaggio dell'utente", descrizione)

    def test_la_descrizione_dello_strumento_documenta_il_separatore(self) -> None:
        """Il modello ha sbagliato formato perche' nessuno gliel'aveva detto."""
        descrizione = next(s.description for s in strumenti()
                           if s.name == "cardio_proponi_terapia")
        self.assertIn("punto e virgola", descrizione)


class TestSostegnoDelConcetto(unittest.TestCase):
    """La domanda dello step 9ter, esposta come strumento a se'."""

    def test_restituisce_offset_regola_e_agente(self) -> None:
        esito = mcp_server.sostegno_del_concetto(ANAMNESI, "I50.9", TERAPIA)
        self.assertTrue(esito["menzioni"])
        m = esito["menzioni"][0]
        for campo in ("agente", "campo", "inizio", "fine", "regola", "stato"):
            self.assertIn(campo, m)
        self.assertEqual(ANAMNESI[m["inizio"]:m["fine"]].lower(),
                         "scompenso cardiaco")

    def test_un_codice_non_estratto_lo_dice_invece_di_tacere(self) -> None:
        esito = mcp_server.sostegno_del_concetto(ANAMNESI, "E11", TERAPIA)
        self.assertEqual(esito["menzioni"], [])
        self.assertIn("non lo ha estratto", esito["nota"])

    def test_un_tipo_sbagliato_e_un_errore_leggibile(self) -> None:
        """Un messaggio d'errore deve dire al modello come correggersi."""
        esito = mcp_server.sostegno_del_concetto(ANAMNESI, "I50.9", TERAPIA,
                                                 tipo="sbagliato")
        self.assertIn("errore", esito)
        self.assertIn("condizione", esito["errore"])


class TestVerificaSicurezza(unittest.TestCase):

    def test_un_farmaco_normale_e_ammesso(self) -> None:
        esito = mcp_server.verifica_sicurezza(ANAMNESI, "C03DA", TERAPIA)
        self.assertEqual(esito["esito"], "ammesso")

    def test_un_farmaco_a_cui_il_paziente_e_allergico_e_vietato(self) -> None:
        """La sezione allergie va scritta come il clinico la scrive.

        La prima stesura di questo test usava «Allergie: principi attivi: ...»
        e otteneva `ammesso`. Non era un difetto del filtro: la sonda cerca
        l'intestazione reale del reparto, e un test che inventa una sintassi
        misura l'invenzione invece del sistema.
        """
        anamnesi = (ANAMNESI + " Allergie e intolleranze: Principi attivi "
                    "(acido acetilsalicilico)")
        esito = mcp_server.verifica_sicurezza(anamnesi, "B01AC06", TERAPIA)
        self.assertIn("B01AC06", esito["allergie_viste"])
        self.assertEqual(esito["esito"], "vietato")
        self.assertTrue(esito["motivi"])

    def test_un_nome_al_posto_del_codice_NON_produce_un_verdetto(self) -> None:
        """Il falso permesso, misurato nella valutazione a dieci domande.

        Il modello ha chiesto la sicurezza di «Bisoprololo» per nome, e il
        filtro — che confronta codici — non ha trovato nessuna regola e ha
        risposto `ammesso`. Uno strato di sicurezza che dice si' a cio' che non
        capisce e' peggio di uno che non c'e'.
        """
        for nome in ("Bisoprololo", "aspirina", "", "XYZ99", "C99ZZ"):
            with self.subTest(ricevuto=nome):
                esito = mcp_server.verifica_sicurezza(ANAMNESI, nome, TERAPIA)
                self.assertIn("errore", esito)
                self.assertNotIn("esito", esito)
                self.assertIn("cardio_cerca_codice", esito["errore"])

    def test_un_codice_a_sette_caratteri_e_accettato(self) -> None:
        esito = mcp_server.verifica_sicurezza(ANAMNESI, "c07ab07", TERAPIA)
        self.assertEqual(esito["farmaco_atc"], "C07AB07")
        self.assertIn("esito", esito)

    def test_spiega_che_da_verificare_non_e_un_divieto(self) -> None:
        esito = mcp_server.verifica_sicurezza(ANAMNESI, "C03DA", TERAPIA)
        self.assertIn("non e' un divieto", esito["nota"])


class TestCercaCodice(unittest.TestCase):

    def test_il_codice_esatto_viene_prima(self) -> None:
        esito = mcp_server.cerca_codice("C03DA", "atc", 3)
        self.assertEqual(esito["risultati"][0]["codice"], "C03DA")

    def test_cerca_anche_per_nome(self) -> None:
        esito = mcp_server.cerca_codice("aldosterone", "atc", 5)
        self.assertTrue(any("C03DA" in r["codice"] for r in esito["risultati"]))

    def test_dichiara_la_knowledge_base(self) -> None:
        """Nessuna mappatura di questo progetto viene dalla memoria di un modello."""
        self.assertIn("AIFA", mcp_server.cerca_codice("C03DA")["fonte"])
        self.assertIn("ICD-10",
                      mcp_server.cerca_codice("I50", "icd")["fonte"])

    def test_accetta_i_nomi_veri_della_classificazione(self) -> None:
        """`ICD-10` e' come si chiama davvero, e rifiutarlo costa un giro.

        Misurato: il modello locale ha speso una chiamata su `sistema='ICD-10'`
        prima di indovinare `icd`. Un cavillo lessicale che costa dieci secondi
        di inferenza e' un difetto dell'interfaccia, non dell'utente.
        """
        for alias in ("ICD-10", "icd10", "ICD 10", "icd"):
            with self.subTest(alias=alias):
                esito = mcp_server.cerca_codice("I50", alias, 2)
                self.assertNotIn("errore", esito)
                self.assertTrue(esito["risultati"])

    def test_un_sistema_sconosciuto_e_un_errore_leggibile(self) -> None:
        esito = mcp_server.cerca_codice("C03DA", "snomed")
        self.assertIn("errore", esito)
        self.assertEqual(esito["sistema_ricevuto"], "snomed")


if __name__ == "__main__":
    unittest.main()
