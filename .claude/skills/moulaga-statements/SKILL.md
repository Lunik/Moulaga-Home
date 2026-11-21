---
name: moulaga-statements
description: Met à jour les relevés mensuels (soldes) et les documents joints (PDF de relevés, extraits de compte, rapports de situation) des comptes bancaires, livrets et contrats d'assurance vie dans l'app moulaga via son API. À utiliser dès que l'utilisateur donne un dossier, un zip ou des PDF de relevés (toute banque ou assurance vie) et demande de mettre à jour les relevés, soldes ou documents d'un compte, même s'il ne parle ni de snapshot ni d'API. Ne couvre pas les opérations ni les cours des actifs (voir moulaga-holdings).
---

# Mise à jour des relevés et documents moulaga

Un relevé moulaga = un snapshot de solde par compte et par mois (`period` = `YYYY-MM`), avec des PDF en pièces jointes. Scripts et fichiers extraits restent dans le scratchpad, jamais dans le dépôt : ce sont des données bancaires.

## 1. Authentification

Même procédure que `moulaga-holdings` : demander à l'utilisateur de se connecter lui-même (`! curl -c jar.txt ... /api/profiles/<id>/select`), ne jamais écrire le PIN. Cookie `moulaga_profile_session`, 12 h, verrou après 15 min d'inactivité (401 = redemander).

## 2. Endpoints

- `GET /api/accounts` : trouver les comptes par nom et institution. Plusieurs comptes peuvent partager un PDF (un relevé peut couvrir compte courant et livrets).
- `GET /api/accounts/{id}/snapshots` : voir les derniers mois.
- `PUT /api/accounts/{id}/snapshots` avec `{"period":"2026-10","balance":"<solde>"}` : crée ou remplace (idempotent).
- `GET /api/accounts/{id}/snapshots/{sid}/attachments` : voir le nommage existant.
- `POST /api/accounts/{id}/snapshots/{sid}/attachments` en multipart, champ `file` (`-F "file=@x.pdf;type=application/pdf"`). Pas idempotent : lister avant, sinon doublon.

## 3. Méthode

1. **Inventaire** : lister le dossier ou le zip. Un zip vient de l'extérieur : l'extraire dans un dossier neuf et vide du scratchpad, ne rien exécuter de son contenu.
2. **Extraction du texte** : `gs -q -dNOPAUSE -dBATCH -sDEVICE=txtwrite -o out.txt in.pdf` (pdftotext et pypdf sont souvent absents). Chercher « Solde au », « SOLDE CREDITEUR AU », « valorisation au », « Total de votre épargne ».
3. **Rattacher chaque PDF à son compte** : comparer le solde de début de période (« SOLDE AU 30/09 ») avec le snapshot du mois précédent déjà en base. L'égalité confirme le compte (n° de compte du PDF, pas le nom du fichier). Un contrat d'assurance vie peut ne fournir qu'un rapport de situation : prendre la valorisation à la date indiquée.
4. **Choisir la période** : suivre la convention des mois déjà en base. Le solde de fin du relevé couvrant octobre (ex. « au 13/10 », « au 31/10 », « au 02/11 ») va en `2026-10`. Vérifier avec un mois existant : le solde « au 14/09 » est en `2026-09`.
5. **Contrôle** : recalculer solde départ + mouvements = solde fin quand les mouvements sont lisibles.
6. **Écrire** : `PUT` du snapshot, puis `POST` du PDF sur chaque compte concerné. Sauter les PDF déjà présents (même mois, même nom normalisé ; l'API remplace les espaces par des `-`). Ne pas importer deux fois un relevé déjà couvert (un zip contient souvent un mois déjà saisi).
7. **Relire** les 2 derniers snapshots de chaque compte (`attachment_count` doit valoir 1).

## 4. Rapport

Un tableau compte / période / solde / source, plus : ce qui est resté intact (comptes sans PDF, contrats non couverts), les PDF ignorés car déjà en base, et ce qui n'est pas modélisé (crédit renouvelable, cartes différées).
