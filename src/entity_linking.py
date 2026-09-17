"""Step 5 - Collegamento delle menzioni alla knowledge base (pipeline C).

Dopo `RisolutoreICD`, un ultimo passaggio cerca il termine ICD piu' simile
per trigrammi di caratteri (Jaccard). Misurato sui referti, la similarita'
ortografica non separa il collegamento giusto da quello sbagliato, quindi
**propone e non risolve**: l'esito e' sempre AMBIGUO, con termine e punteggio
nel metodo. Le sigle (BPCO, FA) restano non collegate: nessuna fonte citabile
le scioglie. Tabella e verifiche: docs/05_pipeline_estrazione_C.md.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from risolutori import EsitoICD, RisolutoreICD, normalizza
from schema import StatoNormalizzazione

# Soglia bassa: l'esito e' una proposta, e quelle utili stanno in basso.
SOGLIA_SIMILARITA = 0.35
DIMENSIONE_NGRAMMA = 3

# Sotto questa lunghezza i trigrammi sono troppo pochi perche' la similarita'
# sia informativa: "FA" condivide trigrammi con qualunque cosa.
LUNGHEZZA_MINIMA = 6


def trigrammi(testo: str, dimensione: int = DIMENSIONE_NGRAMMA) -> set[str]:
    """Trigrammi di caratteri con i bordi marcati (spazi in testa e in coda)."""
    imbottito = f" {testo} "
    return {imbottito[i : i + dimensione] for i in range(len(imbottito) - dimensione + 1)}


@dataclass(frozen=True)
class Proposta:
    """Un termine della knowledge base proposto per una menzione."""

    termine: str
    codici: tuple[str, ...]
    punteggio: float


class IndiceSimilarita:
    """Il termine ICD piu' simile, con indice inverso sui trigrammi."""

    def __init__(self, indice_termini: dict[str, list[str]]) -> None:
        self.termini = {t: tuple(c) for t, c in indice_termini.items() if len(t) >= LUNGHEZZA_MINIMA}
        self.trigrammi_per_termine = {t: trigrammi(t) for t in self.termini}
        self.per_trigramma: dict[str, list[str]] = defaultdict(list)
        for termine, gruppo in self.trigrammi_per_termine.items():
            for trigramma in gruppo:
                self.per_trigramma[trigramma].append(termine)

    def migliore(self, menzione: str, soglia: float = SOGLIA_SIMILARITA) -> Proposta | None:
        """Il termine piu' simile sopra soglia, o None."""
        chiave = normalizza(menzione)
        if len(chiave) < LUNGHEZZA_MINIMA:
            return None
        gruppo = trigrammi(chiave)
        if not gruppo:
            return None

        condivisi: dict[str, int] = defaultdict(int)
        for trigramma in gruppo:
            for termine in self.per_trigramma.get(trigramma, ()):
                condivisi[termine] += 1

        migliore: Proposta | None = None
        for termine, comuni in condivisi.items():
            # Jaccard; il massimo raggiungibile scarta in anticipo i termini perdenti.
            unione = len(gruppo) + len(self.trigrammi_per_termine[termine]) - comuni
            punteggio = comuni / unione if unione else 0.0
            if punteggio >= soglia and (migliore is None or punteggio > migliore.punteggio):
                migliore = Proposta(termine, self.termini[termine], punteggio)
        return migliore


class CollegatoreICD:
    """`RisolutoreICD` piu' la similarita' come ultimo passaggio, mai prima di un metodo esatto."""

    def __init__(self, risolutore: RisolutoreICD, soglia: float = SOGLIA_SIMILARITA) -> None:
        self.risolutore = risolutore
        self.soglia = soglia
        self.indice = IndiceSimilarita(risolutore.indice)

    def collega(self, menzione: str) -> EsitoICD:
        esito = self.risolutore.risolvi(menzione)
        if esito.stato is not StatoNormalizzazione.NIL:
            return esito

        proposta = self.indice.migliore(menzione, self.soglia)
        if proposta is None:
            return esito

        # Sempre AMBIGUO con codice `None`: nessuno a valle puo' usarlo come certo.
        return EsitoICD(
            codice=None,
            stato=StatoNormalizzazione.AMBIGUO,
            concetto=proposta.termine,
            candidati=tuple(sorted(set(proposta.codici))),
            metodo=f"proposta_similarita:{proposta.punteggio:.2f}:{proposta.termine}",
        )
