# 0028 — Le serveur garde ses photos une seule fois, dans une réserve par empreinte, et le portable reconstitue l'archive autonome

> **Statut :** en vigueur · **Date :** 2026-11-04

**Contexte.** Chaque archive `pokeprice-inventory-v1` recopie toutes les
photos : 758 Mo de JPEG (3 104 fichiers) pour 35 Mo de base et 6 Mo de
documents de référence. Une archive pèse donc environ 800 Mo, et 95 % de ses
octets sont identiques d'une nuit à l'autre. Le serveur garde 7
quotidiennes et au moins 3 ponctuelles, soit 5,6 à 8 Go d'archives. Son
disque, agrandi à 200 Go, les absorbe, mais ce volume grandit avec chaque
photo. La contrainte principale est ailleurs : le portable rapatrie 800 Mo
chaque nuit et garde ses archives sur un disque rempli à 96 %.

Deux faits rendent la déduplication sûre :
- une photo est nommée par le SHA-256 de son contenu (`Store.save_photo`) ;
  elle n'est jamais réécrite ni supprimée par l'application. Une même photo
  a donc toujours le même nom et le même contenu ;
- la restauration contrôle déjà le SHA-256 de chaque fichier, et vérifie que
  chaque photo citée par la base est présente.

**Options.**
1. **Statu quo.** Rien à écrire. Le serveur occupe 5,6 à 8 Go en archives ;
   le transfert vers le portable reste de 800 Mo par nuit, et le portable
   garde 2,4 Go d'archives. À chaque nouvelle photo, ces volumes grandissent.
2. **Réserve par empreinte sur le serveur, et archive autonome reconstituée
   sur le portable.**
   - Le serveur garde les photos une seule fois dans
     `backups/photos/<sha256>.jpg`. Les archives du dossier `backups/`
     passent au format `pokeprice-inventory-v2`, qui contient la base, les
     documents de référence et un manifeste listant chaque photo avec son
     SHA-256, sans les photos. Elles pèsent environ 10 Mo (la base se
     compresse bien).
   - La réserve est faite de liens physiques vers `inventory/photos` : sur le
     même disque, une photo coûte 0 octet de plus. Elle protège contre une
     suppression, pas contre une réécriture sur place ; une copie la
     protégerait aussi, pour 758 Mo de plus.
   - Le portable rapatrie l'archive v2 et seulement les photos qu'il n'a pas
     encore, dans sa propre réserve. Il reconstitue ensuite une archive v1
     complète et autonome, qu'il contrôle par une restauration ; c'est elle qui
     part chiffrée sur Drive, comme aujourd'hui.
   - Les archives téléchargées depuis la gestion et celles écrites hors de
     `backups/` restent en v1 autonome.
3. **Comme 2, et Drive incrémental.** Les photos sont envoyées une seule fois
   sur Drive, et la quotidienne Drive ne porte que la base. Une branche du
   17 octobre (`claude/drive-photos-incremental`, jamais fusionnée) l'a
   esquissée. Le gain est de 800 Mo envoyés par nuit, mais une restauration
   depuis Drive exige alors des milliers de fichiers chiffrés et le code du
   projet, au lieu d'une seule commande `age -d`.
4. **Outil de déduplication du marché** (restic, borg). La déduplication est
   éprouvée, mais il faut un nouveau format, une nouvelle dépendance sur le
   serveur ARM et sur le portable, et récrire la chaîne de vérification
   (restauration de contrôle, état dans la gestion, Drive chiffré).

| | 1. Statu quo | 2. Réserve + reconstitution | 3. Et Drive incrémental | 4. restic/borg |
|---|---|---|---|---|
| Archives sur le serveur | 5,6 à 8 Go | ≈ 0,1 Go (+0,76 Go si copie) | ≈ 0,1 Go | ≈ 0,8 Go |
| Transfert nocturne vers le portable | 800 Mo | ≈ 10 Mo + photos nouvelles | idem | idem |
| Portable | 2,4 Go | ≈ 1,6 Go | ≈ 0,8 Go | ≈ 0,8 Go |
| Envoi Drive par nuit | 800 Mo | 800 Mo | ≈ 10 Mo | ≈ 10 Mo |
| Restauration depuis Drive | 1 fichier, `age -d` | inchangée | des milliers de fichiers | outil requis |
| Code à écrire | aucun | moyen | élevé | élevé |

**Risques de l'option 2 à la restauration, et leur parade.**
- *Une archive v2 n'est pas autonome* : sans la réserve, elle ne restaure
  rien. `restore` cherche la réserve à côté de l'archive (`photos/`), accepte
  `--photos` pour en désigner une autre, et refuse avec un message clair si
  une photo manque. Le portable et Drive gardent une archive v1 autonome.
- *Point unique* : une photo abîmée dans la réserve touche toutes les
  archives du serveur à la fois, au lieu d'une seule. La restauration de
  contrôle de chaque nuit relit le SHA-256 de chaque photo citée ; une
  altération devient un échec visible dans la gestion, le lendemain au plus
  tard. Les archives v1 du portable et de Drive restent indépendantes.
- *Un nettoyage trop zélé* : une photo n'est retirée de la réserve que si
  aucune archive v2 gardée ne la cite et qu'elle n'est plus dans
  `inventory/photos`. Ce nettoyage tourne sous le verrou des sauvegardes.
- *Les archives v1 existantes* restent lisibles : le code de restauration v1
  ne change pas, et un test restaure une archive v1 écrite à l'ancienne.
- *Un retour à une version antérieure du code* refuserait les archives v2
  (« Format de sauvegarde inconnu »), sans les abîmer.

**Décision.** Option 2, avec la réserve en liens physiques. L'option 3
pourra suivre si l'envoi Drive devient la contrainte ; elle ne change rien à
ce que décrit cette fiche.

**Conséquences.**
- La place des archives du serveur ne dépend plus du nombre de photos, et la
  rétention peut grandir sans que le disque suive le nombre de photos.
- Le rapatriement devient court ; le premier, qui remplit la réserve du
  portable, transfère encore 758 Mo.
- Le portable fabrique une archive, mais seulement à partir de celle du
  serveur et de photos dont il contrôle l'empreinte, jamais depuis sa propre
  base : la [fiche 0003](0003-drive-depuis-le-portable-chiffre.md) tient
  toujours.
- Restaurer sur le serveur exige la réserve : sauvegarder `backups/` sans
  `backups/photos/` ne suffit plus.

**Preuve.** `tests/test_photo_reserve.py`.

**Pour aller plus loin.** [Sauvegardes](../DAILY-BACKUPS.md).
