# IA et vision : la machine propose, l'humain décide

> **Pour qui :** toute personne qui veut comprendre ce que font les modèles dans Lilydex, et ce qu'ils ne font pas.
> **Vous y trouverez :** les principes, chaque brique avec ses mesures et ses limites, les garde-fous, le coût, et la place de l'IA dans le développement du projet.
> **Statut :** en vigueur. Le détail des mesures est dans le [banc d'essai](BANC-RECONNAISSANCE.md).

> **In short.** Lilydex uses applied, measured and supervised AI. A vision-language
> model (Gemini) reads each card photo; a pre-trained image model (DINOv2, CPU only)
> checks the edition from the image alone; a nearest-neighbour gate with rejection
> skips cloud calls for basic Energy cards. Every model output is a *proposal* with its
> evidence (photo, model, protocol, raw answer); a person confirms identity, variant and
> condition. Models abstain when unsure, safety thresholds are never lowered, and every
> choice was measured on a bench of hand-verified cards. No model is trained or fine-tuned.

## Les principes

1. **Le modèle propose, une personne décide.** Aucune lecture ne modifie une
   fiche. Une identité n'est « confirmée » qu'après le choix d'une édition par
   une personne ; la variante et l'état aussi.
2. **S'abstenir plutôt que deviner.** Une photo illisible est refusée ; deux
   éditions trop proches laissent le contrôle « indécis » ; une variante de
   valeur demande un examen physique.
3. **Tout garder.** Chaque lecture conserve la photo lue, le modèle, le
   protocole, la réponse brute et les jetons consommés. Une lecture devient
   obsolète dès que la photo change.
4. **Mesurer avant d'adopter.** Chaque brique a été passée au banc d'essai,
   face à d'autres solutions. Celles qui n'apportaient rien ont été écartées.
5. **Une seule file.** Tous les désaccords (finition, langue, édition)
   arrivent dans « À examiner », avec leurs preuves.

## Les briques

| Brique | Modèle | Où ça tourne | Mesure |
|---|---|---|---|
| Lecture de la carte à la saisie | Gemini (vision-langage) | cloud, appelé par le serveur | numéro juste 23 à 25 fois sur 30 selon le passage ; langue 30 sur 30 |
| Finition, tampon et langue du texte | Gemini | cloud, après chaque saisie avec photo | holo ou mate : aucune erreur sur 21 cartes quand la lecture tranche ; aucune variante fausse proposée au-dessus du seuil de valeur |
| Contrôle d'édition par l'image | DINOv2-small, pré-entraîné | serveur, processeur seul | 22 vraies éditions confirmées sur 27, une fausse alerte |
| Porte énergie (pipeline d'albums) | DINOv2-small, plus proches voisins avec rejet | portable ou serveur | 166 énergies de base sur 166 admises, une autre carte admise à tort sur 1 601 |
| Lecture des albums (pipeline) | Gemma via Ollama (local, par défaut) ou Gemini | portable | non mesurée pour Gemma |
| Aide à l'état | Gemini | cloud, seulement à la demande | non mesurée : une proposition, jamais une note |
| Préparation des photos | vision classique (Pillow), sans IA | serveur | non mesurée ; l'original est toujours gardé |

*Conditions de mesure : 27 à 31 cartes d'une seule collection vérifiées sur la carte physique (25 FR, 5 EN, 1 IT, aucune japonaise), gemini-3.8-flash, DINOv2-small, deux passages jugés sur le pire ; porte énergie : 1 767 exemplaires, chaque carte hors de sa propre banque ; octobre 2026. Détail : [banc d'essai](BANC-RECONNAISSANCE.md).*

### Lire une carte à la saisie

Vous photographiez une carte, au téléphone ou à la webcam. Gemini lit le nom
imprimé, la référence, la langue, les PV et le tampon ; l'application cherche
ensuite dans TCGdex les éditions qui correspondent exactement. Vous comparez
l'illustration et choisissez : sans ce geste, l'identité reste « À vérifier ».

- La réponse du modèle suit un schéma strict, revalidé par le serveur.
- Une photo dont le recto n'est pas lisible est refusée : il faut la reprendre.
- La recherche dans le catalogue est stricte (nom sans accents, numéro, PV,
  niveau) : elle ne « corrige » jamais une lecture en silence.
- Au moment de confirmer, le serveur revérifie que le nom, l'édition, la
  langue, le numéro et les PV n'ont pas changé depuis ce choix.

### Lire la finition, le tampon et la langue

Juste après chaque saisie avec photo, Gemini répond à des questions fermées :
l'illustration est-elle holo, mate ou incertaine ? Le fond brille-t-il ? Un
tampon est-il imprimé ? Dans quelle langue est le texte hors nom ? Une règle
fixe croise ensuite cette lecture avec les variantes connues de TCGdex, le
tampon observé par une personne et la [valeur en jeu](VALUATION.md) :

- si la version Foil vaut au moins le seuil de valeur (10 € par défaut) ou n'a
  pas de prix connu, la règle **demande un examen physique** : une
  illustration mate ne prouve jamais une Standard quand une reverse possible
  vaut cher ;
- sinon, elle propose la variante ;
- un tampon observé par une personne l'emporte toujours sur la lecture ;
- une langue lue différente de la fiche envoie la carte dans « À examiner ».
  Vous corrigez, ou vous gardez la langue de la fiche avec un motif.

Ce contrôle de langue n'est pas un second avis indépendant : c'est le même
modèle, dans un autre appel. Il a remplacé Tesseract, qui n'aurait rattrapé
aucune erreur et envoyait des cartes en examen sans raison
([fiche 0005](decisions/0005-langue-sans-tesseract.md)).

`pokeprice-manage serve --no-auto-checks` coupe ces lectures automatiques.

### Contrôler l'édition par l'image

Un second regard, indépendant du texte : la photo ressemble-t-elle davantage
à l'édition enregistrée qu'aux autres impressions du même nom ? DINOv2, un
modèle d'images pré-entraîné utilisé tel quel, calcule un vecteur pour la
photo et pour chaque image TCGdex de même nom, puis les compare. Résultat :
accord, indécis (écart inférieur à 0,05), désaccord ou impossible. Un
désaccord envoie la carte dans « À examiner » ; la fiche n'est jamais modifiée.

- Le calcul se fait sur le serveur, sans carte graphique ; aucune photo ne
  part vers un service extérieur pour ce contrôle.
- Les vecteurs sont mis en cache sous l'empreinte SHA-256 de chaque image :
  une image n'est analysée qu'une fois, et un cache calculé sur un poste reste
  valable sur un autre.
- Sans l'option `vision`, l'application affiche « Contrôle indisponible sur ce
  serveur » et fonctionne normalement.
- La marge de 0,05 a été choisie sur une table de compromis entre fausses
  alertes et erreurs rattrapées ([fiche 0006](decisions/0006-dinov2-marge.md)).

**Limites** : les réimpressions à l'illustration identique ne se départagent
pas par l'image ; la galerie se limite au nom enregistré, donc un mauvais nom
n'est pas détecté ; les promos sans image TCGdex ne sont pas contrôlables.
Le libellé « Édition confirmée par l'image » signifie que l'édition de la
fiche arrive en tête, même de peu : pour des illustrations identiques, c'est
un accord sans valeur de preuve.

### La porte énergie

Dans le pipeline d'albums, les énergies de base, nombreuses et sans valeur,
ne passent plus par Gemini. Avec `pokeprice scan --energy-gate <dossier>`,
DINOv2 compare chaque pochette aux exemplaires de la collection : les énergies
de base servent de références, toutes les autres cartes de contre-exemples,
énergies spéciales comprises. Une pochette passe la porte seulement si
l'énergie de base la plus proche devance toute autre carte d'au moins 0,10, et
seulement si la banque compte au moins 20 références.

Une pochette admise arrive « Énergie de base », non identifiée, type proposé à
confirmer, sans prix. Elle n'est jamais confirmée ni cotée. Une énergie
spéciale encore absente de la collection peut passer la porte : elle reste
alors à examiner. Décision : [fiche 0010](decisions/0010-porte-energie.md).

### Lire les albums en ligne de commande

`pokeprice scan` découpe les photos de pages en pochettes et lit chaque carte.
La lecture est locale par défaut (Gemma via [Ollama](https://ollama.com),
aucune photo envoyée, aucun coût) ; `--backend gemini` l'envoie au service
cloud, qui peut être facturé. Une réponse vide ou malformée devient un échec
qu'on peut relancer, jamais une « pochette vide ». Le travail reprend après
une interruption (`--resume`).

La qualité de lecture de Gemma n'a pas été mesurée.

### L'aide à l'évaluation de l'état

Sur demande seulement, Gemini reçoit les photos originales du recto et du
verso, avant toute correction, et rend la liste des défauts visibles et un
état proposé, ou « indéterminable ». Le serveur applique ses propres
garde-fous : un état NM exige deux faces exploitables, les originaux et une
qualité suffisante. L'état final est choisi par une personne, avec un motif.
Voir [l'aide à l'état](CONDITION-ASSESSMENT.md).

Ce n'est pas une notation : ni note PSA ou BGS, ni confiance inventée, et
aucune mesure sur des cartes réelles.

### La préparation des photos

Ce n'est pas de l'IA : de la vision par ordinateur classique, écrite avec
Pillow seul. Repérage de la carte, redressement de la perspective, balance des
blancs bornée à ±8 % par canal. Si la forme n'est pas sûre, la photo reste
entière. L'original est toujours conservé, et l'aide à l'état reçoit
l'original, pas la photo retouchée.

## Les garde-fous

- **Injection par l'image** : chaque prompt traite le texte imprimé sur la
  carte comme une donnée, jamais comme une instruction, et l'appel de
  fonctions automatique est désactivé. Ce point n'a pas été éprouvé par des
  images piégées.
- **Clés** : la clé Gemini reste sur le serveur, jamais dans le navigateur ;
  une erreur du fournisseur est remplacée par un message fixe, pour ne jamais
  afficher une clé ou des en-têtes.
- **Photos** : ré-encodées sans métadonnées EXIF ni position ; taille et
  nombre de pixels bornés. Chaque envoi à Gemini est annoncé dans l'interface.
  Les photos de cartes partent tout de même chez Google : ne photographiez ni
  personne ni document ([RGPD](RGPD.md)).
- **Débit** : 5 lectures par minute et par compte.
- **Images de référence** : téléchargées seulement depuis les hôtes du
  catalogue, avec une taille bornée.

## Le coût

- Lecture de la finition et de la langue : environ 1 930 jetons Gemini par
  carte.
- Contrôle d'édition : environ une seconde par carte sur processeur, une fois
  les images en cache. Sur le serveur, l'option `vision` occupe environ 1 Go
  de disque ; le service au repos reste sous 150 Mo de mémoire, et le calcul
  de la banque de la porte énergie monte à 1,2 Go
  ([hébergement](DEPLOYMENT.md)).
- La porte énergie évite un appel Gemini par énergie de base reconnue.

## Ce que l'IA ne fait pas dans Lilydex

- Elle ne confirme rien : identité, variante et état restent des décisions
  humaines.
- Elle ne repère pas les reverses de façon sûre sur une photo de classeur.
- Elle ne signale pas les contrefaçons : une seule au banc, et des fausses
  alertes.
- Elle n'évalue pas l'état de façon mesurée.
- Aucun modèle n'est entraîné ni affiné : DINOv2 est utilisé tel quel, Gemini
  est piloté par des prompts.
- Un seul lecteur de texte est en service (Gemini) ; le service est prêt à en
  accueillir un second, qui n'est pas branché.

## Le pilote agent

Un agent IA peut travailler sur un album délégué, avec sa propre clé d'accès,
révocable à tout moment. Il ne prépare que des brouillons de lots ; une
personne publie, réserve et vend. Voir le [pilote agent](AGENT_CONTROL.md).

## L'IA dans le développement du projet

Lilydex est développé avec des agents de code, surtout Claude Code. La
majorité des commits portent la mention `Co-Authored-By`
(`git log --grep Co-Authored-By --oneline`). Le mainteneur fixe les jalons et
leurs critères de sortie, établit la vérité terrain sur les cartes physiques,
tranche par écrit et relit ; le banc d'essai et les tests servent de
garde-fous.

- **Les agents ont été mesurés comme les autres lecteurs.** Des agents Claude
  (Haiku et Sonnet) ont lu le banc à l'aveugle ; ils n'ont pas été retenus
  pour la lecture ([fiche 0004](decisions/0004-gemini-seul-lecteur.md)).
- **Le contrat du référentiel a été relu par plusieurs modèles**, pour en
  trouver les failles, sans leur demander de certifier des faits.
- **La revue visuelle de l'audit des photos** a été faite par un agent sur des
  planches de contact ; chaque correction a été confirmée par une personne
  ([audit des photos](AUDIT-PHOTOS.md)).
- **Les skills** (`skills/`) sont des procédures d'exploitation versionnées
  pour les agents qui travaillent sur la collection.
- **Les tests** n'appellent aucun modèle : lecteurs et services sont injectés,
  ce qui rend chaque règle testable sans réseau.
