# Application privée de gestion Pokémon

Première version locale du 4 octobre 2026 : FastAPI, SQLite et interface française
sans service externe pour consulter, corriger ou suivre les ventes.

## Démarrage

Depuis `~/Projects/pokeprice` :

```bash
uv sync --extra web --extra dev
uv run --extra web pokeprice-manage import pokeprice_library_manifest.json
uv run --extra web pokeprice-manage serve
```

Ouvrir [http://127.0.0.1:3820](http://127.0.0.1:3820). Au premier accès, choisir
son compte administrateur et un mot de passe d'au moins dix caractères. Aucun
mot de passe par défaut n'est livré pour la collection réelle. Le serveur reste
sur cet appareil. Pour utiliser le téléphone sur le même Wi-Fi, écouter sur
l'adresse IPv4 Wi-Fi du portable :

```bash
uv run --extra web pokeprice-manage serve --host <adresse-wifi>
```

Ouvrir alors `http://<adresse-wifi>:3820` depuis le téléphone. L'adresse peut
changer avec le DHCP ; cette consultation locale utilise HTTP. Le téléphone
utilisera l'adresse HTTPS après déploiement Internet.

Depuis le 5 octobre 2026, un [lien HTTPS Cloudflare temporaire](TUNNEL.md)
permet aussi la consultation et la gestion à distance avec le compte existant.
Il dépend du portable et des processus locaux ; l'hébergement permanent reste
à réaliser.

Le dossier persistant est `data/inventory/`, exclu de Git : base
`collection.sqlite3` et sous-dossier `photos/`. Changer ce dossier avec
`pokeprice-manage --data <dossier> ...`. Ne pas déplacer la base seule en oubliant
les photos et les documents de référence archivés. Les versions de schéma
1 à 12 sont migrées explicitement. Sauvegarder avant de démarrer une nouvelle
version qui migre la base.

## Référentiel M1.1 en mode audit

L’ajout et la correction permettent de saisir la finition observée, l’état du
tampon (« non examiné », « absence constatée », « présent »), son texte original
et une autre marque de distribution facultative. Les observations partielles
restent sauvables sans catalogue ou prix. Auteur, date et motif sont attribués
par le serveur ; la confirmation globale de la variante reste distincte.
Les anciens champs vides et textes de tampon sont conservés avec l’état
« non examiné » à la migration.

Le filtre **Examen → Référentiel à compléter** conserve son état dans l’adresse,
fonctionne dans les vues exemplaires/éditions et respecte le tri Classeur.
Il expose les lacunes du référentiel séparément de l’examen physique.
La fiche et son aperçu montrent l’état de correspondance marchande.

```bash
uv run pokeprice-manage reference-audit > outputs/reference-audit.json
```

Cet audit ouvre la base en lecture seule, sans migration, réseau ou correction.
Il distingue les références héritées non liées, les références manuelles, les
prix absents et les besoins de couverture par édition/langue. Le sous-total
vérifié reste inconnu tant qu’aucune cotation liée n’est vérifiée.
Le paquet initial ne certifie pas les références existantes et ne remplace pas
encore le calcul de prix hérité : les preuves de marché restent à compléter.

Pour une pièce justificative et après une mise à jour des règles :

```bash
uv run pokeprice-manage reference-archive capture.html
uv run pokeprice-manage reference-recheck
uv run pokeprice-manage reference-recheck --apply
```

La première commande range la pièce par SHA-256. `reference-recheck` liste les
cotations liées devenues incompatibles ; `--apply` inscrit leur suspension au
journal. Une suspension ne se lève que par une restauration explicite.

Les sauvegardes emportent aussi les règles et moteurs enregistrés avec les
décisions, les cotations liées et leurs événements, et les documents sources
rangés une fois par SHA-256 dans `reference_documents/` (PDF, JSON ou HTML).
Une pièce manquante ou altérée est signalée ; aucun téléchargement automatique
ne rétablit son statut de preuve.
Voir [le guide fonctionnel du référentiel](PRINT_REFERENCE_GUIDE.md) et
[l’état détaillé et les limites de M1.1](PRINT_REFERENCE_IMPLEMENTATION.md).

## Ce qui fonctionne

- Recherche globale par nom, extension, référence et album ; filtres de stock
  et d'identification ; nombre d'exemplaires et d'éditions, pagination.
- Photos propres à chaque exemplaire, accessibles après connexion uniquement.
- Correction de nom, extension, référence, catalogue, langue, PV, variante,
  état, notes et emplacement ; auteur, date, motif et anciennes valeurs conservés.
- Ajout manuel, nouveaux albums, ajout/remplacement d'une photo.
- Comptes consultation, gestion et administration ; révocation d'accès et
  fermeture des sessions lors d'un changement de rôle. Le dernier administrateur
  actif ne peut pas être désactivé ou rétrogradé.
- Lots en brouillon, réservation transactionnelle, vente, paiement déclaré,
  expédition, clôture, annulation et retour ; frais, port, emballage et
  remboursements en euros. Prix affiché, cible, minimum et convenu sont distincts.
  Une réservation concurrente du même exemplaire échoue.
- Exports CSV, JSON avec provenance/historique et HTML autonome avec photos,
  utilisant l'état de la base. Sauvegarde SQLite cohérente et photos en ZIP.

Les montants sont stockés en centimes. Le net calculé vaut prix + port facturé
− frais − coût du port − emballage − remboursements. Le paiement est déclaré
manuellement : l'application ne prend ni n'effectue de paiement. Un retour
réintègre les cartes et remet leur état à confirmer ; enregistrer séparément le
montant réellement remboursé. Aucune annonce n'est publiée automatiquement.

Le prix de référence n'est pas un prix de vente souhaité. Une correction
d'identité ou de variante efface la référence courante devenue incertaine ; les
anciens relevés restent dans l'historique. Un prix indisponible reste vide.
Préciser une finition compatible avec l’identité, le tampon et la catégorie
déjà cotés conserve la référence, sa source et sa date. Une catégorie modifiée
ou encore ambiguë exige un nouveau relevé. La fiche affiche aussi la référence
manuelle datée, même sans relevé détaillé ni moyenne permettant une valeur prudente.

`pokeprice-manage repair-prices` audite les anciennes pertes causées par une
précision compatible de finition. Après sauvegarde, `--apply` restaure uniquement
les cotations sourcées et datées du plan, avec contrôle de version et auteur
fixe `system:price-recovery`. `--copy-id` limite les exemplaires ; les confirmations
humaines sont conservées. Aucun prix déjà présent ou explicitement supprimé
sans changement de finition n’est remplacé.
Les états importés restent à confirmer. Aucune décote automatique n'est appliquée.

### Relever le prix d'une carte

Sur la fiche d'une carte confirmée avec son édition TCGdex, **Relever le prix
(TCGdex)** interroge TCGdex et enregistre un relevé daté : prix bas, moyennes
sur 1, 7 et 30 jours et tendance Cardmarket de la variante de l'exemplaire
(normale, ou holo/reverse si la carte est marquée Foil). La tendance devient la
référence (`TCGdex · Cardmarket trend` ou `trend-holo`), avec sa date ; le relevé
complet reste dans l'historique. Un relevé identique au précédent n'ajoute pas
de correction. Une carte à vérifier ou sans édition n'est pas relevée.

À partir de 2 €, des alertes signalent une variante inconnue de TCGdex, un écart
d'au moins ×3 avec l'autre variante, des moyennes divergentes ou un prix bas
très inférieur à la tendance. En dessous, la carte relève du vrac vendu en lot.

En ligne de commande, `pokeprice-manage prices` relève toutes les identités
confirmées (`--album <id>` pour un album, `--only-missing` pour les cartes jamais
relevées, `--actor` pour l'auteur inscrit) et affiche un bilan.

Pour plusieurs cartes, les cocher puis cliquer **Relever les prix (n)** dans la
barre de sélection ; le nombre compte les cartes confirmées avec édition, les
autres sont ignorées. Chaque carte est relevée séparément : un échec (TCGdex,
tunnel, fiche modifiée entre-temps) n'arrête pas les suivantes. Le bilan indique
les prix relevés, les cartes ignorées, les échecs et les cartes avec alertes.

### Noms dans plusieurs langues

La recherche trouve une carte par son nom dans six langues (français, anglais,
allemand, italien, espagnol, portugais) : « Dracaufeu » ou « Glurak » trouvent un
Charizard anglais. `pokeprice-manage names` récupère ces noms une seule fois par
édition (schéma 9, tables `catalog_names` et `catalog_lookups`) ; `prices`
l'appelle à la fin de chaque relevé, sans requête pour les éditions connues.

Ménagement de TCGdex : une requête par extension et par langue (elle donne toutes
les cartes de l'extension, gardées pour les classeurs à venir), une à la fois avec
0,25 s de pause, réponses mises en cache y compris les absences (redemandées au
bout de 90 jours), nouvel essai avec attente croissante et respect de
`Retry-After` sur 429 et 5xx, arrêt après cinq échecs serveur consécutifs. Une
édition absente d'une langue reçoit le nom du Pokémon, retrouvé par son numéro de
Pokédex. Premier passage du 12 octobre 2026 : 1 136 requêtes en 7 min 37 s, puis
aucune.

### Tampon sur l'illustration

Le champ **Tampon sur l'illustration** (schéma 8) garde le texte d'un logo de
série ou d'un tampon imprimé sur l'image, par exemple « EX Fantômes Holon » :
la marque d'une promo holo tamponnée. **Lire la carte** le propose quand Gemini
le voit (21 tampons sur 21 au banc d'essai du 7 octobre) ; la saisie reste à
confirmer. Le tampon apparaît sur la carte, dans la recherche, dans le filtre
Variante → Tamponnées, dans les exports et les dossiers d'annonce. Modifier le
tampon change la variante : le prix de référence est retiré et doit être relevé.
Cardmarket range ces promos avec les Foil, mélangées aux reverses : le lien des
offres le rappelle, et seules les offres dont le commentaire mentionne le tampon
sont comparables.

### Estimer le prix de vente depuis Cardmarket

L'API Cardmarket n'accepte plus de nouvelles inscriptions et la collecte
automatique des pages n'est pas utilisée. Dans la fiche, ouvrir **Voir les
offres Cardmarket**, sélectionner toute la page (Ctrl+A), copier, puis coller
dans **Estimer le prix de vente depuis Cardmarket**. Le serveur repère chaque
offre (état, commentaire, prix) et ignore les prix d'en-tête (tendance,
moyennes). Règle fixe :

- au moins une offre au même état : prix de marché = médiane de toutes ces
  offres, fourchette du premier au troisième quartile dès quatre offres ;
  confiance bonne à partir de cinq offres, moyenne de deux à quatre. Les offres
  les moins chères (exemplaires abîmés, déstockage) ne fixent pas le prix ;
- sinon : médiane de l'état le plus proche, décote de 0,75 par cran d'état
  (hypothèse par défaut, à calibrer sur les ventes), confiance faible ;
- carte tamponnée : seules les offres dont le commentaire mentionne un tampon
  (« stamp », « tampon », « logo ») sont retenues ;
- alerte si moins de trois offres comparables, ou si le texte collé ne nomme
  pas la carte.

Il s'agit de prix demandés, pas de ventes ; les frais et le port restent à
déduire. L'estimation est enregistrée dans l'historique avec les offres, sans
modifier la carte ni son prix de référence ; la plus récente s'affiche.

### Repérer les cartes à examiner

Le filtre **Examen → À examiner** retient les contrôles physiques restant à faire
sur les cartes de valeur, les divergences de variante du catalogue, les identités
incertaines et les prix prudents incomplets. Le **seuil de valeur** vaut 10 €
par défaut et reste dans l’adresse avec le filtre et le tri Classeur. Les badges
et les fiches précisent les motifs d’examen et la valeur en jeu : maximum du
prix prudent des variantes et éditions plausibles.

La collection et les résultats filtrés affichent **Tendance**, **Valeur
prudente** (minimum entre tendance et moyenne à 30 jours, sans décote d’état)
et **Estimation de vente**, avec le nombre d’exemplaires couverts. Les prix
absents restent inconnus. Une estimation ancienne après correction d’identité,
de variante ou d’état est conservée dans la fiche et exclue des totaux.
Voir [les règles et la réception de M1](VALUATION.md).

### Vérifier les variantes

Le filtre **Variante** de la barre de recherche propose Standard, Foil et
**Foil à vérifier** : les cartes Foil dont le dernier relevé signale que TCGdex
ne connaît pas de reverse (à partir de 2 €), et dont la variante n’a pas encore
été confirmée physiquement. Les cartes concernées portent le
badge « ⚠ Variante à vérifier » ; les autres alertes de prix sont comptées sur
la carte. Le filtre est conservé dans l'adresse de la page (`?variant=check`).

Parcours conseillé : filtre Foil, **Sélectionner les cartes affichées**,
**Relever les prix** ; puis filtre Foil à vérifier, examen des photos, et
**Changer la variante** sur la sélection. Chaque carte reçoit sa correction avec
le motif saisi, puis un nouveau relevé de prix ; une carte déjà dans la variante
choisie reste inchangée. Ajouter `&limit=200` à l'adresse affiche jusqu'à
200 cartes par page.

La fiche sépare **Finition observée sur la carte** (mate, holo, holo avec cadre
brillant, reverse, spéciale) et **Catégorie de prix calculée** (Standard/Foil). La catégorie se déduit côté
serveur de la finition, du tampon et des données de l’édition : mate → Standard,
fond reverse → Foil, holo d’origine → Standard, illustration holo d’une édition
mate avec reverse connue → Foil. Le menu calculé est verrouillé dans la fiche.
Quand l’édition comporte explicitement une impression mate et une impression
holo parallèle, avec deux tarifs distincts et aucune reverse, « Holo dans
l’illustration » calcule Foil. C’est le cas de Manaphy 2/17 POP Série 9 ;
Foil désigne alors l’impression holo parallèle, pas un fond reverse.
Quand les tarifs décrivent explicitement une holo d’origine et une reverse,
sans impression mate, ils permettent de résoudre des indicateurs de finition
incomplets du catalogue. Baggaïd 74/99 Destinées Futures est ainsi Standard
pour l’illustration holo et Foil pour la reverse, conformément à la
[liste officielle Pokémon](https://assets.pokemon.com/assets/cms2/pdf/trading-card-game/checklist/bw4_web_cardlist_en.pdf).
Les montants utilisés restent les cotations Cardmarket en euros.
Une catégorie encore indéterminée est étiquetée « Catégorie enregistrée · à
vérifier » et n’est pas présentée comme un calcul automatique.
Une Prime
comme Roigada 85/90 Indomptable a un cadre holo d’origine : finition « Holo avec
cadre brillant », catégorie Standard. La [liste officielle Pokémon](https://assets.pokemon.com/assets/cms2/pdf/trading-card-game/checklist/hgss3_web_cardlist_en.pdf)
classe cette édition parmi les Prime, et les numéros 81–90 n’existent qu’en
une version brillante. Une holo tamponnée sur une carte normalement mate peut
relever de Foil ; le tampon et les observations restent enregistrés séparément.
Pour EX Deoxys n°16–95, une illustration holo avec le tampon de l’extension
est la reverse/Foil. C’est notamment le cas de Barboach 54/107 en italien.
Le [tableau officiel Pokémon](https://assets.pokemon.com/assets/cms/pdf/tcg/checklists/deoxys_checklist.pdf)
documente les impressions mate et parallèle brillante de cette plage.

**Standard signifie la version normale de l’édition**, qui peut être mate ou
holo d’origine ; une finition holo ne suffit pas à choisir Standard. Pour
Pikachu 78/110 EX Fantômes Holon, une illustration holo avec le tampon de
l’extension est la parallèle commercialisée comme reverse/Foil, malgré son
fond mat. La [liste officielle de l’extension](https://assets.pokemon.com/assets/cms/pdf/tcg/checklists/holonphantoms_checklist.pdf)
donne deux impressions (mate et brillante) aux numéros 18–98. Le serveur calcule Foil pour cette finition tamponnée ; il applique aussi cette
règle aux numéros 14–88 tamponnés EX Gardiens de Cristal, selon la
[liste officielle](https://assets.pokemon.com/assets/cms/pdf/tcg/checklists/crystalguardians_checklist.pdf). Une ancienne combinaison
incohérente conserve ses observations physiques, mais son prix est exclu des
totaux et un motif demande d’appliquer la catégorie calculée. Un enregistrement ou un
nouveau relevé de prix corrige cette catégorie avec historique et version
attendue, en conservant la date et l’auteur de l’observation physique lorsqu’elle
n’a pas changé. Un relevé ne crée jamais une confirmation humaine. Le prix prudent catalogue
n’est pas une estimation de vente pour l’état PO ni pour une langue donnée.

Cocher **Variante et tampon vérifiés sur la carte physique** clôt le contrôle,
même lorsque la catégorie de prix reste identique. La date et l’auteur sont
enregistrés par le serveur. Une divergence catalogue demeure informative et
ne remet pas la carte dans « Foil à vérifier ». Une correction d’identité,
de variante manuelle, de tampon, de finition ou du recto exige une nouvelle confirmation ;
un relevé de prix conserve la confirmation. Les anciens imports et corrections
ne sont jamais déclarés vérifiés automatiquement.

Si le catalogue est incomplet ou admet plusieurs impressions, la fiche garde
une sélection manuelle et demande de préciser le produit dans les observations
avant tarification. La finition et sa confirmation physique peuvent être
enregistrées même sans ces informations ; le prix reste exclu des valeurs
tant que sa catégorie n’est pas déterminée.
Les données de finition sont récupérées et mises en cache lors de la saisie
d’une holo sans métadonnées locales, même si TCGdex ne fournit pas de prix
Cardmarket. Celebi Promo Nintendo 029 est ainsi une holo d’origine en Standard,
avec un prix en euros à relever séparément. Cette consultation ne modifie ni
l’exemplaire, ni sa confirmation, ni son relevé de prix.
Une ancienne correction de catégorie sans
finition observée retourne dans « À examiner » ; elle n’est pas présumée erronée.
L’audit en lecture seule `python scripts/audit_variant_categories.py` répertorie
les catégories incohérentes, les observations ambiguës et ces corrections à
reprendre. Il ne modifie aucune donnée de collection.

La file « À examiner » montre les tâches restantes : identité, variante/tampon,
état et prix à actualiser. Une carte de valeur dont l’examen physique et le prix
prudent sont complets quitte la file ; elle garde le badge « Carte de valeur ».
Après confirmation de la variante, la valeur en jeu exclut les autres variantes
écartées. L’instabilité du marché reste une information de prix.

La variante **Foil** signifie « plus brillante que la version standard de la
carte » : reverse (fond de la carte holographique hors illustration, illustration mate) ou holo tamponnée d'une
carte normalement mate, que Cardmarket range avec les Foil. Une Rare Holo
imprimée holo d'origine reste **Standard** : Cardmarket et TCGdex donnent son
prix en tendance normale et rangent sous « holo » celui de sa reverse. Les
variantes de TCGdex sont parfois incomplètes : le Pikachu 78/110 holo tamponné
« ex Fantômes Holon » n'y figure pas. Le pipeline d'albums marque Foil toute
carte brillante ; une alerte signale les cartes Foil dont TCGdex ne connaît pas
de reverse.

**Voir les offres Cardmarket** ouvre la page du produit filtrée sur la langue
de l'exemplaire, son état ou meilleur (`minCondition`) et, pour une carte Foil,
les reverse uniquement (`isReverseHolo=Y`). Ces filtres ont été vérifiés le
7 octobre 2026. Les offres sont triées par prix : comparer celles de même état.

### Lire la finition sur la photo (M2)

Dans la fiche, **Lire la finition** transmet la photo du recto à Gemini, qui
répond à trois questions : illustration holo ou mate, fond brillant hors de
l’illustration (reverse), texte d’un tampon. La lecture est enregistrée avec la
photo lue, le modèle, la version du protocole et les jetons consommés. Elle ne
modifie ni la fiche ni le prix.

La fiche en tire une **proposition**, recalculée à chaque ouverture avec la
règle de catégorie habituelle (édition, tampon, versions TCGdex) :

- illustration holo → Standard ou Foil selon l’édition et le tampon ;
- illustration mate → Standard, **sauf** si une reverse est possible et que
  sa version Foil vaut au moins le seuil (ou n’a pas de prix connu) : la
  proposition devient « Examen physique requis ». Aucun modèle ne distingue
  sûrement une reverse sur une photo de classeur ;
- fond brillant signalé → reverse possible, à examiner sous un éclairage rasant ;
- photo insuffisante → aucune proposition.

Un tampon déjà observé par une personne (présent ou absent) prime sur le tampon
lu. **Enregistrer la finition retenue** applique le choix humain (finition,
tampon, et la case « carte examinée en main » pour confirmer la variante) ; la
lecture et la proposition sont jointes à l’historique comme preuves. Une lecture
devient obsolète dès que la photo du recto change.

Une lecture en désaccord avec la fiche (illustration holo contre fiche mate ou
reverse, tampon contraire) place la carte dans « À examiner », même sous le
seuil, jusqu’à une confirmation physique postérieure à cette lecture.

**Lecture automatique à la saisie.** Avec `pokeprice-manage serve`, chaque
nouvel exemplaire enregistré avec une photo du recto (saisie à l’unité ou en
série) est lu une fois, juste après l’enregistrement, sans retarder la saisie.
L’historique indique « lancée automatiquement à la saisie ». Si la lecture
échoue (Gemini indisponible, photo refusée), l’historique le note et la carte
reste à lire depuis la fiche. L’identification d’un exemplaire déjà en stock
et le remplacement d’une photo ne déclenchent rien. `--no-auto-checks`
désactive la lecture automatique (pas d’envoi à Gemini sans action explicite).

**Non-régression.** `uv run python scripts/bench_recognition.py app` rejoue le
banc d’essai à travers l’application, sur une copie de la base remise à l’état
de saisie (variante non observée), en deux passages : chaque mesure est jugée
sur le pire. Il échoue si une mesure passe sous son score du 7 octobre, ou si une proposition contredit une variante confirmée alors que
la version Foil atteint le seuil ou n’a pas de prix connu.
Une photo inexploitable (Gliscor, nom coupé) doit être refusée, pas lue.
`app-check` rejoue hors ligne les lectures enregistrées avec les règles
actuelles ; le test `tests/test_recognition_bench.py` en fait autant quand le
banc local est présent.

## Supprimer ou restaurer un exemplaire

Un administrateur ouvre la fiche et choisit **Supprimer cet exemplaire**, puis
renseigne un motif et confirme. La carte quitte la collection et ses exports
HTML/CSV ; ses photos, sources, prix et historique restent conservés dans la
corbeille, la sauvegarde et l’export JSON complet. Une carte appartenant à un
lot en cours, réservée ou vendue ne peut pas être supprimée.

Pour revenir sur une suppression, choisir **Stock → Corbeille**, ouvrir la
fiche et cliquer sur **Restaurer cet exemplaire**. L’exemplaire conserve son
identifiant et son emplacement. Aucun effacement définitif n’est proposé.
Un réimport ne réactive pas les exemplaires supprimés.

**Désélectionner tout** remet seulement à zéro la sélection pour un lot :
cette action ne supprime aucun exemplaire.

## Constituer un lot

Depuis **Collection** ou **Ventes**, cliquer sur **Créer un lot**. Cocher les
exemplaires disponibles, ou utiliser **Ajouter les cartes affichées** pour la
page courante. La sélection reste conservée entre les recherches, les albums et
les pages ; chaque carte choisie peut être retirée du récapitulatif. Deux
exemplaires d'une même édition restent distincts grâce à leur emplacement.

Cliquer sur **Continuer**, vérifier le contenu, puis renseigner le titre et le
prix envisagé. Les objectifs de prix, le canal et les notes sont facultatifs.
**Enregistrer le lot en brouillon** ouvre le lot dans **Ventes**. Les cartes
restent disponibles jusqu'à l'action **Réserver les cartes**. Un compte de
consultation ne peut pas créer de lot.

Ce parcours a été rendu explicite le 5 octobre 2026. Actualiser la page pour
charger la nouvelle interface, y compris depuis le lien Cloudflare.

## Saisie assistée par photo

Depuis **Ajouter une carte**, utiliser **Prendre une photo** ou **Téléverser une
image**. Les mêmes choix sont disponibles sur la fiche pour remplacer sa photo,
avec un aperçu et un enregistrement explicite. Le recto entier et ses deux coins
inférieurs doivent être lisibles.

Sur Android et iPhone, **Prendre une photo** ouvre la capture native. Sur
ordinateur, le bouton demande l'accès à la caméra et affiche son aperçu ; choisir
le périphérique si plusieurs caméras sont disponibles, puis **Capturer la photo**.
Fermer ce dialogue coupe la caméra. Une capture passe par l'aperçu habituel avant
tout enregistrement. Le navigateur exige HTTPS ou localhost pour cet aperçu :
depuis une adresse Wi-Fi en HTTP, utiliser le lien HTTPS ou le téléversement.
Un refus de permission ou l'absence de caméra laisse le téléversement accessible.

## Retrouver sa consultation et agrandir les photos

La recherche, les filtres, la pagination et l'onglet actif sont inscrits dans
l'URL, par exemple `/?q=Zarbi&stock=available&offset=40`. Actualiser ou partager
ce lien conserve la consultation ; les boutons précédent/suivant du navigateur
restaurent également les filtres et la page. La connexion reste nécessaire.
Le sélecteur **Trier → Classeur** parcourt les albums par nom, puis les pages
et les pochettes dans l'ordre numérique. Ce choix est conservé dans l'adresse
(`?sort=binder`) avec tous les filtres et les affichages par exemplaire ou par
édition ; les éditions suivent le premier exemplaire dans cet ordre. Le tri
par nom reste le choix par défaut.
Un lien `/api/copies?...` ouvert comme une page rejoint cette consultation en
conservant ses paramètres ; les appels de l'API continuent à recevoir du JSON.

Cliquer sur une photo de carte ouvre le même composant d'agrandissement depuis
la collection, une fiche, les aperçus de photo ou les éditions proposées.
La comparaison de saisie montre **Votre exemplaire** et **Carte du catalogue**
ensemble, avec un zoom indépendant jusqu'à 400 % et une remise à l'échelle.
Une image zoomée se déplace en la faisant glisser à la souris ou au doigt ;
les deux images de la comparaison gardent leurs déplacements indépendants.
Les images se superposent verticalement sur petit écran. La fermeture ou Échap
rend la main à la saisie sans effacer ses champs ni confirmer l'édition.

## Préparer la photo

L'aperçu propose trois réglages locaux, sans appel Gemini : recadrage automatique,
redressement de perspective et légère balance des couleurs. Le redressement
utilise les quatre coins et suppose le format habituel d'une carte Pokémon.
Il accompagne le recadrage ; désactiver le recadrage désactive aussi le redressement.
La détection vise une carte verticale entière sur un fond uni, ou un cadre jaune
continu même sur un fond texturé. Si les contours
sont ambigus, coupés, multiples ou trop inclinés, la photo reste entière. Une
marge garde les bords et la référence.

Sur ordinateur, l'aperçu caméra affiche une mire de cadrage au format carte,
verticale et centrée. La capture transmet sa position (`X-Card-Guide`, en
fractions de l'image) avec la photo. Les contours détectés sur l'image entière
restent prioritaires. Sinon, la détection est reprise dans la zone de la mire,
qui exclut l'entourage et tolère un tapis texturé (feutrine) : c'est ce qui
permet de redresser un verso bleu. En dernier recours, le recadrage suit la mire
avec 6 % de marge, sans redressement. La provenance indique `crop_source`
(`contours`, `contours-in-guide` ou `guide`) et la mire. Les téléversements et la capture native Android n'ont pas de mire.
L'aperçu demande la résolution native de la caméra, y compris en portrait :
une caméra Android relayée par `scrcpy --capture-orientation=90` n'est pas
recadrée par le navigateur. La balance s'appuie sur les zones claires
presque neutres et limite chaque canal à ±8 %, sans augmentation de saturation,
lissage ni suppression de défauts. Elle ne corrige pas les reflets ni le flou.

Désactiver les trois options permet de retrouver exactement la photo d'entrée
normalisée. Cette version entière et la version préparée sont conservées sous
des hashes distincts, avec les réglages dans la provenance ou l'historique et
dans les sauvegardes. « Photo entière » désigne ici le JPEG orienté, limité à
1600 pixels et débarrassé de ses métadonnées, avant les trois corrections ; le
fichier du téléphone reste intact. Modifier un réglage annule la lecture mise en
cache et le choix d'édition : relire ou rechercher avant de confirmer.

**Lire la carte** envoie cette photo au modèle Gemini `gemini-3.8-flash`
configuré sur le serveur. La lecture propose le nom imprimé, la référence,
la langue et les PV. L'extension est recherchée dans TCGdex, sans recherche de prix.
Une clé `GEMINI_API_KEY` ou `GOOGLE_API_KEY` est requise ; elle n'est jamais
envoyée au navigateur. Les appels utilisent le compte API configuré.

Cliquer sur une édition proposée, comparer l'illustration du catalogue avec la
photo de l'exemplaire, puis cocher la confirmation. La photo et l'identité sont
enregistrées ensemble. Sans confirmation, l'exemplaire reste **à vérifier**.
Si la lecture échoue, saisir le nom, la référence complète et la langue, puis
cliquer sur **Rechercher l'extension**. Une extension inconnue peut rester vide.

Pour une carte déjà ajoutée, ouvrir sa fiche puis **Identifier la carte**.
L'opération complète cet exemplaire sans en créer un autre ; son emplacement,
sa photo, son stock, ses notes et son état physique sont conservés. Une modification
concurrente de sa fiche exige de reprendre la préparation.

La lecture Gemini, les recherches catalogue et la confirmation sont conservées
dans la provenance ou l'historique. L'état physique et le prix restent séparés :
aucune estimation de grade ou de prix n'est enregistrée par ce parcours.
La saisie peut aussi être effectuée entièrement à la main, sans photo.

## Verso et proposition d'état

La fiche d'un exemplaire affiche maintenant **Recto** et **Verso**, chacun avec
capture, téléversement, préparation et agrandissement. Ajouter le verso conserve
l'UUID, le stock et l'identité du recto : il ne crée pas une deuxième carte.
Après l'ajout d'une carte, la fiche permet de compléter immédiatement le verso.

**Évaluer l'état** transmet les photos entières disponibles à Gemini
`gemini-3.8-flash`, avant les corrections locales lorsqu'elles sont conservées.
Pour les photos anciennes, une preuve de préparation correspondant à la photo
courante permet de retrouver l'original ; sinon cette limite est signalée.
Le téléversement seul ne déclenche aucun appel Gemini.

La proposition décrit les défauts du recto et du verso, la qualité des photos et
les limites de l'examen. Elle peut être **indéterminable**. NM exige deux faces
exploitables et les versions avant correction. Un verso absent laisse une
évaluation partielle. La proposition ne remplace pas l'état enregistré, même
déjà vérifié, et ne modifie aucun prix.

Pour retenir un état, choisir **État retenu après examen**, confirmer l'examen
de la carte en main et cliquer sur **Enregistrer l'état vérifié**. La validation
peut retenir une autre catégorie que celle proposée. Elle conserve le lien à
l'évaluation et son motif dans l'historique. Si une photo a changé, la proposition
est obsolète et exige une nouvelle évaluation avant cette validation.

Les originaux, versos et réponses d'évaluation sont inclus dans les sauvegardes.
Le JSON conserve la provenance complète ; l'HTML autonome contient les deux
faces, avec l'état enregistré et son statut de confirmation. Le [document de
conception](CONDITION-ASSESSMENT.md) précise le protocole et les protections.

Les préparations sont privées, limitées et gardées en mémoire pendant 30 minutes.
Un redémarrage du serveur les efface ; elles ne constituent pas du stock. Seules
les cartes enregistrées et leurs photos entrent dans les sauvegardes. Les photos
acceptées sont JPEG, PNG ou WebP, jusqu'à 8 Mo et 24 mégapixels.

## Source de vérité et import

La base devient la source de vérité des modifications faites dans l'application.
Les CSV, checkpoints, corrections et photos des albums restent les sources
initiales archivées ; l'application ne les modifie pas.

Un UUID est attribué à chaque pochette importée et conservé ensuite, même si
l'exemplaire change d'album ou d'emplacement. La clé d'origine et la ligne source
complète restent associées à cet UUID. Les cartes hors catalogue restent
manuelles ; les candidats d'une identité non résolue sont conservés dans la
provenance, sans identifiant ni prix confirmé dans la fiche courante.

Relancer l'import du même manifeste n'ajoute aucun doublon et n'écrase aucune
correction de l'application. Des changements dans les sources sont signalés par
`source_changed`, sans fusion automatique. Un nouveau nom de fichier ou nouvel
identifiant d'album produit une nouvelle clé d'origine : ne pas réimporter un
album rephotographié sans établir la correspondance avec ses exemplaires actuels.
Les nouveaux albums peuvent être ajoutés au manifeste puis importés.

Pour exporter les **corrections actuelles**, utiliser l'application ou les
commandes `pokeprice-manage export`, plutôt que la commande historique `library`,
qui relit les rapports d'origine.

```bash
uv run --extra web pokeprice-manage status
uv run --extra web pokeprice-manage export html outputs/collection-geree.html
uv run --extra web pokeprice-manage export json outputs/collection-geree.json
uv run --extra web pokeprice-manage export csv outputs/collection-geree.csv
```

Les sorties doivent être nouvelles. Le CSV protège les cellules textuelles qui
commencent par un caractère de formule ; le JSON reste l'export fidèle complet.
L'export HTML contient les photos et le statut de stock dans les notes, mais pas
l'historique détaillé des ventes ni la gestion hors connexion.

## Sauvegarder et restaurer

```bash
# Sans chemin : nouvelle archive datée dans data/backups/.
uv run --extra web pokeprice-manage backup
uv run --extra web pokeprice-manage backup outputs/collection-backup.zip
uv run --extra web pokeprice-manage --data /tmp/collection-restauree restore outputs/collection-backup.zip
uv run --extra web pokeprice-manage --data /tmp/collection-restauree status
```

La restauration exige un dossier inexistant, vérifie les hashes, l'intégrité
SQLite, les relations et les photos. Les comptes et hashes de mots de passe sont
restaurés ; les sessions sont fermées. Conserver les ZIP privés, avec une copie
hors de l'appareil. Aucune synchronisation Drive n'a été configurée.

Le mécanisme de sauvegarde utilise l'[API SQLite](https://www.sqlite.org/backup.html),
et non une copie à chaud du fichier principal. Les photos sont stockées sous leur
hash, sans réécriture : le ZIP inclut les anciennes photos utiles à l'historique.
L'[instantané initial](RECOVERY.md) conserve en plus les pages originales des
albums et le pipeline. Les nouvelles captures de sources excluent désormais
`data/` et `outputs/development/` ; sauvegarder la gestion avec la commande dédiée.

**Avant chaque migration de schéma**, l'application copie d'abord la base telle
quelle dans `data/backups/before-schemaN-fromM-<date>.sqlite3` (fichier SQLite
unique, privé, intégrité vérifiée). Si la copie échoue, la base n'est pas
migrée et l'application ne démarre pas. Les photos ne sont pas copiées : aucune
migration ne les modifie. Toute commande qui ouvre la base (y compris `backup`)
déclenche la migration ; c'est cette copie qui conserve l'état précédent. Ces
fichiers ne sont pas purgés avec les sauvegardes quotidiennes.

## Validation de cette version

Les 401 exemplaires ont été importés, puis réimportés : **0 ajout, 401 reconnus**.
Les comptes sont 111 / 110 / 180 par album, 347 éditions, 400 identités confirmées,
22 confirmées sans prix et une non résolue. Les 401 vignettes sont identiques à
celles de la bibliothèque initiale. Les sources des albums restent inchangées.

Preuves : [premier import](../outputs/inventory-import-2026-10-04.json),
[réimport](../outputs/inventory-reimport-2026-10-04.json),
[audit de rapprochement](../outputs/development/import-validation.json),
[exercice de restauration](../outputs/development/managed-recovery-check.json).

Les **147 tests passent**, dont l'inscription depuis l'adresse Wi-Fi et la
gestion des réponses HTTP vides ou illisibles. La sauvegarde finale a été restaurée dans une base
distincte au schéma 4 : les dix tables métier et les 401 photos sont identiques.
Les essais d'interface ont été faits sur une copie ; ils n'ajoutent aucun compte,
lot ou mouvement de stock dans la collection réelle. Le propriétaire a depuis créé son
compte pour les essais Android et l'accès distant.

```bash
uv run --extra web --extra dev pytest
uv run --extra web python scripts/verify_inventory_import.py
```

L'audit d'import est prévu avant les premières modifications ; il compare les
références, PV, langues, variantes, statuts, corrections, prix et photos à la
bibliothèque initiale. Les tests couvrent également les droits, les photos
privées, les demandes depuis une autre origine, les conflits de versions, la
révocation d'accès, les réservations concurrentes, annulations, retours et
remboursements, les archives corrompues et la restauration.

Les parcours de connexion, correction/déplacement, création d'un lot,
réservation, vente et retour ont été exercés dans le navigateur sur une copie.
Le nouveau parcours de lot a également été vérifié le 5 octobre : sélection
conservée entre pages et recherches, retrait individuel, récapitulatif mobile,
enregistrement en brouillon et disponibilité inchangée des cartes choisies.
Le rendu mobile a été vérifié dans le navigateur, puis le propriétaire a confirmé un test
concluant sur Android réel via le Wi-Fi le 4 octobre 2026. Le parcours caméra
a été confirmé par le propriétaire le 5 octobre. Le propriétaire a ensuite confirmé le fonctionnement
attendu des nouveaux réglages photo sur Android réel le même jour.
Le 5 octobre, la saisie assistée a été testée
sur une copie ; une lecture Gemini réelle de Gourgeist a retrouvé `077/203`,
anglais, 120 PV et la recherche catalogue a proposé Evolving Skies. Les essais
du navigateur réutilisent cette réponse réelle pour éviter des générations
supplémentaires. Les nouvelles vérifications couvrent les photos de préparation
privées, le mode manuel, les confirmations modifiées, la reprise sans doublon,
les conflits de fiche et la conservation de la provenance.
Les filtres au rafraîchissement et au retour navigateur, les agrandissements et
la comparaison sur écran étroit ont été vérifiés sur une copie. Le dialogue
caméra et son téléversement de secours ont été exercés sur ordinateur. Le propriétaire a
confirmé la capture par webcam réelle le 5 octobre 2026.
Le parcours verso/évaluation a été vérifié sur une copie avec des observations
explicitement simulées. Une requête Gemini réelle sur deux mires synthétiques a
validé le format de réponse et reconnu l'absence de carte réelle. L'essai de
gradation sur une photo privée reste à autoriser séparément. Les tests couvrent
également la migration 4→5, la conservation des originaux, les propositions
obsolètes, la concurrence et la restauration des versos et évaluations.
Le propriétaire confirme également le fonctionnement attendu du parcours photo Android
verso/état le 5 octobre. Cette confirmation d'usage et la validation du format
sur mires synthétiques restent distinctes d'une évaluation de la fiabilité des
états proposés sur un échantillon de cartes réelles.
Il n'y a pas encore de rapprochement automatique de sources modifiées, de suivi bancaire
ou de catalogue public. Le déploiement Internet est préparé dans
[DEPLOYMENT.md](DEPLOYMENT.md) ; le tunnel de développement reste temporaire.


## Six prochains classeurs : améliorations du 5 octobre

Depuis la Collection, **Saisie en série** conserve l'album, la page et la
pochette. Choisir le format de page (9 pochettes par défaut), prendre ou
importer le recto et éventuellement le verso, puis vérifier les champs.
**Enregistrer et passer à la suivante** crée un seul exemplaire et propose
la pochette suivante ; après la dernière, la page suivante est proposée.
Les champs et photos non validés restent conservés pendant 30 jours.
Un rafraîchissement, une fermeture ou un redémarrage permettent de reprendre
la série. Mettre en pause conserve le brouillon ; terminer la série libère
ses préparations. La lecture Gemini reste déclenchée explicitement.

Une même photo de recto ou un emplacement occupé produit une alerte. Ouvrir
la fiche existante, ou confirmer un exemplaire physique distinct. Les deux
exemplaires restent séparés. Les alertes sont revérifiées pendant l'écriture.
Un double appui ou une réponse perdue ne crée pas une deuxième carte.

**Afficher → Éditions et quantités** regroupe les exemplaires sans les fusionner.
Les filtres et cette vue restent dans l'URL. Les compteurs de stock portent sur
l'édition entière ; les exemplaires affichés respectent les filtres.

Cocher jusqu'à 20 exemplaires puis **Préparer les photos sélectionnées** :
simuler les réglages recto ou verso, agrandir les comparaisons et cocher les
résultats souhaités. L'application crée une sauvegarde avant remplacement.
**Annuler ce traitement** et les vingt derniers traitements se retrouvent dans
**Photos par lot**, même sans sélectionner de carte ; une fiche modifiée depuis l'application du lot bloque son
annulation. Sans photo originale conservée, la simulation signale qu'elle
utilise l'image actuelle. Aucun modèle ni service de prix n'est appelé.

Dans **Ventes**, chaque lot propose **Télécharger le brouillon d'annonce** :
texte modifiable, photos recto/verso et informations à compléter. Les notes
privées et détails financiers de gestion sont exclus. Ce téléchargement ne
change pas le stock. Le prix demandé du lot est repris s'il existe ; l'état
physique non confirmé est indiqué comme à vérifier.

**Gestion → Sauvegardes** donne les dates locale et Drive, les erreurs et la
commande de sauvegarde manuelle. Voir [DAILY-BACKUPS.md](DAILY-BACKUPS.md) pour
la planification et les limites de contrôle de la copie externe.

Réception : tests sur bases temporaires, reprise et rollover Chrome après F5,
vue par édition avec filtre et URL, rendu mobile à 390 × 844 sans débordement,
statut visible sur HTTPS. Les photos et leur persistance recto/verso passent
les tests API. L'essai de téléversement automatisé dans Chrome est empêché
par l'accès aux URL de fichiers désactivé dans l'extension ; le nouveau
parcours série sur Android matériel reste à confirmer par le propriétaire.
