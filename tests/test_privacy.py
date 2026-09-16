"""Il controllo di privacy deve guardare anche i file non ancora aggiunti.

E' la lezione di un difetto vero: `file_versionati` chiamava `git ls-files`, che
elenca l'indice. Un file nuovo non era letto, il controllo passava *per assenza*,
e una frase presente in un solo referto e' entrata nel repository al primo
commit. Un controllo di sicurezza che tace su cio' che non ha guardato stampa la
stessa riga di esito di uno che ha guardato tutto: e' il modo peggiore di
fallire, e questo test lo impedisce.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import privacy  # noqa: E402


def _git(cartella: Path, *argomenti: str) -> None:
    subprocess.run(["git", *argomenti], cwd=cartella, check=True,
                   capture_output=True, text=True)


class TestFileVersionati(unittest.TestCase):
    """Che cosa entra nell'elenco dei file da controllare."""

    def setUp(self) -> None:
        self._temporanea = tempfile.TemporaryDirectory()
        self.radice = Path(self._temporanea.name)
        _git(self.radice, "init", "-q")
        (self.radice / ".gitignore").write_text("ignorato.md\n", encoding="utf-8")
        (self.radice / "tracciato.md").write_text("gia' nell'indice\n", encoding="utf-8")
        _git(self.radice, "add", "tracciato.md", ".gitignore")

    def tearDown(self) -> None:
        self._temporanea.cleanup()

    def nomi(self) -> set[str]:
        return {p.name for p in privacy.file_versionati(self.radice)}

    def test_il_file_tracciato_viene_controllato(self) -> None:
        self.assertIn("tracciato.md", self.nomi())

    def test_il_file_nuovo_non_ancora_aggiunto_viene_controllato(self) -> None:
        """Il caso che il difetto lasciava passare."""
        (self.radice / "nuovo.md").write_text("mai aggiunto\n", encoding="utf-8")
        self.assertIn("nuovo.md", self.nomi())

    def test_il_file_ignorato_resta_fuori(self) -> None:
        """I dati clinici stanno in cartelle ignorate: allargare non deve
        significare mettersi a leggere il corpus come se fosse codice."""
        (self.radice / "ignorato.md").write_text("dato clinico\n", encoding="utf-8")
        self.assertNotIn("ignorato.md", self.nomi())

    def test_le_estensioni_non_testuali_restano_fuori(self) -> None:
        (self.radice / "immagine.png").write_bytes(b"\x89PNG")
        self.assertNotIn("immagine.png", self.nomi())


if __name__ == "__main__":
    unittest.main()
