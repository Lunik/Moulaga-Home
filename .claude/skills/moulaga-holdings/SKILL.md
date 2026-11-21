---
name: moulaga-holdings
description: Met à jour les actifs (opérations achat/vente et cours actuels) d'un compte titres, PEA, assurance vie ou wallet crypto dans l'app moulaga via son API. À utiliser dès que l'utilisateur demande de refaire l'historique d'opérations d'un compte à partir de PDF, relevés ou captures d'écran, d'ajouter des récompenses (staking, dividendes réinvestis), ou de mettre à jour le prix actuel des actifs (boursorama.com, captures d'écran), même s'il ne cite pas l'API.
---

# Mise à jour des actifs moulaga

App FastAPI + React, API sous `/api` (sur l'hôte de l'app, demandé à l'utilisateur). Tout script et tout JSON restent dans le scratchpad, jamais dans le dépôt : ce sont des données bancaires.

## 1. Authentification

Ne jamais demander ni écrire le PIN dans un fichier. Demander à l'utilisateur de se connecter lui-même (`! curl ...`) :

```
! curl -sk -c $SCRATCH/jar.txt -X POST https://<hôte-moulaga>/api/profiles/<id>/select -H 'content-type: application/json' -d '{"pin":"…"}'
```

`GET /api/profiles` donne l'id. Le cookie `moulaga_profile_session` dure 12 h, avec verrou après 15 min d'inactivité : si 401, redemander un login. Lire le cookie du jar dans les scripts Python (`urllib`, contexte SSL non vérifié si certificat local).

## 2. Modèle de données

- `Holding` : quantité, `average_price` (PRU), `current_price`, `symbol` (ISIN ou ticker), `asset_class`.
- `HoldingOperation` : seulement `buy` / `sell`. `unit_price` à 2 décimales, quantité à 10 décimales.
- Une position = rejeu des opérations : achat = moyenne pondérée, vente = PRU inchangé. Vente > position = 422. Pas de type dividende, arbitrage ou frais : les modéliser en achats.

Endpoints :
- `GET /accounts` (trouver l'id par nom ; tolérer les fautes de frappe), `GET /holdings?account_id=`, `GET /holding-operations`
- `POST /holding-operations` avec `holding_id`, ou `new_holding{account_id,name,symbol,asset_class}` pour un nouveau support. Corps : `operation_type, quantity, unit_price, occurred_on` (date complète acceptée).
- `DELETE /holdings/{hid}/operations/{oid}`, `DELETE /holdings/{id}` (doublons seulement)
- `PATCH /holdings/{id}` : `current_price`, `symbol`, etc.

## 3. Règles de conduite

1. **Lire d'abord** : sauvegarder holdings et opérations existants en JSON (scratchpad) avant toute écriture.
2. Refaire un historique = supprimer les anciennes opérations du compte (ordre chrono inverse) puis recréer (ordre chrono). Demander avant : date d'ouverture quand les documents ne remontent pas assez loin, et définition du PRU voulu.
3. Ne pas supprimer de holding sauf doublon. Ne pas toucher `asset_class` existante.
4. Après écriture, relire l'API : quantités et PRU contre les documents, valeur totale du compte.
5. Rapport final : écarts restants, hypothèses, variations de cours fortes à vérifier.

## 4. Sources et recettes

**PDF** : extraire le texte avec ghostscript (`gs -q -sDEVICE=txtwrite -o out.txt in.pdf`) ; `pdftotext` et `pypdf` sont souvent absents. Écrire un script de parsing, vérifier les cas atypiques (OPC sans « Montant brut »).

**Assurance vie (lettres d'allocation, relevé)** : déduire les opérations des écarts de parts entre deux allocations successives, au prix de la valeur de part. Réconcilier avec le relevé final (parts arrondies à 2 décimales, tolérance ±0,005). Pour que le PRU colle au relevé, résoudre linéairement le prix du premier achat de chaque support. Dividendes réinvestis : achat = montant ÷ valeur de part.

**PEA / titres (avis d'opéré)** : prix unitaire = montant net débité ÷ quantité (inclut commissions et TTF), arrondi à 2 décimales. Dividendes, frais de tenue de compte et mouvements d'espèces ne sont pas modélisés : le dire.

**Crypto / récompenses (captures d'écran)** : lire date et quantité de chaque ligne, ajouter des achats. Suivre la convention déjà présente dans le compte (ex. staking à 0,01 € l'unité, donc PRU quasi inchangé) : regarder les opérations existantes avant de choisir. Éviter de recréer une date déjà saisie.

**Cours actuels** :
- Source par défaut : boursorama.com. Chercher par ISIN : `/recherche/?query=<ISIN>` redirige vers la fiche ; le premier élément `data-ist-last` est le cours. Passer par Chrome (`mcp__claude-in-chrome__*`, `fetch` en JS dans la page) par lots de ~10 ISIN, en renvoyant de courtes chaînes `isin=prix` (les sorties longues sont tronquées).
- Valider le nom de la fiche trouvée avant d'appliquer ; renseigner `symbol` (ISIN) quand il manque.
- Si l'utilisateur donne les cours (capture d'écran), ils priment.
- Repricer aussi les positions à 0 part.
- Signaler les variations > 15 % (comparer à l'ancien cours) : vérifier la page plutôt que d'écrire une erreur de scraping.
- Les cours de fonds sont la dernière valeur liquidative, pas forcément celle du jour.
