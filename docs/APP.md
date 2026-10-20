# Guide de l'application de gestion

> **Pour qui :** l'équipe qui gère et vend une collection (administration, gestion, consultation).
> **Vous y trouverez :** comment installer et ouvrir l'application, créer les comptes, l'utiliser depuis un téléphone, puis chaque tâche dans l'ordre où vous la rencontrez.
> **Statut :** en vigueur. Les options de chaque commande sont dans la [référence des commandes](COMMANDES.md).

La gestion est la partie privée de Lilydex. Vous y tenez l'inventaire de votre
collection, [exemplaire](GLOSSAIRE.md#les-cartes) par exemplaire : photos,
identité, variante, état, prix et ventes. La partie publique du site, la
vitrine, est décrite plus bas ([Publier en vitrine](#publier-en-vitrine)) et
dans ses [règles détaillées](CATALOGUE.md).

Vos cartes peuvent être en plusieurs langues ; l'interface et ce guide sont en
français. L'application est un serveur web écrit en Python (FastAPI) ; toutes
vos données tiennent dans une base SQLite et un dossier de photos, sur la
machine qui l'héberge. Consulter, corriger et suivre les ventes ne demande
aucun service extérieur. Les actions qui en appellent un, comme la lecture
d'une photo par Gemini ou le relevé d'un prix sur TCGdex, le signalent.

Les mots propres à Lilydex sont définis dans le [glossaire](GLOSSAIRE.md).

## Ce que vous pouvez faire

- **Démarrer** : installer, créer le compte administrateur, ouvrir l'accès à
  l'équipe ou à votre téléphone. → [Démarrer](#démarrer)
- **Saisir des cartes**, une à une ou en série, avec photo et lecture
  automatique, ou à la main. → [Saisir des cartes](#saisir-des-cartes)
- **Vérifier une carte** : identité, variante, tampon, langue, édition, état.
  → [Vérifier une carte](#vérifier-une-carte)
- **Relever les prix** et estimer un prix de vente.
  → [Relever les prix](#relever-les-prix)
- **Vendre** : lots, brouillons d'annonce, vitrine publique, demandes des
  clients. L'application n'encaisse rien et ne publie aucune annonce d'elle-même.
  → [Vendre](#vendre)
- **Consulter la collection** : recherche, filtres, tri par classeur,
  visionneuse, clavier. → [Consulter la collection](#consulter-la-collection)
- **Importer et exporter** : classeurs numérisés, CSV, JSON, page HTML
  autonome. → [Importer et exporter vos données](#importer-et-exporter-vos-données)
- **Sauvegarder et restaurer.** → [Sauvegarder](#sauvegarder)
- **Déléguer un album à un agent IA**, qui ne prépare que des brouillons de
  lots. → [Pilote agent](AGENT_CONTROL.md)

## Démarrer

### Installer et lancer l'application

Il vous faut Python 3.10 ou plus récent et [uv](https://docs.astral.sh/uv/).
Lancez les commandes à la racine du dépôt.

```bash
uv sync --extra web --extra dev
uv run --extra web pokeprice-manage serve
```

La première commande installe l'application (`web`) et les outils de test
(`dev`, inutiles pour un simple usage) ; la seconde démarre le serveur. Ouvrez
<http://127.0.0.1:3820/gestion>. L'adresse racine affiche la vitrine publique.

Sur un clone neuf, la collection est vide : le premier lancement crée le
dossier de données et une base vide. Remplissez-la en
[saisissant vos cartes](#saisir-des-cartes) ou en
[important des classeurs numérisés](#numériser-et-importer-un-classeur).

Par défaut, le serveur n'écoute que sur votre ordinateur (`127.0.0.1`) : aucun
autre appareil ne peut l'ouvrir. Le port 3820 se change avec `--port`.

> **Où lancer les commandes**
>
> - **Installation sur votre ordinateur :** à la racine du dépôt, précédez
>   chaque commande `pokeprice-manage` de `uv run --extra web`.
> - **Collection hébergée sur un serveur :** la base du serveur fait foi.
>   Lancez sur le serveur toute commande qui lit ou modifie la collection, sous
>   la forme décrite dans
>   [Héberger Lilydex](DEPLOYMENT.md#lancer-une-commande-sur-le-serveur), avec
>   `--data /srv/pokeprice/inventory`. Une base restée sur votre ordinateur est
>   une ancienne copie : n'y écrivez rien.
> - **Sans `--data`,** une commande vise `data/inventory/` dans le dossier
>   courant, et y crée une base vide s'il n'en existe pas.

### Créer le compte administrateur

Au premier accès, la page vous demande de créer le compte administrateur :
un nom et un mot de passe d'au moins 10 caractères. Lilydex ne livre aucun
compte ni mot de passe par défaut. Vous pouvez aussi créer ce compte dans un
terminal ; la commande demande le mot de passe sans l'afficher :

```bash
uv run --extra web pokeprice-manage user <nom> --role admin
```

### Donner un accès à l'équipe

Chaque personne a son propre compte, avec l'un de ces rôles :

| Rôle | Ce qu'il permet |
|---|---|
| Consultation (`reader`) | Consulter la collection et l'exporter |
| Gestion (`editor`) | En plus : corriger les fiches, publier, gérer les lots et les ventes |
| Administration (`admin`) | En plus : gérer les comptes, les clients de la vitrine, les sauvegardes, supprimer un exemplaire |

L'administrateur ajoute un compte dans l'onglet **Gestion**, panneau « Donner
un accès », ou avec la commande `user` et `--role editor` ou `--role reader`.
Pour retirer un accès, décochez « Compte actif » puis cliquez sur « Modifier
l'accès ». Changer le rôle d'un compte ou le désactiver ferme ses sessions. Le
dernier administrateur actif ne peut être ni désactivé ni rétrogradé.

### Utiliser votre téléphone sur le même Wi-Fi

Pour consulter ou saisir des cartes depuis votre téléphone sans héberger
l'application, faites écouter le serveur sur votre réseau Wi-Fi :

1. Créez d'abord le compte administrateur, dans le terminal ou par le premier
   accès sur `127.0.0.1`. Ouvert au réseau, le serveur refuse de démarrer sans
   administrateur actif : sinon, le premier appareil du réseau à ouvrir la page
   deviendrait administrateur.
2. Relancez le serveur sur l'adresse IPv4 de votre ordinateur sur le Wi-Fi
   (par exemple `192.168.1.20`, visible dans les paramètres Wi-Fi) :

   ```bash
   uv run --extra web pokeprice-manage serve --host <adresse-wifi>
   ```

3. Sur le téléphone, ouvrez `http://<adresse-wifi>:3820/gestion`.

Deux limites : l'adresse de l'ordinateur peut changer quand le routeur en
attribue une nouvelle (DHCP) ; la connexion passe en HTTP, sans chiffrement,
et le navigateur refuse alors l'aperçu de la caméra (voir
[Saisir des cartes](#prendre-ou-téléverser-une-photo)). Pour un accès chiffré
depuis n'importe où, hébergez Lilydex sur un serveur : voir
[Héberger Lilydex](DEPLOYMENT.md).

### Clé Gemini (facultative)

La lecture des photos passe par Gemini, un modèle vision-langage de Google
(`gemini-3.8-flash`). Elle demande une clé `GEMINI_API_KEY` (ou
`GOOGLE_API_KEY`), lue dans le fichier `.env` de votre dossier personnel ou du
dossier de lancement ; Git ignore ces fichiers. La clé reste sur le serveur,
jamais dans le navigateur, et les appels utilisent le compte API configuré.
Sans clé, la lecture échoue avec un message clair : vous saisissez l'identité à
la main, et le reste de l'application fonctionne. Sur un serveur hébergé, la
clé se place dans le fichier d'environnement du service.

### Où sont vos données

Toute la collection tient dans un dossier, `data/inventory/` par défaut, que
Git ignore :

| Élément | Contenu |
|---|---|
| `collection.sqlite3` | La base : fiches, historique, prix, ventes et comptes |
| `photos/` | Les photos de chaque exemplaire, nommées par leur empreinte SHA-256 |
| `reference_documents/` | Les pièces justificatives du référentiel, rangées par empreinte |
| `references/` | Le cache du contrôle par l'image (images TCGdex, vecteurs) ; il se recalcule |
| `thumbnails/` | Les vignettes de la grille ; elles se recalculent |

Pour utiliser un autre dossier, placez `--data` avant la commande :
`pokeprice-manage --data <dossier> <commande>`. Déplacez toujours le dossier
entier, jamais la base seule. Le dossier `backups/`, à côté, reçoit les
sauvegardes et les copies faites avant une migration.

### Mettre à jour l'application

Une nouvelle version du code peut faire évoluer la structure de la base. Quand
le serveur ou une commande ouvre une base plus ancienne que le code :

1. Lilydex copie d'abord la base telle quelle dans
   `backups/before-schemaN-fromM-<date>.sqlite3` (un fichier SQLite privé, dont
   l'intégrité est vérifiée) ;
2. puis migre la base vers la version attendue.

Si la copie échoue, la base n'est pas migrée et l'application ne démarre pas.
Une base plus récente que le code est refusée. Toute commande qui ouvre la
base, y compris `backup`, déclenche la migration. La copie ne contient pas les
photos (aucune migration ne les modifie) et n'est jamais supprimée par la
rotation des sauvegardes. Faites une [sauvegarde complète](#sauvegarder) avant
de lancer une nouvelle version.

## Saisir des cartes

### Ajouter une carte

Ouvrez **Collection → Ajouter une carte**. Vous pouvez tout saisir à la main,
sans photo, ou partir d'une photo :

1. **Prenez ou téléversez la photo du recto** (voir ci-dessous). Le recto
   entier et ses deux coins inférieurs doivent être lisibles.
2. **Préparez-la** si besoin : l'aperçu propose recadrage, redressement et
   balance des couleurs (voir [Préparer la photo](#préparer-la-photo)).
3. **Cliquez sur Lire la carte.** Gemini propose le nom imprimé, la référence,
   la langue, les PV et le texte d'un éventuel tampon ; l'application cherche
   l'extension dans TCGdex, sans chercher de prix. Une photo dont le recto
   n'est pas lisible est refusée : reprenez-la.
4. **Choisissez une édition proposée.** La comparaison montre **Votre
   exemplaire** et **Carte du catalogue** côte à côte, avec un zoom
   indépendant jusqu'à 400 %. Comparez l'illustration, puis cochez la
   confirmation. Sans elle, l'exemplaire reste **à vérifier**.
5. **Enregistrez.** La photo et l'identité sont enregistrées ensemble. La fiche
   propose ensuite d'ajouter le verso.

Si la lecture échoue, saisissez le nom, la référence complète et la langue,
puis cliquez sur **Rechercher l'extension**. Une extension inconnue peut rester
vide.

Pour une carte déjà en stock, ouvrez sa fiche puis **Identifier la carte** :
l'opération complète cet exemplaire sans en créer un autre ; son emplacement,
sa photo, son stock, ses notes et son état physique sont conservés. Une
modification concurrente de la fiche oblige à reprendre la préparation.

La lecture, les recherches dans le catalogue et la confirmation sont gardées
dans la provenance et l'historique. L'état physique et le prix restent à part :
ce parcours n'enregistre ni estimation d'état ni prix.

### Prendre ou téléverser une photo

**Prendre une photo** ouvre la capture native sur Android et iPhone. Sur
ordinateur, le bouton demande l'accès à la caméra et en affiche l'aperçu ;
choisissez la caméra s'il y en a plusieurs, puis **Capturer la photo**. Fermer
ce dialogue coupe la caméra. Une capture passe par l'aperçu habituel avant tout
enregistrement.

Le navigateur n'autorise l'aperçu de la caméra qu'en HTTPS ou sur
`localhost` : depuis une adresse Wi-Fi en HTTP, utilisez le téléversement. Un
refus de permission ou l'absence de caméra laisse le téléversement accessible.
Les mêmes choix servent, sur la fiche, à remplacer une photo.

Sur ordinateur, l'aperçu affiche une **mire de cadrage** au format carte. Un
téléphone peut servir de webcam : relayée par `scrcpy --capture-orientation=90`,
sa caméra garde sa résolution native, y compris en portrait, sans recadrage du
navigateur.

Les photos acceptées sont en JPEG, PNG ou WebP, jusqu'à 8 Mo et
24 mégapixels.

### Préparer la photo

L'aperçu propose trois réglages, calculés sur le serveur sans appel à Gemini :

- **Recadrage automatique.** La détection vise une carte verticale entière sur
  un fond uni, ou un cadre jaune continu même sur un fond texturé. Si les
  contours sont ambigus, coupés, multiples ou trop inclinés, la photo reste
  entière. Une marge garde les bords.
- **Redressement de la perspective**, à partir des quatre coins et du format
  d'une carte Pokémon. Il accompagne le recadrage : désactiver le recadrage
  désactive aussi le redressement.
- **Balance des couleurs**, appuyée sur les zones claires presque neutres et
  limitée à ±8 % par canal, sans saturation, lissage ni retouche des défauts.
  Elle ne corrige ni les reflets ni le flou.

Avec la mire, la capture transmet sa position (`X-Card-Guide`). Les contours
trouvés sur l'image entière restent prioritaires ; sinon, la détection reprend
dans la zone de la mire, ce qui tolère un tapis texturé et permet de redresser
un verso bleu ; en dernier recours, le recadrage suit la mire avec 6 % de
marge, sans redressement. La provenance indique `crop_source` (`contours`,
`contours-in-guide` ou `guide`). Les téléversements et la capture native
Android n'ont pas de mire.

Désactiver les trois réglages redonne exactement la photo d'entrée normalisée :
le JPEG orienté, limité à 1 600 pixels et débarrassé de ses métadonnées. Cette
version entière et la version préparée sont gardées sous des empreintes
distinctes, avec les réglages dans la provenance et dans les sauvegardes ; le
fichier du téléphone reste intact. Modifier un réglage annule la lecture et le
choix d'édition : relisez ou recherchez avant de confirmer.

Les préparations en cours sont privées et expirent au bout de 30 minutes ;
elles ne constituent pas du stock et n'entrent pas dans les sauvegardes.

### Saisir en série

**Collection → Saisie en série** enchaîne les cartes d'un classeur : vous
choisissez l'album, la page, la pochette et le format de page (9 pochettes par
défaut), prenez ou importez le recto et éventuellement le verso, vérifiez les
champs, puis **Enregistrer et passer à la suivante** crée un seul exemplaire et
propose la pochette suivante ; après la dernière, la page suivante.

- Les champs et photos non validés sont gardés 30 jours : un rafraîchissement,
  une fermeture ou un redémarrage permettent de reprendre la série.
  **Mettre en pause** garde le brouillon ; **terminer la série** libère ses
  préparations.
- La lecture Gemini se lance à la demande.
- Une même photo de recto, ou un emplacement déjà occupé, déclenche une
  alerte : ouvrez la fiche existante, ou confirmez qu'il s'agit d'un exemplaire
  physique distinct. Les alertes sont revérifiées à l'écriture ; un double
  appui ou une réponse perdue ne crée pas une deuxième carte.

### Lecture et contrôles automatiques après la saisie

Avec `pokeprice-manage serve`, chaque nouvel exemplaire enregistré avec une
photo du recto, à l'unité ou en série, est lu une fois juste après
l'enregistrement, sans retarder la saisie : lecture de la finition, du tampon
et de la langue, puis contrôle de l'édition par l'image si l'édition est
confirmée et l'option vision installée. L'historique indique « lancée
automatiquement à la saisie ». En cas d'échec (Gemini indisponible, photo
refusée), l'historique le note et la lecture reste possible depuis la fiche.
L'identification d'un exemplaire déjà en stock et le remplacement d'une photo
ne déclenchent rien. `serve --no-auto-checks` coupe ces lectures : rien ne part
vers Gemini sans action explicite.

### Préparer les photos d'une sélection

Cochez jusqu'à 20 exemplaires puis **Préparer les photos sélectionnées** :
simulez les réglages du recto ou du verso, agrandissez les comparaisons et
cochez les résultats voulus. L'application crée une sauvegarde avant de
remplacer les photos. **Annuler ce traitement**, et les vingt derniers
traitements, se retrouvent dans **Photos par lot**, même sans carte
sélectionnée ; une fiche modifiée depuis le traitement bloque son annulation.
Sans photo originale conservée, la simulation signale qu'elle part de l'image
actuelle. Aucun modèle ni service de prix n'est appelé.

## Vérifier une carte

Chaque vérification est une décision humaine, enregistrée avec son auteur, sa
date et son motif par le serveur. Les modèles ne font que proposer
([IA et vision](IA-VISION.md)).

### Corriger une fiche

Vous pouvez corriger le nom, l'extension, la référence, l'identifiant du
catalogue, la langue, les PV, la variante, l'état, les notes et l'emplacement.
Chaque correction garde son auteur, sa date, son motif et les anciennes
valeurs. Les états importés restent à confirmer.

### La variante : Standard ou Foil

La variante choisit la série de prix Cardmarket d'un exemplaire :

- **Standard** : la version normale de l'édition, mate ou holo d'origine. Une
  Rare Holo imprimée holo d'origine reste Standard : Cardmarket et TCGdex
  donnent son prix en tendance normale et rangent sous « holo » celui de sa
  reverse.
- **Foil** : une version qui brille davantage que la version standard :
  reverse (fond holographique hors de l'illustration, illustration mate) ou
  holo tamponnée d'une carte normalement mate, que Cardmarket range avec les
  Foil.

Le symbole de rareté ne suffit pas à trancher ; la fiche indique la version
standard selon TCGdex, dont les variantes sont parfois incomplètes. Le pipeline
d'albums marque Foil toute carte brillante ; une alerte signale les cartes Foil
dont TCGdex ne connaît pas de reverse.

La fiche sépare la **finition observée sur la carte** (mate, holo, holo avec
cadre brillant, reverse, spéciale) et la **catégorie de prix calculée**. Le
serveur déduit la catégorie de la finition, du tampon et des données de
l'édition : mate → Standard ; fond reverse → Foil ; holo d'origine →
Standard ; illustration holo d'une édition mate avec reverse connue → Foil. Le
menu calculé est verrouillé dans la fiche. Cas particuliers :

- Une édition qui a explicitement une impression mate et une impression holo
  parallèle, avec deux tarifs et sans reverse : « Holo dans l'illustration »
  donne Foil, qui désigne alors l'impression parallèle (Manaphy 2/17 POP
  Série 9).
- Des tarifs qui décrivent une holo d'origine et une reverse, sans impression
  mate, complètent un catalogue incomplet : Baggaïd 74/99 Destinées Futures est
  Standard pour l'illustration holo, Foil pour la reverse, conformément à la
  [liste officielle](https://assets.pokemon.com/assets/cms2/pdf/trading-card-game/checklist/bw4_web_cardlist_en.pdf).
- Une Prime comme Roigada 85/90 Indomptable a un cadre holo d'origine : « Holo
  avec cadre brillant », Standard. La
  [liste officielle](https://assets.pokemon.com/assets/cms2/pdf/trading-card-game/checklist/hgss3_web_cardlist_en.pdf)
  la classe parmi les Prime ; les numéros 81 à 90 n'existent qu'en version
  brillante.
- EX Fantômes Holon, numéros 18 à 98 : une illustration holo avec le tampon de
  l'extension est la parallèle vendue comme reverse ou Foil, malgré son fond
  mat (Pikachu 78/110) ; la
  [liste officielle](https://assets.pokemon.com/assets/cms/pdf/tcg/checklists/holonphantoms_checklist.pdf)
  donne deux impressions. Même règle pour EX Gardiens de Cristal, numéros 14 à
  88 tamponnés ([liste](https://assets.pokemon.com/assets/cms/pdf/tcg/checklists/crystalguardians_checklist.pdf)),
  et EX Deoxys, numéros 16 à 95 (Barboach 54/107 en italien ;
  [tableau](https://assets.pokemon.com/assets/cms/pdf/tcg/checklists/deoxys_checklist.pdf)).

Une catégorie encore indéterminée est étiquetée « Catégorie enregistrée · à
vérifier ». Si le catalogue est incomplet ou admet plusieurs impressions, la
fiche garde une sélection manuelle et demande de préciser le produit dans les
observations ; le prix reste exclu des totaux tant que la catégorie n'est pas
déterminée. Pour une holo saisie sans données locales de finition, ces données
sont récupérées et mises en cache, même sans prix Cardmarket (Celebi Promo
Nintendo 029 : holo d'origine, Standard) ; cela ne modifie ni l'exemplaire, ni
sa confirmation, ni son prix.

Une ancienne combinaison incohérente garde ses observations physiques, mais son
prix est exclu des totaux et un motif demande d'appliquer la catégorie
calculée. Un enregistrement ou un nouveau relevé corrige alors la catégorie,
avec historique et version attendue, en gardant la date et l'auteur de
l'observation physique si elle n'a pas changé. Une ancienne correction de
catégorie sans finition observée revient dans « À examiner », sans être
présumée erronée. L'audit en lecture seule `python scripts/audit_variant_categories.py`
liste les catégories incohérentes, les observations ambiguës et ces
corrections à reprendre.

### Le tampon

Le champ **Tampon sur l'illustration** garde le texte d'un logo ou d'un tampon
imprimé sur l'image, par exemple « EX Fantômes Holon ». L'état du tampon se
note « non examiné », « absence constatée » ou « présent », avec son texte
original et une autre marque de distribution facultative. **Lire la carte** le
propose quand Gemini le voit (21 sur 21 au [banc d'essai](BANC-RECONNAISSANCE.md)) ;
la saisie doit être confirmée. Le tampon apparaît sur la carte, dans la
recherche, dans le filtre **Variante → Tamponnées**, dans les exports et les
dossiers d'annonce. Modifier le tampon change la variante : le prix de
référence est retiré et doit être relevé. Cardmarket range ces promos avec les
Foil, mêlées aux reverses : seules les offres dont le commentaire mentionne le
tampon sont comparables.

### Confirmer la variante sur la carte physique

Cochez **Variante et tampon vérifiés sur la carte physique** : le contrôle se
clôt, même si la catégorie reste identique ; la date et l'auteur sont
enregistrés par le serveur. Une divergence avec le catalogue reste une
information et ne remet pas la carte dans « Foil à vérifier ». Une correction
d'identité, de variante manuelle, de tampon, de finition ou du recto exige une
nouvelle confirmation ; un relevé de prix la conserve. Les anciens imports et
corrections ne sont jamais déclarés vérifiés automatiquement, et un relevé ne
crée jamais de confirmation humaine. Les observations partielles restent
enregistrables sans catalogue ni prix.

**Variante → Foil à vérifier** retient les cartes Foil dont le dernier relevé
signale que TCGdex ne connaît pas de reverse (à partir de 2 €) et dont la
variante n'est pas confirmée ; elles portent le badge « ⚠ Variante à
vérifier ». Parcours conseillé : filtre Foil, **Sélectionner les cartes
affichées**, **Relever les prix** ; puis filtre Foil à vérifier, examen des
photos et **Changer la variante** sur la sélection. Chaque carte reçoit sa
correction avec le motif saisi, puis un nouveau relevé ; une carte déjà dans la
variante choisie reste inchangée. `&limit=200` dans l'adresse affiche jusqu'à
200 cartes par page.

### Lire la finition sur la photo

Dans la fiche, **Lire la finition** transmet la photo du recto à Gemini, qui
répond à quatre questions : illustration holo ou mate, fond brillant hors de
l'illustration (reverse), texte d'un tampon, langue du texte imprimé hors nom
(attaques, talents, description). La lecture est enregistrée avec la photo lue,
le modèle, la version du protocole et les jetons consommés. Elle ne modifie ni
la fiche ni le prix.

La fiche en tire une **proposition**, recalculée à chaque ouverture avec la
règle de catégorie :

- illustration holo → Standard ou Foil selon l'édition et le tampon ;
- illustration mate → Standard, **sauf** si une reverse est possible et que sa
  version Foil vaut au moins le seuil de valeur ou n'a pas de prix connu : la
  proposition devient « Examen physique requis ». Aucun modèle ne distingue
  sûrement une reverse sur une photo de classeur ;
- fond brillant signalé → reverse possible, à examiner sous un éclairage
  rasant ;
- photo insuffisante → aucune proposition.

Un tampon déjà observé par une personne, présent ou absent, prime sur le tampon
lu. **Enregistrer la finition retenue** applique votre choix (finition, tampon
et, si vous avez la carte en main, la confirmation de la variante) ; la lecture
et la proposition sont jointes à l'historique comme preuves. Une lecture
devient obsolète dès que la photo du recto change.

Une lecture en désaccord avec la fiche (illustration holo contre fiche mate ou
reverse, tampon contraire) place la carte dans « À examiner », même sous le
seuil, jusqu'à une confirmation physique postérieure à cette lecture.

**Langue du texte.** Si la langue lue diffère de celle de la fiche, la carte
entre dans « À examiner ». Corrigez la langue de la fiche, ou cliquez sur
**Garder la langue de la fiche** pour cette lecture, avec un motif inscrit à
l'historique. Une langue non lue (texte illisible, énergie de base) ne
déclenche rien. Ce contrôle vise surtout les noms identiques d'une langue à
l'autre (Pikachu), que la recherche du catalogue, stricte sur la langue, ne
départage pas. Ce n'est pas un second avis indépendant : c'est le même modèle,
dans un autre appel.

**Non-régression.** Le banc d'essai rejoue ces lectures à travers
l'application ; il échoue si une mesure passe sous son seuil, ou si une
proposition contredit une variante confirmée dont la version Foil atteint le
seuil ou n'a pas de prix connu. Voir le [banc d'essai](BANC-RECONNAISSANCE.md).

### Contrôler l'édition par l'image

Dans la fiche, **Comparer aux images TCGdex** compare la photo du recto aux
images de toutes les impressions de même nom, dans la langue de la carte et en
anglais. Le calcul se fait sur le serveur avec DINOv2, sans lire le texte :
c'est un contrôle indépendant de la lecture qui a proposé l'édition. Il est
enregistré comme une lecture et ne modifie pas la fiche.

- **Édition confirmée** : l'édition de la fiche est la plus proche.
- **Image indécise** : une autre impression devance de moins de 0,05 ; c'est
  le cas des réimpressions à l'illustration identique (dresseurs, Base Set 2).
- **Désaccord** : une autre impression devance d'au moins 0,05 ; la carte
  entre dans « À examiner ». **Garder l'édition de la fiche** après examen la
  retire de la file ; pour corriger, passez par l'identification : le contrôle
  est recalculé contre la nouvelle édition.

Sans image TCGdex de l'édition (promos McDonald's), le contrôle est impossible.
Il demande l'option vision :

```bash
uv sync --extra web --extra vision
```

Le modèle `facebook/dinov2-small` (environ 85 Mo) est téléchargé au premier
usage ; `HF_HOME` permet de réutiliser un cache existant. Sans l'option,
l'application affiche « Contrôle indisponible sur ce serveur ».

### Le verso et l'état

La fiche affiche **Recto** et **Verso**, chacun avec capture, téléversement,
préparation et agrandissement. Ajouter le verso garde l'identifiant, le stock
et l'identité du recto : il ne crée pas une deuxième carte.

**Évaluer l'état** transmet à Gemini les photos entières disponibles, avant
les corrections locales quand elles sont conservées. Pour une photo ancienne,
une preuve de préparation qui correspond à la photo courante permet de
retrouver l'original ; sinon, cette limite est signalée. Téléverser une photo
n'envoie rien : l'évaluation ne part que si vous la demandez.

La proposition décrit les défauts du recto et du verso, la qualité des photos
et les limites de l'examen ; elle peut être **indéterminable**. Un état NM
exige deux faces exploitables et les versions avant correction ; un verso
absent laisse une évaluation partielle. La proposition ne remplace pas l'état
enregistré et ne modifie aucun prix.

Pour retenir un état, choisissez **État retenu après examen**, confirmez
l'examen de la carte en main et cliquez sur **Enregistrer l'état vérifié**.
Vous pouvez retenir un autre état que celui proposé ; le lien à l'évaluation et
votre motif sont gardés dans l'historique. Si une photo a changé, la
proposition est obsolète et il faut évaluer de nouveau. Le protocole et ses
protections sont dans l'[aide à l'état](CONDITION-ASSESSMENT.md).

### Le référentiel des impressions

L'ajout et la correction enregistrent les observations dont le
[référentiel](PRINT_REFERENCE_GUIDE.md) a besoin : finition observée, état du
tampon, son texte original, une autre marque de distribution. Le filtre
**Examen → Référentiel à compléter** montre les lacunes du référentiel, à part
de l'examen physique ; il garde son état dans l'adresse, fonctionne dans les
vues par exemplaire et par édition, et respecte le tri Classeur. La fiche et
son aperçu montrent l'état de la correspondance marchande.

Le référentiel est en mode audit : il ne certifie pas les références
existantes et ne remplace pas le calcul de prix hérité
([fiche 0011](decisions/0011-referentiel-mode-audit.md)).

```bash
uv run --extra web pokeprice-manage reference-audit > outputs/reference-audit.json
```

Cet audit ouvre la base en lecture seule, sans migration, réseau ni
correction. Il distingue les références héritées non liées, les références
manuelles, les prix absents et les besoins de couverture par édition et
langue. Le sous-total vérifié reste inconnu tant qu'aucune cotation liée n'est
vérifiée.

Pour ranger une pièce justificative, puis vérifier les cotations après une
mise à jour des règles :

```bash
uv run --extra web pokeprice-manage reference-archive capture.html
uv run --extra web pokeprice-manage reference-recheck
uv run --extra web pokeprice-manage reference-recheck --apply
```

`reference-archive` range la pièce sous son empreinte SHA-256.
`reference-recheck` liste les cotations liées devenues incompatibles ;
`--apply` inscrit leur suspension au journal. Une suspension ne se lève que par
une restauration explicite.

Les sauvegardes emportent les règles et moteurs enregistrés avec les
décisions, les cotations liées et leurs événements, et les pièces rangées une
fois chacune dans `reference_documents/` (PDF, JSON ou HTML). Une pièce
manquante ou altérée est signalée ; aucun téléchargement automatique ne
rétablit son statut de preuve. Détails et limites :
[état de la mise en œuvre](PRINT_REFERENCE_IMPLEMENTATION.md).

### Repérer les cartes à examiner

Le filtre **Examen → À examiner** retient les contrôles qui restent à faire :
identité incertaine, variante ou tampon à examiner sur les cartes de valeur,
divergences avec le catalogue, désaccords des lectures, état non validé, prix
prudent incomplet ou à actualiser. Le **seuil de valeur** vaut 10 € par défaut
et reste dans l'adresse avec le filtre et le tri Classeur. Les badges et les
fiches précisent les motifs et la valeur en jeu : le plus haut prix prudent
parmi les variantes et éditions encore plausibles.

Une carte de valeur dont l'examen physique et le prix prudent sont complets
quitte la file et garde le badge « Carte de valeur ». Après confirmation de la
variante, la valeur en jeu exclut les variantes écartées. L'instabilité du
marché reste une information de prix. Règles détaillées et commande de
réception : [valeur en jeu](VALUATION.md).

## Relever les prix

### Relever le prix d'une carte

Sur la fiche d'une carte confirmée avec son édition TCGdex, **Relever le prix
(TCGdex)** enregistre un relevé daté : prix bas, moyennes sur 1, 7 et 30 jours
et tendance Cardmarket de la variante de l'exemplaire (normale, ou holo et
reverse si la carte est Foil). La tendance devient le **prix de référence**
(`TCGdex · Cardmarket trend` ou `trend-holo`), avec sa date ; le relevé complet
reste dans l'historique. Un relevé identique au précédent n'ajoute rien. Une
carte à vérifier ou sans édition n'est pas relevée.

À partir de 2 €, des alertes signalent une variante inconnue de TCGdex, un
écart d'au moins ×3 avec l'autre variante, des moyennes divergentes ou un prix
bas très inférieur à la tendance. En dessous, la carte relève du vrac vendu en
lot.

Pour plusieurs cartes, cochez-les puis **Relever les prix (n)** dans la barre
de sélection ; le nombre compte les cartes confirmées avec édition, les autres
sont ignorées. Chaque carte est relevée séparément : un échec n'arrête pas les
suivantes. Le bilan donne les prix relevés, les cartes ignorées, les échecs et
les alertes. En ligne de commande, `pokeprice-manage prices` relève toutes les
identités confirmées (`--album <id>`, `--only-missing`, `--actor`).

### Ce que devient le prix

- Le prix de référence est une tendance, pas un prix de vente. Il n'est
  jamais décoté selon l'état.
- Un prix indisponible reste vide, jamais zéro.
- Une correction d'identité ou de variante efface la référence courante,
  devenue incertaine ; les anciens relevés restent dans l'historique.
- Préciser une finition compatible avec l'identité, le tampon et la catégorie
  déjà cotés conserve la référence, sa source et sa date. Une catégorie
  modifiée ou encore ambiguë exige un nouveau relevé.
- Pour une carte sans cote TCGdex, un prix saisi à la main tient lieu de
  référence ; la fiche affiche cette référence manuelle datée, même sans relevé
  détaillé.

`pokeprice-manage repair-prices` audite les références perdues, par le passé,
lors d'une précision compatible de finition. Après une sauvegarde, `--apply`
restaure seulement les cotations sourcées et datées du plan, avec contrôle de
version et l'auteur fixe `system:price-recovery` ; `--copy-id` limite les
exemplaires. Les confirmations humaines sont conservées, et aucun prix présent
ou supprimé volontairement n'est remplacé.

### Noms dans plusieurs langues

La recherche trouve une carte par son nom dans six langues (français,
anglais, allemand, italien, espagnol, portugais) : « Dracaufeu » ou « Glurak »
trouvent un Charizard anglais. `pokeprice-manage names` récupère ces noms une
fois par édition ; `prices` l'appelle à la fin de chaque relevé, sans requête
pour les éditions déjà connues. Une édition absente d'une langue reçoit le nom
du Pokémon, retrouvé par son numéro de Pokédex.

Pour ménager TCGdex : une requête par extension et par langue (elle donne
toutes les cartes de l'extension, gardées pour les classeurs à venir), une à la
fois avec 0,25 s de pause ; réponses mises en cache, absences comprises
(redemandées au bout de 90 jours) ; nouvel essai avec attente croissante et
respect de `Retry-After` sur les erreurs 429 et 5xx ; arrêt après cinq échecs
serveur consécutifs.

### Estimer le prix de vente depuis Cardmarket

L'API Cardmarket n'accepte plus de nouvelles inscriptions, et Lilydex ne
collecte pas ses pages automatiquement. Dans la fiche, ouvrez **Voir les offres
Cardmarket**, sélectionnez toute la page (Ctrl+A), copiez, puis collez dans
**Estimer le prix de vente depuis Cardmarket**. Le serveur repère chaque offre
(état, commentaire, prix) et ignore les prix d'en-tête. La règle :

- au moins une offre au même état : prix de marché = médiane de ces offres,
  fourchette du premier au troisième quartile dès quatre offres ; confiance
  bonne à partir de cinq offres, moyenne de deux à quatre. Les offres les moins
  chères ne fixent pas le prix ;
- sinon : médiane de l'état le plus proche, avec une décote de 0,75 par cran
  d'état, hypothèse par défaut à calibrer sur les ventes ; confiance faible ;
- carte tamponnée : seules les offres dont le commentaire mentionne un tampon
  (« stamp », « tampon », « logo ») sont retenues ;
- alerte si moins de trois offres comparables, ou si le texte collé ne nomme
  pas la carte.

Ce sont des prix demandés, pas des ventes ; frais et port restent à déduire.
L'estimation est enregistrée dans l'historique avec les offres, sans modifier la
carte ni son prix de référence ; la plus récente s'affiche.

**Voir les offres Cardmarket** ouvre la page du produit filtrée sur la langue
de l'exemplaire, son état ou mieux (`minCondition`) et, pour une carte Foil,
les reverses seulement (`isReverseHolo=Y`). Les offres sont triées par prix :
comparez celles du même état.

### Les totaux de la collection

La collection et les résultats filtrés affichent **Tendance**, **Valeur
prudente** (le plus bas entre la tendance et la moyenne à 30 jours, sans
décote d'état) et **Estimation de vente**, avec le nombre d'exemplaires
couverts. Les prix absents restent inconnus. Une estimation ancienne, après une
correction d'identité, de variante ou d'état, reste visible dans la fiche mais
sort des totaux. Le prix prudent du catalogue n'est pas une estimation de vente
pour l'état PO ni pour une langue donnée.

## Vendre

### Constituer un lot

Depuis **Collection** ou **Ventes**, cliquez sur **Créer un lot**. Cochez les
exemplaires disponibles, ou **Ajouter les cartes affichées** pour la page
courante. La sélection est gardée entre les recherches, les albums et les
pages ; chaque carte peut être retirée du récapitulatif. Deux exemplaires d'une
même édition restent distincts par leur emplacement. **Désélectionner tout**
vide la sélection sans supprimer aucun exemplaire.

**Continuer**, vérifiez le contenu, puis donnez un titre et un prix envisagé ;
les objectifs de prix, le canal et les notes sont facultatifs. **Enregistrer le
lot en brouillon** ouvre le lot dans **Ventes**. Les cartes restent disponibles
jusqu'à **Réserver les cartes**. Un compte de consultation ne peut pas créer de
lot.

### Suivre un lot

Un lot passe du brouillon à la réservation, la vente, le paiement déclaré,
l'expédition et la clôture, ou à l'annulation et au retour. La réservation est
transactionnelle : une réservation concurrente du même exemplaire échoue. Prix
affiché, prix cible, prix minimum et prix convenu sont distincts ; frais, port,
emballage et remboursements se saisissent en euros. **Ventes** filtre les lots
par statut et masque les annulés par défaut.

- Les montants sont stockés en centimes. Le net vaut : prix + port facturé −
  frais − coût du port − emballage − remboursements.
- Le paiement est déclaré à la main : l'application ne prend ni n'effectue
  aucun paiement.
- Un retour réintègre les cartes et remet leur état à confirmer ; enregistrez
  à part le montant réellement remboursé.

### Préparer une annonce

Dans **Ventes**, chaque lot propose **Télécharger le brouillon d'annonce** : un
dossier ZIP avec un texte modifiable, les photos recto et verso et les
informations à compléter. Les notes privées et les détails financiers sont
exclus. Le téléchargement ne change pas le stock. Le prix demandé du lot est
repris s'il existe ; un état non confirmé est indiqué « à vérifier ». Aucune
annonce n'est publiée automatiquement sur une plateforme.

### Publier en vitrine

La vitrine publique est la page d'accueil du site, visible sans compte ; la
gestion est sous `/gestion`, avec la même connexion. Les anciens liens de
gestion (`/?view=…`) et `/vitrine` sont redirigés ; un lien discret « Espace
vendeur » mène à la gestion, et un compte de l'équipe qui se connecte sur la
vitrine y est renvoyé.

La fiche d'un exemplaire affiche, sous le prix, un bloc **Vitrine**. Le **prix
de vitrine proposé** est le premier disponible dans cet ordre :

1. le prix que vous saisissez en publiant ;
2. si l'état est confirmé, l'estimation sur les offres au même état, arrondie
   au dixième supérieur ;
3. si l'état est confirmé, le prix saisi à la main, arrondi de même ;
4. la tendance Cardmarket arrondie au dixième supérieur, si la variante est
   confirmée, l'état MT, NM ou EX et la tendance inférieure à 10 €.

Aucune décote selon l'état. Sinon, la fiche donne les motifs (état à
confirmer, variante à vérifier, état inférieur à EX, 10 € ou plus, pas de
tendance), et **Publier à un prix fixé à la main** reste possible pour une
carte identifiée et disponible. Le **plancher de 0,50 €** est comparé au
montant avant l'arrondi : une carte à 0,41 € va dans un lot ou se donne.

- **Publier à ce prix** publie ; une carte publiée affiche son prix et sa
  source. **Changer le prix de vitrine** met à jour la même publication ;
  **Retirer de la vitrine** la retire, avec un motif inscrit à l'historique.
- Depuis une sélection, **Publier en vitrine** publie chaque carte à son propre
  prix et signale les refus ; **Publier en lot** demande un prix unique pour
  l'ensemble, au moins 0,50 €.
- Un exemplaire n'appartient qu'à une publication en ligne. Une publication
  dont un exemplaire est réservé, vendu ou supprimé sort de la vitrine.
- Le prix publié ne change jamais tout seul : un relevé plus récent est
  seulement signalé dans la liste des publications.
- **Stock → Publiés en vitrine** montre les exemplaires en ligne. Un compte de
  consultation voit les publications sans pouvoir publier.

**Ce que voit un visiteur.** La vitrine ne charge aucun code de gestion et
n'ouvre aucune session. Elle liste les publications dont tous les exemplaires
sont disponibles, avec une recherche (nom, extension, numéro), un filtre de
langue, un prix maximum et un tri (récentes, prix, nom). Une fiche montre le
recto et le verso, l'extension, le numéro, la langue, l'état **s'il est
confirmé** (sinon « état visible sur les photos »), la finition, le tampon, la
distribution, le prix et sa date. Les réponses publiques sont construites champ
par champ : jamais de notes, de provenance, d'historique, de prix bruts,
d'emplacement ni d'identifiant d'exemplaire ; les photos passent par
l'identifiant de la publication. Les lectures anonymes sont limitées à 300
requêtes par minute et par adresse. La page porte `noindex` tant que
l'indexation par les moteurs de recherche n'est pas décidée ; la gestion et
l'API portent `X-Robots-Tag: noindex, nofollow`.

**Confiance et contact.** La vitrine dit qu'il s'agit d'un site personnel non
officiel, sans paiement en ligne ni téléchargement, et renvoie à `/a-propos` :
qui vend, comment se passe un achat, données conservées, contact, code source.
L'adresse de contact vient de `POKEPRICE_CONTACT_EMAIL`, le nom du responsable
du traitement de `POKEPRICE_CONTROLLER_NAME`, dans l'environnement du serveur ;
sans eux, la page annonce le contact « bientôt » et parle « du vendeur ».
L'inscription rappelle de choisir un mot de passe propre à Lilydex.

### Les clients et leurs demandes

Sur la vitrine, **Créer un compte** demande un nom, un e-mail, un mot de passe
de 10 caractères au moins et la lecture de l'information sur les données (la
base légale est la demande de réservation, pas un consentement). Le compte
reste **en attente** : l'administrateur le valide, le refuse ou le désactive
dans **Gestion → Comptes et albums → Comptes clients de la vitrine**. La
réponse à l'inscription est la même, que l'adresse soit connue ou non ; cinq
inscriptions par heure et par adresse au plus. Un client se connecte avec son
e-mail ; il n'apparaît jamais parmi les comptes de l'équipe, ne peut pas
recevoir de rôle de gestion et n'accède à aucune action de gestion.

Un client connecté ajoute des cartes à **Ma demande** (gardée dans son
navigateur), écrit un message (envoi, remise en main propre) et l'envoie.
**Une demande ne bloque rien.** Il suit ses demandes dans **Mes demandes** et
peut annuler une demande en attente ; dix demandes en attente au plus par
client ; une demande sans réponse expire au bout de 7 jours.

Dans **Ventes**, le panneau **Demandes de la vitrine** liste les demandes, en
attente d'abord, avec l'e-mail, le message et les exemplaires. **Accepter les
cartes cochées** crée un lot « Vitrine · nom du client », canal Vitrine, au prix
figé lors de la demande, et le réserve aussitôt ; les cartes non cochées sont
« non retenues ». Si un exemplaire vient d'être réservé ailleurs, l'acceptation
échoue sans laisser de brouillon. **Refuser la demande** demande un motif,
visible par le client. Contactez ensuite le client depuis votre messagerie pour
le paiement et l'envoi : le lot suit le circuit habituel et le client voit son
statut (réservée, vendue, expédiée…). Chaque décision est inscrite à
l'historique des exemplaires.

### Les données des clients

Les durées annoncées sur `/a-propos` sont appliquées chaque nuit, avant la
sauvegarde, par `pokeprice-manage purge` : compte refusé effacé 30 jours après
l'inscription ; compte jamais validé, 90 jours après ; demande sans suite
(refusée, expirée, annulée), 6 mois après ; client sans demande depuis 3 ans,
effacé avec ses demandes. Les durées sont dans `privacy.py` : en changer une,
c'est changer la notice aussi.

Un client gère lui-même ses droits dans **Mon compte** : corriger son nom et
son e-mail (qui sert aussi à se connecter), télécharger toutes ses données en
JSON (`/api/me/export`), supprimer son compte. Modifier ou supprimer demande le
mot de passe actuel. Une demande d'effacement reçue par e-mail se traite sur le
serveur, avec `--data` (forme complète dans
[Héberger Lilydex](DEPLOYMENT.md#lancer-une-commande-sur-le-serveur)) :

```bash
sudo -u pokeprice env HOME=/srv/pokeprice /opt/pokeprice/.venv/bin/python -m pokeprice.manage --data /srv/pokeprice/inventory forget <e-mail>
```

Le compte, ses sessions, ses demandes et leurs messages sont supprimés. Un lot
issu d'une demande acceptée reste dans les ventes, avec ses montants, mais le
nom, l'e-mail et le message du client y sont remplacés (« client effacé »,
« message effacé »), dans le lot comme dans son historique. Seuls les comptes
clients s'effacent ainsi, jamais ceux de l'équipe. Ce qui a été ajouté à la
main dans les notes d'un lot n'est pas retrouvé : relisez ces notes.

Chaque effacement est inscrit, par identifiant de compte seulement, dans
`erasures.jsonl` à côté du dossier de collection. `restore` rejoue ce journal
dans le dossier restauré s'il est à côté : une archive antérieure à un
effacement ne fait pas revenir le client. Voir aussi
[Données personnelles](RGPD.md).

## Consulter la collection

### Rechercher et filtrer

La recherche porte sur le nom, l'extension, la référence et l'album ; les
filtres, sur le stock, l'identification, la variante et l'examen. La
collection affiche le nombre d'exemplaires et d'éditions, avec une pagination.
**Afficher → Éditions et quantités** regroupe les exemplaires sans les
fusionner : les compteurs de stock portent sur l'édition entière, les
exemplaires affichés respectent les filtres.

La recherche, les filtres, la pagination, la vue et l'onglet actif sont
inscrits dans l'adresse, par exemple `/gestion?q=Zarbi&stock=available&offset=40`.
Actualiser ou partager ce lien garde la consultation ; les boutons précédent et
suivant du navigateur restaurent aussi les filtres et la page. La connexion
reste nécessaire. Un lien `/api/copies?...` ouvert comme une page rejoint cette
consultation ; les appels de l'API reçoivent toujours du JSON.

**Trier → Classeur** parcourt les albums par nom, puis les pages et les
pochettes dans l'ordre (`sort=binder` dans l'adresse), avec tous les filtres et
les deux vues ; les éditions suivent leur premier exemplaire dans cet ordre. Le
tri par nom reste le choix par défaut.

### Agrandir les photos

Cliquer sur une photo ouvre le même agrandissement depuis la collection, une
fiche, les aperçus ou les éditions proposées. Une image zoomée se déplace en la
faisant glisser, à la souris ou au doigt ; dans une comparaison, les deux images
gardent des déplacements indépendants et se superposent verticalement sur un
petit écran. Fermer, ou Échap, rend la main à la saisie sans effacer ses champs
ni confirmer l'édition.

La grille charge une vignette (280 × 392 px au plus) ; l'agrandissement et la
visionneuse gardent la photo d'origine. Les vignettes se recalculent à la
demande dans `thumbnails/` et ne font pas partie des sauvegardes.

### Parcourir au clavier et en visionneuse

Dans la grille, la carte qui a le focus est entourée :

| Touche | Effet |
|---|---|
| Flèches | Carte voisine ; gauche et droite franchissent les pages de résultats |
| Début, Fin | Première ou dernière carte de la page |
| Pg↑, Pg↓ | Page précédente ou suivante, à la même place |
| Ctrl+Début, Ctrl+Fin | Tout début ou toute fin des résultats |
| Entrée | Ouvrir la fiche |
| Espace | Cocher la carte pour la sélection ou le lot |
| **V** | Ouvrir ou fermer la visionneuse |

La **visionneuse** (touche **V** ou bouton **Visionneuse**) montre la carte en
plein écran, sur ordinateur comme sur téléphone, avec une ligne pour le nom,
l'extension, le prix prudent et l'emplacement :

- **I** (ou le bouton i) affiche le détail, à droite sur ordinateur, en bas sur
  téléphone ; **T** épingle la bande des cartes de la page, qui apparaît aussi
  quand la souris approche du bas de l'écran. Ces deux choix sont mémorisés sur
  l'appareil.
- ← et → enchaînent les cartes sur tous les résultats ; Pg↑ et Pg↓ sautent de
  10 cartes, ou d'une page de classeur avec **Trier → Classeur** ; Début et Fin
  vont aux extrémités.
- **R** (ou le bouton Verso) retourne la carte ; Entrée ouvre la fiche ; Espace
  la sélectionne ; Échap ou **V** ramènent à la grille sur la dernière carte
  vue.
- Sur téléphone, un glissement horizontal sur la photo change de carte. Une
  touche pressée pendant un chargement est jouée ensuite.

## Supprimer ou restaurer un exemplaire

Un administrateur ouvre la fiche, choisit **Supprimer cet exemplaire**, donne
un motif et confirme. La carte quitte la collection et ses exports HTML et CSV ;
ses photos, sources, prix et historique restent dans la corbeille, la
sauvegarde et l'export JSON complet. Une carte d'un lot en cours, réservée ou
vendue ne peut pas être supprimée.

Pour revenir sur une suppression : **Stock → Corbeille**, ouvrez la fiche,
puis **Restaurer cet exemplaire**. L'exemplaire garde son identifiant et son
emplacement. Aucun effacement définitif n'est proposé, et un réimport ne
réactive pas un exemplaire supprimé.

## Importer et exporter vos données

### Numériser et importer un classeur

Photographiez chaque page du classeur, puis lancez :

```bash
uv run pokeprice scan <dossier-photos> --grid 3x3 -o <album.csv>
```

La commande découpe chaque page en pochettes, lit chaque carte et la rapproche
du catalogue TCGdex ; ses options sont dans la
[référence des commandes](COMMANDES.md#pokeprice-scan). Ajoutez ensuite l'album
au manifeste et importez-le :

```bash
uv run --extra web pokeprice-manage import <manifeste.json>
```

- Un identifiant durable est attribué à chaque pochette importée et gardé
  ensuite, même si l'exemplaire change d'album ou d'emplacement. La clé
  d'origine et la ligne source complète lui restent associées.
- Relancer l'import du même manifeste n'ajoute aucun doublon et n'écrase
  aucune correction faite dans l'application. Des changements dans les sources
  sont signalés par `source_changed`, sans fusion automatique.
- Un nouveau nom de fichier ou un nouvel identifiant d'album produit une
  nouvelle clé d'origine : ne réimportez pas un album rephotographié sans
  établir la correspondance avec ses exemplaires actuels.
- Pour un classeur rempli à partir d'une page ultérieure, `"first_page": 51`
  dans son entrée numérote la première photo de cartes page 51 ; le rapport du
  scan reste numéroté à partir de 1. Le scan ne compte pas la couverture : la
  première page de cartes est la page 1.
- Les cartes hors catalogue restent manuelles ; les candidats d'une identité
  non résolue sont gardés dans la provenance, sans identifiant ni prix
  confirmé.

Les CSV, checkpoints, corrections et photos des albums restent les sources
initiales archivées : l'application ne les modifie pas, et la base devient la
source de vérité des modifications. Les corrections des rapports d'origine
passent par `pokeprice scan --corrections`.

`pokeprice-manage repair-pages` audite les pages des classeurs Diamond & Pearl
et Platinium, dont la couverture avait été comptée comme page 1. Après une
sauvegarde, `--apply` retire une page aux exemplaires encore à leur emplacement
d'import, avec contrôle de version et l'auteur fixe `system:page-shift` ; un
exemplaire dont la page ou l'album a changé depuis l'import n'est pas touché.

### Exporter

Pour exporter l'état actuel, corrections comprises, utilisez l'application ou
`pokeprice-manage export`, plutôt que la commande historique `library`, qui
relit les rapports d'origine :

```bash
uv run --extra web pokeprice-manage status
uv run --extra web pokeprice-manage export html outputs/collection-geree.html
uv run --extra web pokeprice-manage export json outputs/collection-geree.json
uv run --extra web pokeprice-manage export csv outputs/collection-geree.csv
```

Les fichiers de sortie doivent être nouveaux. Le CSV protège les cellules qui
commencent par un caractère de formule ; le JSON est l'export fidèle complet,
avec la provenance et l'historique. La page HTML autonome contient les photos
recto et verso, l'état enregistré et son statut de confirmation, et le stock
dans les notes, mais pas l'historique détaillé des ventes.

## Sauvegarder

Chaque nuit, le serveur archive la collection et vérifie l'archive par une
restauration ; le portable en garde une copie et l'envoie chiffrée sur Google
Drive. Le panneau **Sauvegardes** de la gestion, réservé aux administrateurs,
affiche la dernière archive vérifiée, la dernière erreur et une alerte au-delà
de 36 heures. Le bouton **Sauvegarder et vérifier maintenant** refait l'archive
du jour, sans l'envoyer sur Drive. Le détail est dans [Sauvegardes](DAILY-BACKUPS.md).

Avant une opération de masse, faites une sauvegarde complète de la base visée
(sur le serveur, avec `--data`) :

```bash
uv run --extra web pokeprice-manage backup
uv run --extra web pokeprice-manage backup outputs/collection-backup.zip
uv run --extra web pokeprice-manage --data /tmp/collection-restauree restore outputs/collection-backup.zip
uv run --extra web pokeprice-manage --data /tmp/collection-restauree status
```

Sans chemin, `backup` écrit une archive datée dans `backups/`. L'archive est
cohérente : la base est copiée par l'[API de sauvegarde de SQLite](https://www.sqlite.org/backup.html),
pas comme un fichier en cours d'usage, avec toutes les photos, y compris les
anciennes utiles à l'historique, les originaux, versos et réponses
d'évaluation. La restauration exige un dossier inexistant et vérifie les
empreintes, l'intégrité SQLite, les relations et les photos ; les comptes et
leurs mots de passe hachés sont restaurés, les sessions fermées. Gardez les
archives privées, avec une copie hors de l'appareil. L'[instantané
initial](RECOVERY.md) garde en plus les pages originales des classeurs.

## Ce que l'application ne fait pas

- Elle ne rapproche pas automatiquement des sources modifiées.
- Elle ne suit pas les paiements bancaires : le paiement se déclare à la main.
- Elle ne publie aucune annonce sur une plateforme de vente.
- Elle ne confirme rien à votre place : identité, variante et état restent des
  décisions humaines.

## Ce qui est vérifié

Les tests couvrent les droits, les photos privées, les requêtes venues d'une
autre origine, les conflits de versions, la révocation d'accès, les
réservations concurrentes, les annulations, retours et remboursements, les
archives corrompues et la restauration, les préparations de photos privées, le
mode manuel, les confirmations modifiées, la reprise sans doublon, les versos
et évaluations, les propositions obsolètes et les migrations. Ils tournent
sans réseau ni modèle ([Contribuer](../CONTRIBUTING.md)).

`scripts/verify_inventory_import.py` compare un import à la bibliothèque
d'origine (références, PV, langues, variantes, statuts, corrections, prix,
photos) ; il sert avant les premières modifications. Les réceptions passées,
sur Android et dans le navigateur, sont au [journal](JOURNAL.md).
