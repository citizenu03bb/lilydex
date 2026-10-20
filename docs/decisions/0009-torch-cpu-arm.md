# 0009 — torch pour processeur seul sur le serveur ARM

> **Statut :** en vigueur · **Date :** 2026-10-18

**Contexte.** Le contrôle d'édition et la porte énergie utilisent DINOv2, donc
torch. Le serveur est une instance ARM (aarch64) sans carte graphique
([fiche 0002](0002-oracle-cloud-serveur-fait-foi.md)).

**Options.**
1. La roue torch de PyPI : sur aarch64, elle apporte plusieurs Go de
   bibliothèques CUDA, inutiles sans carte Nvidia.
2. La roue de l'index « CPU » de PyTorch, choisie seulement pour aarch64 par
   `[tool.uv.sources]` dans `pyproject.toml`.

**Décision.** Option 2.

**Mesures sur le serveur.** Environnement Python de 912 Mo, modèle de 85 Mo ;
129 Mo de mémoire pour le service au repos, le modèle n'étant chargé qu'au
premier contrôle. La banque de la porte énergie monte à 1,2 Go en calculant
toute la collection (1 767 exemplaires en 2 min 44), puis 310 Mo et 2 s une
fois son cache à jour.

*Conditions de mesure : instance Oracle Cloud A1, 2 cœurs, 10 Go de mémoire, octobre 2026.*

**Conséquences.** L'instance AMD de 1 Go ne suffit pas. Les vecteurs étant
indexés par l'empreinte des images, un cache calculé sur le portable se
réutilise sur le serveur.

**Pour aller plus loin.** [Héberger Lilydex](../DEPLOYMENT.md#loption-vision).
