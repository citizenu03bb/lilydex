# Valeur en jeu et file d'examen

> **Pour qui :** toute personne qui veut comprendre pourquoi une carte est envoyée en examen, et comment se calculent les valeurs affichées.
> **Vous y trouverez :** le calcul de la valeur prudente et de la valeur en jeu, les cas particuliers, la file « À examiner », les trois totaux et la commande qui vérifie la file.
> **Statut :** en vigueur. Ces règles forment le jalon M1 de la [feuille de route](ROADMAP.md).

Le temps humain doit aller aux cartes où une erreur coûterait de l'argent.
L'application calcule donc, pour chaque exemplaire, ce qu'il pourrait valoir au plus
compte tenu de ce qui reste incertain, et envoie en examen les cartes dont
l'enjeu dépasse un seuil.

## Le seuil

Le seuil vaut **10 €** par défaut, réglable dans la collection de 0,01 à
10 000 €. Le filtre **Examen → À examiner** et le seuil restent dans l'adresse
(`?review=needed&threshold=10&sort=binder`), avec les autres filtres, la
pagination et l'affichage par exemplaire ou par édition.

## Le calcul

Pour chaque variante, Standard ou Foil, du dernier relevé TCGdex valide :

`prix prudent = min(tendance, moyenne à 30 jours)`

Les deux mesures sont nécessaires. Une absence, une valeur négative ou non
finie, ou une devise autre que l'euro laisse le prix inconnu ; un vrai prix nul
reste zéro. Les moyennes à 1 et 7 jours servent seulement à signaler
l'instabilité du marché.

La **valeur en jeu** est le plus haut prix prudent parmi les variantes et les
éditions candidates encore plausibles. Elle sert à repérer les contrôles
utiles, pas à fixer un prix.

- **Après confirmation physique de la variante**, seule la catégorie retenue
  reste plausible : une autre variante plus chère ne gonfle plus la valeur en
  jeu.
- **Pour une identité incertaine**, seule la dernière recherche qui correspond
  au nom, à la référence, à la langue et aux PV actuels fournit les candidats.
  Leurs prix viennent du détail TCGdex obtenu lors de la recherche, ou d'un
  relevé plus récent de la même édition et de la même langue. Les rapports
  d'origine peuvent fournir un candidat, avec leurs limites. Un candidat sans
  prix complet rend la valeur en jeu incomplète.
- **Les consultations restent locales** : la liste, le résumé et les fiches ne
  déclenchent ni relevé de prix ni recherche dans le catalogue. Les prix des
  candidats restent séparés des références et des totaux.

### Une carte sans cotation TCGdex

Quand TCGdex ne donne pas la cote d'une carte, le relevé la cherche dans le
**guide des prix officiel de Cardmarket**, un fichier public mis à jour chaque
jour. Le produit est celui que donne TCGdex, ou la seule carte de la même
extension qui porte le même nom anglais et les mêmes attaques et pouvoirs. Le
relevé indique alors la source « Cardmarket · guide des prix », la date du
fichier, le produit et la méthode ; c'est une cote comme une autre, pas une
valeur manuelle ([fiche 0016](decisions/0016-guide-des-prix-cardmarket.md)).

Quand ni TCGdex ni le guide ne fournissent de prix prudent pour la catégorie de l'exemplaire
(carte sans cotation Cardmarket, comme les promos Nintendo ou certains Zarbi),
une référence saisie à la main, datée et sourcée hors TCGdex, en tient lieu. Le
plus souvent, c'est une tendance seule : la valeur reste marquée incomplète,
mais la carte sort du motif « prix à actualiser ». Un prix TCGdex disponible
l'emporte toujours. Le relevé échoue alors avec un message explicite (erreur
422), et la fiche propose une recherche Cardmarket déduite du nom anglais et du
numéro, avec le code imprimé de l'extension quand il est connu (« Darkrai GE 4 »
ouvre directement la bonne page).

### Une énergie de base

Une énergie de base confirmée et sans cotation (Énergie Feu, Fighting
Energy…) est classée **vrac** : elle se vend en lot, sans cote à chercher, et
ne porte pas le motif « prix à actualiser ». Les énergies spéciales, comme la
Double Énergie Incolore, gardent leur recherche de prix ; une énergie de base
cotée garde sa cote ; une énergie seulement proposée par la porte énergie reste
à confirmer ([fiche 0015](decisions/0015-energies-de-base-en-vrac.md)).

### Un produit Cardmarket douteux

TCGdex attribue parfois un même produit Cardmarket à deux cartes d'une
extension (Darkrai GE 3 Lv.38 et GE 4 Lv.40 : produit 277905, celui du Lv.38 ;
de même Airmure BCR 95/96 et Solochi DRX 93/94).
À chaque relevé, les numéros voisins (n-1 et n+1) sont comparés, avec un cache
de 30 jours. Un produit partagé met la carte en examen jusqu'au verdict d'une
personne, qui vaut pour cet identifiant du catalogue et ce produit seulement :

- **vérifié** : le doute est levé ;
- **incorrect** : les prix TCGdex de cette carte sont écartés et ses références
  TCGdex retirées ; le relevé cherche alors le bon produit dans le guide des prix
  Cardmarket (même extension, même nom, mêmes attaques) et n'est refusé que
  s'il ne le trouve pas ; la valeur manuelle prend alors le relais ;
- **annulé** : retour au comportement automatique.

Si TCGdex change de produit, l'ancien verdict ne s'applique plus.

### Une catégorie incompatible avec la finition

La case de confirmation ne valide pas une catégorie incompatible avec la
finition observée. Pour EX Fantômes Holon, numéros 18 à 98, une illustration
holo avec le tampon de l'extension relève de la parallèle Foil, même si le fond
est mat. Une ancienne confirmation en Standard reste dans l'historique, mais
son prix courant sort des valeurs et la carte revient dans la file avec
« catégorie de prix à corriger ». Les cotations des deux catégories comptent
pour le risque jusqu'à la correction. Relevé et estimation de vente sont
bloqués tant que la catégorie est incohérente.

La confirmation de la finition reste enregistrable quand les métadonnées
manquent ou que le produit reste indéterminé ; elle ne valide pas ce prix. Les
métadonnées de finition mises en cache permettent de calculer la catégorie sans
cotation ; elles ne deviennent jamais un prix ni une confirmation humaine.

### Ce qu'une correction change

Une correction d'identité, de tampon ou de catégorie retire le relevé courant
du calcul jusqu'au relevé suivant. Préciser une finition compatible avec le
produit déjà coté conserve sa référence, sa source et sa date ; une finition
ambiguë invalide le prix. L'historique est toujours conservé.

## La file « À examiner »

La file contient les identités incertaines, les prix prudents incomplets et les
examens physiques qui restent à faire. Au-dessus du seuil, la variante, le
tampon et l'état doivent être confirmés. Une carte de valeur dont les
vérifications sont terminées sort de la file ; son badge « Carte de valeur »
reste visible.

Les motifs distinguent l'identité, la variante ou le tampon, l'état et le prix
à actualiser :

- Une divergence de variante signalée par TCGdex exige une vérification
  physique, même sous le seuil ; elle disparaît après la confirmation humaine.
- Une reverse plausible mais sans prix demande un examen. Une mesure partielle
  connue sous le seuil ne suffit pas à imposer l'examen de cette variante : son
  minimum ne peut pas dépasser cette mesure.
- Une prime de variante (au moins ×3) motive le contrôle tant que la variante
  n'est pas confirmée.
- Un marché instable (écart d'au moins ×2 entre la tendance et les moyennes)
  reste une information de prix : il ne rouvre pas l'examen physique.
- Les états importés non validés ne remplissent pas à eux seuls toute la file.
- Une lecture de la finition en désaccord avec la finition ou le tampon notés
  ajoute le motif « Lecture de la finition en désaccord », quel que soit le
  seuil. Une confirmation physique postérieure à cette lecture le lève ; une
  nouvelle lecture toujours en désaccord le rétablit. Une lecture d'une
  ancienne photo du recto ne compte plus.

**La confirmation physique** exige une identité confirmée et une finition
décrite ; la date et l'auteur viennent du serveur. Un changement d'identité, de
langue, de catégorie de prix manuelle, de tampon, de finition ou de recto
l'annule, sauf nouvelle confirmation explicite dans la même correction. Un
déplacement, l'état, les notes et les relevés de prix la conservent. Aucune
ancienne correction ne devient une confirmation physique par déduction.

## Les trois totaux

La collection complète et les résultats filtrés affichent séparément :

- **Tendance** : la dernière tendance de la variante enregistrée et identifiée ;
- **Valeur prudente** : le plus bas entre la tendance et la moyenne à 30 jours
  de cette variante, sans décote d'état ;
- **Estimation de vente** : les dernières offres collées pour l'identité, la
  variante et l'état actuels, hors frais et port.

Chaque montant indique le nombre d'exemplaires couverts, ceux sans prix et
ceux en vrac, comptés à part et sans montant ; un total entièrement inconnu
s'affiche indisponible. Les totaux portent sur tous
les résultats filtrés, avant la pagination, et comptent chaque exemplaire une
fois dans l'affichage par édition.

Une estimation de vente devient ancienne après une correction d'identité, de
variante, de tampon, de langue ou d'état, même annulée ensuite. Elle reste
visible et archivée, mais sort des totaux. Une nouvelle estimation avec de
nouvelles offres la rend courante. La calibration par l'état et les ventes
appartient au jalon M4.

## Vérifier la file

Cette commande audite la file en lecture seule, sans migration ni
modification de la base :

```bash
uv run python scripts/audit_valuation.py \
  --known-edition ex13-78 --known-edition base4-4 \
  --known-edition dp2-122 --known-edition base5-20 \
  --output outputs/development/m1-valuation-audit.json
```

Elle vérifie que les éditions de valeur connues (Pikachu 78/110 `ex13-78`,
Dracaufeu 4/130 `base4-4`, Lucario LV.X 122/123 `dp2-122`, Tortank obscur
20/82 `base5-20`) sont dans la file ou ont été examinées physiquement. Le
détail reste privé dans `outputs/`, que git ignore.

Le script échoue aussi quand la file dépasse 15 % des cartes, le critère
d'origine de M1. La feuille de route a abandonné cette borne : aucun contrôle
n'est masqué pour la respecter, et un échec sur ce seul critère n'est pas une
régression. Les résultats des audits passés sont au [journal](JOURNAL.md).
