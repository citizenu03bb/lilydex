# Journal

> **Pour qui :** toute personne qui veut savoir ce qui a changé, et quand.
> **Vous y trouverez :** les changements notables, du plus récent au plus ancien, une à quatre lignes chacun, avec leur preuve.
> **Statut :** tenu à jour. Le détail complet est dans `git log` ; les raisons des choix sont dans les [fiches de décision](decisions/README.md).

Une page qui décrit le fonctionnement ne porte pas de date : quand un passage
daté la quitte, il est versé ici dans le même commit.

## 2026-10-23

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
