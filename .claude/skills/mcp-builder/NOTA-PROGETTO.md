# Dove questa skill non vale, in questo progetto

La skill e' ufficiale e generica. Tre sue raccomandazioni vanno ignorate qui,
e la ragione e' vincolante, non stilistica.

## 1. `scripts/evaluation.py` non va eseguito

Importa `from anthropic import Anthropic`: si paga a consumo e il piano Pro di
Carlo non copre l'accesso all'API. Per valutare il server MCP si usa la strada
che il progetto ha gia': `src/llm_backend.py`, con `BackendOllama` (gratis) o
`BackendOpenRouter`. Le domande di valutazione della Fase 4 restano utili: e'
solo l'esecutore che cambia.

## 2. Il linguaggio e' Python, non TypeScript

La skill consiglia TypeScript. Qui il server deve importare `src/traccia.py`,
`src/ranker.py` e `src/filtro.py`, che sono Python: riscriverli o parlarci
attraverso un sottoprocesso aggiungerebbe una copia da tenere allineata. Si usa
FastMCP — la skill lo documenta in `reference/python_mcp_server.md`.

## 3. Trasporto stdio, non HTTP

La skill preferisce HTTP streamable per i server remoti. Questo server gira
sulla macchina di Carlo e legge dati clinici che non escono dal disco: stdio e'
il trasporto che rende quella proprieta' vera per costruzione.

## Che cosa il server deve esporre, e perche'

Gli strumenti utili sono quelli che *leggono*. Il filtro di sicurezza dello step
8 e' simbolico per vincolo («mai LLM, mai dataset»): un modello non deve poter
decidere che cosa e' ammissibile, ne' scrivere nel grafo.

- `sostegno_del_concetto` (da `src/traccia.py`) — «da dove viene questo fatto»
  e' esattamente la domanda che un modello conversazionale deve poter fare.
- l'interrogazione dello stato di un paziente e la traccia di una proposta.
