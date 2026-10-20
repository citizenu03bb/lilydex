# 0010 — La porte énergie, avec une marge de 0,10

> **Statut :** en vigueur · **Date :** 2026-10-16

**Contexte.** Environ une pochette de classeur sur huit est une énergie de
base : une carte sans valeur, qui coûtait un appel à Gemini comme les autres.

**Options.**
1. Tout lire avec Gemini.
2. Reconnaître les énergies de base par l'image, avant Gemini, avec la
   collection elle-même comme banque : énergies de base en références, toutes
   les autres cartes en contre-exemples, énergies spéciales comprises.

**Décision.** Option 2, dans le pipeline d'albums (`scan --energy-gate`). Une
pochette passe la porte seulement si l'énergie de base la plus proche devance
toute autre carte d'au moins 0,10, et si la banque compte au moins 20
références. Elle arrive « Énergie de base », type proposé à confirmer, jamais
confirmée ni cotée.

**Mesure.** Carte par carte, chaque carte hors de sa propre banque : 166
énergies de base sur 166 admises, et une seule autre carte admise à tort sur
1 601, la seule Double Énergie Incolore de la collection. Sur les pochettes de
six classeurs, une Double Énergie Incolore passait encore à la marge de 0,08,
d'où 0,10.

**Conséquences.** Une énergie spéciale encore absente de la collection peut
passer la porte ; elle reste alors à examiner. Les étiquettes viennent des noms
enregistrés : une carte mal nommée fausse la banque.

**Preuve.** [Banc d'essai](../BANC-RECONNAISSANCE.md#la-porte-énergie),
`scripts/eval_energy_gate.py`.
