---
name: local-demo
description: Demarre la demonstration Moulaga dans le depot local et presente au developpeur les parcours a valider apres une fonctionnalite terminee.
---

# local-demo

## Objectif

Rendre chaque fonctionnalite terminee immediatement observable : servir l'application complete
depuis le depot, avec la seed synthetique fraiche, puis indiquer au developpeur l'URL et les ecrans
exacts a valider.

## Quand l'utiliser

- Systematiquement quand une fonctionnalite ou un correctif est termine, apres `demo-seed-check` et
  `web-build-test`, avant de rendre la main au developpeur.
- Quand une revue visuelle est demandee sur une page, un etat ou un parcours.
- Jamais sur des donnees bancaires reelles : cette skill n'utilise que la seed de demonstration.

## Procedure

1. Verifier d'abord que la seed couvre le changement (`demo-seed-check`) et que le build et les
   tests passent (`web-build-test`). Une demo qui ne montre pas la fonctionnalite est inutile.
2. Demarrer l'instance locale depuis la racine du depot :

   ```bash
   ./scripts/demo-local.sh start
   ```

   Le script installe les dependances manquantes, construit le frontend dans
   `backend/app/static`, regenere la seed dans `.data/demo`, puis sert l'application sur
   <http://127.0.0.1:8010> (port suivant libre si 8010 est occupe).
3. Verifier que l'instance repond avant de la presenter :

   ```bash
   ./scripts/demo-local.sh status
   ```

4. Annoncer au developpeur, en une reponse courte :
   - l'URL exacte affichee par le script ;
   - un lien profond par ecran impacte, par exemple `#/dashboard`, `#/accounts`,
     `#/accounts/<id>`, `#/budget/transactions`, `#/budget/cashflow`, `#/budget/envelopes`,
     `#/wealth/holdings`, `#/wealth/real-estate`, `#/family`, `#/settings` ;
   - les etapes concretes de validation, y compris les etats limites semes (compte archive,
     pagination, piece jointe, transfert, projection) ;
   - la commande d'arret `./scripts/demo-local.sh stop`.
5. Laisser l'instance active pendant la validation. Si le developpeur demande une correction,
   appliquer le correctif puis relancer `./scripts/demo-local.sh restart`.

## Commandes utiles

| Besoin | Commande |
|---|---|
| Demarrer avec build et seed neuve | `./scripts/demo-local.sh start` |
| Relancer apres un correctif | `./scripts/demo-local.sh restart` |
| Relance rapide sans rebuild ni reseed | `./scripts/demo-local.sh start --skip-build --keep-data` |
| Forcer un port | `./scripts/demo-local.sh start --port 8020` |
| Ouvrir le navigateur | `./scripts/demo-local.sh start --open` |
| Etat courant | `./scripts/demo-local.sh status` |
| Journal du serveur | `./scripts/demo-local.sh logs` |
| Arreter | `./scripts/demo-local.sh stop` |

## Garanties a preserver

- La demo tourne dans le depot : base et pieces jointes synthetiques sous `.data/demo`, PID et
  journal sous `.data/demo-runtime`, les deux ignores par Git.
- `MOULAGA_DATA_DIR` n'est jamais pointe vers `/data` et `MOULAGA_DEMO_MODE` reste `false` : la base
  reelle de l'utilisateur et le conteneur Docker du port 8000 ne sont jamais touches.
- Aucun fichier genere par la demo ne doit etre committe, et aucune sortie ne doit contenir de
  donnees bancaires reelles ni de chemin prive.
- Si le port par defaut est occupe, utiliser le port annonce par le script plutot que tuer le
  processus existant.

## Exemple

Correct : apres l'ajout des pieces jointes de releve, lancer `./scripts/demo-local.sh start`, puis
annoncer « demo sur <http://127.0.0.1:8010>, ouvrir `#/accounts/3`, section Releves, telecharger le
justificatif seme ; arret avec `./scripts/demo-local.sh stop` ».

Incorrect : conclure la fonctionnalite avec seulement « tests verts », sans instance lancee ni
parcours de validation, ou demarrer la demo sur la base persistante `./data`.
