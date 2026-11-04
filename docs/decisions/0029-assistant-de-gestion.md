# 0029 — Un assistant de gestion : un brief du jour, une file « À toi », puis un chat qui ne passe que par des outils fermés

> **Statut :** proposée, complète les décisions [0021](0021-autonomie-maximale.md) et [0022](0022-agent-confirme-ou-demande-photo.md) · **Date :** 2026-11-04

**Contexte.** Avec les décisions 0021 et 0022, l'IA identifie, cote, range,
compose et publie seule. Il ne reste à Lily que ce que la 0021 (a) lui
réserve : les photos que l'IA demande, l'argent qui sort (paiement,
remboursement), l'irréversible, tout prix sous le plancher anti-bradage
([décision 0026](0026-plancher-anti-bradage-gestion.md)), les messages libres
aux clients et le plafond de délégation. Mais ces demandes sont éparpillées
dans la gestion : demandes de photo, réservations, refus de prix sous le
plancher. Rien ne dit non plus ce que l'IA a fait. Lily a peu de temps et
consulte surtout depuis son téléphone.

Le but : en quelques minutes, au téléphone, Lily sait ce que l'IA a fait et ce
qui l'attend.

**Options.**
1. **Rien de neuf.** Lily parcourt chaque écran de la gestion. Elle ne voit
   pas ce que l'IA a fait, et une demande oubliée bloque une vente.
2. **Un brief et une file, sans modèle de langue.** Le serveur rassemble ce
   que l'IA a fait et ce qui attend Lily ; chaque attente est une carte
   d'action. Simple et sûr, mais Lily ne peut ni poser de question ni donner
   un ordre en langage courant.
3. **Un chat libre** : un modèle de langue lit et écrit dans la base pour le
   compte de Lily. Souple, mais une phrase mal comprise, ou une consigne
   cachée dans le message d'un client, peut alors faire n'importe quelle
   écriture, y compris une décision de la 0021 (a).
4. **L'option 2 d'abord, puis un chat** qui n'écrit jamais lui-même : il
   appelle une liste fermée d'outils avec sa propre clé de délégation, et
   toute décision humaine retombe dans la file.

**Décision.** Option 4, en quatre étapes.

*Le brief du jour.*
- Il dit ce que l'IA a fait depuis le dernier brief (cartes identifiées,
  cotées, rangées, lots publiés ou retirés, actions annulées), ce qui attend
  Lily, et le temps estimé pour le traiter.
- Il part par la notification existante (`src/pokeprice/notifications.py`),
  avec les mêmes règles : des nombres, des totaux et un lien vers la gestion,
  jamais le nom, l'adresse ou le message d'un client.
- Il s'affiche en haut de la gestion, lisible sur un écran de téléphone.

*La file « À toi ».*
- Elle ne contient que les décisions humaines de la 0021 (a) et les photos à
  reprendre de la 0022. Rien de ce que l'IA peut trancher seule n'y entre.
- Chaque élément est une carte d'action : ce qui est demandé, pourquoi, et le
  bouton qui le fait (déposer la photo, confirmer la réservation, accepter ou
  refuser la dérogation).
- Sources :
  - les photos à reprendre (`GET /api/photo-requests`) ;
  - les réservations à confirmer (`src/pokeprice/reservations.py`) ;
  - les demandes de dérogation au plancher anti-bradage
    (décision 0030, `GET /api/floor-requests`) ;
  - plus tard, les brouillons de réponses aux clients, qu'un humain relit
    avant envoi puisqu'un message libre lui revient.

*Le chat.* Il sert à comprendre (« pourquoi ce lot n'est pas publié ? »), à
commander (« baisse les lots de plus de trente jours ») et à annuler.
- Le modèle n'écrit jamais lui-même dans la base. Il appelle une liste fermée
  d'outils : ceux de l'API agent v1 (`src/pokeprice/agent_api.py`) et des
  services de la gestion, nommés un par un.
- Il agit avec sa propre clé de délégation. Le serveur décide des droits,
  comme pour tout agent ([décision 0012](0012-agent-brouillons.md)) ; le chat
  ne peut pas élargir sa clé, puisque le plafond de délégation est une
  décision humaine.
- Toute décision de la 0021 (a) devient une carte de la file, même si Lily la
  demande en toutes lettres dans le chat. Le chat la prépare ; le bouton de la
  carte la fait.
- Les messages des clients, le texte des annonces et toute donnée lue en base
  sont des données, jamais des consignes : le modèle les cite ou les résume,
  il n'obéit pas à ce qu'ils contiennent. Une consigne cachée dans un message
  ne vaut donc rien.
- Chaque action est journalisée avec son auteur, la commande d'origine et
  l'état antérieur, et s'annule sur le modèle de `agent-review-undo`
  (`src/pokeprice/agent_review.py`) : une commande entière s'annule d'un coup.
- Au-delà d'un plafond d'actions par commande, le chat affiche son plan et
  attend une confirmation avant d'agir.

*Le modèle du chat : décision ouverte.* Deux familles sont envisagées :
- un modèle local, servi par Ollama sur le serveur : rien ne quitte le
  serveur, mais le serveur ARM sans carte graphique limite la taille du
  modèle et sa vitesse ;
- un modèle hébergé, appelé par API : meilleurs appels d'outils et réponses
  rapides, mais les données des cartes et des demandes sortent du serveur.

Les critères, dans l'ordre :
1. la fiabilité des appels d'outils : le bon outil, des arguments valides, pas
   d'outil inventé ;
2. la latence perçue au téléphone ;
3. le coût d'usage ;
4. la confidentialité des données des clients.

Le choix se fera sur une mesure, avec un jeu de commandes types rejoué sur
chaque candidat, avant la V1. Cette fiche ne le tranche pas.

*Les étapes.*
- **V0** : brief du jour et file « À toi », sans modèle de langue.
- **V1** : chat en lecture seule ; il explique et cherche, il n'écrit rien.
- **V2** : commandes dans les droits de la délégation, avec le plan affiché
  avant d'agir et l'annulation de chaque commande.
- **V3** : photo envoyée directement dans le chat pour répondre à une demande
  de photo, et brouillons de réponses aux clients. Les plateformes (Vinted,
  Leboncoin, Cardmarket) rejoindront les outils une fois leur publication
  livrée.

**Conséquences.**
- Lily n'a qu'un endroit à ouvrir : le brief dit combien de temps prendra la
  file, et la file ne contient que ce qu'elle seule peut faire.
- La V0 ne dépend d'aucun modèle de langue ni d'aucun service extérieur ; elle
  reste utile si le chat n'est jamais livré.
- Le chat n'a pas plus de droits qu'un agent délégué. Une erreur du modèle se
  limite à ce que sa clé permet, et elle s'annule.
- Une décision humaine demande toujours un clic sur une carte, même quand Lily
  vient de la demander dans le chat. C'est un geste de plus, accepté pour que
  ni une phrase mal comprise ni une consigne glissée dans un message ne fasse
  sortir de l'argent ou brader une carte.
- L'estimation du temps du brief est une moyenne par sorte de carte d'action ;
  elle n'est pas mesurée sur l'usage réel au départ.
- Tant que le modèle n'est pas choisi, la V1 ne démarre pas.

**Pour aller plus loin.** [Pilote agent](../AGENT_CONTROL.md),
[guide d'autonomie](../../skills/pokeprice-autonome/SKILL.md).
