"""Test del caricamento del dataset."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_loading import (  # noqa: E402
    TIPO_ANAMNESI,
    TIPO_TERAPIA_DIMISSIONE,
    TIPO_TERAPIA_INGRESSO,
    carica_dataset,
)


def referto(tipo: str, testo: str) -> dict:
    """Costruisce un referto minimo nella forma in cui compare nel file."""
    return {"tipo": tipo, "data": "01.01.2026 10:00", "reportOid": 1, "testo": testo}


def scrivi_dataset(record: list[dict]) -> Path:
    """Scrive un dataset temporaneo e ne restituisce il percorso."""
    file_temporaneo = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    json.dump(record, file_temporaneo, ensure_ascii=False)
    file_temporaneo.close()
    return Path(file_temporaneo.name)


class TestCaricamento(unittest.TestCase):
    def test_record_completo_senza_anomalie(self):
        percorso = scrivi_dataset([
            {
                "encOid": 1,
                "referti": [
                    referto(TIPO_ANAMNESI, "Paziente iperteso."),
                    referto(TIPO_TERAPIA_INGRESSO, "Lasix: 25 mg cpr. /die (ore 8) ;"),
                    referto(TIPO_TERAPIA_DIMISSIONE, '"Furosemide (Lasix cpr. 25 mg): da assumere 25 mg (ore 8)"'),
                ],
            }
        ])
        record, anomalie = carica_dataset(percorso)

        self.assertEqual(len(record), 1)
        self.assertEqual(anomalie, [])
        self.assertEqual(record[0].enc_oid, 1)
        self.assertEqual(record[0].testo_anamnesi, "Paziente iperteso.")
        self.assertTrue(record[0].ha_terapia_dimissione)

    def test_terapia_dimissione_assente_non_e_anomalia(self):
        """143 record su 1000 non hanno la dimissione: e' una caratteristica.

        Segnalarla come anomalia produrrebbe 143 falsi allarmi e nasconderebbe
        i difetti veri.
        """
        percorso = scrivi_dataset([
            {
                "encOid": 2,
                "referti": [
                    referto(TIPO_ANAMNESI, "Anamnesi."),
                    referto(TIPO_TERAPIA_INGRESSO, "Nessuna terapia domiciliare."),
                ],
            }
        ])
        record, anomalie = carica_dataset(percorso)

        self.assertEqual(anomalie, [])
        self.assertFalse(record[0].ha_terapia_dimissione)
        self.assertIsNone(record[0].testo_terapia_dimissione)

    def test_referto_obbligatorio_mancante_e_anomalia(self):
        percorso = scrivi_dataset([
            {"encOid": 3, "referti": [referto(TIPO_ANAMNESI, "Solo anamnesi.")]}
        ])
        _, anomalie = carica_dataset(percorso)

        problemi = [a.tipo_problema for a in anomalie]
        self.assertIn("referto_obbligatorio_mancante", problemi)

    def test_enc_oid_duplicato_scartato_una_sola_volta(self):
        referti = [referto(TIPO_ANAMNESI, "A"), referto(TIPO_TERAPIA_INGRESSO, "B")]
        percorso = scrivi_dataset([
            {"encOid": 4, "referti": referti},
            {"encOid": 4, "referti": referti},
        ])
        record, anomalie = carica_dataset(percorso)

        self.assertEqual(len(record), 1)
        self.assertEqual([a.tipo_problema for a in anomalie], ["encOid_duplicato"])

    def test_anomalie_accumulate_senza_eccezioni(self):
        """Il loader non deve fermarsi al primo record difettoso."""
        percorso = scrivi_dataset([
            {"encOid": 5, "referti": [referto(TIPO_ANAMNESI, ""), referto(TIPO_TERAPIA_INGRESSO, "x")]},
            {"encOid": 6, "referti": [referto(TIPO_ANAMNESI, "ok"), referto(TIPO_TERAPIA_INGRESSO, "y")]},
        ])
        record, anomalie = carica_dataset(percorso)

        self.assertEqual(len(record), 2)  # entrambi caricati nonostante il difetto
        self.assertIn("testo_vuoto", [a.tipo_problema for a in anomalie])

    def test_testo_di_tipo_inatteso_non_interrompe(self):
        """Difendersi da un `testo` non stringa: era il caso dei file derivati."""
        percorso = scrivi_dataset([
            {
                "encOid": 7,
                "referti": [
                    {"tipo": TIPO_ANAMNESI, "data": None, "reportOid": None, "testo": [1, 2]},
                    referto(TIPO_TERAPIA_INGRESSO, "x"),
                ],
            }
        ])
        record, anomalie = carica_dataset(percorso)

        self.assertEqual(record[0].testo_anamnesi, "")
        self.assertIn("testo_tipo_inatteso", [a.tipo_problema for a in anomalie])


if __name__ == "__main__":
    unittest.main()
