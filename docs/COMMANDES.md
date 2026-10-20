# Référence des commandes

> **Pour qui :** toute personne qui lance Lilydex en ligne de commande.
> **Vous y trouverez :** chaque commande, ses sous-commandes et leurs options, telles que le code les définit.
> **Statut :** généré par `scripts/gen_commandes.py` depuis le code ; ne pas modifier à la main.

Depuis un clone du dépôt, préfixez chaque commande par `uv run --extra web`
(par exemple `uv run --extra web pokeprice-manage serve`). Sur le serveur de
production, lancez-les sous l'utilisateur `pokeprice` avec `--data` explicite :
la forme complète est dans [Héberger Lilydex](DEPLOYMENT.md). Sans `--data`,
`pokeprice-manage` vise `data/inventory` dans le dossier courant.

Pour l'usage pas à pas, voyez le [guide de l'application](APP.md).

## `pokeprice`

Pipeline d'albums : numériser des classeurs en ligne de commande.

### `pokeprice scan`

Scanne une photo de page ou un dossier de photos

| Argument | Effet |
|---|---|
| `path` | Chemin vers une image ou un dossier d'images |
| `--grid` `GRID` | Disposition des pochettes (défaut: auto - détection visuelle IA) Valeurs : `auto`, `3x3`, `2x2`, `4x3`, `3x4`, `single`. Par défaut : `auto`. |
| `--rotate` `ROTATE` | Correction d'orientation (défaut: auto) Valeurs : `auto`, `0`, `90`, `180`, `270`. Par défaut : `auto`. |
| `--backend` `BACKEND` | Moteur de vision (défaut: ollama local ; gemini envoie les images au cloud) Valeurs : `ollama`, `gemini`. Par défaut : `ollama`. |
| `--model` `MODEL` | Nom du modèle (défaut: gemini-3.8-flash pour gemini, gemma4:e4b-it-q4_K_M pour ollama) |
| `--output`, `-o` `OUTPUT` | Fichier de sortie (.csv ou .xlsx) Par défaut : `pokeprice_report.csv`. |
| `--save-crops` `SAVE_CROPS` | Dossier optionnel où sauvegarder les découpes individuelles de cartes |
| `--inset` `INSET` | Marge intérieure de découpe (0.02 = 2%) pour éviter les coutures plastiques Par défaut : `0.02`. |
| `--condition` `CONDITION` | Force cet état pour toutes les cartes (défaut: grade OCR, ou état inconnu) Valeurs : `NM`, `EX`, `GD`, `LP`, `PL`, `PO`, `NM/EX`. |
| `--exclude` `EXCLUDE` | Noms de fichiers à exclure (ex: PXL_20261004_074746593.jpg) |
| `--limit` `LIMIT` | Nombre maximum d'images à traiter (0 = toutes) |
| `--resume` | Reprend le checkpoint du même fichier de sortie |
| `--retries` `RETRIES` | Réessais OCR après échec (défaut: 2) Valeurs : `0`, `1`, `2`, `3`, `4`, `5`. Par défaut : `2`. |
| `--energy-gate` `DONNEES` | Dossier de la collection (ex. data/inventory) : les énergies de base reconnues par l'image ne sont pas lues par Gemini |
| `--corrections` `CORRECTIONS` | Fichier JSON de corrections de référence par fichier/position |

### `pokeprice lookup`

Recherche directe du prix d'une carte par nom

| Argument | Effet |
|---|---|
| `name` | Nom de la carte, cherché dans le catalogue français puis anglais (ex: Darkrai) |
| `number` | Numéro ou fraction (ex: 4/106) |
| `--pv`, `--hp` `PV` | Points de vie (PV / HP) imprimés sur la carte (ex: 80) |
| `--holo` | Chercher la version holographique / reverse |

### `pokeprice report`

Affiche le résumé d'un rapport CSV existant

| Argument | Effet |
|---|---|
| `csv_file` | Chemin vers le fichier CSV généré |

### `pokeprice html`

Génère un rapport web interactif (photos réelles + officielles côte à côte)

| Argument | Effet |
|---|---|
| `report_file` | Fichier CSV ou Excel généré par scan |
| `album_dir` | Dossier contenant les photos du classeur |
| `-o`, `--output` `OUTPUT` | Chemin du fichier HTML de sortie |
| `--title` `TITLE` | Titre de la page web |
| `--grid` `GRID` | Géométrie pour les anciens exports sans métadonnées Valeurs : `3x3`, `2x2`, `4x3`, `3x4`, `single`. |
| `--rotate` `ROTATE` | Valeurs : `auto`, `0`, `90`, `180`, `270`. Par défaut : `auto`. |
| `--inset` `INSET` | Par défaut : `0.02`. |

### `pokeprice library`

Consolide les albums et recherche tous les exemplaires

| Argument | Effet |
|---|---|
| `manifest` | Manifeste JSON des albums à regrouper |
| `-o`, `--output` `OUTPUT` | Préfixe des sorties HTML, CSV et JSON Par défaut : `pokeprice_library`. |

## `pokeprice-manage`

Application de gestion et exploitation : serveur, imports, exports, sauvegardes, comptes.

Options communes :

| Argument | Effet |
|---|---|
| `--data` `DATA` | Dossier persistant de base et photos Par défaut : `data/inventory`. |

### `pokeprice-manage import`

Import conservateur, sans écraser les modifications

| Argument | Effet |
|---|---|
| `manifest` |  |

### `pokeprice-manage status`

Comptes et rapprochement de la collection

### `pokeprice-manage reference-audit`

Audit local du référentiel et des références héritées ; aucune migration ou correction

### `pokeprice-manage reference-recheck`

Suspensions de cotations liées devenues incompatibles (après mise à jour des règles)

| Argument | Effet |
|---|---|
| `--apply` | Inscrire les suspensions au journal |
| `--reason` `REASON` | Par défaut : `Mise à jour du référentiel`. |

### `pokeprice-manage reference-archive`

Archiver une pièce justificative (PDF, HTML, JSON) par empreinte SHA-256

| Argument | Effet |
|---|---|
| `document` |  |

### `pokeprice-manage user`

Créer un accès avec saisie confidentielle du mot de passe

| Argument | Effet |
|---|---|
| `username` |  |
| `--role` `ROLE` | Valeurs : `admin`, `editor`, `reader`. Par défaut : `reader`. |

### `pokeprice-manage agent-create`

Déléguer un album à un agent

| Argument | Effet |
|---|---|
| `name` |  |
| `--owner` `OWNER` | Compte de gestion délégant |
| `--album` `ALBUM` |  |
| `--client` `CLIENT` | Client et destinataire des données/photos |
| `--days` `DAYS` | Par défaut : `7`. |
| `--photos` |  |
| `--drafts` |  |
| `--corrections` | Appliquer seulement des corrections préautorisées |
| `--value-ceiling-eur` `VALUE_CEILING_EUR` | Par défaut : `10`. |
| `--token-file` `TOKEN_FILE` | Nouveau fichier privé ; aucun secret sur stdout |

### `pokeprice-manage agent-list`

Lister les délégations sans leurs secrets

### `pokeprice-manage agent-revoke`

Révoquer immédiatement un accès agent

| Argument | Effet |
|---|---|
| `grant_id` |  |

### `pokeprice-manage agent-approve-corrections`

Autoriser un plan précis de rattachements catalogue

| Argument | Effet |
|---|---|
| `grant_id` |  |
| `--request-file` `REQUEST_FILE` |  |
| `--reason` `REASON` |  |

### `pokeprice-manage agent-schema`

Contrat OpenAPI agent hors ligne, sans ouvrir de base

### `pokeprice-manage serve`

Interface locale privée

| Argument | Effet |
|---|---|
| `--port` `PORT` | Par défaut : `3820`. |
| `--no-agent-api` | Désactiver les routes agent |
| `--host` `HOST` | Adresse d’écoute : 127.0.0.1 ou l’adresse Wi-Fi pour le réseau local Par défaut : `127.0.0.1`. |
| `--secure-cookie` | Cookie HTTPS derrière un proxy local |
| `--allowed-host` `ALLOWED_HOST` | Nom d’hôte autorisé derrière le proxy |
| `--no-auto-checks` | Ne pas lire la finition (Gemini) automatiquement après chaque saisie photo |

### `pokeprice-manage backup`

Sauvegarde SQLite cohérente et photos

| Argument | Effet |
|---|---|
| `output` | ZIP ; par défaut, archive datée dans data/backups |

### `pokeprice-manage backup-daily`

Sauvegarde quotidienne et restauration de contrôle

| Argument | Effet |
|---|---|
| `--force` |  |

### `pokeprice-manage backup-status`

État local et copie externe

### `pokeprice-manage backup-key`

Créer (une fois) la clé de chiffrement des copies Drive ; affiche la clé publique

### `pokeprice-manage backup-drive`

Copie Drive déterministe et restauration de contrôle

| Argument | Effet |
|---|---|
| `--remote` `REMOTE` | Par défaut : `gdrive`. |
| `--rclone` `RCLONE` |  |

### `pokeprice-manage backup-server-pull`

Rapatrier et vérifier la sauvegarde du serveur

| Argument | Effet |
|---|---|
| `--host` `HOST` | utilisateur@serveur |
| `--mirror` `MIRROR` | Archives rapatriées ; jamais un dossier de collection Par défaut : `data/oci-backups`. |
| `--ssh` `SSH` | Par défaut : `ssh`. |

### `pokeprice-manage backup-server-drive`

Copie Drive de la sauvegarde rapatriée du serveur

| Argument | Effet |
|---|---|
| `--host` `HOST` | utilisateur@serveur |
| `--mirror` `MIRROR` | Archives rapatriées ; jamais un dossier de collection Par défaut : `data/oci-backups`. |
| `--ssh` `SSH` | Par défaut : `ssh`. |
| `--remote` `REMOTE` | Par défaut : `gdrive`. |
| `--rclone` `RCLONE` |  |

### `pokeprice-manage backup-record-failure`

Signaler un échec de copie externe

### `pokeprice-manage backup-record-upload`

Enregistrer une copie Drive après contrôle de ses métadonnées

| Argument | Effet |
|---|---|
| `archive` |  |
| `file_id` |  |
| `size` |  |
| `--expected-sha256` `EXPECTED_SHA256` | SHA-256 capturé avant le téléversement |

### `pokeprice-manage restore`

Restaurer dans un nouveau dossier --data

| Argument | Effet |
|---|---|
| `archive` |  |

### `pokeprice-manage prices`

Relevé TCGdex des identités confirmées (prix et variantes)

| Argument | Effet |
|---|---|
| `--album` `ALBUM` | Limiter à un album (identifiant) |
| `--only-missing` | Seulement les cartes jamais relevées |
| `--limit` `LIMIT` |  |
| `--actor` `ACTOR` | Auteur inscrit dans l'historique Par défaut : `manage`. |

### `pokeprice-manage repair-prices`

Auditer les cotations perdues après précision de finition

| Argument | Effet |
|---|---|
| `--apply` | Appliquer le plan audité |
| `--copy-id` `COPY_ID` | Limiter aux exemplaires indiqués |

### `pokeprice-manage repair-pages`

Auditer les pages décalées par une couverture comptée comme page 1

| Argument | Effet |
|---|---|
| `--apply` | Appliquer le plan audité |

### `pokeprice-manage names`

Noms des éditions en plusieurs langues (TCGdex, une fois par édition)

| Argument | Effet |
|---|---|
| `--languages` `LANGUAGES` | Par défaut : `fr,en,de,it,es,pt`. |

### `pokeprice-manage forget`

Effacer un client de la vitrine (e-mail ou identifiant)

| Argument | Effet |
|---|---|
| `client` |  |
| `--reason` `REASON` | Par défaut : `Demande de la personne`. |

### `pokeprice-manage purge`

Appliquer les durées de conservation des données clients

### `pokeprice-manage export`

Export de la collection gérée

| Argument | Effet |
|---|---|
| `format` | Valeurs : `csv`, `json`, `html`. |
| `output` |  |

## `pokeprice-agent`

Client du pilote agent : appelle l'API déléguée, jamais la base.

Options communes :

| Argument | Effet |
|---|---|
| `--url` `URL` | Par défaut : `http://127.0.0.1:3820`. |
| `--token-file` `TOKEN_FILE` | Fichier privé du jeton ; aucune valeur secrète en argument |

### `pokeprice-agent capabilities`

### `pokeprice-agent corrections`

Lire les corrections préautorisées

### `pokeprice-agent apply-correction`

Appliquer un plan précis, sans champ libre

| Argument | Effet |
|---|---|
| `id` |  |
| `--expected-version` `EXPECTED_VERSION` |  |
| `--approval-sha256` `APPROVAL_SHA256` |  |

### `pokeprice-agent copies`

| Argument | Effet |
|---|---|
| `--query` `QUERY` |  |
| `--limit` `LIMIT` | Par défaut : `60`. |
| `--offset` `OFFSET` |  |

### `pokeprice-agent copy`

| Argument | Effet |
|---|---|
| `id` |  |

### `pokeprice-agent photo`

| Argument | Effet |
|---|---|
| `id` |  |
| `--side` `SIDE` | Valeurs : `front`, `back`. Par défaut : `front`. |
| `--output` `OUTPUT` |  |

### `pokeprice-agent prepare-lot`

| Argument | Effet |
|---|---|
| `--keep` `KEEP` | Par défaut : `1`. |
| `--maximum` `MAXIMUM` | Par défaut : `20`. |
| `--language` `LANGUAGE` |  |
| `--request-output` `REQUEST_OUTPUT` | Nouveau JSON prêt pour create-draft |
| `--title` `TITLE` | Par défaut : `Lot de doublons Pokémon`. |

### `pokeprice-agent create-draft`

| Argument | Effet |
|---|---|
| `--request-file` `REQUEST_FILE` |  |
| `--key` `KEY` |  |

### `pokeprice-agent draft`

| Argument | Effet |
|---|---|
| `id` |  |

### `pokeprice-agent package`

| Argument | Effet |
|---|---|
| `id` |  |
| `--output` `OUTPUT` |  |
