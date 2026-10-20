# Proposition — M1.1 : référentiel embarqué des impressions

> **Archive.** Proposition d'origine du référentiel des impressions, précisée ensuite par le [contrat](../PRINT_REFERENCE_CONTRACT.md). Le fonctionnement actuel est décrit dans le [guide du référentiel](../PRINT_REFERENCE_GUIDE.md). Le texte ci-dessous est conservé tel qu'il était ; seuls les liens ont été mis à jour.

Statut : proposition du 13 octobre 2026, contrat précisé après consultation,
non implémentée. Le comportement à livrer est défini dans
[PRINT_REFERENCE_CONTRACT.md](../PRINT_REFERENCE_CONTRACT.md) ; ce document
conserve le contexte et le périmètre de la proposition.

## Résultat recherché

Sur un périmètre documenté, une carte décrite « illustration holo + tampon
EX Deoxys » doit être reconnue comme une parallèle reverse et utiliser sa
correspondance de prix vérifiée, sans nouvelle exception dans le code.
Une holo d’origine utilise Standard lorsque cette correspondance est établie.
Les observations physiques et leur confirmation restent attribuées au propriétaire.

Le moteur doit accompagner les **six albums restant à scanner**. La collection
actuelle est un échantillon de départ, pas une limite de couverture. Une nouvelle
édition s’ajoute au référentiel par des données et des preuves, sans modifier le
moteur de classement.

Je recommande de livrer ce socle avant M2. Les vérifications IA pourront ensuite
comparer une observation aux impressions documentées. *Décision du 13 octobre
après revue : le socle est livré en audit, mais M1.1 ne bloque plus M2 ; voir
la [roadmap](../ROADMAP.md).* L’enrichissement du
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
documents originaux sont archivés une fois par empreinte, hors du paquet,
et inclus dans la procédure de sauvegarde ; leurs références et les faits
vérifiés accompagnent les règles.
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

Le calcul part d’un ensemble d’impressions possibles ; les observations
réduisent cet ensemble. Le prix exige une seule correspondance marchande
vérifiée pour toutes les possibilités restantes, même si l’impression précise
reste indéterminée. Un unique candidat connu dans une liste partielle ne suffit
pas. Les états de résolution et l’identité de prix sont définis dans le contrat.
Une règle embarquée vérifiée applicable prime sur les indications plus faibles
de TCGdex.
Le désaccord reste visible et ne réécrit pas l’observation humaine.

| Situation | Comportement proposé |
|---|---|
| Une impression est établie avec correspondance vérifiée | Impression et correspondance calculées, avec explication et source |
| Plusieurs impressions partagent la même correspondance vérifiée | Prix commun utilisable ; l’impression précise n’est pas inventée |
| Impression reconnue, correspondance manquante | Impression conservée ; prix vérifié inconnu |
| Plusieurs impressions impliquent des correspondances différentes | Choix guidé entre ces impressions ; prix indéterminé tant que le choix manque |
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

Pour les nouvelles observations, `stamp_state` distingue tampon non examiné,
absence constatée et présence constatée. Les anciens champs vides et
confirmations restent conservés avec leur provenance ; aucune absence de tampon n’est
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
Ce travail se fait par lot d’éditions, hors du parcours de scan du propriétaire.

Ajouter une édition nécessite une entrée de données et sa validation. Les
modifications du moteur sont réservées à une caractéristique physique ou
commerciale qu’il ne sait réellement pas représenter.

La couverture progresse selon trois priorités : les ambiguïtés ayant un impact
sur le prix, les éditions nombreuses dans les albums, puis les cas isolés.
Le tableau de couverture donne les éditions documentées, partielles et
provisoires, ainsi que le nombre d’exemplaires concernés. Le pourcentage est
recalculé après chaque import : il ne constitue pas une promesse de couverture
des albums encore inconnus.

## Livraison avant M2

**1. Observations et contrat.** Stabiliser les discriminants à capturer avant
les six scans, l’identité de prix et les sorties du résolveur. Le contrat définit
20 scénarios de réception, dont les précisions compatibles et le changement de
produit malgré une même étiquette Foil.

**2. Moteur commun.** Livrer le moteur pur et l’adaptateur des usages actuels,
avec des fixtures synthétiques ; la sauvegarde physique ne dépend pas de la
couverture du référentiel.

**3. Règles et première couverture.** Transférer les règles justifiées et
formaliser les cas Roigada, Pikachu, Grainipiot, Manaphy, Baggaïd, Celebi et
Barboach. Les huit groupes sont le premier banc de régression. Chaque entrée
doit avoir ses preuves d’impression et de marché, sur ses numéros et langues.
Les preuves manquantes restent signalées ; le comportement actuel ne vaut pas
preuve. Le paquet installé est contrôlé hors du dépôt et hors ligne.

**4. Audit et extension.** Rejouer les fiches en lecture seule, établir le
rapport avant/après, puis migrer et activer après contrôle de sauvegarde et
restauration. Étendre les règles pendant les six scans. M2 confronte ses
propositions aux candidats et aux preuves de ce contrat.

L’audit distingue les catégories inchangées, les catégories à corriger, les
correspondances de prix modifiées, les ambiguïtés et les périmètres non couverts.
Une mise à jour du référentiel ne change pas les confirmations physiques.
Toute correction appliquée à une fiche garde l’auteur, le motif, la version
du référentiel et l’historique. Une cotation incompatible est suspendue,
conservée avec source et date et exclue des valeurs. Une précision compatible
ne l’efface pas. Sans cotation compatible justifiée, un nouveau relevé est
nécessaire ; le prix d’une autre correspondance n’est jamais transféré.

Sauvegarde avant toute migration ; validation sur une restauration temporaire.
La proposition actuelle ne modifie aucune fiche et ne déclenche aucun scan.

## Critères de réception

La réception détaillée et les invariants sont dans
[le contrat M1.1](../PRINT_REFERENCE_CONTRACT.md#9-livraison-et-réception), scénarios
**C01–C20**. Les exigences suivantes en résument le périmètre.

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
La revue de design ne certifie pas ces pièces ni leur portée linguistique :
leur vérification reste une étape explicite de la première couverture.
