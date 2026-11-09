# 0041 — Les énergies en vrac sont offertes dans les lots, sans changer de tranche postale

> **Statut :** en vigueur · **Date :** 2026-11-09

**Contexte.** La [fiche 0015](0015-energies-de-base-en-vrac.md) classe les
énergies de base confirmées en vrac, pour une vente en lot. Or l'outil de lots
écartait toute carte sans prix prudent : 131 énergies restaient sans débouché.
Une énergie de base ne vaut presque rien à l'unité ; un lot d'énergies seul
coûterait plus en port et en temps qu'il ne rapporte.

**Options.**
1. Un lot « vrac énergies » à prix fixe : un prix inventé, à surveiller, et un
   envoi de plus.
2. Des énergies offertes en bonus dans les lots de doublons, en nombre libre :
   chaque énergie pèse 2 g, assez pour faire changer de tranche postale (lettre
   suivie ≤ 20 g à 2,02 €, ≤ 100 g à 3,60 €, Colissimo ≤ 250 g à 5,49 €).
3. Des énergies offertes, au plus le nombre qui tient dans la tranche postale
   du lot sans bonus.

**Décision.** Option 3. L'outil de lots ajoute à chaque lot composé des
énergies en vrac tant que les frais de port du lot, calculés comme la
réservation les calcule (`shipping_quote`, poids des cartes et de l'emballage,
recommandé dès le seuil), restent ceux du lot sans bonus. Il en met au plus
10 par lot, pour en garder pour les lots suivants. Le prix du lot et son
plancher anti-bradage ne changent pas : ils portent sur les cartes cotées.
Le titre annonce « + N énergies offertes ».

Une énergie entre en bonus si elle est en vrac (fiche 0015), disponible, prise
dans aucun brouillon ni lot en ligne, et publiable à prix fixé à la main.
L'outil les prend dans l'ordre du classeur, pour que la préparation se fasse
d'une page à l'autre.

**Conséquences.**
- Le client ne paie pas les énergies, ni en prix ni en port, quand il achète un
  lot seul.
- Plusieurs lots achetés ensemble peuvent passer ensemble une tranche que
  chacun respectait : le port compte le poids réel, bonus compris.
- Un lot qui remplit déjà sa tranche (5 cartes pour 20 g) ne reçoit rien.
- Aucune énergie n'est gardée dans l'album : la fiche 0015 les destine à la
  vente.
- Le thème « Lot Vrac Énergies de Base » reste sans usage : les énergies n'ont
  pas de référence catalogue et n'entrent pas dans les lots thématiques.
