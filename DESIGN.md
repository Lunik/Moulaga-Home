# Principes de design

## Formulaires responsives

Tout formulaire de l'application, qu'il serve a creer, modifier, configurer ou confirmer une
donnee, doit s'ouvrir dans une surface dediee. Les formulaires integres directement dans une page
ne sont pas autorises.

- **Desktop** : afficher le formulaire dans une modale au-dessus de la page courante afin de
  conserver le contexte de navigation.
- **Mobile** : afficher le meme formulaire dans une vue pleine page, sans fond de modale, avec une
  action de retour clairement visible dans l'en-tete.

Le composant et la logique metier du formulaire doivent rester identiques dans les deux versions :
seule leur presentation change selon la taille de l'ecran. Les champs, la validation, les erreurs et
les actions de confirmation ou d'annulation doivent offrir le meme comportement.

La fermeture de la modale, le retour mobile et l'annulation doivent ramener l'utilisateur au
contexte depuis lequel le formulaire a ete ouvert. Si le formulaire contient des modifications non
enregistrees, ces actions doivent demander confirmation avant de les abandonner.
