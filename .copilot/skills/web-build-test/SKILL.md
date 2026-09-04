---
name: web-build-test
description: Vérifie le build frontend + tests backend pour un changement Moulaga.
---

# web-build-test

## Objectif

Valider que le frontend et le backend restent compatibles après une modification.

## Étapes

1. Pour tout changement fonctionnel, appliquer d'abord la skill `demo-seed-check`.
2. `cd backend && .venv/bin/python -m pytest tests/test_seed_demo.py`
3. `cd backend && .venv/bin/python -m ruff check app tests`
4. `cd backend && .venv/bin/python -m pytest`
5. `cd frontend && npm run build`
6. `cd frontend && npm run lint`

## Quand l'utiliser

- Avant de conclure un correctif ou une fonctionnalité.
- Pour confirmer qu'un changement de schéma ou d'API ne casse pas le dashboard.
- Pour confirmer que la seed de demonstration reste executable et couvre le changement.
