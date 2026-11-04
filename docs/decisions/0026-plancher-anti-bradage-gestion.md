# 0026 — Le plancher anti-bradage s'applique aussi aux prix fixés depuis la gestion

> **Statut :** en vigueur, complète la [décision 0021](0021-autonomie-maximale.md) · **Date :** 2026-11-04

**Contexte.** La [décision 0021](0021-autonomie-maximale.md) fixe qu'aucune vente
ne descend sous la valeur de référence diminuée d'une marge réglable
(`POKEPRICE_LOT_MAX_MARGIN`, 15 % par défaut, bornée de 0 à 50). L'outil de
lots (`scripts/pokeprice_lots.py`) et l'export vers les plateformes
(`src/pokeprice/marketplace_export.py`) contrôlaient déjà ce plancher, chacun
avec sa propre copie de la formule. En revanche, la publication depuis la
gestion (`src/pokeprice/listings.py` et `src/pokeprice/web/app.js`, en « Mode
lot » comme pour un prix unitaire fixé à la main) ne vérifiait que le plancher
absolu de 0,50 €.

**Options.**
1. Laisser la gestion au seul plancher de 0,50 € et compter sur l'export
   plateforme ou la vigilance de l'opérateur : une carte ou un lot publié en
   vitrine depuis la gestion peut alors partir sous 85 % de sa cote.
2. Bloquer toute publication manuelle d'une carte sans référence : trop rigide
   en gestion pour une carte atypique ou un lot dont le prix est saisi à la
   main avant cotation complète.
3. Définir la règle une seule fois dans `src/pokeprice/pricing.py` et
   l'appliquer partout : export, script de lots, publication en vitrine
   (`Listings.publish`) et interface de gestion, tout en gardant le plancher de
   0,50 € avec un message explicite lorsqu'aucune référence n'est connue (ou
   qu'elle vaut 0).

**Décision.** Option 3.
- `DEFAULT_LOT_MAX_MARGIN = 15`, `LOT_MAX_MARGIN_ENV = "POKEPRICE_LOT_MAX_MARGIN"`,
  `lot_max_margin()` et `lot_floor_cents(total_reference_cents)` sont définis
  une seule fois dans `src/pokeprice/pricing.py` et importés par
  `src/pokeprice/listings.py`, `src/pokeprice/marketplace_export.py` et
  `scripts/pokeprice_lots.py`.
- `Listings.publish` refuse tout lot dont le prix est inférieur à
  `max(FLOOR_CENTS, lot_floor_cents(somme des références))` et tout prix
  unitaire manuel inférieur à `max(FLOOR_CENTS, lot_floor_cents(référence))`.
- Une carte sans référence (ou à 0) garde le comportement actuel (`FLOOR_CENTS`
  = 0,50 €) à l'unité comme en lot sans référence, et le message de refus le
  précise explicitement.
- Une carte dont la variante est à vérifier prend pour référence la plus basse
  des cotes connues de ses variantes possibles et de sa référence enregistrée,
  jamais 0 : une carte à 100 € en holo et 30 € en standard ne descend pas sous
  le plancher calculé sur 30 €.
- L'interface de gestion (`src/pokeprice/web/app.js`) affiche le minimum
  autorisé avant validation dans le « Mode lot », le dialogue de création de
  lot, la publication directe de lot et le détail d'une fiche, et affiche un
  message explicite en cas de refus (textes dans `messages/fr.json` et
  `messages/en.json`).

**Conséquences.**
- Une seule définition du calcul de marge et d'arrondi au centime supérieur
  dans tout le dépôt.
- Aucun prix saisi depuis la gestion ne peut descendre sous la valeur de
  référence moins la marge configurée.
- Les annonces déjà en ligne dont la cote monte après publication restent
  relevées au plancher lors de l'export vers les plateformes.

**Preuve.** `tests/test_listings.py`, `tests/test_marketplace_export.py`,
`tests/test_pokeprice_lots.py`, `tests/test_web_client.py`.
