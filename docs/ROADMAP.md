# Roadmap MVP — pokeprice

Version du 12 octobre 2026, mise à jour le 13 octobre après la revue de M1.1
(prochaines étapes ci-dessous). Remplace la roadmap du 5 octobre, conservée comme
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
| Langue | Gemini | 31/31 (Tesseract : 28/31, écarté le 14 octobre) |
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

## Prochaines étapes — ordre proposé le 13 octobre, à valider

| # | Étape | Pourquoi maintenant | Effort |
|---|---|---|---|
| 1 | ~~**Clore M0 : audit des variantes Foil** par observation de la finition et du tampon, en commençant par les 27 cartes signalées~~ **Fait le 13 octobre** | Peu coûteux ; M2 et le référentiel comparent leurs propositions à ces observations, elles doivent être justes | ½ jour |
| 2 | ~~**M1.1 : premier cas de bout en bout**, EX Fantômes Holon en français : règle FR avec tampon, preuve FR, capture Cardmarket, saisie d’un relevé lié à la correspondance~~ **Fait le 13 octobre** | Valide le système de preuve sur le problème qui l’a motivé et mesure le coût réel d’une preuve | dans les 2 jours de M1.1 |
| 3 | **M2 : vérifications indépendantes** — tranches 1 à 4 livrées les 13 et 14 octobre ; restent la double source pour la contrefaçon et la tranche 5 (DINOv2 à la saisie) | Ne dépend plus de M1.1 ; nécessaire avant de saisir les six classeurs | 3 à 5 jours |
| 4 | **M3 : saisie des six classeurs**, avec extension du référentiel par impact (éditions chères et nombreuses d’abord) | Les observations sont prêtes ; chaque classeur alimente la file « Référentiel à compléter » | 3 à 5 jours |
| 5 | **M4 puis M5** | Inchangés | 3 à 6 jours |

**Étape 2, 13 octobre (soir) : règle, preuves et saisie livrées.** Le
Pikachu 78/110 FR est la première carte à correspondance Cardmarket prouvée
(produit 277048, Reverse). La fiche saisit tendance et moyenne à 30 jours
ensemble, liées à cette correspondance. Constats : l’encyclopédie officielle
française n’a aucune carte d’EX Fantômes Holon, et Cardmarket refuse la
capture automatisée ; une preuve a coûté environ une heure, plus deux minutes
d’enregistrement de page par le propriétaire. Détails et limite du moteur :
[PRINT_REFERENCE_IMPLEMENTATION.md](PRINT_REFERENCE_IMPLEMENTATION.md#premier-cas-de-bout-en-bout--ex-fantômes-holon-78-en-français-13-octobre-2026).

**Étape 1 close le 13 octobre (soir).** Les 8 Foil signalées par une alerte du
relevé ont été confirmées une à une ; 14 autres Foil l’ont été dans la journée ;
les 35 dernières, toutes dans l’album Platinium, ont été confirmées en groupe
sur observation du propriétaire (reverse, absence de tampon constatée). Les
filtres « Foil à vérifier (alerte du relevé) » et « Foil non vérifiées à l’œil »
sont vides : chaque Foil de la collection a une finition observée et une
confirmation datée et attribuée. Dix d’entre elles (extensions Noir & Blanc)
sont des reverses que TCGdex ne répertorie pas : la confirmation physique prime.

**Décision sur la borne de 15 % : plus d’actualité.** Le 13 octobre au soir, la
file contient **31 cartes sur 403 (7,7 %)** au seuil de 10 € (même nombre à
5 €). Toutes attendent un prix : relevé à refaire après un changement de
catégorie, saisie manuelle faute de cotation TCGdex, ou version holo spéciale à
préciser (Lougaroc sm3-76, Steelix hgss2-24). Aucun examen physique n’y reste.
Avant le nettoyage du jour, elle en comptait 34 à 10 € et 57 à 5 €.

**Recoupement avec M1.1.** Le 13 octobre, deux mécanismes simples ont été
ajoutés hors du référentiel (commit `f5580be`, règles dans
[VALUATION.md](VALUATION.md)) :
- un prix saisi à la main tient lieu de prix prudent quand TCGdex n’a pas de
  cotation Cardmarket (Celebi NP, Zarbi, Méganium HGSS, Nidoran ♀ Jungle) ;
- un verdict humain (vérifié, incorrect) sur le produit Cardmarket que TCGdex
  associe à une carte, avec détection des produits partagés entre numéros
  voisins (Darkrai GE 3/4, Airmure BCR 95/96, Solochi DRX 93/94).

Ces deux mécanismes jouent en version simple le rôle de la correspondance
marchande et des relevés manuels liés de M1.1 : il faudra les reprendre dans le
référentiel le moment venu.

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

**Complément du 12 octobre :** finition observée distincte de la catégorie de
prix ; confirmation physique datée et attribuée ; contrôles qui se clôturent
sans être rouverts par un relevé catalogue. Les cartes de valeur vérifiées
gardent leur badge et quittent la file. Une divergence catalogue reste une tâche
même sous le seuil tant que la variante n’est pas confirmée. Sur la sauvegarde
de contrôle avant migration : **73/405 (18,02 %)** dans la file ; la borne de
15 % de la réception initiale n’est donc plus satisfaite sur cet état. Aucun
contrôle n’est masqué pour respecter artificiellement cette borne. L’audit des
éditions connues accepte désormais « dans la file ou examen physique terminé ».

Le contrôle de cohérence couvre aussi les parallèles EX Fantômes Holon :
« illustration holo + tampon » n°18–98 ne peut pas être confirmée en Standard.
Une ancienne combinaison incohérente revient dans la file, et son prix est
exclu des totaux, sans modifier les observations physiques enregistrées.

### M1.1 — Socle implémenté, audit actif, preuves marchandes à compléter

Contrat v1 du 13 octobre 2026 : livrer un moteur commun et des règles
d’édition sourcées, versionnées et utilisables hors ligne. Depuis la revue
du 13 octobre, M2 n’attend plus sa clôture (décision ci-dessous).
La couverture doit accompagner les **six albums restant à scanner** ; la
collection actuelle fournit le premier banc de régression. Une édition nouvelle
doit pouvoir être ajoutée par des données, sans correctif du moteur, et son
absence du référentiel ne doit pas bloquer la saisie physique.

Après consultation indépendante (Claude Opus, Gemini, DeepSeek, Mistral),
le contrat retient un ensemble d’impressions candidates et une correspondance
marchande explicite. Standard/Foil reste une projection ; la conservation du
prix dépend du produit, des filtres, des métriques et de la population cotée.
La résolution d’impression et la résolution de marché ont des états distincts.

**Avancement du 13 octobre :** observations explicites et provenance serveur,
moteur pur, identité marchande canonique, journal de cotations liées et
restauration explicite implémentés. L’interface, l’aperçu, la liste, les exports
et le CLI exposent le même audit. Schéma 12 testé sur restauration temporaire ;
les valeurs et attestations héritées sont conservées. Les tests synthétiques
couvrent les invariants du contrat, avec installation hors checkout sans réseau
et reproduction de décisions après sauvegarde/restauration.

Le premier paquet embarque cinq règles physiques anglaises de portée partielle,
avec faits extraits et empreintes des listes officielles. Il suit les huit
familles mais ne contient **aucune correspondance marchande vérifiée**. Il ne
remplace donc pas encore le calcul de prix hérité. Il reste à documenter les
impressions dans les langues de la collection, les distributions particulières,
les produits et métriques Cardmarket, puis à raccorder leur acquisition et
activer la sélection vérifiée après audit. M1.1 reste ouvert.

**Décision du 13 octobre, après revue : M1.1 ne bloque plus M2.** Sur la
collection actuelle, le paquet ne résout encore aucune carte (404/404 hors
périmètre à l’audit). La collection est multilingue (395 FR, 6 EN, 2 JA, 1 IT)
et l’application vise un public international ; or les règles ne couvrent que
l’anglais, et les 27 cartes des familles de régression sont françaises (26) ou
italienne (1). Chaque langue demande donc ses propres preuves.
M2 compare donc ses propositions à la catégorie de prix actuelle, puis aux
candidats du référentiel là où une règle couvre la carte. Tant qu’une édition
et une langue n’ont pas de correspondance vérifiée, **la tarification provisoire
reste le calcul de M1** : références héritées datées, affichées avec leur
provenance, jamais présentées comme vérifiées.

Le travail de preuves restant est **limité à 2 jours effectifs**, réévalués
après le premier des six classeurs, en commençant par les éditions où une
erreur coûte le plus. Procédure pour chaque pièce :

1. Enregistrer la source (liste officielle, page produit Cardmarket sauvegardée
   en HTML ou PDF, base d’impressions) puis l’archiver :
   `pokeprice-manage reference-archive capture.html` donne son SHA-256.
2. Écrire le fait extrait dans `prints-v1.json` avec cette empreinte, le
   localisateur, la date et le périmètre exact : édition, numéros et **langue**.
   - Preuve de marché : identifiant produit Cardmarket, filtres affichés
     (langue, reverse…), champs de prix relevés et devise.
   - Preuve de langue : une pièce qui montre les impressions **dans cette
     langue**. Une liste anglaise ne couvre jamais le français ; le validateur
     refuse une règle FR appuyée sur une preuve limitée à l’anglais.
     Sources officielles connues : l’encyclopédie des cartes de pokemon.com
     par langue (FR, IT, EN…, depuis la série EX) et la recherche officielle
     japonaise de pokemon-card.com (depuis l’ère XY seulement). Aucune ne
     liste les reverses : la preuve de marché reste distincte.
3. Après la mise à jour des règles : `pokeprice-manage reference-recheck`
   liste les cotations liées devenues incompatibles ; `--apply` inscrit leur
   suspension au journal.

**Ordre initial** (remplacé par les [prochaines étapes](#prochaines-étapes--ordre-proposé-le-13-octobre-à-valider)) : vocabulaire d’observation avant les scans (dont tampon non examiné /
absence constatée / présence constatée), moteur pur, règles sourcées sur les
huit familles, puis audit et activation après sauvegarde/restauration. Les
anciennes cotations restent visibles avec leur provenance ; une incompatibilité
les suspend sans effacer les attestations physiques.

**Terminé lorsque :** les scénarios C01–C20 passent, les règles réelles ont
leurs preuves d’impression et de marché sur leur périmètre, le paquet fonctionne
hors ligne et une restauration reproduit une décision historique. La consultation
ne certifie pas les faits métier et ne constitue pas une livraison de M1.1.

Explication fonctionnelle : [PRINT_REFERENCE_GUIDE.md](PRINT_REFERENCE_GUIDE.md).
Comportement, migration et réception :
[PRINT_REFERENCE_CONTRACT.md](PRINT_REFERENCE_CONTRACT.md).
Contexte et enrichissement : [PRINT_REFERENCE_PROPOSAL.md](archive/PRINT_REFERENCE_PROPOSAL-2026-10-13.md).
Livraison et limites : [PRINT_REFERENCE_IMPLEMENTATION.md](PRINT_REFERENCE_IMPLEMENTATION.md).

### M2 — Vérifications automatiques indépendantes (3 à 5 jours)

- Lecture Gemini enrichie : illustration holo, fond holographique, tampon (déjà
  livré), signes de contrefaçon.
- **Proposition de variante** : version standard selon TCGdex croisée avec
  l'illustration lue → Standard ou Foil proposé ; reverse possible et prime élevée
  → examen humain obligatoire.
- ~~Langue contrôlée par Tesseract~~ remplacé le 14 octobre par un contrôle de
  cohérence : langue du texte imprimé lue avec la finition, comparée à la
  fiche ; désaccord → « à examiner ».
- Édition contrôlée par DINOv2 parmi les cartes de même nom, en tâche locale
  (GPU) ; désaccord avec le catalogue → « à examiner ».
- Alerte de contrefaçon seulement si deux sources indépendantes concordent.
- Chaque vérification est enregistrée dans l'historique avec ses preuves ; le banc
  d'essai devient le test de non-régression (seuils minimaux par mesure).

**Terminé lorsque :** une nouvelle saisie produit automatiquement ces signaux ;
le banc rejoué sur l'application atteint au moins les scores du tableau ci-dessus ;
aucune décision de variante n'est appliquée sans validation humaine.

**Tranche 1, 13 octobre : proposition de variante.** Table commune
`verifications` (schéma 14) : chaque lecture garde sa source, son modèle, son
protocole, la photo lue, la réponse brute et les jetons consommés. Un lecteur
est un simple appelable ; Gemini est le premier, un autre modèle s’y branche
sans changer le service. La fiche propose Standard ou Foil à partir de la
lecture et de la règle de catégorie existante ; une illustration mate ne vaut
jamais preuve de Standard quand une reverse possible a une prime au-dessus du
seuil. Le choix humain s’applique avec la lecture en preuve ; un désaccord avec
la fiche entre dans « À examiner ». Détails : [APP.md](APP.md#lire-la-finition-sur-la-photo-m2).
Essai réel sur trois cartes confirmées à l’œil (holo tamponnée EX Deoxys, mate,
reverse Noir & Blanc) : 3/3, tampon compris, pour environ 1 350 jetons
d’entrée et 450 de sortie (raisonnement compris) par carte.
Reste pour M2 : lecture automatique à la saisie, Tesseract (langue), DINOv2
(édition), double source pour la contrefaçon, banc en test de non-régression.

**Tranche 2, 13 octobre : lecture à la saisie, banc en non-régression.**
Avec `pokeprice-manage serve`, tout nouvel exemplaire photographié (à l’unité
ou en série) est lu une fois juste après l’enregistrement ; un échec est noté
dans l’historique, la saisie n’attend pas. `bench_recognition.py app` rejoue le
banc à travers l’application, sur une copie de la base remise à l’état de
saisie : deux passages réels, chaque mesure jugée sur le pire des deux
(décision du 13 octobre), échec sous le seuil.

| Mesure | Seuil (7 oct.) | 1er passage | 2e passage |
|---|---|---|---|
| Numéro | 24/30 | 24/30 | 24/30 |
| Langue | 30/30 | 30/30 | 30/30 |
| Édition en 1er | 20/29 (13 oct.) | 20/29 | 21/29 |
| Photo inexploitable refusée | 1/1 | 1/1 | 1/1 |
| Holo ou mate, quand la lecture tranche | 21/21 | 18/18 | 21/21 |
| Lecture tranchée (sinon examen) | 18/21 | 18/21 | 21/21 |
| Tampon | 21/21 | 21/21 | 21/21 |
| Proposition fausse, Foil au seuil ou sans prix | 0 | 0 | 0 |

Gliscor 62/111 a le haut coupé : son nom n’est pas sur la photo. La lecture de
saisie le refuse et demande une reprise, ce qui est le bon résultat ; le
7 octobre, l’ancien protocole l’avait lu en devinant le nom. Le banc attend
désormais ce refus, et les seuils de numéro, langue et édition sont ceux du
7 octobre sans cette carte. Les autres écarts changent d’un passage à
l’autre. Au pire des deux, l’édition donnait 20/29 pour 21/29 au 7 octobre : Celebi
29/40 est lu « Celebi ☆ » une fois sur deux (l’étoile noire des promos, près
du numéro, rattachée au nom ; aucune étoile n’est imprimée), et la recherche
catalogue ne trouve alors rien ; Clic et PokéNav perdent leur numéro un
passage sur deux. Le banc a
aussi trouvé un trou de règle, corrigé : TCGdex ne répertorie pas certaines
reverses (Clic 75/114), son « pas de reverse » ne vaut donc plus preuve quand
la photo laisse le fond indéterminé. Une reverse sous le seuil proposée
Standard reste tolérée (Clic à 0,77 €), comme le prévoit la règle.
**Décision du 13 octobre : seuils de confort au niveau actuel, seuils de
sécurité intouchables.** Une édition manquée renvoie la carte en « à vérifier » :
elle coûte du temps, pas d’argent. Le seuil d’édition devient donc 20/29, le
pire des deux passages de l’application ; le banc protège désormais contre un
recul à partir de ce niveau. Les seuils qui empêchent une carte de valeur de
passer en vrac (proposition fausse, holo ou mate tranché, tampon) ne baissent
pas. Amélioration possible hors seuil : garder ☆, δ et les lettres de Zarbi dans
le nom, et lire l’étoile noire des promos comme symbole d’extension (Celebi
☆ ex14-100 est une autre carte que la promo np-29).

**Tranche 3, 13 octobre : édition contrôlée par l’image.** DINOv2 (option
`vision`, GPU ou processeur, environ une seconde par carte une fois les
images en cache) classe la photo parmi toutes les impressions TCGdex de même
nom ; un écart d’au moins 0,05 en faveur d’une autre impression envoie la
carte dans « À examiner », jusqu’à ce qu’une personne garde ou corrige
l’édition. Lancé automatiquement à la saisie d’une édition confirmée.

| Mesure (banc rejoué sur l’application) | Résultat |
|---|---|
| Vraie édition confirmée par l’image | 22/27 |
| Vraie édition sans fausse alerte | 26/27 (Solochi) |
| Impression voisine la plus ressemblante signalée | 14/26 |

Le 7 octobre donnait 24/27 sur une galerie sans les réimpressions à
l’illustration identique (Recherche d’énergie, PokéNav) : l’image seule ne
les départage pas, le contrôle reste alors indécis. Marge 0,05 choisie le
13 octobre (0,02 : 3 fausses alertes, 17 voisines ; 0,08 : aucune, 11).
Quatre passages Gemini ont montré un bruit plus large que prévu (numéro 23
à 25/30, édition 18 à 22/29) : les seuils de numéro et d’édition Gemini sont
au plus bas observé, les seuils de sécurité restent ceux du 7 octobre.
Piste : DINOv2 retrouve presque toutes les éditions que Gemini manque faute
d’avoir lu le numéro (Fossile Crâne, Zarbi K, Octillery…) ; il pourrait
proposer l’édition à la saisie quand le catalogue ne trouve rien.
Reste pour M2 : Tesseract (langue), double source pour la contrefaçon.

**Tranche 4, 14 octobre : Tesseract écarté, langue contrôlée par cohérence.**
Une contre-expertise ne vaut que par les erreurs qu’elle rattrape. Gemini n’a
manqué aucune langue au banc (31/31, puis 30/30 à chaque passage dans
l’application) ; Tesseract (28/31) n’aurait rien rattrapé et aurait envoyé
3 cartes françaises sur 31 dans « À examiner » sans raison (Clic, Octillery,
Transfert, lues italien, anglais ou rien), souvent gagnant d’une seule voix
quand il avait raison, sans japonais, et au prix d’une dépendance système.
La recherche catalogue, stricte sur la langue, arrête déjà la plupart des
erreurs : un nom français ne se trouve pas dans le catalogue anglais. Reste
le cas des noms identiques d’une langue à l’autre. La lecture de finition
(protocole `card-finish-v2`, déjà faite à chaque saisie) lit donc aussi la
langue du texte imprimé hors nom ; un désaccord avec la fiche entre dans
« À examiner » jusqu’à correction ou décision de garder la langue. Ce n’est
pas une source indépendante (même modèle, autre appel, autre question), mais
le contrôle ne coûte qu’environ 100 jetons de plus par carte (1 930 contre
1 820 à 1 860). Détails : [APP.md](APP.md#lire-la-finition-sur-la-photo-m2).

| Mesure (banc rejoué sur l’application, 14 oct.) | 1er passage | 2e passage |
|---|---|---|
| Langue du texte lue juste | 31/31 | 31/31 |
| Langue de la fiche sans fausse alerte | 31/31 | 31/31 |

Seuils fixés à ce niveau. Les autres mesures restent au-dessus de leurs
seuils. Un premier essai le même jour avait perdu 3 à 7 contrôles d’édition
sur des appels TCGdex échoués : l’image n’est pas en cause (DINOv2 rejoué
seul : 22/27, 26/27, 14/26, comme le 13 octobre), mais ces échecs réseau
font tomber les mesures sous leur seuil.
Reste pour M2 : double source pour la contrefaçon, puis la tranche 5.

**Tranche 5, à faire : DINOv2 propose l’édition à la saisie quand le
catalogue ne trouve rien.** Aujourd’hui, faute de numéro lu (ou mal lu), la
recherche catalogue rend une liste vide et la saisie passe à la main. À la
place :

1. galerie : toutes les impressions TCGdex qui portent le nom lu, dans la
   langue lue et en anglais, noms comparés sans accents, casse, crochets ni
   ponctuation ;
2. filtre par le numéro, même mal lu : on garde les impressions dont le
   numéro ou le nombre de cartes de l’extension correspond (« 68/97 » garde
   l’extension à 97 cartes) ; sans numéro lu, pas de filtre ;
3. DINOv2 classe la photo dans ce qui reste ; l’impression en tête est
   proposée si son écart avec la deuxième atteint 0,05 (ou si elle reste
   seule). Pas de proposition si le filtre a écarté des impressions sans
   image : la vraie peut être parmi elles ;
4. une personne confirme, avec la photo à côté de l’image TCGdex proposée.
   Le contrôle d’édition de la tranche 3, sur la galerie complète, joue
   ensuite le rôle de second avis ; l’historique doit dire qu’il ne s’agit
   pas d’un avis indépendant.

**Évaluation du 14 octobre**, sur les lectures enregistrées des deux passages
du banc (DINOv2 rejoué hors ligne, sans nouvel appel Gemini). Sur les seules
cartes sans résultat catalogue, l’échantillon est trop petit pour conclure ;
on a donc aussi simulé la règle sur toutes les cartes (29 par passage).

| Règle | Cartes sans résultat catalogue (6 puis 8) | Toutes les cartes (58 lectures) |
|---|---|---|
| Nom seul, écart ≥ 0,05 | 6/6 puis 6/8 justes, aucune fausse | 30 justes, **4 fausses**, 24 sans proposition |
| Nom puis filtre par numéro, écart ≥ 0,05 | 6/6 puis **7/8** justes, aucune fausse | **48 justes**, 1 fausse, 9 sans proposition |

Sans filtre, deux erreurs reviennent aux deux passages. Solochi : confusion
avec une impression récente, écart 0,075. Baggiguane 10/12 : la vraie
impression n’a pas d’image, DINOv2 en choisit forcément une autre. Monter la
marge ne les sépare pas des bonnes propositions, qui ont aussi des écarts de
0,061 et 0,075. Le numéro, même partiel, les règle. Il départage aussi Clic
(« 89/114 ») et Chamallot (écart de 0,075 à 0,241), et récupère Zarbi K
(« 58/105 »), Fossile Crâne et Méthode d’entraînement du Prof. Orme. La seule
erreur restante est PokéNav lu « 88/109 », numéro d’une autre impression
existante (ex1-88) : le catalogue faisait déjà la même erreur, et son
illustration est identique à la vraie, donc l’image ne peut pas trancher.
Risque restant : sans aucun numéro lu, une vraie impression sans image
(promos, comme Baggiguane) laisse passer une mauvaise proposition. La
proposition doit alors signaler les impressions de ce nom qui n’ont pas
d’image.

Côté catalogue, même cause : `catalogue_candidates` compare les noms en
distinguant les majuscules (« Fossile crâne » contre « Fossile Crâne »), à
corriger dans la même tranche.

À prévoir : la proposition à la saisie (avec l’option `vision`, sinon
inchangé), la galerie par nom lu en partageant le code de `same_name_gallery`,
le nombre de cartes par extension (TCGdex `/sets`, en cache), une mesure
« édition proposée par l’image » dans `bench_recognition.py app` (justes au
moins 6/6 et 7/8 sur les cartes sans résultat catalogue, aucune fausse), et
des tests : nom lu avec une autre casse ou des crochets, numéro partiel,
impressions sans image.

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

- Hébergement : en ligne depuis le 16 octobre sur Oracle Cloud Always Free
  (0 €), <https://lilydex.duckdns.org>, Caddy et Let's Encrypt
  ([DEPLOYMENT.md](DEPLOYMENT.md)). Le serveur fait foi depuis le 16 octobre
  à 21 h 11, après le remplacement de sa base par celle du portable. Ce n'était
  possible sans perte que parce que 22 tables sur 24 étaient identiques à la
  sauvegarde d'origine ; seuls les comptes et les sessions avaient changé, et ils
  ont été conservés.
- Synchronisation portable ↔ lilydex : aujourd'hui, deux bases peuvent diverger
  sans que rien ne le signale, et il n'existe aucune fusion. À construire :
  - **Une seule base fait foi**, celle du serveur. Le portable reste le poste de
    numérisation (photos, OCR, scan) et rapatrie les sauvegardes du serveur
    (`deploy/oci-pull-backup.sh`).
  - **Envoi du travail du portable sans remplacer la base** : un nouvel album
    (rapport, photos, entrée de manifeste) est transféré puis importé *sur le
    serveur* (`pokeprice-manage import`, sans doublon ni écrasement des
    corrections). Les corrections passent par l'API du serveur, avec version
    attendue, auteur et motif.
  - **Copie locale en lecture seule** : une base restaurée depuis le serveur
    refuse les écritures et affiche la date de sa sauvegarde, pour qu'aucune
    correction ne s'y perde.
  - **Contrôle de divergence** (`sync-check`) : comptes par table, dernier
    événement et comptes utilisateurs des deux côtés, avant toute bascule ou
    tout import.
  - **Bascule exceptionnelle documentée** : remplacer une base uniquement si la
    cible n'a aucun événement depuis la sauvegarde dont elle provient. Conserver
    les comptes et les sessions de la cible, et garder l'ancienne base de côté.

  **Terminé lorsque :** un classeur numérisé sur le portable arrive sur lilydex
  sans remplacer la base, et une écriture dans une copie locale est refusée.
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
| Second avis (Sonnet) | **Gemini seul pour M2** (13 octobre), derrière l’interface commune de vérification | un second lecteur se branche plus tard par configuration ; sans seconde source, pas d’alerte de contrefaçon, seulement un motif « à examiner » |
| Hébergement | **aucun budget avant le mois prochain** : faire avec l'existant | 16 octobre : Oracle Cloud Always Free (0 €), <https://lilydex.duckdns.org> ; le serveur fait foi, synchronisation avec le portable en M5 |
| Prix de vente affiché | **tendance Cardmarket, plancher 0,50 €** (16 octobre) | seulement pour les cartes NM/EX dont l'état et la variante sont confirmés, arrondi, affiché avec sa date, modifiable à la main ; sous le plancher, les cartes partent en cadeaux ou en lots ; les cartes abîmées et celles à 10 € ou plus reçoivent un prix fixé à la main ou tiré des offres au même état (pas de décote automatique) |
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

Écartés ou à évaluer (13 octobre) :

- **CLI Antigravity (`agy`) sur l’abonnement Google** : écarté pour la lecture
  carte par carte. Essai sur une photo : 69 à 117 s, plus de 50 000 jetons
  d’entrée et aucune réponse sans autoriser l’agent à exécuter des commandes.
  Il propose aussi Claude Sonnet : piste possible pour un second avis groupé
  sur la file d’un classeur, à mesurer.
- **Modèles de décision locaux** (par exemple Liquid AI d1-3B, poids ouverts
  publiés en octobre 2026) : réponses fermées avec probabilité, exécutables sur
  le GPU local. Candidat de second avis sur holo/mate et tampon, à mesurer sur
  le banc ; sans effet attendu sur les reverses, limitées par la prise de vue.

## Risques

- **Sources externes mouvantes** : l'API Gemini change (le paramètre `temperature`
  est devenu obsolète en octobre), les variantes et prix TCGdex sont incomplets,
  l'API Cardmarket est fermée aux nouvelles inscriptions. Parade : chaque donnée
  garde sa source et sa date, le banc d'essai détecte les régressions.
- **Reverses et promos tamponnées** : non détectables automatiquement de façon
  fiable. Parade : file d'examen humain dès que la prime le justifie.
- **Machine unique** : code et données sur un seul portable. Parade : dépôt
  distant (M0) et sauvegardes Drive déjà en place pour les données.
- **Deux bases qui divergent** : le portable et lilydex ont chacun leur base.
  Le 16 octobre, une journée de travail (import de 65 cartes, 51 identifications,
  832 relevés, 680 photos) n'existait que sur le portable. Parade : le serveur
  fait foi, et la synchronisation est prévue en M5.
- **Travaux concurrents** : plusieurs agents (Claude, Codex) modifient le dépôt.
  Parade : commits fréquents, contrôles avant commit, formatage limité aux fichiers
  modifiés.

## Après le MVP

- Pilotage par agents IA : [plan revu les 19–20 octobre](AGENT_CONTROL_PLAN.md).
  Les jalons A1 à A5
  de l'[archive](archive/ROADMAP-2026-10-05.md) restent des extensions selon
  le besoin. Le pilote peut soutenir
  M4 sans attendre tout le MVP. **Pilote technique livré le 19 octobre** :
  [lecture HTTP/CLI, préparation de lots et brouillons dans Ventes](AGENT_CONTROL.md),
  avec contrôles de portée, prix inconnu explicite, idempotence et restauration.
  [Première évaluation conversationnelle synthétique](AGENT_EVALUATION_RESULTS.md) :
  quatre essais réussis avec/sans skill, en lecture seule et avec brouillons.
  Aucun gain propre au skill démontré. Le parcours suivant est la préparation
  de cinq contrôles, les observations manquantes rendant le lot peu adapté à
  cette collection. [Réception du 20 octobre](AGENT_REVIEW_RESULTS.md) : un vrai
  client isolé a parcouru un album réel figé et préparé cinq questions à partir
  de ses photos, en lecture seule. Les contrôles techniques et la revue des
  images passent ; le gain humain reste à mesurer devant le classeur.
- Catalogue public ([plan](CATALOGUE.md)) : vitrine ouverte, visible sans compte (décision du 16 octobre) ; elle montre une sélection explicite de cartes et de champs. Un client s'inscrit pour demander une réservation ; l'administrateur l'accepte, ce qui crée un lot réservé. Le client ne voit ni notes, ni provenance, ni historique, ni acheteurs. Prix affiché selon la décision du 16 octobre. Décidé le 16 octobre : pas de service d'e-mail au départ ; un compte client reste en attente jusqu'à sa validation par un administrateur ; une demande ne bloque les cartes qu'à son acceptation ; le contact (paiement, envoi) se fait depuis la boîte du vendeur. Service d'envoi (Brevo ou Mailjet, domaine deSEC pour SPF/DKIM) quand le volume ou les mots de passe oubliés le justifient. Intégrations autorisées aux plateformes de vente ensuite.
- Calibration de l'aide à l'évaluation de l'état sur les ventes réelles.
- PostgreSQL seulement si plusieurs serveurs ou de nombreuses écritures
  simultanées deviennent nécessaires.

## Suivi

- [x] M0 — Relevés complets, audit des variantes clos, restauration Drive, dépôt distant
  - [x] Relevé TCGdex : 379 cartes le 12 octobre (`pokeprice-manage prices`) ; 20 sans cote TCGdex (Zarbi, Celebi NP, Nidoran ♀ Jungle, Méganium HGSS) ; depuis le 13 octobre, un prix saisi à la main tient lieu de valeur prudente pour ces cartes
  - [x] Restauration du snapshot initial depuis Drive, vérifiée le 12 octobre
  - [x] Audit des variantes Foil, clos le 13 octobre : alertes du relevé toutes décidées, toutes les Foil confirmées à l’œil (filtre « Foil non vérifiées à l’œil » vide)
  - [x] Dépôt distant : GitHub `citizenu03bb/lilydex` depuis le 16 octobre (historique propre, sans les commits d’avant la réécriture), bugs suivis en issues
- [x] M1 — Valeur en jeu, file « À examiner », totaux prudents
- [ ] M1.1 — Référentiel des impressions : socle livré en audit ; preuves FR et de marché limitées à 2 jours ; ne bloque plus M2
- [ ] M2 — Vérifications indépendantes branchées, banc en test de non-régression
  - [x] Tranche 1 : lecture de la finition, proposition Standard/Foil, validation humaine, désaccords dans la file (13 octobre)
  - [x] Tranche 2 : lecture automatique à la saisie et banc rejoué sur l’application, pire de deux passages, seuils de sécurité inchangés (13 octobre)
  - [x] Tranche 3 : contrôle de l’édition par l’image (DINOv2), désaccords dans la file, seuils Gemini au plancher de quatre passages (13 octobre)
- [ ] M3 — Import de classeur dans l'application, série Android réceptionnée
- [ ] M4 — Estimation par état, lots du vrac, calibration par les ventes
- [ ] M5 — Hébergement, tests de bout en bout, restauration après déploiement
- [ ] Sortie MVP — critères S1 à S6 tenus sur un nouveau classeur

### Cohérence des catégories après M1 — 12 octobre 2026

La fiche calcule désormais Standard/Foil depuis les observations physiques et
les métadonnées de l’édition ; le serveur impose la même décision. Les cas
ambigus restent à examiner avec un produit documenté. Les corrections
anciennes sans finition reviennent dans la file sans être déclarées erronées.
L’audit `scripts/audit_variant_categories.py` est en lecture seule ; aucune
confirmation humaine ni observation physique n’est inventée ou réécrite.
