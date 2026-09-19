# Conception multi-utilisateur

Ce document fixe les regles retenues pour rendre Moulaga multi-utilisateur. Il precede
l'implementation et sert de contrat : toute divergence constatee dans le code doit etre corrigee
ici ou la.

## Perimetre

Une instance de Moulaga represente **un seul foyer**. Le multi-foyer est abandonne : il n'est ni
selectionnable, ni creable, ni expose dans l'interface.

Une personne du foyer est un **profil**. Chaque profil gere ses ressources comme s'il etait seul sur
l'instance, et peut partager certaines d'entre elles avec les autres profils.

## Ecran de selection

Au demarrage, l'application ouvre un ecran de selection de profil.

- une tuile par profil, avec nom et couleur ou avatar ;
- une tuile de creation de profil ;
- aucun profil invite ;
- un acces a la gestion des profils ;
- un changement de profil ramene a cet ecran.

Au premier demarrage, l'ecran devient un onboarding qui cree le premier profil. Ce profil est
administrateur de l'instance.

## Les trois natures de propriete

C'est la regle centrale du modele. Chaque donnee appartient a une et une seule de ces trois
categories.

### 1. Flux financiers : la propriete vient du compte

Un compte possede un ou plusieurs titulaires. **Tout ce qui transite par un compte herite
automatiquement et exclusivement des titulaires de ce compte** :

- series recurrentes de revenu et de depense ;
- echeances et projections ;
- soldes releves ;
- positions et contributions portees par le compte.

Une serie recurrente ne porte donc aucune propriete propre. Le formulaire n'affiche pas de
selecteur de personnes, mais une information deduite et non modifiable, par exemple
« Partage avec Bob, car rattache au compte joint ». Changer le compte d'une serie change son
partage.

Cette regle est totale : `RecurringSeries.account_id` est non nullable, donc aucun flux ne peut se
retrouver sans proprietaire.

Le geste bancaire reel exprime l'intention : un salaire verse sur un compte joint appartient au
foyer, un salaire verse sur un compte personnel reste personnel.

### 2. Ressources de personne : un seul profil, jamais partagees

Certaines donnees decrivent une personne et non de l'argent. Elles appartiennent a exactement un
profil et ne peuvent pas etre partagees :

- contrats de travail ;
- bulletins de paie ;
- profil de retraite et projections associees.

C'est aujourd'hui le seul endroit ou l'application est structurellement mono-utilisateur :
`PensionProfile` est un singleton, avec une seule date de naissance et un seul age de depart pour
toute l'instance. Un foyer de deux adultes ne peut donc pas y modeliser deux carrieres ni deux
retraites.

### 3. Biens et dettes : proprietaires explicites

Un bien immobilier, un actif ou une dette ne transite pas par un compte. Il porte donc sa propre
liste de proprietaires.

Le compte preleve pour rembourser un credit ne determine pas qui porte la dette :

- la **mensualite recurrente** herite du compte debite ;
- le **capital restant du** est reparti entre les debiteurs declares sur la dette.

Une personne peut ainsi rembourser temporairement depuis son compte personnel une dette detenue a
deux, sans que la propriete de la dette change.

## Repartition

La repartition est **egalitaire** entre les proprietaires d'une ressource :

- deux proprietaires : moitie chacun ;
- trois proprietaires : un tiers chacun ;
- zero proprietaire : interdit, une ressource en a toujours au moins un.

L'interface ne propose pas de pourcentages personnalises. En revanche, la table de liaison stocke un
poids par proprietaire, fixe a la meme valeur pour tous. Ce champ n'apparait nulle part dans
l'interface : il evite une migration sur des donnees financieres le jour ou une repartition inegale
sera souhaitee.

### Arrondis

Les montants sont stockes avec 2 decimales. Une division non exacte ne doit jamais faire disparaitre
de centimes : le reliquat est attribue selon un ordre stable des proprietaires, par identifiant
croissant.

Cent euros partages entre trois profils donnent donc 33,34 €, 33,33 € et 33,33 €. L'ordre doit etre
deterministe afin que les montants ne changent pas entre deux chargements.

## Enveloppes budgetaires : vue foyer

Les enveloppes sont portees par la **categorie**, sous forme d'un arbre hierarchique dont le budget
d'un parent est synchronise sur la somme de ses enfants. Une categorie est transverse a plusieurs
comptes aux proprietaires differents.

Les enveloppes ne sont donc **pas divisees** et restent affichees en montants totaux : une enveloppe
est une decision commune du foyer, pas un actif possede.

Cela preserve les invariants de l'arbre budgetaire et evite un concept peu comprehensible du type
« mon tiers de l'enveloppe courses ».

## Quote-part des biens deja partages

`RealEstateAsset.ownership_share` existe deja et reduit la contribution du bien au patrimoine net.
Il est redefini comme **la part du foyer dans le bien**, face a des coproprietaires exterieurs
(indivision, SCI, famille).

Le partage entre profils s'applique **ensuite, sur cette part seulement**. Un bien de 300 000 €
detenu a 50 % par le foyer et partage entre deux profils vaut 75 000 € pour chacun.

Sans cette regle, la valeur serait divisee deux fois et le patrimoine net deviendrait silencieusement
faux.

## Absence d'historique

Le partage n'est pas historise. Il n'existe ni date d'effet, ni ancienne repartition conservee.

Quand les proprietaires changent :

- le nouveau partage prend effet immediatement ;
- toutes les vues sont recalculees, y compris sur les periodes passees ;
- aucune repartition anterieure n'est conservee.

La consequence doit etre assumee et annoncee : si une personne rejoint un compte detenu depuis dix
ans, l'historique des soldes et la courbe de patrimoine net de l'ancien titulaire sont divises
retroactivement. L'interface avertit avant validation plutot que de laisser l'utilisateur decouvrir
une courbe modifiee.

## Affichage

Le montant principal du tableau de bord est toujours **la part du profil actif**. Le montant total
reste visible des qu'une ressource est partagee.

Ressource partagee :

> **Votre part : 2 000 €**
> Solde total : 4 000 € · partage avec Bob

Ressource personnelle :

> **Solde : 2 000 €**
> Personnel

Avant enregistrement, les formulaires resument la repartition : montant total, part du profil actif,
nombre et identite des proprietaires.

Les indicateurs calcules sur la part du profil actif sont le solde total, les revenus et depenses
recurrents, le disponible apres recurrents, les projections sur douze mois, le patrimoine net et les
dettes. Les enveloppes budgetaires font exception et restent en vue foyer.

## Transferts

Les transferts ne sont ni des revenus ni des depenses et restent exclus des indicateurs budgetaires.
Ils deplacent en revanche la propriete de la valeur.

Un transfert de 1 000 € d'un compte personnel vers un compte joint partage a deux retire 1 000 € au
compte personnel, puis attribue 500 € a chacun des deux titulaires du compte joint. C'est le
comportement attendu d'une mise en commun reelle.

## Confidentialite et autorisations

### PIN facultatif

Chaque profil possede un nom, un avatar ou une couleur, un role, un etat actif ou archive et un PIN
facultatif stocke sous forme de hash.

- profil sans PIN : ouverture immediate ;
- profil protege : saisie du PIN ;
- chaque profil cree, modifie ou retire son propre PIN ;
- un administrateur peut uniquement supprimer le PIN d'un autre profil ;
- verrouillage manuel disponible ;
- retour a la selection apres redemarrage du navigateur ;
- verrouillage automatique des profils proteges apres inactivite.

Le backend emet une session pour le profil selectionne. **Le filtrage ne doit jamais reposer
uniquement sur le frontend** : chaque route verifie la session active et restreint les ressources.

Limite a enoncer honnetement : un administrateur peut supprimer un PIN, donc acceder aux donnees
des autres. Le PIN protege la confidentialite entre membres de bonne foi, pas contre l'administrateur
de l'instance. L'interface ne doit pas promettre davantage.

### Droits

Un membre gere ses comptes personnels, cree des comptes partages, consulte et modifie les ressources
dont il est proprietaire, gere les series recurrentes des comptes correspondants ainsi que ses biens
et dettes. Il ne voit jamais les ressources personnelles des autres.

Un administrateur cree, archive et restaure des profils, retire leur PIN si necessaire et gere les
parametres de l'instance. Le role administrateur donne des droits d'administration, **pas un droit
de lecture financiere universel**.

Tout coproprietaire peut modifier une ressource partagee. Il n'y a pas de circuit d'approbation,
trop lourd pour une application familiale.

### Retrait et suppression

Retirer une personne d'un compte partage exige qu'au moins un titulaire subsiste. Le retrait
recalcule immediatement les quotes-parts, retire l'acces au compte et a ses pieces jointes, et les
series recurrentes suivent automatiquement les nouveaux titulaires.

Un profil ne peut pas etre supprime tant qu'il detient des ressources. Le parcours presente un
inventaire a resoudre : comptes personnels a transferer ou archiver, comptes partages dont le
retirer, biens et dettes a transferer ou archiver, pieces jointes concernees. Une fois l'inventaire
resolu, le profil est archive plutot que supprime physiquement.

## Pieces jointes

Une piece jointe reste stockee sous `MOULAGA_DATA_DIR/attached` avec un chemin hache, et n'est
accessible qu'aux proprietaires de la ressource qui la porte. Le controle est realise cote backend,
au moment du telechargement.

## Consequences sur le modele existant

Le modele actuel ne peut pas etre etendu tel quel.

- `households`, `household_members` et `shared_account_links` supposent plusieurs foyers et
  partagent un compte avec *un foyer* plutot qu'avec *des personnes*. `SharedAccountLink` et sa
  permission `view|edit` sont remplaces par une relation compte ↔ profil.
- `household_members` sert de base au futur profil, car `GoalContribution.member_id` y pointe deja.
- `Account.name` est unique globalement : deux profils ne pourraient pas avoir chacun un « Livret A ».
  Cette contrainte doit etre relachee.
- `PensionProfile` est un singleton et doit devenir propre a un profil.
- `WorkContract` et `PaySlip` doivent etre rattaches a un profil.
- `RealEstateAsset.ownership_share` change de signification sans changer de type.

Le foyer peut rester un singleton technique pour limiter les migrations risquees, mais disparait des
parcours utilisateur.

## Invariants

1. Une instance contient exactement un foyer.
2. Toute ressource possede au moins un proprietaire.
3. Tout flux financier possede exactement un compte de rattachement.
4. Un flux herite exclusivement des proprietaires actuels de son compte.
5. Une ressource de personne appartient a un seul profil et ne se partage pas.
6. Un bien et une dette portent leurs propres proprietaires.
7. Une categorie ne possede pas de proprietaires.
8. Une ressource partagee est stockee une seule fois et n'est jamais comptee deux fois.
9. La part individuelle est le montant total divise egalement entre les proprietaires.
10. Les centimes residuels sont attribues selon un ordre stable.
11. Le tableau de bord ne compte que la part du profil actif ; les enveloppes restent en vue foyer.
12. Modifier un partage recalcule immediatement toutes les vues, sans historique.
13. Les transferts deplacent la propriete de la valeur sans creer de revenu ni de depense.
14. La visibilite et la quote-part sont calculees cote backend.

## Decoupage

1. **Profils et session** : ecran de selection, creation, changement de profil, PIN facultatif,
   session backend, migration de toutes les donnees existantes vers le premier profil.
2. **Ressources de personne** : rendre le profil de retraite, les contrats de travail et les
   bulletins de paie propres a un profil. C'est le seul domaine structurellement mono-utilisateur
   aujourd'hui, et le plus utile a livrer tot.
3. **Comptes partages** : proprietaires multiples, heritage automatique des series recurrentes,
   levee de l'unicite des noms de comptes.
4. **Biens et dettes** : proprietaires explicites et clarification de `ownership_share`.
5. **Restitution** : quote-part et montant total affiches partout, projections et patrimoine net
   adaptes, enveloppes conservees en vue foyer.
6. **Seed de demonstration** : deux carrieres, deux retraites, un compte joint, un bien et une dette
   partages, ainsi qu'un cas de repartition a trois pour couvrir les arrondis.

## Principe directeur

Le compte determine a qui appartient l'argent. La personne determine a qui appartient sa carriere.
Une donnee est stockee une seule fois, sa propriete est explicite, et la vue personnelle de chaque
profil est calculee automatiquement.
