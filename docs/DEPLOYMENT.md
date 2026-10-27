# Héberger le site

> **Pour qui :** toute personne qui installe ou exploite Les cartes de Lily sur un serveur.
> **Vous y trouverez :** l'architecture, l'installation pas à pas, la mise à jour, la façon de lancer une commande sur le serveur, l'option vision et les vérifications après une mise en ligne.
> **Statut :** en vigueur. Les choix sont expliqués dans les fiches [0002](decisions/0002-oracle-cloud-serveur-fait-foi.md), [0003](decisions/0003-drive-depuis-le-portable-chiffre.md) et [0009](decisions/0009-torch-cpu-arm.md).

Le site tourne sur un serveur Linux derrière Caddy, qui fournit HTTPS. La base
du serveur fait foi ; le portable du mainteneur rapatrie les sauvegardes et
garde seul l'accès à Google Drive.

## L'architecture

| Élément | Choix |
|---|---|
| Serveur | Oracle Cloud, offre gratuite (Always Free) : instance ARM Ampere `VM.Standard.A1.Flex` (1 à 4 cœurs, 6 à 24 Go de mémoire) ou AMD `VM.Standard.E2.1.Micro` (1 Go, plus 2 Go d'échange) ; disque de 47 à 100 Go. L'option vision demande l'instance ARM. |
| Système | Oracle Linux 8 ou 9 (utilisateur `opc`) ou Ubuntu 22.04 ou 24.04 (utilisateur `ubuntu`) : les scripts gèrent les deux. |
| HTTPS | Caddy sur les ports 80 et 443, certificat Let's Encrypt automatique, sous-domaine gratuit pointé en `A` vers l'adresse du serveur ([deSEC](https://desec.io) en `.dedyn.io` ou [DuckDNS](https://www.duckdns.org) en `.duckdns.org`). |
| Application | Service systemd `pokeprice`, sous l'utilisateur `pokeprice`, code dans `/opt/pokeprice`, données dans `/srv/pokeprice/inventory`, écoute sur `127.0.0.1:3820`. |
| Sauvegardes | Chaque nuit sur le serveur, rapatriées et copiées chiffrées sur Drive par le portable : voir [Sauvegardes](DAILY-BACKUPS.md). |

Autres hébergeurs possibles, sur un petit serveur privé payant : Scaleway
`STARDUST1-S` en IPv6 (environ 1,10 € TTC par mois), Netcup `VPS piko G11s`,
1 cœur, 1 Go, 30 Go (environ 2,25 €), Hetzner `CX23` (environ 6,59 €).
*Conditions de mesure : prix relevés en octobre 2026.*

## Où vivent les secrets

- **Sur le serveur**, dans `/etc/pokeprice/pokeprice.env` (propriétaire
  `root:pokeprice`, mode `0640`), et nulle part ailleurs :
  - `GEMINI_API_KEY` (ou `GOOGLE_API_KEY`), pour la lecture des photos ;
  - `POKEPRICE_HOST`, le nom de domaine accepté par l'application ;
  - `POKEPRICE_CONTACT_EMAIL` et `POKEPRICE_CONTROLLER_NAME`, l'adresse de
    contact et le nom du responsable du traitement affichés sur la page
    « À propos ». Ils ne sont jamais versionnés.
- **Sur le portable seulement** : le jeton Google Drive (configuration
  rclone, `rclone.conf`), l'identifiant du dossier Drive et la clé de chiffrement des
  sauvegardes. Aucun n'est copié sur le serveur.

`deploy/oci-sync-secrets.sh` réécrit le fichier du serveur en entier à partir
du `~/.env` du portable, par un flux SSH chiffré, sans jamais afficher un
secret.

## Installer un serveur

Avant de commencer : créez l'instance, ouvrez les ports TCP 80 et 443 dans la
*Security List* d'Oracle Cloud, et créez l'enregistrement DNS `A` de votre
sous-domaine. Remplacez `<utilisateur>` par `opc` (Oracle Linux) ou `ubuntu`.

1. **Préparer le système.** Fuseau `Europe/Paris`, 2 Go d'échange, Caddy,
   `uv`, Git et rsync, pare-feu local (firewalld ou iptables) ouvert sur 80 et
   443, utilisateur `pokeprice` et dossier `/srv/pokeprice`, journal système
   conservé trois mois (il contient les adresses IP des visiteurs). Le script
   peut être relancé sans risque.

   ```bash
   ssh <utilisateur>@<ip-serveur> 'sudo bash -s' < deploy/oci-provision.sh
   ```

2. **Transférer les secrets** depuis le `~/.env` du portable.

   ```bash
   ./deploy/oci-sync-secrets.sh <utilisateur>@<ip-serveur> <sous-domaine>
   ```

3. **Déployer.** Le script copie les seuls fichiers suivis par Git dans
   `/opt/pokeprice`, installe Python et l'environnement avec les options `web`
   et `vision`, marque les exécutables pour SELinux sur Oracle Linux, installe
   les unités systemd et la configuration Caddy, puis vérifie `/health`.

   ```bash
   ./deploy/oci-deploy.sh <utilisateur>@<ip-serveur> <sous-domaine>
   ```

   **Si le serveur n'a aucune base**, le script crée une archive
   quotidienne *à partir de la base du portable* (`data/inventory`) et la
   restaure sur le serveur. C'est le bon comportement pour une toute première
   installation. **Pour réinstaller un serveur perdu**, ne le laissez pas
   faire : la base du portable est une ancienne copie. Restaurez d'abord sur le
   serveur la dernière archive rapatriée (`data/oci-backups/oci-daily-<date>.zip`,
   voir [Sauvegardes](DAILY-BACKUPS.md#restaurer-une-archive)) dans
   `/srv/pokeprice/inventory`, puis lancez le déploiement, qui conserve une
   base existante.

4. **Installer la copie Drive sur le portable** : clé de chiffrement, fichier
   `~/.config/pokeprice/backup.env` et unités utilisateur, comme le décrit
   [Sauvegardes](DAILY-BACKUPS.md#installer-la-copie-drive-sur-le-portable).

## Mettre à jour le code

Relancez `oci-deploy.sh` : il recopie le code suivi par Git, réinstalle
l'environnement, redémarre le service et garde la base. Avant une version qui
migre la base, rapatriez et testez une sauvegarde :

```bash
./deploy/oci-pull-backup.sh <utilisateur>@<ip-serveur>
```

Restaurez ensuite l'archive rapatriée dans un dossier temporaire et lancez-y la
nouvelle version : la migration se teste sur cette copie. Au démarrage, le
serveur copie aussi sa base dans `/srv/pokeprice/backups/before-schema…` avant
de la migrer.

## Lancer une commande sur le serveur

Sur le serveur, lancez toujours `pokeprice-manage` sous l'utilisateur
`pokeprice`, avec le Python du déploiement et `--data` explicite :

```bash
sudo -u pokeprice env HOME=/srv/pokeprice /opt/pokeprice/.venv/bin/python -m pokeprice.manage --data /srv/pokeprice/inventory <commande>
```

**Sans `--data`, la commande viserait `data/inventory` dans le dossier
courant**, une autre base, vide : rien ne s'appliquerait à la collection, et
une commande d'écriture créerait une base parasite. La liste des commandes est
dans la [référence des commandes](COMMANDES.md#pokeprice-manage).

**Lancez-la depuis un dossier que `pokeprice` peut lire**, par exemple `cd /tmp`
ou le dossier du code (`/opt/pokeprice`). Ce n'est pas propre à Oracle Cloud :
sur tout hébergement où le service a son propre utilisateur, `sudo -u` garde le
dossier courant. Depuis le dossier personnel de l'administrateur ou un dossier
privé (mode `0700`), `uv` ne peut pas lire sa configuration et Python ne peut
pas ouvrir un script relatif : la commande échoue, parfois sans message.
Donnez aussi des chemins absolus aux fichiers.

## Les fichiers de `deploy/`

| Fichier | Rôle |
|---|---|
| `oci-provision.sh` | Prépare le système (voir l'étape 1). |
| `oci-sync-secrets.sh` | Transfère les secrets (`stdin` SSH, `set +x`, `umask 0077`), sans affichage. |
| `oci-deploy.sh` | Déploie le code, l'environnement, la base initiale, les unités et Caddy. |
| `pokeprice.service` | Le service de l'application. Durcissement : `User=pokeprice`, `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict` (système en lecture seule), `ProtectHome` (dossiers personnels masqués), écriture limitée à `/srv/pokeprice` ; cookie de session marqué `Secure` (`--secure-cookie`) ; seul l'hôte `${POKEPRICE_HOST}` est accepté. |
| `pokeprice-backup.service` et `.timer` | Chaque nuit vers 3 h : durées de conservation des données clients (`purge`), puis archive vérifiée (`backup-daily`), 7 archives gardées. |
| `Caddyfile.example` | HTTPS, compression, corps de requête limité à 9 Mo, relais vers `127.0.0.1:3820`. |
| `pokeprice-drive-backup.service` et `.timer` | Unités utilisateur **du portable** : rapatriement, chiffrement et copie Drive à 3 h 15. |
| `oci-pull-backup.sh` | Raccourci de `backup-server-pull` (ou de `backup-server-drive` avec `--push-drive`) : rapatrie et contrôle la dernière archive du serveur. |

## L'option vision

`oci-deploy.sh` installe l'option `vision` (torch, transformers). Elle sert au
contrôle de l'édition par l'image dans l'application et à `scan --energy-gate`
([IA et vision](IA-VISION.md)). Sans elle, l'application affiche « Contrôle
indisponible sur ce serveur ». Sur aarch64, torch vient de l'index « CPU » de
PyTorch (`[tool.uv.sources]` dans `pyproject.toml`) : la roue de PyPI y
ajouterait plusieurs Go de bibliothèques CUDA inutiles sans carte graphique.

| Mesure | Valeur |
|---|---|
| Environnement Python (`.venv`) | 912 Mo |
| Modèle `facebook/dinov2-small` (`/srv/pokeprice/.cache/huggingface`) | 85 Mo |
| Service au repos | 129 Mo de mémoire ; le modèle n'est chargé qu'au premier contrôle |
| Banque de la porte énergie, premier calcul | 1,2 Go de mémoire, 2 min 44 pour 1 767 exemplaires |
| Banque de la porte énergie, cache à jour | 310 Mo, 2 s |

*Conditions de mesure : instance A1, 2 cœurs, 10 Go de mémoire, octobre 2026.*

L'instance `E2.1.Micro` (1 Go) ne suffit pas.

Les caches vivent sous `/srv/pokeprice/inventory/references` : images TCGdex
de référence, vecteurs du contrôle d'édition (`dinov2-small.pt`) et de la porte
énergie (`energy-bank.pt`). Ils ne sont pas dans les sauvegardes et se
recalculent seuls. Les photos étant nommées par leur empreinte SHA-256, les
vecteurs calculés sur un autre poste restent valables. Pour éviter le premier
calcul, reprenez ceux du portable :

```bash
rsync -az --ignore-existing --no-owner --no-group --rsync-path="sudo rsync" data/inventory/references/ <utilisateur>@<ip-serveur>:/srv/pokeprice/inventory/references/
rsync -az --no-owner --no-group --rsync-path="sudo rsync" ~/.cache/huggingface/hub/models--facebook--dinov2-small <utilisateur>@<ip-serveur>:/srv/pokeprice/.cache/huggingface/hub/
ssh <utilisateur>@<ip-serveur> 'sudo chown -R pokeprice:pokeprice /srv/pokeprice/inventory/references /srv/pokeprice/.cache && sudo chmod -R go-rwx /srv/pokeprice/inventory/references /srv/pokeprice/.cache'
```

## Vérifier une mise en ligne

- `https://<sous-domaine>/health` répond ; la connexion HTTPS, l'expiration et
  la déconnexion fonctionnent ; sans session, les cartes, photos, exports et
  sauvegardes de la gestion répondent `401` ; un parcours réel sur un téléphone
  Android passe.
- Sur le serveur : `systemctl list-timers pokeprice-backup.timer` et
  `sudo journalctl -u pokeprice-backup.service`.
- Sur le portable : `systemctl --user list-timers pokeprice-drive-backup.timer`
  et `journalctl --user -u pokeprice-drive-backup.service`.

## Pendant le développement

Pour montrer l'application depuis le portable sans serveur, un tunnel HTTPS
temporaire est possible ; il a servi avant l'hébergement permanent
([document archivé](archive/TUNNEL-2026-10-05.md)).
