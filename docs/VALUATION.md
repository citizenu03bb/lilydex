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

Une correction d’identité ou de variante retire le relevé courant du calcul
jusqu’au prochain relevé. Les données historiques restent conservées.

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

La file contient les cartes dont la valeur en jeu atteint le seuil, les
identités incertaines et les prix prudents incomplets qui empêchent de décider.
Une reverse connue mais sans prix reste à examiner. Une métrique partielle
connue sous le seuil ne suffit pas à imposer l’examen de cette variante : son
minimum éventuel ne peut pas dépasser cette métrique.

Les motifs expliquent le contrôle : carte de valeur, variante à forte prime
(au moins ×3), reverse ou variante spéciale, marché instable (écart d’au moins
×2 entre tendance et moyennes), identité incertaine, prix incomplet, état non
validé. Les motifs d’état et de marché concernent les cartes de valeur : les
états importés non validés ne remplissent pas à eux seuls toute la file.

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
