# Roadmap MVP — pokeprice

Version du 12 octobre 2026. Remplace la roadmap du 5 octobre, conservée comme
journal dans [archive/ROADMAP-2026-10-05.md](archive/ROADMAP-2026-10-05.md)
(évaluation des logiciels existants, choix FastAPI/SQLite, étapes 0 à 6,
chantier « pilotage par agents »).

## Objectif du MVP

**Faire passer un classeur de cartes de la photo à un inventaire prêt à vendre,
sans laisser passer une carte de valeur.** Le temps du propriétaire se concentre sur les
cartes où il y a de l'argent en jeu ; le reste part en lots, valorisé sans effort.

Le MVP est atteint lorsqu'un nouveau classeur d'environ 100 cartes satisfait
**tous** les critères suivants, mesurés sur l'un des six classeurs à venir :

| # | Critère de sortie | Mesure |
|---|---|---|
| S1 | Chaque carte est identifiée ou explicitement « à vérifier » | 0 carte sans statut |
| S2 | Aucune carte de valeur ne passe en vrac | 100 % des cartes dont la *valeur en jeu* ≥ seuil sont examinées (variante, tampon, état) |
| S3 | Les cartes de valeur ont un prix sourcé | référence TCGdex datée **et** estimation de vente par état pour chacune |
| S4 | Le reste est valorisé en lots | valeur prudente du vrac calculée, lots prêts à exporter |
| S5 | Le coût humain est maîtrisé | ≤ 1 h de travail du propriétaire pour 100 cartes, hors prise de vue |
| S6 | Les données sont en sécurité | sauvegarde restaurée avec succès, code poussé hors de la machine |

La *valeur en jeu* d'une carte est le prix le plus élevé parmi ses identités
plausibles (variantes Standard/Foil, éditions candidates), en valeur prudente
(le plus bas entre tendance et moyenne 30 jours). Seuil par défaut : **10 €**,
réglable (voir décisions).

## Point de départ (12 octobre 2026)

**Collection :** 405 exemplaires dans 4 classeurs, 401 identités confirmées ;
12 cartes relevées en détail, 1 estimation de vente, 1 lot réservé. Base en
schéma 8. Tout le code est commité sur `master` (174 tests).

**Déjà livré :**

- Pipeline d'albums en ligne de commande : découpe des pages, lecture Gemini,
  rapprochement TCGdex, rapports CSV/Excel/HTML.
- Application de gestion FastAPI/SQLite : exemplaires, corrections versionnées,
  historique, corbeille, comptes et rôles, photos privées, exports, sauvegardes
  quotidiennes locales et Drive vérifiées. Voir [APP.md](APP.md).
- Saisie à l'unité et en série (recto/verso, reprise) ; capture webcam avec mire
  de cadrage, préparation des photos (recadrage, perspective, balance).
- Évaluation d'état proposée par IA et validée par l'humain.
- Prix : relevés TCGdex datés (unitaires ou en masse), alertes à partir de 2 €,
  lien Cardmarket filtré, estimation de vente depuis des offres collées.
- Variantes : Standard / Foil (« plus brillante que la version standard »), champ
  Tampon, indication TCGdex de la version standard, filtres et correction en masse.
- Lots, annonces préparées, réservations et ventes.
- [Banc d'essai de reconnaissance](../scripts/bench_recognition.py) sur 31 cartes
  vérifiées (Gemini, Tesseract, DINOv2/CLIP, agents Claude).

**Ce que le banc d'essai a établi (7 octobre) :**

| Question | Meilleure source | Résultat |
|---|---|---|
| Numéro de carte | Gemini | 25/31 (Tesseract : 4/31 sur découpes de 400 px) |
| Langue | Gemini, Tesseract | 31/31 et 28/31 |
| Édition | Gemini + catalogue, rattrapé par DINOv2 | 21/30 seul ; DINOv2 retrouve la bonne parmi les cartes de même nom dans 24/27 cas |
| Illustration holo ou mate | Gemini | 21/21 |
| Tampon | Gemini | 21/21 |
| **Reverse** | **aucune** | 0 à 1 sur 2 : angle mort de tous les modèles sur photo de classeur |
| Contrefaçon | Gemini et Sonnet ensemble | Mudbray signalée ; Sonnet sans fausse alerte |

## Écarts à combler

1. **Personne ne calcule la valeur en jeu** : les cartes de valeur se repèrent à la
   main (Pikachu 78/110 à 6 € ou 430 € selon la variante, 23 Rare Holo marquées
   Foil et sous-cotées d'environ 330 €).
2. **Les vérifications du banc ne sont pas branchées** dans l'application.
3. **La saisie des six classeurs** passe par la ligne de commande, puis un import
   par manifeste : pas de file d'examen dans l'application.
4. **Les reverses** ne sont détectables ni par les modèles ni par TCGdex
   (variantes incomplètes) : seul l'œil humain ou une double prise de vue tranche.
5. **L'estimation de vente** reste figée à l'état du moment, sans calibration par
   les ventes réelles ; le vrac n'a pas de valorisation de lot.
6. **Exploitation** : pas de dépôt distant, pas d'hébergement décidé, tunnel
   rapide instable (cinq coupures en deux heures le 6 octobre).

## Jalons

Chaque jalon est utilisable seul. Efforts en journées de travail effectif,
ordres de grandeur à réévaluer à la fin de chaque jalon.

### M0 — Données de référence fiables (½ à 1 jour)

- Relevé TCGdex en masse des 401 identités confirmées (base de la valeur en jeu).
- Fin de l'audit des variantes : 84 des 90 cartes Foil restent à vérifier à l'œil,
  dont 23 imprimées holo d'origine à repasser en Standard sauf tampon. Le filtre
  « Foil à vérifier » ne les montre qu'une fois relevées.
- Restauration du snapshot initial depuis Drive (point 0 ter de l'ancienne roadmap).
- **Code poussé sur un dépôt distant privé.**

**Terminé lorsque :** chaque carte confirmée a un relevé daté ; plus aucune carte
dans le filtre « Foil à vérifier » sans décision ; une restauration Drive a réussi ;
`master` existe hors du portable.

### M1 — Valeur en jeu et file « À examiner » (1 à 2 jours)

- Calcul côté serveur de la valeur en jeu à partir du dernier relevé : variantes,
  et autres éditions candidates quand l'identité n'est pas confirmée.
- Filtre et badge « À examiner », avec le motif : variante à forte prime, reverse
  possible, marché instable, identité incertaine, état non validé.
- Totaux de collection en trois colonnes : tendance, valeur prudente, estimation
  de vente quand elle existe. La valeur affichée ne dépend plus d'une seule
  tendance volatile.

**Terminé lorsque :** sur la collection actuelle, toutes les cartes connues de
valeur (Pikachu 78/110, Dracaufeu 4/130, Lucario LV.X, Tortank obscur…) sont dans
la file, et la file contient au plus 15 % des cartes.

**Livré le 12 octobre 2026 :** calcul local depuis les relevés conservés,
candidats séparés des références, filtre/badges/motifs, seuil dans l’URL et
trois totaux avec couverture. Audit en lecture seule : **57/405 (14,07 %)**
au seuil de 10 €, les quatre éditions attendues dans la file.
Règles et commande de réception : [VALUATION.md](VALUATION.md).

### M2 — Vérifications automatiques indépendantes (3 à 5 jours)

- Lecture Gemini enrichie : illustration holo, fond holographique, tampon (déjà
  livré), signes de contrefaçon.
- **Proposition de variante** : version standard selon TCGdex croisée avec
  l'illustration lue → Standard ou Foil proposé ; reverse possible et prime élevée
  → examen humain obligatoire.
- Langue contrôlée par Tesseract ; désaccord → « à examiner ».
- Édition contrôlée par DINOv2 parmi les cartes de même nom, en tâche locale
  (GPU) ; désaccord avec le catalogue → « à examiner ».
- Alerte de contrefaçon seulement si deux sources indépendantes concordent.
- Chaque vérification est enregistrée dans l'historique avec ses preuves ; le banc
  d'essai devient le test de non-régression (seuils minimaux par mesure).

**Terminé lorsque :** une nouvelle saisie produit automatiquement ces signaux ;
le banc rejoué sur l'application atteint au moins les scores du tableau ci-dessus ;
aucune décision de variante n'est appliquée sans validation humaine.

### M3 — Saisie à l'échelle des six classeurs (3 à 5 jours)

- **Import d'un classeur depuis l'application** : photos de pages téléversées,
  découpe par pochette, lecture et vérifications en tâche de fond, exemplaires
  créés « à vérifier » dans une file d'examen par page.
- Reprise après interruption et coût Gemini affiché par classeur.
- Réception de la saisie en série sur Android réel (en attente depuis le 5 octobre).
- Optionnel : double prise de vue (deux éclairages) pour trancher les reverses
  sur les cartes de la file « À examiner ».

**Terminé lorsque :** un classeur de 100 cartes est importé et examiné en moins
d'une heure de travail humain (critère S5), sans passer par la ligne de commande.

### M4 — Prix de vente et lots (2 à 3 jours)

- Estimation recalculée automatiquement depuis les dernières offres collées quand
  l'état change ; tableau des prix par état dans la fiche.
- Valorisation du vrac : valeur de lot à partir des prix bas, lots préparés par
  tranche de valeur.
- **Calibration** : chaque vente enregistre le rapport prix obtenu / référence par
  état ; la décote de 0,75 par cran est remplacée par la médiane observée dès
  cinq ventes dans un état, avec le nombre de ventes affiché.

**Terminé lorsque :** chaque carte de la file a une estimation par état, le vrac
d'un classeur est réparti en lots valorisés, et la calibration s'affiche dès les
premières ventes.

### M5 — Exploitation (1 à 3 jours selon l'hébergement)

- Sans budget : l'application reste sur le portable ; accès distant privé et
  gratuit par réseau maillé (Tailscale, offre personnelle) à la place du tunnel
  rapide instable, sans exposition publique ni nom de domaine. Serveur ou tunnel
  nommé avec domaine réexaminés quand un budget existe.
- Script de contrôle unique : tests Python et JavaScript, lint des fichiers modifiés.
- Tests de bout en bout (Playwright sur copie temporaire de la base) : saisie,
  relevé, estimation, série, lot.
- Exercice de restauration complet après déploiement.

**Terminé lorsque :** les critères S6 sont tenus et l'application est accessible
de façon stable là où le propriétaire l'utilise.

**Effort total du MVP : 10 à 19 jours de travail effectif.** Le critère S5 se
mesure à la fin de M3, la sortie du MVP sur le premier des six classeurs après M4.

## Décisions

| Sujet | Décision du 12 octobre 2026 | Conséquence |
|---|---|---|
| Seuil de valeur en jeu | **10 €** (≈ 10 % des cartes à examiner) | à revoir après le premier classeur |
| Saisie des classeurs | **les deux : application et ligne de commande** | M3 construit un service d'import commun (découpe, lecture, vérifications, file d'examen) ; la CLI et l'application n'en sont que deux façades, testées sur le même cœur |
| Second avis (Sonnet) | **à discuter** | options ci-dessous ; Gemini seul en attendant |
| Hébergement | **aucun budget avant le mois prochain** : faire avec l'existant | portable à la maison ; accès distant gratuit et privé à mettre en place (M5) ; serveur ou domaine réexaminés le mois prochain |
| Reverses | **éclairage adapté** : une surface foil montre une bande arc-en-ciel (photo de Drackhaus 64/132) | M3 : consigne d'éclairage rasant à la prise ; essai à deux images avec la lumière déplacée ; un comptage naïf des couleurs saturées ne suffit pas (zones de texte imprimées en couleur) |

**Second avis — options à trancher :**

- **Gemini seul** : gratuit au-delà du coût actuel ; au banc, meilleur sur le holo
  (21/21) mais 2 fausses alertes de contrefaçon sur 30.
- **Agent Sonnet sur l'abonnement Claude** : sans budget supplémentaire, lancé à la
  demande sur la file « À examiner » d'un classeur (≈ 74 000 jetons pour 31 cartes
  au banc). Au banc : aucune fausse alerte de contrefaçon, lecture comparable à
  Gemini, moins bon sur le holo (7/9).
- **Sonnet par l'API** : ≈ 0,5 à 1 centime par carte vérifiée, automatisable, mais
  compte Console et crédits à créer, donc après le mois prochain.

Dans tous les cas, le second avis passe par une interface commune de
vérification : changer de modèle relève de la configuration, pas du code.

## Risques

- **Sources externes mouvantes** : l'API Gemini change (le paramètre `temperature`
  est devenu obsolète en octobre), les variantes et prix TCGdex sont incomplets,
  l'API Cardmarket est fermée aux nouvelles inscriptions. Parade : chaque donnée
  garde sa source et sa date, le banc d'essai détecte les régressions.
- **Reverses et promos tamponnées** : non détectables automatiquement de façon
  fiable. Parade : file d'examen humain dès que la prime le justifie.
- **Machine unique** : code et données sur un seul portable. Parade : dépôt
  distant (M0) et sauvegardes Drive déjà en place pour les données.
- **Travaux concurrents** : plusieurs agents (Claude, Codex) modifient le dépôt.
  Parade : commits fréquents, contrôles avant commit, formatage limité aux fichiers
  modifiés.

## Après le MVP

- Pilotage par agents IA : identité d'agent, contrat d'API, simulations
  générales, traitements réessayables, adaptateur MCP (jalons A1 à A5 détaillés
  dans l'[archive](archive/ROADMAP-2026-10-05.md)).
- Catalogue public éventuel, intégrations autorisées aux plateformes de vente.
- Calibration de l'aide à l'évaluation de l'état sur les ventes réelles.
- PostgreSQL seulement si plusieurs serveurs ou de nombreuses écritures
  simultanées deviennent nécessaires.

## Suivi

- [ ] M0 — Relevés complets, audit des variantes clos, restauration Drive, dépôt distant
  - [x] Relevé TCGdex : 379 cartes le 12 octobre (`pokeprice-manage prices`) ; 20 sans cote TCGdex (Zarbi, Celebi NP, Nidoran ♀ Jungle, Méganium HGSS)
  - [x] Restauration du snapshot initial depuis Drive, vérifiée le 12 octobre
  - [ ] Audit des variantes Foil (27 cartes signalées par le relevé, 84 sur 90 non vérifiées)
  - [x] Dépôt distant privé : GitHub `citizenu03bb/pokeprice`, historique sans données personnelles, bugs suivis en issues
- [x] M1 — Valeur en jeu, file « À examiner », totaux prudents
- [ ] M2 — Vérifications indépendantes branchées, banc en test de non-régression
- [ ] M3 — Import de classeur dans l'application, série Android réceptionnée
- [ ] M4 — Estimation par état, lots du vrac, calibration par les ventes
- [ ] M5 — Hébergement, tests de bout en bout, restauration après déploiement
- [ ] Sortie MVP — critères S1 à S6 tenus sur un nouveau classeur
