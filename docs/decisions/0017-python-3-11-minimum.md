# 0017 — Python 3.11 au minimum

> **Statut :** en vigueur · **Date :** 2026-10-27

**Contexte.** Dependabot signalait 49 alertes ouvertes, dont 41 sur Pillow
(4 critiques : débordements de tas au décodage d'images, injection
d'arguments vers Ghostscript). Lilydex ouvre avec Pillow chaque photo
téléversée. Les correctifs sont dans Pillow 13 et filelock 4.2, qui exigent
Python 3.11. Tant que le projet acceptait Python 3.10, le fichier `uv.lock`
gardait pour cette version Pillow 12.3 et filelock 4.1, toujours vulnérables.

**Options.**
1. Garder Python 3.10 et laisser ces versions dans le verrou, pour une version
   que personne n'utilise.
2. Exiger Python 3.11.

**Ce qui a été mesuré.** Le portable, le serveur et l'intégration continue
tournent en Python 3.13. Python 3.10 arrive en fin de vie en octobre 2026.
Avec Pillow 13, la suite de tests passe, option vision comprise.

**Décision.** Option 2 : `requires-python = ">=3.11"`.

**Conséquences.**
- Le verrou ne contient plus qu'une version de Pillow (13.0.0) et de filelock
  (4.2.4) ; les alertes correspondantes se ferment.
- Un poste en Python 3.10 doit installer une version plus récente ; `uv` le
  fait seul (`uv python install 3.13`).
