---
name: db-migration
description: Crée et valide un script de migration SQLite avec rollback testé et migration idempotente.
---

# db-migration

## Objectif

Garantir que toute modification du schéma SQLite (`models.py` → `migrations.py`) est accompagnée d'un script de migration non destructif, d'un rollback testé et d'une vérification d'idempotence sur une base réelle.

## Quand l'utiliser

- Quand `models.py` est modifié (nouvelle table, colonne, contrainte, index).
- Avant tout `git commit` qui touche le schéma persistant.
- Quand `SCHEMA_VERSION` est incrémenté dans `migrations.py`.

## Règles QA obligatoires (QA_RULES.md)

1. **Migration script** : `backend/app/migrations.py` doit contenir `EXPECTED_COLUMNS` et `SCHEMA_VERSION` mis à jour.
2. **Rollback script** : créer `backend/scripts/rollback_migration.py` qui applique `ALTER TABLE ... DROP COLUMN` pour chaque colonne ajoutée dans `EXPECTED_COLUMNS`.
3. **Rollback test** : `backend/tests/test_migration_rollback.py` doit exécuter la migration puis le rollback et vérifier que `PRAGMA user_version` revient à l'ancienne version et que le schéma est restauré.
4. **Idempotence** : relancer la migration deux fois sur le même DB doit être un no-op (pas d'erreur SQLite, pas de colonne dupliquée).
5. **Sauvegarde** : `migrations.py` doit créer un `.backup-...` avant toute modification structurelle.
6. **Tests** : `pytest tests/test_migration_rollback.py` doit passer avant tout merge.

## Procédure

1. Modifier `models.py` avec la nouvelle colonne/table.
2. Mettre à jour `EXPECTED_COLUMNS` dans `backend/app/migrations.py` et augmenter `SCHEMA_VERSION`.
3. Écrire le rollback dans `backend/scripts/rollback_migration.py`.
4. Écrire le test dans `backend/tests/test_migration_rollback.py`.
5. Exécuter :

```bash
cd backend
.venv/bin/python -m pytest tests/test_migration_rollback.py -v
```

6. Vérifier que `.data/demo/moulaga.db` reste intact (pas touché par le test) et que `./data` est ignoré par Git.

## Garanties

- Aucune colonne manquante dans `EXPECTED_COLUMNS` (erreur `no such column` au runtime).
- Aucune colonne erronée dans `EXPECTED_COLUMNS` (ancienne colonne `recurring_series_id` supprimée du code et du DB si présente).
- Le rollback doit être testé et documenté dans le même changement que la migration.
- La seed `backend/app/commands/seed_demo.py` doit refléter le nouveau schéma.
