# 0023 — La cotation en lot retient une cote qu'un marché instable ferait bondir

> **Statut :** en vigueur, applique le plancher anti-bradage de la [décision 0021](0021-autonomie-maximale.md) · **Date :** 2026-11-03

**Contexte.** La cote de référence est la tendance Cardmarket. Pour une carte
peu échangée, une ou deux ventes isolées la déplacent : un produit mêle
1re édition et édition illimitée, toutes langues et tous états. L'essai de la
cotation matinale sur une copie de la collection a recoté 1 573 cartes ; la
cote totale a baissé de 11 %, et 722 cartes portaient l'avertissement
« marché instable ». Une commune passait de 0,17 € à 7,35 €, une reverse peu
commune de 1,84 € à 39,63 €, deux rares anciennes perdaient de 60 à 80 %. Le
plancher anti-bradage se calcule sur cette cote : une baisse à tort ferait
vendre sous la valeur.

**Options.**
1. Activer la cotation matinale telle quelle et traiter les avertissements au
   fil de l'eau : la cote bouge chaque matin sans contrôle.
2. Retenir la plus basse de la tendance et de la moyenne sur 30 jours : une
   baisse à tort passe quand même, et abaisse le plancher.
3. En lot, garder la cote en place quand un marché instable la déplacerait
   fortement, et signaler la carte pour vérification.

**Décision.** Option 3.
- La règle ne vaut que pour une cotation en lot (`prices`, avec ou sans
  `--from-guide`). Un relevé fait à la main sur une fiche s'applique toujours.
- La cote est retenue si la carte a déjà une cote, si sa variante ne change
  pas, si l'écart atteint le seuil des variations notables (`--threshold`,
  20 % par défaut, carte de 2 € et plus) et si le marché est instable : les
  moyennes sur 1, 7 et 30 jours et la tendance diffèrent du simple au double.
- Le relevé retenu s'écrit dans l'historique (`price-held`), sans changer la
  fiche ni sa valorisation. La carte passe en « À vérifier » avec la cote que
  la tendance proposerait.
- La revue se termine par un relevé à la main, un prix fixé à la main ou un
  relevé en lot que la règle laisse passer.

**Conséquences.**
- Un marché stable continue d'être recoté seul ; la hausse d'une carte
  vraiment recherchée passe.
- Une carte dont le marché reste instable garde une cote ancienne tant que
  personne ne la vérifie, peut-être fausse elle aussi.
- Un premier prix, sans cote antérieure, entre sans contrôle.

**Preuve.** `tests/test_prices_bulk.py`.
