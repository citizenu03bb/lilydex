# Proposition — M1.1 : référentiel embarqué des impressions

Statut : proposition du 13 octobre 2026, non implémentée.

## Résultat recherché

Une carte décrite « illustration holo + tampon EX Deoxys » doit être reconnue
comme une parallèle reverse et utiliser sa cotation Foil, sans nouvelle
exception dans le code. Une holo d’origine doit utiliser la cotation Standard.
Les observations physiques et leur confirmation restent attribuées à Pat.

Le moteur doit accompagner les **six albums restant à scanner**. La collection
actuelle est un échantillon de départ, pas une limite de couverture. Une nouvelle
édition s’ajoute au référentiel par des données et des preuves, sans modifier le
moteur de classement.

Je recommande de livrer ce socle avant M2. Les vérifications IA pourront ensuite
comparer une observation aux impressions documentées. L’enrichissement du
référentiel se poursuivra avec les imports de M3.

## État observé

Audit local en lecture seule le 13 octobre 2026, à 01:34 heure de Paris :

- 404 exemplaires actifs, dont 399 avec un identifiant catalogue ;
- 66 groupes d’éditions selon les préfixes des identifiants catalogue ;
- 57 finitions renseignées et 347 encore non renseignées ;
- huit premiers groupes de régression couvrant 27 exemplaires : EX Légendes
  Oubliées, EX Deoxys, EX Fantômes Holon, EX Gardiens de Cristal, Indomptable,
  Destinées Futures, POP Série 9 et Promo Nintendo.

Ces chiffres ne préjugent ni du volume ni des éditions des six futurs albums.
Le détail reproductible est conservé dans
`outputs/development/variant-reference-scope-2026-10-13.json`.

Actuellement, quelques règles d’édition sont codées dans `variant_pricing.py`.
Les autres décisions utilisent les indicateurs TCGdex ou les impressions
présentes dans ses données de prix. Cela explique les corrections successives
et la dépendance à des métadonnées parfois incomplètes.

## Trois informations distinctes

| Information | Autorité et conservation |
|---|---|
| Impressions possibles d’une édition | Référentiel documenté, avec source, périmètre et version |
| Caractéristiques de l’exemplaire | Observation physique et confirmation humaine déjà conservées |
| Correspondance avec un produit et sa cotation | Règle de marché documentée, puis relevé daté Cardmarket/TCGdex ou manuel |

Une liste officielle peut établir « une version mate et une parallèle
brillante ». La traduction en produit Cardmarket, filtre et champ de cotation
doit également être vérifiée. Une source anglaise ne valide pas automatiquement
toutes les impressions françaises, italiennes ou japonaises.

Les listes consultées constituent des preuves sur leur périmètre. Une liste
incomplète ne permet pas de déclarer qu’une promo ou une réimpression n’existe
pas.

## Référentiel livré avec l’application

Le référentiel serait un ensemble de fichiers JSON dans
`src/pokeprice/data/print_reference/`, inclus dans le paquet installé. Le moteur
resterait dans un module Python commun à la fiche, la liste, la saisie, la CLI,
la valorisation et les exports. Aucun accès réseau ne serait nécessaire pour
appliquer une règle embarquée.

Chaque entrée décrit :

- l’édition, les numéros exacts ou la plage documentée et les langues couvertes ;
- les impressions identifiées : mate, holo d’origine, reverse, holo parallèle,
  promo particulière, avec un identifiant stable d’impression ;
- les indices physiques utilisables : zone brillante, tampon, marque de produit ;
- la correspondance de prix : produit, catégorie, filtre et champ de cotation,
  lorsqu’ils sont établis ;
- les sources de chaque affirmation, la date de vérification et l’empreinte du
  document consulté ;
- une couverture explicite : complète pour un périmètre donné, partielle ou
  encore provisoire.

Le paquet comporte une version de schéma et une version de contenu. Les
documents originaux sont archivés localement et inclus dans la procédure de
sauvegarde ; leurs références et les faits vérifiés accompagnent les règles.
Les versions de règles utilisées sont conservées avec leur empreinte pour
pouvoir expliquer une décision ancienne après une mise à jour. La sauvegarde
et la restauration devront donc inclure ces archives de référence.
Les photos privées d’exemplaires restent dans la collection.

Standard/Foil devient une projection de l’impression et de sa correspondance
de marché. Le booléen historique `foil` peut être conservé pour la compatibilité,
mais ne suffit plus à choisir tous les produits ou filtres. En particulier,
« holo parallèle » ne doit pas entraîner mécaniquement le filtre
`isReverseHolo=Y` : ce filtre appartient à la correspondance de marché vérifiée.

## Résolution et interface

Le calcul prend l’édition identifiée, les observations et le référentiel. Une
règle embarquée vérifiée prime sur les indications contradictoires de TCGdex.
Le désaccord reste visible et ne réécrit pas l’observation humaine.

| Situation | Comportement proposé |
|---|---|
| Une impression correspond | Impression et catégorie de prix calculées, avec explication et source |
| Plusieurs impressions partagent la même cotation vérifiée | Catégorie commune utilisable ; l’impression précise n’est pas inventée |
| Plusieurs impressions impliquent des cotations différentes | Choix guidé entre ces impressions ; prix indéterminé tant que le choix manque |
| Édition ou langue non couverte | Proposition catalogue explicitement provisoire ; demande d’enrichissement regroupée par édition |
| Observation hors du périmètre documenté | Conservation de l’observation et option « Autre impression / non répertoriée » |

TCGdex reste utile pour les identités, les propositions et les relevés. Il ne
peut pas remplacer silencieusement une règle embarquée vérifiée. Une proposition
provisoire ne devient pas une preuve officielle parce qu’elle est mise en cache.
Une catégorie ambiguë continue à exclure le prix des valeurs calculées.

La saisie montre par exemple :

> Impression reconnue : reverse tamponnée EX Deoxys.
> Catégorie de prix : Foil. Source : référentiel embarqué, version affichée.

L’utilisateur renseigne la finition et le tampon ; il n’a pas à arbitrer
Standard/Foil pour une impression reconnue. Si plusieurs impressions restent
possibles, la fiche demande le détail qui les distingue, avec des libellés
concrets. Une remarque libre ne valide plus à elle seule une correspondance
de prix : il faut un produit ou une impression identifié et une source.

Pour les nouvelles observations, « tampon non vérifié » et « aucun tampon
observé » doivent être distingués. Les anciens champs vides et confirmations
restent conservés avec leur provenance ; aucune absence de tampon n’est
inventée lors de la migration.

La sauvegarde d’une observation physique reste possible hors ligne, sans prix
ou sans couverture du référentiel. Une impression reconnue peut avoir un prix
inconnu ; c’est le cas rencontré avec Celebi.

## Enrichissement pour les six albums

L’import ou l’identification d’une nouvelle édition crée une entrée dans une
file de **couverture du référentiel**, distincte des vérifications physiques de
chaque carte. Cette file regroupe les besoins par édition et langue.

Un outil de préparation récupère les sources disponibles et produit un brouillon
de règles. L’extraction d’un PDF ou les données TCGdex ne publient pas
automatiquement une règle vérifiée. Les faits, les limites de numéros, les
langues et les correspondances de marché sont contrôlés avant intégration.
Ce travail se fait par lot d’éditions, hors du parcours de scan de Pat.

Ajouter une édition nécessite une entrée de données et sa validation. Les
modifications du moteur sont réservées à une caractéristique physique ou
commerciale qu’il ne sait réellement pas représenter.

La couverture progresse selon trois priorités : les ambiguïtés ayant un impact
sur le prix, les éditions nombreuses dans les albums, puis les cas isolés.
Le tableau de couverture donne les éditions documentées, partielles et
provisoires, ainsi que le nombre d’exemplaires concernés. Le pourcentage est
recalculé après chaque import : il ne constitue pas une promesse de couverture
des albums encore inconnus.

## Livraison en deux étapes

**1. Moteur et première couverture.** Définir le format, transférer les règles
actuelles, formaliser les cas Roigada, Pikachu, Grainipiot, Manaphy, Baggaïd,
Celebi et Barboach, et afficher la provenance. Les huit groupes identifiés sont
le premier banc de régression ; chaque entrée ne couvre que les impressions
et langues effectivement documentées. Les preuves manquantes restent signalées.

**2. Audit et extension.** Rejouer toutes les fiches en lecture seule, établir
un rapport avant/après, puis étendre les règles aux éditions déjà présentes
et aux nouvelles éditions découvertes pendant les six scans. Faire évoluer M2
pour confronter ses propositions à ce référentiel et afficher les contradictions.

L’audit distingue les catégories inchangées, les catégories à corriger, les
correspondances de prix modifiées, les ambiguïtés et les périmètres non couverts.
Une mise à jour du référentiel ne change pas les confirmations physiques.
Toute correction appliquée à une fiche garde l’auteur, le motif, la version
du référentiel et l’historique. Un changement de correspondance de prix invalide
la cotation courante et exige un nouveau relevé ; il ne réutilise pas le prix
d’une autre impression.

Sauvegarde avant toute migration ; validation sur une restauration temporaire.
La proposition actuelle ne modifie aucune fiche et ne déclenche aucun scan.

## Critères de réception

- Les cas de régression donnent la bonne catégorie avec les appels réseau coupés.
- Une donnée TCGdex contradictoire ne modifie pas une règle embarquée vérifiée.
- Les plages, exceptions et langues non couvertes ne sont pas extrapolées.
- Les données du référentiel sont présentes dans le paquet installé, et chaque
  décision affiche sa version et ses sources.
- Fiche, aperçu, CLI, relevé, totaux et export utilisent le même moteur et la
  même correspondance de prix.
- Les ambiguïtés et prix absents sont visibles ; un prix absent reste inconnu.
- L’audit de migration conserve les observations, auteurs et dates de
  confirmation ; aucune finition n’est créée à partir de l’ancienne catégorie.
- Une édition nouvellement découverte peut être saisie puis enrichie par des
  données, sans nouvelle branche conditionnelle propre à cette édition.

## Sources de départ

- [EX Deoxys — liste officielle Pokémon](https://assets.pokemon.com/assets/cms/pdf/tcg/checklists/deoxys_checklist.pdf)
- [EX Fantômes Holon — liste officielle Pokémon](https://assets.pokemon.com/assets/cms/pdf/tcg/checklists/holonphantoms_checklist.pdf)
- [EX Gardiens de Cristal — liste officielle Pokémon](https://assets.pokemon.com/assets/cms/pdf/tcg/checklists/crystalguardians_checklist.pdf)
- [Indomptable — liste officielle Pokémon](https://assets.pokemon.com/assets/cms2/pdf/trading-card-game/checklist/hgss3_web_cardlist_en.pdf)
- [Destinées Futures — liste officielle Pokémon](https://assets.pokemon.com/assets/cms2/pdf/trading-card-game/checklist/bw4_web_cardlist_en.pdf)

Les promos, kits et parallèles particulières demandent aussi leurs preuves
de produit. Leur présence dans une API ne suffit pas à certifier l’exhaustivité
des impressions ou leur correspondance de marché.
