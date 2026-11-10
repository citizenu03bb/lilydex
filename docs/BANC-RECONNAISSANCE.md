# Banc d'essai de reconnaissance

> **Pour qui :** toute personne qui veut savoir ce que valent les lecteurs de l'application, chiffres à l'appui.
> **Vous y trouverez :** la méthode, les résultats par question avec leur intervalle de confiance, les décisions qu'ils ont motivées, leurs limites et la façon d'agrandir le banc.
> **Statut :** rapport de mesure. Chaque tableau porte ses conditions de mesure ; la présentation d'ensemble est dans [IA et vision](IA-VISION.md).

## À quoi sert le banc

Le banc répond à deux questions :

1. **Que sait faire chaque lecteur** (Gemini, Tesseract, DINOv2, CLIP, des
   agents Claude) sur de vraies cartes de la collection ?
2. **Un changement de prompt, de règle ou de modèle dégrade-t-il la sécurité ?**
   Le banc sert de test de non-régression : il échoue si une mesure passe sous
   son seuil.

Il a servi à décider, pas seulement à décorer : Tesseract écarté, Gemini seul
lecteur de texte, marge du contrôle par l'image choisie sur une table de
compromis. Ces choix ont chacun leur [fiche de décision](decisions/README.md).

## La méthode

- **La vérité terrain** : 31 cartes de la collection, vérifiées sur la carte
  physique, finitions comprises (lumière rasante pour les reverses). Les
  variantes vérifiées sont écrites dans `scripts/bench_recognition.py`.
- **Les photos** : 29 découpes de classeur de 400 px de large, plus deux
  photos prises à l'unité. Une carte (Gliscor 62/111) a le haut coupé : le
  bon résultat est de refuser la photo, pas de deviner le nom.
- **La galerie** : pour chaque carte, toutes les éditions TCGdex de même nom
  servent de leurres, dans la langue de la carte et en anglais.
- **Un intervalle à côté de chaque taux** : un résultat s'écrit « 22/27
  (IC 95 % : 63,3–91,9 %) ». L'intervalle dit entre quelles valeurs le vrai taux
  se trouve vraisemblablement, compte tenu du nombre de cartes. C'est
  l'intervalle de Wilson ; quand aucune erreur n'est observée, c'est la borne
  exacte de Clopper–Pearson à 95 % : zéro erreur sur 21 cartes établit « moins
  de 13,3 % d'erreurs », pas « aucune erreur ». Les bornes publiées sont
  arrondies vers l'extérieur, jamais vers le taux : la borne basse vers le bas,
  la borne haute vers le haut (`src/pokeprice/bench_stats.py`).
- **Une vérité toujours humaine, et sa provenance** : un modèle ne fournit
  jamais la vérité. Chaque carte porte la façon dont sa vérité a été établie,
  et les résultats sont donnés à part pour chacune
  ([fiche 0043](decisions/0043-banc-provenance-et-intervalles.md)) :
  *vérifiée à l'aveugle* (observée sur la carte physique sans voir de lecture),
  *récoltée* (confirmation déjà enregistrée dans la collection, faite sans
  protocole de banc) ou *banc initial* (les 31 cartes d'origine).
- **Une notation commune** : chaque lecteur est noté sur les mêmes mesures.
  Les agents Claude (Haiku et Sonnet) ont lu les cartes à l'aveugle.
- **Dans l'application** : `bench_recognition.py app` rejoue le banc à travers
  l'application, sur une copie jetable de la base remise à l'état de saisie.
  Deux passages réels ; chaque mesure est jugée sur **le pire des deux**,
  parce que Gemini n'est pas déterministe et qu'un passage chanceux ne doit
  pas masquer une régression.
- **Hors ligne** : `bench_recognition.py app-check` recalcule les propositions
  avec les règles actuelles à partir des lectures enregistrées, sans nouvel
  appel. Il affiche chaque mesure avec son compte et son intervalle, puis le
  détail par strate : provenance de la vérité, langue, finition.

```bash
uv run --extra web --extra vision python scripts/bench_recognition.py app        # passage réel (Gemini, TCGdex)
uv run --extra web --extra vision python scripts/bench_recognition.py app-check  # rejeu hors ligne
```

Dans la suite de tests (`tests/test_recognition_bench.py`), le rejeu tourne
si les données locales existent ; le passage réel ne se lance qu'avec
`POKEPRICE_BENCH=1`.

**Ce qui se rejoue depuis le dépôt.** La vérité terrain et les deux passages
enregistrés dans l'application sont publiés dans
[`docs/evaluations/banc-reconnaissance/`](evaluations/banc-reconnaissance/), les
identifiants d'exemplaires remplacés par des étiquettes (`banc-01`…). Depuis un
simple clone, `app-check` et la suite de tests rejouent donc hors ligne les
mesures de la lecture à la saisie, de la finition, de la langue et du contrôle
d'édition, avec les règles actuelles. Restent privés : les photos de la
collection (nécessaires au passage réel), les résultats du premier banc
(Tesseract, CLIP, agents Claude) et ceux de la porte énergie, qui ne sont
présentés ici qu'en résumé.

## Le premier banc : comparer les lecteurs

| Question | Meilleure source | Résultat (IC 95 %) | Autres lecteurs |
|---|---|---|---|
| Numéro de carte | Gemini | 25/31 (63,7–90,9 %) | agent Sonnet 24/31 (60,1–88,7 %) ; agent Haiku 5/31 (7,0–32,7 %) ; Tesseract 4/31 (5,1–28,9 %) |
| Langue | Gemini | 31/31 (90,7–100 %) | Tesseract 28/31 (75,1–96,7 %) |
| Édition | Gemini et catalogue | 21/30 (52,1–83,4 %) | DINOv2 retrouve la bonne édition parmi les cartes de même nom dans 24/27 cas (71,9–96,2 %) |
| Illustration holo ou mate | Gemini | 21/21 (86,7–100 %) | |
| Tampon | Gemini | 21/21 (86,7–100 %) | 3 cartes tamponnées seulement : le score mesure surtout l'absence de fausse détection |
| Reverse | aucune | 0 à 1 sur 2 | Gemini 0/2 (0–77,7 %), agent Sonnet 1/2 (9,4–90,6 %) : angle mort de tous les lecteurs sur photo de classeur |
| Contrefaçon | aucune seule | 1 contrefaçon au banc | Gemini la signale avec 2 fausses alertes sur 30 vraies cartes (1,8–21,4 %) ; Sonnet sans fausse alerte ; Haiku la manque |

Recherche d'images, sur une galerie de 473 images de référence (3 promos sans
image TCGdex, donc 27 cartes évaluables) :

| Modèle | Bonne édition en tête (IC 95 %) | Parmi les 3 premières (IC 95 %) |
|---|---|---|
| DINOv2-small | 19/27 (51,5–84,2 %) | 24/27 (71,9–96,2 %) |
| CLIP ViT-B/32 | 13/27 (30,7–66,1 %) | 14/27 (33,9–69,3 %) |

Les deux intervalles de la première colonne se recouvrent : sur 27 cartes,
l'écart entre DINOv2 et CLIP est une indication, pas une preuve.

*Conditions de mesure : 31 cartes d'une seule collection (25 FR, 5 EN, 1 IT, aucune japonaise), dont 21 à variante vérifiée sur la carte et 2 reverses ; gemini-3.8-flash ; Tesseract fra+eng+ita+deu+spa ; agents Claude Haiku et Sonnet lancés à la main ; octobre 2026.*

## Le banc dans l'application : lecture à la saisie

| Mesure | Seuil | 1er passage | 2e passage | Pire passage (IC 95 %) |
|---|---|---|---|---|
| Numéro | 23/30 | 24/30 | 23/30 | 23/30 (59,0–88,3 %) |
| Langue | 30/30 | 30/30 | 30/30 | 30/30 (90,4–100 %) |
| Édition en tête | 18/29 | 21/29 | 20/29 | 20/29 (50,7–82,8 %) |
| Photo inexploitable refusée | 1/1 | 1/1 | 1/1 | 1/1 (5,0–100 %) |
| Holo ou mate, quand la lecture tranche | 21/21 | 21/21 | 21/21 | 21/21 (86,7–100 %) |
| Lecture tranchée (sinon examen) | 18/21 | 21/21 | 21/21 | 21/21 (86,7–100 %) |
| Tampon | 21/21 | 21/21 | 21/21 | 21/21 (86,7–100 %) |
| **Proposition de variante fausse, Foil au seuil ou sans prix** | **0** | **0/24** | **0/24** | **0/24 (0–11,8 %)** |

*Conditions de mesure : banc rejoué à travers l'application, deux passages réels publiés (ceux que `app-check` rejoue), gemini-3.8-flash, 30 cartes (la photo à refuser exclue des mesures de lecture), 24 cartes dont une personne a vérifié la variante, toutes du banc initial, octobre 2026.*

La dernière ligne est celle qui protège l'argent, et c'est la moins établie :
aucune proposition fausse et coûteuse sur 24 cartes signifie seulement que le
taux réel est sous 12 %. Deux propositions contraires sur ces 24 (2,3–25,9 %)
sont tolérées par la règle : des reverses sous le seuil de valeur proposées
Standard. Descendre la borne à 5 % demande 59 cartes vérifiées sans une seule
proposition fausse, à 2 % il en faut 149.

Quatre passages ont montré un bruit plus large que prévu : numéro de 23 à
25/30, édition de 18 à 22/29. Les erreurs qui changent d'un passage à l'autre :
Celebi 29/40 lu « Celebi ☆ » une fois sur deux (l'étoile noire des promos,
près du numéro, rattachée au nom), Clic et PokéNav qui perdent leur numéro un
passage sur deux.

**Seuils de confort, seuils de sécurité.** Une édition manquée renvoie la
carte « À vérifier » : elle coûte du temps, pas d'argent. Les seuils de
numéro et d'édition sont donc fixés au plus bas observé. Les seuils qui
empêchent une carte de valeur de passer en vrac (proposition de variante
fausse, holo ou mate, tampon) ne baissent jamais.

**Un trou de règle trouvé par le banc.** TCGdex ne répertorie pas certaines
reverses (Clic 75/114) : son « pas de reverse » ne vaut donc plus preuve quand
la photo laisse le fond indéterminé. Une reverse sous le seuil de valeur
proposée Standard reste tolérée par la règle (Clic à 0,77 €, Octillery 58/127).

**Coût** : environ 1 930 jetons par carte pour la lecture de la finition
(protocole `card-finish-v2`), langue comprise, contre 1 820 à 1 860 sans la
langue. Le tout premier essai réel, sur trois cartes confirmées à l'œil (une
holo tamponnée EX Deoxys, une mate, une reverse Noir & Blanc), avait donné 3
sur 3, tampon compris, pour environ 1 350 jetons d'entrée et 450 de sortie,
raisonnement compris.

## Le contrôle d'édition par l'image

| Mesure | Résultat (IC 95 %) |
|---|---|
| Vraie édition confirmée par l'image | 22/27 (63,3–91,9 %) |
| Vraie édition sans fausse alerte | 26/27 (81,7–99,35 %) ; une fausse alerte : Solochi |
| Impression voisine la plus ressemblante signalée (fausse édition simulée) | 14/26 (35,4–71,3 %) |

Le calcul est déterministe : les deux passages donnent les mêmes chiffres.
Le premier banc donnait 24/27 sur une galerie sans les réimpressions à
l'illustration identique (Recherche d'énergie, PokéNav) : l'image seule ne
les départage pas, le contrôle reste alors indécis.

**Choix de la marge**, l'écart de similarité sous lequel deux éditions sont
jugées trop proches pour trancher :

| Marge | Fausses alertes sur 27 vraies éditions (IC 95 %) | Éditions voisines signalées sur 26 (IC 95 %) |
|---|---|---|
| 0,02 | 3/27 (3,8–28,1 %) | 17/26 (46,2–80,6 %) |
| **0,05 (retenue)** | **1/27 (0,65–18,3 %)** | **14/26 (35,4–71,3 %)** |
| 0,08 | 0/27 (0–10,6 %) | 11/26 (25,5–61,1 %) |

Les intervalles des trois marges se recouvrent largement : la table a orienté
le choix, 27 cartes ne suffisent pas à départager les marges.

*Conditions de mesure : banc rejoué à travers l'application, DINOv2-small (facebook/dinov2-small) sur processeur, galerie des éditions TCGdex de même nom, environ 1 s par carte une fois les images en cache, octobre 2026.*

Des appels TCGdex échoués font chuter ces mesures (3 à 7 contrôles perdus lors
d'un essai) : le contrôle a besoin du réseau pour constituer sa galerie.

### Piste mesurée, non livrée : proposer l'édition à la saisie

Quand le catalogue ne trouve rien (numéro absent ou mal lu), DINOv2 pourrait
proposer l'édition. Simulation hors ligne sur les lectures enregistrées des
deux passages :

| Règle | Cartes sans résultat catalogue (6, puis 8) | Toutes les cartes (58 lectures) |
|---|---|---|
| Nom seul, écart ≥ 0,05 | 6/6 puis 6/8 justes, aucune fausse | 30 justes, **4 fausses**, 24 sans proposition (30/34 propositions justes, IC 95 % : 73,3–95,4 %) |
| Nom puis filtre par numéro, écart ≥ 0,05 | 6/6 puis **7/8** justes, aucune fausse | **48 justes**, 1 fausse, 9 sans proposition (48/49, IC 95 % : 89,3–99,64 %) |

*Conditions de mesure : lectures enregistrées des deux passages applicatifs, DINOv2-small rejoué hors ligne, octobre 2026.*

Sans filtre, deux erreurs reviennent aux deux passages : Solochi, confondu
avec une impression récente (écart 0,075), et Baggiguane 10/12, dont la vraie
impression n'a pas d'image, si bien que DINOv2 en choisit forcément une autre.
Monter la marge ne les sépare pas des bonnes propositions, qui ont aussi des
écarts de 0,061 et 0,075. Le numéro, même partiel, les règle : « 68/97 » garde
l'extension à 97 cartes. Il départage aussi Clic (« 89/114 ») et Chamallot
(écarts de 0,075 à 0,241), et récupère Zarbi K (« 58/105 »), Fossile Crâne et
Méthode d'entraînement du Prof. Orme.

La seule erreur restante, avec le filtre, est PokéNav lu « 88/109 », numéro
d'une autre impression existante dont l'illustration est identique : le
catalogue faisait déjà la même erreur, et l'image ne peut pas trancher. Risque
restant : sans numéro lu, une vraie impression sans image (promos) laisse
passer une mauvaise proposition ; la proposition devra alors signaler les
impressions de ce nom qui n'ont pas d'image.

## La langue : Tesseract face au contrôle de cohérence

| Mesure | Tesseract | Contrôle de cohérence (Gemini) |
|---|---|---|
| Langue juste | 28/31 (IC 95 % : 75,1–96,7 %) | 31/31, aux deux passages (IC 95 % : 90,7–100 %) |
| Cartes envoyées en examen sans raison | 3 (Clic, Octillery, Transfert) | 0 |
| Erreurs de Gemini rattrapées | 0 | sans objet |

*Conditions de mesure : 31 cartes (25 FR, 5 EN, 1 IT, aucune japonaise), Tesseract fra+eng+ita+deu+spa, gemini-3.8-flash dans la lecture de la finition, deux passages applicatifs, octobre 2026.*

Le contrôle de cohérence n'est pas indépendant : c'est le même modèle, dans un
autre appel, sur une autre question (la langue du texte imprimé hors nom). Il
coûte environ 100 jetons de plus par carte. Décision : [fiche 0005](decisions/0005-langue-sans-tesseract.md).

## La porte énergie

La porte énergie reconnaît par l'image les énergies de base, dans le pipeline
d'albums, pour ne pas les envoyer à Gemini. Une pochette passe la porte si
l'énergie de base la plus proche devance toute autre carte d'au moins 0,10.

**Protocole publié**, carte par carte, chaque carte hors de sa propre banque
(`scripts/eval_energy_gate.py`) : pour chaque exemplaire, on retire de la
banque toutes les lignes qui partagent sa photo, puis on lui applique la règle.

| Mesure | Résultat |
|---|---|
| Énergies de base admises | 166/166 (IC 95 % : 98,2–100 %) |
| Autres cartes admises à tort | 1/1 601 (IC 95 % : 0,01–0,36 %) : la seule Double Énergie Incolore de la collection, qui n'a aucun autre exemplaire dans la banque pour la retenir |
| Type proposé, quand il est comparable | 96/99 justes (IC 95 % : 91,4–99,0 %), 3 faux (67 sans type enregistré ou sans proposition) |
| Effet de la marge entre 0,05 et 0,12 | aucun sur cette mesure |

*Conditions de mesure : 1 767 exemplaires d'une seule collection, photos préparées de la collection, étiquettes tirées des noms enregistrés, DINOv2-small, marges 0,05 à 0,12, octobre 2026.*

```bash
uv run --extra vision python scripts/eval_energy_gate.py data/inventory --margins 0.05,0.08,0.10
```

Une carte admise à tort n'est jamais confirmée ni cotée : elle arrive
« Énergie de base », type à confirmer, et reste à examiner.

**La mesure sur les pochettes de classeur, plus fragile.** Sur six classeurs
numérisés (1 305 pochettes), 162 énergies de base sur 164 sont passées
(IC 95 % : 95,6–99,67 %), et
aucune autre carte ; à la marge de 0,08, une Double Énergie Incolore passait
encore. Le protocole exact de cette mesure n'a pas été consigné : on ne sait
pas si les photos de ces pochettes étaient déjà dans la banque. C'est elle qui
a fixé la marge à 0,10 ; elle n'est pas citée comme résultat principal.

## Agrandir le banc

Le banc vise au moins 200 cartes vérifiées, dont 60 par strate qui compte :
reverses, holos, autres langues que le français, éditions voisines (même nom,
autre impression), cartes de valeur. À 60 cartes sans erreur, la borne passe
sous 5 % ; à 200 cartes, un taux de 80 % est connu à ± 6 points.

Deux commandes préparent le travail. Elles ouvrent la base en lecture seule,
exigent `--data` et n'écrivent rien dans la collection :

```bash
pokeprice-manage --data <base> bench-harvest                    # ce que la collection contient déjà
pokeprice-manage --data <base> bench-sample --format sheet      # la prochaine séance, à remplir devant le classeur
```

- **`bench-harvest`** compte les variantes déjà confirmées par une personne :
  par langue, par finition, par provenance, et selon que le motif enregistré
  dit ou non que la carte a été observée en main. Il ne nomme aucune carte.
  L'auteur est celui que la fiche enregistre : une variante confirmée par un
  agent ou un automate, ou sans auteur enregistré, est comptée à part et ne
  sert jamais de vérité.
- **`bench-sample`** propose les cartes à vérifier ensuite, les strates les
  plus loin de leur cible d'abord, une seule carte par impression, dans l'ordre
  du classeur. Avant l'observation, une carte n'est qu'une reverse *possible*
  (le catalogue en liste une) : elle compte pour la part de ces cartes qui se
  sont révélées reverses jusqu'ici. La feuille de séance ne montre ni lecture
  ni nom : la personne note le nom, le numéro, la langue, la finition et le
  tampon qu'elle voit. `--names` affiche les noms, et l'identité n'est alors
  plus vérifiée à l'aveugle. La sortie JSON porte l'identifiant et la version
  de chaque exemplaire, pour un outil.
- **L'enregistrement reste humain.** La personne saisit ce qu'elle a noté dans
  les fiches, avec un motif qui commence par « Vérification à l'aveugle
  (banc) ». C'est ce motif, et l'absence de lecture de finition antérieure, qui
  classent la confirmation « à l'aveugle ».

Une séance préparée par un agent avec le guide `pokeprice-agent` peut partir
de la sortie JSON (identifiant, version, album, page, pochette), mais ce guide
fait examiner la photo et formuler une question : la vérification qui en sort
est ancrée par cette lecture, donc *récoltée*, pas à l'aveugle.

*Conditions de mesure : comptage en lecture seule sur la collection de référence, novembre 2026.*

| Ce que la collection contient | Cartes |
|---|---|
| Variantes confirmées par une personne, photo conservée | 301 (237 impressions distinctes) |
| Confirmées par un agent ou un automate, ou sans auteur enregistré (exclues) | 0 |
| dont le motif dit « observée en main » | 106 |
| dont le motif ne permet pas de savoir (carte ou photo) | 195 |
| Par langue | 257 FR, 41 EN, 2 JA, 1 IT |
| Par finition | 200 mates ou autres, 55 reverses, 46 holos |
| Confirmées après avoir vu une lecture de finition | 0 : aucune lecture n'existait encore |
| Vérifiées à l'aveugle selon le protocole | 0 |
| Avec une édition du catalogue (contrôle d'édition rejouable) | 250 |
| Lecture de finition enregistrée | 0 ; un passage réel de Gemini est nécessaire |

Ces 301 cartes sont *récoltées* : leur finition a été confirmée sans qu'une
lecture de finition existe, mais leur identité vient de la proposition du
pipeline d'albums, que la personne avait sous les yeux. Elles n'entrent dans
les mesures qu'après un passage réel, et leurs résultats restent séparés de
ceux des vérifications à l'aveugle.

## Les limites

- **Petits échantillons d'une seule collection** : 21 à 31 cartes selon la
  question, choisies en partie parmi les cas difficiles. Les intervalles
  mesurent l'incertitude du compte, pas ce biais de choix : aucun pourcentage
  n'est à généraliser.
- **Une vérité en partie ancrée** : les cartes du banc initial et les cartes
  récoltées ont été confirmées par une personne qui voyait l'identité proposée.
  Seules les vérifications à l'aveugle mesurent sans ce biais, et il n'y en a
  aucune.
- **Aucune carte japonaise** au banc, et deux seulement dans la collection :
  rien n'est établi pour le japonais, et cette collection ne permet pas de
  l'établir.
- **Deux reverses seulement** : leur détection sur photo n'est pas fiable, d'où
  l'examen physique au-dessus du seuil de valeur ([fiche 0008](decisions/0008-reverses-examen-physique.md)).
- **Lecture locale non mesurée** : le pipeline d'albums lit par défaut avec
  Gemma via Ollama, qui n'a jamais été passé au banc.
- **Aide à l'état non mesurée** : seuls le parcours et le format de réponse ont
  été validés.
- **Photos privées** : un nouveau passage réel demande les photos de la
  collection, qui ne sont pas publiées ; seules les lectures enregistrées le
  sont.
