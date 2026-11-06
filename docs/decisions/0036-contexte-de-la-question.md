# 0036 — Chaque question du chat part avec ce que l'écran affiche, par liste blanche, comme une donnée

> **Statut :** proposée, complète les décisions [0029](0029-assistant-de-gestion.md), [0032](0032-outils-assistant-lecture.md) et [0034](0034-conversations-du-chat.md) · **Date :** 2026-11-05

**Contexte.** Le chat de gestion ne sait pas ce que Lily regarde. « Pourquoi
celle-là n'est pas en vente ? » juste après avoir fermé une fiche l'oblige à
demander laquelle, ou à chercher au hasard. « Ça ne marche pas » ne lui dit ni
l'erreur affichée, ni s'il parle à un téléphone ou à un ordinateur, ni si la
gestion est installée. La V1.1 du chat lui donne ce contexte. Deux risques :
faire sortir chez le fournisseur du modèle une donnée de client (un nom dans
un titre de lot, un message), et laisser un texte de l'écran se faire passer
pour une consigne.

**Options.**
1. **Rien joindre** : le modèle demande ou cherche. Une question de plus, au
   téléphone, pour chaque « celle-là ».
2. **Joindre l'état de la page** (fiche entière, lot ouvert avec son titre,
   texte des champs). Le modèle sait tout, mais le titre d'un lot porte souvent
   le nom du client, et une note libre peut contenir n'importe quoi.
3. **Joindre une liste fermée de clés, par identifiant**, validée par le
   serveur ; le modèle relit la fiche par les outils existants s'il en a
   besoin.

**Décision.** Option 3.
- L'interface (`web/assistant.js`) joint à chaque `POST /api/assistant` un
  objet `context` : la vue ouverte (`view`), la fiche ouverte ou fermée depuis
  moins de dix minutes (`copy_id`), la vente visée par l'adresse
  (`sale_id`), les filtres actifs (`filters`), l'appareil (`device` : téléphone
  ou ordinateur, gestion installée ou navigateur, iOS, Android ou autre), la
  version de l'interface (`ui_version`, celle du cache du service worker) et
  le dernier message d'erreur renvoyé par le serveur (`last_error`), s'il date
  de moins de cinq minutes ; une connexion réussie l'efface.
- **Aucune donnée de client** : ni nom, ni message, ni adresse, ni titre de
  lot. Une fiche ou une vente passe par son identifiant seul.
- **Le serveur décide** (`assistant_context.clean`) : chaque clé a sa
  vérification (valeurs permises, motif d'identifiant, longueur bornée ; la
  recherche de la collection à 80 caractères, l'erreur à 200, débarrassée de
  ce qui ressemble à une adresse électronique ou à un numéro de téléphone). Une
  clé inconnue ou une valeur hors bornes est écartée, jamais transmise ; le
  journal du serveur n'en note que le nom. Un contexte qui n'est pas un objet,
  ou de plus de 2 000 caractères, est refusé (422). Écarter plutôt que refuser
  le superflu garde le chat utilisable quand une interface en cache est plus
  ancienne ou plus récente que le serveur.
- **Une donnée, jamais une consigne.** Le contexte part dans le message de la
  question, dans une partie à lui, avant le texte de Lily, sous la forme
  `{"interface_context", "source", "notice"}`, comme `untrusted()` pour un
  texte de client ([fiche 0032](0032-outils-assistant-lecture.md)). La
  consigne système n'en reçoit rien ; une section à part lui dit que « la carte
  affichée » est la fiche du contexte, à relire par les outils. Seule la
  question en cours porte son contexte ; l'historique n'en rejoue aucun.
- **Ce que sait le serveur** part dans la même partie, sous `server_context`,
  à chaque question, même sans contexte d'écran : la date et l'heure à Paris
  (`now`, la consigne ne portant que la date pour rester la même toute la
  journée) et le rôle du compte, lu dans la base et jamais dans l'interface
  (`role` : administrateur, équipe ou lecture seule, avec ce qu'il voit). Le
  chat ne renvoie donc pas un compte d'équipe vers Statistiques ou Réglages, et
  la consigne ne suppose ni le genre ni le prénom de la personne : aucun nom
  ne part au modèle.
- **Gardé avec la question** dans `assistant.sqlite3` (colonne
  `questions.context_json`, ajoutée par une migration idempotente) : effacé
  avec la conversation par son auteur, purgé avec la question après 30 jours
  ([fiche 0034](0034-conversations-du-chat.md)).
- **Le banc** accepte un `context` par cas, contrôlé par la même liste
  blanche, pour mesurer les questions « carte affichée »
  ([banc](../../bench/assistant/README.md)).

**Conséquences.**
- « Celle-là » se résout sans question de plus ; la fiche relue coûte un appel
  d'outil, pas un aller-retour avec Lily.
- Le contexte ajoute une centaine de jetons à chaque question.
- Le chat s'ouvre depuis la barre du haut, donc fiche fermée : la « carte
  affichée » est la dernière fiche fermée depuis moins de dix minutes. Une
  carte regardée longtemps avant peut être prise pour celle-là ; le modèle la
  nomme dans sa réponse, ce qui le montre.
- Une nouvelle clé de contexte demande une ligne dans la liste blanche et son
  test : sans elle, le serveur l'écarte.
- La recherche tapée dans la collection part chez Google avec la question :
  elle sert à chercher des cartes, mais rien n'empêche d'y taper autre chose.

**Pour aller plus loin.** [L'assistant dans le guide](../APP.md#lassistant),
`src/pokeprice/assistant_context.py`, `tests/test_assistant_context.py`.
