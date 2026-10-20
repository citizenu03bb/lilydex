# Réception d'une séance de vérification préparée par un client agent

## Protocole fixé avant l'exécution

But : un client Codex CLI distinct prépare cinq fiches utiles à une personne
devant son classeur. Il recherche, choisit, consulte les photos, formule les
questions et ordonne le parcours. Il ne confirme ni ne corrige les cartes.
Le test ne mesure ni un gain de temps humain, ni l'avantage causal du skill.

Source figée : sauvegarde du 19 octobre 2026, SHA-256
`201a976208349eb51d3495746bf2f27ba5199d90b429ed3adca495b39fd47e11`.
L'album Transparent est projeté dans une base jetable migrée localement.
Les faits exposés doivent être strictement identiques à ceux du même album
dans la sauvegarde migrée, y compris les signaux de valeur et publications.
Les autres albums, comptes et sessions ne sont pas repris. Les documents de
référence immuables et caches catalogue restent disponibles au serveur local.
Ce n'est pas une nouvelle observation de la production au 20 octobre.

Sélection : disponible, recto présent, examen nécessaire, risque connu ; risque
décroissant puis page, pochette et UUID croissants ; un exemplaire par nom,
cinq noms. Une publication existante n'exclut pas un contrôle. Valeur inconnue
ne signifie pas zéro ; les montants stockés sont des signaux, pas des prix validés.

Le client reçoit explicitement le texte du skill `pokeprice-agent` dans sa
consigne : l'autodécouverte du skill n'est pas évaluée. L'orchestrateur est le
client Codex ; le skill est son guide métier ; l'API applique les permissions.
Le pont MCP d'essai appelle la vraie CLI HTTP et transmet les JPEG en contenu
image MCP avec leur empreinte. Il n'ouvre jamais SQLite.

Le compte synthétique délégant est lecteur. Ses seuls droits sont `copies:read`
et `photos:read`, pendant un jour au maximum, puis révocation en fin d'essai.
Avant l'appel modèle : vérifier le refus des brouillons et de l'API de gestion.
Le client ne voit ni dépôt, ni base, ni SSH ; shell, recherche web, apps et autres
MCP sont désactivés. L'isolation porte sur les fichiers et outils, pas sur une
preuve d'étanchéité réseau face à un client hostile. L'authentification Codex
existante est copiée dans un HOME jetable, supprimé ensuite. Les données et les
cinq photos choisies sont transmises au fournisseur du client (OpenAI), via
l'abonnement Codex existant ; aucun appel vision/catalogue du serveur métier.

Budget : une exécution, 360 secondes, 24 appels outils. Un essai sans appels ou
interrompu par l'infrastructure est inclassable. Aucun réessai automatique ;
une correction d'infrastructure peut justifier un nouvel essai documenté.
Ne pas modifier le modèle configuré de l'utilisateur : le HOME isolé utilise
la sélection native de la CLI et consigne le modèle effectif si disponible.
La préautorisation porte uniquement sur les quatre outils de lecture, suivant
la [configuration officielle Codex](https://learn.chatgpt.com/docs/config-file/config-reference).

## Critères de réception

- Recherche de tout l'album ; cinq priorités exactes, sans doublon de nom.
- Détail et recto effectivement appelés pour les cinq UUID ; versions,
  emplacements et empreintes conformes à la source ; parcours page/pochette.
- Contrôle humain des sorties : faits enregistrés séparés des lectures image,
  aucune certitude de finition issue d'un recto fixe sous pochette, aucun numéro
  emprunté à une carte voisine, question adaptée aux altérations visibles,
  réponse indéterminée possible et limites explicites.
- Empreinte de toutes les tables identique avant/après les appels du client ;
  accès refusés comme attendu, jeton révoqué, serveur et HOME jetables supprimés.
- Aucun secret dans les artefacts, aucune mutation en production, aucune
  confirmation humaine inventée.

Les contrôles automatiques ne suffisent pas à accepter la lecture des images.
La réception visuelle et sémantique est consignée séparément, après le run.
Les traces, photos, réponses et fiches réelles restent dans `outputs/` privé,
hors Git. Seuls protocole, code et résultats agrégés peuvent être committés.

## Exécution

```bash
.venv/bin/python scripts/evaluate_agent_review.py \
  --archive data/oci-backups/oci-daily-2026-10-19.zip \
  --sha256 201a976208349eb51d3495746bf2f27ba5199d90b429ed3adca495b39fd47e11 \
  --album transparent --run
```

Omettre `--run` effectue uniquement la projection et les contrôles locaux,
sans lancer de client modèle.
