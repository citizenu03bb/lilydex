# Séance de vérification préparée par un agent : réception

> **Statut :** rapport daté du 20 octobre 2026, selon un [protocole](AGENT_REVIEW_EVALUATION.md) fixé avant l'exécution. Il n'est pas tenu à jour.

**Un vrai client agent a préparé cinq contrôles recevables à partir des fiches
et photos d'un album réel figé.** Il a recherché les priorités, examiné les cinq
rectos et préparé des questions adaptées, dans l'ordre du classeur. Aucune
carte n'a été validée et aucune donnée de production n'a changé.

Le [protocole](AGENT_REVIEW_EVALUATION.md) précède l'exécution.
Le [relevé agrégé](evaluations/agent-review-2026-10-20.json) conserve les contrôles,
l'usage et les empreintes des traces privées. Les cartes, photos, réponses et
UUID réels restent hors Git, dans `outputs/agent-review/20261020T084224-5ca332/`.

## Résultat observé

| Mesure | Résultat |
|---|---|
| Client et modèle consigné | Codex CLI 0.155.1, `gpt-6-astra`, sélection native |
| Source | Instantané du 19 octobre, 432 exemplaires de l'album délégué |
| Exécutions modèle | Une, 108,72 secondes |
| Appels | 16 : droits, cinq pages, cinq détails, cinq photos |
| Erreurs d'outil | Zéro |
| Sélection, versions, emplacements, empreintes | Cinq sur cinq conformes |
| Questions utiles pour préparer un contrôle | Cinq sur cinq, revue qualitative par l'agent parent |
| Réponses physiques obtenues / cartes validées | Zéro / zéro |
| Base avant et après les appels | Toutes les tables identiques |

Le client a retenu les cinq priorités prévues sans exclure les cartes déjà
publiées. Les faits exposés par la projection sont identiques à ceux du même
album dans la sauvegarde migrée localement. Les comptes réels, sessions et
autres albums n'ont pas été copiés dans cette projection.

Quatre questions distinguent des marques de la carte de celles de sa protection.
La cinquième demande une observation à l'inclinaison, après avoir lu l'identité
visible. Une altération importante passe avant une question de finition. Le
numéro d'une carte voisine dans une image n'est pas attribué à l'exemplaire ciblé.
Chaque fiche propose une réponse indéterminée, signale l'absence de verso et
distingue les états enregistrés d'une confirmation physique.

La revue a comparé les cinq images effectivement remises aux observations et
questions produites. Elle est effectuée par l'agent parent qui a construit le
banc, sans aveugle ni évaluateur indépendant. Les lectures de petits numéros
restent des observations sur image ; aucune identité ou finition n'est validée.
Les termes techniques tels que `risk_cents` dans les explications peuvent être
simplifiés pour l'usage quotidien.

## Correction de réception, sans nouvel appel modèle

Le premier reçu automatique rejette le parcours : le banc attend des UUID seuls,
alors que le client a produit des libellés « page, pochette, nom, UUID » dans le
bon ordre. La consigne et le schéma ne précisaient pas cette restriction de format.
Il s'agit d'un décalage du contrat du banc, pas d'un parcours métier erroné.

Le lecteur de parcours accepte maintenant exactement un UUID connu par libellé,
sans changer l'ordre ni supprimer les doublons. Un libellé ambigu ou un UUID
inconnu reste rejeté ; le schéma décrit aussi explicitement le format préféré.
Un test couvre ces cas. La même réponse brute repasse ensuite les onze contrôles
automatiques, puis la revue des images. Le reçu initial et la réception corrigée
sont conservés séparément ; aucune réponse n'a été éditée, aucun modèle relancé.

## Droits, coût et limites

Le compte synthétique est lecteur, avec seulement `copies:read` et `photos:read`.
Les brouillons et l'API de gestion sont effectivement refusés. Le dépôt, la base
et SSH sont invisibles au client ; ses outils disponibles sont les quatre outils
de lecture du banc. L'isolation réseau face à un client hostile n'est pas évaluée.
Le jeton est révoqué et son rejet vérifié, le serveur arrêté, le HOME contenant
l'authentification temporaire et les bases supprimés. Les traces ne contiennent
pas le jeton. L'aperçu du rapport utilise un serveur séparé de lecture locale.

Usage annoncé par la CLI : 309 263 jetons d'entrée cumulés, dont 267 520 en cache,
et 3 452 jetons de sortie. Ces chiffres incluent les contextes répétés des appels ;
ce n'est pas la taille d'une seule consigne. L'abonnement Codex existant a servi,
sans nouvelle clé API ni modèle appelé côté serveur métier. Aucun coût en euros
ou temps humain gagné n'est déduit de ces mesures.

Le skill a été fourni explicitement. Cette seule exécution ne prouve ni son
avantage causal, ni sa découverte automatique, ni la qualité d'autres clients.
La simulation antérieure par l'agent parent ne remplace pas ce processus distinct ;
aucune des deux ne remplace une séance physique avec une personne.

Validation technique : 40 tests ciblés agent/API/CLI/banc réussis, Ruff et format
du skill validés. Aucun changement de schéma ni de route métier pour ce parcours.

## Suite retenue

Faire répondre une personne à ces cinq questions devant le classeur, en acceptant
l'indétermination, puis mesurer le temps total, les ambiguïtés et la relecture.
Les réponses passent par les fiches existantes avec les droits humains. Élargir
les droits ou déployer un orchestrateur supplémentaire n'est pas nécessaire pour
cette réception. Le client orchestre, le skill guide, l'application applique les
droits et conserve les faits.
