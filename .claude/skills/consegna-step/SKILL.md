---
name: consegna-step
description: Chiudere uno step del progetto - test, aggiornamento della documentazione, commit e push. Usare quando si sta per fare git commit o git push in questo repository, quando si e' finito di scrivere codice o documentazione di uno step, o quando si aggiorna docs/00_architettura.md.
---

# Chiudere uno step

Il progetto avanza per step numerati, uno per documento in `docs/`. Ogni step si
chiude nello stesso modo.

## La sequenza

- [ ] 1. `python3 -m unittest discover -s tests -q` — tutti verdi, nessun test
      usa la rete.
- [ ] 2. il documento dello step in `docs/` esiste ed e' aggiornato con i
      **numeri misurati in questa sessione**, non ricordati
- [ ] 3. `docs/00_architettura.md` aggiornato: e' l'indice vivo del progetto,
      sia la sezione dello step sia la riga nella tabella finale
- [ ] 4. i notebook versionati non hanno output salvati
      (`sum(len(c.get('outputs',[])) for c in nb['cells'])` deve fare 0)
- [ ] 5. commit e push su `master`
- [ ] 6. **fermarsi e riferire a Carlo.** Il prossimo step non si comincia senza
      la sua conferma.

## Che cosa non deve mai entrare in un commit

`.gitignore` copre gia' `data/`, `reports/`, `*.log`, `.env.local`. Controllare
comunque il diff prima di spingere:

```bash
git diff <base>..HEAD | grep -inE "sk-or-|api[_-]?key *= *[\"']"
```

La chiave OpenRouter sta in `.env.local` (chmod 600) e va **ruotata a fine
progetto**, perche' e' comparsa in chiaro in una conversazione.

## Come si scrive un messaggio di commit qui

Italiano, senza lettere accentate (si scrive `e'`, `piu'`), titolo nella forma
`Step N: la cosa fatta, e la cosa che si e' imparata`. Corpo lungo, con sezioni
in maiuscolo, e **i numeri misurati dentro il messaggio**.

Il messaggio deve dire anche cio' che e' andato storto: gli errori miei corretti
in corso d'opera, e le affermazioni ritirate. La cronologia del progetto e' parte
di cio' che Carlo discutera' con il docente, quindi un commit che nasconde una
correzione gli toglie materiale.

Chiudere con:

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

## Vincoli permanenti che un commit non puo' violare

- **Solo dati grezzi.** La sorgente e' `data/raw/anamnesiterapie.txt`. Nessun
  file gia' passato per un LLM puo' diventare dataset canonico.
- **Nessuna mappatura inventata.** Nome commerciale → principio attivo → ATC, e
  condizione → ICD, vengono da knowledge base esterne **citate** (WHO ATC/DDD,
  AIFA, ICD-10 2019 Elenco Sistematico, openFDA, Wikidata). Una voce non coperta
  si segnala come mappatura manuale con la sua fonte; non si riempie in
  silenzio.
- **Si conserva tutto.** Le voci non risolte si marcano, non si cancellano:
  servono a vedere che cosa e' stato mancato.
- **Lo step 8 resta simbolico:** mai LLM, mai dataset.
