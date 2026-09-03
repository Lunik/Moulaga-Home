# Roadmap fonctionnelle

Cette roadmap conserve la correspondance unitaire avec les 26 captures de reference. Les doublons
visuels 21/22 et 1/26 partagent volontairement la meme implementation.

## Epic d'audit fonctionnel iteratif

L'audit fonctionnel doit partir des features structurantes et remonter progressivement vers les
features niche. Chaque palier n'est audite en profondeur que si le precedent est juge
suffisamment sain.

Constat attendu a chaque etape :

- OK
- ecart
- arbitrage produit

Mode operatoire :

- auditer un palier a la fois ;
- extraire les ecarts avant de passer au suivant ;
- transformer immediatement les ecarts en tickets actionnables ;
- garder les features niche et les garanties specifiques pour la fin.

### Paliers d'audit

1. **Socle applicatif**
   - demarrage app ;
   - persistance SQLite ;
   - preferences globales ;
   - navigation principale ;
   - sante generale backend/frontend.
2. **Donnees coeur**
   - comptes ;
   - categories ;
   - transactions ;
   - pagination du registre ;
   - creation, edition et suppression.
3. **Lecture metier de base**
   - tableau de bord ;
   - soldes ;
   - revenus et depenses ;
   - derniers mouvements ;
   - coherence globale des chiffres.
4. **Pilotage budgetaire**
   - cycle budgetaire ;
   - enveloppes ;
   - cashflow ;
   - hierarchie des categories ;
   - ventilation des depenses.
5. **Automatisation locale**
   - regles ;
   - boite de categorisation ;
   - suggestions locales ;
   - seuils et modes `off`, `suggest`, `auto`.
6. **Recurrents**
   - detection ;
   - series ;
   - changements ;
   - previsions.
7. **Patrimoine**
   - actifs ;
   - dettes ;
   - contributions ;
   - allocation ;
   - performance ;
   - absence de double comptage.
8. **Partage local**
   - foyer ;
   - roles ;
   - comptes partages ;
   - objectifs communs.
9. **Features niche et garanties**
   - identites marchandes locales ;
   - snapshots avances ;
   - migration Banque_v3 ;
   - atomicite et idempotence ;
   - confidentialite.

## Phase 0 - Fondations

- [x] 12. Preferences : theme, langue/locale, date et style de navigation.
- [x] 13. Navigation principale responsive.
- [x] Versionnement et sauvegarde automatique du schema SQLite.
- [x] Registre pagine et mutations completes des transactions.

## Phase 1 - Budget et comptes

- [x] 4. Enveloppes budgetaires par cycle.
- [x] 7. Jour de paie, cycle budgetaire et identites marchandes locales.
- [x] 9. Categories, couleurs, archivage et sous-categories.
- [x] 17. Creation, edition, archivage et filtres des comptes.
- [x] 19. Vue multi-comptes et poches virtuelles sans double comptage.
- [x] 20. Detail compte, historique et transactions contextualisees.
- [x] 21. Releves mensuels idempotents.
- [x] 22. Releves mensuels disponibles uniformement sur chaque compte.
- [x] 23. Apercu complet du cycle budgetaire.
- [x] 24. Cashflow Sankey en vue cycle ou annee.
- [x] 25. Ventilation hierarchique et volumes de transactions.

## Phase 2 - Automatisation locale

- [x] 1. Detection et journal des changements recurrents.
- [x] 2. Echeancier previsionnel multi-mois.
- [x] 3. CRUD et statuts des series recurrentes.
- [x] 6. Boite de categorisation, affectation et traitement groupe.
- [x] 8. Suggestions locales, modes suggestion/auto et seuil de confiance.
- [x] 10. Regles deterministes par beneficiaire ou mot-cle.
- [x] 26. Meme detection de changements que le point 1.

## Phase 3 - Patrimoine

- [x] 5. Allocation epargne/investissement et contributions.
- [x] 14. Tableau de bord du patrimoine net et historique.
- [x] 15. Dettes, mensualites et progression.
- [x] 16. Positions, recherche, filtres et valorisation.
- [x] 18. Historique persistant des plus-values et moins-values.

## Phase 4 - Partage local

- [x] 11. Foyers, profils locaux, roles, comptes et objectifs partages.

## Phase 5 - Validation

- [x] Tests backend des migrations, calculs, autorisations et CRUD.
- [x] Build et verification TypeScript du frontend.
- [x] Validation visuelle desktop et mobile avec une base synthetique separee.
- [x] Validation des themes clair/sombre et des navigations sidebar/topbar.
- [x] Parcours transaction complet : creation, persistance et suppression confirmee.
