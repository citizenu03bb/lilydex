---
name: pokeprice-lots
description: Analyser les doublons de la collection Pokémon, générer des suggestions de lots thématiques cohérents et maintenir une rotation glissante plafonnée à 5 brouillons dans l'espace Ventes du serveur de production.
---

# Rotation et suggestions de lots de vente

## Overview

Ce skill permet d'analyser systématiquement les exemplaires excédentaires (doublons) de la collection de référence des Cartes de Lily, de composer des regroupements thématiques cohérents (Vintage Wizards of the Coast, Bloc Diamant & Perle / Platine, Dresseurs et Objets, HeartGold SoulSilver, Brillantes, etc.) et d'alimenter l'espace privé **Gestion → Ventes** avec une fenêtre glissante de **5 brouillons au maximum**.

Lors de chaque renouvellement périodique (~toutes les 2 semaines) :
- Les cartes restent en vitrine individuelle sans perturbation tant que le lot n'est pas vendu.
- Si le quota de 5 brouillons actifs est atteint lors de l'ajout de nouveaux lots, une rotation **FIFO** (First In, First Out) annule les brouillons les plus anciens non concrétisés (`status='cancelled'`).
- La vente d'un lot (`status='reserved'`) retire automatiquement les exemplaires de la vitrine au moment précis de la transaction.

## Dependencies

- [`pokeprice-collection`](../pokeprice-collection/SKILL.md) : Fait autorité sur l'accès et les règles de gestion du serveur de production (`/srv/pokeprice/inventory/collection.sqlite3`).
- [`pokeprice-agent`](../pokeprice-agent/SKILL.md) : Définit les principes de préservation du stock de collection (au moins 1 exemplaire conservé par référence).

## Quick Start

```bash
# 1. Vérifier l'état de la fenêtre de rotation (max 5 brouillons actifs)
uv run python scripts/pokeprice_lots.py --remote --output /tmp/status.json status

# 2. Analyser les doublons disponibles et prévisualiser les lots candidats
uv run python scripts/pokeprice_lots.py --remote --output /tmp/lots_candidats.json analyze

# 3. Simuler la rotation (dry-run : aucun changement en base)
uv run python scripts/pokeprice_lots.py --remote --output /tmp/rotation_preview.json rotate --dry-run

# 4. Appliquer la rotation sur le serveur de production
uv run python scripts/pokeprice_lots.py --remote --output /tmp/rotation_applied.json rotate
```

Pour une exécution locale sur une copie de base de données :
```bash
uv run python scripts/pokeprice_lots.py --data data/inventory --output /tmp/lots.json analyze
```

## Utility Scripts

Le script CLI [`scripts/pokeprice_lots.py`](file:///home/pat/Projects/pokeprice/scripts/pokeprice_lots.py) propose cinq sous-commandes :

### `analyze`
Parcourt la collection pour isoler les exemplaires excédentaires au-delà du premier exemplaire conservé, puis les regroupe par affinité de bloc ou d'usage :
- `vintage_wotc` : Set de Base, Jungle, Fossile (1999-2000).
- `dp_platine` : Génération 4 Sinnoh (2007-2009).
- `dresseurs` : Supporters, objets et stades utilitaires pour les joueurs.
- `hgss` : Génération 2 Johto (2010).
- `brillantes` : Cartes holographiques ou reverse en surplus.
- `energies` : Vracs d'énergies de base.

Paramètres :
- `--max-per-lot <N>` : Nombre maximal de cartes par lot (défaut : 20).
- `--output <fichier.json>` : Fichier obligatoire enregistrant les propositions de lots et leur valorisation.

### `status`
Inspecte la table `sales` de la base de référence :
- Indique le nombre de brouillons actifs actuels et la capacité restante (sur 5).
- Vérifie l'intégrité de chaque carte d'un lot (alerte si une carte a été réservée, vendue ou supprimée entre-temps).
- `--output <fichier.json>` : Enregistre le rapport d'état.

### `rotate`
Applique la rotation glissante des lots :
- Si la somme des brouillons existants et des nouveaux lots dépasse 5, les plus anciens brouillons sont annulés avec traçabilité dans le journal (`sale_events`).
- Insère les nouveaux lots au statut `draft` dans `sales` et `sale_items`.
- `--dry-run` : Simule l'opération et détaille les annulations/créations projetées sans rien écrire.
- `--limit <N>` : Nombre de nouveaux lots à intégrer (défaut : 5).
- `--actor <nom>` : Auteur tracé dans l'historique des ventes (défaut : `pokeprice-lots`).

### `compose`
Compose un lot sur-mesure à partir d'un prompt en langage naturel interprété par Gemini (`gemini-3.8-flash` via Structured Outputs) ou d'une recette typée JSON directe :
- Interprète les intentions sémantiques et subjectives (*pépites sous-évaluées*, *panaché 1ère génération*, *cartes reverses*, *petits budgets*) en un schéma typé `LotCompositionRecipe`.
- Applique des filtres durs déterministes (état minimal, finitions, blocs, exclusions) et des heuristiques de scoring sans jamais halluciner d'exemplaires.
- Évite les doublons de Pokémon dans le lot (`diversity: maximize_species`) et applique une décote commerciale cohérente.

Paramètres :
- `--prompt "<texte>"` : Requête en langage naturel (ex: `"trouve-moi les pépites sous-évaluées"`).
- `--recipe "<json_ou_fichier>"` : Recette JSON structurée directe (optionnel, permet d'éviter l'appel réseau ou pour les tests).
- `--scope duplicates|all` : Périmètre de sélection des cartes (`duplicates` par défaut, ou `all` pour inclure exceptionnellement les cartes uniques d'album).
- `--create-draft` : Enregistre le lot en tant que brouillon de vente dans `sales`.
- `--dry-run` : Simule la composition ou la création sans écriture en base.
- `--actor <nom>` : Auteur tracé dans l'historique (défaut : `pokeprice-lots`).
- `--output <fichier.json>` : Enregistre le lot généré, la recette, les métadonnées photos (`photo`, `page`, `position`, `from_album`) et le bloc de diagnostic transparent `stock_diagnostic` en cas de stock insuffisant ou ciblé.

```bash
# Exemple de composition par prompt (simulation sur doublons)
uv run python scripts/pokeprice_lots.py --remote --output /tmp/pepites.json compose --prompt "trouve-moi les pépites sous-évaluées"

# Exemple explorant toute la collection (avec cartes d'album marquées)
uv run python scripts/pokeprice_lots.py --remote --output /tmp/pikachus_all.json compose --prompt "lot de 3 cartes Pikachu au meilleur marché-prix" --scope all

# Exemple avec création immédiate du brouillon de vente
uv run python scripts/pokeprice_lots.py --remote --output /tmp/pepites_draft.json compose --prompt "panaché de 10 cartes de la 1ère génération" --create-draft
```

### `publish-to-storefront`
Bascule un brouillon de vente (`sales`) en annonce de lot sur la vitrine publique (`listings`) :
- Dépublie proprement les annonces individuelles des cartes du lot (évite l'erreur de contrainte unique).
- Publie le lot sous une seule annonce publique avec son titre et son prix en vitrine.
- Met à jour le dossier de vente dans l'espace Ventes pour y consigner l'identifiant de l'annonce vitrine.

Paramètres :
- `--sale-id <UUID>` : Identifiant du brouillon de lot à publier.
- `--dry-run` : Simule l'opération (liste les dépublications unitaires et le lot projeté sans rien écrire).
- `--actor <nom>` : Auteur tracé dans l'historique (défaut : `pokeprice-lots`).
- `--output <fichier.json>` : Enregistre le rapport de publication.

```bash
uv run python scripts/pokeprice_lots.py --remote --output /tmp/pub.json publish-to-storefront --sale-id <UUID>
```

## Workflow

### 1. Diagnostic bimensuel
1. Lancer `status` pour vérifier combien de brouillons sont encore en attente et s'ils sont tous valides.
2. Si un brouillon a une carte réservée entre-temps via la vitrine, il apparaît avec `is_valid: false`.

### 2. Revue des candidats
1. Lancer `analyze` pour mettre à jour la liste des doublons disponibles et leurs prix de référence.
2. Consulter le fichier JSON produit pour identifier les thèmes les plus attractifs du moment.

### 3. Simulation & Application
1. Lancer `rotate --dry-run` pour prévisualiser quels anciens brouillons seront remplacés par les nouveaux.
2. Exécuter `rotate` pour créer les brouillons sur le serveur.
3. Les lots apparaissent immédiatement dans l'interface de gestion sous **Ventes → Brouillons**, prêts à être exploités pour une publication sur les plateformes de vente (Vinted, Leboncoin, bourses).

## Common Mistakes

- **Confondre brouillon de vente (`sales`) et publication de vitrine (`listings`)** : Un brouillon de lot n'altère pas la vitrine publique. Ne pas dépublier manuellement les cartes de la vitrine pour préparer un lot de vente.
- **Modifier la collection locale au lieu de la production** : Ne jamais exécuter de commande d'écriture avec `--data data/inventory` en pensant modifier le site en production. Utiliser `--remote` depuis le poste de travail ou exécuter sur le serveur avec `--data /srv/pokeprice/inventory`.
- **Forcer plus de 5 brouillons** : Le plafond de 5 lots garantit la clarté du catalogue et le renouvellement régulier du stock.
