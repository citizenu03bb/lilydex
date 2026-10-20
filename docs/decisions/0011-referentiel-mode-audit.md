# 0011 — Le référentiel des impressions en mode audit

> **Statut :** en vigueur · **Date :** 2026-10-13

**Contexte.** Le prix d'une carte dépend de l'impression exacte et du produit
Cardmarket qui lui correspond. Le calcul hérité repose sur la catégorie
Standard/Foil, une approximation. Un référentiel de règles appuyées sur des
preuves devait la remplacer. Mais le premier paquet de règles ne couvrait que
l'anglais, alors que la collection est surtout française, avec quelques cartes
anglaises, japonaises et italiennes : il ne résolvait aucune carte.

**Options.**
1. Attendre que le référentiel couvre la collection avant les contrôles
   automatiques (jalon M2).
2. Livrer le référentiel en mode audit : il s'affiche et se contrôle, sans
   remplacer le calcul hérité, et M2 avance en parallèle.

**Décision.** Option 2. Le contrat a été relu par plusieurs modèles avant
d'être fixé. Chaque langue demande ses propres preuves ; tant qu'une édition et
une langue n'ont pas de correspondance vérifiée, le prix reste le calcul
hérité, affiché avec sa provenance, jamais présenté comme vérifié.

**Conséquences.**
- Les preuves sont archivées sous leur empreinte SHA-256 ; une pièce
  manquante ou altérée est signalée.
- Une nouvelle édition s'ajoute par des données, sans correctif du moteur.
- Le travail de preuves est borné et commence par les éditions où une erreur
  coûte le plus.

**Pour aller plus loin.** [Guide du référentiel](../PRINT_REFERENCE_GUIDE.md),
[contrat](../PRINT_REFERENCE_CONTRACT.md).
