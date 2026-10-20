# 0003 — Seul le portable accède à Drive, et les copies sont chiffrées

> **Statut :** en vigueur · **Date :** 2026-10-18

**Contexte.** Le serveur fait une sauvegarde vérifiée chaque nuit. Il en faut
une copie hors du serveur. Un serveur exposé sur Internet ne doit pas détenir
de jeton donnant accès à un stockage personnel.

**Options.**
1. Le serveur envoie lui-même ses archives sur Google Drive.
2. Le portable rapatrie l'archive par SSH, la vérifie et l'envoie sur Drive.
3. Comme 2, mais l'archive est chiffrée avant l'envoi.

**Décision.** Option 3. Aucun jeton Drive ni identifiant de dossier n'est
copié sur le serveur. Le portable rapatrie la dernière archive vérifiée,
contrôle son empreinte SHA-256 et une restauration, la chiffre avec l'outil
age, l'envoie, la retélécharge, la déchiffre et la restaure avant de marquer
le succès.

**Conséquences.**
- Une compromission du serveur ne donne pas accès au Drive.
- La clé de déchiffrement doit être conservée hors du portable : sans elle,
  les copies Drive sont illisibles.
- Le portable ne fabrique jamais d'archive depuis sa propre base, qui est une
  copie.

**Pour aller plus loin.** [Sauvegardes](../DAILY-BACKUPS.md).
