# CLAUDE.md

Ce dépôt cible une application auto-hébergée de budget personnel.

## Priorités

- ne pas exposer de données bancaires confidentielles dans le dépôt ;
- garder `README.md`, `AGENTS.md`, `.copilot/` et le code cohérents ;
- préserver l'atomicite et l'idempotence de la migration initiale ;
- garder SQLite comme source de verite persistante apres la migration.

## Vérification rapide

```bash
cd backend && .venv/bin/python -m ruff check app tests
cd backend && .venv/bin/python -m pytest
cd frontend && npm run build && npm run lint
```

## Référence

- `AGENTS.md` : conventions métier et architecture
- `.copilot/instructions.md` : instructions Copilot
- `README.md` : usage et démarrage
