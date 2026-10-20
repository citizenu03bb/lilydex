# 0005 — Langue du texte : un contrôle de cohérence plutôt que Tesseract

> **Statut :** en vigueur · **Date :** 2026-10-14

**Contexte.** Un nom identique d'une langue à l'autre (Pikachu) ne permet pas
au catalogue de distinguer une carte anglaise d'une carte française. Il
fallait un contrôle de la langue.

**Options.**
1. Tesseract (fra, eng, ita, deu, spa) comme second lecteur, indépendant de
   Gemini.
2. Demander à Gemini, dans la lecture de la finition déjà faite à chaque
   saisie, la langue du texte imprimé hors nom, et la comparer à la fiche.

**Mesure** (31 cartes, deux passages). Tesseract trouve 28 langues justes sur
31, envoie 3 cartes françaises en examen sans raison et ne rattrape aucune
erreur de Gemini. Le contrôle de cohérence trouve 31 langues justes sur 31,
sans fausse alerte.

**Décision.** Option 2.

**Conséquences.**
- Aucune dépendance système ; environ 100 jetons de plus par carte.
- Le contrôle n'est pas indépendant : même modèle, autre question.
- Aucune carte japonaise au banc : rien n'est établi pour le japonais.

**Preuve.** [Banc d'essai](../BANC-RECONNAISSANCE.md#la-langue--tesseract-face-au-contrôle-de-cohérence).
