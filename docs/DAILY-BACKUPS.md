# Sauvegardes privées

Destination choisie par le propriétaire le 5 octobre 2026 : Poképrice — sauvegardes (dossier Drive privé).
Le dossier et les fichiers téléversés ont été contrôlés : seul le propriétaire
dispose d'une permission. Aucun partage supplémentaire n'est créé.

## Chaque jour

Depuis le 16 octobre 2026 à 21 h 11, la collection vivante est sur le serveur
(voir [DEPLOYMENT.md](DEPLOYMENT.md)). La base `data/inventory` du portable est
une copie périmée : aucun travail planifié ne la lit ni n'y écrit.

- À **3 h, heure de Paris**, le serveur lance `pokeprice-backup.timer` :
  sauvegarde SQLite cohérente avec les photos, restauration de contrôle,
  rétention des sept dernières `daily-AAAA-MM-JJ.zip` sous `/srv/pokeprice/backups`.
- À **3 h 15**, le timer utilisateur `pokeprice-drive-backup.timer` du portable
  lance `backup-server-drive` :
  1. par SSH (`opc@…`, sans mot de passe ni invite), il démarre
     `pokeprice-backup.service` sur le serveur. Le portable attend ainsi une
     sauvegarde nocturne en retard, ou fait revérifier l'archive du jour ;
  2. il choisit la dernière `daily-*.zip` du serveur et relève son SHA-256 et sa taille ;
  3. il la rapatrie en `data/oci-backups/oci-daily-AAAA-MM-JJ.zip`. Si le
     SHA-256 ou la taille diffèrent de ceux du serveur, rien n'est conservé.
     Une restauration temporaire contrôle ensuite SQLite, les clés étrangères
     et les photos. Une archive déjà rapatriée avec la même empreinte n'est pas
     retéléchargée ;
  4. il la **chiffre** (age, voir plus bas), l'envoie sur Drive, la retélécharge,
     la déchiffre et la restaure avant de marquer le succès.
  Le service peut réessayer deux fois, à quinze minutes d'intervalle, et au
  plus trois fois par jour.
- Les trois dernières archives `oci-daily-*.zip` restent sur le portable, faute
  de place sur le disque. Les fichiers Drive ne sont pas purgés.
- Le préfixe `oci-` sépare ces archives des anciennes `daily-AAAA-MM-JJ.zip`
  du portable, dans `data/backups` comme sur Drive.

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
temporairement : 404 exemplaires actifs. Ce contrôle portait le statut
`download-sha256-restore` ; depuis le chiffrement des copies, il s'appelle `download-decrypt-sha256-restore`. Les autres archives, dont les parties du snapshot
initial, conservent leur niveau de contrôle antérieur par métadonnées ; ce test
ne revendique pas leur restauration distante.
Les archives contiennent les comptes et leurs hashes
de mot de passe nécessaires à la restauration, dont les e-mails et demandes des
clients de la vitrine, mais aucune session connectée réactivable. Depuis le
18 octobre 2026, elles ne partent sur Drive que chiffrées.

## Chiffrement des copies Drive

Le portable chiffre chaque archive avec [age](https://age-encryption.org)
(X25519) avant l'envoi : Drive ne reçoit que des `….zip.age`, illisibles sans
la clé. Google n'a donc aucun accès aux données des clients, ce qui dispense de
contrat de sous-traitance pour un compte Drive personnel. La clé est créée une
fois par `.venv/bin/python -m pokeprice.manage backup-key`, qui n'affiche que la
clé publique ; elle vit dans `~/.config/pokeprice/backup-key.txt` (mode 0600,
format de clé d'age). Sans elle, ou si elle est lisible par d'autres comptes,
aucune copie n'est envoyée. Chaque copie est déchiffrée après retéléchargement :
une clé perdue ou altérée se voit dès la nuit suivante.

**Sans cette clé, aucune copie Drive n'est récupérable.** Elle doit avoir une
copie hors ligne, distincte du portable (disque externe), et jamais sur Drive.

Récupération sans le projet, avec l'outil `age` :

```bash
age -d -i backup-key.txt oci-daily-AAAA-MM-JJ-SHA256.zip.age > archive.zip
```

puis `restore` comme ci-dessous. Les copies envoyées avant le chiffrement
(`….zip` sans `.age`) restent lisibles par Google jusqu'à ce que la rétention
les mette à la corbeille, au plus tard après 12 mois et 30 jours ; les mettre
à la corbeille plus tôt à la main ne gêne pas le service.

## Commandes

L'unité nocturne lit l'adresse du serveur dans `~/.config/pokeprice/backup.env`,
fichier privé (mode 0600) hors du dépôt : `POKEPRICE_OCI_HOST=opc@<IP_OCI>`.

Depuis `~/Projects/pokeprice` :

```bash
.venv/bin/python -m pokeprice.manage backup-server-pull --host opc@<IP_OCI>
.venv/bin/python -m pokeprice.manage backup-server-drive --host opc@<IP_OCI> --rclone ~/.local/bin/rclone --remote gdrive
.venv/bin/python -m pokeprice.manage --data /tmp/pokeprice-restored restore data/oci-backups/oci-daily-2026-10-17.zip
systemctl --user list-timers pokeprice-drive-backup.timer
journalctl --user -u pokeprice-drive-backup.service
```

La restauration exige un dossier inexistant. Le bouton **Gestion → Sauvegarder
et vérifier maintenant** renouvelle l'archive du jour ; sa copie externe sera
effectuée au prochain passage du timer du portable ou par la commande `backup-server-drive`. Le bouton ne promet pas un
téléversement Drive immédiat. `backup-record-upload ARCHIVE FILE_ID SIZE --expected-sha256 SHA256_AVANT_TRANSFERT` est
réservé au mécanisme de copie après lecture des métadonnées Drive ;
`backup-record-failure` conserve un échec visible sans effacer le dernier succès.

Les unités installées sont reproduites dans `deploy/pokeprice-drive-backup.*`.
Elles visent ce portable ; adapter leurs chemins pour un autre appareil.
L'ancien `pokeprice-local-backup.timer`, qui fabriquait l'archive depuis
`data/inventory`, est retiré. Le suivi de la copie du serveur est
`data/oci-backups/backup-status.json`, en permissions 0600 : la vue Gestion du
serveur ne voit pas encore la copie Drive faite par le portable.
La sortie des commandes omet l'identifiant du dossier Drive, car elle va dans le journal.
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
Drive sont nommées `oci-daily-AAAA-MM-JJ-SHA256.zip.age` (copie du serveur) ou
`daily-AAAA-MM-JJ-SHA256.zip.age` (copies du portable), le SHA-256 étant celui
de l'archive en clair, pour conserver les versions d'un même jour. Une copie
chiffrée déjà envoyée de contenu identique est réutilisée ; une copie en clair
ne l'est jamais. Après un résultat de transfert incertain,
le prochain essai recherche d'abord ce nom. Plusieurs fichiers de même nom,
une archive altérée ou des permissions supplémentaires bloquent la validation.
Le service ne partage aucun fichier Drive. Après chaque copie vérifiée, il
applique une rétention aux seules archives `daily-*` et `oci-daily-*` du dossier :
il garde toutes celles des 7 derniers jours ayant une archive, la plus récente
de chacune des 8 dernières semaines et de chacun des 12 derniers mois, et met
les autres **à la corbeille** Drive, d'où elles restent récupérables 30 jours.
Les autres fichiers du dossier ne sont jamais touchés. Un échec de rétention
n'invalide pas la copie du jour : elle sera retentée à la copie suivante.

Les appels SSH, rclone et HTTP ont des délais maximaux. Pour un transfert, le
délai est proportionnel à la taille de l'archive (débit plancher de 250 ko/s,
au moins 4 min, au plus 3 h) : une archive de 790 Mo a droit à environ 53 min. Toute erreur conserve le
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
