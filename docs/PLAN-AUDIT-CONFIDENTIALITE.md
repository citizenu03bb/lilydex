# Plan d'action : l'audit de confidentialité et d'usage

> **Pour qui :** quiconque corrige les défauts relevés par l'audit de confidentialité, de rétention, du panier et de la gestion.
> **Vous y trouverez :** les neuf constats, regroupés en lots indépendants, avec pour chacun la correction visée, le test qui la prouve et l'ordre recommandé.
> **Statut :** plan de correction maintenu à partir des constats du commit `1c4766b`, confrontés au code de la PR qui introduit ce plan. Les réalisations vont dans le [journal](JOURNAL.md) ; les choix de conception dans les [fiches de décision](decisions/README.md).

## Le constat

Un audit externe, mené surtout à la lecture du code (revue de sécurité confiée
à un modèle OpenAI), relève deux défauts prioritaires sur la vie privée des
clients, puis des défauts de rétention, de panier et d'ergonomie de la gestion.
La course à l'effacement d'une conversation de l'assistant a été reproduite sur
une base temporaire ; le reste n'a été ni testé en production, ni sur un
appareil, ni avec un lecteur d'écran. Les tests ciblés de l'assistant lancés
pendant l'audit n'ont pas abouti : ils ne comptent pas comme réussis.

Une relecture rapide confirme les constats 1 à 3 dans le code :
`PATCH /api/me` change l'e-mail (qui sert d'identifiant) sans preuve de
contrôle, l'invité est rattaché par `email=?`, l'effacement cherche l'identité
courante dans les lots, et `forget()` valide la base avant `record()`.

| N° | Gravité | Défaut | Lot |
|---|---|---|---|
| 1 | P1 | Un client approuvé s'approprie une adresse non vérifiée, puis les demandes invitées faites à cette adresse | [L1](#l1--identité-et-effacement-des-clients) |
| 2 | P1 | L'effacement d'un compte laisse un ancien nom ou e-mail dans les lots vendus | [L1](#l1--identité-et-effacement-des-clients) |
| 3 | P2 | Une restauration peut ramener des données effacées si le journal d'effacement manque | [L2](#l2--durabilité-de-leffacement-et-rétention) |
| 4 | P2 | L'empreinte d'audience survit au-delà de la fin de journée annoncée | [L2](#l2--durabilité-de-leffacement-et-rétention) |
| 5 | P2 | Une question en cours journalise des arguments après l'effacement de sa conversation | [L4](#l4--assistant) |
| 6 | P2 | La demande est enregistrée à un prix différent de celui affiché dans le panier | [L3](#l3--panier) |
| 7 | P2 | L'assistant ne dit pas, là où l'on écrit, que les échanges partent chez Google ; les « 30 jours au plus » peuvent être dépassés | [L4](#l4--assistant) |
| 8 | P2 | Un flux de réponse interrompu s'affiche comme une réponse complète | [L4](#l4--assistant) |
| 9 | P3 | Article indisponible non désigné, panier périmé restauré ; dialogues de gestion sans nom accessible | [L3](#l3--panier), [L5](#l5--accessibilité-de-la-gestion) |

## Les principes

- Un lot, une branche, une PR ; chaque correction arrive avec le test qui
  rejoue le scénario de l'audit et échouait avant elle.
- Les tests n'appellent aucun service réel (ni e-mail, ni Gemini) et tournent
  sur une base temporaire.
- L'assistant est en cours de développement (V1.1) : le lot L4 se fait dans
  cette suite de travaux, ou après sa fusion, pour ne pas toucher
  `assistant.py`, `assistant_model.py` et `web/assistant.js` en parallèle.
- Les lots L1, L2, L3 et L5 ne touchent pas ces fichiers et peuvent avancer
  tout de suite.
- Toute migration de schéma est essayée sur une sauvegarde restaurée avant la
  mise en ligne ; aucune écriture sur la base d'un poste de développement.

## Les lots

### L1 — Identité et effacement des clients

**Constat 1 — adresse non vérifiée.** Fichiers : `webapp.py` (`me_update`),
`reservations.py` (`guest`).

- Le changement d'e-mail devient une demande : la nouvelle adresse est rangée
  dans un champ en attente (`pending_email`, jeton haché, échéance) et
  n'entre en vigueur, comme identifiant et pour les demandes, qu'après le clic
  sur un lien reçu à cette adresse. L'adresse courante reste celle du compte
  jusque-là.
- Le compte garde la trace de la vérification de son adresse
  (`email_verified_at`). Une demande invitée n'est rattachée à un compte
  existant que si son adresse est vérifiée ; sinon elle suit le parcours d'un
  inconnu, sans révéler l'existence du compte.
- Une adresse déjà inscrite mais non vérifiée ne permet pas de créer un
  second compte ordinaire : prévoir une identité invitée séparée ou des
  coordonnées propres à la demande. L'approbation d'un compte par le vendeur
  ne prouve pas le contrôle de son adresse ; les comptes existants ne sont
  pas marqués vérifiés sans preuve. Les liens de mot de passe déjà émis sont
  invalidés lorsque l'adresse change.
- Décision à prendre : si l'application n'a pas de canal d'envoi d'e-mail
  utilisable pour ce lien, le changement d'adresse passe par le vendeur
  (demande visible dans la gestion), et le rattachement automatique des
  invités est suspendu pour tout compte dont l'adresse a changé.
- Test : client approuvé → changement vers une adresse libre → demande invitée
  à cette adresse → la demande n'apparaît pas dans son compte et il ne peut
  pas l'annuler. Puis vérification du lien → l'adresse change.

**Constat 2 — identité restée dans les lots.** Fichiers : `reservations.py`
(création du lot à l'acceptation), `privacy.py` (`erase`).

- À l'acceptation, ce qui est copié du client dans le lot (titre, notes,
  historique) est aussi rangé dans des champs structurés liés à la demande
  (par exemple `client_name`, `client_email` sur la demande ou le lot), au lieu
  de n'exister que dans du texte libre.
- L'effacement remplace ces champs par lien (`requests.client_id` →
  `sale_id`), quelle que soit l'identité courante, et recherche aussi, dans le
  texte libre, toutes les identités figées par ces champs, pas seulement la
  courante.
- Reprise des lots existants : un script lit les demandes acceptées et
  remplit les champs structurés depuis l'historique, sur une sauvegarde
  restaurée d'abord.
- Test : acceptation → changement de nom et d'e-mail → suppression du compte →
  ni l'ancien nom ni l'ancien e-mail ne restent dans `sales` ni dans son
  historique.

### L2 — Durabilité de l'effacement et rétention

**Constat 3 — journal d'effacement.** Fichiers : `privacy.py` (`forget`,
`record`, `replay`), `manage.py` (`restore`).

- L'intention d'effacer est écrite et synchronisée sur disque dans le journal
  avant la validation de la base, pour `forget()` comme pour `purge()` ; le
  rejeu est idempotent, donc une intention dont l'effacement n'a pas abouti
  est simplement rejouée. Une erreur d'écriture ou de synchronisation empêche
  la validation de l'effacement.
- `restore` refuse de finir quand le journal est absent ou illisible, sauf
  option explicite (`--sans-journal`) qui dit ce qu'elle risque ; il signale
  un journal incomplet (intention sans fin). Le journal est validé avant
  restauration ; la destination définitive n'apparaît qu'après un rejeu
  réussi dans un dossier temporaire.
- Le journal vit **à côté** du dossier `--data`, dans `erasures.jsonl` ; les
  archives de collection et leur copie distante ne l'emportent pas. Inclure
  `inventory_backup.py`, `server_backup.py` et `drive_backup.py` dans le lot
  pour préserver une copie récente du journal, y compris après perte du
  serveur. Une copie ancienne dans l'archive ne remplace jamais le journal
  courant et ne garantit pas les effacements postérieurs à cette archive.
- Tests : écriture ou synchronisation du journal impossible → effacement
  non validé ; panne après l'intention durable → rejeu de l'effacement ;
  journal absent ou invalide → aucune destination restaurée ; sauvegarde et
  rapatriement → journal récupérable avec les effacements récents.

**Constat 4 — empreinte d'audience.** Fichiers : `audience.py` (`forget`),
`web/about.html`.

- `forget()` passe aussi par un minuteur quotidien indépendant (même famille
  que les minuteurs des prix et du brief), juste après minuit.
- La notice dit le délai réellement tenu (« effacée au plus tard dans l'heure
  qui suit la fin de la journée », ou ce que garantit le minuteur).
- Test : un jour sans visite ni rapport → l'appel du nettoyage seul efface
  sels et empreintes de la veille.

### L3 — Panier

**Constat 6 — prix affiché et prix enregistré.** Fichiers :
`web/storefront.js` (instantané du panier), `reservations.py` (`prices`),
`webapp.py` (schémas, devis, routes invitées et connectées, réponse de conflit).

- Avant l'envoi, le navigateur redemande un devis (prix et disponibilité de
  chaque article) ; si un prix a changé, le panier montre l'écart et demande
  un accord avant l'envoi.
- L'envoi porte les prix acceptés ; le serveur compare avec les prix courants
  et répond par un conflit qui liste les articles changés, au lieu
  d'enregistrer silencieusement un autre total. La comparaison et l'insertion
  de la demande partagent la même transaction, pour les visiteurs invités
  comme pour les clients connectés. Le navigateur conserve le détail structuré
  des conflits reçu du serveur.
- Test : ajout au panier → changement de prix → envoi avec l'ancien prix →
  conflit ; changement après le devis → conflit sans demande partielle ;
  envoi avec le prix accepté → demande enregistrée au bon total.

**Constat 9 (panier) — article indisponible.** Fichiers : `reservations.py`
(contrôle de disponibilité), `web/storefront.js` (restauration du panier).

- Le conflit d'indisponibilité désigne les articles en cause ; le panier les
  retire ou les marque, et la restauration au rechargement revalide le
  contenu au lieu de remettre le même panier périmé. Une panne réseau
  conserve le panier et propose de réessayer ; elle ne vaut pas confirmation
  d'indisponibilité.
- Test : un article vendu entre l'ajout et l'envoi → la réponse le nomme, le
  panier rechargé ne le contient plus.

### L4 — Assistant

À faire dans le cadre du développement de l'assistant, avec ses tests et son
banc.

**Constat 5 — effacement pendant une question.** Fichier : `assistant.py`
(suppression, journal des outils).

- La suppression pose une pierre tombale sur la conversation ; chaque écriture
  du journal (question, appel d'outil, réponse) vérifie, dans la même
  transaction, que la conversation existe encore et non effacée, sinon elle
  abandonne et la question en cours s'arrête.
- Test : rejouer la séquence de l'audit sur un journal temporaire — question
  lancée, suppression depuis un autre onglet, appel d'outil suivant → aucun
  argument enregistré.

**Constat 7 — transfert vers Google et rétention.** Fichiers :
`web/messages/fr.json` (et les autres langues), `assistant.py` (purge),
`web/about.html` ou `RGPD.md`.

- La note de la fenêtre de discussion dit que les questions, le contexte de
  la conversation et les résultats des outils sont envoyés à Google, et
  demande de ne pas y coller de données de clients.
- La rétention annoncée tient compte du rythme de la purge (« 30 jours, purgés
  chaque nuit ») ; la lecture filtre en plus tout ce qui dépasse 30 jours, si
  bien qu'une purge manquée ne rend rien de visible ; un échec de purge
  remonte dans le brief ou une notification.
- La [fiche 0038](decisions/0038-capture-des-echecs.md) distingue les
  conversations signalées, conservées jusqu'à 180 jours après le signal pour
  le banc. Cette exception est expliquée au point d'usage et dans le guide ;
  elle ne prolonge pas l'historique ordinaire envoyé au modèle au-delà de
  30 jours. Les notes des signaux et les brouillons du banc font partie du
  périmètre de rétention et d'effacement.
- Test : conversation de 31 jours, purge non passée → elle n'est ni listée ni
  envoyée au modèle ; conversation signalée → accès réservé au parcours du
  banc et effacement par son auteur toujours possible ; signal expiré →
  aucune donnée de l'échange conservée par cette exception.

**Constat 8 — flux interrompu.** Fichier : `web/assistant.js`.

- Sans événement `done`, la réponse est marquée incomplète, avec un bouton
  pour réessayer ; l'identifiant de conversation est envoyé dès le début du
  flux (premier événement), pour que le navigateur retrouve une question
  déjà enregistrée.
- Test : flux coupé avant `done` → message d'erreur et reprise possible, pas
  de réponse vide présentée comme terminée.

### L5 — Accessibilité de la gestion

**Constat 9 (dialogues).** Fichier : `web/index.html`.

- Chaque `dialog` de la gestion reçoit `aria-labelledby` vers son titre
  visible ; un test statique vérifie que chaque référence désigne un titre
  unique, non vide, et qu'aucun dialogue n'en manque.
- Vérification manuelle avec un lecteur d'écran (Orca sous Linux, TalkBack
  sur le téléphone) ; le résultat va dans le journal.

## L'ordre recommandé

1. **L1**, en premier : les deux défauts P1 touchent des clients réels. Le
   constat 2 n'attend aucune décision ; le constat 1 attend celle sur le
   canal d'envoi d'e-mail.
2. **L2**, ensuite : petit, et il rend fiable l'effacement que L1 corrige.
3. **L3**, à mener en parallèle de L2 (fichiers distincts).
4. **L5**, à tout moment : court et sans risque.
5. **L4**, dans le développement de l'assistant, au plus tard avant la
   phase C, qui donnera des commandes à l'assistant.

Chaque lot se termine par `uv run --extra web --extra dev pytest`, une mise en
ligne, et une ligne dans le journal.

## La décision qui reste à prendre

Le constat 1 dépend d'un choix : vérifier la nouvelle adresse par un lien
envoyé par e-mail, ce qui suppose un canal d'envoi fiable, ou faire passer
tout changement d'adresse par le vendeur. Ce choix fera l'objet d'une fiche
dans `decisions/`.
