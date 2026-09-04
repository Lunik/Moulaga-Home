# Moulaga

Application auto-hebergee de budget, cashflow et suivi patrimonial. Toutes les donnees restent dans
une base SQLite locale et persistante.

## Fonctionnalites

- tableau de bord du patrimoine net, actifs, dettes et evolution mensuelle ;
- comptes groupes par etablissement, historique, releves, configurations de livrets et positions ;
- registre pagine des transactions avec pieces jointes locales, creation, edition, suppression et filtres ;
- cycle budgetaire configurable, enveloppes, cashflow Sankey et ventilation hierarchique ;
- categories, sous-categories, archivage et regles deterministes ;
- boite de categorisation et suggestions entierement locales ;
- series recurrentes, detection de changements et echeancier previsionnel ;
- dettes, positions, valorisations, contributions et performance du portefeuille ;
- foyers locaux, roles, comptes partages et objectifs communs ;
- themes clair/sombre/systeme, formats de date et styles de navigation ;
- identites marchandes locales par monogramme et couleur, sans appel externe.

La correspondance avec les 26 maquettes et l'ordre d'audit iteratif des fonctionnalites sont
decrits dans [ROADMAP.md](ROADMAP.md).

## Confidentialite

Le fichier `Banque_v3.numbers`, les exports CSV et les bases SQLite contiennent des donnees
confidentielles. Ils ne doivent jamais etre copies dans le depot ou les logs.

- la migration Banque_v3 est une commande one-shot, jamais une route API ;
- la categorisation dite privee utilise uniquement les regles et l'historique SQLite local ;
- aucune donnee bancaire n'est envoyee a un modele ou un service tiers ;
- les identites marchandes sont saisies et stockees localement, sans telechargement de logo ;
- les donnees de test et de demonstration sont entierement synthetiques.
- les pieces jointes sont conservees sous `MOULAGA_DATA_DIR/attached` dans des chemins haches ;
  elles restent sensibles et hors du depot Git.

## Demarrage Docker

```bash
docker compose up --build
```

Ouvrir ensuite <http://localhost:8000>.

Le volume `./data:/data` conserve la base `./data/moulaga.db` lors des redemarrages et
reconstructions du conteneur.

## Demarrage en developpement

Backend :

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
MOULAGA_DATA_DIR=./.data .venv/bin/uvicorn app.main:app --reload
```

Frontend :

```bash
cd frontend
npm install
npm run dev
```

Vite proxifie `/api` vers <http://localhost:8000>.

## Base persistante et migrations

SQLite devient la source de verite apres la reprise initiale. Au demarrage, Moulaga :

1. inspecte la version du schema avec `PRAGMA user_version` ;
2. cree une sauvegarde horodatee avant toute modification d'une base existante ;
3. applique les ajouts non destructifs necessaires ;
4. conserve les comptes, transactions et relations historiques.

Pour une sauvegarde manuelle coherente :

```bash
docker compose stop moulaga
cp data/moulaga.db /chemin/prive/moulaga-backup.db
docker compose start moulaga
```

La copie est sensible et doit rester hors du depot.

## Migration initiale de Banque_v3

1. Exporter localement `Banque_v3.numbers` au format CSV.
2. Arreter Moulaga.
3. Executer la migration sur le fichier local.
4. Redemarrer Moulaga puis conserver SQLite comme source de verite.

Avec l'environnement Python :

```bash
docker compose stop moulaga
cd backend
MOULAGA_DATA_DIR=../data .venv/bin/moulaga-migrate-banque-v3 \
  "/chemin/prive/banque.csv" --account "Compte courant"
cd ..
docker compose start moulaga
```

Avec Docker, sans copier le CSV dans le depot :

```bash
docker compose stop moulaga
docker compose run --rm \
  -v "/chemin/absolu/banque.csv:/import/banque.csv:ro" \
  moulaga moulaga-migrate-banque-v3 /import/banque.csv --account "Compte courant"
docker compose start moulaga
```

Colonnes reconnues :

- `Date` : `YYYY-MM-DD`, `DD/MM/YYYY` ou `DD-MM-YYYY` ;
- `Libelle` / `Description` ;
- `Montant`, ou `Debit` + `Credit` ;
- `Categorie` facultative.

La migration est atomique et idempotente : une ligne invalide annule l'ensemble, et une relance ne
duplique pas les transactions.

## Donnees fictives pour la QA

La commande suivante refuse le repertoire `/data` par defaut et doit cibler un dossier temporaire
explicite :

```bash
MOULAGA_DATA_DIR=/tmp/moulaga-demo .venv/bin/moulaga-seed-demo --reset
MOULAGA_DATA_DIR=/tmp/moulaga-demo \
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010
```

Ne jamais utiliser `--reset` contre une base utilisateur.

## Verification

```bash
cd backend
.venv/bin/python -m ruff check app tests
.venv/bin/python -m pytest

cd ../frontend
npm run lint
npm run build
```
