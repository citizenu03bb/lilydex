# 0024 — Un déplacement en lot refuse les cartes engagées dans un lot ou une vente et s'applique tout ou rien

> **Statut :** en vigueur · **Date :** 2026-11-04

**Contexte.** Réorganiser un classeur ou transférer une série de cartes vers un
autre album fiche par fiche est long et source d'erreurs de numéro de page ou
de pochette. Un déplacement groupé doit montrer où va chaque carte avant toute
écriture, éviter d'empiler deux cartes dans la même pochette, conserver
l'historique par carte et pouvoir être annulé d'un bloc. Il faut aussi décider
du sort des cartes réservées, vendues, ou rattachées à un lot ou à une annonce
de vitrine.

**Options.**
1. Autoriser le déplacement de toutes les cartes, y compris réservées, vendues
   ou en lot, avec un simple avertissement dans l'aperçu : rejeté, car une
   carte vendue a quitté le classeur, une carte réservée ou en brouillon de lot
   doit rester trouvable à l'emplacement préparé pour l'expédition, et
   incrémenter sa version périme les brouillons préparés par l'agent
   (`agent_drafts`).
2. Refuser toute carte publiée en vitrine, même à l'unité : rejeté, car les
   doublons disponibles sont publiés à l'unité tout en restant rangés dans les
   classeurs, et la vitrine publique n'expose ni l'album ni la pochette.
3. Refuser les cartes supprimées, réservées, vendues ou engagées dans un lot
   actif (vente non annulée/retournée ou lot multi-cartes en ligne), signaler
   dans l'aperçu les cartes publiées à l'unité ainsi que les cases d'arrivée
   déjà occupées, et appliquer ou annuler l'opération en une seule transaction.

**Décision.** Option 3.
- L'aperçu (`POST /api/move-batches`) calcule la destination de chaque carte
  selon deux modes : `auto` (premières cases libres de l'album d'arrivée) ou
  `from_slot` (cases consécutives à partir d'une page et d'une case données).
- En mode `from_slot`, les cases d'arrivée déjà occupées par d'autres cartes de
  l'album sont signalées dans l'aperçu (`collision`, `occupied_by`) et bloquent
  l'application par défaut tant qu'un placement sans collision n'est pas choisi.
- Les cartes dans la corbeille, réservées, vendues ou rattachées à un lot actif
  (`sales` hors `cancelled`/`returned`, ou `listings` en ligne de plusieurs
  cartes) sont refusées avec `409 Conflict` dès l'aperçu et revérifiées sous
  verrou d'écriture à l'application. Une annonce unitaire en ligne reste
  autorisée et signalée (`published`).
- L'application (`POST /api/move-batches/{id}/apply`) crée une sauvegarde
  préalable puis appelle `Store.patch` pour chaque carte dans une seule
  transaction `BEGIN IMMEDIATE`. Un conflit de version ou d'occupation au
  milieu du lot annule toute la transaction : rien n'est écrit.
- L'annulation (`POST /api/move-batches/{id}/undo`) remet toutes les cartes à
  leur album, page et case d'origine dans une seule transaction si aucune carte
  n'a changé de version depuis le déplacement et si les cases d'origine sont
  restées libres.

**Conséquences.**
- Pour déplacer une carte engagée dans un brouillon de lot, l'opérateur annule
  d'abord le brouillon, déplace la carte, puis recrée le lot.
- Chaque carte déplacée (et éventuellement remise en place) conserve une entrée
  `correction` complète dans `events`, sans perdre ses confirmations d'état, de
  variante ni son prix de référence.

**Preuve.** `tests/test_move_batches.py`, `tests/test_web_client.py`.
