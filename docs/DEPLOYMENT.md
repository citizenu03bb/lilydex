# Déploiement Internet (Oracle Cloud Always Free & VPS)

Configuration d'hébergement permanent avec isolation stricte des secrets. Un [tunnel HTTPS Cloudflare temporaire](TUNNEL.md) reste utilisable pendant le développement local.

## Architecture retenue (0 € / mois)

- **Serveur :** Instance **Oracle Cloud (OCI) Always Free** sous Ubuntu 24.04 LTS (`VM.Standard.A1.Flex` ARM Ampere 1 à 4 OCPU / 6 à 24 Go RAM, ou `VM.Standard.E2.1.Micro` AMD 1 Go RAM + 2 Go swap), disque persistant de 47 à 100 Go. Alternatives VPS dédiées chiffrées en octobre 2026 : Scaleway `STARDUST1-S` IPv6 (~1,10 € TTC/mois), Netcup `VPS piko G11s` 1 vCore / 1 Go / 30 Go SSD (~2,25 € TTC/mois), Hetzner `CX23` (~6,59 € TTC/mois).
- **HTTPS direct sans frais de domaine :** Caddy en frontal sur les ports `80`/`443` avec un sous-domaine gratuit pointant en `A` vers l'IP publique OCI ([deSEC.io](https://desec.io) en `.dedyn.io` ou [DuckDNS](https://www.duckdns.org) en `.duckdns.org`), et certificat Let's Encrypt automatique.
- **Cloisonnement des secrets :**
  - **Aucun jeton OAuth Google Drive (`rclone.conf`) ni identifiant de dossier Drive (`POKEPRICE_DRIVE_FOLDER`)** n'est copié sur le serveur cloud.
  - Seule la clé `GEMINI_API_KEY` (ou `GOOGLE_API_KEY`) et `POKEPRICE_HOST` résident sur le serveur dans `/etc/pokeprice/pokeprice.env` (`root:pokeprice`, mode `0640`), transférés de machine à machine par flux SSH chiffré sans jamais s'afficher en clair.
  - Le serveur exécute `backup-daily` chaque nuit à 03 h (`Europe/Paris`) dans `/srv/pokeprice/backups` (avec restauration de contrôle et rétention des 7 derniers ZIP). Le portable rapatrie les sauvegardes via SSH (`deploy/oci-pull-backup.sh`) et conserve l'exclusivité de la copie Google Drive.

## Fichiers et scripts fournis (`deploy/`)

- `deploy/pokeprice.service` : service applicatif (`User=pokeprice`, `ProtectSystem=strict`, `ProtectHome=true`, cookie HTTPS `--secure-cookie`, hôte autorisé `${POKEPRICE_HOST}`, base et photos sous `/srv/pokeprice/inventory`).
- `deploy/pokeprice-backup.service` et `.timer` : sauvegarde quotidienne vérifiée (`backup-daily`) sous `/srv/pokeprice/backups`, avec rétention des 7 dernières archives quotidiennes.
- `deploy/Caddyfile.example` : modèle HTTPS et proxy local vers `127.0.0.1:3820`.
- `deploy/oci-provision.sh` : provisionnement idempotent d'Ubuntu 24.04 sur OCI (fuseau `Europe/Paris`, swap 2 Go, ouverture des ports `80`/`443` dans `iptables` local OCI, installation de Caddy et `uv`, création de l'utilisateur `pokeprice` et de `/srv/pokeprice`).
- `deploy/oci-sync-secrets.sh` : transfert direct (`stdin` SSH, `set +x`, `umask 0077`) de `GEMINI_API_KEY` depuis `~/.env` vers `/etc/pokeprice/pokeprice.env` sans affichage.
- `deploy/oci-deploy.sh` : synchronisation des seuls fichiers suivis par Git (`git ls-files`), installation du `.venv`, restauration initiale de la dernière archive vérifiée `data/backups/daily-*.zip`, activation de `systemd` et Caddy, puis test de `/health`.
- `deploy/oci-pull-backup.sh` : rapatriement par SSH de la dernière sauvegarde quotidienne du serveur OCI vers le portable avec restauration locale de contrôle.

## Procédure d'installation

Depuis le portable (après création de l'instance OCI, ouverture des ports TCP 80/443 dans la *Security List* OCI et création de l'enregistrement DNS `A`) :

```bash
# 1. Provisionner le système distant
ssh ubuntu@<IP_OCI> 'sudo bash -s' < deploy/oci-provision.sh

# 2. Transférer la clé Gemini sans jamais l'afficher
./deploy/oci-sync-secrets.sh ubuntu@<IP_OCI> <sous-domaine.dedyn.io>

# 3. Déployer le code, restaurer la collection et activer HTTPS
./deploy/oci-deploy.sh ubuntu@<IP_OCI> <sous-domaine.dedyn.io>
```

Pour rapatrier une sauvegarde quotidienne depuis le serveur vers le portable et l'envoyer sur Google Drive :

```bash
./deploy/oci-pull-backup.sh ubuntu@<IP_OCI> --push-drive
```

## Vérifications avant et après publication

- Vérifier `https://<domaine>/health`, la connexion HTTPS, l'expiration/déconnexion, le refus (`401`) sans session sur les cartes, photos, exports et sauvegardes, et un parcours Android réel.
- Vérifier le timer avec `systemctl list-timers pokeprice-backup.timer` et le journal `journalctl -u pokeprice-backup.service`.
- Avant une mise à jour de schéma, exécuter `./deploy/oci-pull-backup.sh ubuntu@<IP_OCI>` et tester la migration.

