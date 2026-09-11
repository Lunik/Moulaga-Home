# Moulaga

Application auto-hebergee de suivi de comptes, budget recurrent et patrimoine. Toutes les donnees
restent dans une base SQLite locale et persistante.

## Fonctionnalites

- tableau de bord dont les soldes proviennent des derniers releves de comptes et dont les revenus,
  depenses, budget disponible, flux Sankey et prochaines echeances proviennent des series
  recurrentes actives ;
- comptes groupes par etablissement et entite regionale, avec selecteur de banque,
  numero ou identifiant facultatif, historique, releves avec pieces jointes locales,
  configurations de livrets et positions ;
- cycle budgetaire configurable, enveloppes plafonnees ou non avec budgets parents repartis entre
  leurs sous-categories et reliquat automatique « Autres », report lors de leur suppression,
  projection graphique des flux recurrents avec selection rapide du cycle ou de l'annee ;
- categories deplacables dans la hierarchie, archivage protecteur et restauration ;
- series recurrentes typees, modifiables et accompagnees de pieces jointes locales, avec
  echeancier previsionnel ;
- dettes creees et modifiees en modale, association a une serie recurrente, import TSV
  d'echeancier pour les credits, liens navigables entre biens, dettes et series recurrentes,
  biens immobiliers avec quote-part et emprunt associe, positions, valorisations,
  contributions et performance du portefeuille ;
- foyers locaux, roles, comptes partages et objectifs communs ;
- themes clair/sombre/systeme, formats de date et styles de navigation ;
- PWA installable avec interface, graphiques et tuiles de synthese disponibles hors ligne.

Les derniers releves sont la source des soldes ; les series recurrentes actives, hors virements,
sont la source des indicateurs et graphiques budgetaires. Moulaga ne conserve aucun registre
d'operations unitaires.

La correspondance avec les 26 maquettes et l'ordre d'audit iteratif des fonctionnalites sont
decrits dans [ROADMAP.md](ROADMAP.md).

## Confidentialite

Les exports bancaires et les bases SQLite contiennent des donnees confidentielles. Ils ne doivent
jamais etre copies dans le depot ou les logs.

- aucune donnee bancaire n'est envoyee a un modele ou un service tiers ;
- les donnees de test et de demonstration sont entierement synthetiques.
- les pieces jointes des releves, recurrents, dettes et biens sont conservees sous
  `MOULAGA_DATA_DIR/attached` dans des chemins haches ; elles restent sensibles et hors du depot Git.

## Demarrage Docker

Le fichier `docker-compose.yml` active le mode demonstration par defaut. Chaque demarrage du
conteneur efface la base et les pieces jointes presentes dans `./data`, puis recree la seed
synthetique :

```bash
docker compose up --build
```

Ouvrir ensuite <http://localhost:8000>.

Pour commencer a conserver les modifications dans le temps, retirer
`MOULAGA_DEMO_MODE: "true"` de `docker-compose.yml`, puis recreer le conteneur :

```bash
docker compose up -d --force-recreate
```

Sans cette variable, l'image utilise `MOULAGA_DEMO_MODE=false` et le volume `./data:/data`
conserve la base `./data/moulaga.db` lors des redemarrages et reconstructions du conteneur.

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

## Installation PWA et mode hors ligne

Moulaga peut etre installee depuis un navigateur compatible lorsqu'elle est servie en HTTPS, ou
depuis `localhost` pendant le developpement. Le premier chargement en ligne precache l'interface et
les vues compilees, puis precharge les donnees des graphiques et tuiles courantes.

Les lectures visuelles utilisent le reseau en priorite et la derniere reponse locale en cas
d'indisponibilite de l'instance. Les filtres et periodes deja consultes sont egalement conserves.
Les pieces jointes ne sont volontairement pas stockees pour le mode hors ligne. Les modifications
restent reservees au mode connecte.

## Base persistante et migrations

Les operations de cette section supposent que `MOULAGA_DEMO_MODE` a ete retire du Compose. Tant
que le mode demonstration est actif, le prochain demarrage remplace toutes les donnees.

SQLite devient la source de verite apres la reprise initiale. Au demarrage, Moulaga :

1. inspecte la version du schema avec `PRAGMA user_version` ;
2. cree une sauvegarde horodatee avant toute modification d'une base existante ;
3. applique les ajouts non destructifs necessaires ;
4. lors du passage au schema sans registre, materialise le dernier solde historique dans un releve,
   puis retire les anciennes tables et leurs pieces jointes ;
5. conserve les comptes, relevés, recurrents et relations patrimoniales.

Pour une sauvegarde manuelle coherente :

```bash
docker compose stop moulaga
cp data/moulaga.db /chemin/prive/moulaga-backup.db
docker compose start moulaga
```

La copie est sensible et doit rester hors du depot.

## Donnees fictives pour la QA

Pour une demonstration locale complete depuis le depot, sans Docker :

```bash
./scripts/demo-local.sh start
```

Le script installe les dependances manquantes, construit le frontend, regenere la seed synthetique
dans `.data/demo` puis sert l'application sur <http://127.0.0.1:8010> (premier port libre a partir
de 8010). `./scripts/demo-local.sh status`, `logs`, `restart` et `stop` pilotent l'instance. Les
donnees de cette instance sont synthetiques, confinees a `.data/` et ignorees par Git ; la base
persistante `./data` n'est jamais touchee.

Le demarrage Docker standard active deja la seed de demonstration et la recree a chaque demarrage.
Pour lancer la meme seed manuellement hors du conteneur, utiliser un dossier temporaire explicite :

```bash
MOULAGA_DATA_DIR=/tmp/moulaga-demo .venv/bin/moulaga-seed-demo --reset
MOULAGA_DATA_DIR=/tmp/moulaga-demo \
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010
```

Cette seed fournit des scenarios synthetiques pour chaque fonctionnalite, notamment les comptes
actifs et archives, les soldes issus des releves, les budgets et flux issus des series recurrentes,
l'epargne et sa projection, les positions, les transferts, la pagination et les pieces jointes.
Toute nouvelle fonctionnalite doit enrichir la seed et
`backend/tests/test_seed_demo.py` dans le meme changement.

Ne jamais activer `MOULAGA_DEMO_MODE` ni utiliser `--reset` contre une base utilisateur.

## Verification

```bash
cd backend
.venv/bin/python -m ruff check app tests
.venv/bin/python -m pytest

cd ../frontend
npm run lint
npm run build
```
