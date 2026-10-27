# Consignes pour les agents de code

Les cartes de Lily est développé en grande partie avec des agents de code. Ces règles
s'ajoutent à [CONTRIBUTING.md](CONTRIBUTING.md), qui fait foi.

## Données

- La collection de référence est sur le serveur de production
  (`/srv/pokeprice/inventory`). La base `data/inventory/` d'un poste de
  développement est une copie : n'y écrivez jamais une modification de la
  collection. Avant toute écriture, vérifiez quelle base est visée.
- Sur le serveur, toute commande `pokeprice-manage` prend `--data` explicite ;
  sans lui, elle viserait une autre base. La procédure d'exploitation est dans
  [skills/pokeprice-collection/SKILL.md](skills/pokeprice-collection/SKILL.md).
- Les essais se font sur une base temporaire ou une sauvegarde restaurée.

## Guides et parcours métier

Les guides versionnés vivent dans `skills/` et sont exposés via les liens
symboliques `.agents/skills` et `.codex/skills` pour la découverte automatique
par les clients agents (Pi, Codex, Antigravity) :

- [`pokeprice-collection`](skills/pokeprice-collection/SKILL.md) : exploitation
  de la collection par l'opérateur (serveur, sauvegardes, imports, délégations,
  approbation de corrections en lot) ;
- [`pokeprice-agent`](skills/pokeprice-agent/SKILL.md) : consultation déléguée
  d'un album via `pokeprice-agent`, préparation d'une séance de vérification
  dans l'ordre du classeur et brouillons de lots de doublons ;
- [`pokeprice-agent-prix`](skills/pokeprice-agent-prix/SKILL.md) : diagnostic
  des cartes sans prix et application des corrections catalogue préautorisées
  (`pokeprice-agent apply-correction`).

Pour accélérer le traitement des cartes « À identifier », « À vérifier » et
« À examiner », suivez le parcours décrit dans
[docs/RESOLUTION_CARTES.md](docs/RESOLUTION_CARTES.md).

## Code

- Lancez `uv run --extra web --extra dev pytest` avant chaque commit.
- Un test n'appelle aucun service réel et ne lit aucune clé.
- Commits en français, au format `type(portée): résumé`.
- Ne touchez pas aux fichiers scellés par empreinte :
  `docs/AGENT_EVALUATION_PROTOCOL.md` et `skills/pokeprice-agent/`.

## Documentation

- Au présent, sans date dans les pages qui décrivent le fonctionnement ;
  l'événement va dans `docs/JOURNAL.md`, la décision dans `docs/decisions/`.
- Une page réécrite rejoint `PAGES_VIVANTES` dans `scripts/check_docs.py`.
- Vocabulaire : [docs/GLOSSAIRE.md](docs/GLOSSAIRE.md). Les cartes de Lily désigne
  le produit, `lilydex` le dépôt, `pokeprice` le paquet Python.
- Rien de personnel dans le dépôt : ni nom, ni e-mail, ni adresse IP, ni
  identifiant de dossier Drive.
