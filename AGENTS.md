# AGENTS.md — Moulaga

Conventions et décisions de conception à lire avant toute modification de ce dépôt.

## Ce que c'est

Moulaga est une application auto-hébergée de gestion et de suivi de budget et d'argent. L'objectif est de garder la donnée locale, privée, sous contrôle de l'utilisateur, sans la diffuser dans le dépôt Git.

Le stack principal est :

- backend : FastAPI + SQLite + SQLAlchemy
- frontend : React + Vite + Tailwind
- code source : hébergé localement, app servi depuis un seul conteneur

## Données sensibles

Tout export bancaire CSV/DB et toute piece jointe financiere sont sensibles et confidentiels. Ils
doivent rester hors du dépôt Git.

Règles :

- ne jamais committer de `.numbers`, `.csv`, `.db` ;
- ignorer `./data` et `MOULAGA_DATA_DIR` ;
- éviter les logs qui exposent des détails bancaires ;
- stocker les pieces jointes uniquement sous `MOULAGA_DATA_DIR/attached` avec des chemins haches ;
- utiliser des exemples synthétiques dans les tests.

## Architecture

### Backend

Les routes FastAPI sont decoupees par domaine dans `backend/app/routers/` : budget, comptes,
categories, recurrents, patrimoine, foyers et preferences.

Le schema persistant est dans `backend/app/models.py`, les DTO dans `backend/app/schemas.py` et le
versionnement non destructif dans `backend/app/migrations.py`.

### Frontend

L'interface principale est `frontend/src/App.tsx`, les vues sont dans `frontend/src/views/`, le
routage URL dans `frontend/src/routing.ts` et les composants partages dans `frontend/src/ui.tsx`.

Le dashboard doit montrer :

- solde total issu des derniers releves
- revenus recurrents du mois
- depenses recurrentes du mois
- budget disponible apres recurrents
- projection recurrente sur douze mois
- prochaines echeances recurrentes

## Règles métier

- Les montants doivent être stockés avec 2 décimales.
- Les derniers releves mensuels sont la source de verite des soldes ; sans releve, le solde initial
  est utilise.
- Les series recurrentes actives sont la source des revenus, depenses, enveloppes et graphiques
  budgetaires. Les series de type `transfer` en sont exclues.
- Aucun registre d'operations unitaires n'est conserve ou expose.
- Les catégories peuvent être de type `income` ou `expense`.
- Le budget mensuel d'une catégorie est facultatif.
- Les liens partages et positions ne doivent jamais provoquer de double comptage.
- Le transfert d'un solde lors de l'archivage met directement a jour les releves des deux comptes.
- Un compte archive est consultable et restaurable, mais toutes ses autres mutations sont refusees.
- Les projections de livrets utilisent le taux configurable du compte et excluent les versements futurs.
- Les mutations d'un foyer exigent un acteur et un role suffisant.

L'evolution multi-utilisateur, ses trois natures de propriete et ses invariants de partage sont
decrits dans `MULTI_USER.md`.

## Seed de demonstration

- `backend/app/commands/seed_demo.py` est le contrat de demonstration et de QA visuelle de
  l'application. Toute fonctionnalite ajoutee ou modifiee doit mettre a jour cette seed dans le
  meme changement afin de fournir un cas synthetique coherent et directement testable.
- Chaque nouvel etat visible ou parcours metier doit etre represente, notamment les variantes
  actives/archivees, les donnees liees, les etats vides utiles et les seuils comme la pagination.
- `backend/tests/test_seed_demo.py` doit verifier les donnees et les routes necessaires au nouveau
  parcours. Une fonctionnalite n'est pas terminee si seule son implementation est testee avec des
  fixtures isolees.
- La seed ne doit contenir aucune donnee bancaire reelle. Les pieces jointes de demonstration sont
  generees a l'execution sous `MOULAGA_DATA_DIR`, jamais ajoutees au depot.
- `MOULAGA_DEMO_MODE=true` est explicitement destructif : l'entrypoint Docker execute la seed avec
  `--reset` a chaque demarrage. Le Compose l'active par defaut ; l'utilisateur doit retirer cette
  variable avant de commencer a conserver ses modifications ou d'importer ses donnees.
- Hors mode demonstration, conserver les gardes de securite de la commande : refus de `/data`,
  refus d'ecraser une base sans `--reset` et absence de chemins locaux dans les sorties.

## Vérification

Avant de conclure une modification :

```bash
cd backend && .venv/bin/python -m pytest tests/test_seed_demo.py
cd backend && .venv/bin/python -m ruff check app tests && .venv/bin/python -m pytest
cd frontend && npm run build && npm run lint
```

Puis, pour toute fonctionnalite terminee, lancer la demonstration locale et indiquer au
developpeur l'URL et les ecrans a valider :

```bash
./scripts/demo-local.sh start
```

Cette instance sert le frontend construit et la seed synthetique depuis le depot
(`.data/demo`, `.data/demo-runtime`), sans jamais toucher `./data` ni le conteneur Docker.
Elle s'arrete avec `./scripts/demo-local.sh stop`.

## Important

Si une modification touche les releves ou les donnees bancaires, lire en priorite les tests de
budget ; la moindre erreur de calcul a un impact direct sur la fiabilite du produit.
