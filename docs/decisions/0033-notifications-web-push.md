# 0033 — La gestion installée reçoit ses alertes par Web Push ; ntfy reste en secours

> **Statut :** proposée, complète la [décision 0029](0029-assistant-de-gestion.md) (brief du jour) et les [alertes au vendeur](../VITRINE.md#les-alertes-au-vendeur) · **Date :** 2026-11-04

**Contexte.** Le brief du matin et les alertes de la vitrine (nouvelle
demande, rappels) partent par ntfy et par e-mail. Lily gère depuis son
iPhone. ntfy demande une application tierce, un sujet dont l'adresse est le
secret, et un abonnement à ce sujet sur chaque téléphone ; l'e-mail se perd
parmi les autres. Depuis que la gestion s'installe comme une application
(manifeste et service worker de portée `/gestion`), le téléphone peut
recevoir ses notifications directement, avec l'icône de l'application, et un
toucher ouvre la bonne vue. Sur iPhone (iOS 16.4 et suivants), Web Push n'est
possible que pour une application web **installée** sur l'écran d'accueil, et
la permission ne se demande qu'après un geste de l'utilisateur.

**Options.**
1. **Garder ntfy seul** : rien à écrire, mais une application de plus à
   installer et à comprendre, et un toucher qui ouvre ntfy avant la gestion.
2. **Une application native** : hors de portée pour un projet de cette taille
   (comptes développeur, publication, maintenance).
3. **Web Push standard** (RFC 8030, chiffrement RFC 8291, identification
   VAPID RFC 8292) vers la gestion installée, comme canal en plus de ntfy et
   de l'e-mail.

**Décision.** Option 3.

*Les clés.* `pokeprice-manage vapid-keys` génère une paire P-256 et l'affiche
une seule fois, ou l'écrit avec `--output` dans un fichier créé en `0600` et
jamais écrasé. Les variables `POKEPRICE_VAPID_PUBLIC_KEY`,
`POKEPRICE_VAPID_PRIVATE_KEY` et `POKEPRICE_VAPID_SUBJECT` (`mailto:` ou
`https://`) vivent avec les autres secrets ; sans l'une d'elles, le canal est
éteint. Aucune clé n'est versionnée, journalisée ni lue par un test : les
tests génèrent une paire jetable.

*Les abonnements.* Dans **Réglages**, l'interrupteur « Notifications sur ce
téléphone » demande la permission au moment où on le touche, jamais à
l'ouverture de la page ; dans Safari sur iPhone, il reste grisé et explique
qu'il faut d'abord installer l'application. Le navigateur s'abonne auprès de
son service de push avec la clé publique du serveur, puis envoie
l'abonnement à `POST /api/push/subscriptions`. `DELETE` le retire ; un compte
ne retire que ses propres téléphones. Les deux routes sont réservées aux
comptes de gestion connectés (administration, gestion, lecture) et passent le
contrôle d'origine commun. La table `push_subscriptions` (schéma 25) garde
quatre colonnes : le point d'accès, les deux clés du navigateur et le compte.
Le point d'accès doit être en HTTPS sur un service de push connu (Apple,
Google, Mozilla, Microsoft) : le serveur ne peut donc pas être amené à poster
vers une adresse quelconque.

*L'envoi.* Le canal `WebPush` de `notifications.py` rejoint la liste de
`channels_from_env` quand les trois variables sont présentes. Il envoie à
chaque abonnement d'un compte de gestion actif, par `pywebpush`, avec un délai
de 10 secondes et une durée de vie de 12 heures chez le service de push. La
charge utile est `{title, body, url}` : le titre et le texte courts déjà
envoyés sur les autres canaux, les liens retirés du texte, 180 caractères au
plus, et un chemin sous `/gestion` (`/gestion` pour le brief,
`/gestion?demande=…` pour une demande), sans l'origine. Un abonnement que le
service déclare disparu (404 ou 410) est supprimé. L'envoi réussit si un
téléphone au moins est joint ; il n'échoue, et la file des alertes le
réessaie, que si tous ont échoué. Chaque canal est envoyé séparément : un
échec de Web Push n'empêche jamais ntfy ni l'e-mail, et inversement. Un
journal ne nomme jamais un point d'accès, seulement la classe de l'erreur.

*Le service worker.* L'écouteur `push` affiche la notification avec l'icône
de l'application ; `notificationclick` met au premier plan la gestion déjà
ouverte et la mène à l'URL donnée, ou ouvre une fenêtre. Une URL hors de
`/gestion` retombe sur `/gestion`. Le cache ne change pas.

*Ce qui transite par les services de push.* Le serveur poste chaque
notification au service du navigateur : Apple (`*.push.apple.com`) pour
Safari et l'application installée sur iPhone, Google (`fcm.googleapis.com`)
pour Chrome et Android, Mozilla pour Firefox, Microsoft pour Edge. Le contenu
est chiffré de bout en bout pour le navigateur (RFC 8291) : le service ne lit
ni le titre ni le texte. Il voit en revanche l'adresse IP du serveur, le
point d'accès du téléphone, l'heure, la taille du message chiffré, la durée
de vie demandée, et le sujet VAPID (d'où l'intérêt d'une adresse de contact
dédiée plutôt que personnelle). Comme les messages ne portent que des nombres
et un chemin, même une fuite du contenu ne révélerait aucune donnée de
client. ntfy, lui, reçoit le texte en clair.

*ntfy.* Il reste configuré, en secours, pour l'instant. Il pourra être retiré
quand ces trois critères seront réunis :
1. au moins deux semaines de briefs reçus par Web Push sur l'iPhone de Lily,
   sans brief manqué que ntfy aurait livré ;
2. aucune alerte de demande perdue sur la même période (le journal du service
   ne montre pas de « Web Push : … » répété) ;
3. l'interrupteur vérifié après une mise à jour d'iOS et après une
   réinstallation de l'application (l'abonnement se reprend en un toucher).

Le retrait consiste à enlever `POKEPRICE_NTFY_URL` (et le jeton) du `~/.env`
du portable puis à resynchroniser les secrets ; le code de ntfy reste, éteint.

**Conséquences.**
- Une dépendance de plus dans l'extra `web` : `pywebpush` et `py-vapid`, qui
  tirent `aiohttp` et `http-ece`.
- La notification n'arrive que sur un téléphone où l'interrupteur a été
  touché, depuis l'application installée sur iPhone. Désinstaller
  l'application, ou bloquer ses notifications, coupe Web Push sans prévenir
  le serveur jusqu'au prochain 410 : ntfy couvre ce cas tant qu'il reste.
- Changer la paire VAPID invalide tous les abonnements : chaque téléphone
  doit retoucher l'interrupteur (il se réabonne avec la nouvelle clé). La
  commande refuse d'écraser un fichier existant pour cette raison.
- Un échec partiel (un téléphone sur deux) n'est pas réessayé pour le
  téléphone manqué : réessayer renverrait la notification aux autres.
- Le brief de 7 h 30 est envoyé par un processus séparé du serveur web ; il
  lit les mêmes abonnements dans la base.

**Pour aller plus loin.** [Installer la gestion](../APP.md#installer-la-gestion-sur-le-téléphone),
[variables et clés](../DEPLOYMENT.md#activer-les-notifications-web-push),
`tests/test_web_push.py`, `tests/web_push_runtime.cjs`,
`tests/web_push_toggle_runtime.cjs`.
