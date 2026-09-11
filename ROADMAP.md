# Roadmap fonctionnelle

Moulaga se concentre sur trois sources locales et explicites :

- les releves mensuels pour les soldes de comptes et les liquidites ;
- les series recurrentes pour les revenus, depenses, enveloppes et projections ;
- les valorisations dediees pour les actifs, biens immobiliers et dettes.

## Socle

- [x] Demarrage autonome avec FastAPI, React et SQLite.
- [x] Sauvegarde automatique avant toute migration structurelle.
- [x] Themes, formats de date et styles de navigation.
- [x] PWA avec prechargement des vues de synthese.
- [x] Seed de demonstration synthetique et isolee.

## Comptes et releves

- [x] Creation, edition, archivage et restauration des comptes.
- [x] Groupement par etablissement et entite regionale.
- [x] Releves mensuels saisis ou importes en TSV.
- [x] Pieces jointes locales des releves dans des chemins haches.
- [x] Historique des soldes par compte et par etablissement.
- [x] Projection des livrets a partir des soldes mensuels et du taux configure.
- [x] Transfert du dernier solde releve lors de l'archivage.

## Budget recurrent

- [x] Cycle budgetaire configurable.
- [x] CRUD manuel des series recurrentes et de leurs statuts.
- [x] Frequences hebdomadaire, mensuelle, trimestrielle et annuelle.
- [x] Revenus, depenses et solde previsionnel du cycle.
- [x] Projection mensuelle sur douze mois.
- [x] Cashflow Sankey alimente par les comptes sources et categories recurrentes.
- [x] Enveloppes hierarchiques, plafonds et budget disponible.
- [x] Exclusion des virements entre comptes des indicateurs budgetaires.
- [x] Pieces jointes locales des series recurrentes.

## Patrimoine

- [x] Positions, contributions, allocation et performance.
- [x] Dettes et association aux echeances recurrentes.
- [x] Biens immobiliers, quote-parts et dettes associees.
- [x] Patrimoine net courant et historique.
- [x] Absence de double comptage des comptes d'investissement.

## Foyer

- [x] Profils locaux et roles.
- [x] Comptes partages avec dernier solde releve.
- [x] Objectifs et contributions communes.

## Retrait du registre d'operations - 2026-09-10

- [x] Solde historique materialise dans un releve avant migration.
- [x] Anciennes tables et pieces jointes retirees apres sauvegarde.
- [x] Routes, DTO, types, cache PWA et ecrans associes retires.
- [x] Seed reconstruite sans donnees d'operations unitaires.
- [x] Dashboard et budget reconnectes aux releves et series recurrentes.
