# QA Rules — DB Migration

## Enforcement

Avant chaque commit qui touche le schéma SQLite :

```bash
python3 backend/scripts/check_migration_rollback.py
```

Le script doit retourner le code 0 et afficher `Migration + rollback OK`.

## Vérifications obligatoires

- [ ] `SCHEMA_VERSION` est incrémenté et cohérent avec `models.py`.
- [ ] `EXPECTED_COLUMNS` dans `migrations.py` contient toutes les nouvelles colonnes.
- [ ] `rollback_migration.py` existe et applique `ALTER TABLE ... DROP COLUMN`.
- [ ] `tests/test_migration_rollback.py` passe (`pytest -v`).
- [ ] Aucune colonne erronée (ex. `recurring_series_id` au lieu de `recurring_series_repayment_id`) n'est ajoutée.
- [ ] `seed_demo.py` est mis à jour si le schéma change.
- [ ] `.data/demo/moulaga.db` n'est pas corrompu par le test.
