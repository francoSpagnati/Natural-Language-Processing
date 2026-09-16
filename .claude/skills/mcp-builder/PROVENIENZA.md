# Provenienza di questa skill

Non e' stata scritta in questo progetto. E' la skill ufficiale `mcp-builder`
di Anthropic, copiata senza modifiche.

| | |
|---|---|
| fonte | https://github.com/anthropics/skills/tree/main/skills/mcp-builder |
| commit | `34040c9c568585f6929bedeaad110ad08f079624` |
| licenza | Apache 2.0 — testo completo in `LICENSE.txt` |
| copiata il | 2026-09-16 |

Verificabile con:

    git clone --depth 1 https://github.com/anthropics/skills.git
    diff -r skills/skills/mcp-builder .claude/skills/mcp-builder

## Le uniche due modifiche al file originale

`SKILL.md` e' stato toccato in due punti, entrambi per rimandare a
`NOTA-PROGETTO.md`:

1. una frase in coda al campo `description` del frontmatter;
2. una citazione di tre righe subito sotto il titolo.

Il resto e' identico all'originale. `diff` mostrera' queste due modifiche piu'
i tre file nostri (`PROVENIENZA.md`, `NOTA-PROGETTO.md` e questo elenco).
