# 0013 — Pas de synchronisation entre le portable et le serveur

> **Statut :** en vigueur · **Date :** 2026-10-20

**Contexte.** Le portable et le serveur ont chacun une base. Une
synchronisation aurait permis de récupérer les changements du serveur en
quelques secondes, de simuler des opérations en local et de les promouvoir
vers la production.

**Options.**
1. Construire cette synchronisation (exploration détaillée dans la
   [proposition archivée](../archive/SYNC_PROPOSAL-2026-10-19.md)).
2. Une seule base de référence, sur le serveur ; le portable rapatrie les
   sauvegardes et s'en sert pour les essais.

**Décision.** Option 2. La synchronisation reste une exploration ; elle ne sera
pas implémentée.

**Conséquences.**
- Toute écriture de collection se fait sur le serveur, par l'application ou
  par une commande lancée sur le serveur avec `--data`.
- Pour essayer une opération sur des données réelles, on restaure une
  sauvegarde dans un dossier temporaire.
