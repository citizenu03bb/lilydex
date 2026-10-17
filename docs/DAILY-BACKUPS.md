# Sauvegardes privées

Destination choisie par le propriétaire le 5 octobre 2026 : Poképrice — sauvegardes (dossier Drive privé).
Le dossier et les fichiers téléversés ont été contrôlés : seul le propriétaire
dispose d'une permission. Aucun partage supplémentaire n'est créé.

## Chaque jour

- À **3 h, heure de Paris**, le timer utilisateur `pokeprice-local-backup.timer`
  lance une sauvegarde SQLite cohérente avec toutes les photos gérées, y compris
  les versions précédentes. Une restauration temporaire contrôle les SHA-256,
  l'intégrité SQLite, les clés étrangères et les photos référencées.
- À **3 h 15**, le timer utilisateur `pokeprice-drive-backup.timer` lance
  `backup-drive` avec le remote rclone `gdrive` existant. Le service peut
  réessayer deux fois, à quinze minutes d'intervalle, en cas d'échec.
  Il contrôle les permissions, copie une archive stable puis la retélécharge :
  SHA-256, restauration temporaire, SQLite et photos sont vérifiés avant succès.
- Les sept dernières archives `daily-AAAA-MM-JJ.zip` restent sur le portable.
  Les sauvegardes manuelles et les fichiers Drive ne sont pas purgés.

Le timer est actif et son service a terminé avec succès. Il rattrape un
déclenchement local manqué au prochain démarrage de la session utilisateur.
Le portable et la session utilisateur doivent fonctionner ; la copie externe
dépend du réseau et de l'autorisation Google partagée avec gphotosync.
Elle ne dépend plus de Codex, de son quota ou du connecteur. La précédente
automation Codex est mise en pause après réception du service de remplacement.
La vue Gestion affiche les dates, les erreurs enregistrées et un
retard supérieur à 36 heures.

**Réception du 6 octobre 2026 :** le ZIP Drive `daily-2026-10-06.zip` a été
retéléchargé par rclone, son SHA-256 comparé au ZIP local et son contenu restauré
temporairement : 404 exemplaires actifs. Le statut porte désormais
`download-sha256-restore`. Les autres archives, dont les parties du snapshot
initial, conservent leur niveau de contrôle antérieur par métadonnées ; ce test
ne revendique pas leur restauration distante.
Les archives contiennent les comptes et leurs hashes
de mot de passe nécessaires à la restauration, mais aucune session connectée
réactivable. Elles restent privées.

## Commandes

L'unité nocturne lit l'adresse du serveur dans `~/.config/pokeprice/backup.env`,
fichier privé (mode 0600) hors du dépôt : `POKEPRICE_OCI_HOST=opc@<IP_OCI>`.

Depuis `~/Projects/pokeprice` :

```bash
.venv/bin/python -m pokeprice.manage backup-daily
.venv/bin/python -m pokeprice.manage backup-drive --rclone ~/.local/bin/rclone --remote gdrive
.venv/bin/python -m pokeprice.manage backup-status
.venv/bin/python -m pokeprice.manage --data /tmp/pokeprice-restored restore data/backups/daily-2026-10-05.zip
systemctl --user list-timers pokeprice-local-backup.timer
journalctl --user -u pokeprice-local-backup.service
systemctl --user list-timers pokeprice-drive-backup.timer
journalctl --user -u pokeprice-drive-backup.service
```

La restauration exige un dossier inexistant. Le bouton **Gestion → Sauvegarder
et vérifier maintenant** renouvelle l'archive du jour ; sa copie externe sera
effectuée au prochain passage du timer ou par la commande `backup-drive`. Le bouton ne promet pas un
téléversement Drive immédiat. `backup-record-upload ARCHIVE FILE_ID SIZE --expected-sha256 SHA256_AVANT_TRANSFERT` est
réservé au mécanisme de copie après lecture des métadonnées Drive ;
`backup-record-failure` conserve un échec visible sans effacer le dernier succès.

Les unités installées sont reproduites dans `deploy/pokeprice-local-backup.*`
et `deploy/pokeprice-drive-backup.*`.
Elles visent ce portable ; adapter leurs chemins pour un autre appareil.
Le suivi local est `data/inventory/backup-status.json`, en permissions 0600.
L'API de statut et de sauvegarde manuelle est réservée aux administrateurs.

## Transfert déterministe

La configuration et le jeton du remote `gdrive` sont réutilisés directement ;
aucun secret n'est copié dans le projet. Le dossier destination est imposé par
son identifiant dans chaque commande, sans modifier le remote partagé.
L'autorisation couvre Drive ; cette limite de destination est une règle du
service, pas une restriction du jeton OAuth. La révocation affecterait les
autres projets qui utilisent ce remote.

Une copie temporaire privée stabilise les octets pendant le transfert ; un
verrou empêche deux exécutions Poképrice simultanées. Les nouvelles archives
Drive sont nommées `daily-AAAA-MM-JJ-SHA256.zip` pour conserver les versions d'un
même jour. Une ancienne copie connue de contenu identique peut être réutilisée,
comme lors de la réception du 6 octobre. Après un résultat de transfert incertain,
le prochain essai recherche d'abord ce nom. Plusieurs fichiers de même nom,
une archive altérée ou des permissions supplémentaires bloquent la validation.
Le service ne supprime ni ne partage aucun fichier Drive.

Les appels rclone et HTTP ont des délais maximaux. Toute erreur conserve le
dernier succès et inscrit un échec dans la vue Gestion ; les détails sont dans
le journal systemd. Il n'y a pas encore de notification externe autonome.
Une sauvegarde locale remplacée pendant le transfert n'est pas déclarée à jour.
Le retéléchargement et la restauration sont effectués à chaque exécution réussie,
y compris lorsqu'aucun nouveau fichier n'a besoin d'être envoyé.

## Sources originales et application

Le ZIP quotidien contient la collection gérée et ses photos. Les 80 grandes
photos originales des classeurs sont dans le snapshot initial, décrit dans
[RECOVERY.md](RECOVERY.md). Pour ce snapshot de 590 Mo, le connecteur impose
une limite de transfert de 100 Mio : sept parties de 90 Mio au maximum permettent
de reconstituer exactement l'archive, avec `SHA256SUMS.parts`, `parts.json`,
le manifeste initial et `RESTAURER.txt`.

Les artefacts installables et sources de la livraison sont également conservés
dans Drive. Pour récupérer la gestion récente, utiliser ces sources ou la wheel
récente plutôt que le code du snapshot initial, antérieur au backend de gestion.
Reconfigurer les identifiants de services séparément : les fichiers `.env` ne
font pas partie des archives de code.
