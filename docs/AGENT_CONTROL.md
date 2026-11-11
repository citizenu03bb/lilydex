# Utiliser le pilote agent

> **Pour qui :** toute personne qui veut déléguer un album à un agent IA.
> **Vous y trouverez :** ce que l'agent peut faire et ne peut pas faire, le skill qui le guide, les commandes du client et les évaluations faites.
> **Statut :** en vigueur ; pilote technique. La délégation initiale est expliquée dans la [fiche 0012](decisions/0012-agent-brouillons.md), complétée pour les corrections préautorisées par la [fiche 0014](decisions/0014-corrections-agent-autorisees.md), puis pour l'autonomie maximale par la [fiche 0021](decisions/0021-autonomie-maximale.md).

Un agent peut consulter **un album délégué**, préparer
un lot prudent de doublons et créer un brouillon visible dans **Ventes**. Il
peut aussi lire les photos et télécharger le paquet d’annonce si ces accès ont
été accordés. Le client `pokeprice-agent` appelle uniquement l’API HTTP ; il
n’ouvre jamais la base de collection.

La personne décrit son objectif dans son client agent habituel. Celui-ci peut
utiliser les commandes ci-dessous pour rechercher, comparer et préparer son
résultat. Aucun nouveau modèle n’est appelé côté serveur. La qualité des
explications et le temps gagné doivent encore être évalués à l’usage ; le
client livré n’est pas un chatbot intégré au site.

Le [plan révisé](AGENT_CONTROL_PLAN.md) explique l’apport par rôle et les
extensions possibles. Les corrections de catalogue préautorisées passent par le parcours décrit ci-dessous.

La politique d'ensemble vise l'autonomie maximale des agents : ils identifient,
cotent, rangent, composent les lots et publient, sans attendre de clic, et
rendent chaque action annulable. Restent humains les paiements et
remboursements, les suppressions définitives, les messages libres aux clients,
tout prix sous le plancher anti-bradage et le plafond de délégation. Le guide
chapeau [pokeprice-autonome](../skills/pokeprice-autonome/SKILL.md) porte cette
politique ; la composition et la publication de lots passent par
[pokeprice-lots](../skills/pokeprice-lots/SKILL.md), par le client de l’API
agent (voir [Déléguer l’outil des lots](#déléguer-loutil-des-lots)) ; l’accès
opérateur au serveur est réservé à l’opérateur.

Le pilote décrit sur cette page reste un **périmètre d'évaluation** : son guide
scellé et son API déléguée ne publient, ne réservent et ne vendent rien. Ces
limites mesurent un usage précis ; elles ne bornent pas l'autonomie des autres
parcours.

## Agent et skill d'exploitation

Pour une demande de prix manquants, exposez le guide autonome
[pokeprice-agent-prix](../skills/pokeprice-agent-prix/SKILL.md). Il distingue
absence de lien, relevé non acquis et absence de cotation prouvée, puis décrit
l’application des plans déjà autorisés. Sa [réception](AGENT_PRICE_EVALUATION.md)
sépare les régressions du logiciel et l’évaluation du comportement d’un client.
Choisissez le guide selon le parcours ; le guide scellé conserve les consignes
et les résultats du pilote initial, sans servir de guide aux corrections.

Le guide versionné est [pokeprice-agent](../skills/pokeprice-agent/SKILL.md).
Il apprend au client à vérifier ses droits, respecter les quantités à conserver,
reprendre une création sans doublon et expliquer les décisions humaines restantes.
Le client agent conduit la conversation et choisit les appels ; la CLI exécute
ces appels HTTP ; le serveur décide ce qui est autorisé et enregistre les faits.
Le guide de maintenance `pokeprice-collection` garde un autre usage, avec un
accès opérateur plus large. Aucun accès opérateur n'est nécessaire au pilote.

Une installation cliente doit exposer seulement l'API déléguée et ce guide,
avec les données autorisées. Le skill ne protège pas une base ou des clés SSH
accessibles par ailleurs au même agent. Garder une seule source versionnée du
guide ; ses emplacements de découverte dépendent du client.

Le [protocole conversationnel](AGENT_EVALUATION_PROTOCOL.md) compare explicitement
le même usage avec et sans le guide, sur des données synthétiques et dans un
processus séparé des fichiers réels. Son adaptateur MCP est réservé au banc de
test ; il ne remplace pas la CLI ni n'étend les droits du pilote.
Le [rapport d'évaluation](AGENT_EVALUATION_RESULTS.md) consigne les quatre essais
réussis et les limites : le gain humain n'est pas mesuré.

## Préparer cinq contrôles dans un classeur

Le skill guide aussi une séance de vérification : l'agent cherche les priorités
dans l'album, relit les fiches et leurs photos, puis prépare des questions
concrètes dans l'ordre des pages et pochettes. Il distingue une information
enregistrée, ce qu'il peut lire sur l'image et ce qu'il reste à observer en main.
Une carte publiée peut demander un contrôle ; les exclusions d'un lot de vente
ne s'appliquent donc pas automatiquement à ce parcours.

Les permissions `copies:read` et `photos:read` suffisent, y compris pour un
lecteur. Les outils existants permettent cette préparation sans nouvelle route
d'écriture :

```bash
pokeprice-agent capabilities
pokeprice-agent copies --limit 100 --offset 0
pokeprice-agent copy UUID_EXEMPLAIRE
pokeprice-agent photo UUID_EXEMPLAIRE --side front --output /chemin/prive/recto.jpg
```

Le client doit pouvoir montrer l'image à son modèle : télécharger un fichier
seul ne prouve pas qu'il l'a examinée. Le [banc de réception](AGENT_REVIEW_EVALUATION.md)
teste ce parcours avec un vrai client isolé sur une copie figée de l'album réel.
La [réception de la séance de vérification](AGENT_REVIEW_RESULTS.md) accepte les cinq préparations,
après vérification des appels et des images, sans confirmation physique.
La préparation n'ajoute aucune confirmation physique ; la personne répond
ensuite dans les fiches existantes, avec ses propres droits. « Indéterminé »
reste une réponse utile. Le temps gagné et l'usage quotidien restent à mesurer.

## Installer et préparer l’accès

```bash
uv sync --extra web --extra dev
```

Le schéma est migré au prochain démarrage de l’application ou d’une
commande de gestion qui ouvre cette base. Avant mise à jour sur une installation
réelle, créer une sauvegarde cohérente avec la version précédente et la
restaurer dans un dossier temporaire selon [RECOVERY.md](RECOVERY.md). Les tests
de cette livraison ont utilisé des bases temporaires ; aucun accès réel n’est
créé automatiquement.

Sur la machine qui héberge la collection de référence, un opérateur disposant
de l’accès local crée une délégation. Le compte délégant doit être actif ; un
lecteur peut déléguer la consultation, un gestionnaire ou administrateur peut
également déléguer les brouillons et les corrections préautorisées. Seul un
administrateur délègue l’outil des lots (voir plus bas).

```bash
uv run pokeprice-manage --data data/inventory agent-create assistant-collection \
  --owner NOM_DU_COMPTE --album IDENTIFIANT_ALBUM \
  --client "Client agent choisi et fournisseur qui reçoit les données" \
  --days 7 --drafts --photos \
  --token-file /chemin/prive/assistant-collection.token
```

Le répertoire privé doit déjà exister. Le fichier est créé en mode `0600`,
sans écraser un fichier existant ; le secret n’est pas affiché. Il contient un
jeton de forte entropie, dont seul le condensat est conservé en base. Le fichier
doit être transmis au client par un canal privé si celui-ci est sur une autre
machine. Le garder hors du dépôt et des journaux.

Omettre `--drafts` pour la lecture seule et `--photos` pour un accès textuel.
La permission photo autorise la remise des images à ce client ; elle ne peut
pas empêcher le client de les envoyer à son propre modèle. `--client` documente
ce destinataire, sans constituer une restriction réseau après transmission.

Le plafond de valeur est de 10 € par défaut (`--value-ceiling-eur`). L’agent ne
peut pas l’augmenter. Le jeton expire après 7 jours par défaut, 30 au maximum.
Un changement de rôle ou la désactivation du délégant s’applique aux requêtes
suivantes ; le déclassement en lecteur retire immédiatement la création de
brouillons et les corrections, et tout déclassement sous administrateur retire
les permissions de l’outil des lots.

## Préparer un lot depuis le client agent

Configurer le client avec **l’URL de la collection de référence**, sans copier
sa base sur le poste client. HTTPS est obligatoire, sauf pour la boucle locale.
Sur le serveur lui-même, l’URL par défaut (`http://127.0.0.1:3820`) fonctionne :
l’application accepte la boucle locale en plus de son nom public.
Les redirections HTTP ne sont pas suivies et aucun cookie personnel n’est utilisé.

```bash
export POKEPRICE_AGENT_URL=https://VOTRE_SERVEUR
export POKEPRICE_AGENT_TOKEN_FILE=/chemin/prive/assistant-collection.token

uv run pokeprice-agent capabilities
uv run pokeprice-agent copies --query Pikachu --limit 20
uv run pokeprice-agent prepare-lot --language fr --keep 1 --maximum 20 \
  --title "Doublons français" --request-output /chemin/prive/lot-1.json
```

La préparation renvoie les exemplaires retenus, ceux conservés et les exclusions
avec leurs motifs. Le premier exemplaire éligible dans l’ordre page/pochette est
conservé ; les autres peuvent rejoindre le lot, sans fusionner leurs UUID.
La sélection est limitée à 20 cartes. Les observations inconnues, prix incomplets,
cartes de valeur, désaccords et cartes indisponibles ou déjà publiées sont exclus.
Un prix de référence ne devient jamais automatiquement le prix demandé du lot.

Les marques de distribution et de tampon doivent avoir été examinées pour
regrouper les impressions. Une collection partiellement documentée peut donc
ne proposer aucun doublon : les motifs précisent ce qui manque, sans inventer
une observation pour rendre le lot possible.

Le fichier JSON de requête est privé et contient la sélection avec les versions
examinées, un motif et un texte proposé. Il peut être relu ou modifié par le
client agent avant la création, dans les limites des droits accordés.

```bash
uv run pokeprice-agent create-draft \
  --request-file /chemin/prive/lot-1.json --key lot-1
uv run pokeprice-agent draft IDENTIFIANT_DU_LOT
uv run pokeprice-agent package IDENTIFIANT_DU_LOT \
  --output /chemin/prive/lot-1-annonce.zip
```

Après une réponse perdue, **réutiliser la même clé et le même fichier** : le
serveur retourne le même lot. Réutiliser la clé avec un autre contenu est refusé.
Les droits courants sont vérifiés avant de retourner un ancien résultat.
Une nouvelle création revérifie les versions, les observations et les valeurs,
la disponibilité, la portée et le nombre d’exemplaires à conserver ensemble.
Un conflit ne produit aucun brouillon partiel.

## Appliquer des corrections autorisées

L’opérateur crée un accès avec `--corrections`. Ce droit permet seulement
l’application de plans enregistrés pour cette délégation. Il ne donne aucun
accès général de modification et ne permet pas à l’agent d’autoriser son plan.
Le guide scellé `pokeprice-agent` conserve son périmètre initial. Le guide
[pokeprice-agent-prix](../skills/pokeprice-agent-prix/SKILL.md) décrit la conduite
cliente de ce parcours ; la [décision sur les corrections](decisions/0014-corrections-agent-autorisees.md)
explique son autorisation.

L’opérateur relit les références et les photos, recueille l’accord de la personne,
puis prépare un fichier JSON privé. Chaque ligne contient `id`, `expected_version`
et `catalog_id` ; `number` permet une correction explicite de la référence complète,
et `refresh_price` indique si le relevé de prix est autorisé. Le serveur relit
TCGdex et refuse une différence de nom, de numéro complet ou de PV.

```bash
pokeprice-manage --data /CHEMIN_COLLECTION agent-approve-corrections IDENTIFIANT_ACCES \
  --request-file /chemin/prive/corrections.json \
  --reason "Rattachements au catalogue et relevés approuvés par le propriétaire"
pokeprice-agent corrections
pokeprice-agent apply-correction UUID_EXEMPLAIRE \
  --expected-version VERSION_EXAMINEE --approval-sha256 EMPREINTE_AUTORISEE
```

L’enregistrement du plan ne modifie aucune fiche. L’agent transmet seulement
la version examinée et l’empreinte du plan. Le serveur contrôle les droits,
l’album et la version avant l’écriture. Une fiche modifiée entre-temps demande
une nouvelle revue. Après une réponse perdue, la même requête retourne le même
reçu sans répéter l’écriture ; la révocation s’applique aussi à cette reprise.

La cotation provient du relevé natif en euros et reste une référence de marché,
pas un prix demandé. Une cotation absente, une variante incompatible ou un produit
marchand signalé incorrect laisse le prix inconnu. Un prix déjà présent ne peut
pas être écrasé par ce parcours. Les fiches, relevés et reçus conservent la source,
son empreinte et l’identité `agent:IDENTIFIANT_ACCES`.

L’accord porte sur le rattachement au catalogue, pas sur une observation en main.
Les observations physiques et l’état enregistré sont conservés ; le changement
d’identité invalide la confirmation globale de variante selon les règles de la
fiche. Le reçu indique qu’aucune confirmation physique n’a été créée.

## Déléguer l’outil des lots

L’outil des lots de doublons passe par l’API agent, avec trois permissions
distinctes :

| Permission | Option | Opérations annoncées |
|---|---|---|
| `lots:read` | `--lots-read` | `lots-pool`, `lots-status`, `lots-plan`, `lots-publication` |
| `lots:compose` | `--lots-compose` | `lots-compose`, `lots-rotate`, `lots-cancel`, `lots-raise` |
| `lots:publish` | `--lots-publish` | `lots-publish`, `lots-unpublish` |

Publier n’emporte pas le droit de composer : chaque permission se demande à
part. Ces permissions portent sur **toute la collection**, quel que soit
l’album nommé par l’accès ; `agent-create` le rappelle sur la sortie
d’erreur et `/capabilities` l’indique (`lots.scope` vaut `collection`).
`/capabilities` annonce ces opérations seulement à un accès qui détient la
permission correspondante ; un accès sans permission lots n’en voit aucune
trace. Chaque opération a sa route et sa sous-commande de `pokeprice-agent`
(voir [Client en ligne de commande](#client-en-ligne-de-commande-des-lots)).
La production des lots passe par ces routes ([fiche
0044](decisions/0044-outil-des-lots-par-l-api-agent.md)). L’agent des lots
tourne sous un utilisateur local dédié du poste de l’opérateur, qui ne détient
que le fichier du jeton des lots : ni clé `ssh`, ni `sudo`, ni compte sur le
serveur. La clé lots de production est déléguée pour 7 jours
(`--days 7`, la valeur par défaut d’`agent-create`) ; à l’échéance, un administrateur en crée une nouvelle avec
`agent-create`, l’agent ne la renouvelle jamais lui-même.

```bash
uv run pokeprice-manage --data /CHEMIN_COLLECTION agent-create lots-doublons \
  --owner COMPTE_ADMINISTRATEUR --album IDENTIFIANT_ALBUM \
  --lots-read --lots-compose --lots-publish \
  --client "Client agent et fournisseur qui reçoit les données" \
  --token-file /chemin/prive/lots-doublons.token
```

Règles vérifiées par le serveur :

- **Administrateur seulement, deux fois.** La création refuse une permission
  lots si le compte délégant n’est pas un administrateur actif ; chaque appel
  la retire si ce compte n’est plus administrateur, et refuse tout si le compte
  est désactivé.
- **Un accès, un usage.** Un accès lots ne se combine ni avec `--drafts`, ni
  avec `--corrections`, ni avec `--assistant`.
- **Plafond de valeur.** 10 € par carte par défaut, 20 € au plus : une valeur
  plus haute est ramenée à 20 € à la création, et une opération lots n’applique
  jamais plus de 20 €, même si la base dit autre chose.
- **Durée.** 7 jours par défaut, comme tout accès agent.
- **Délivrance locale.** Seul `pokeprice-manage agent-create` crée un accès ;
  aucune route de l’API ne crée, n’élargit ni ne prolonge une délégation.

### Lire le gisement, l’état et un plan

Quatre routes, toutes sous `/api/agent/v1/lots` et toutes réservées à
`lots:read`. Aucune n’écrit : chacune autorise l’accès et lit la collection
dans la même transaction de lecture. Un accès sans `lots:read` reçoit 403
sur chacune.

| Route | Opération | Rôle |
|---|---|---|
| `GET /lots/pool?max_per_lot=` | `lots-pool` | gisement des doublons : comptes, lots candidats avec identifiants et versions des cartes, énergies offertes, cartes écartées et « à chiffrer » (200 au plus par liste, totaux exacts, drapeau `*_truncated`) ; `max_per_lot` de 3 à 50, 20 par défaut |
| `GET /lots/status` | `lots-status` | brouillons actifs, lots en ligne, plafond de 5 brouillons utilisé (`cap_used`), ce qui bloque un nouveau lot (`blocked_by`) ; chaque brouillon porte `tool_made` |
| `POST /lots/plan` | `lots-plan` | essai de composition à partir d’une recette `{recipe}` : cartes et versions, énergies offertes à part (`bonus`), prix demandé calculé par le serveur, plancher et marge, et `plan_id` |
| `GET /lots/{sale_id}/publication` | `lots-publication` | vérification de publication d’un brouillon de l’outil : publiable ou non, refus au plancher distingué des autres refus, annonces unitaires à retirer, dernière demande de dérogation |

- **Ce que la requête ne règle pas.** L’auteur, la marge, le plancher, le
  plafond de brouillons et le périmètre viennent du serveur : la marge de la
  base, le plafond de valeur de l’accès (20 € au plus), les doublons seuls.
  Une carte gardée dans l’album n’entre jamais dans un plan.
- **Recette stricte.** Un champ inconnu est refusé, les types sont stricts,
  le titre tient en 120 caractères et le résumé en 500, chaque liste en
  20 éléments, et le texte libre ne porte ni lien, ni adresse, ni balise.
  Le script garde sa recette telle quelle.
- **Lot de l’outil.** Un brouillon est `tool_made` quand l’outil des lots ou
  un agent l’a créé comme lot (auteur et canal « Lot » de l’événement de
  création). Le titre d’un brouillon fait à la main n’est pas renvoyé, et sa
  vérification de publication répond 404.
- **`plan_id`.** Empreinte SHA-256 de la recette, des cartes et de leurs
  versions, des énergies offertes, du prix, de la marge et du plafond de
  valeur : elle change dès que l’un d’eux change.
- **Débit.** `pool` et `plan` relisent toute la collection : six appels par
  minute et par accès à eux deux, en plus de la limite générale.

### Composer, faire tourner, annuler et relever

Quatre routes d’écriture, sous `/api/agent/v1/lots` et réservées à
`lots:compose`. Chacune se fait dans une seule transaction d’écriture, dans cet
ordre : autorisation, clé d’idempotence, quotas, validations recalculées sur la
collection du moment, écritures. L’auteur enregistré est `agent:<identifiant
de l’accès>`.

| Route | Opération | Rôle |
|---|---|---|
| `POST /lots` | `lots-compose` | crée le brouillon d’un plan : `{recipe, plan_id, asking_cents?}` et un en-tête `Idempotency-Key` obligatoire ; réponse 201 avec le brouillon, son prix, le plancher et `raised_to_floor` |
| `POST /lots/rotate` | `lots-rotate` | rotation des brouillons : `{dry_run, limit?}` et un en-tête `Idempotency-Key` obligatoire ; à blanc par défaut |
| `POST /lots/{sale_id}/cancel` | `lots-cancel` | annule un brouillon de l’outil : `{expected_version, reason}` |
| `POST /lots/{sale_id}/raise` | `lots-raise` | relève le prix d’un brouillon de l’outil : `{expected_version, asking_cents}` |

- **Le serveur compose.** `POST /lots` recalcule le plan de la recette ; si son
  `plan_id` diffère de celui reçu, la réponse est 409 `stale_plan` et rien ne
  s’écrit. Le client ne fournit ni cartes, ni énergies offertes, ni auteur,
  ni marge, ni périmètre, ni plafond : un tel champ est refusé (422). Une
  carte gardée dans l’album n’entre jamais dans un lot.
- **Pas de double réservation.** Une carte déjà prise par un brouillon, une
  vente réservée ou un lot en ligne n’entre pas dans le plan. Les écritures se
  suivant une à une, deux compositions concurrentes sur les mêmes cartes ne
  réussissent jamais toutes les deux : la seconde reçoit `stale_plan`.
- **Plafond.** 5 brouillons actifs au plus, lots en ligne et brouillons faits à
  la main compris, vérifiés dans la transaction (409 `draft_cap`). Le `limit`
  de la rotation ne fait que baisser le nombre de lots créés.
- **Prix.** Jamais sous le plancher anti-bradage du jour : un prix calculé
  dessous y est relevé, sans demande de dérogation. `asking_cents` ne peut que
  relever le prix calculé (422 `price_lowered` sinon). `raise` ne baisse
  jamais un prix : le nouveau prix vaut au moins l’actuel, et au moins le
  plancher du jour.
- **Brouillons de l’outil seulement.** `cancel`, `raise` et la rotation ne
  touchent qu’un brouillon `tool_made` ; un brouillon fait à la main répond
  404 et garde sa place dans le plafond. Un brouillon dont le lot est en ligne
  ne s’annule ni ne se relève (409 `online_lot`).
- **Rotation.** Elle se calcule sur un instantané de lecture, puis tout se
  revalide dans la transaction d’écriture : chaque brouillon à annuler (encore
  brouillon, de l’outil, hors ligne, même version), chaque carte à prendre,
  puis le plafond. Un changement entre les deux donne `stale_plan` ; un accès
  révoqué entre les deux, 401. La réponse liste aussi, sous `due_online`, les
  lots en ligne de l’outil invendus depuis plus que l’âge de rotation
  (`rotation_days`, réglé dans **Réglages → Plancher anti-bradage**). Un accès
  qui détient aussi `lots:publish` les remplace (voir plus bas) ; sans lui, la
  rotation les signale sans y toucher.
- **Idempotence.** Même clé et même corps : la réponse enregistrée revient,
  avec `replayed: true`, avant toute validation. Même clé et autre corps :
  409 `idempotency_conflict`. Une clé vaut pour un accès : deux accès peuvent
  utiliser la même. Une rotation à blanc n’enregistre rien.
- **Quotas par accès et par jour.** 20 lots créés (429 `draft_quota`) et
  100 refus journalisés (429 `refusal_quota`), un refus au plus par
  opération, code et minute.
- **Journal sans table.** Chaque écriture réussie est un événement `lot-op`
  (clé, opération, empreinte de la requête, réponse) et chaque refus un
  événement `lot-denied`, sans exemplaire ; le schéma de la base ne change
  pas. Création, annulation et prix restent aussi dans l’historique de la
  vente.
- **Débit.** `POST /lots` et `POST /lots/rotate` relisent toute la collection
  et partagent les six appels par minute de `pool` et `plan`.

### Publier, retirer et remplacer les lots en ligne

Deux routes d’écriture, sous `/api/agent/v1/lots` et réservées à
`lots:publish`, dans le même cadre que la composition : une seule transaction
d’écriture, autorisation, idempotence, quotas, validations, écritures, auteur
`agent:<identifiant de l’accès>`.

| Route | Opération | Rôle |
|---|---|---|
| `POST /lots/{sale_id}/publish` | `lots-publish` | publie en vitrine un brouillon de l’outil : `{expected_version, dry_run}` et un en-tête `Idempotency-Key` obligatoire ; à blanc par défaut ; aucun champ de prix |
| `POST /lots/{listing_id}/unpublish` | `lots-unpublish` | retire une annonce de lot de l’outil : `{expected_version, reason}` (version de l’annonce) |

- **Vérification dans la transaction.** La publication repasse chaque carte
  payante aux règles d’entrée en lot avec le plafond de valeur de l’accès :
  identité confirmée, cote enregistrée, rien à examiner, sous le plafond,
  disponible, prise par aucune autre vente ni aucun autre lot en ligne. Une
  carte passée « à examiner » depuis la composition fait refuser le lot
  (422 `not_publishable`), et rien ne s’écrit. Les annonces unitaires de ses
  cartes sont retirées, le lot publié et la vente mise à jour sur la même
  connexion.
- **Prix.** Un prix sous le plancher du jour est relevé au plancher, celui de
  la vente compris (`raised_to_floor`) ; aucune demande de dérogation n’est
  enregistrée pour un agent. Le plancher absolu de 0,50 € tient toujours, et
  un prix n’est jamais baissé.
- **Lots de l’outil seulement.** Un brouillon fait à la main répond 404 ; un
  brouillon déjà en ligne, 409 `online_lot`. `unpublish` ne retire qu’une
  annonce publiée par l’outil des lots ou un agent et qui porte au moins deux
  cartes ; une annonce faite à la main ou d’une seule carte répond 404.
- **Après un retrait.** Le brouillon de l’outil qui porte ces cartes est
  annulé dans la même transaction. Les cartes d’un lot retiré ou remplacé
  reviennent au gisement sans annonce unitaire jusqu’à leur prochaine
  composition, car les annonces unitaires retirées à la publication ne sont
  pas rétablies. Si une vente faite à la main
  (409 `hand_made_sale`) ou réservée (409 `sale_in_progress`) porte l’une
  d’elles, rien n’est retiré.
- **Rotation des lots en ligne.** Pour un accès qui détient `lots:compose` et
  `lots:publish`, `POST /lots/rotate` remplace d’abord, du plus ancien au plus
  récent, les lots en ligne de l’outil invendus depuis plus que l’âge de
  rotation. Chaque remplacement est une transaction : retrait de l’annonce,
  annulation du brouillon, composition d’un nouveau lot (les cartes libérées
  comprises), puis publication avec les règles ci-dessus. Un échec annule ce
  remplacement seul : le lot reste en ligne tel qu’il était, et la réponse le
  liste sous `online_rotation.failed`. Le remplaçant est, parmi les lots
  possibles, celui qui reprend le moins de cartes payantes du lot remplacé ;
  s’il n’y en a aucun (`no_replacement`), ou si le seul possible reprend
  exactement les mêmes cartes payantes (`no_fresh_replacement`), le lot reste
  en ligne et la réponse le liste sous `skipped`. Le prix d’un remplaçant
  n’est jamais sous le plancher du jour. Le plafond de
  5 brouillons et les quotas valent pour chaque remplacement ; une rotation à
  blanc liste les remplacements prévus sous `online_rotation.planned`.
- **Quota par accès et par jour.** 10 lots publiés (429 `publish_quota`),
  remplacements compris ; chaque remplacement compte aussi un lot créé.
- **Débit.** `publish` relit toute la collection : il partage les six appels
  par minute de `pool` et `plan`. La transaction d’écriture relit les
  valorisations du lot comme le script de publication, sans plus.
- **Ce qui n’existe pas.** Ni publication de tous les brouillons d’un coup, ni
  route qui touche aux accès, à la marge, à l’âge de rotation ou aux
  dérogations.

### Client en ligne de commande des lots

`pokeprice-agent` porte une sous-commande par opération, avec la même URL et le
même fichier de jeton que ses autres commandes (`--url` ou
`POKEPRICE_AGENT_URL`, `--token-file` ou `POKEPRICE_AGENT_TOKEN_FILE`, en mode
0600). Il écrit la réponse JSON du serveur sur la sortie standard ; un refus
sort en code 1, avec le statut et le code d’erreur du serveur sur la sortie
d’erreur (`HTTP 409 stale_plan : …`, `HTTP 429 draft_quota : …`).

```bash
export POKEPRICE_AGENT_URL=https://SERVEUR
export POKEPRICE_AGENT_TOKEN_FILE=/chemin/prive/lots-doublons.token
uv run pokeprice-agent lots-status
uv run pokeprice-agent lots-plan --recipe-file recette.json
uv run pokeprice-agent lots-compose --recipe-file recette.json --plan-id PLAN_ID
uv run pokeprice-agent lots-publication SALE_ID
uv run pokeprice-agent lots-publish SALE_ID --expected-version 3 --apply
uv run pokeprice-agent lots-rotate --apply
```

| Sous-commande | Options |
|---|---|
| `lots-pool` | `--max-per-lot` |
| `lots-status` | aucune |
| `lots-plan` | `--recipe-file` (64 Ko au plus) |
| `lots-publication` | `SALE_ID` |
| `lots-compose` | `--recipe-file`, `--plan-id`, `--asking-cents`, `--key` |
| `lots-rotate` | `--apply`, `--limit`, `--key` ; à blanc sans `--apply` |
| `lots-cancel` | `SALE_ID`, `--expected-version`, `--reason` |
| `lots-raise` | `SALE_ID`, `--expected-version`, `--asking-cents` |
| `lots-publish` | `SALE_ID`, `--expected-version`, `--apply`, `--key` ; à blanc sans `--apply` |
| `lots-unpublish` | `LISTING_ID`, `--expected-version`, `--reason` |

- **Clé d’idempotence.** `lots-compose`, `lots-rotate` et `lots-publish`
  envoient une clé neuve à chaque appel. Un échec affiche la clé envoyée ;
  la redonner par `--key` rejoue la même opération sans la doubler, même si le
  serveur l’a déjà faite.
- **Version attendue.** `lots-cancel`, `lots-raise`, `lots-publish` et
  `lots-unpublish` transmettent `--expected-version` telle quelle ; le serveur
  refuse une version dépassée (409).
- **Le script par l’API.** `scripts/pokeprice_lots.py --api` fait passer ses
  sous-commandes par ces routes, sans `--data` ni accès au serveur :
  `analyze` lit le gisement, `status` l’état, `rotate` la rotation (écriture
  sauf `--dry-run`), `compose` le plan puis, avec `--create-draft`, le
  brouillon ; `publish-to-storefront` vérifie chaque brouillon de l’outil puis
  le publie à la version vérifiée, un à un avec `--all`. Un prompt
  (`--prompt`) est interprété par Gemini sur le poste, qui envoie la recette.
  `--actor`, `--max-drafts` et `--scope all` sont refusés : le serveur fixe
  l’auteur, le plafond et le périmètre. `--key` redonne la clé d’un essai de
  `rotate`, `compose` ou d’une publication. Sans `--api`, le script ouvre la base
  donnée par `--data`, là où elle vit : c’est le repli de l’opérateur, sans mode
  `ssh`.

```bash
python scripts/pokeprice_lots.py --api --token-file /chemin/prive/lots-doublons.token \
  --output /tmp/lots-status.json status
```

## Outils de l'assistant de gestion

Le chat de gestion et son banc d'essai lisent la collection par des
outils fermés, sans écrire ([fiche 0032](decisions/0032-outils-assistant-lecture.md)).
Ils demandent la portée `assistant:read`, qui couvre toute la collection et
que seul un compte gestionnaire ou administrateur délègue :

```bash
uv run pokeprice-manage --data /CHEMIN_COLLECTION agent-create assistant-gestion \
  --owner NOM_DU_COMPTE --album IDENTIFIANT_ALBUM --assistant \
  --client "Client du chat et fournisseur qui reçoit les données" \
  --days 7 --token-file /chemin/prive/assistant-gestion.token
```

| Route | Rôle |
|---|---|
| `GET /api/agent/v1/assistant-tools` | liste des outils : nom, description pour le modèle, schéma JSON des arguments |
| `POST /api/agent/v1/assistant-tools/{name}` | appelle un outil ; le corps est l'objet d'arguments, la réponse `{tool, result, request_id}` |

Outils : `search_copies`, `get_copy`, `explain_price`, `why_not_for_sale`,
`list_listings`, `sales_summary`, `agent_activity`, `todo_queue`, puis
`knowledge`, qui renvoie une section du guide ou une règle métier, sans
aucune commande ([fiche 0035](decisions/0035-connaissances-de-l-assistant.md)),
et `count_copies`, qui compte toute la collection sans plafond de page : doublons
par édition exacte, classements et comptes par nom, extension, langue, statut,
stock ou album ([fiche 0037](decisions/0037-comptage-et-nombres.md)). Leurs
schémas sont versionnés dans [assistant-tools.json](assistant-tools.json) ;
`python -m pokeprice.assistant_tools --write` le régénère.

Le serveur vérifie la portée à chaque appel et refuse un argument inconnu ou
hors bornes (422 `invalid_arguments`), un outil inconnu (404 `unknown_tool`)
et une délégation sans la portée (403). Aucune sortie ne contient le nom,
l'e-mail, l'adresse ni le message d'un client, ni les notes privées : un texte
de client exposé plus tard le sera dans un champ `untrusted_text`, à citer
et jamais à suivre.

## Relecture dans Ventes

Le lot apparaît avec la mention **Préparation par agent**, son texte à relire
et un prix convenu à préciser. Les exemplaires restent disponibles. Un prix
inconnu est exposé comme `null`, y compris dans l’export de gestion ; le zéro
technique imposé par l’ancien stockage des ventes est accompagné d’un marqueur
distinct et n’est pas présenté comme une valeur convenue.

La personne peut poursuivre le parcours de gestion existant avec ses propres
droits. Elle doit renseigner explicitement un prix convenu avant de réserver
ce brouillon. La délégation de création ne donne pas à l’agent ces droits humains.

Si une fiche change, la préparation est signalée comme à revoir. Le paquet est
**régénéré à partir des fiches courantes** et l’indique dans `a-completer.txt` ;
ce n’est pas une annonce approuvée et figée. Le texte de l’agent reste séparé,
dans `proposition-agent.txt`, des informations factuelles du générateur.
Les notes privées et données financières de gestion ne sont pas incluses.

## Révoquer, limiter et vérifier

```bash
uv run pokeprice-manage --data data/inventory agent-list
uv run pokeprice-manage --data data/inventory agent-revoke IDENTIFIANT_ACCES
uv run pokeprice-manage agent-schema > /chemin/prive/api-agent.json
```

La création et la révocation d’un accès s’inscrivent dans l’historique de la
collection (`agent-grant-create`, `agent-grant-revoke`), dans la même
transaction que l’accès lui-même : identifiant de l’accès et du compte
délégant, album, client, permissions, plafond et expiration, jamais le jeton
ni son condensat. L’auteur
est celui que donne `--actor`, `system:manage` sinon.

L’export du contrat est hors ligne : il n’ouvre aucune base et n’expose que les
routes agent. La documentation HTTP publique reste désactivée. Pour fermer
l’ensemble des routes agent, démarrer le serveur avec `serve --no-agent-api`.

Limites du pilote : un album de 2 000 exemplaires au maximum, 100 résultats par
page, 20 cartes par lot, 100 brouillons par délégation, requêtes de création de
64 Ko au plus. Débit limité en mémoire du processus : 60 requêtes par minute
par délégation, 300 par adresse, avec une limite supplémentaire sur les refus
d’authentification. Ces compteurs repartent à zéro au redémarrage.

Les sauvegardes conservent les brouillons et leur provenance, mais neutralisent
les jetons. La restauration les neutralise aussi, même si une ancienne archive
en contenait : créer un nouvel accès sur l’installation restaurée. Aucun
traitement payant n’est repris automatiquement.

Réception automatisée : client CLI contre un vrai serveur HTTP local, refus de
toutes les routes de gestion avec le seul jeton agent, portée, photos, sélection
prudente, relecture humaine, conflits, requêtes concurrentes, réponse perdue,
révocation, migration et sauvegarde/restauration. Le gain de temps humain et
l’essai du client habituel sur la collection réelle restent à mesurer.
