# Le verso et l'aide à l'état

> **Pour qui :** toute personne qui photographie le verso de ses cartes ou demande une proposition d'état.
> **Vous y trouverez :** le parcours, ce que le modèle reçoit et rend, les garde-fous, la conservation des données et ce qui est vérifié.
> **Statut :** en vigueur. Le mode d'emploi pas à pas est dans le [guide de l'application](APP.md#le-verso-et-létat).

L'état d'une carte (de MT à PO, sur l'échelle de Cardmarket) se décide carte en
main. L'application aide en deux temps : elle garde une photo du verso avec celle du
recto, puis, si vous le demandez, propose un état à partir de ces photos. La
proposition reste une aide : c'est une personne qui retient l'état.

## Le parcours

La fiche présente le recto et le verso, chacun avec capture, téléversement,
préparation et agrandissement. Le verso ne crée pas un exemplaire de plus et ne
sert pas à reconnaître l'édition. Après l'enregistrement d'une nouvelle carte,
la fiche propose d'ajouter le verso.

**Évaluer l'état** transmet à Gemini (`gemini-3.8-flash`) les photos entières
normalisées, avant les corrections locales. L'action annonce cet envoi.
Téléverser une photo n'envoie rien : l'évaluation ne part que si vous la
demandez. Une photo ancienne dont la version avant correction n'est pas
disponible reste utilisable, avec cette limite signalée.

## Ce que rend le modèle

Un état proposé, les défauts de chaque face, une justification, la qualité des
photos et les limites de l'examen. La proposition peut être **indéterminable**.
Un verso absent, le flou, les reflets et les contours coupés doivent être
signalés. Aucune note PSA ou BGS, aucune confiance chiffrée et aucune
estimation de prix ne sont demandées.

## Les garde-fous

- Le serveur applique ses propres règles, sans les déléguer au prompt : une
  proposition NM exige deux faces exploitables, les originaux et une qualité
  suffisante, sinon elle est retirée ; une face absente est inscrite dans les
  limites.
- La proposition et sa provenance sont immuables : modèle, version du
  protocole, photos réellement envoyées, réponse brute, auteur et date.
- Elle n'écrase jamais l'état courant, même non confirmé. Vous choisissez
  l'état final, confirmez avoir examiné la carte et inscrivez un motif ; cette
  validation est enregistrée à part.
- Une proposition fondée sur des photos remplacées devient obsolète et ne peut
  plus être validée. Les modifications concurrentes de la fiche sont refusées
  par son numéro de version.
- Le modèle reçoit l'original, pas la photo retouchée.

## Les données

Chaque exemplaire peut référencer, en plus de sa photo du recto, le recto avant
correction, le verso préparé et le verso avant correction ; les évaluations
ont leur propre table. Les photos restent privées et nommées par leur
empreinte. Les originaux historiques ne sont retrouvés que si leur preuve de
préparation correspond à la photo courante.

Les sauvegardes emportent toutes les versions des photos et les évaluations ;
la restauration vérifie aussi les photos du verso et les pièces de
l'évaluation. L'export JSON garde toute la provenance ; l'export HTML autonome
inclut le verso. Une proposition n'est jamais exportée comme un état confirmé.

## Ce qui est vérifié

Les tests portent, sur des collections temporaires, sur la migration, la
séparation du recto et du verso, l'envoi des originaux, les droits de lecture
et d'écriture, les erreurs du fournisseur, les réponses incohérentes,
l'évaluation sans modification de la fiche, la confirmation humaine, les photos
remplacées, la concurrence, la sauvegarde, la restauration et l'export hors
connexion.

Le parcours a été confirmé à l'usage sur Android, et le format de réponse
validé sur deux mires synthétiques, que le modèle a bien reconnues sans carte.
**La fiabilité des états proposés sur de vraies cartes n'est pas mesurée** :
présentez l'évaluation comme une aide. Sa calibration sur les ventes réelles
est prévue après le MVP ([feuille de route](ROADMAP.md#prévu)).
