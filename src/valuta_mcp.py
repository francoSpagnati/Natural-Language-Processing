"""Step 10bis - La valutazione del server MCP: dieci domande scritte prima.

Le quattro corse dello step 10 hanno trovato tre difetti, ma quattro corse non
sono una misura. Qui le domande sono **scritte prima di eseguirle**, ciascuna
con l'esito atteso, e il modello locale le affronta una per una. Si conta:

1. **strumento giusto** — il primo strumento chiamato e' quello atteso?
2. **testo intatto** — se lo strumento riceve un'anamnesi, e' un pezzo del testo
   dell'utente o una riscrittura? (il difetto della corsa 3 dello step 10)
3. **risposta arrivata** — il modello chiude entro i giri previsti?

Il modello e' `qwen3.5:4b` via ollama: costa zero, e la valutazione della skill
`mcp-builder` la prevede con l'API Anthropic, che qui non si usa.

Le anamnesi sono sintetiche e passano il controllo di privacy del progetto: in
un file versionato non entra testo dei referti.

## Uso

    python3 src/valuta_mcp.py                 # tutte e dieci, ~1 h di CPU
    python3 src/valuta_mcp.py --solo 1 4 10   # un sottoinsieme
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE / "src"))

from mcp_client_locale import conversa, testo_fedele  # noqa: E402


@dataclass(frozen=True)
class Domanda:
    numero: int
    testo: str
    strumento_atteso: str | None     # None = non deve chiamare nessuno strumento
    anamnesi_attesa: bool            # lo strumento riceve un testo clinico?
    nota: str


# Le dieci domande, decise prima della prima esecuzione. Coprono i cinque
# strumenti, i due stili di scrittura (prosa e telegrafico) che allo step 10
# hanno dato esiti diversi, un caso di sicurezza, e una domanda fuori ambito.
DOMANDE: tuple[Domanda, ...] = (
    Domanda(1, "Segue cura per ipertensione arteriosa dal 2004. Scompenso cardiaco. "
               "In terapia: Furosemide 25 mg; Ramipril 5 mg. Che cosa aggiungeresti "
               "alla dimissione, e perche'?",
            "cardio_proponi_terapia", True, "prosa completa, il caso favorevole"),
    Domanda(2, "Scompenso, iperteso, furosemide + ramipril. Che aggiungere?",
            "cardio_proponi_terapia", True, "telegrafico, il caso della corsa 2"),
    Domanda(3, "Nel testo «Scompenso cardiaco. Segue cura per ipertensione arteriosa "
               "dal 2004.» da dove viene il codice I50.9? Quali parole lo sostengono?",
            "cardio_sostegno_del_concetto", True, "la domanda dello step 9ter"),
    Domanda(4, "Paziente con questa anamnesi: «Scompenso cardiaco. Allergie e "
               "intolleranze: Principi attivi (acido acetilsalicilico)». Posso "
               "prescrivere acido acetilsalicilico, codice B01AC06?",
            "cardio_verifica_sicurezza", True, "deve uscire vietato"),
    Domanda(5, "Che cos'e' il codice ATC C03DA?",
            "cardio_cerca_codice", False, "ricerca per codice"),
    Domanda(6, "Qual e' il codice ATC dei sartani?",
            "cardio_cerca_codice", False, "ricerca per nome"),
    Domanda(7, "Su quanti ricoveri e' stato misurato questo sistema, e quanto e' "
               "affidabile il suo ranker migliore?",
            "cardio_statistiche_corpus", False, "gli aggregati"),
    Domanda(8, "Anamnesi: «Blocco atrioventricolare di secondo grado. Segue cura per "
               "ipertensione arteriosa dal 2010.» Posso dare un betabloccante, C07AB?",
            "cardio_verifica_sicurezza", True, "deve uscire da_verificare, non vietato"),
    Domanda(9, "Anamnesi: «Fibrillazione atriale permanente, mai cardiovertita. "
               "Allergie e intolleranze: Principi attivi (acido acetilsalicilico)». "
               "Terapia: Bisoprololo 2,5 mg. Che cosa aggiungeresti?",
            "cardio_proponi_terapia", True, "proposta con allergia: serve l'avvertimento"),
    Domanda(10, "Che tempo fa oggi a Milano?",
            None, False, "fuori ambito: nessuno strumento va chiamato"),
)


def giudica(domanda: Domanda, esito: dict) -> dict:
    chiamate = esito["chiamate"]
    primo = chiamate[0]["strumento"] if chiamate else None
    strumento_giusto = (primo == domanda.strumento_atteso
                        if domanda.strumento_atteso else not chiamate)

    fedelta = [c.get("testo_fedele") for c in chiamate
               if c.get("testo_fedele") is not None]
    if not domanda.anamnesi_attesa:
        testo_intatto = None
    elif not fedelta:
        testo_intatto = False        # doveva passare un testo e non l'ha fatto
    else:
        testo_intatto = all(fedelta)

    risposta_arrivata = not esito["risposta"].startswith("(nessuna risposta")
    return {
        "numero": domanda.numero,
        "strumento_atteso": domanda.strumento_atteso,
        "primo_strumento": primo,
        "strumento_giusto": strumento_giusto,
        "testo_intatto": testo_intatto,
        "risposta_arrivata": risposta_arrivata,
        "giri": esito["giri"],
        "chiamate": len(chiamate),
        "secondi": round(esito.get("secondi", 0.0), 1),
        "nota": domanda.nota,
    }


def stampa(righe: list[dict]) -> None:
    def segno(v):
        return "-" if v is None else ("si" if v else "NO")

    print(f"\n{'n':>2}  {'strumento atteso':30}{'giusto':>7}{'intatto':>8}"
          f"{'risposta':>9}{'giri':>5}{'s':>6}  nota")
    for r in righe:
        print(f"{r['numero']:>2}  {str(r['strumento_atteso']):30}"
              f"{segno(r['strumento_giusto']):>7}{segno(r['testo_intatto']):>8}"
              f"{segno(r['risposta_arrivata']):>9}{r['giri']:>5}{r['secondi']:>6.0f}"
              f"  {r['nota']}")
    n = len(righe)
    giusti = sum(1 for r in righe if r["strumento_giusto"])
    con_testo = [r for r in righe if r["testo_intatto"] is not None]
    intatti = sum(1 for r in con_testo if r["testo_intatto"])
    arrivate = sum(1 for r in righe if r["risposta_arrivata"])
    print(f"\nstrumento giusto  {giusti}/{n}")
    print(f"testo intatto     {intatti}/{len(con_testo)}  (solo dove un testo va passato)")
    print(f"risposta arrivata {arrivate}/{n}")


def main() -> None:
    argomenti = argparse.ArgumentParser(description="Valuta il server MCP con dieci domande.")
    argomenti.add_argument("--solo", type=int, nargs="*", default=None)
    argomenti.add_argument("--modello", default="qwen3.5:4b")
    argomenti.add_argument("--uscita", type=Path,
                           default=RADICE / "data" / "processed" / "valutazione_mcp.json")
    opzioni = argomenti.parse_args()

    scelte = [d for d in DOMANDE if not opzioni.solo or d.numero in opzioni.solo]
    righe = []
    for d in scelte:
        print(f"\n=== domanda {d.numero}: {d.nota}")
        esito = asyncio.run(conversa(d.testo, opzioni.modello, verboso=True))
        riga = giudica(d, esito)
        riga["risposta"] = esito["risposta"][:400]
        righe.append(riga)

    stampa(righe)
    opzioni.uscita.parent.mkdir(parents=True, exist_ok=True)
    opzioni.uscita.write_text(json.dumps({
        "modello": opzioni.modello,
        "domande": [d.__dict__ for d in scelte],
        "esiti": righe,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nDettaglio in {opzioni.uscita}")


if __name__ == "__main__":
    main()
