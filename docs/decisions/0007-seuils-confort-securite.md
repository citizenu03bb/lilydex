# 0007 — Seuils de confort et seuils de sécurité, jugés sur le pire de deux passages

> **Statut :** en vigueur · **Date :** 2026-10-13

**Contexte.** Le banc d'essai sert de test de non-régression. Mais Gemini
n'est pas déterministe : sur quatre passages, le numéro varie de 23 à 25/30 et
l'édition de 18 à 22/29. Un seuil fixé sur un bon passage échoue au hasard ;
un seuil trop bas ne protège de rien.

**Options.**
1. Un passage, seuils au meilleur score observé.
2. Plusieurs passages, et des seuils différents selon le coût d'une erreur.

**Décision.** Option 2.
- Le banc fait deux passages réels ; chaque mesure est jugée sur **le pire**.
- **Seuils de confort** (numéro, édition) : au plus bas observé. Une édition
  manquée renvoie la carte « À vérifier » : elle coûte du temps, pas d'argent.
- **Seuils de sécurité** (proposition de variante fausse au-dessus du seuil de
  valeur, holo ou mate, tampon) : ils ne baissent jamais. Aucune proposition
  fausse n'est tolérée quand l'enjeu dépasse le seuil.

**Conséquences.** Un changement de prompt, de règle ou de modèle qui dégrade
la sécurité fait échouer le banc. Les seuils sont stockés comme des parts, pour
qu'un jeu de vérité reconstruit garde la même exigence.

**Preuve.** [Banc d'essai](../BANC-RECONNAISSANCE.md#le-banc-dans-lapplication--lecture-à-la-saisie).
