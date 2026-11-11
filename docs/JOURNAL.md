# Journal

> **Pour qui :** toute personne qui veut savoir ce qui a changé, et quand.
> **Vous y trouverez :** les changements notables, du plus récent au plus ancien, une à quatre lignes chacun, avec leur preuve.
> **Statut :** tenu à jour. Le détail complet est dans `git log` ; les raisons des choix sont dans les [fiches de décision](decisions/README.md).

Une page qui décrit le fonctionnement ne porte pas de date : quand un passage
daté la quitte, il est versé ici dans le même commit.

## 2026-11-11

- L'agent des lots passe sur le serveur, sous le compte restreint
  `lilydex-lots` (ni shell, ni `sudo`, ni clé `ssh`, ni accès à la collection
  ou aux secrets) : `pokeprice-lots-rotate.timer` lance chaque matin vers 10 h
  `pokeprice-agent lots-rotate --apply` vers l'interface locale, sans
  fournisseur d'IA. La clé lots se renouvelle sur le serveur, sous
  `pokeprice` et sans `ssh` (`lots-key-renew.sh` en mode local, vers 9 h 30) ;
  le renouvellement du poste devient un repli (`deploy/user/`). L'interpréteur
  du déploiement quitte `/srv/pokeprice` pour `/opt/pokeprice/.python`. Une
  étape ultérieure peut ajouter un agent d'IA sous le même compte
  ([AGENT_CONTROL](AGENT_CONTROL.md#agent-des-lots-sur-le-serveur),
  `deploy/pokeprice-lots-rotate.service`, `tests/test_lots_key_renewal.py`).
- Une carte qui quitte un lot de l'outil, par un retrait ou par la rotation
  d'un lot en ligne, revient seule en vitrine si son prix du jour relevé au
  plancher atteint 1 €, dans la même transaction ; les autres retournent au
  gisement. Les réponses listent `relisted` et `not_relisted`, et ces
  annonces ne comptent pas dans le quota des lots publiés
  ([décision 0045](decisions/0045-cartes-sorties-d-un-lot-en-annonce-unitaire.md),
  [AGENT_CONTROL](AGENT_CONTROL.md), `tests/test_agent_lots_relist.py`).
- Renouvellement automatique de la clé des lots, côté opérateur : un minuteur
  quotidien délivre une nouvelle clé 48 h avant l'échéance, la dépose pour
  l'utilisateur des lots (0640) et révoque l'ancienne aussitôt ; l'agent ne
  renouvelle jamais son propre accès. Le lanceur de l'agent met à jour son
  clone avant chaque lancement
  ([AGENT_CONTROL](AGENT_CONTROL.md#renouvellement-automatique-de-la-clé-des-lots),
  `deploy/lots-key-renew.sh`, `deploy/lots-agent-run.sh`,
  `tests/test_lots_key_renewal.py`).
- La production des lots passe par l'API agent : l'identité restreinte des
  agents des lots est en place, un utilisateur local distinct du poste de
  l'opérateur qui ne détient que le jeton des lots (ni clé `ssh`, ni `sudo`,
  ni compte sur le serveur), avec une clé lots déléguée par un administrateur
  pour 7 jours. `scripts/pokeprice_lots.py` perd `--remote` et `--local` :
  restent `--api` pour les agents et `--data` pour l'opérateur, là où vit la
  base ([AGENT_CONTROL](AGENT_CONTROL.md#déléguer-loutil-des-lots),
  [guide](../skills/pokeprice-lots/SKILL.md), `tests/test_agent_lots_client.py`).
- Les guides des agents passent par le client de l'API agent pour l'outil des
  lots : `pokeprice-lots` décrit le parcours plan, composition, vérification et
  publication, la rotation, les quotas, la clé d'idempotence et le sens de
  chaque code d'erreur ; `--remote` et `--local` n'y figurent plus que comme
  chemin opérateur, qui reste celui de la production tant que l'identité
  restreinte des agents n'y existe pas
  ([fiche 0044](decisions/0044-outil-des-lots-par-l-api-agent.md),
  [guide](../skills/pokeprice-lots/SKILL.md)).

## 2026-11-10

- Routes de publication de l'outil des lots sur l'API agent, réservées à
  `lots:publish` : publier un brouillon de l'outil (à blanc par défaut, prix
  relevé au plancher, chaque carte revérifiée dans la transaction) et retirer
  une annonce de lot de l'outil, dont les cartes reviennent au gisement. Avec
  `lots:compose` en plus, la rotation remplace les lots en ligne échus, un par
  transaction. `Listings.publish` refuse à un agent un lot qui porte une carte
  sans cote, non confirmée ou à examiner. Quota de 10 publications par jour
  ([AGENT_CONTROL](AGENT_CONTROL.md#publier-retirer-et-remplacer-les-lots-en-ligne),
  [fiche 0044](decisions/0044-outil-des-lots-par-l-api-agent.md),
  `tests/test_agent_lots_publish.py`).
- Routes d'écriture de l'outil des lots sur l'API agent, réservées à
  `lots:compose` : créer le brouillon d'un plan recalculé par le serveur
  (`stale_plan` sinon), faire tourner les brouillons (à blanc par défaut),
  annuler ou relever un brouillon de l'outil. Prix jamais sous le plancher du
  jour, plafond de 5 et cartes libres vérifiés dans la transaction ;
  idempotence, quotas et journal par événements, schéma inchangé. Nouveau
  réglage administrateur journalisé : âge de rotation des lots en ligne,
  14 jours ; la rotation signale ces lots (`due_online`) sans y toucher
  ([AGENT_CONTROL](AGENT_CONTROL.md#composer-faire-tourner-annuler-et-relever),
  `tests/test_agent_lots_compose.py`).
- Routes de lecture de l'outil des lots sur l'API agent, sous
  `/api/agent/v1/lots` et réservées à `lots:read` : gisement, état des
  brouillons, plan de composition à blanc avec `plan_id`, vérification de
  publication d'un brouillon de l'outil. Aucune n'écrit ; recette stricte,
  doublons seuls, six appels par minute pour le gisement et le plan
  ([AGENT_CONTROL](AGENT_CONTROL.md#lire-le-gisement-létat-et-un-plan),
  `tests/test_agent_lots_api.py`).
- Permissions `lots:read`, `lots:compose` et `lots:publish` sur les accès
  agent, sans route lots pour l'instant : délivrées par
  `pokeprice-manage agent-create --lots-*` au seul compte administrateur
  actif, retirées à l'appel suivant si ce compte perd ce rôle, jamais
  combinées avec brouillons, corrections ou assistant, plafond ramené à 20 €
  au plus. `/capabilities` les annonce, portée collection, au seul accès qui
  les détient. Création et révocation d'un accès sont journalisées ; schéma
  inchangé ([AGENT_CONTROL](AGENT_CONTROL.md#déléguer-loutil-des-lots),
  `tests/test_agent_lots_permissions.py`).
- Le moteur des lots quitte `scripts/pokeprice_lots.py` pour le paquet
  `pokeprice.lots` (gisement, propositions, rotation, publication, recette) ;
  il travaille sur la connexion que lui donne l'appelant, marge du plancher
  comprise. L'interprétation Gemini des prompts passe dans
  `pokeprice.lots_prompt`, que le serveur n'importe pas. Le script garde ses
  options et ses sorties (`tests/test_lots_package.py`,
  `tests/test_pokeprice_lots.py`).
- Limiteurs de débit bornés et normalisés : une adresse IPv6 compte pour son
  /64, chaque compteur garde au plus 4 096 clés, et `pokeprice-manage serve`
  ne fait confiance à `X-Forwarded-For` que depuis le proxy local. Limites et
  messages inchangés ; risques restants dans
  l'[audit de sécurité](AUDIT-SECURITE.md#limiteurs-de-débit-10-novembre)
  (`tests/test_ratelimit.py`). Préparé, pas encore déployé.
- Contrôles statiques en CI : `ruff` (lint, sans reformatage), `mypy` avec
  une base de départ pour les modules historiques, couverture publiée sans
  seuil, suite lancée sous Python 3.11, 3.12 et 3.13 (`pyproject.toml`,
  `.github/workflows/tests.yml`).
- Installation allégée : pandas, openpyxl et tabulate quittent le socle pour
  l'option `cli` (pipeline d'albums et `pokeprice-manage import`) ;
  `google-genai` passe dans `web` et `cli`. La commande d'installation du
  serveur ne change pas (`tests/test_extras.py`).
- La marge du plancher anti-bradage quitte la variable
  `POKEPRICE_LOT_MAX_MARGIN` pour un réglage de la base (schéma 27), modifiable
  par un administrateur connecté dans **Réglages → Plancher anti-bradage** et
  journalisé (auteur, date, ancienne et nouvelle valeur). L'outil de lots ne
  transmet plus la variable au serveur ; `--marge` de l'export n'accepte qu'une
  marge plus stricte. La migration reprend une fois la valeur de la variable du
  serveur ([décision 0042](decisions/0042-marge-du-plancher-reglage-administrateur.md),
  `tests/test_listings.py`, `tests/test_floor_requests.py`,
  `tests/test_pokeprice_lots.py`). Préparé, pas encore déployé.
- Le banc d'essai publie chaque taux avec son compte et son intervalle de
  confiance à 95 %, et sépare les vérités selon leur provenance (à l'aveugle,
  récoltée, banc initial). Deux commandes en lecture seule préparent son
  agrandissement vers 200 cartes : `bench-harvest` et `bench-sample`
  ([fiche 0043](decisions/0043-banc-provenance-et-intervalles.md)). Comptage
  sur la collection de référence : 301 variantes confirmées par une personne,
  dont 106 déclarées observées en main, aucune vérifiée à l'aveugle.
- La mesure « aucune variante fausse proposée au-dessus du seuil » compte les
  24 cartes du banc dont une personne a vérifié la catégorie de prix, au lieu
  des 14 confirmées dans la base au moment du passage : 0/24, taux sous 12 %.

## 2026-11-06

- La boutique passe sur son propre domaine, `lescartesdelily.fr` (OVH).
  `www.lescartesdelily.fr` et `lilydex.duckdns.org` redirigent en 301, chemin
  compris ; `oci-deploy.sh` prend ces redirections en arguments. Les sessions
  et abonnements Web Push, liés à l'ancienne origine, sont à refaire une fois.
- Le [plan de correction de l'audit](PLAN-AUDIT-CONFIDENTIALITE.md) précise
  la quarantaine des anciennes demandes sans preuve de destinataire et le
  rejeu par identifiants immuables. Les lots identité et rétention se mettent
  en ligne ensemble ; la réussite des tests ne vaut pas déploiement.
- Corrections L1/L2 de l'audit préparées : preuve d'adresse par le lien du
  vendeur, coordonnées figées, effacement durable et rejeu par identifiants de
  demandes, nettoyage d'audience indépendant. Scénarios de sauvegarde et de
  transfert rejoués sur bases temporaires (`tests/test_privacy_restore_identity.py`).
- Audit, assistant : effacer une conversation bloque les arguments, le
  contexte et les réponses tardives ; les messages expirés restent hors du
  chat et du modèle même sans purge. La saisie annonce le transfert vers
  Google et un flux coupé reste incomplet avec reprise possible
  (`tests/test_assistant_privacy.py`).
- Audit, accessibilité : chaque dialogue de la gestion est relié à son titre
  visible. Le contrôle statique vérifie une cible unique, visible dans le
  balisage et non vide ; aucun essai Orca ou TalkBack n'est réalisé
  (`tests/test_dialog_accessibility.py`).
- Chat de gestion : chaque question part avec l'heure de Paris et le rôle du
  compte (`server_context`) ; la date de la consigne suit Paris et non plus
  UTC ; la consigne ne suppose plus le genre de la personne ; `count_copies`
  donne la valeur de la sélection en cotes ; cas `compter-04` et `role-01` au
  banc ([fiche 0036](decisions/0036-contexte-de-la-question.md),
  [fiche 0037](decisions/0037-comptage-et-nombres.md)).
- Défaut du chat : à « top10 des cartes en doublon », il conseillait de se
  reconnecter, parce que l'interface joignait encore l'erreur de la session
  expirée d'avant la connexion. La dernière erreur est désormais datée, jointe
  cinq minutes au plus et effacée à la connexion ; la consigne ne la commente
  que si la question porte sur un problème ; cas `affichee-05` au banc.

## 2026-11-05

- Relecture du [plan de correction de l'audit](PLAN-AUDIT-CONFIDENTIALITE.md) :
  journal d'effacement externe aux archives, restauration avant publication,
  comparaison transactionnelle des prix et conservation distincte des échanges
  signalés. Le plan devient une page maintenue et contrôlée.
- Banc du chat, V1.1 complète sur master (#73 à #77) : trois passes sur
  Gemini 3.8 Flash, 61, 59 et 61 cas réussis sur 63 ; 14 pièges évités sur 14,
  aucune réponse dangereuse, cas « doublons » réussi aux trois passes, environ
  6 $ par mois estimés. Échecs : le modèle répond depuis la carte de
  l'application sans appeler `knowledge` (comment-05, comment-06), cherche
  dans le guide au lieu de préparer une écriture V2 (ecrire-01, -02, -07),
  compte au lieu de lister (chercher-10)
  ([résultats](../bench/assistant/results/gemini-3.8-flash-v1.1-passe1.md)).
- Chat de gestion, V1.1 comptage : outil `count_copies` (doublons par édition
  exacte ou par nom, classements, comptes par extension, langue, statut,
  sans plafond de page) et règle des nombres dans la consigne, après une
  réponse aux doublons inventés la veille au soir. Le banc gagne 14 cas
  (compter, comment faire, carte affichée) et la vérification des nombres ;
  trois passes provisoires sur Gemini 3.8 Flash donnent 59, 60 et 59 sur 60
  ([fiche 0037](decisions/0037-comptage-et-nombres.md),
  [rapport](../bench/assistant/results/gemini-3.8-flash-v1.1-passe1.md)).
- Chat de gestion, V1.1 : une carte courte de la gestion dans sa consigne, et
  l'outil `knowledge`, qui lit à la demande une section du guide ou une règle
  métier (plancher, dérogations, autonomie, lots, ordre du classeur), sans les
  commandes de serveur. Deux cas « comment faire » rejoignent le banc
  ([fiche 0035](decisions/0035-connaissances-de-l-assistant.md)).
- Chat de gestion, V1.1 : chaque question part avec le contexte de l'écran
  (vue, fiche par identifiant, filtres, appareil, version, dernière erreur),
  validé par liste blanche côté serveur, lu par le modèle comme une donnée et
  gardé 30 jours avec la question ; le banc accepte un contexte par cas
  ([fiche 0036](decisions/0036-contexte-de-la-question.md),
  `tests/test_assistant_context.py`). Pas encore rejoué avec Gemini.
- Chat de gestion, capture des échecs : bouton 👎 sous chaque réponse avec
  une note facultative, signaux du serveur (erreur du modèle ou d'un outil,
  plafond de tours, question reformulée) et convention « Défaut : … » ;
  les conversations signalées échappent à la purge des 30 jours (180 jours
  au plus) et `pokeprice-manage assistant-drafts` en tire des brouillons du
  banc sans donnée réelle ([fiche 0038](decisions/0038-capture-des-echecs.md),
  `tests/test_assistant_signals.py`).
- Alerte de coût du chat : les jetons s'additionnent par mois civil, hors de la
  purge des 30 jours, et une notification part une fois par mois quand le coût
  estimé atteint 30 € ; la grille des tarifs passe du banc au paquet
  ([fiche 0039](decisions/0039-alerte-de-cout-du-chat.md)).
- Premier brief du matin reçu par ntfy et Web Push, sans erreur. ntfy est
  ensuite retiré du serveur : il ne doublait que le téléphone du propriétaire,
  déjà abonné à Web Push, et l'adresse de son sujet avait fui
  ([fiche 0033](decisions/0033-notifications-web-push.md)).

## 2026-11-04

- Notifications plus visibles : l'interrupteur passe en tête des Réglages, au-dessus
  des sauvegardes, où il passait inaperçu, et le brief propose « Recevoir le
  brief sur cet appareil » tant que l'appareil n'est pas abonné
  ([guide](APP.md#recevoir-les-notifications-sur-le-téléphone)).
- Chat de gestion activé sur le serveur avec sa clé Gemini dédiée. Le banc,
  rejoué avec la consigne finale du chat, donne 46/46 et 14/14 pièges évités
  pour Gemini 3.8 Flash (réponse p50 4,2 s ;
  [rapport](../bench/assistant/results/gemini-3.8-flash-v1.md)).
- `oci-sync-secrets.sh` transmet aussi `POKEPRICE_PACKING_GRAMS` : le fichier du
  serveur est réécrit en entier, et cette variable s'y perdait.
- Chat de gestion, V1 en lecture : bouton **Assistant** dans la gestion,
  réponse en flux continu par `POST /api/assistant`, huit outils en lecture
  appelés par le serveur sous `assistant:read`, quatre tours d'outils au plus,
  plafond quotidien et débit par compte, jetons affichés, conversations
  gardées 30 jours hors des sauvegardes ; sans `POKEPRICE_ASSISTANT_GEMINI_KEY`,
  le chat est éteint. La consigne système est partagée avec le banc
  ([guide](APP.md#lassistant), [fiche 0034](decisions/0034-conversations-du-chat.md),
  `tests/test_assistant.py`). Le banc n'a pas été rejoué avec la consigne
  finale : aucune clé Gemini sur le poste.
- Notifications Web Push de la gestion installée : interrupteur « Notifications
  sur ce téléphone » dans les Réglages, abonnements par compte de gestion
  (schéma 25, table `push_subscriptions`), canal `webpush` à côté de ntfy et de
  l'e-mail pour le brief et les alertes, clés générées par
  `pokeprice-manage vapid-keys` ; ntfy reste en secours
  ([fiche 0033](decisions/0033-notifications-web-push.md),
  [activation](DEPLOYMENT.md#activer-les-notifications-web-push),
  `tests/test_web_push.py`).
- Modèle du chat retenu : Gemini 3.8 Flash, avec une clé à lui sur une offre
  payante ([fiche 0031](decisions/0031-modele-du-chat.md), passée en vigueur).
- Banc du modèle du chat de gestion : 46 commandes types en français
  familier, rejouées en deux tours au plus sur des données synthétiques, avec
  les outils en lecture de la fiche 0032 et quatre outils d'écriture fictifs.
  Mesurés : Gemini 3.8 Flash (46/46, 3,9 s au médian), Gemini 3.5 Flash-Lite
  (40/46) et quatre gemma4 locaux sur le processeur (19 à 41/46, jusqu'à
  38 s) ; aucun n'a fait d'action dangereuse. Claude n'est pas mesuré, faute de
  clé. Proposition : Gemini Flash avec une clé à lui
  ([fiche 0031](decisions/0031-modele-du-chat.md),
  [banc](../bench/assistant/README.md), `tests/test_assistant_bench.py`).
- Assistant de gestion, V1 en lecture : huit outils fermés (`search_copies`,
  `get_copy`, `explain_price`, `why_not_for_sale`, `list_listings`,
  `sales_summary`, `agent_activity`, `todo_queue`) avec schémas JSON stricts,
  servis sous la portée de délégation `assistant:read`
  (`/api/agent/v1/assistant-tools`) ; aucune sortie ne porte de donnée de client
  ([fiche 0032](decisions/0032-outils-assistant-lecture.md),
  [schémas](assistant-tools.json), `tests/test_assistant_tools.py`).
- Gestion installable comme application (PWA) : manifeste et service worker de
  portée `/gestion`, icônes tirées de la mascotte, page hors ligne, aide à
  l'installation dans les Réglages (iPhone et Android). Le cache, nommé d'après
  le contenu de l'interface, ne garde jamais `/api` ni les photos ; la vitrine
  ne change pas ([guide](APP.md#installer-la-gestion-sur-le-téléphone),
  `tests/test_app_install.py`).
- Brief du jour programmé sur le serveur : `pokeprice-brief.timer` envoie
  chaque matin vers 7 h 30 `brief --notify`, après la cotation matinale
  ([déploiement](DEPLOYMENT.md#envoyer-le-brief-du-jour)). Son texte compte aussi les photos
  demandées par l'agent et les demandes de la vitrine traitées.
- Gestion : assistant de gestion, V0 sans modèle de langage. En haut de la
  gestion, un « Brief du jour » résume ce que les agents ont fait depuis
  24 heures, d'après les événements journalisés, et la file « À toi » liste
  les seules décisions de l’opératrice (demandes à traiter, lots à expédier ou à
  encaisser, prix sous le plancher à trancher, photos à reprendre dans l'ordre
  du classeur), chacune avec son
  bouton. Route `GET /api/todo`, commande `pokeprice-manage brief [--notify]`
  ([guide](APP.md#le-brief-et-la-file--à-toi-), `tests/test_todo.py`).
- Plancher anti-bradage : un prix d'agent sous le plancher devient une demande
  de dérogation que la gestion accorde, relève au plancher ou refuse
  (`GET /api/floor-requests`, panneau « Prix sous le plancher à trancher ») ;
  un agent ne publie plus seule une carte sans référence ;
  `pokeprice-manage floor-audit` liste les annonces en ligne que la cote a
  fait passer sous le plancher, sans rien republier
  ([fiche 0030](decisions/0030-derogations-plancher.md),
  `tests/test_floor_requests.py`).
- Assistant de gestion proposé : un brief du jour poussé par la notification
  et affiché en haut de la gestion, une file « À toi » limitée aux décisions
  humaines et aux photos à reprendre, puis un chat qui n'agit que par des
  outils fermés avec sa propre délégation ; le choix du modèle reste ouvert
  ([fiche 0029](decisions/0029-assistant-de-gestion.md)).
- Sauvegardes : les archives du serveur ne recopient plus les 758 Mo de
  photos. Chaque photo est gardée une fois, par lien physique, dans la réserve
  `backups/photos/`, et l'archive de la nuit (format v2) ne porte que la base,
  les preuves et la liste des photos. Le portable ne rapatrie que les photos
  nouvelles (environ 10 Mo par nuit au lieu de 800 Mo) et reconstitue
  l'archive complète v1 envoyée sur Drive ; les archives v1 existantes se
  restaurent comme avant
  ([fiche 0028](decisions/0028-reserve-de-photos-par-empreinte.md),
  `tests/test_photo_reserve.py`).
- Exploitation : le disque du serveur, rempli à 89 % (27 Go sur 30) surtout
  par des archives de 800 Mo, est vidé de ses archives ponctuelles périmées
  et de ses dossiers d'essai, puis agrandi à 200 Go (183 Go pour `/`, 12 %
  occupés). La rotation des sauvegardes passe aussi avant d'écrire l'archive
  de la nuit : sur un disque presque plein, le contrôle d'espace la refusait
  et la rotation ne libérait jamais de place
  ([Sauvegardes](DAILY-BACKUPS.md#rétention), `tests/test_backup_retention.py`).
- Vitrine : le mode de livraison d'une demande (`delivery`, `registered`) a
  ses propres colonnes au lieu d'un préfixe `[delivery:…]` dans le message ;
  le schéma 24 reprend les demandes existantes et retire le préfixe de leur
  message (`tests/test_shipping_and_conditions.py`).
- Vitrine : calcul des frais de port avant réservation selon les tarifs La Poste
  2026 (lettre suivie, recommandé R2 obligatoire dès 50 € de cartes, remise en
  main propre gratuite) ; réponse préremplie en un clic pour l'opératrice dans
  la gestion ; pages statiques bilingues de conditions de vente `/conditions` et
  `/en/conditions` référencées dans le sitemap
  ([fiche 0027](decisions/0027-frais-de-port-et-conditions-de-vente.md),
  `tests/test_shipping_and_conditions.py`).
- Sauvegardes : avant un lot de photos, une page de classeur ou un
  déplacement, l'application copie la base seule (environ 36 Mo) au lieu
  d'une archive avec les photos (800 Mo), qui remplissait le disque du
  serveur en quelques lots ; les 5 dernières copies de chaque sorte sont
  gardées (`tests/test_backup_retention.py`).
- Gestion : déplacement en lot d'une sélection de cartes vers un autre album ou
  une autre page (`/api/move-batches`, action « Déplacer vers… »), avec aperçu
  des emplacements et des collisions de cases, placement dans les premières
  cases libres ou à partir d'une page et case données, refus des cartes
  réservées, vendues ou en lot actif, application transactionnelle tout ou rien
  avec sauvegarde et historique par carte, et annulation complète
  ([décision 0024](decisions/0024-deplacements-en-lot.md),
  `tests/test_move_batches.py`, `tests/test_web_client.py`).
- Plancher anti-bradage en gestion : la règle (`POKEPRICE_LOT_MAX_MARGIN`, 15 %
  par défaut, bornée de 0 à 50, `lot_max_margin` et `lot_floor_cents`) est
  définie une seule fois dans `src/pokeprice/pricing.py` et partagée par
  `listings.py`, `marketplace_export.py` et `scripts/pokeprice_lots.py`. La
  gestion affiche le minimum autorisé avant validation et refuse tout prix de
  lot ou prix unitaire manuel sous ce plancher ; une carte à variante à
  vérifier compte pour la plus basse cote de ses variantes, jamais 0 ([décision 0026](decisions/0026-plancher-anti-bradage-gestion.md),
  `tests/test_listings.py`, `tests/test_web_client.py`).

## 2026-11-03

- Cotation en lot : une cote qu'un marché instable déplacerait d'au moins
  20 % reste en place ; le relevé est gardé et la carte passe « À vérifier »
  ([fiche 0023](decisions/0023-cote-retenue-marche-instable.md),
  `tests/test_prices_bulk.py`). Vu à l'essai de la cotation matinale sur une
  copie : −11 % de cote totale, communes portées à 7 € par une vente isolée.
- Gestion : **Page de classeur (3×3)** dépose ou photographie une page entière
  pour un album et un numéro de page, la découpe en 9 pochettes avec `slicer.py`
  et affiche l'aperçu case par case (remplacement du recto sur une pochette
  occupée, nouvelle fiche « À identifier » sur une case vide), avec application
  atomique précédée d'une sauvegarde et annulation gardée par version
  ([décision 0025](decisions/0025-photo-page-classeur-gestion.md),
  `tests/test_workflows.py`, `tests/test_web_client.py`).
- Vente sur les plateformes : `scripts/export_annonces.py` prépare, en lecture
  seule, une annonce par dossier pour Vinted et Leboncoin et le fichier d'import
  de stock Cardmarket ; prix jamais sous la cote moins une marge réglable
  ([guide](VENTE-PLATEFORMES.md)). Rien n'est publié automatiquement.
- Vitrine : chaque demande de réservation prévient le vendeur par ntfy et par
  courriel, avec rappels à J+2 et J+5, sans donnée du client
  ([fonctionnement](VITRINE.md#les-alertes-au-vendeur)). Le client web lit
  `?demande=` une fois, à l'ouverture de la gestion, avant que l'adresse ne soit
  réécrite (`tests/test_notifications.py`, `tests/test_web_client.py`).
- Politique IA : la règle « la machine propose, l'humain décide » laisse place
  à l'autonomie maximale des agents ([fiche 0021](decisions/0021-autonomie-maximale.md)),
  avec un plancher anti-bradage et la demande de nouvelle photo. Guide chapeau
  `pokeprice-autonome` ; aucun comportement du code changé.

- L'agent de revue confirme variante et état par le chemin d'écriture humain
  quand finition, édition par l'image et état concordent ; sinon il demande
  une photo, listée dans « Photos à reprendre ». Commande `agent-review`,
  passage annulable ([décision 0022](decisions/0022-agent-confirme-ou-demande-photo.md)).

## 2026-10-29

- CI de la vitrine : recette Playwright versionnée, exécutée dans Firefox et
  WebKit sur données synthétiques locales ; zoom, filtres, toucher, clavier et
  reprises après erreur. Rapports et captures archivés, traces en cas d'échec.

- Recette Firefox et WebKit sous Linux : la reprise d'une photo en échec renouvelle
  les adresses de ses variantes, pour provoquer une nouvelle requête sous WebKit
  tout en conservant les dimensions adaptatives. Régression couverte sur données synthétiques.

- Entretien : actions CI sur Node 24, versions fixées par commit ; nettoyage
  indépendant des dérivés publics non référencés, après 30 jours, avec simulation
  manuelle et plafonds par passage. Base, photos sources et sauvegardes préservées.

- P2 de la vitrine : zoom partagé avec la gestion, images de consultation
  adaptatives, aperçus sociaux servis sans JavaScript et filtre d'état confirmé.
  Les variantes et le zoom ne gonflent plus le comptage des ouvertures de fiche.
  Développement et recette locaux, sans modification de la collection ni mise en ligne.

- Le favicon se conserve un jour avec ETag : les changements d'adresse de la
  visionneuse réutilisent l'icône sans la télécharger à chaque ouverture et fermeture.

- Mise en ligne des parcours et performances de la vitrine (#34, `e79a561`) :
  base existante conservée, sauvegarde du code restaurée et comparée, pages
  publiques à 200, gestion API à 401 et assets revalidés à 304. La recette révèle
  un débordement de photo verticale de lot ; le cadre de la visionneuse le contient.

- Vitrine : grille progressive, fiche desktop en colonnes, identité publique et
  navigation harmonisées ; menu, focus et soumissions répétés corrigés. Chargement
  stabilisé, cache statique revalidé et budgets photos/API séparés. Recette locale
  sur données synthétiques, sans modification de la collection.

## 2026-10-28

- Lots thématiques : skill `pokeprice-lots` et script `scripts/pokeprice_lots.py`
  pour l'analyse des doublons et la composition de lots par intention en langage
  naturel (`compose` via Gemini Structured Outputs). Rotation glissante plafonnée
  à 5 brouillons dans l'espace Ventes, diagnostic transparent de stock, périmètre
  extensible à toute la collection (`--scope {duplicates, all}`) et publication
  directe en vitrine (`publish-to-storefront`) avec dépublication unitaire
  automatique des cartes composant le lot.

- Vitrine : la fiche mobile garde prix et faits hors des actions ; la vue Filtres
  conserve recherche, compteur et critères. Chargement annoncé, reprise visible
  après panne et retour au catalogue depuis un résultat vide. Contraste des
  contrôles et radios de thème corrigés ; recette sur données temporaires.

- Mise en ligne de la vitrine anglaise et des erreurs traduites (#30, #31,
  `01c0376`) à la place de `f89a9d6`, sans migration ; base conservée. En ligne :
  `/health`, `/`, `/en/`, `/a-propos` et `/gestion` à 200, `/api/listings` à
  `401` ; une connexion erronée répond `wrong_credentials` et `/en/` porte
  « Incorrect email or password. » ; 1 415 annonces.

- Vitrine : les erreurs du serveur qu'un visiteur peut rencontrer portent un
  `code` à côté du `detail` français ; la page les affiche dans sa langue, si
  bien qu'une carte retirée ou un mot de passe erroné se lisent en anglais sous
  `/en/` ([fiche 0020](decisions/0020-textes-dans-des-dictionnaires.md)).

## 2026-10-27

- Vitrine : ses textes passent dans un dictionnaire, `messages/fr.json`, que le
  serveur et `t()` lisent ([fiche 0020](decisions/0020-textes-dans-des-dictionnaires.md)).
  Rien ne change à l'écran ; c'est le prérequis de la version anglaise.

- Vitrine en anglais sous `/en/`, avec `/en/carte/…` et la page À propos
  traduite, `/en/a-propos`, où le texte français fait foi. Un lien en pied de
  page change de langue sur la même carte. L'API publique envoie le code de la
  finition au lieu de son libellé français.

- Mise en ligne du logotype dérivé de `SITE_NAME` (#29, `f89a9d6`) à la place de
  `decf086`, sans migration ; base conservée. En ligne : `/health`, `/`,
  `/a-propos` et `/gestion` à 200, `/api/listings` à `401` ; logotype servi en
  deux lignes ; ni marqueur `{{` ni « Lilydex » sur les trois pages ; 1 415 annonces.

- Vitrine : le logotype « Les cartes / de Lily » dérive lui aussi de `SITE_NAME`,
  coupé avant le dernier « de ».

- Mise en ligne de la visionneuse plein écran corrigée, des vignettes de
  **Ma sélection** et du nom Les cartes de Lily (#27, #28, `decf086`) à la place
  de `422d1c2`, sans migration ; base conservée. En ligne : titres des trois
  pages au nouveau nom, sans « Lilydex » ; photo réelle entière en plein écran à
  1280 × 800 ; vignette affichée dans la sélection ; 1 415 annonces ; gestion à
  `401` sans session.

- Le produit s'appelle Les cartes de Lily ([fiche 0019](decisions/0019-les-cartes-de-lily.md)).
  Vitrine, À propos, gestion et export des données prennent le nom d'une seule
  constante ; la documentation vivante suit. Dépôt, adresse et identifiants
  techniques gardent `lilydex`.

- Vitrine : **Ma sélection** montre le recto de chaque carte choisie, y compris
  dans une sélection enregistrée avant ce changement.

- Vitrine : en plein écran sur ordinateur, la photo d'une fiche tient dans
  sa zone ; elle la dépassait sans qu'on puisse la faire défiler.

- Mise en ligne de la vitrine « Les cartes de Lily » (#26, `422d1c2`) à la
  place de `9d50f93`, sans migration ; base conservée, sauvegarde de la nuit
  présente. En ligne : 1 415 annonces avec leurs photos, filtres Extension et
  Finition, critères relus depuis l'adresse, fiche ouverte depuis un résultat
  filtré, gestion à `401` sans session.

- Vitrine : intégration du catalogue « Les cartes de Lily », palette crème,
  sauge et terracotta, photos entières et réservation accessible dans l'en-tête.
  Les filtres Extension et Finition précèdent la pagination côté serveur ; sur
  téléphone, une vue dédiée conserve les critères et annonce le total global.
  Vérification sur données temporaires, sans migration ni déploiement.

- Vitrine : la fiche d'une carte devient une visionneuse, en plein écran sur
  téléphone : carte voisine d'un glissement ou d'une flèche, recto et verso,
  adresse `/carte/<id>` tenue à jour.

- À propos : la mascotte, la même danseuse en pied, illustre « Qui vend ? ».
  Dans la gestion, le logo n'ouvre plus la visionneuse des photos.

- Identité : un logo (une danseuse de flamenco en chibi, un lys dans le
  chignon, un éventail de cartes) remplace le « L » des en-têtes, et l'onglet
  a son icône : `/favicon.ico` ne répond plus 404. Les images sont générées en
  local avec Z-Image Turbo, sans aucun personnage ni dessin Pokémon, puis
  détourées.

- Vitrine : les moyens de paiement (Wero, virement, PayPal) se règlent dans
  la gestion. Un client voit le total, la référence du lot et les coordonnées
  tant que son lot est réservé et non payé ; la gestion copie le même texte
  pour l'e-mail, et `/a-propos` nomme les moyens sans coordonnées (schéma 21).

- Vitrine : une réservation se demande sans compte, avec un nom et un e-mail ;
  accepter la demande valide le client. Le vendeur envoie depuis sa
  messagerie un lien à usage unique pour choisir ou changer un mot de passe
  (schéma 20, [fiche 0018](decisions/0018-reservation-sans-compte.md)).

- Gestion : la grille annonce son chargement, la pagination donne le numéro
  de page et permet d'y sauter, l'onglet « Gestion » devient « Réglages », les
  barres des statistiques se lisent au toucher et au clavier, et l'en-tête de
  la collection est plus compact sur téléphone.

- Vitrine : les thèmes s'appellent Clair, Sombre et Dense (boutons de 40 px
  sur écran tactile), le panier devient « Ma sélection » pour ne plus se
  confondre avec « Mes demandes », le filtre de langue ne propose que les
  langues en vente et « Afficher plus » indique où l'on en est.

- Dépendances : Pillow 13, filelock 4.2, setuptools 84.2, opentelemetry-api
  1.45.1 et certifi à jour, qui ferment les 49 alertes Dependabot ouvertes.
  Python 3.11 devient le minimum ([fiche 0017](decisions/0017-python-3-11-minimum.md)).

- Vitrine : la recherche trouve les noms anglais et des autres langues du
  catalogue (« eevee » → Évoli) et pardonne une faute de frappe. Chaque carte a
  une adresse partageable (`/carte/…`), les filtres restent dans l'adresse et
  Retour ferme la fiche.

- Audit d'ergonomie de la vitrine et de la gestion. Vitrine : le badge ne
  promet plus de verso (aucune annonce n'en a), l'état non confirmé est dit,
  une publication en masse se lit de A à Z, les cartes apparaissent dès le
  premier écran mobile, le bouton de réservation reste visible. Gestion : la
  fiche d'exemplaire perd ses doublons et replie les outils et champs techniques.

## 2026-10-23

- Statistiques : « Do Not Track » n'exclut plus une visite (une visite de
  contrôle depuis un Chrome qui l'envoyait n'était pas comptée), les pages que
  Chrome précharge sont comptées, et une erreur d'enregistrement va au journal
  du service. Global Privacy Control reste respecté.

- La gestion a un onglet **Statistiques** : fréquentation de la vitrine
  comptée sans cookie ni adresse conservée (empreinte salée effacée chaque
  soir, totaux 25 mois), robots et équipe exclus. Registre RGPD et notice
  `/a-propos` complétés.

- Exploitation : les sauvegardes ponctuelles ont une rétention (3 dernières,
  sinon 14 jours ; 5 copies d'avant migration), après qu'elles ont rempli le
  disque du serveur ; une sauvegarde est refusée avant d'écrire si la place
  manque. `prices --unpriced` relève les cartes sans prix de référence. Après
  un produit Cardmarket jugé incorrect, le relevé cherche le bon dans le guide.

- Le relevé de prix complète TCGdex par le guide des prix officiel de
  Cardmarket quand TCGdex ne donne pas de cote : 45 des 47 cartes liées sans
  cote en trouvent une ([fiche 0016](decisions/0016-guide-des-prix-cardmarket.md)).

- Exemplaires sans prix ramenés de 276 à 71 ([plan d'action](PLAN-PRIX-MANQUANTS.md)) :
  les énergies de base confirmées partent en vrac
  ([fiche 0015](decisions/0015-energies-de-base-en-vrac.md)), 88 énergies
  proposées par la porte confirmées sur planche, et 68 identités « à
  vérifier » confirmées en lot, avec leur relevé TCGdex, après tri DINOv2 et
  coches du propriétaire. Une sauvegarde précède chaque lot.

- La fiche montre l'image TCGdex de l'édition à côté du recto, avec ses liens
  TCGdex et Cardmarket ; l'image anglaise remplace une image française
  absente. La galerie du contrôle d'édition exclut les cartes TCG Pocket, qui
  faussaient des doutes et des désaccords. Les commandes lancées sur le
  serveur atteignent l'application par la boucle locale.

## 2026-10-21

- Lecture locale par Ollama rétablie : Gemma 4 raisonnait avant de répondre
  et épuisait son budget de jetons, si bien que `pokeprice scan` renvoyait des
  réponses vides ; la requête désactive ce raisonnement. Sur deux pages de
  classeur, le prompt multilingue n'invente plus de nom français pour des
  énergies anglaises et lit les cartes françaises comme avant.

- Identification assistée corrigée (issue #2) : une lecture Gemini n'efface
  plus un champ déjà rempli et ne réinitialise plus un tampon noté, sauf pour
  proposer un tampon qu'elle lit ; une édition unique, au nom et à la
  référence exacts, est présélectionnée ; une édition choisie sans
  confirmation garde extension et identifiant catalogue en « à vérifier » ;
  les remarques de la lecture rejoignent les notes
  ([Ajouter une carte](APP.md#ajouter-une-carte)).

## 2026-10-20

- Banc comparatif de huit modèles Gemini via Pi sur le parcours des prix
  manquants et de cohérence BDD (`pokeprice-agent-prix`) : `gemini-3.1-flash-lite`
  (18 s, 1,4 c$) et `gemini-2.5-flash-lite` (48,5 s, 0,9 c$) atteignent `8/8`
  pour un coût onze à dix-huit fois inférieur à `gemini-3.8-flash`
  ([résultats](AGENT_PRICE_EVALUATION.md#banc-comparatif-des-modèles-gemini),
  [relevé](evaluations/agent-pricing-gemini-2026-10-20.json)).

- Les guides de `skills/` sont exposés dans `.agents/skills` et `.codex/skills`
  et référencés dans [AGENTS.md](../AGENTS.md) pour la découverte automatique
  par les clients agents. La page [Résoudre les cartes en suspens](RESOLUTION_CARTES.md)
  planifie l'enchaînement entre outils locaux, agent multimodal et examen en
  main pour les trois files (« À identifier », « À vérifier », « À examiner »).

- Le guide autonome `pokeprice-agent-prix` reprend le diagnostic des prix
  manquants et l’application des corrections déjà autorisées. Les cas
  synthétiques rejouent les rapprochements, refus et conflits de version,
  sans remplacer une évaluation du comportement du modèle ou du gain humain
  ([réception](AGENT_PRICE_EVALUATION.md)).

- Le pilote agent applique les corrections de catalogue et relevés préautorisés
  par le propriétaire : plan borné par délégation, version et empreinte, reçu
  sans doublon et identité d’agent dans l’historique. Aucune confirmation
  physique n’est créée ([décision 0014](decisions/0014-corrections-agent-autorisees.md)).

- Recherche catalogue : les apostrophes droites/courbes et le suffixe Delta
  omis dans un nom ne masquent plus une édition candidate. La référence,
  la langue et les PV restent contrôlés ; le choix et la confirmation restent
  explicites. La fiche distingue une identité confirmée sans lien catalogue
  d'une carte sans cotation ([application](APP.md#relever-les-prix)).

- Refonte de la documentation : pages au présent, journal unique, fiches de
  décision, glossaire, contrôle automatique des liens et des dates
  (`scripts/check_docs.py`). La documentation d'avant la refonte reste lisible
  au commit `fecf90e`.

## 2026-10-19

- Pilote agent livré : un agent IA prépare des brouillons de lots sur un album
  délégué, avec une clé révocable ([pilote agent](AGENT_CONTROL.md)).
- Synchronisation portable ↔ serveur explorée, non retenue
  ([proposition archivée](archive/SYNC_PROPOSAL-2026-10-19.md)).

## 2026-10-18

- Les copies Drive sont chiffrées avec age (X25519) avant l'envoi : Drive ne
  reçoit plus que des fichiers `.zip.age`
  ([fiche 0003](decisions/0003-drive-depuis-le-portable-chiffre.md)). Les
  copies envoyées avant (`.zip` sans `.age`) restent lisibles par Google
  jusqu'à ce que la rétention Drive les mette à la corbeille ; on peut les y
  mettre plus tôt à la main sans gêner le service.
- Données personnelles : espace « Mon compte », registre des traitements,
  durées de conservation et procédures ([RGPD](RGPD.md)).
- Option vision installée sur le serveur ARM, avec torch pour processeur seul ;
  empreinte mémoire et disque mesurée ([hébergement](DEPLOYMENT.md)).

## 2026-10-17

- Le portable rapatrie chaque nuit l'archive vérifiée du serveur et l'envoie
  sur Drive ; il ne sauvegarde plus sa propre base, devenue une copie. L'ancien
  timer `pokeprice-local-backup.timer`, qui archivait `data/inventory`, est
  désactivé (`systemctl --user disable --now pokeprice-local-backup.timer`).
  Les archives rapatriées prennent le préfixe `oci-`, qui les distingue des
  archives `daily-<date>.zip` faites auparavant sur le portable.
- Rétention des archives sur Drive : les plus anciennes vont à la corbeille.
- Délai de transfert proportionnel à la taille de l'archive, après qu'un délai
  fixe de 240 s a interrompu trois fois l'envoi d'une archive de 790 Mo.

## 2026-10-16

- Le serveur Oracle Cloud devient la référence de la collection
  ([fiche 0002](decisions/0002-oracle-cloud-serveur-fait-foi.md)). Une journée
  de travail faite sur le portable seulement (65 cartes importées,
  51 identifications, 832 relevés, 680 photos redécoupées) y est reportée en
  remplaçant la base du serveur par celle du portable : c'était possible sans
  perte parce que 22 tables sur 24 étaient identiques à la sauvegarde
  d'origine ; les comptes et les sessions du serveur ont été conservés. Depuis,
  le portable ne sert plus qu'aux essais et aux sauvegardes.
- Code publié sous licence MIT, après un [audit de sécurité](AUDIT-SECURITE.md),
  dans un dépôt neuf sans l'historique d'avant la réécriture du 12 octobre.
- Vitrine publique livrée en quatre tranches ([vitrine](VITRINE.md)) : rôle
  client et séparation des routes (11 routes de gestion passent de
  « connecté » à « équipe » ; sur 69 routes, 8 restent hors équipe, listées
  dans un test) ; publication et prix affiché ; vitrine sans compte, essayée
  en largeur ordinateur et téléphone sur une base temporaire ; inscription et
  demandes de réservation, parcours complet essayé au navigateur. La vitrine
  passe à la racine du site, la gestion sur `/gestion`.
- Porte énergie dans le pipeline d'albums ([IA et vision](IA-VISION.md)).
- Audit des photos des classeurs : 680 photos redécoupées, 140 corrections,
  22 cartes à retourner dans le classeur ([audit des photos](AUDIT-PHOTOS.md)).

## 2026-10-14

- Six nouveaux classeurs numérisés et importés.
- `repair-pages` appliqué : 210 exemplaires des classeurs Diamond & Pearl et
  Platinium reculent d'une page (la couverture avait été comptée comme page 1).
- Tesseract écarté sur mesure ; la langue est contrôlée par cohérence
  ([fiche 0005](decisions/0005-langue-sans-tesseract.md)).

## 2026-10-13

- Gemini retenu seul lecteur de texte ; l'agent Antigravity écarté (69 à
  117 s et plus de 50 000 jetons pour une photo)
  ([fiche 0004](decisions/0004-gemini-seul-lecteur.md)).
- Contrôles indépendants (jalon M2), tranches 1 à 3 : lecture de la finition
  et proposition de variante, lecture à la saisie avec le banc d'essai en
  test de non-régression, contrôle de l'édition par l'image (DINOv2).
- Référentiel des impressions en mode audit (jalon M1.1) : contrat, socle, et
  premier cas de bout en bout, EX Fantômes Holon 78 en français
  ([guide du référentiel](PRINT_REFERENCE_GUIDE.md)).
- Audit des variantes Foil clos : les 8 Foil signalées par une alerte du
  relevé confirmées une à une, 14 autres dans la journée, les 35 dernières de
  l'album Platinium en groupe sur observation (reverse, absence de tampon
  constatée). Dix sont des reverses Noir & Blanc que TCGdex ne répertorie pas.
- File « À examiner » : 31 cartes sur 403 (7,7 %) au seuil de 10 €, toutes en
  attente d'un prix ; elle en comptait 34 à 10 € et 57 à 5 € avant le
  nettoyage du jour. La borne de 15 % du critère de M1 est abandonnée.
- Premier cas de bout en bout du référentiel : le Pikachu 78/110 français
  d'EX Fantômes Holon a une correspondance Cardmarket prouvée (produit 277048,
  reverse). L'encyclopédie officielle française n'a aucune carte de cette
  extension, et Cardmarket refuse la capture automatisée : la preuve a coûté
  environ une heure, plus deux minutes d'enregistrement de page.
- Le référentiel ne bloque plus M2 : son premier paquet de règles, anglais, ne
  résout aucune des 404 cartes de la collection (395 FR, 6 EN, 2 JA, 1 IT), et
  les 27 cartes des familles de régression sont françaises ou italienne.
- Prix saisi à la main pour les cartes sans cote TCGdex, et verdict humain sur
  le produit Cardmarket associé par TCGdex, avec détection des produits
  partagés entre numéros voisins ([valeur en jeu](VALUATION.md)).

## 2026-10-12

- Point de départ de la feuille de route du MVP : 405 exemplaires dans
  4 classeurs, 401 identités confirmées, 12 cartes relevées en détail,
  1 estimation de vente, 1 lot réservé ; 174 tests. Écarts relevés : aucune valeur en jeu
  calculée (23 Rare Holo marquées Foil, sous-cotées d'environ 330 €),
  contrôles du banc non branchés, reverses indétectables, tunnel instable
  (cinq coupures en deux heures).
- Valeur prudente et file « À examiner » (jalon M1) ([valeur en jeu](VALUATION.md)) :
  57 cartes sur 405 (14,07 %) dans la file au seuil de 10 €, les quatre
  éditions de valeur attendues comprises. Avec la finition observée et la
  confirmation physique, la file passe à 73 sur 405 (18,02 %) : aucun contrôle n'est masqué
  pour tenir la borne de 15 %.
- Catégorie Standard ou Foil calculée depuis les observations physiques et les
  métadonnées de l'édition, imposée aussi par le serveur ; les corrections
  anciennes sans finition reviennent dans la file sans être déclarées
  erronées. Audit en lecture seule : `scripts/audit_variant_categories.py`.
- Premier relevé TCGdex de toute la collection (`pokeprice-manage prices`) :
  379 cartes ; 20 sans cote TCGdex.
- Noms dans six langues pour la recherche : premier passage de
  `pokeprice-manage names`, 1 136 requêtes TCGdex en 7 min 37 s, puis aucune.
- Restauration de l'instantané initial depuis Drive, vérifiée
  ([instantané](RECOVERY.md)).
- Historique git réécrit pour en retirer les données personnelles.
- Feuille de route du MVP ([ROADMAP](ROADMAP.md)), qui remplace la
  [feuille de route d'origine](archive/ROADMAP-2026-10-05.md).

## 2026-10-07

- Filtres du lien « Voir les offres Cardmarket » (langue, `minCondition`,
  `isReverseHolo`) vérifiés sur Cardmarket.
- Banc d'essai de reconnaissance : Gemini, Tesseract, DINOv2, CLIP et des
  agents Claude mesurés sur des cartes vérifiées
  ([banc d'essai](BANC-RECONNAISSANCE.md)).

## 2026-10-06

- Copie Drive des sauvegardes par un timer du portable et rclone ; elle
  remplace une automatisation par agent (Codex), mise en pause, et ne dépend
  plus de son quota ni de son connecteur. Réception : l'archive Drive
  `daily-2026-10-06.zip` retéléchargée, son SHA-256 comparé au ZIP local et
  son contenu restauré (404 exemplaires actifs) ; niveau de contrôle
  `download-sha256-restore`. Les archives déjà sur Drive, dont les parties de
  l'instantané initial, gardent leur contrôle par métadonnées
  ([sauvegardes](DAILY-BACKUPS.md)).

## 2026-10-05

- Accès HTTPS temporaire par un tunnel Cloudflare
  ([document archivé](archive/TUNNEL-2026-10-05.md)).
- Verso et aide à l'évaluation de l'état ([aide à l'état](CONDITION-ASSESSMENT.md)).
- Améliorations pour les six classeurs suivants
  ([document archivé](archive/IMPROVEMENTS-2026-10-05.md)) : saisie en série
  avec reprise, alertes de doublon, vue par édition, préparation des photos
  par lot avec annulation, brouillon d'annonce, panneau des sauvegardes.
  Réception : tests sur bases temporaires, reprise après rafraîchissement dans
  Chrome, vue par édition avec filtre et adresse, rendu mobile à 390 × 844 sans
  débordement ; la série sur un vrai téléphone Android reste à réceptionner
  (jalon M3).
- Parcours de lot explicite (sélection gardée entre pages et recherches,
  retrait individuel, récapitulatif mobile, brouillon sans réserver), vérifié
  dans le navigateur.
- Saisie assistée par photo essayée sur une copie : une vraie lecture Gemini de
  Gourgeist retrouve `077/203`, anglais, 120 PV, et le catalogue propose
  Evolving Skies. Capture par la caméra, réglages photo et parcours verso et
  état confirmés à l'usage sur Android et avec une webcam. Le format de
  l'évaluation de l'état a été validé sur deux mires synthétiques, reconnues
  sans carte ; la fiabilité des états proposés sur de vraies cartes n'est pas
  mesurée.
- Sauvegardes quotidiennes et copie externe de l'instantané initial sur Drive.
  Les copies hors site iront dans un dossier Google Drive privé : une seule
  permission, celle du compte propriétaire, aucun partage ; ce contrôle est
  depuis appliqué à chaque copie.

## 2026-10-04

- Instantané initial de la collection : 368 fichiers, dont les 80 photos
  originales ([instantané](RECOVERY.md)).
- Trois logiciels existants évalués ; une application maison est retenue
  ([évaluation](EVALUATION.md), [fiche 0001](decisions/0001-application-maison.md)).
- Première application de gestion locale (FastAPI et SQLite) et premier import
  de trois classeurs : 401 exemplaires, puis réimport sans ajout (401 reconnus).
  Comptes par album 111 / 110 / 180, 347 éditions, 400 identités confirmées,
  22 sans prix, une non résolue ; vignettes identiques à la bibliothèque
  d'origine. La sauvegarde finale, restaurée dans une base distincte, garde les
  dix tables métier et les 401 photos identiques. Essais d'interface sur une
  copie ; premier essai concluant sur un vrai téléphone Android par le Wi-Fi.

## 2026-10-03

- Premier pipeline d'albums : découpe des pages, lecture locale par Gemma via
  Ollama, rapprochement TCGdex.
