# Moulaga — Instructions pour Copilot

## Sources de vérité

Avant toute modification, lire dans l'ordre :

1. `AGENTS.md` — conventions, architecture, règles métier.
2. `README.md` — démarrage et usage.
3. `backend/tests/` et le code des routes si l'impact touche l'API.
4. `backend/app/commands/seed_demo.py` et `backend/tests/test_seed_demo.py` pour tout changement
   fonctionnel.

## Ce que c'est

Moulaga est une application auto-hébergée de gestion de budget personnel, avec :

- backend FastAPI + SQLite
- frontend React + Vite + Tailwind
- stockage local des données sensibles dans `./data` ou `MOULAGA_DATA_DIR`

## Règles de confidentialité

- Ne jamais inclure les données bancaires réelles dans des exemples, captures, logs ou tests.
- L'export Numbers doit rester hors dépôt : `.numbers`, `.csv`, `*.db` sont ignorés.
- Les fichiers de données sensibles doivent vivre dans un volume local, pas dans le code source.

## Vérification avant de terminer

Toujours faire au minimum :

```bash
cd backend && .venv/bin/python -m pytest tests/test_seed_demo.py
cd backend && .venv/bin/python -m ruff check app tests && .venv/bin/python -m pytest
cd frontend && npm run build && npm run lint
```

## Skills disponibles

- `web-build-test` — vérifie backend + frontend après une modification
- `demo-seed-check` — maintient la seed synthétique comme catalogue exécutable des fonctionnalités
- `local-demo` — lance la démonstration locale dans le dépôt pour la validation par le développeur

## Règles métier

- Un compte, une catégorie et une série récurrente ont des règles claires et doivent rester cohérents.
- Les montants représentent des valeurs décimales avec centimes.
- SQLite est la source de verite persistante pour toutes les operations suivantes.
- Les derniers releves mensuels pilotent les soldes des comptes et les liquidites du patrimoine ;
  aucun registre d'operations unitaires n'est conserve.
- Les series recurrentes actives pilotent les revenus, depenses, enveloppes et graphiques
  budgetaires ; les virements recurrents doivent en etre exclus.
- Les chiffres affichés doivent rester cohérents entre overview, comptes, catégories et récurrents.
- Les calculs de patrimoine et partages ne doivent jamais compter deux fois un montant.
- Les virements recurrents ne sont ni des revenus ni des depenses budgetaires.
- Un compte archive est en lecture seule jusqu'a sa restauration explicite.
- Les pieces jointes restent sous `MOULAGA_DATA_DIR/attached`, hors Git, dans des chemins haches.
- Les projections de livrets reposent sur le taux du compte et n'anticipent aucun versement.
- Toute fonctionnalite ajoutee ou modifiee doit avoir un scenario synthetique dans
  `backend/app/commands/seed_demo.py` et une assertion de contrat dans
  `backend/tests/test_seed_demo.py`.
- `MOULAGA_DEMO_MODE=true` reinitialise volontairement la base de demonstration a chaque demarrage
  Docker. Il faut retirer cette variable avant tout usage persistant ou import de donnees.

## Workflow

1. Comprendre le besoin et vérifier les conventions dans `AGENTS.md`.
2. Identifier le scenario de demonstration du changement et mettre a jour la seed et son test.
3. Modifier uniquement le périmètre nécessaire.
4. Utiliser `demo-seed-check`, puis vérifier le build et les tests avec `web-build-test`.
5. Lancer `local-demo` et presenter au developpeur l'URL et les ecrans a valider.
6. Ne pas publier de données bancaires ni de pièces jointes sensibles.
