---
name: web-build-test
description: Vérifie le build frontend + tests backend pour un changement Moulaga.
---

# web-build-test

## Objectif

Valider que le frontend et le backend restent compatibles après une modification.

## Étapes

1. `cd backend && .venv/bin/python -m ruff check app tests`
2. `cd backend && .venv/bin/python -m pytest`
3. `cd frontend && npm run build`
4. `cd frontend && npm run lint`

## Quand l'utiliser

- Avant de conclure un correctif ou une fonctionnalité.
- Pour confirmer qu'un changement de schéma ou d'API ne casse pas le dashboard.
