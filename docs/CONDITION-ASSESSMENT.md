# Le verso et l'aide à l'état

> **Pour qui :** toute personne qui photographie le verso de ses cartes ou demande une proposition d'état.
> **Vous y trouverez :** le parcours, ce que le modèle reçoit et rend, les garde-fous, la conservation des données et ce qui est vérifié.
> **Statut :** en vigueur. Le mode d'emploi pas à pas est dans le [guide de l'application](APP.md#le-verso-et-létat).

L'état d'une carte (de MT à PO, sur l'échelle de Cardmarket) se décide carte en
main. L'application aide en deux temps : elle garde une photo du verso avec celle du
recto, puis propose un état à partir de ces photos. Une personne retient
l'état, ou l'agent de revue le confirme quand les preuves concordent ; sinon,
l'agent demande une autre prise de vue.

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
  proposition NM exige un recto exploitable et original, des photos de
  qualité suffisante et, s'il y a un verso, sa version originale ; sinon elle
  est retirée. Un verso absent ne la retire pas : « Verso non vu » est inscrit
  dans les limites ([décision 0049](decisions/0049-etat-sans-manipulation.md)).
- La qualité des photos ne juge que les faces fournies (protocole
  `card-condition-v3`) ; une évaluation faite sous un protocole plus ancien est
  relue par l'agent.
- La note suit le barème écrit de Cardmarket : NM, très peu de points blancs
  minuscules et aucune rayure ; EX, quelques points blancs et des rayures
  fines, aucun pli visible au premier coup d'œil ; GD, usure forte et
  rayures, aucune pliure ; LP, pliure admise. Le défaut le plus pénalisant
  décide, et le doute donne la note inférieure. La lecture dit aussi si elle
  voit un pli ([décision 0052](decisions/0052-pli-en-main-et-bareme-cardmarket.md)).
- La proposition et sa provenance sont immuables : modèle, version du
  protocole, photos réellement envoyées, réponse brute, auteur et date.
- Elle n'écrase jamais l'état courant, même non confirmé. Vous choisissez
  l'état final, confirmez avoir examiné la carte et inscrivez un motif ; cette
  validation est enregistrée à part.
- Une proposition fondée sur des photos remplacées devient obsolète et ne peut
  plus être validée. Les modifications concurrentes de la fiche sont refusées
  par son numéro de version.
- Le modèle reçoit l'original, pas la photo retouchée.

## L'agent de revue

L'agent de revue (`agent:revue`, module `agent_review.py`) confirme la
variante et l'état **par le même chemin d'écriture qu'une personne** : la
fiche change de version, l'événement de validation garde les lectures, et
porte en plus `decided_by: agent`, le score et l'identifiant du passage.

Il confirme la variante si :

- la lecture de finition est « proposée », sur une photo de qualité
  suffisante, sans désaccord de finition, de tampon ou de langue ;
- le contrôle d'édition par l'image désigne l'édition de la fiche, avec au
  moins la marge de 0,05 de la [décision 0006](decisions/0006-dinov2-marge.md) ;
- au seuil de valeur (10 € par défaut) ou sans valeur prudente connue, le
  verso est aussi exploitable ([décision 0008](decisions/0008-reverses-examen-physique.md)).

Il confirme l'état si l'évaluation est exploitable sur le recto et de qualité
suffisante, avec la même règle de verso au seuil.

Chaque facette établie est écrite, sauf si une photo demandée dans le même
passage l'effacerait : une photo du recto efface la variante et l'état, une
photo du verso efface l'état. Sur une carte importée, l'identité confirmée est
toujours écrite. Si elle ne se confirme pas, rien n'est écrit
([décision 0050](decisions/0050-confirmer-par-facette.md)).

Aucune carte ne sort du classeur pour juger son état
([décision 0049](decisions/0049-etat-sans-manipulation.md)). Sous le seuil,
le recto suffit. Au-dessus, sans verso exploitable, l'agent ne demande pas le
verso : la variante et l'état restent provisoires jusqu'à la photo du verso
prise pour l'annonce, et le passage suivant tranche.

Une **prise au reflet** (la carte inclinée sous une lampe, hors pochette)
tranche la question des reverses quand elle est de qualité suffisante : une
bande arc-en-ciel sur le corps de la carte propose la reverse, un corps
nettement mat propose la Standard, même au-dessus du seuil. La fiche d'une
carte dont la finition demande un examen offre le bouton **Photo au reflet** ;
la photo qui répond à une demande « reflet holo » de l'agent compte aussi comme
prise au reflet. Une photo ordinaire ne prouve toujours pas la Standard
([décision 0047](decisions/0047-import-de-classeur-sur-le-serveur.md)).

Pour une carte créée par l'import d'un classeur et encore « à vérifier », il
confirme aussi l'identité, en premier, avec la variante et l'état, ou rien
([décision 0047](decisions/0047-import-de-classeur-sur-le-serveur.md)) :
le catalogue a trouvé cette seule édition, au nom exact et à la référence
complète ; le contrôle d'édition par l'image la désigne avec la marge ; la
langue lue est celle de l'édition ; la carte est sous le seuil de valeur.
Tant que le réglage `agent_review_apply` est faux, il n'écrit aucune
identité, quel que soit l'appelant (processus d'import ou `agent-review
--apply`) : le rapport dit seulement qu'il la confirmerait.

Sinon, il inscrit une **demande de photo** dans le journal (`photo-request`) :
la carte, la vue (recto net, verso, reflet holo, coins de près) et une raison
en une phrase. Une seule vue par face, la plus précise. La gestion les liste
sous « Photos à reprendre », dans l'ordre du classeur. Le bouton ouvre
l'appareil photo du téléphone ; la nouvelle photo ferme la demande et le
serveur relance seul les lectures et la décision pour cette carte. Tant que
`agent_review_apply` est faux, la photo est lue et rien n'est écrit
([décision 0051](decisions/0051-porte-sur-les-erreurs-graves.md)). Une vue déjà
reprise sans succès n'est pas redemandée : la carte reste en l'état, avec son
état enregistré. Le rapport la range dans `kept`, avec ce que les photos ne
tranchent pas, et personne ne l'examine en main.
Un désaccord avec la fiche n'appelle pas de photo : la carte reste « À examiner ».

### Les prises de près en série

**Collection → Prises de près** (administrateur) enchaîne les photos que
l'agent demande, carte après carte dans l'ordre du classeur, pour un import,
un album, la sélection en cours ou une liste d'exemplaires portée par un lien
(`/gestion?prises=<id>,<id>,…`, 500 au plus) ; l'import d'un classeur offre le
même bouton pour ses cartes
([décision 0048](decisions/0048-serie-de-prises-de-pres.md)). La liste est le
verdict de l'agent en simulation sur ces cartes, calculé à l'ouverture : elle
existe donc aussi quand `agent_review_apply` est faux et que l'agent
n'inscrit aucune demande.

À chaque carte, la série demande aussi : « Pli, cassure ou marque enfoncée ? »
(non, pli, enfoncement ou doute). Un pli ou un enfoncement plafonne à LP
l'état que l'agent confirme ; une carte qu'il ne confirme pas (photo à
reprendre, carte de valeur, recto insuffisant) garde son état enregistré. Un
doute le laisse tel qu'enregistré. La réponse ne relance aucune lecture :
l'agent décide de nouveau sur les lectures qu'il a. Sans réponse en
main, un pli vu par la lecture plafonne aussi la note ; une réponse en main
l'emporte ([décision 0052](decisions/0052-pli-en-main-et-bareme-cardmarket.md)).

Chaque étape montre la page, la pochette sur la grille de l'import, la
vignette actuelle et la vue à prendre : reflet (la carte inclinée sous une
lampe rasante), coins de près (le recto hors pochette, les quatre coins nets),
recto net, puis verso. Un geste ouvre l'appareil photo ; la carte suivante
s'affiche aussitôt, et l'envoi part en fond. La photo remplace la face visée
par le chemin de la fiche ; un reflet est enregistré comme tel. Après la
réponse, le serveur relit la carte (finition, édition par l'image, état) et
l'agent décide sur elle seule : il écrit si `agent_review_apply` est vrai,
sinon son verdict reste dans le journal de la carte (`closeup-review`). Si
cette relecture n'a pas rendu de verdict au bout de dix minutes (un
redémarrage du service l'a interrompue), l'ouverture suivante de la série la
relance. Deux photos de la même carte prises coup sur coup lancent leurs
relectures l'une après l'autre. Une vue déjà prise dans une série n'est pas
redemandée : la carte passe dans « Restent en l'état ». En fin de série, l'écran donne la médiane du temps par
carte et les verdicts de l'agent.

En lot : `pokeprice-manage --data <base> agent-review` simule, `--apply`
écrit, `--read` lance les lectures manquantes. Le rapport compte les cartes
confirmées, les demandes de photo, les cartes laissées de côté et les
décisions humaines évitées. `agent-review-runs` liste les passages ;
`agent-review-undo <passage> --actor <compte>` les annule, sauf les fiches
modifiées depuis, signalées.

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
