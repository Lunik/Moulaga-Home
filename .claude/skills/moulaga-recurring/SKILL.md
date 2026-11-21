---
name: moulaga-recurring
description: Compare les relevés de compte (PDF, extraits) avec les séries du budget récurrent de l'app moulaga et propose, puis applique après accord, les créations, changements de montant et fins de série via l'API. À utiliser dès que l'utilisateur demande d'identifier les changements de budgets récurrents (nouveau, plus d'actualité, changement de montant), de vérifier les prélèvements ou virements permanents, ou de contrôler les doublons parmi les séries récurrentes, même sans citer l'API. Toujours lister avant de modifier.
---

# Revue du budget récurrent moulaga

Scripts et PDF extraits restent dans le scratchpad, jamais dans le dépôt : ce sont des données bancaires. Connexion : l'utilisateur se connecte lui-même (voir `moulaga-holdings`), jamais de PIN dans un fichier.

## 1. Modèle et pièges

- `GET /api/recurring` : `id, label, account_id, category_id, frequency (weekly|monthly|quarterly|yearly), next_due, amount, amount_type (fixed|variable), status (active|paused|ended), recurring_type, custom_type, total_amount, profile_share`.
- `POST /api/recurring`, `PATCH /api/recurring/{id}`, `DELETE /api/recurring/{id}` (204).
- **Compte partagé : la lecture renvoie `amount` = part du profil, mais l'écriture attend le total.** Pour un prêt à 1000 € sur un compte joint à deux, envoyer `-1000.00` (la part devient `-500.00`). Toujours relire `total_amount` et `profile_share` après un `PATCH`.
- **Pas de date de fin ni de compte cible** sur une série : une échéance qui s'arrête à date fixe ou une destination de virement ne peuvent pas être enregistrées. Le dire, ne pas les simuler.
- `next_due` sert d'ancre de cadence : une date passée reste valable. Pour une série créée, mettre la prochaine occurrence.
- `recurring_type = other` exige `custom_type` (ex. « Frais bancaires »).
- **Les séries `transfer` sont exclues du budget** (`backend/app/recurring_budget.py`) : pas de double comptage entre un virement interne et les dépenses du compte destinataire. Elles apparaissent en revanche dans `/api/recurring/forecast`.
- Catégories : `GET /api/categories` (ids selon le profil, ne pas les mémoriser).

## 2. Méthode

1. **Lire** les séries et les relevés (extraction `gs -sDEVICE=txtwrite`, voir `moulaga-statements`). Les montants du Joint sont à comparer en total, pas en part.
2. **Comparer** chaque mouvement du relevé avec une série du même compte :
   - **Nouveau** : mouvement répété (2 mois ou plus, ou explicitement permanent) sans série.
   - **Changement de montant** : série trouvée par libellé et date, montant différent d'un seuil clair.
   - **Plus d'actualité** : série absente d'un seul relevé = signal faible, ne jamais conclure sur un mois (échéances annuelles, trimestrielles, décalées).
   - Écarter les achats ponctuels, un solde d'impôt annuel, un salaire variable.
3. **Croiser** avec les ordres permanents donnés par l'utilisateur (captures d'app bancaire) : un virement récurrent y est décrit avec montant, jour et période, ce qui évite de deviner.
4. **Lister avant de toucher**, avec un numéro distinct par ligne (jamais deux lignes sous le même numéro), classé en Nouveaux, Changements de montant, Absents, avec montant en base, montant constaté, source, et une recommandation. L'utilisateur répond `go` ou `nogo` par numéro. Garder le suivi des numéros d'un tour à l'autre.
5. **Appliquer seulement les `go`**. Un récap final précède l'application quand l'utilisateur le demande ; une suppression exige un accord explicite.
6. **Vérifier les doublons** après application : libellés identiques par compte, séries proches (même montant et fréquence est souvent légitime : plusieurs abonnements ou provisions identiques). Signaler les chevauchements d'intention (taxe foncière en dépense et en virement de provision), sans trancher seul.
7. **Relire** `GET /api/recurring` et donner un récapitulatif par numéro.

## 3. Rapport

Tableau par numéro : action, série, avant, après, statut (fait, nogo, à décider). Terminer par les limites (pas de date de fin) et les risques de double comptage.
