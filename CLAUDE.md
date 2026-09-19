# CLAUDE.md

Ce dépôt cible une application auto-hébergée de budget personnel.

## Priorités

- ne pas exposer de données bancaires confidentielles dans le dépôt ;
- garder `README.md`, `AGENTS.md`, `.copilot/` et le code cohérents ;
- préserver l'atomicite et l'idempotence de la migration initiale ;
- garder SQLite comme source de verite persistante apres la migration.
- garder les releves comme source des soldes et les series recurrentes comme source du budget.

## Vérification rapide

```bash
cd backend && .venv/bin/python -m ruff check app tests
cd backend && .venv/bin/python -m pytest
cd frontend && npm run build && npm run lint
./scripts/demo-local.sh start
```

## Référence

- `AGENTS.md` : conventions métier et architecture
- `MULTI_USER.md` : conception multi-utilisateur et invariants de partage
- `.copilot/instructions.md` : instructions Copilot
- `.copilot/skills/local-demo/SKILL.md` : démonstration locale pour la validation développeur
- `README.md` : usage et démarrage
