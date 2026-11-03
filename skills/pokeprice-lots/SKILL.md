---
name: pokeprice-lots
description: Analyser les doublons de la collection Pokémon, générer des suggestions de lots thématiques cohérents, maintenir une rotation glissante plafonnée de brouillons dans l'espace Ventes et publier les lots en vitrine sans jamais laisser de carte hors ligne.
---

# Rotation et suggestions de lots de vente

## Overview

Ce guide décrit `scripts/pokeprice_lots.py`, qui isole les exemplaires
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
- Un brouillon de vente n'altère pas la vitrine : les cartes y restent à l'unité
  jusqu'à la publication du lot.
- La publication d'un lot est atomique : toutes les cartes sont vérifiées avant
  la moindre dépublication, puis dépublication, publication et mise à jour de la
  vente se font dans une seule transaction. Si une carte est refusée ou si une
  étape échoue, rien n'est écrit et les annonces unitaires restent en ligne.
- La rotation n'annule jamais un brouillon dont le lot est en ligne.
- Un lot n'est jamais bradé : son prix ne descend pas sous la somme des cotes de
  ses cartes moins 15 % (variable d'environnement `POKEPRICE_LOT_MAX_MARGIN`,
  entre 0 et 50). `compose` plafonne sa décote à cette marge, sans décote par
  défaut, et `publish-to-storefront` refuse un lot sous ce plancher ou dont une
  carte n'a pas de cote (une cote nulle compte comme absente), en recalculant
  les cotes du jour. Avec `--remote`, la marge réglée sur le poste est transmise
  au serveur.

## Dependencies

- [`pokeprice-collection`](../pokeprice-collection/SKILL.md) : fait autorité sur
  l'accès au serveur de production, les sauvegardes et la base de référence.
- [`pokeprice-agent`](../pokeprice-agent/SKILL.md) : préservation du stock de
  collection (au moins un exemplaire conservé par référence).

## Choisir la base

Toute commande prend `--data` explicite ; le script n'a aucune base par défaut.

- Sur le serveur : `--data /srv/pokeprice/inventory`, la base de référence.
- Depuis le poste de travail, `--remote --data /srv/pokeprice/inventory` exécute
  la commande sur le serveur (hôte lu dans `~/.config/pokeprice/backup.env`) et
  y transmet le `--data` indiqué.
- Pour un essai : une base temporaire ou une sauvegarde restaurée, jamais
  `data/inventory/` du poste pour une écriture.

## Quick Start

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

Depuis le poste de travail :

```bash
uv run python scripts/pokeprice_lots.py --remote --data /srv/pokeprice/inventory --output /tmp/status.json status
```

Essai sur une copie temporaire :

```bash
uv run python scripts/pokeprice_lots.py --data /tmp/essai-lots/inventory --output /tmp/lots.json analyze
```

## Sous-commandes

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
`GEMINI_API_KEY`. Avec `--remote`, le prompt est interprété sur le poste de
travail et seule la recette part sur le serveur.

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
