# Banc d'essai de reconnaissance

> **Pour qui :** toute personne qui veut savoir ce que valent les lecteurs de Lilydex, chiffres à l'appui.
> **Vous y trouverez :** la méthode, les résultats par question, les décisions qu'ils ont motivées et leurs limites.
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
- **Une notation commune** : chaque lecteur est noté sur les mêmes mesures.
  Les agents Claude (Haiku et Sonnet) ont lu les cartes à l'aveugle.
- **Dans l'application** : `bench_recognition.py app` rejoue le banc à travers
  l'application, sur une copie jetable de la base remise à l'état de saisie.
  Deux passages réels ; chaque mesure est jugée sur **le pire des deux**,
  parce que Gemini n'est pas déterministe et qu'un passage chanceux ne doit
  pas masquer une régression.
- **Hors ligne** : `bench_recognition.py app-check` recalcule les propositions
  avec les règles actuelles à partir des lectures enregistrées, sans nouvel
  appel.

```bash
uv run --extra web --extra vision python scripts/bench_recognition.py app        # passage réel (Gemini, TCGdex)
uv run --extra web --extra vision python scripts/bench_recognition.py app-check  # rejeu hors ligne
```

Dans la suite de tests (`tests/test_recognition_bench.py`), le rejeu tourne
si les données locales existent ; le passage réel ne se lance qu'avec
`POKEPRICE_BENCH=1`.

**Les données du banc restent privées** (photos de la collection, lectures
enregistrées, dans `outputs/`, que git ignore). Le dépôt public contient le
code du banc, sa notation et ces résumés : les chiffres ci-dessous ne sont pas
reproductibles depuis le seul dépôt.

## Le premier banc : comparer les lecteurs

| Question | Meilleure source | Résultat | Autres lecteurs |
|---|---|---|---|
| Numéro de carte | Gemini | 25/31 | agent Sonnet 24/31 ; agent Haiku 5/31 ; Tesseract 4/31 |
| Langue | Gemini | 31/31 | Tesseract 28/31 |
| Édition | Gemini et catalogue | 21/30 | DINOv2 retrouve la bonne édition parmi les cartes de même nom dans 24/27 cas |
| Illustration holo ou mate | Gemini | 21/21 | |
| Tampon | Gemini | 21/21 | 3 cartes tamponnées seulement : le score mesure surtout l'absence de fausse détection |
| Reverse | aucune | 0 à 1 sur 2 | Gemini 0/2, agent Sonnet 1/2 : angle mort de tous les lecteurs sur photo de classeur |
| Contrefaçon | aucune seule | 1 contrefaçon au banc | Gemini la signale avec 2 fausses alertes sur 30 vraies cartes ; Sonnet sans fausse alerte ; Haiku la manque |

Recherche d'images, sur une galerie de 473 images de référence (3 promos sans
image TCGdex, donc 27 cartes évaluables) :

| Modèle | Bonne édition en tête | Parmi les 3 premières |
|---|---|---|
| DINOv2-small | 19/27 | 24/27 |
| CLIP ViT-B/32 | 13/27 | 14/27 |

*Conditions de mesure : 31 cartes d'une seule collection (25 FR, 5 EN, 1 IT, aucune japonaise), dont 21 à variante vérifiée sur la carte et 2 reverses ; gemini-3.8-flash ; Tesseract fra+eng+ita+deu+spa ; agents Claude Haiku et Sonnet lancés à la main ; octobre 2026.*

## Le banc dans l'application : lecture à la saisie

| Mesure | Seuil | 1er passage | 2e passage |
|---|---|---|---|
| Numéro | 24/30 | 24/30 | 24/30 |
| Langue | 30/30 | 30/30 | 30/30 |
| Édition en tête | 20/29 | 20/29 | 21/29 |
| Photo inexploitable refusée | 1/1 | 1/1 | 1/1 |
| Holo ou mate, quand la lecture tranche | 21/21 | 18/18 | 21/21 |
| Lecture tranchée (sinon examen) | 18/21 | 18/21 | 21/21 |
| Tampon | 21/21 | 21/21 | 21/21 |
| **Proposition de variante fausse, Foil au seuil ou sans prix** | **0** | **0** | **0** |

*Conditions de mesure : banc rejoué à travers l'application, deux passages réels, gemini-3.8-flash, 30 cartes (la photo à refuser exclue des mesures de lecture), octobre 2026.*

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

| Mesure | Résultat |
|---|---|
| Vraie édition confirmée par l'image | 22/27 |
| Vraie édition sans fausse alerte | 26/27 (une fausse alerte : Solochi) |
| Impression voisine la plus ressemblante signalée (fausse édition simulée) | 14/26 |

Le calcul est déterministe : les deux passages donnent les mêmes chiffres.
Le premier banc donnait 24/27 sur une galerie sans les réimpressions à
l'illustration identique (Recherche d'énergie, PokéNav) : l'image seule ne
les départage pas, le contrôle reste alors indécis.

**Choix de la marge**, l'écart de similarité sous lequel deux éditions sont
jugées trop proches pour trancher :

| Marge | Fausses alertes sur 27 vraies éditions | Éditions voisines signalées sur 26 |
|---|---|---|
| 0,02 | 3 | 17 |
| **0,05 (retenue)** | **1** | **14** |
| 0,08 | 0 | 11 |

*Conditions de mesure : banc rejoué à travers l'application, DINOv2-small (facebook/dinov2-small) sur processeur, galerie des éditions TCGdex de même nom, environ 1 s par carte une fois les images en cache, octobre 2026.*

Des appels TCGdex échoués font chuter ces mesures (3 à 7 contrôles perdus lors
d'un essai) : le contrôle a besoin du réseau pour constituer sa galerie.

### Piste mesurée, non livrée : proposer l'édition à la saisie

Quand le catalogue ne trouve rien (numéro absent ou mal lu), DINOv2 pourrait
proposer l'édition. Simulation hors ligne sur les lectures enregistrées des
deux passages :

| Règle | Cartes sans résultat catalogue (6, puis 8) | Toutes les cartes (58 lectures) |
|---|---|---|
| Nom seul, écart ≥ 0,05 | 6/6 puis 6/8 justes, aucune fausse | 30 justes, **4 fausses**, 24 sans proposition |
| Nom puis filtre par numéro, écart ≥ 0,05 | 6/6 puis **7/8** justes, aucune fausse | **48 justes**, 1 fausse, 9 sans proposition |

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
| Langue juste | 28/31 | 31/31, aux deux passages |
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
| Énergies de base admises | 166/166 |
| Autres cartes admises à tort | 1 sur 1 601 : la seule Double Énergie Incolore de la collection, qui n'a aucun autre exemplaire dans la banque pour la retenir |
| Type proposé, quand il est comparable | 96 justes, 3 faux (67 sans type enregistré ou sans proposition) |
| Effet de la marge entre 0,05 et 0,12 | aucun sur cette mesure |

*Conditions de mesure : 1 767 exemplaires d'une seule collection, photos préparées de la collection, étiquettes tirées des noms enregistrés, DINOv2-small, marges 0,05 à 0,12, octobre 2026.*

```bash
uv run --extra vision python scripts/eval_energy_gate.py data/inventory --margins 0.05,0.08,0.10
```

Une carte admise à tort n'est jamais confirmée ni cotée : elle arrive
« Énergie de base », type à confirmer, et reste à examiner.

**La mesure sur les pochettes de classeur, plus fragile.** Sur six classeurs
numérisés (1 305 pochettes), 162 énergies de base sur 164 sont passées, et
aucune autre carte ; à la marge de 0,08, une Double Énergie Incolore passait
encore. Le protocole exact de cette mesure n'a pas été consigné : on ne sait
pas si les photos de ces pochettes étaient déjà dans la banque. C'est elle qui
a fixé la marge à 0,10 ; elle n'est pas citée comme résultat principal.

## Les limites

- **Petits échantillons d'une seule collection** : 21 à 31 cartes selon la
  question, choisies en partie parmi les cas difficiles. Aucun pourcentage
  n'est à généraliser.
- **Aucune carte japonaise** au banc, alors que la collection en contient :
  rien n'est établi pour le japonais.
- **Deux reverses seulement** : leur détection sur photo n'est pas fiable, d'où
  l'examen physique au-dessus du seuil de valeur ([fiche 0008](decisions/0008-reverses-examen-physique.md)).
- **Lecture locale non mesurée** : le pipeline d'albums lit par défaut avec
  Gemma via Ollama, qui n'a jamais été passé au banc.
- **Aide à l'état non mesurée** : seuls le parcours et le format de réponse ont
  été validés.
- **Données privées** : le rejeu complet demande les photos et les lectures
  enregistrées, qui ne sont pas publiées.
