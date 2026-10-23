# 0016 — Le guide des prix officiel de Cardmarket complète TCGdex

> **Statut :** en vigueur · **Date :** 2026-10-23

**Contexte.** TCGdex donne la cote Cardmarket de la plupart des cartes, mais
pas de toutes : sur 47 cartes confirmées et liées au catalogue, aucune n'avait
de prix. Pour 18 d'entre elles, TCGdex connaissait le produit Cardmarket sans
sa cote ; pour les autres, surtout des Zarbi DP et des cartes anciennes, il
ne connaissait pas le produit. L'API Cardmarket est fermée aux nouveaux
utilisateurs et le site n'est pas aspiré.

**Options.**
1. Laisser ces prix inconnus, ou les saisir à la main depuis les offres.
2. Utiliser les deux fichiers que Cardmarket publie librement chaque jour :
   le guide des prix (tendance, moyennes, colonnes holo) et la liste des cartes
   (produit, extension, nom).

**Ce qui a été mesuré.** Sur ces 47 cartes, 45 trouvent leur cote : les 18
dont TCGdex donne le produit, et 27 retrouvées dans la même extension par leur
nom anglais et les noms de leurs attaques et pouvoirs. Cardmarket distingue
ainsi les cartes de même nom (« Unown [L] Lv.18 [LINK | Hidden Power] »). Deux
cartes de produits promotionnels restent sans extension connue.

**Décision.** Option 2. Le guide complète seulement une carte que TCGdex laisse
sans cote ; une cote TCGdex n'est jamais remplacée. Le produit vient de TCGdex
quand il le donne ; sinon, seule une correspondance unique dans l'extension
compte. Le relevé garde sa provenance : source « Cardmarket · guide des prix »,
date du fichier, produit et méthode de correspondance. Les fichiers sont gardés
un jour dans le dossier de la collection, hors des sauvegardes.

**Conséquences.**
- Ces cotes ont la même place qu'une cote TCGdex : tendance, valeur prudente,
  valeur en jeu et file « À examiner » ; ce ne sont pas des valeurs manuelles.
- Une erreur de correspondance donnerait la cote d'une autre carte : elle est
  visible dans le relevé (produit et nom Cardmarket) et se signale comme un
  produit incorrect.
- Trouver l'extension d'une série demande de lire quelques cartes TCGdex de
  cette série, une seule fois.
