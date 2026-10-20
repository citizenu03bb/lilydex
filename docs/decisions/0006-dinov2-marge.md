# 0006 — DINOv2 plutôt que CLIP, avec une marge de 0,05

> **Statut :** en vigueur · **Date :** 2026-10-13

**Contexte.** Un contrôle de l'édition indépendant du texte lu demandait de
comparer la photo aux images des éditions de même nom, sans entraîner de
modèle.

**Options.**
1. CLIP ViT-B/32 : bonne édition en tête 13/27, parmi les 3 premières 14/27.
2. DINOv2-small : 19/27 en tête, 24/27 parmi les 3 premières.

Puis, pour DINOv2, l'écart sous lequel deux éditions sont jugées trop proches
pour trancher :

| Marge | Fausses alertes sur 27 vraies éditions | Éditions voisines signalées sur 26 |
|---|---|---|
| 0,02 | 3 | 17 |
| 0,05 | 1 | 14 |
| 0,08 | 0 | 11 |

**Décision.** DINOv2-small, utilisé tel quel, avec une marge de 0,05 : une
seule fausse alerte, et plus de la moitié des éditions voisines signalées.

**Conséquences.**
- Sous la marge, le contrôle se déclare indécis plutôt que de trancher.
- Les réimpressions à l'illustration identique restent indécidables par
  l'image.
- Le calcul tourne sur processeur, environ une seconde par carte une fois les
  images en cache.

**Preuve.** [Banc d'essai](../BANC-RECONNAISSANCE.md#le-contrôle-dédition-par-limage).
