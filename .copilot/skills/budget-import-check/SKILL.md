---
name: budget-import-check
description: Vérifie la commande one-shot de migration bancaire, son atomicité et sa déduplication.
---

# budget-import-check

## Objectif

Contrôler que la migration initiale des données bancaires exportées au format CSV alimente
correctement SQLite, sans route API, doublon ni import partiel.

## Étapes

1. Vérifier que le CSV contient des colonnes de date, libellé et montant.
2. Vérifier que le parsing gère les formats `YYYY-MM-DD`, `DD/MM/YYYY` et `DD-MM-YYYY`.
3. Vérifier que les montants sont convertis en décimaux à 2 chiffres.
4. Vérifier qu'une ligne invalide annule toute la migration.
5. Vérifier que les doublons sont détectés via hash de source ou clé métier.
6. Vérifier que les comptes et catégories sont bien créés ou réutilisés.
7. Vérifier que `/api/imports/csv` n'existe pas.

## Cas à tester

- import d'un CSV simple avec revenus et dépenses
- import d'un CSV déjà importé
- fichier de mauvais format / `.numbers` direct
- montant avec virgule, espace ou symbole euro
- CSV contenant une ligne invalide
