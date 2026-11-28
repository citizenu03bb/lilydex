# 0049 — Aucune carte ne sort du classeur pour juger son état : le recto suffit sous 10 €, le verso attend la vente

> **Statut :** en vigueur, modifie les décisions [0022](0022-agent-confirme-ou-demande-photo.md) et [0048](0048-serie-de-prises-de-pres.md), modifiée par la [décision 0055](0055-etat-note-par-une-personne.md) (l'état n'est plus confirmé par l'agent) · **Date :** 2026-11-21

**Contexte.** Après la série de prises de près sur les 60 cartes de la
vérification à l'aveugle, l'agent de revue confirmait 1 carte, redemandait une
photo pour 52 et en envoyait 6 « à examiner en main ». La lecture d'état
jugeait la photo « limitée » sur 57 cartes, d'abord parce qu'il n'y avait pas
de verso. L'agent traduisait « limitée » par « reprenez les coins » : il
redemandait une photo déjà prise, puis renvoyait la carte à une personne. Sur
les photos de près, la note d'état concordait pourtant avec celle du
propriétaire sur 13 des 19 cartes notées. Le propriétaire refuse les
manipulations répétées. Entre NM et EX, l'écart de prix d'une carte à moins de
10 € se compte en centimes. Un acheteur de carte de valeur demande de toute
façon une photo du verso.

**Options.**
1. **Exiger le verso de toutes les cartes** : chaque carte sortirait de sa
   pochette au moins une fois, sans rien changer au prix des cartes à bas prix.
2. **Recto seul sous 10 €, verso demandé au-dessus** : les cartes de valeur,
   qui méritent le plus de soin, seraient manipulées une fois de plus.
3. **Recto seul partout, verso des cartes de valeur photographié à la mise en
   vente**, quand la carte sort de toute façon.

**Décision.** Option 3.
- La lecture d'état passe au protocole `card-condition-v2` : la qualité ne
  juge que les photos fournies, et une face absente ne la baisse pas. Sur le
  recto seul, le modèle note ce que le recto montre, NM compris, et inscrit
  « Verso non vu » dans les limites. Le serveur ne retire plus un NM faute de
  verso. Il le retire encore sur des photos limitées, sur un recto
  inexploitable ou retouché, ou sur un verso retouché.
- Une évaluation faite sous un protocole plus ancien est relue.
- **Sous le seuil de valeur** (10 € par défaut), l'agent confirme l'état noté
  sur le recto.
- **Au seuil ou au-dessus**, sans verso exploitable, la variante et l'état
  restent provisoires. L'agent ne demande pas le verso. La photo prise pour
  l'annonce le fournit, et le passage suivant de l'agent tranche.
- **Personne n'examine une carte en main.** Ce que les photos ne tranchent
  pas, ou ce qu'une vue déjà reprise ne règle pas, reste tel qu'enregistré.
  Le rapport de l'agent range ces cartes dans `kept`, et la série les affiche
  sous « Restent en l'état ».
- Deux photos de la même carte, prises coup sur coup, lancent leurs relectures
  l'une après l'autre, au lieu de faire échouer la seconde.

**Conséquences.**
- Un état NM peut être confirmé sans que le verso ait été vu. Sous 10 €, une
  usure du verso coûte au plus quelques centimes et un échange avec
  l'acheteur.
- Une carte de valeur n'a pas de prix automatique avant sa mise en vente.
- Les cartes « en l'état » gardent un état non confirmé. Elles ne repassent
  devant personne.
- Le seuil de la vérification à l'aveugle (aucune variante fausse, borne
  haute de l'erreur d'état sous 10 %) reste à mesurer sur le protocole v2
  avant `--apply`.

**Preuve.** `tests/test_condition_assessment.py`, `tests/test_agent_review.py`,
`tests/test_closeups.py`.
