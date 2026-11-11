# 0044 — L'outil des lots passe par l'API agent, sous trois permissions réservées à l'administrateur

> **Statut :** en vigueur, amende la [décision 0021](0021-autonomie-maximale.md), amendée par la [décision 0045](0045-cartes-sorties-d-un-lot-en-annonce-unitaire.md) · **Date :** 2026-11-10

**Contexte.** La [décision 0021](0021-autonomie-maximale.md) laisse les agents
composer, publier et faire tourner les lots de doublons sans attendre de clic.
Jusqu'ici, ils le faisaient par `scripts/pokeprice_lots.py` avec un accès
opérateur au serveur (`ssh`, puis `sudo` sous le compte du service) : un tel
accès peut tout faire, créer une délégation, écrire dans la base ou changer un
réglage. Le plafond de valeur, la délivrance par un administrateur et les
quotas n'étaient donc qu'une convention. Une revue de la conception relève en
outre que le refus d'une carte sans cote ou à examiner ne vivait que dans une
vérification préalable du script, que la rotation pouvait annuler un brouillon
fait à la main, et que les lots en ligne bloquaient la rotation : cinq lots en
ligne invendus empêchaient tout nouveau lot, et les énergies offertes
([décision 0041](0041-energies-offertes-dans-les-lots.md)) ne sortaient plus.

**Options.**
1. Garder le script et l'accès opérateur, en resserrant les consignes : rien
   n'empêche techniquement un agent d'en sortir.
2. Une seule permission « lots » sur l'API agent : simple, mais publier en
   vitrine et composer un brouillon ne pèsent pas le même risque.
3. Trois permissions sur l'API agent, chaque règle vérifiée par le serveur dans
   la transaction qui écrit.

**Décision.** Option 3.

- **Trois permissions.** `lots:read` (gisement, état, plan, vérification de
  publication), `lots:compose` (créer, faire tourner, annuler, relever un
  brouillon), `lots:publish` (publier, retirer une annonce de lot). Publier
  n'emporte pas composer. Elles portent sur toute la collection.
- **Administrateur seulement.** Seul un compte administrateur actif délègue ces
  permissions, par `pokeprice-manage agent-create` ; chaque appel les retire si
  ce compte n'est plus administrateur. Aucune route ne crée, n'élargit ni ne
  prolonge un accès, et aucune ne touche à la marge, à l'âge de rotation ni aux
  dérogations.
- **Une transaction par écriture.** Autorisation, clé d'idempotence, quotas,
  validations recalculées sur la collection du moment, puis écritures, sur une
  seule connexion ; l'auteur est `agent:<accès>`. Le serveur compose : le
  client ne choisit ni les cartes, ni les énergies offertes, ni le prix
  plancher. Idempotence et quotas sont des événements, sans table ni migration.
- **Brouillons de l'outil, doublons seuls.** Seuls les brouillons et les
  annonces de lot créés par l'outil des lots ou un agent s'annulent, se
  publient, se retirent ou tournent ; jamais un brouillon fait à la main,
  jamais une annonce d'une seule carte. Une carte gardée dans l'album n'entre
  jamais dans un lot par l'API.
- **La vérification de publication est obligatoire.** À la publication, chaque
  carte payante repasse, dans la transaction, les règles d'entrée en lot avec
  le plafond de l'accès. `Listings.publish` refuse lui-même, pour un agent, un
  lot qui porte une carte sans cote, non confirmée ou à examiner ; une personne
  qui publie depuis la gestion n'y est pas soumise.
- **Pas de dérogation pour un agent.** Un prix sous le plancher du jour est
  relevé au plancher, jamais mis en file pour une personne ; le plancher absolu
  de 0,50 € tient toujours. Il n'y a ni baisse de prix datée ni file de
  dérogations pour les agents.
- **Rotation des lots en ligne.** Un lot en ligne de l'outil, invendu depuis
  plus que l'âge de rotation (14 jours par défaut, réglage administrateur
  journalisé), est remplacé : retrait de l'annonce, annulation du brouillon,
  composition d'un autre lot (celui qui reprend le moins de cartes payantes du
  lot remplacé ; jamais exactement les mêmes), publication, le tout
  dans une transaction, du plus ancien au plus récent, dans le plafond de
  5 brouillons et les quotas du jour (20 lots créés, 10 publiés). Il faut
  `lots:compose` et `lots:publish` ; sans la seconde, ces lots sont seulement
  signalés. La rotation ne baisse jamais un prix.
- **Accès au serveur.** Les affirmations de la décision 0021 sur la
  publication de lots « par `scripts/pokeprice_lots.py` », et celles de la
  page [IA et vision](../IA-VISION.md) sur l'accès opérateur, valent jusqu'à ce
  que le client passe par l'API. Un agent recevra ensuite une identité
  restreinte sur le serveur, sans `sudo` ni accès à la base ; cette identité
  reste à mettre en place, et la clé d'API n'est la frontière de sécurité qu'à
  partir de là.

**Conséquences.**
- La question de la rotation des lots en ligne, laissée ouverte quand les cinq
  lots en ligne bloquaient tout nouveau lot, est tranchée : ils tournent après
  l'âge de rotation, au lieu de baisser de prix.
- Une carte que personne n'achète au plancher continue d'être recombinée d'une
  rotation à l'autre. C'est accepté pour l'instant, à revoir avec de vraies
  ventes.
- Les annonces unitaires remplacées par un lot ne reviennent pas quand le lot
  est retiré ou remplacé : les cartes retournent au gisement sans annonce
  unitaire jusqu'à leur prochaine composition. Amendé par la
  [décision 0045](0045-cartes-sorties-d-un-lot-en-annonce-unitaire.md) : une
  carte d'au moins 1 € au prix du jour relevé au plancher revient seule en
  vitrine.
- Tant que le client en ligne de commande et l'identité restreinte ne sont pas
  livrés, l'accès opérateur existe encore : la règle tient par la consigne
  donnée aux agents, pas encore par le serveur.
- Le script de l'outil garde ses refus d'aujourd'hui, dérogation au plancher
  comprise, pour l'opérateur.

**Pour aller plus loin.** [Pilote agent](../AGENT_CONTROL.md#déléguer-loutil-des-lots),
[guide des lots](../../skills/pokeprice-lots/SKILL.md).
