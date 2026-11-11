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
| HTTPS | Caddy sur les ports 80 et 443, certificat Let's Encrypt automatique, domaine pointé en `A` vers l'adresse du serveur : domaine acheté (la boutique utilise `lescartesdelily.fr`) ou sous-domaine gratuit ([deSEC](https://desec.io) en `.dedyn.io`, [DuckDNS](https://www.duckdns.org) en `.duckdns.org`). |
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
  - le [chat de gestion](APP.md#lassistant), éteint tant que sa clé manque :
    - `POKEPRICE_ASSISTANT_GEMINI_KEY`, une clé Gemini à lui, d'un projet
      Google où la facturation est activée ([fiche 0031](decisions/0031-modele-du-chat.md)) ;
      le chat ne lit jamais `GEMINI_API_KEY` à sa place ;
    - `POKEPRICE_ASSISTANT_MODEL` (facultatif, `gemini-3.8-flash` par défaut ;
      `gemini-3.5-flash-lite` est le repli) ;
    - `POKEPRICE_ASSISTANT_DAILY_LIMIT` (facultatif, 100 questions par jour
      pour toute la gestion) et `POKEPRICE_ASSISTANT_PER_MINUTE` (facultatif,
      6 questions par minute et par compte) ;
    - `POKEPRICE_ASSISTANT_COST_ALERT_EUR` (facultatif, 30 € ; 0 éteint
      l'alerte) et `POKEPRICE_ASSISTANT_EUR_PER_USD` (facultatif, 0,95 €
      pour un dollar) : le seuil de l'alerte de coût mensuelle et le taux qui
      convertit le tarif ([fiche 0039](decisions/0039-alerte-de-cout-du-chat.md)) ;
  - `POKEPRICE_HOST`, le nom de domaine accepté par l'application ;
  - `POKEPRICE_PUBLIC_ORIGIN`, l'origine HTTPS publique sans chemin, utilisée
    pour les URL des aperçus de partage ; si elle est absente, le serveur
    conserve les titres et descriptions mais omet les URL absolues et images
    de partage. Elle ne se déduit jamais d'un en-tête fourni par le visiteur ;
  - `POKEPRICE_CONTACT_EMAIL` et `POKEPRICE_CONTROLLER_NAME`, l'adresse de
    contact et le nom du responsable du traitement affichés sur la page
    « À propos ». Ils ne sont jamais versionnés ;
  - les alertes de demande de réservation ([fonctionnement](VITRINE.md#les-alertes-au-vendeur)),
    chaque canal étant éteint tant que ses variables manquent :
    - `POKEPRICE_NTFY_URL`, l'adresse du sujet ntfy (`https://` obligatoire,
      ou `http://localhost` pour un essai) : l'adresse est le secret. Le
      serveur ne la configure plus : Web Push la remplace
      ([fiche 0033](decisions/0033-notifications-web-push.md)) ;
    - `POKEPRICE_NTFY_TOKEN`, un jeton d'accès si le sujet est protégé
      (facultatif) ;
    - `POKEPRICE_SMTP_HOST`, `POKEPRICE_SMTP_FROM` et `POKEPRICE_NOTIFY_EMAIL`
      (à défaut `POKEPRICE_CONTACT_EMAIL`) : le serveur d'envoi, l'expéditeur
      et le destinataire, tous trois requis pour le courriel ;
    - `POKEPRICE_SMTP_PORT` (facultatif : 587 en `starttls`, 465 en `ssl`,
      25 en `none`), `POKEPRICE_SMTP_USER` et `POKEPRICE_SMTP_PASSWORD`
      (facultatifs : sans identifiant, pas d'authentification) ;
    - `POKEPRICE_SMTP_SECURITY`, `starttls` (défaut), `ssl` ou `none` ; toute
      autre valeur retombe sur `starttls`. `none` envoie en clair, mot de
      passe compris : à réserver à un relais local de confiance ;
    - `POKEPRICE_VAPID_PUBLIC_KEY`, `POKEPRICE_VAPID_PRIVATE_KEY` et
      `POKEPRICE_VAPID_SUBJECT` (`mailto:…` ou `https://…`), les trois requis
      pour les notifications Web Push de la gestion installée
      ([activation](#activer-les-notifications-web-push)).
- **Sur le portable seulement** : le jeton Google Drive (configuration
  rclone, `rclone.conf`), l'identifiant du dossier Drive et la clé de chiffrement des
  sauvegardes. Aucun n'est copié sur le serveur.

`deploy/oci-sync-secrets.sh` réécrit le fichier du serveur en entier à partir
du `~/.env` du portable, par un flux SSH chiffré, sans jamais afficher un
secret. Il recopie les variables listées ci-dessus, alertes comprises ; une
variable ajoutée à la main sur le serveur disparaît à la synchronisation
suivante.

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
   ./deploy/oci-deploy.sh <utilisateur>@<ip-serveur> <domaine> [<domaine-redirigé>...]
   ```

   Les domaines ajoutés après le premier (`www`, ancienne adresse)
   redirigent en 301 vers le domaine principal, chemin compris. La boutique
   se déploie avec
   `lescartesdelily.fr www.lescartesdelily.fr lilydex.duckdns.org` ; un
   déploiement sans ces redirections les retire de Caddy.

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

La commande générale est décrite ci-dessous ; l'entretien des dérivés dispose
aussi d'une [procédure dédiée](#entretenir-le-cache-public).

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
| `pokeprice-audience-purge.service` et `.timer` | Nettoyage indépendant des sels et empreintes des jours précédents, programmé à 0 h 05, heure de Paris, avec au plus cinq minutes de délai aléatoire. Activé par `oci-deploy.sh`. |
| `pokeprice-media-cache.service` et `.timer` | Entretien indépendant des dérivés publics, vers 4 h 30, limité au cache. |
| `pokeprice-prices.service` et `.timer` | Cotation matinale de la collection vers 6 h 20 (`prices --from-guide`). Non activés par `oci-deploy.sh`. |
| `pokeprice-brief.service` et `.timer` | Brief du jour de la gestion vers 7 h 30 (`brief --notify`). Non activés par `oci-deploy.sh`. |
| `pokeprice-lots-key.service` et `.timer` | Renouvellement de la clé de l'agent des lots vers 9 h 30, sous `pokeprice`, sans `ssh` (`lots-key-renew.sh` en mode local). Non activés par `oci-deploy.sh` ([AGENT_CONTROL](AGENT_CONTROL.md#renouvellement-automatique-de-la-clé-des-lots)). |
| `pokeprice-lots-rotate.service` et `.timer` | Rotation quotidienne des lots vers 10 h (`pokeprice-agent lots-rotate --apply`), sous le compte restreint `lilydex-lots`, sans accès à la collection. Non activés par `oci-deploy.sh` ([AGENT_CONTROL](AGENT_CONTROL.md#agent-des-lots-sur-le-serveur)). |
| `user/pokeprice-lots-key.service` et `.timer` | Unités utilisateur **du poste** : repli du renouvellement de la clé des lots par `ssh`. |
| `Caddyfile.example` | HTTPS, compression, corps de requête limité à 9 Mo, relais vers `127.0.0.1:3820`. |
| `pokeprice-drive-backup.service` et `.timer` | Unités utilisateur **du portable** : rapatriement, chiffrement et copie Drive à 3 h 15. |
| `oci-pull-backup.sh` | Raccourci de `backup-server-pull` (ou de `backup-server-drive` avec `--push-drive`) : rapatrie et contrôle la dernière archive du serveur. |

## Effacer les empreintes d'audience

Le nettoyage d'audience ne dépend ni d'une visite, ni d'un rapport, ni de la
sauvegarde : `pokeprice-audience-purge.timer` lance `audience-purge` chaque
nuit et rattrape un passage manqué au démarrage. Le service dispose de cinq
minutes pour finir. La notice annonce une suppression programmée dans l'heure
après minuit, heure de Paris ; une machine arrêtée ou un service en échec
demande une intervention. Contrôlez son état et son journal comme ceux de la
sauvegarde :

```bash
systemctl status pokeprice-audience-purge.timer pokeprice-audience-purge.service
journalctl -u pokeprice-audience-purge.service
```

## Entretenir le cache public

`pokeprice-media-cache.timer` déclenche un service indépendant vers 4 h 30,
heure de Paris, avec un délai aléatoire de dix minutes au plus. Un passage
manqué est rattrapé au démarrage. Un échec de cet entretien ne bloque pas la
sauvegarde quotidienne.

Le service traite uniquement `public-media/` : fichiers réguliers à nom
SHA-256, JPEG ou WebP, âgés d'au moins 30 jours et sans référence actuelle.
Les liens, sous-dossiers, fichiers inconnus et temporaires restent intacts.
Les références de toutes les cartes sont lues, même hors vitrine, réservées
ou supprimées ; les rectos et versos correspondants sont protégés. Le plan
est limité à 200 fichiers et 64 Mio par passage. Les passages suivants
traitent l'éventuel reliquat.

La commande n'initialise pas de base et n'utilise pas `Store`. SQLite est
ouvert en lecture seule ; une référence manquante ou modifiée pendant
l'analyse annule la suppression. Le service dispose d'un système de fichiers
en lecture seule, avec une exception limitée au dossier du cache. Il ne lit
aucune configuration secrète.

Pour mesurer et examiner le plan sans suppression :

```bash
sudo -u pokeprice env HOME=/srv/pokeprice /opt/pokeprice/.venv/bin/python -m pokeprice.manage --data /srv/pokeprice/inventory public-media-cache
```

Pour appliquer les mêmes limites :

```bash
sudo -u pokeprice env HOME=/srv/pokeprice /opt/pokeprice/.venv/bin/python -m pokeprice.manage --data /srv/pokeprice/inventory public-media-cache --apply
```

`--data` est obligatoire, même pour la simulation. Le rapport JSON distingue
volume, fichiers ignorés, dérivés protégés, plan, suppressions et plafond
atteint. Deux nettoyages ne s'exécutent pas en même temps sur ce cache. Le
timer et ses journaux se consultent avec `systemctl status
pokeprice-media-cache.timer` et `journalctl -u pokeprice-media-cache.service`.

## Coter la collection chaque matin

`pokeprice-prices.timer` lance vers 6 h 20, heure de Paris, la cotation
matinale décrite dans [Valorisation](VALUATION.md#la-cotation-matinale) :
`prices --from-guide --actor system:prices`, avec `--data
/srv/pokeprice/inventory`. Elle passe après la sauvegarde de la nuit et
l'entretien du cache, et après la publication du guide Cardmarket. Un passage
manqué est rattrapé au démarrage. Le service n'écrit que dans le dossier de la
collection.

`oci-deploy.sh` copie le dépôt mais n'installe ni n'active ce timer.
L'opérateur l'active à la main :

```bash
sudo cp /opt/pokeprice/deploy/pokeprice-prices.service /opt/pokeprice/deploy/pokeprice-prices.timer /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now pokeprice-prices.timer
```

Le rapport du passage se lit avec `journalctl -u pokeprice-prices.service`.

## Envoyer le brief du jour

`pokeprice-brief.timer` lance vers 7 h 30, heure de Paris, le
[brief du jour](APP.md#le-brief-et-la-file--à-toi-) : `brief --notify`, avec
`--data /srv/pokeprice/inventory`. Il passe après la cotation matinale, dont
il compte les effets. La notification part sur les canaux d'alerte de la
vitrine, lus dans `/etc/pokeprice/pokeprice.env` ; elle ne porte que des
nombres, aucune donnée de client. Un passage manqué est rattrapé au
démarrage. Le service lit la collection et n'y écrit rien.

`oci-deploy.sh` copie le dépôt mais n'installe ni n'active ce timer.
L'opérateur l'active à la main :

```bash
sudo cp /opt/pokeprice/deploy/pokeprice-brief.service /opt/pokeprice/deploy/pokeprice-brief.timer /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now pokeprice-brief.timer
```

Le texte envoyé se lit avec `journalctl -u pokeprice-brief.service`.

## Activer les notifications Web Push

Web Push envoie le brief et les alertes de la vitrine directement sur les
téléphones où la gestion est installée ([fiche 0033](decisions/0033-notifications-web-push.md)).
Il demande une paire de clés VAPID, générée une fois. Comme
`oci-sync-secrets.sh` réécrit le fichier du serveur à partir du `~/.env` du
portable, la paire s'ajoute à ce `~/.env`, sur le portable :

```bash
uv run --extra web pokeprice-manage vapid-keys --subject mailto:<adresse-de-contact> >> ~/.env
```

La commande n'a pas besoin de `--data` : elle ne lit ni n'écrit la base. Sans
redirection, elle affiche les trois lignes une seule fois ; avec `--output
<fichier>`, elle les écrit dans un fichier créé en `0600`, qu'elle refuse
d'écraser. Le sujet est l'adresse de contact transmise aux services de push
d'Apple, de Google et de Mozilla : une adresse dédiée plutôt que personnelle.

Ensuite, synchronisez les secrets, puis redéployez : `oci-deploy.sh` installe
`pywebpush` (extra `web`) et redémarre le service, qui migre la base au
schéma 25 après l'avoir copiée dans `/srv/pokeprice/backups/`.

```bash
./deploy/oci-sync-secrets.sh <utilisateur>@<ip-serveur> <domaine>
```

Sur chaque téléphone, ouvrez la gestion installée, **Réglages →
Notifications sur ce téléphone**. Le brief du lendemain matin le vérifie ;
pour essayer tout de suite, lancez une fois le brief à la main :

```bash
sudo -u pokeprice env HOME=/srv/pokeprice /opt/pokeprice/.venv/bin/python -m pokeprice.manage --data /srv/pokeprice/inventory brief --notify
```

Sa sortie liste les canaux joints dans `notified` et les échecs dans
`errors`. Une nouvelle paire coupe tous les abonnements : chaque téléphone
doit alors retoucher l'interrupteur. Ne la régénérez qu'en cas de fuite.

## Les dépendances installées

`oci-deploy.sh` installe l'environnement avec
`uv sync --frozen --extra web --extra vision`. Le socle et l'option `web`
couvrent l'application, l'assistant, les sauvegardes et les tâches
planifiées (cotation, brief). L'option `cli` (pandas, openpyxl, tabulate)
sert au pipeline d'albums `pokeprice` et à `pokeprice-manage import` : le
serveur ne l'installe pas, et ces commandes s'y arrêtent en nommant l'option
manquante. Numérisez et importez depuis un poste de travail, ou ajoutez
`--extra cli` à la commande d'installation si le serveur doit importer.

L'interpréteur Python que gère `uv` s'installe dans `/opt/pokeprice/.python`
(`UV_PYTHON_INSTALL_DIR`), lisible par tous comme le code, et non sous
`/srv/pokeprice`, fermé : le compte restreint de l'agent des lots lance le
client du déploiement sans rien lire de la collection. Si l'environnement
virtuel repose sur un interpréteur d'ailleurs, `oci-deploy.sh` le reconstruit
une fois, avant de redémarrer le service.

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
