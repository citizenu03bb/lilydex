# 0030 — Un prix sous le plancher devient une demande de dérogation qu'une personne tranche

> **Statut :** proposée, complète les [décisions 0021](0021-autonomie-maximale.md) et [0026](0026-plancher-anti-bradage-gestion.md) · **Date :** 2026-11-04

**Contexte.** La [décision 0021](0021-autonomie-maximale.md) veut qu'un prix
sous le plancher anti-bradage soit « présenté à l'humain avec sa raison,
jamais appliqué d'office », et qu'un exemplaire sans prix de référence ne se
vende pas seul. La [décision 0026](0026-plancher-anti-bradage-gestion.md) a
centralisé le calcul et le refus dans `Listings.publish`, mais trois écarts
restent :

- le refus est net : l'agent reçoit une erreur, et personne ne voit le prix
  qu'il proposait ni pourquoi ;
- une carte sans référence se publie seule à 0,50 €, quel que soit l'auteur ;
- une annonce publiée au plancher reste en ligne quand sa cote monte ensuite :
  rien ne la signale en vitrine (seul l'export plateforme la relève).

**Options.**
1. Une table `floor_requests` : une migration, une sauvegarde à restaurer pour
   l'essayer, pour un volume de quelques demandes par semaine.
2. Des événements, sur le modèle des demandes de photo de la
   [décision 0022](0022-agent-confirme-ou-demande-photo.md) : aucune
   migration, l'historique est déjà là.
3. Laisser l'agent baisser son prix jusqu'au plancher : il ne demande plus
   rien, mais il perd l'information qu'il avait (une carte abîmée, un lot qui
   ne part pas) et la personne ne la voit jamais.

**Décision.** Option 2, dans `src/pokeprice/floor_requests.py`.

- Un auteur est un agent quand son compte commence par `agent:` ou vaut
  `pokeprice-lots` (`is_agent` dans `src/pokeprice/listings.py`).
- Sous le plancher, `Listings.publish` lève `FloorRefusal` (sous-classe de
  `ValueError`, même message qu'avant) avec les exemplaires, le prix demandé,
  le plancher, les références et la raison. Venant d'un agent, le refus
  inscrit aussi une demande : un événement `floor-request` sans exemplaire
  (`copy_id` nul). L'outil de lots fait de même quand le plancher est son
  seul motif de refus, après l'annulation de sa transaction et jamais en essai
  à blanc. Une même sélection au même prix ne crée qu'une demande ouverte.
- Le plancher absolu de 0,50 € ne se déroge pas.
- `GET /api/floor-requests` liste les demandes ouvertes, et la fonction
  `open_floor_requests(store)` les rend au même format pour les autres
  écrans. Une demande se ferme d'elle-même quand un exemplaire est supprimé,
  réservé ou vendu, quand le lot est publié autrement, ou quand le prix de
  l'annonce auditée a changé.
- Trois décisions, réservées à un compte humain de gestion (rôle éditeur ou
  administrateur) : `accept` publie au prix demandé avec la source « Dérogation
  accordée par <compte> » ; `raise` publie au plancher du jour ; `refuse`
  ferme la demande. Chacune est un événement `floor-request-decision`. Une
  clé d'agent n'atteint pas ces routes (authentification par cookie de
  session) et le service refuse un compte agent (`HumanOnly`, 403).
- Un agent ne publie pas seule une carte sans référence, ni un lot dont aucune
  carte n'a de référence : le refus lui dit de la mettre dans un lot avec des
  cartes cotées ou de relever d'abord son prix. Une personne garde le plancher
  de 0,50 € de la 0026. Un prix calculé publié par un agent passe aussi par le
  contrôle du plancher.
- `pokeprice-manage --data <base> floor-audit` liste, en lecture seule, les
  annonces en ligne dont le prix est passé sous le plancher du jour, avec le
  prix de relèvement. `--record` inscrit une demande par annonce (origine
  `audit`) : la garder accorde la dérogation, la relever change seulement le
  prix de l'annonce. Rien n'est republié d'office ; une annonce gardée par
  dérogation n'est plus signalée tant que son prix ne change pas.

**Conséquences.**
- Aucune migration ; les demandes et décisions restent dans l'historique.
- Un agent qui propose sous le plancher n'attend plus rien en silence : sa
  demande apparaît en gestion, dans le panneau « Prix sous le plancher à
  trancher ».
- Une dérogation accordée tient pour ce prix : si la cote monte encore
  ensuite, l'audit ne la signale plus. Une personne qui veut la revoir change
  le prix ou retire l'annonce.
- Les seules voies d'agent qui publient en vitrine passent par
  `Listings.publish` : l'outil de lots. L'API agent
  (`src/pokeprice/agent_api.py`) n'écrit que des brouillons de vente
  ([décision 0012](0012-agent-brouillons.md)).

**Preuve.** `tests/test_floor_requests.py`, `tests/test_listings.py`,
`tests/test_pokeprice_lots.py`, `tests/test_agent_control.py`.
