---
name: demo-seed-check
description: Met a jour et verifie la seed synthetique pour chaque fonctionnalite Moulaga.
---

# demo-seed-check

## Objectif

Garder `backend/app/commands/seed_demo.py` comme catalogue executable de toutes les fonctionnalites
et de tous les etats importants visibles dans l'application.

## Quand l'utiliser

- Pour toute nouvelle fonctionnalite ou modification de comportement, backend ou frontend.
- Quand une page ajoute un etat, une action, un filtre, un seuil ou une nouvelle relation.
- Avant `web-build-test`, afin que la validation globale parte d'une seed a jour.

## Procedure obligatoire

1. Reperer les donnees, etats et routes necessaires au parcours modifie.
2. Ajouter dans `backend/app/commands/seed_demo.py` un scenario synthetique coherent qui rend le
   parcours directement visible. Couvrir les seuils fonctionnels reels, par exemple plus de 100
   mouvements si la page pagine a 100.
3. Reutiliser les relations et helpers du produit plutot que fabriquer une representation propre a
   la seed. Les soldes, transferts, archives et pieces jointes doivent respecter les memes
   invariants que l'API.
4. Generer les eventuelles pieces jointes uniquement a l'execution sous `MOULAGA_DATA_DIR`, avec un
   contenu explicitement synthetique. Ne jamais committer de fichier bancaire ou de fichier genere.
5. Preserver les protections de la commande : dossier `/data` refuse hors
   `MOULAGA_DEMO_MODE=true`, ecrasement refuse sans `--reset`, chemins locaux absents des sorties et
   nettoyage des fichiers lors d'un reset. Le mode demo Docker est volontairement destructif et
   doit reinitialiser la seed a chaque demarrage tant que la variable est presente.
6. Ajouter ou adapter les assertions de `backend/tests/test_seed_demo.py` pour verifier le scenario
   via les routes consommees par l'interface, y compris le telechargement si un fichier est seme.
7. Executer :

   ```bash
   cd backend
   .venv/bin/python -m ruff check app/commands/seed_demo.py tests/test_seed_demo.py
   .venv/bin/python -m pytest tests/test_seed_demo.py
   ```

## Exemple

Correct : une nouvelle piece jointe de releve ajoute un releve synthetique, cree son fichier local
hashe a l'execution, puis verifie son compteur, sa liste et son telechargement dans
`test_seed_demo.py`.

Incorrect : tester uniquement l'upload avec une fixture API et laisser la seed sans piece jointe ;
la fonctionnalite resterait invisible lors de la QA de l'application complete.
