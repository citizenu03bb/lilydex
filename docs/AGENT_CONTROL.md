# Utiliser le pilote agent

> **Pour qui :** toute personne qui veut déléguer un album à un agent IA.
> **Vous y trouverez :** ce que l'agent peut faire et ne peut pas faire, le skill qui le guide, les commandes du client et les évaluations faites.
> **Statut :** en vigueur ; pilote technique. La délégation initiale est expliquée dans la [fiche 0012](decisions/0012-agent-brouillons.md), complétée pour les corrections préautorisées par la [fiche 0014](decisions/0014-corrections-agent-autorisees.md).

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
Les confirmations physiques, réservations, publications, ventes et paiements
restent sous les droits humains.

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
également déléguer les brouillons et les corrections préautorisées.

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
suivantes ; le déclassement en lecteur retire immédiatement la création de lots et les corrections.

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
