# Moulaga — Instructions pour Copilot

## Sources de vérité

Avant toute modification, lire dans l'ordre :

1. `AGENTS.md` — conventions, architecture, règles métier.
2. `README.md` — démarrage et usage.
3. `backend/tests/` et le code des routes si l'impact touche l'API.

## Ce que c'est

Moulaga est une application auto-hébergée de gestion de budget personnel, avec :

- backend FastAPI + SQLite
- frontend React + Vite + Tailwind
- stockage local des données sensibles dans `./data` ou `MOULAGA_DATA_DIR`
- migration initiale one-shot d'un export CSV Numbers, jamais exposee par l'API

## Règles de confidentialité

- Ne jamais inclure les données bancaires réelles dans des exemples, captures, logs ou tests.
- L'export Numbers doit rester hors dépôt : `.numbers`, `.csv`, `*.db` sont ignorés.
- Les fichiers de données sensibles doivent vivre dans un volume local, pas dans le code source.

## Vérification avant de terminer

Toujours faire au minimum :

```bash
cd backend && .venv/bin/python -m ruff check app tests && .venv/bin/python -m pytest
cd frontend && npm run build && npm run lint
```

## Skills disponibles

- `web-build-test` — vérifie backend + frontend après une modification
- `budget-import-check` — vérifie la commande de migration bancaire initiale

## Règles métier

- Un compte, une catégorie et une transaction ont des règles claires et doivent rester cohérents.
- Les montants représentent des valeurs décimales avec centimes.
- La migration CSV doit etre atomique, idempotente et distincte de l'application interactive.
- SQLite est la source de verite persistante pour toutes les operations suivantes.
- Les chiffres affichés doivent rester cohérents entre overview, comptes et catégories.
- Les calculs de patrimoine, poches et partages ne doivent jamais compter deux fois un montant.
- Aucune suggestion ou identite marchande ne doit appeler un service externe.

## Workflow

1. Comprendre le besoin et vérifier les conventions dans `AGENTS.md`.
2. Modifier uniquement le périmètre nécessaire.
3. Vérifier le build et les tests.
4. Ne pas publier de données bancaires ni de pièces jointes sensibles.
