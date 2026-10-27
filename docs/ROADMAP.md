# Feuille de route

> **Pour qui :** toute personne qui veut savoir où va le projet.
> **Vous y trouverez :** l'objectif de la première version utilisable (MVP), ses critères de sortie, l'état de chaque jalon, ce qui est prévu ensuite, ce qui est à l'étude et ce qui a été écarté.
> **Statut :** en vigueur. Ce qui a été fait, et quand, est dans le [journal](JOURNAL.md) ; les raisons des choix sont dans les [fiches de décision](decisions/README.md).

## L'objectif du MVP

**Faire passer un classeur de cartes de la photo à un inventaire prêt à vendre,
sans laisser passer une carte de valeur.** Le temps humain va aux cartes où une
erreur coûterait de l'argent ; le reste part en lots, valorisé sans effort.

Le MVP est atteint quand un nouveau classeur d'environ 100 cartes satisfait
**tous** ces critères :

| # | Critère de sortie | Mesure |
|---|---|---|
| S1 | Chaque carte est identifiée ou explicitement « à vérifier » | 0 carte sans statut |
| S2 | Aucune carte de valeur ne passe en vrac | 100 % des cartes dont la valeur en jeu atteint le seuil sont examinées (variante, tampon, état) |
| S3 | Les cartes de valeur ont un prix sourcé | relevé TCGdex daté **et** estimation de vente par état pour chacune |
| S4 | Le reste est valorisé en lots | valeur prudente du vrac calculée, lots prêts à exporter |
| S5 | Le coût humain est maîtrisé | 1 h de travail au plus pour 100 cartes, hors prise de vue |
| S6 | Les données sont en sécurité | sauvegarde restaurée avec succès, code poussé hors de la machine |

La **valeur en jeu** d'une carte est le prix le plus élevé parmi ses identités
encore plausibles (variantes Standard ou Foil, éditions candidates), en valeur
prudente : le plus bas entre la tendance et la moyenne à 30 jours. Le seuil est
de **10 €** par défaut, réglable. Voir [valeur en jeu](VALUATION.md).

## Où en est le MVP

| Jalon | État | Ce qui reste |
|---|---|---|
| M0 — Données de référence fiables | fait | — |
| M1 — Valeur en jeu et file « À examiner » | fait | — |
| M1.1 — Référentiel des impressions | socle en mode audit | les preuves par langue et de marché, limitées à 2 jours |
| M2 — Contrôles automatiques indépendants | tranches 1 à 4 faites | la double source pour la contrefaçon ; la tranche 5 (proposer l'édition par l'image) |
| M3 — Saisie à l'échelle des classeurs | à faire | tout |
| M4 — Prix de vente et lots | à faire | tout |
| M5 — Exploitation | en partie | tests de bout en bout, exercice de restauration, procédure d'import sur le serveur |

Chaque jalon est utilisable seul. Les efforts sont en journées de travail
effectif, des ordres de grandeur réévalués à la fin de chaque jalon. **Effort
total du MVP : 10 à 19 jours.** Le critère S5 se mesure à la fin de M3 ; la
sortie du MVP, sur un nouveau classeur après M4.

## Les jalons

### M0 — Données de référence fiables (½ à 1 jour) — fait

- Un relevé TCGdex pour chaque identité confirmée. Les cartes sans cote TCGdex
  (Zarbi, Celebi NP, Nidoran ♀ Jungle, Méganium HGSS) ont un prix saisi à la
  main, qui tient lieu de valeur prudente.
- Audit des variantes clos : chaque Foil de la collection a une finition
  observée et une confirmation physique datée et attribuée. Les filtres « Foil
  à vérifier (alerte du relevé) » et « Foil non vérifiées à l'œil » sont vides.
- Restauration de l'instantané initial depuis Drive, vérifiée.
- Code poussé hors du portable, sur GitHub ; bugs suivis en issues.

**Critère :** chaque carte confirmée a un relevé daté ; aucune carte dans
« Foil à vérifier » sans décision ; une restauration Drive a réussi ; `master`
existe hors du portable.

### M1 — Valeur en jeu et file « À examiner » (1 à 2 jours) — fait

- Calcul côté serveur de la valeur en jeu à partir du dernier relevé :
  variantes, et autres éditions candidates quand l'identité n'est pas confirmée.
- Filtre et badge « À examiner », avec le motif : variante à forte prime,
  reverse possible, marché instable, identité incertaine, état non validé. Le
  seuil se règle dans l'adresse de la page.
- Totaux de collection en trois colonnes, avec leur couverture : tendance,
  valeur prudente, estimation de vente quand elle existe.
- Finition observée distincte de la catégorie de prix ; confirmation physique
  datée et attribuée ; contrôles qui se clôturent sans être rouverts par un
  relevé du catalogue. Les cartes de valeur vérifiées gardent leur badge et
  quittent la file.
- Un prix saisi à la main tient lieu de prix prudent quand TCGdex n'a pas de
  cotation ; une personne peut déclarer vérifié ou incorrect le produit
  Cardmarket que TCGdex associe à une carte, et les produits partagés entre
  numéros voisins sont détectés. Ces deux mécanismes simples tiennent le rôle
  que M1.1 doit reprendre.

**Critère :** toutes les cartes connues de valeur (Pikachu 78/110, Dracaufeu
4/130, Lucario LV.X, Tortank obscur…) sont dans la file ou ont été examinées
physiquement. La borne initiale de 15 % de cartes dans la file a été
abandonnée : aucun contrôle n'est masqué pour la respecter. Règles et commande
de réception : [valeur en jeu](VALUATION.md).

### M1.1 — Référentiel des impressions — socle en mode audit

Un moteur commun et des règles d'édition sourcées, versionnées et utilisables
hors ligne, qui disent quelles impressions existent et quel produit Cardmarket
leur correspond ([fiche 0011](decisions/0011-referentiel-mode-audit.md)).

- **Fait :** observations explicites avec provenance attribuée par le serveur,
  moteur pur, identité marchande canonique, journal des cotations liées,
  restauration explicite ; le même audit dans l'interface, l'aperçu, la liste,
  les exports et la ligne de commande. Premier cas de bout en bout : le Pikachu
  78/110 français d'EX Fantômes Holon a une correspondance Cardmarket prouvée
  (produit 277048, reverse).
- **Limite :** le premier paquet embarque cinq règles physiques anglaises de
  portée partielle, sans correspondance marchande vérifiée ; il ne résout
  encore aucune carte de la collection, surtout française. Tant qu'une édition
  et une langue n'ont pas de correspondance vérifiée, le prix reste le calcul
  de M1, affiché avec sa provenance, jamais présenté comme vérifié.
- **Reste :** les preuves par langue et de marché, limitées à **2 jours
  effectifs**, réévalués après le premier nouveau classeur, en commençant par
  les éditions où une erreur coûte le plus. Une preuve coûte environ une heure.
  La procédure est dans le [guide du référentiel](PRINT_REFERENCE_GUIDE.md).
  Les mécanismes simples de M1 (prix manuel, verdict sur le produit
  Cardmarket) seront repris dans le référentiel.

**Critère :** les scénarios C01 à C20 passent, les règles réelles ont leurs
preuves d'impression et de marché sur leur périmètre, le paquet fonctionne hors
ligne et une restauration reproduit une décision historique. Une consultation
de modèles ne certifie pas les faits. Voir le [contrat](PRINT_REFERENCE_CONTRACT.md)
et l'[état de la mise en œuvre](PRINT_REFERENCE_GUIDE.md#ce-qui-est-mis-en-œuvre).

### M2 — Contrôles automatiques indépendants (3 à 5 jours)

- **Fait, tranche 1 :** lecture de la finition et du tampon, proposition
  Standard ou Foil, validation humaine, désaccords dans « À examiner ». Une
  illustration mate ne vaut jamais preuve de Standard quand une reverse possible
  vaut cher ([fiche 0008](decisions/0008-reverses-examen-physique.md)).
- **Fait, tranche 2 :** lecture automatique à la saisie ; le banc d'essai rejoué
  à travers l'application devient le test de non-régression
  ([fiche 0007](decisions/0007-seuils-confort-securite.md)).
- **Fait, tranche 3 :** contrôle de l'édition par l'image (DINOv2), désaccords
  dans la file ([fiche 0006](decisions/0006-dinov2-marge.md)).
- **Fait, tranche 4 :** langue du texte contrôlée par cohérence, Tesseract
  écarté ([fiche 0005](decisions/0005-langue-sans-tesseract.md)).
- **Reste, tranche 5 :** quand le catalogue ne trouve rien, DINOv2 propose
  l'édition parmi les impressions du nom lu, filtrées par le numéro même mal
  lu ; une personne confirme. La règle est mesurée hors ligne (48 justes,
  1 fausse, 9 sans proposition sur 58 lectures). À prévoir : la proposition à
  la saisie (avec l'option `vision`), la galerie par nom lu en partageant le
  code de `same_name_gallery`, le nombre de cartes par extension (TCGdex
  `/sets`, en cache), une mesure « édition proposée par l'image » dans le banc
  (au moins 6/6 et 7/8 justes sur les cartes sans résultat du catalogue,
  aucune fausse), et des tests : nom lu avec une autre casse ou des crochets,
  numéro partiel, impressions sans image. À corriger dans la même tranche :
  `catalogue_candidates` compare les noms en tenant compte des majuscules
  (« Fossile crâne » contre « Fossile Crâne »).
- **Reste :** une alerte de contrefaçon seulement si deux sources indépendantes
  concordent ; aujourd'hui, Gemini est le seul lecteur de texte
  ([fiche 0004](decisions/0004-gemini-seul-lecteur.md)), donc aucune alerte.

**Critère :** une nouvelle saisie produit ces signaux automatiquement ; le banc
rejoué dans l'application tient ses seuils ; aucune décision de variante n'est
appliquée sans validation humaine. Résultats : [banc d'essai](BANC-RECONNAISSANCE.md).

### M3 — Saisie à l'échelle des classeurs (3 à 5 jours)

- **Import d'un classeur depuis l'application** : photos de pages téléversées,
  découpe par pochette, lecture et contrôles en tâche de fond, exemplaires
  créés « à vérifier » dans une file d'examen par page. Un seul service
  d'import pour la ligne de commande et l'application.
- Reprise après interruption et coût Gemini affiché par classeur.
- Réception de la saisie en série sur un vrai téléphone Android.
- Extension du référentiel par impact : les éditions chères et nombreuses
  d'abord ; chaque classeur alimente la file « Référentiel à compléter ».
- Facultatif : double prise de vue (deux éclairages) pour trancher les reverses
  de la file « À examiner ».

**Critère :** un classeur de 100 cartes est importé et examiné en moins d'une
heure de travail humain (S5), sans passer par la ligne de commande.

### M4 — Prix de vente et lots (2 à 3 jours)

- Estimation recalculée depuis les dernières offres collées quand l'état
  change ; tableau des prix par état dans la fiche.
- Valorisation du vrac : valeur de lot à partir des prix bas, lots préparés par
  tranche de valeur.
- **Calibration :** chaque vente enregistre le rapport prix obtenu / référence
  par état ; la décote de 0,75 par cran d'état est remplacée par la médiane
  observée dès cinq ventes dans un état, avec le nombre de ventes affiché.

**Critère :** chaque carte de la file a une estimation par état, le vrac d'un
classeur est réparti en lots valorisés, et la calibration s'affiche dès les
premières ventes.

### M5 — Exploitation (1 à 3 jours)

- **Fait :** hébergement permanent sur Oracle Cloud, offre gratuite, avec
  Caddy et HTTPS ([fiche 0002](decisions/0002-oracle-cloud-serveur-fait-foi.md),
  [Héberger le site](DEPLOYMENT.md)) ; la base du serveur fait foi ; sauvegarde
  nocturne vérifiée et copie chiffrée sur Drive ([Sauvegardes](DAILY-BACKUPS.md)).
- **Reste :** une procédure documentée pour importer sur le serveur un classeur
  numérisé sur le portable (rapport, photos, entrée de manifeste), sans
  remplacer la base ; les corrections passent par l'API du serveur. Pas de
  synchronisation entre les deux bases
  ([fiche 0013](decisions/0013-pas-de-synchronisation.md)).
- **Reste :** faire remonter l'état de la copie Drive, suivie sur le
  portable, dans la gestion du serveur ; une notification en cas d'échec de
  sauvegarde ou de copie.
- **Reste :** un script de contrôle unique (tests Python et JavaScript, lint
  des fichiers modifiés) ; des tests de bout en bout (Playwright sur une copie
  temporaire de la base) : saisie, relevé, estimation, série, lot ; un exercice
  de restauration complet sur le serveur.

**Critère :** les critères S6 sont tenus et l'application est accessible de
façon stable.

## Après le MVP

### Prévu

- **Internationalisation de l'interface**, au moins en anglais : la collection
  est multilingue et le site vise un public international. Les textes de la
  vitrine sont dans des dictionnaires ([fiche 0020](decisions/0020-textes-dans-des-dictionnaires.md))
  et la vitrine existe en anglais sous `/en/`. Restent les messages d'erreur du
  serveur, à passer par un code stable, puis d'autres langues.
- **Application installable (PWA)** : manifeste, installation sur le téléphone,
  fonctionnement hors connexion pour la consultation.
- **Refonte de l'interface de gestion**, formulaires en priorité.
- **Déploiement sur d'autres distributions Linux.** Oracle Linux 8 et 9 et
  Ubuntu 22.04 et 24.04 sont déjà gérés par les scripts. À faire : couvrir et
  tester d'autres familles (Debian, Rocky ou Alma, Fedora…) et publier une
  matrice de compatibilité.
- **Vitrine :** un service d'envoi d'e-mails (Brevo ou Mailjet, domaine deSEC
  pour SPF et DKIM) quand le volume ou les mots de passe oubliés le
  justifient ; puis des intégrations autorisées aux plateformes de vente.
  Règles actuelles : [vitrine](VITRINE.md).
- **Pilote agent :** extensions selon le besoin, après une mesure du temps
  humain gagné ([plan](AGENT_CONTROL_PLAN.md)).
- **Aide à l'état** calibrée sur les ventes réelles.

### À l'étude

- **Plusieurs collections sur un même hébergement.** L'application gère aujourd'hui
  une collection, avec plusieurs utilisateurs. Deux voies :
  1. une instance par collection (une base, un dossier de données, un service) :
     presque rien à changer dans le code, il suffit d'outiller le déploiement ;
  2. un vrai multi-locataire (identifiant de collection dans chaque table,
     cloisonnement des requêtes, des photos et des sauvegardes) : une refonte du
     modèle de données, à ne lancer que pour un besoin réel.
- **Un second avis** sur holo ou mate et le tampon : un modèle local de
  décision à réponses fermées (par exemple Liquid AI d1-3B) ou un agent Sonnet
  sur la file d'un classeur, à mesurer sur le banc. Sans effet attendu sur les
  reverses, limitées par la prise de vue.
- **PostgreSQL**, seulement si plusieurs serveurs ou de nombreuses écritures
  simultanées deviennent nécessaires.

### Exploré, non retenu

- **Synchronisation portable ↔ serveur** : le serveur fait foi, le portable
  rapatrie les sauvegardes ([fiche 0013](decisions/0013-pas-de-synchronisation.md),
  [proposition archivée](archive/SYNC_PROPOSAL-2026-10-19.md)).
- **Tesseract** pour contrôler la langue ([fiche 0005](decisions/0005-langue-sans-tesseract.md)).
- **L'agent Antigravity** comme lecteur carte par carte : trop lent, trop coûteux
  en jetons ([fiche 0004](decisions/0004-gemini-seul-lecteur.md)).

## Les décisions en vigueur

Les choix d'architecture et de méthode ont chacun leur
[fiche](decisions/README.md). Deux règles de gestion vivent dans leur page :

- **Seuil de valeur en jeu :** 10 €, à revoir après le premier nouveau
  classeur ([valeur en jeu](VALUATION.md)).
- **Prix affiché en vitrine :** la tendance Cardmarket, avec un plancher de
  0,50 €, seulement pour les cartes NM ou EX dont l'état et la variante sont
  confirmés ; sinon un prix fixé à la main ou tiré des offres au même état
  ([vitrine](VITRINE.md)).

## Les risques

- **Sources externes mouvantes** : l'API Gemini change (le paramètre
  `temperature` est devenu obsolète), les variantes et prix TCGdex sont
  incomplets, l'API Cardmarket est fermée aux nouvelles inscriptions. Parade :
  chaque donnée garde sa source et sa date, le banc d'essai détecte les
  régressions.
- **Reverses et promos tamponnées** : non détectables automatiquement de façon
  fiable. Parade : examen humain dès que la prime le justifie.
- **Deux bases** : le portable garde une copie qui pourrait recevoir des
  écritures par erreur. Parade : le serveur fait foi, les consignes
  d'exploitation et des agents l'imposent, et toute écriture se fait sur le
  serveur.
- **Travaux concurrents** : plusieurs agents de code modifient le dépôt.
  Parade : commits fréquents, tests et contrôle de la documentation avant
  chaque commit.
