# Vendre sur Vinted, Leboncoin et Cardmarket

> **Pour qui :** la personne qui met les cartes en vente sur les plateformes, sans connaissance technique.
> **Vous y trouverez :** comment produire des annonces prêtes à poster, ce qu'elles contiennent, les prix, les cartes écartées et ce qui se fait encore à la main.
> **Statut :** en vigueur. Le code est dans `src/pokeprice/marketplace_export.py`.

Tout le stock disponible est à vendre, dans la vitrine et sur les plateformes.
La commande `export_annonces.py` prépare les annonces : il ne reste qu'à
**copier-coller** (Vinted, Leboncoin) ou à **importer un fichier**
(Cardmarket). Elle ne publie rien elle-même : aucune connexion aux
plateformes, aucun envoi automatique. Elle lit la collection sans jamais la
modifier.

## Produire les annonces

La personne qui gère le serveur lance la commande, une fois par plateforme,
en indiquant la collection, la plateforme et un dossier neuf :

```bash
uv run python scripts/export_annonces.py --data /srv/pokeprice/inventory --plateforme vinted --sortie ~/annonces-vinted
```

| Option | Rôle |
|---|---|
| `--data` | Dossier de la collection. Il est ouvert en lecture seule. |
| `--plateforme` | `vinted`, `leboncoin` ou `cardmarket`. |
| `--sortie` | Dossier où écrire les annonces. Il doit être neuf ou vide : rien n'est écrasé. |
| `--marge` | Plancher plus strict pour cet export : pourcentage entier sous la cote de référence, au plus la marge réglée par l'administrateur. Une marge plus large est refusée. Sans l'option, la marge réglée s'applique. Voir [Prix](#prix). |
| `--site` | Adresse publique de la vitrine, pour le lien vers la fiche. Par défaut, celle du serveur (`POKEPRICE_HOST`). |

À la fin, la commande affiche le nombre d'annonces et renvoie vers
`exclues.txt`. Si le dossier de sortie n'est pas vide, elle s'arrête sans rien
écrire : choisissez un autre nom.

## Vinted et Leboncoin : un dossier par annonce

Le dossier de sortie contient un sous-dossier par annonce, numéroté, par
exemple `001-carte-pokemon-evoli-59-111`. Chacun contient :

- `annonce.txt`, découpé en rubriques à recopier dans le formulaire :
  **TITRE**, **PRIX**, **CATÉGORIE CONSEILLÉE**, **DESCRIPTION**, **PHOTOS** et,
  si besoin, **À VÉRIFIER** ;
- les photos à joindre : `recto.jpg` et `verso.jpg` pour une carte,
  `carte01-recto.jpg`, `carte02-recto.jpg`… pour un lot, rectos d'abord.

Pour publier une annonce :

1. Ouvrez le formulaire de dépôt de la plateforme.
2. Joignez les photos du dossier.
3. Copiez le titre, la description et le prix depuis `annonce.txt`.
4. Choisissez la catégorie conseillée.
5. Laissez la plateforme calculer le port : la description n'en fixe pas.
6. Relisez, puis publiez.

La description reprend le nom, l'extension, le numéro, la langue, l'état
confirmé, la variante, le tampon s'il y en a un et, pour une carte ou un lot
de la vitrine, le lien vers sa fiche `/carte/…`. Une carte en stock mais
absente de la vitrine reçoit une annonce sans lien.

| Règle | Vinted | Leboncoin |
|---|---|---|
| Longueur du titre | 50 caractères | 50 caractères |
| Photos jointes | 20 au plus | 10 au plus |
| Arrondi du prix | aux 10 centimes supérieurs | à l'euro supérieur |

Ces limites sont les plus courtes que les vendeurs signalent ; les plateformes
ne les publient pas. Si un formulaire accepte plus, ou moins, corrigez les
constantes `TITLE_MAX`, `PHOTOS_MAX` ou `CATEGORY` en tête du module. Les photos
au-delà de la limite vont dans un sous-dossier `en-plus`, et la rubrique
**À VÉRIFIER** le signale.

## Cardmarket : un fichier d'import de stock

Pour Cardmarket, le dossier de sortie contient `cardmarket-stock.csv`, à
importer depuis l'espace vendeur, rubrique du stock. Une ligne par article :
les exemplaires identiques (même produit, langue, état, variante et prix) sont
réunis sur une ligne avec leur quantité.

| Colonne | Contenu |
|---|---|
| `idProduct` | Identifiant du produit Cardmarket |
| `count` | Quantité |
| `price` | Prix en euros, avec un point (`1.30`) |
| `idLanguage` | Code de langue Cardmarket (1 anglais, 2 français, 3 allemand…) |
| `condition` | État Cardmarket : MT, NM, EX, GD, LP, PL ou PO ; NM/EX devient EX |
| `isReverseHolo` | 1 pour une reverse, sinon 0 |
| `isFirstEd`, `isSigned` | Toujours 0 |
| `comments` | Vide |

Le séparateur est le point-virgule. Les noms et l'ordre des colonnes suivent
les champs d'article du stock Cardmarket. Si la page d'import en demande
d'autres, corrigez `CARDMARKET_COLUMNS` ou `CARDMARKET_DELIMITER` en tête du
module : le reste suit.

L'identifiant produit vient du catalogue enregistré par l'application lors des
relevés de prix. Une carte sans produit connu, ou dont le produit a été jugé
incorrect, est écartée. Cardmarket vend les cartes à l'unité : les lots n'y
sont pas exportés.

## Prix

Le prix part de celui de la vitrine pour une carte ou un lot publiés.
Pour une carte en stock absente de la vitrine, il part du prix proposé par
l'application, selon les règles de la [vitrine](VITRINE.md) : prix manuel,
estimation sur les offres, ou tendance Cardmarket arrondie.

Ce prix ne descend **jamais sous le plancher anti-bradage** : la cote de
référence diminuée de la marge, et jamais moins de 0,50 €. La règle
(`lot_max_margin` et `lot_floor_cents`) est définie une seule fois dans
`src/pokeprice/pricing.py` et partagée avec la vitrine (`listings.py`) et
l'outil de lots (`scripts/pokeprice_lots.py`) : 15 % par défaut, entier borné
de 0 à 50, arrondi au centime supérieur
([décision 0026](decisions/0026-plancher-anti-bradage-gestion.md)). La marge se
lit dans la base, où seul un administrateur la règle depuis la gestion
([décision 0042](decisions/0042-marge-du-plancher-reglage-administrateur.md)).
`--marge` demande un plancher plus strict pour un export : une valeur
inférieure ou égale à la marge réglée est suivie, une valeur supérieure arrête
l'export avec une erreur, sans rien écrire. Pour un lot, la cote est la somme
des cotes de ses cartes. Un prix trop bas est relevé au plancher, puis arrondi
vers le haut au format de la plateforme.

Exemple avec la marge de 15 % : une carte cotée 2,00 € et publiée en
vitrine à 0,60 € part à 1,70 € sur Vinted et à 2 € sur Leboncoin.

La cote de référence est la tendance Cardmarket relevée, ou à défaut le relevé
manuel daté qui la remplace. Sans cote, le plancher ne peut pas être vérifié :
la carte est écartée.

## Cartes écartées

`exclues.txt` liste chaque carte ou lot non exporté, avec la raison :

- identité, état ou variante à confirmer ;
- aucun prix, ou un prix sous 0,50 € : la carte va dans un lot ;
- aucune cote de référence ;
- un lot dont un exemplaire est réservé, vendu ou supprimé ;
- pour Cardmarket : produit inconnu, langue absente, ou lot.

Pour faire entrer une carte écartée, confirmez ce qui manque dans
l'application (voir [Résoudre les cartes en suspens](RESOLUTION_CARTES.md)),
puis relancez l'export dans un dossier neuf.

Les cartes réservées, vendues ou supprimées ne sont pas du stock : elles
n'apparaissent nulle part. Une carte comprise dans un lot publié n'est
proposée qu'avec son lot.

## Après une vente

L'export ne sait pas ce qui se vend sur une plateforme. Quand une carte part,
retirez l'annonce des autres plateformes et de la vitrine, puis enregistrez la
vente dans l'application comme d'habitude. Le prochain export ne la proposera
plus.
