# AGENTS.md — Moulaga

Conventions et décisions de conception à lire avant toute modification de ce dépôt.

## Ce que c'est

Moulaga est une application auto-hébergée de gestion et de suivi de budget et d'argent. L'objectif est de garder la donnée locale, privée, sous contrôle de l'utilisateur, sans la diffuser dans le dépôt Git.

Le stack principal est :

- backend : FastAPI + SQLite + SQLAlchemy
- frontend : React + Vite + Tailwind
- code source : hébergé localement, app servi depuis un seul conteneur

## Données sensibles

Le fichier `Banque_v3.numbers`, tout export bancaire CSV/DB et les pieces jointes de transactions
sont sensibles et confidentiels. Ils doivent rester hors du dépôt Git.

Règles :

- ne jamais committer de `.numbers`, `.csv`, `.db` ;
- ignorer `./data` et `MOULAGA_DATA_DIR` ;
- éviter les logs qui exposent des détails bancaires ;
- stocker les pieces jointes uniquement sous `MOULAGA_DATA_DIR/attached` avec des chemins haches ;
- utiliser des exemples synthétiques dans les tests.

## Architecture

### Backend

Les routes FastAPI sont decoupees par domaine dans `backend/app/routers/` : budget, comptes,
transactions, categories, regles, recurrents, patrimoine, foyers, preferences et identites locales.

Le schema persistant est dans `backend/app/models.py`, les DTO dans `backend/app/schemas.py` et le
versionnement non destructif dans `backend/app/migrations.py`.
La reprise historique de Banque_v3 est exclusivement une commande one-shot dans
`backend/app/commands/import_banque_v3.py`; elle ne doit pas etre exposee par l'API.

### Frontend

L'interface principale est `frontend/src/App.tsx`, les vues sont dans `frontend/src/views/`, le
routage URL dans `frontend/src/routing.ts` et les composants partages dans `frontend/src/ui.tsx`.

Le dashboard doit montrer :

- solde total
- revenus du mois
- dépenses du mois
- budget restant
- graphiques mensuels
- derniers mouvements

## Règles métier

- Les montants doivent être stockés avec 2 décimales.
- Les transactions sont groupees par compte et categorie et le registre complet est pagine.
- La migration CSV initiale doit être atomique et idempotente.
- Après cette migration, SQLite est la source de vérité et les mouvements sont saisis dans l'application.
- Les catégories peuvent être de type `income` ou `expense`.
- Le budget mensuel d'une catégorie est facultatif.
- Les liens partages et positions ne doivent jamais provoquer de double comptage.
- Les transferts entre comptes sont lies, neutres pour le budget et exclus de la categorisation.
- Un compte archive est consultable et restaurable, mais toutes ses autres mutations sont refusees.
- Les projections de livrets utilisent le taux configurable du compte et excluent les versements futurs.
- Les suggestions, logos et identites marchandes ne doivent effectuer aucun appel reseau.
- Les mutations d'un foyer exigent un acteur et un role suffisant.

## Vérification

Avant de conclure une modification :

```bash
cd backend && .venv/bin/python -m ruff check app tests && .venv/bin/python -m pytest
cd frontend && npm run build && npm run lint
```

## Important

Si une modification touche la migration CSV ou les données bancaires, lire en priorité la commande
one-shot et les tests de budget; la moindre erreur de parsing ou de déduplication a un impact direct
sur la fiabilité du produit.
