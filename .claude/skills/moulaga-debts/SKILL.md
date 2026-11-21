---
name: moulaga-debts
description: Met à jour les dettes (prêts immobiliers, crédits, paiements échelonnés) dans l'app moulaga via son API à partir de captures d'écran ou de PDF de la banque (capital restant dû, échéance, taux, durée). À utiliser dès que l'utilisateur demande de mettre à jour ses dettes, prêts, crédits ou capital restant dû, même sans mentionner l'API. Ne couvre pas les relevés de compte (moulaga-statements) ni les actifs (moulaga-holdings).
---

# Mise à jour des dettes moulaga

Scripts et fichiers lus restent dans le scratchpad, jamais dans le dépôt : ce sont des données bancaires.

## 1. Authentification

Même procédure que `moulaga-holdings` : l'utilisateur se connecte lui-même (`! curl -c jar.txt ... /api/profiles/<id>/select`), jamais de PIN dans un fichier. Cookie 12 h, verrou après 15 min (401 = redemander).

## 2. Endpoints

- `GET /api/debts` : id, `name`, `principal` (montant initial), `balance` (capital restant dû), `interest_rate`, `minimum_payment` (négatif, assurance incluse), `due_date` (fin), séries récurrentes liées.
- `PATCH /api/debts/{id}` avec `{"balance":"<capital restant dû>"}`. Les champs `paid` et `progress` se recalculent seuls.
- `GET|POST /api/debts/{id}/attachments` : pièces jointes (tableaux d'amortissement, offres).

## 3. Méthode

1. **Lire les images ou PDF** (outil Read pour les captures). Relever par prêt : n° de contrat, capital restant dû, montant initial, échéance, date de fin, taux.
2. **Rattacher à la dette** par le montant initial (nominal) et la date de fin, pas par le nom : la banque nomme les prêts par numéro de contrat, l'app par bien (« <Bien> - Prêt »). En cas de doute entre deux prêts, comparer capital restant dû, échéance et ancien solde en base.
3. **Mettre à jour `balance` seulement.** `minimum_payment` inclut l'assurance : l'écart avec l'échéance de la banque est normal (ex. échéance en base supérieure de quelques euros à celle de la banque). Ne pas écraser les taux, durées et séries récurrentes sans raison claire ; signaler un écart.
4. Ne pas toucher les dettes absentes des documents.
5. **Relire** `GET /api/debts` et vérifier `balance`, `paid`, `progress`.

## 4. Rapport

Tableau dette / avant / après. Ajouter : ce qui a été confirmé sans changement (nominal, échéance, fin), les données absentes des documents (taux), et les dettes non touchées.
