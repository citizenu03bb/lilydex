# 0022 — L'agent confirme sur preuves concordantes, sinon il demande une photo

> **Statut :** en vigueur, complète la [décision 0021](0021-autonomie-maximale.md) · **Date :** 2026-11-03

**Contexte.** Un prix automatique exige une variante et un état confirmés.
Jusqu'ici, une personne confirmait les deux, fiche par fiche, même pour une
carte à 0,20 €. Lily a très peu de temps. Les contrôles (finition, édition
par l'image, état) existent mais restent des propositions.

**Options.**
1. Publier des annonces « non vérifiées » : rejeté par la propriétaire.
2. Abaisser les seuils de sécurité de la [décision 0007](0007-seuils-confort-securite.md) : rejeté.
3. Laisser un agent confirmer par le même chemin d'écriture qu'une personne,
   quand toutes les preuves concordent, et sinon demander une prise de vue.

**Décision.** Option 3.
- L'agent (`agent:revue`) confirme la variante si la lecture de finition est
  « proposée » (la règle de la [décision 0008](0008-reverses-examen-physique.md)
  s'applique d'abord), sur une photo de qualité suffisante, sans désaccord de
  finition, de tampon ou de langue, et si le contrôle d'édition par l'image
  désigne l'édition de la fiche avec au moins la marge de la
  [décision 0006](0006-dinov2-marge.md).
- Il confirme l'état proposé si la photo du recto est exploitable et de
  qualité suffisante. Les règles du serveur sur NM restent en place.
- Au seuil de valeur (10 € par défaut) ou sans valeur prudente connue, il
  exige aussi un verso exploitable.
- La variante et l'état sont confirmés ensemble, ou pas du tout.
- Sinon, il demande une photo : recto net, verso, reflet holo ou coins de
  près. Une vue déjà reprise sans succès n'est pas redemandée : la carte va à
  une personne.

**Conséquences.**
- Une carte simple bien photographiée ne demande plus aucune décision humaine
  pour son prix (deux de moins par carte).
- Chaque confirmation porte l'auteur, les lectures, la marge et le passage.
  Un passage entier s'annule.
- Une finition attestée par l'agent ne compte pas comme observation humaine
  pour le référentiel des impressions.
- La fiabilité des états proposés sur de vraies cartes n'est pas mesurée :
  l'annulation et les journaux servent de filet.

**Preuve.** `tests/test_agent_review.py`.
