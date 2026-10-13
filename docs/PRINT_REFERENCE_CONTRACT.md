# M1.1 — Contrat des observations, de la résolution et des cotations

Version du contrat : **1**, 13 octobre 2026. **Spécifié, non implémenté.**

Ce document définit le comportement à livrer avant M2. Il précise
[la proposition M1.1](PRINT_REFERENCE_PROPOSAL.md) après la consultation
`20261013-021806-b4b77c1f` (Claude Opus, Gemini, DeepSeek, Mistral).
La consultation a revu le design ; elle n’a pas certifié les faits Pokémon
ni les produits Cardmarket. Les décisions ci-dessous sont celles retenues
pour l’implémentation, avec leurs critères de réception.

## 1. Informations et autorités distinctes

| Information | Contenu et autorité |
|---|---|
| Observation d’exemplaire | Identité, langue, finition, tampon, marques et photos ; provenance de la saisie et attestation humaine distinctes |
| Impression documentée | Impression physique possible sur une édition, des numéros, des langues et, si nécessaire, un produit ou tirage précis |
| Correspondance marchande (`market_binding`) | Produit, variante native, filtres, famille de métriques, devise et population de prix ; preuve de marché propre |
| Résolution | Candidats compatibles avec les observations, informations manquantes, correspondance utilisable, preuves et versions |
| Cotation | Montant d’une métrique datée, lié à sa correspondance, avec source et portée ; aucune observation physique déduite |

Une preuve d’existence d’impression ne vaut pas preuve de produit marchand.
Une observation, une résolution et un relevé ont des provenances séparées.
Une proposition IA ou catalogue ne devient pas une observation humaine parce
qu’elle est sauvegardée. L’état physique et l’estimation de vente restent
distincts de la cotation catalogue.

## 2. Observations à capturer avant les six scans

La première livraison conserve `finish` et ses valeurs actuelles : non
renseigné, mate, illustration holo, cadre holo, reverse, spéciale. Ces valeurs
décrivent ce qui a été observé ; elles ne constituent pas un produit coté.
Une zone non mentionnée ne devient pas automatiquement une zone mate.

Le tampon possède un état explicite :

| `stamp_state` | Signification | Valeur associée |
|---|---|---|
| `unobserved` | Tampon non examiné | Aucun constat d’absence ; un texte hérité peut rester visible |
| `absent` | Absence constatée sur la carte | Pas de valeur de tampon présente |
| `present` | Tampon constaté | Texte ou identifiant de marque non vide, avec provenance |

Les alias servent à comparer un texte au référentiel ; le texte original reste
conservé. Les marques de produit ou de tirage nécessaires à une règle suivent
la même distinction entre inconnu, absence observée et présence observée.
Leur vocabulaire est établi sur les huit familles de régression avant les
scans. Un discriminant n’est demandé que s’il distingue des impressions ou
des correspondances encore plausibles ; aucun formulaire complet n’est exigé
pour sauvegarder une observation partielle.

Une saisie physique et ses photos restent enregistrables hors ligne, sans
couverture du référentiel et sans cotation. Une attestation humaine porte
sur les observations effectivement examinées, pas sur la complétude du
référentiel. Son auteur et sa date viennent du serveur authentifié.

## 3. Périmètre, preuve et couverture

Chaque règle possède un identifiant stable et un périmètre explicite : édition,
numéros exacts ou plages avec exclusions, langues couvertes et, lorsque cela
change les impressions possibles, produit de distribution ou tirage.
Une langue ou un numéro hors périmètre ne bénéficie pas de la règle. Aucune
extension EN → FR/IT/JA n’est implicite.

Les preuves d’impression et de correspondance marchande ont chacune leur
couverture : `complete`, `partial` ou `provisional`, sur leur périmètre exact.
Chaque affirmation utilisée est reliée à un fait extrait, une source, sa date
de consultation, son empreinte et son périmètre. Une affirmation négative
(« aucune autre impression compatible ») demande une preuve ; l’absence
d’une entrée dans une API ou une liste partielle n’en est pas une.

**La complétude requise concerne la décision locale, pas toute l’extension.**
Une couverture partielle conserve un reste inconnu parmi les candidats,
sauf si une preuve clôt le périmètre discriminant exact. Une autre voie
admissible est une preuve couvrant toutes les impressions encore possibles,
y compris ce reste, et établissant une correspondance marchande commune.
Un unique candidat connu dans une liste partielle ne suffit pas à résoudre.

Le validateur refuse les références inexistantes, les périmètres invalides,
les correspondances incomplètes déclarées vérifiées et les chevauchements
contradictoires non déclarés. L’ordre des fichiers ne départage jamais deux
règles contradictoires.

## 4. Identité de prix : `market_binding`

Une correspondance vérifiée contient les dimensions suivantes :

| Dimension | Sémantique |
|---|---|
| `market` | Place de marché native, par exemple Cardmarket |
| `product_ref` | Identifiant de produit dans un espace de noms explicite, justifié par une preuve ; le seul identifiant de carte catalogue ne suffit pas |
| `native_variant` et `filters` | Variante et filtres natifs documentés ; « sans filtre » est explicite, « inconnu » reste distinct |
| `metric_family` | Famille versionnée décrivant les métriques natives, leur sens et leur sélection, par exemple les champs de tendance et de moyenne à 30 jours |
| `currency` | Devise native ; aucune conversion implicite |
| `population` | Portée du relevé : langues, état ou agrégation du marché lorsque ces dimensions s’appliquent |

Ces dimensions déterminent une clé canonique. Un changement de dimension
qui modifie le produit ou la population cotés change cette clé. L’ordre des
filtres, le libellé affiché, l’URL documentaire, l’identifiant d’une règle ou
une nouvelle version apportant la même sémantique ne la changent pas.
Une équivalence d’identifiants demande une preuve et une trace de migration ;
elle ne se déduit pas d’une égalité de montant. Un champ inconnu n’est jamais
un joker autorisant la compatibilité.

`metric_family` distingue notamment les séries Standard et Foil lorsqu’elles
utilisent des champs différents. Chaque cotation précise en plus sa métrique
(`trend`, `avg30`, référence manuelle…), son montant et sa date. Un montant
manuel dont la métrique n’est pas attestée ne devient pas une tendance.

La source d’acquisition (TCGdex ou lecture directe), sa langue demandée et sa
langue réellement servie sont des métadonnées de provenance. Elles sont
séparées de la langue physique et de la population de prix. Un repli EN ne
certifie pas une impression FR ; il ne prouve pas non plus qu’une cotation
explicitement agrégée toutes langues est un prix réservé à l’anglais.

`foil` reste une projection pour les usages compatibles de l’interface. Il ne
détermine ni le produit, ni les filtres, ni les métriques. Une projection
indisponible est `null` ; le booléen hérité peut être affiché comme ancien
classement, mais ne sert pas de justification à une tarification nouvelle.
« Holo parallèle » n’implique jamais à elle seule `isReverseHolo=Y`.

## 5. Contrat du résolveur

### Entrées et pureté

Le moteur reçoit l’identité et son statut de confirmation, les observations
avec leur provenance, une version immuable du référentiel, les contestations
actives et, facultativement, des instantanés catalogue explicitement fournis.
Il ne lit ni réseau ni base, ne prend pas de décision dépendant de l’heure
et n’écrit rien.

Il part de l’ensemble des impressions possibles dans le périmètre. Un indice
observé contradictoire élimine un candidat ; un indice inconnu le conserve.
Une proposition IA non validée ne l’élimine pas. Les candidats et les preuves
de correspondance, avec leur couverture, déterminent les sorties.

### Sorties

Le résultat expose deux états indépendants, afin de distinguer une impression
reconnue sans produit coté de plusieurs impressions partageant un produit :

| `print_status` | Signification |
|---|---|
| `identified` | Une impression est établie dans le périmètre couvert |
| `candidates` | Plusieurs possibilités, ou un reste non documenté, subsistent |
| `unobserved` | Un indice physique manque pour préciser l’impression |
| `uncovered` | Identité, langue ou observation hors du périmètre documenté |
| `conflict` | Preuves fortes contradictoires ou contestation active de la décision |

| `market_status` | Conséquence pour une nouvelle tarification |
|---|---|
| `verified` | Une seule correspondance complète et vérifiée couvre toutes les possibilités restantes |
| `unobserved` | Un discriminant accessible manque pour départager les correspondances |
| `ambiguous` | Des correspondances distinctes restent possibles malgré les indices disponibles |
| `unmapped` | Impression documentée, mais correspondance de marché manquante |
| `uncovered` | Aucun périmètre vérifié applicable |
| `provisional` | Seule une proposition catalogue est disponible |
| `conflict` | Correspondance empêchée par un conflit de preuves ou une contestation active |

Le résultat comporte aussi : `candidate_print_ids`, `unknown_remainder`,
`candidate_binding_keys` et leur association par candidat, `missing_print_observations`,
`missing_market_observations`, `selected_binding_key`, `foil_projection`,
`pricing_eligible`, `warnings`, `conflicts`, `reason_codes`, les preuves utilisées
par candidat et les versions.
Le candidat catalogue provisoire est séparé de `selected_binding_key`.
Chaque conflit indique s’il concerne l’impression, la correspondance ou les
deux. Un conflit portant seulement sur le nom d’impression ne suffit pas à
invalider une correspondance commune par ailleurs démontrée.

Une identité confirmée, un `market_status=verified` et l’absence de conflit
tarifaire sont nécessaires pour `pricing_eligible=true`. Tous les candidats
restants doivent posséder la même clé vérifiée ; un candidat sans correspondance
empêche ce résultat. Un reste inconnu empêche également ce résultat sauf preuve
de correspondance commune couvrant explicitement ce reste. Seule une résolution
éligible produit une clé sélectionnée et peut produire une projection Standard/Foil.

L’impression peut rester indéterminée si sa distinction n’affecte pas la
correspondance. Un indice nécessaire seulement pour nommer l’impression ne
bloque pas le prix commun documenté. Inversement, une attestation physique
complète ne résout pas une correspondance de marché inconnue.

Les situations prioritaires sont les conflits actifs, puis les inconnues du
périmètre ou de la correspondance, puis les discriminants manquants, puis
l’ambiguïté résiduelle. Tous les motifs restent exposés ; une proposition
catalogue ne masque pas une ambiguïté établie par des preuves plus fortes.
Une observation incompatible avec les impressions documentées reste
enregistrée comme non couverte ; elle n’est jamais corrigée automatiquement.

### Désaccords et contestation

Une règle vérifiée applicable prime sur une indication TCGdex plus faible :
le désaccord produit un avertissement sans annuler la règle. Deux preuves
contradictoires de même autorité imposent un conflit ; leur date ou leur ordre
de chargement ne vaut pas arbitrage sans relation de remplacement documentée.

Une contestation locale peut être enregistrée avec auteur authentifié, motif,
date et version attendue. Elle suspend la décision concernée et alimente la
file de couverture. Elle ne crée ni une nouvelle règle vérifiée ni un droit
d’utiliser le prix d’un autre produit. Un relevé ne clôt pas cette contestation.

## 6. Cotation conservée, sélectionnée ou suspendue

Une cotation est une preuve historique immuable : identifiant, correspondance
ou statut hérité, métrique, montant, devise, source, dates de relevé et de source,
portée et instantané d’acquisition. Corriger le relevé crée un nouvel événement
qui le remplace ou le révoque ; l’original demeure consultable.

La sélection courante porte une cotation et la résolution qui l’autorise,
avec auteur ou acteur de maintenance, motif et version de fiche. Une cotation
incompatible est **suspendue**, conservée avec son motif et exclue des valeurs.
La référence enregistrée reste visible avec sa source et sa date, même lorsqu’elle
ne peut pas fournir la valeur prudente de l’exemplaire.

| Changement | Règle de sélection |
|---|---|
| Précision de finition ou de tampon, même correspondance prouvée | Conserver cotation, source et date ; aucun nouveau relevé imposé |
| Même `foil`, autre produit, variante native, série ou population | Suspendre l’ancien prix ; ne jamais le transférer à la nouvelle correspondance |
| Nouvelle version de règles, même correspondance | Conserver le prix ; tracer la nouvelle résolution |
| Ambiguïté, perte de couverture ou contestation | Suspendre la sélection, conserver la preuve historique |
| Nouveau relevé compatible | Sélectionner la nouvelle preuve avec sa date réelle ; ne pas redater l’ancienne |
| Suppression explicite par l’utilisateur | Révoquer la sélection avec provenance ; aucun retour automatique d’un ancien prix |

Un retour vers une ancienne correspondance ne réactive pas à lui seul un prix.
Une restauration doit être auditable et versionnée : compatibilité complète,
absence de révocation ou de relevé plus récent à respecter, source et date
conservées. Le service actuel `price_recovery` reste limité à son cas de
réparation historique ; il ne devient pas une restauration générale sur un
aller-retour de finition.
La compatibilité ne certifie pas la fraîcheur du prix : une référence conservée
ou restaurée garde sa date d’origine et n’est pas présentée comme un relevé nouveau.

Une moyenne à 30 jours n’est jamais inventée à partir d’une référence manuelle.
Le calcul prudent utilise tendance et moyenne à 30 jours de la même
correspondance et d’un même relevé compatible. Il ne combine pas arbitrairement
des métriques de produits, devises, populations ou acquisitions différentes.
Les totaux EUR n’acceptent que des cotations EUR ; les montants en devises
étrangères restent séparés. Une conversion monétaire ou une estimation par
état demanderait un contrat séparé. Les cotations absentes restent inconnues
(`null`), jamais remplacées par zéro.

## 7. Attestations humaines et migration

Le résolveur, le cache, une mise à jour de règle ou un relevé de prix n’écrivent
jamais `finish`, le constat de tampon, `variant_confirmed`,
`variant_verified_at/by` ou la confirmation d’état. Une nouvelle observation
physique suit le parcours de correction et, si elle est confirmée, reçoit
sa propre attestation. Restaurer un prix ne restaure pas une ancienne attestation.

La migration conserve les valeurs, photos, auteurs, dates et historiques
existants. Un champ de tampon vide ne devient pas `absent`. Un texte hérité
non vide reste visible avec sa provenance ; il ne devient `present` que si une
preuve humaine déjà enregistrée atteste ce tampon, avec une trace de migration
vers le nouvel état. Le texte seul ne suffit pas. Sans cette preuve,
`stamp_state` reste `unobserved`. Une ancienne attestation
globale est conservée et présentée comme telle ; elle n’est pas transformée
en attestations nouvelles par discriminant.

Les anciens prix sans correspondance prouvée restent `legacy_unbound` ou
`legacy_manual`, visibles et datés. Une règle nouvelle ne les certifie pas
rétroactivement. Les rattacher nécessite de vérifier les preuves du relevé,
sa métrique, son produit et sa portée, puis d’enregistrer un événement.
Une annotation libre ne suffit pas. Si ces informations manquent, la référence
historique subsiste et la tarification vérifiée reste inconnue.

La migration structurelle ne lance pas de relevé et ne change pas les montants
ou les attestations. Avant activation du nouveau calcul, un audit expose
séparément les prix compatibles, suspendus, hérités non rattachés, inconnus et
les changements de couverture. Les totaux vérifiés affichent leur couverture ;
les références héritées n’y entrent pas silencieusement comme certifiées.
L’affichage de ces différences est validé avant activation pour éviter une
nouvelle disparition inexpliquée de cotation.

Toute écriture appliquée utilise version attendue, acteur authentifié ou de
maintenance identifié, motif et transaction. Un conflit de version impose un
nouvel audit ; il ne déclenche pas un écrasement de la fiche.

## 8. Reproductibilité, paquet et sauvegarde

Le paquet contient les règles JSON, une version de schéma et une version de
contenu avec empreinte. La validation précède leur utilisation. Une version
invalide produit un diagnostic explicite et aucune nouvelle décision vérifiée ;
elle ne provoque pas un remplacement silencieux par des heuristiques réseau.
Les observations et références déjà enregistrées restent consultables.

Une décision conserve version du moteur, version et empreinte des règles,
identifiants des preuves, instantanés des entrées pertinentes et résultat.
Les versions exactes des règles utilisées et leurs faits justificatifs doivent
rester retrouvables après mise à jour et restauration. Une URL et un hash seuls
ne suffisent pas si le contenu disparaît.

Les documents sources sont archivés une fois par empreinte hors du paquet
applicatif, avec un manifeste. Cette archive, les règles historiques et les
traces utilisées entrent dans la sauvegarde portable ; aucun PDF n’est dupliqué
par fiche ou décision. Une pièce manquante est signalée comme preuve indisponible
et ne devient pas une preuve nouvelle par téléchargement non vérifié.
Le contrôle de restauration vérifie le manifeste et rejoue une décision ancienne
avec ses entrées et sa version, indépendamment de la version courante.
Le rejeu utilise la version enregistrée du moteur ou un lecteur de compatibilité
validé par les fixtures de cette version. Les éléments nécessaires sont conservés
dans l’archive de restauration. Une version non disponible ou non reproductible
est signalée ; le moteur courant ne la remplace pas en prétendant avoir confirmé
la décision ancienne.

## 9. Livraison et réception

### Ordre retenu

1. Vocabulaire d’observation, correspondances et états : fixtures synthétiques
   du contrat ; aucun fait métier nouveau déclaré vérifié.
2. Moteur pur et adaptateur pour les usages actuels ; observations explicites
   disponibles avant les six scans, sans obligation de couverture préalable.
3. Règles embarquées et preuves d’impression **et** de marché des huit familles ;
   sources manquantes signalées, paquet installé testé hors du dépôt et hors ligne.
4. Audit à blanc de la collection, puis migration et activation contrôlées après
   sauvegarde et restauration de contrôle ; extension pendant les scans.

Comparer au comportement actuel sert à expliquer les écarts, pas à conserver
une règle non justifiée. M2 confronte ses propositions aux candidats et preuves
de ce contrat ; ses propositions IA ne remplacent pas les observations.

### Scénarios obligatoires

Les produits A/B et montants éventuels sont des fixtures fictives. Les cas réels
Roigada, Pikachu, Grainipiot, Manaphy, Baggaïd, Celebi et Barboach demandent des
pièces documentaires avant d’être déclarés résolus pour une langue donnée.

| ID | Entrée discriminante | Résultat attendu |
|---|---|---|
| C01 | Finition précisée, correspondance A inchangée | Même cotation, source et date ; attestation physique traitée séparément |
| C02 | Tampon précisé ou alias corrigé, correspondance A démontrée inchangée | Même prix ; texte original et nouvelle provenance conservés |
| C03 | Même booléen Foil, passage du produit A au produit B | Prix A suspendu et exclu ; aucune réutilisation sur B |
| C04 | Deux impressions, même correspondance vérifiée A | `market_status=verified` ; impression précise non inventée |
| C05 | Deux correspondances, discriminant non examiné | `unobserved` ; observation partielle sauvable ; aucun prix sélectionné |
| C06 | Une seule entrée connue dans une couverture partielle, reste sans preuve de correspondance commune | Aucun résultat vérifié par simple singleton |
| C07 | Langue ou numéro hors du périmètre | Non couvert ; aucune extrapolation ni blocage du scan |
| C08 | Repli catalogue FR → EN | Origine réellement servie tracée ; aucune certification de portée FR par le cache |
| C09 | Règle vérifiée applicable, TCGdex contradictoire, réseau coupé | Même résolution locale ; avertissement visible |
| C10 | Deux preuves fortes contradictoires, ou contestation locale active | Conflit ; sélection suspendue ; aucune observation réécrite |
| C11 | Impression identifiée, aucune preuve de correspondance marchande | `identified/unmapped` ; référence historique visible, prix vérifié inconnu |
| C12 | Référence manuelle sans métrique ni moyenne à 30 jours attestées | Aucune tendance ou valeur prudente inventée |
| C13 | Nouveau référentiel, même clé sémantique puis autre clé | Conservation dans le premier cas, suspension dans le second ; attestations identiques |
| C14 | Champs et prix hérités sans preuve suffisante | Valeurs et attestations conservées ; aucune absence ou correspondance certifiée inventée |
| C15 | Prix explicitement retiré, puis retour à une ancienne correspondance | Aucune résurrection automatique de la sélection |
| C16 | Sauvegarde restaurée avec une ancienne version de règles | Décision historique reproductible ; observations, sources et dates préservées |
| C17 | Paquet installé hors checkout, sans réseau ; paquet de règles invalide | Règles valides utilisables localement ; erreur explicite et aucune décision vérifiée pour le paquet invalide |
| C18 | Mêmes entrées et preuves, ordre des fichiers ou des candidats modifié | Même décision, même clé ; sortie canonique et aucune dépendance à l’heure |
| C19 | Métriques de devises, populations ou acquisitions incompatibles | Aucun total EUR avec USD ; aucune valeur prudente par mélange de relevés |
| C20 | Fiche modifiée après audit ou pendant acquisition réseau | Conflit de version ; aucune écriture partielle ni remplacement de la fiche récente |

Fiche, aperçu, CLI, prix, valorisation et export consomment le même résultat
et la même correspondance. La file physique, les besoins de couverture par
édition/langue et les prix manquants sont distingués ; une valeur inconnue
n’est pas masquée pour respecter un quota de cartes à examiner.

**Réception de M1.1 :** C01–C20 passent, les régressions réelles ont leurs preuves
et leur portée explicite, l’audit explique tous les changements de sélection,
et une restauration reproduit une décision historique. Ce document seul ne
déclare ni ces scénarios exécutés ni M1.1 livré.
