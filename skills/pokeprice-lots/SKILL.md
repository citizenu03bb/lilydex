---
name: pokeprice-lots
description: Analyser les doublons de la collection Pokémon, générer des suggestions de lots thématiques cohérents, maintenir une rotation glissante plafonnée de brouillons dans l'espace Ventes et publier les lots en vitrine sans jamais laisser de carte hors ligne. Par défaut, un agent passe par l'API agent (`pokeprice-agent lots-*` ou `pokeprice_lots.py --api`) ; l'accès opérateur au serveur n'est qu'un repli.
---

# Rotation et suggestions de lots de vente

## Overview

Ce guide décrit l'outil des lots, en deux chemins : l'API agent, que suit un
agent ([Chemin agent](#chemin-agent--lapi)), et `scripts/pokeprice_lots.py` avec
`--data`, réservé à l'opérateur ([Chemin opérateur](#chemin-opérateur-repli)).
L'outil isole les exemplaires
excédentaires (doublons) de la collection, compose des regroupements
thématiques (Vintage Wizards of the Coast, Diamant & Perle / Platine, Dresseurs
et Objets, HeartGold SoulSilver, Brillantes…) et alimente l'espace privé
**Gestion → Ventes** avec une fenêtre glissante de brouillons, plafonnée à 5 par
défaut (`--max-drafts`).

Principes :

- Le meilleur exemplaire de chaque référence reste dans l'album.
- Seules entrent en lot les cartes à l'identité confirmée, chiffrées, sans revue
  en attente et sous le seuil de valeur (mêmes règles que `AgentService` :
  `identity_unconfirmed`, `price_incomplete`, `review_needed`, `valuable_card`).
  Une carte sans prix n'entre jamais en lot : elle figure dans la liste
  `to_price` (« à chiffrer ») du rapport.
- Seule exception : les énergies de base en vrac (fiche 0015) sont offertes en
  bonus, au plus 10 par lot et seulement tant que les frais de port du lot ne
  changent pas ([décision 0041](../../docs/decisions/0041-energies-offertes-dans-les-lots.md)).
  Le titre annonce « + N énergies offertes » ; le prix et le plancher portent
  sur les cartes cotées.
- Un brouillon de vente n'altère pas la vitrine : les cartes y restent à l'unité
  jusqu'à la publication du lot.
- La publication d'un lot est atomique : toutes les cartes sont vérifiées avant
  la moindre dépublication, puis dépublication, publication et mise à jour de la
  vente se font dans une seule transaction. Si une carte est refusée ou si une
  étape échoue, rien n'est écrit et les annonces unitaires restent en ligne.
- La rotation n'annule jamais un brouillon dont le lot est en ligne.
- Un lot n'est jamais bradé : son prix ne descend pas sous la somme des cotes de
  ses cartes moins la marge réglée par l'administrateur dans la gestion (15 %
  par défaut, entre 0 et 50, lue dans la base ; règle `lot_max_margin` / `lot_floor_cents` définie dans
  `src/pokeprice/pricing.py` et partagée avec `listings.py` et
  `marketplace_export.py`). `compose` plafonne sa décote à cette marge, sans
  décote par défaut, et `publish-to-storefront` refuse un lot sous ce plancher
  ou dont une carte n'a pas de cote (une cote nulle compte comme absente), en
  recalculant les cotes du jour. L'outil n'a ni option ni variable pour changer
  la marge ; par l'API comme sur le serveur, c'est celle de la base de production qui s'applique.
  La variable n'est lue qu'une fois, par le premier processus qui ouvre une
  base encore au schéma 26 (restauration d'une ancienne sauvegarde comprise) :
  ne la réglez pas vous-même, et faites vérifier la marge par l'administrateur
  dans les Réglages après une restauration
  ([décision 0042](../../docs/decisions/0042-marge-du-plancher-reglage-administrateur.md)).

## Dependencies

- [`pokeprice-collection`](../pokeprice-collection/SKILL.md) : fait autorité sur
  l'accès au serveur de production, les sauvegardes et la base de référence.
- [`pokeprice-agent`](../pokeprice-agent/SKILL.md) : préservation du stock de
  collection (au moins un exemplaire conservé par référence).

## Chemin agent : l'API

Un agent n'a besoin ni de `ssh`, ni de `sudo`, ni de la base : il appelle l'API
agent avec un jeton délégué par un administrateur
([fiche 0044](../../docs/decisions/0044-outil-des-lots-par-l-api-agent.md),
[contrat des routes](../../docs/AGENT_CONTROL.md#déléguer-loutil-des-lots)).
Trois permissions, demandées une à une : `lots:read` (gisement, état, plan,
vérification), `lots:compose` (créer, faire tourner, annuler, relever),
`lots:publish` (publier, retirer). Publier n'emporte pas composer. Un agent ne
crée, n'élargit ni ne prolonge jamais un accès, et aucune route ne touche à la
marge, à l'âge de rotation ni aux dérogations.

> **Production.** Les lots de production passent par l'API. L'agent des lots
> tourne sous un utilisateur local dédié du poste de l'opérateur, qui ne détient
> que le jeton des lots : ni clé `ssh`, ni `sudo`, ni compte sur le serveur.
> L'accès opérateur est réservé à l'opérateur. La clé lots expire au bout de
> 7 jours ; seul un administrateur la renouvelle.

Deux façons équivalentes d'appeler les mêmes routes, avec la même URL et le
même fichier de jeton (mode 0600) :

- `pokeprice-agent lots-pool|lots-status|lots-plan|lots-publication|lots-compose|lots-rotate|lots-cancel|lots-raise|lots-publish|lots-unpublish` :
  une sous-commande par opération, réponse JSON sur la sortie standard ;
- `pokeprice_lots.py --api` : mêmes sous-commandes que le script
  (`analyze`, `status`, `compose`, `rotate`, `publish-to-storefront`), sans
  base ni accès au serveur.

L'URL vient de `--url` ou `POKEPRICE_AGENT_URL`, le jeton de `--token-file` ou
`POKEPRICE_AGENT_TOKEN_FILE`.

```bash
export POKEPRICE_AGENT_URL=https://SERVEUR
export POKEPRICE_AGENT_TOKEN_FILE=/chemin/prive/lots-doublons.token
uv run pokeprice-agent lots-status
uv run python scripts/pokeprice_lots.py --api --output /tmp/status.json status
```

Avec `--api`, `--actor` et `--max-drafts` sont refusés (l'auteur est l'accès,
le plafond vient du serveur), de même que `--scope all` (seuls les doublons
entrent dans un lot) ; `--data` n'y sert pas.

### Parcours

1. **Lire** : `lots-status` (brouillons, lots en ligne, `cap_used`,
   `blocked_by`, `due_online`) puis `lots-pool` (gisement, cartes « à
   chiffrer »). Les cartes sans prix, non confirmées ou à examiner n'entrent
   jamais en lot.
2. **Planifier** : `lots-plan --recipe-file recette.json` renvoie les cartes,
   les énergies offertes, le prix demandé, le plancher et un `plan_id`. Le
   serveur compose : le client ne choisit ni cartes, ni énergies offertes, ni
   plancher, et un champ inconnu de la recette est refusé.
3. **Composer** : `lots-compose --recipe-file recette.json --plan-id PLAN_ID`
   crée le brouillon. `--asking-cents` ne fait que relever le prix. Un prix
   sous le plancher du jour est relevé au plancher (`raised_to_floor`) : un
   agent n'a aucune dérogation, ni file de demandes ; le plancher absolu de
   0,50 € tient.
4. **Vérifier** : `lots-publication SALE_ID` dit si le brouillon est publiable
   et donne sa version ; la vérification est obligatoire, le serveur la refait
   dans la transaction de publication.
5. **Publier** : `lots-publish SALE_ID --expected-version N` est une simulation ;
   `--apply` écrit. Les annonces unitaires des cartes sont retirées et le lot
   publié ensemble ; un refus n'écrit rien.
6. **Retirer** : `lots-unpublish LISTING_ID --expected-version N --reason …`
   retire une annonce de lot de l'outil. Ses cartes d'au moins 1 € au prix du
   jour relevé au plancher reviennent seules en vitrine dans la même
   transaction (`relisted`) ; les autres (`not_relisted`, avec un motif)
   retournent au gisement pour le prochain lot. `lots-cancel` et `lots-raise`
   annulent ou relèvent un brouillon de l'outil. Ils ne touchent jamais un
   brouillon fait à la main, ni une annonce d'une seule carte (404).

### Rotation

`lots-rotate` est une simulation ; `--apply` écrit (`--limit` baisse le nombre
de lots créés). Elle annule d'abord les brouillons invalides puis les plus
anciens, sans jamais toucher un brouillon dont le lot est en ligne ni un
brouillon fait à la main.

Avec `lots:compose` et `lots:publish`, elle remplace aussi les lots en ligne de
l'outil invendus depuis plus que l'âge de rotation (14 jours par défaut,
réglage de l'administrateur), du plus ancien au plus récent : retrait de
l'annonce, annulation du brouillon, nouvelle composition, publication, un lot
par transaction. Le remplaçant reprend le moins possible de cartes payantes du
lot remplacé et n'est jamais exactement le même (`no_fresh_replacement`,
`no_replacement` : le lot reste en ligne). Les cartes du lot remplacé que le
remplaçant ne reprend pas suivent la règle du retrait : seules en vitrine à
partir de 1 € au prix du jour relevé au plancher, sinon au gisement ; chaque
remplacement liste ses `relisted` et `not_relisted`. Ces annonces unitaires ne
comptent pas dans le quota des lots publiés. Sans `lots:publish`, la rotation
signale ces lots sous `due_online` sans y toucher. Elle ne baisse jamais un
prix.

### Quotas

Par accès et par jour : 5 brouillons actifs au plus (lots en ligne et brouillons
faits à la main compris), 20 lots créés, 10 lots publiés (remplacements
compris, qui comptent aussi un lot créé). `pool`, `plan`, `compose`, `rotate` et
`publish` relisent toute la collection et partagent six appels par minute.

### Réessayer, et lire les erreurs

Chaque écriture (`lots-compose`, `lots-rotate`, `lots-publish`) porte une clé
d'idempotence, neuve par défaut. Quand l'appel échoue sans réponse sûre
(réseau, délai), le client affiche la clé sur la sortie d'erreur : relancez la
**même commande** avec `--key CLÉ`. Le serveur rejoue alors la réponse
enregistrée (`replayed: true`) au lieu d'écrire deux fois. Une nouvelle clé
sur un nouveau constat, jamais sur une autre requête : même clé et autre corps
donnent 409 `idempotency_conflict`.

| Réponse | Sens | Prochain geste |
|---|---|---|
| 409 `stale_plan` | la collection a changé depuis le plan | `lots-plan` à nouveau, puis `lots-compose` avec le nouveau `plan_id` |
| 409 `version_conflict` | la version du brouillon ou de l'annonce a changé | relire (`lots-status`, `lots-publication`), reprendre avec la version lue |
| 409 `draft_cap` | 5 brouillons actifs | `lots-rotate`, ou `lots-cancel` d'un brouillon de l'outil ; jamais d'annulation à la main d'un brouillon fait à la main |
| 409 `online_lot` | le brouillon est déjà en ligne | rien à publier ; `lots-unpublish` pour le retirer |
| 409 `idempotency_conflict` | la clé a déjà servi à une autre requête | ne pas réutiliser cette clé pour ce corps |
| 409 `hand_made_sale`, `sale_in_progress` | une vente faite à la main ou réservée porte ces cartes | rien n'est retiré ; laisser la personne trancher |
| 422 `not_publishable` | une carte a changé (à examiner, sans cote, non confirmée) | `lots-publication` pour le motif ; la corriger dans le parcours de revue, puis recomposer |
| 422 `price_lowered` | `--asking-cents` sous le prix calculé | relever, jamais baisser |
| 404 | brouillon ou annonce absent, fait à la main, ou d'une seule carte | ne pas insister : hors du périmètre de l'outil |
| 429 `draft_quota`, `publish_quota` | quota du jour atteint | s'arrêter jusqu'au lendemain |
| 429 `refusal_quota` | trop de refus journalisés | s'arrêter et lire les refus au lieu de relancer |
| 429 avec `Retry-After` | débit dépassé | attendre ce délai (le client l'affiche), puis relancer avec la même clé |
| 401, 403 | accès révoqué, expiré, ou permission manquante | s'arrêter : seul l'administrateur délègue ou renouvelle |

Un refus d'un lot sous le plancher ne devient jamais une demande pour une
personne : l'agent relève le prix ou laisse le lot.

## Chemin opérateur (repli)

`scripts/pokeprice_lots.py` avec `--data` ouvre lui-même la base : il se lance
là où elle vit, sur le serveur sous le compte du service, ou sur une base
d'essai. Ce chemin, qui peut tout faire sur la base, est réservé à l'opérateur ;
un agent n'en dépend pas et suit le chemin ci-dessus. Le script n'a pas de mode
`ssh` : `--api` et `--data` sont ses deux seuls modes. Les sous-commandes et
leurs paramètres ci-dessous valent pour ce chemin ; avec `--api`, les mêmes noms
appellent les routes décrites plus haut.

### Choisir la base

Toute commande prend `--data` explicite ; le script n'a aucune base par défaut.

- Sur le serveur : `--data /srv/pokeprice/inventory`, la base de référence.
- Pour un essai : une base temporaire ou une sauvegarde restaurée, jamais
  `data/inventory/` du poste pour une écriture.

## Quick Start (chemin opérateur)

Sur le serveur, toujours une simulation (`--dry-run`) avant l'écriture :

```bash
# 1. État de la fenêtre de rotation
pokeprice_lots.py --data /srv/pokeprice/inventory --output /tmp/status.json status

# 2. Doublons disponibles, lots candidats et cartes à chiffrer
pokeprice_lots.py --data /srv/pokeprice/inventory --output /tmp/lots.json analyze

# 3. Rotation simulée, puis appliquée
pokeprice_lots.py --data /srv/pokeprice/inventory --output /tmp/rotation.json rotate --dry-run
pokeprice_lots.py --data /srv/pokeprice/inventory --output /tmp/rotation.json rotate
```

`pokeprice_lots.py` désigne `scripts/pokeprice_lots.py` lancé avec le Python de
l'installation (sur le serveur : `/opt/pokeprice/.venv/bin/python
/opt/pokeprice/scripts/pokeprice_lots.py`, sous l'utilisateur `pokeprice`).

Essai sur une copie temporaire :

```bash
uv run python scripts/pokeprice_lots.py --data /tmp/essai-lots/inventory --output /tmp/lots.json analyze
```

## Sous-commandes

Elles valent pour `pokeprice_lots.py` avec `--data` (chemin opérateur) et, avec
`--api`, pour les mêmes noms par l'API, dont les écarts sont dans le chemin
agent : pas de dérogation au plancher, prix relevé au lieu d'être refusé,
doublons seuls, auteur et plafond fixés par le serveur.

### `analyze`

Isole les exemplaires excédentaires au-delà de l'exemplaire conservé, écarte les
cartes non éligibles et regroupe les autres par bloc ou usage :
`vintage_wotc`, `dp_platine`, `dresseurs`, `hgss`, `brillantes`, `energies`…

Le rapport contient :

- `lots` : lots candidats, avec prix demandé et valeur de référence ;
- `excluded` : doublons écartés, avec leurs motifs ;
- `to_price` : doublons sans prix, à chiffrer avant tout lot.

Paramètre : `--max-per-lot <N>` (défaut : 20).

### `status`

Inspecte les brouillons de vente :

- nombre de brouillons actifs et capacité restante sous le plafond ;
- `is_valid` : faux si une carte a été réservée, vendue ou supprimée ;
- `online_listing_id` : annonce de lot en ligne qui porte les cartes du
  brouillon, le cas échéant.

Paramètre : `--max-drafts <N>` (défaut : 5).

### `rotate`

Applique la rotation glissante :

- si les brouillons existants et les nouveaux lots dépassent le plafond, les
  brouillons invalides sont annulés d'abord, puis les plus anciens ;
- un brouillon dont le lot est en ligne n'est jamais annulé (rapport :
  `online_drafts_kept`). Il compte dans le plafond : s'il ne reste pas de place,
  moins de lots sont créés (rapport : `lots_skipped_for_capacity`) ;
- annulations et créations se font dans une seule transaction.

Paramètres :

- `--max-drafts <N>` : plafond de brouillons actifs (défaut : 5) ;
- `--limit <N>` : nombre de nouveaux lots à intégrer (défaut : le plafond) ;
- `--dry-run` : détaille annulations et créations sans rien écrire ;
- `--actor <nom>` : auteur tracé dans l'historique (défaut : `pokeprice-lots`).

### `compose`

Compose un lot sur mesure à partir d'une recette JSON (`LotCompositionRecipe`)
ou d'un prompt en langage naturel interprété par Gemini (Structured Outputs).
Le modèle est la constante `DEFAULT_GEMINI_MODEL` du script, remplaçable par la
variable d'environnement `POKEPRICE_LOTS_GEMINI_MODEL` ; la clé est lue dans
`GEMINI_API_KEY`. Le paquet `google-genai` vient avec l'option `web` ou `cli`
(`uv run --extra web python scripts/pokeprice_lots.py … compose`). Avec `--api`, le prompt est interprété sur le poste
de l'agent et seule la recette part au serveur ; avec `--data`, là où le script
tourne.

Les filtres de la recette s'appliquent au gisement éligible : une carte sans
prix, non confirmée, à revoir ou de valeur n'entre jamais dans le lot composé.

Paramètres :

- `--prompt "<texte>"` ou `--recipe "<json_ou_fichier>"` (la recette évite tout
  appel réseau) ;
- `--scope duplicates|all` : doublons seuls (défaut) ou aussi les exemplaires
  d'album, marqués `from_album` ;
- `--create-draft` : enregistre le lot en brouillon de vente ;
- `--dry-run`, `--actor <nom>`.

```bash
pokeprice_lots.py --data /srv/pokeprice/inventory --output /tmp/pepites.json \
  compose --recipe /tmp/recette-pepites.json --dry-run
```

### `publish-to-storefront`

Remplace les annonces unitaires des cartes d'un brouillon par une seule annonce
de lot en vitrine :

1. vérifie le brouillon (statut `draft`, au moins deux cartes, chacune cotée,
   prix fixé, au moins égal au plancher de 0,50 € et au plancher anti-bradage)
   et chaque carte avec la règle de `display_price`
   appliquée par `Listings.publish(lot=True)` : identité confirmée, carte
   disponible, absente de tout autre lot en ligne ;
2. au moindre refus, s'arrête avec la liste des motifs, sans rien retirer ;
   quand le plancher anti-bradage est le seul motif, inscrit aussi, pour l'opérateur seulement, une demande
   de dérogation que la gestion tranche (`floor_request_id` dans le rapport,
   jamais en `--dry-run`, [décision 0030](../../docs/decisions/0030-derogations-plancher.md)) ;
3. sinon, dans une seule transaction : dépublie les annonces unitaires, publie
   le lot et consigne l'annonce dans le dossier de vente (canal `Vitrine`).

Paramètres :

- `--sale-id <UUID>` : publie ce brouillon ;
- `--all` : publie chaque brouillon valide hors ligne, chacun
  de façon atomique ; le rapport sépare `published`, `refused` et `skipped` ;
- `--dry-run`, `--actor <nom>`.

```bash
pokeprice_lots.py --data /srv/pokeprice/inventory --output /tmp/pub.json publish-to-storefront --all --dry-run
pokeprice_lots.py --data /srv/pokeprice/inventory --output /tmp/pub.json publish-to-storefront --sale-id <UUID>
```

## Workflow

Pour un agent, le parcours est celui du [chemin agent](#parcours) ; la suite
décrit le chemin opérateur.

1. **Diagnostic** : `status` pour compter les brouillons, repérer les invalides
   et ceux déjà en ligne.
2. **Revue** : `analyze`, puis lecture du rapport ; les cartes de `to_price` se
   chiffrent dans l'application avant de pouvoir entrer en lot.
3. **Rotation** : `rotate --dry-run`, vérification des annulations projetées,
   puis `rotate`.
4. **Vitrine** : `publish-to-storefront --all --dry-run`, revue des refus, puis
   la commande sans `--dry-run`.

## Common Mistakes

- **Omettre `--data` ou viser la mauvaise base** : le script refuse de démarrer
  sans `--data`. Vérifier le chemin avant toute écriture ; `data/inventory/` du
  poste est une copie.
- **Confondre brouillon de vente (`sales`) et publication de vitrine
  (`listings`)** : un brouillon ne touche pas la vitrine. Ne pas dépublier les
  cartes à la main pour préparer un lot : `publish-to-storefront` s'en charge.
- **Annuler à la main un brouillon dont le lot est en ligne** : l'annonce
  resterait en vitrine sans dossier de vente. Retirer d'abord l'annonce de lot.
- **Forcer un lot avec des cartes sans prix** : elles sont écartées du gisement
  et listées « à chiffrer ». Les chiffrer, puis relancer `analyze`.
