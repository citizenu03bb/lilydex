# M1 — Valeur en jeu et examen

Le seuil par défaut est de **10 €**, réglable dans la collection de 0,01 à
10 000 €. Le filtre **Examen → À examiner** et le seuil sont conservés dans
l’URL (`?review=needed&threshold=10&sort=binder`), avec les autres filtres,
la pagination et l’affichage par exemplaire ou par édition.

## Calcul

Pour chaque variante Standard/Foil du dernier relevé TCGdex valide :

`prix prudent = min(tendance, moyenne à 30 jours)`

Les deux métriques sont nécessaires. Une absence, une valeur négative ou non
finie, ou une devise autre que l’euro laisse le prix inconnu. Un vrai prix nul
reste zéro. La valeur en jeu est le maximum prudent des variantes et des
éditions candidates plausibles ; elle sert à repérer les contrôles utiles.
Les moyennes à 1 et 7 jours servent à signaler l’instabilité.

**Valeur manuelle.** Quand TCGdex ne fournit aucun prix prudent pour la
catégorie de l’exemplaire (carte sans cotation Cardmarket, comme les promos
Nintendo ou certains Zarbi), une référence saisie à la main, datée et sourcée
hors TCGdex, en tient lieu. Le plus souvent c’est une tendance seule : la valeur
reste marquée incomplète, mais la carte sort du motif « prix à actualiser ». Un
prix TCGdex disponible l’emporte toujours. Le relevé échoue alors avec un
message explicite (422), et la fiche propose une recherche Cardmarket déduite
du nom anglais et du numéro.

**Produit Cardmarket douteux.** TCGdex attribue parfois un même produit
Cardmarket à deux cartes d’une extension (Darkrai GE 3 Lv.38 et GE 4 Lv.40 :
produit 277905, celui du Lv.38). À chaque relevé, les numéros voisins (n-1,
n+1) sont comparés, avec un cache de 30 jours. Un produit partagé met la carte
en examen jusqu’au verdict d’une personne, qui s’applique à l’identifiant
catalogue et à ce produit seulement :
- **vérifié** : le doute est levé ;
- **incorrect** : les prix TCGdex de cette carte sont écartés et ses références
  TCGdex retirées. Le relevé est refusé, et la valeur manuelle prend le relais ;
- **annulé** : retour au comportement automatique.

Si TCGdex change de produit, l’ancien verdict ne s’applique plus. La recherche
Cardmarket déduite ajoute le code imprimé de l’extension quand il est connu
(« Darkrai GE 4 » ouvre directement la bonne page).

Après confirmation physique de la variante, seule la catégorie de prix retenue
reste une hypothèse plausible. Une autre variante plus chère ne maintient plus
artificiellement la valeur en jeu de l’exemplaire.

Exception : une catégorie de prix incompatible avec la finition observée n’est
pas validée par la simple case de confirmation. Pour EX Fantômes Holon n°18–98,
une illustration holo avec tampon de l’extension relève de la parallèle Foil,
même si le fond est mat. Une ancienne confirmation en Standard reste conservée
dans l’historique, mais son prix courant est exclu des valeurs et la carte
revient dans la file avec « catégorie de prix à corriger ». Les cotations des
deux catégories restent prises en compte pour le risque jusqu’à correction.
Relevé et estimation de vente sont bloqués tant que la catégorie est incohérente.
La confirmation de la finition physique reste enregistrable lorsque les
métadonnées manquent ou que le produit de prix demeure indéterminé. Elle ne
valide pas ce prix. Les métadonnées de finition mises en cache séparément
permettent de calculer la catégorie sans cotation disponible ; elles ne sont
jamais converties en prix ni en confirmation humaine.

Une correction d’identité, de tampon ou de catégorie retire le relevé courant
du calcul jusqu’au prochain relevé. Préciser une finition compatible avec le
produit déjà coté conserve sa référence, sa source et sa date ; une finition
ambiguë invalide le prix. Les données historiques restent conservées.

Pour une identité incertaine, seule la dernière recherche qui correspond au
nom, à la référence, à la langue et aux PV actuels fournit les candidats. Leurs
prix proviennent du détail TCGdex déjà demandé lors de la recherche, ou d’un
relevé plus récent de la même édition et langue déjà conservé. Les rapports
d’origine peuvent fournir une candidature, avec leurs limites explicites.
Un candidat sans prix complet rend la valeur en jeu incomplète.

Les consultations de la liste, du résumé et des fiches restent locales :
elles ne déclenchent ni relevé de prix ni recherche catalogue. Les prix des
candidats restent séparés des références et des totaux de collection.

## File d’examen

La file contient les identités incertaines, les prix prudents incomplets et les
examens physiques restant à faire. Au-dessus du seuil, la variante/tampon et
l’état doivent être confirmés. Une carte de valeur dont les vérifications sont
terminées sort de la file ; son badge « Carte de valeur » reste visible.
Une divergence de variante signalée par TCGdex exige une vérification physique,
même sous le seuil, et disparaît des tâches après confirmation humaine.
Une reverse plausible mais sans prix reste à examiner. Une métrique partielle
connue sous le seuil ne suffit pas à imposer l’examen de cette variante : son
minimum éventuel ne peut pas dépasser cette métrique.

Les motifs distinguent identité, variante/tampon, état et prix à actualiser.
Une prime de variante (au moins ×3) motive le contrôle tant que la variante
n’est pas confirmée. Le marché instable (écart d’au moins ×2 entre tendance et
moyennes) reste une information de prix : il ne rouvre pas l’examen physique.
Les états importés non validés ne remplissent pas à eux seuls toute la file.

La confirmation physique exige une identité confirmée et une finition décrite.
La date et l’auteur viennent du serveur. Les changements d’identité, de langue,
de catégorie de prix manuelle, de tampon, de finition ou de recto l’annulent, sauf nouvelle
confirmation explicite dans la même correction. Déplacement, état, notes et
relevés de prix la conservent. Aucune ancienne correction ne devient une
confirmation physique par déduction.

## Trois totaux

La collection complète et les résultats filtrés affichent séparément :

- **Tendance** : dernière tendance de la variante enregistrée et identifiée.
- **Valeur prudente** : minimum de la tendance et de la moyenne à 30 jours
  pour cette variante, sans décote d’état.
- **Estimation de vente** : dernières offres collées pour l’identité, la
  variante et l’état actuels, hors frais et port.

Chaque montant indique le nombre d’exemplaires couverts et ceux sans prix.
Un total entièrement inconnu est affiché indisponible. Les totaux portent sur
tous les résultats filtrés, avant pagination, et comptent chaque exemplaire
une fois dans l’affichage par édition.

Une estimation de vente devient ancienne après une correction d’identité,
de variante, de tampon, de langue ou d’état, même si la correction est ensuite
annulée. Elle reste visible et archivée, mais sort des totaux. Refaire
l’estimation avec de nouvelles offres la rend courante ; la calibration par
l’état et les ventes appartient à M4.

## Réception

Audit du 12 octobre 2026, en lecture seule sur la collection : **57/405 cartes
(14,07 %)** au seuil de 10 €, sous la limite de 15 %. Les quatre éditions
attendues sont présentes dans la file : Pikachu 78/110 (`ex13-78`),
Dracaufeu/Charizard 4/130 (`base4-4`), Lucario LV.X 122/123 (`dp2-122`) et
Tortank obscur 20/82 (`base5-20`). Les prix incomplets sont inclus dans ce compte.

Commande reproductible (sans migration ni modification de la base) :

```bash
.venv/bin/python scripts/audit_valuation.py \
  --known-edition ex13-78 --known-edition base4-4 \
  --known-edition dp2-122 --known-edition base5-20 \
  --output outputs/development/m1-valuation-audit.json
```

Le JSON détaillé reste privé dans `outputs/`, exclu de Git. L’audit échoue si
une édition attendue manque de la file ou si celle-ci dépasse 15 % ; aucune
carte n’est retirée artificiellement pour atteindre cette limite.
