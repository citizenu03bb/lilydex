# 0001 — Une application maison plutôt qu'un logiciel existant

> **Statut :** en vigueur · **Date :** 2026-10-04

**Contexte.** La collection se gère carte par carte : chaque exemplaire a sa
photo, ses corrections, sa variante, son prix sourcé et son parcours de vente.
Avant d'écrire une application, trois logiciels libres de collection Pokémon
ont été essayés sur des copies des données.

**Options.**
1. Adapter Bindarr.
2. Adapter PokéCollect.
3. Adapter PokéCollector.
4. Compléter le pipeline existant par une application ciblée.

**Ce que l'essai a montré.** Aucun des trois ne gère des photos propres à
chaque exemplaire : ils rattachent une photo à l'édition. Tous demandaient de
changer leur modèle de données pour l'historique des corrections, la
provenance des prix, les rôles privés et les ventes. PokéCollector et
PokéCollect reposent sur PostgreSQL ; PokéCollector est sous licence AGPL.
L'essai n'établit pas qu'un fork serait plus rapide qu'une application ciblée.

**Décision.** Option 4 : une application FastAPI et SQLite qui réutilise les
données, les corrections, les photos et l'export du pipeline.

**Conséquences.** SQLite suffit pour un seul serveur et quelques utilisateurs
qui écrivent peu en même temps ; PostgreSQL deviendra pertinent si ces
contraintes changent. Tout le parcours de vente est à écrire.

**Preuve.** [Évaluation des logiciels existants](../EVALUATION.md).
