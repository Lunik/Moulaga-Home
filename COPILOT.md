# Copilot Configuration

## Structure

Ce dépôt utilise `.copilot/` pour centraliser les instructions et les compétences reconnues par les clients Copilot :

- Copilot CLI
- GitHub Copilot
- Copilot in VS Code
- Claude Code

## Fichiers clés

| Fichier | Rôle |
|---|---|
| [`.copilot/instructions.md`](.copilot/instructions.md) | instructions globales |
| [`.copilot/skills/`](.copilot/skills/) | compétences du dépôt |
| [`.copilot/README.md`](.copilot/README.md) | guide des compétences |
| [AGENTS.md](AGENTS.md) | conventions et architecture |
| [CLAUDE.md](CLAUDE.md) | point d'entrée pour Claude Code |

## Vérification avant de terminer

```bash
skill: "demo-seed-check"
skill: "web-build-test"
```

Ou manuellement :

```bash
cd backend && .venv/bin/python -m ruff check app tests && .venv/bin/python -m pytest
cd frontend && npm run build && npm run lint
```

## Points clés

- Les données bancaires sont sensibles et hors dépôt.
- La base SQLite vit dans `./data` / `MOULAGA_DATA_DIR`.
- La migration CSV de Banque_v3 est une commande one-shot, pas une route API.
- Apres la migration, SQLite est la source de verite pour les comptes et transactions.
- La migration doit rester atomique et idempotente.
- Les migrations de schema doivent sauvegarder une base existante avant modification.
- La categorisation privee et les identites marchandes restent entierement locales.
- `ROADMAP.md` trace les 26 surfaces fonctionnelles, leur validation et l'ordre d'audit iteratif.
