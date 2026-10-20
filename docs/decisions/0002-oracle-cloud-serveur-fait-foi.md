# 0002 — Oracle Cloud gratuit, et le serveur fait foi

> **Statut :** en vigueur · **Date :** 2026-10-16

**Contexte.** L'application devait devenir accessible en permanence, depuis
un téléphone et pour des clients, sans dépendre du portable ni d'un tunnel
temporaire. Contrainte : un coût d'hébergement nul.

**Options.**
1. Garder le tunnel Cloudflare depuis le portable : instable, dépend d'une
   machine allumée.
2. Un petit serveur privé payant (Scaleway, Netcup, Hetzner : de 1 à 7 € par
   mois).
3. L'offre gratuite d'Oracle Cloud : instance ARM Ampere, jusqu'à 4 cœurs et
   24 Go de mémoire, ou instance AMD de 1 Go.

**Décision.** Oracle Cloud, instance ARM, avec Caddy et un certificat Let's
Encrypt sur un sous-domaine gratuit. **La base du serveur fait foi** : le
portable ne garde qu'une copie, qui rapatrie les sauvegardes et sert aux
essais.

**Conséquences.**
- Pas de carte graphique : torch en version processeur seul
  ([fiche 0009](0009-torch-cpu-arm.md)).
- L'instance AMD de 1 Go ne suffit pas à l'option vision.
- Deux bases ont existé en parallèle ; une journée de travail faite sur le
  portable a dû être reportée sur le serveur. Depuis, aucune écriture de
  collection ne se fait sur le portable, et la synchronisation entre les deux
  n'est pas retenue ([fiche 0013](0013-pas-de-synchronisation.md)).

**Pour aller plus loin.** [Héberger Lilydex](../DEPLOYMENT.md).
