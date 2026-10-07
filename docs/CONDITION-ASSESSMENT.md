# Verso et aide à l'évaluation de l'état

Décision du 5 octobre 2026 : ajouter le verso au même exemplaire, puis proposer
une évaluation Gemini explicite, distincte de l'état validé par le propriétaire.

## Parcours

La fiche présente le recto et le verso, chacun avec capture, téléversement,
préparation et agrandissement. Le verso ne crée pas un exemplaire supplémentaire
et ne sert pas à reconnaître l'édition. Une nouvelle carte rejoint cette fiche
après son enregistrement pour permettre la seconde photo.

« Évaluer l'état » transmet les photos entières normalisées avant les corrections
locales au modèle `gemini-3.8-flash`. L'action annonce cette transmission. Les
photos anciennes dont la version avant correction n'est pas disponible restent
utilisables, avec cette limite signalée. Aucun appel n'est déclenché par un upload.

Le résultat contient un état proposé, les défauts par face, une justification,
la qualité des photos et les limites de l'examen. Il peut être indéterminable.
Le verso absent, le flou, les reflets et les contours coupés doivent être signalés.
Une proposition NM demande deux faces exploitables. Aucune note PSA/BGS, mesure
de confiance inventée ou estimation de prix n'est demandée.

La proposition et sa provenance sont immuables : modèle, version du protocole,
photos réellement envoyées, réponse brute, auteur et date. Elle n'écrase jamais
l'état courant, même non confirmé. Le propriétaire peut choisir l'état final,
confirmer son examen de la carte et enregistrer un motif. La validation est
auditée séparément. Une proposition fondée sur des photos remplacées devient
obsolète et ne peut plus être validée. Les modifications concurrentes de la fiche
sont refusées par son numéro de version.

## Données et conservation

Le schéma SQLite 5 ajoute trois références facultatives aux exemplaires : recto
avant correction, verso préparé et verso avant correction. Une table conserve
les évaluations. Les photos restent adressées par hash et privées. Les anciens
exemplaires, états, prix, stocks et identifiants restent identiques lors de la
migration. Les originaux historiques sont retrouvés uniquement lorsque leur
preuve de préparation correspond à la photo courante.

Les sauvegardes portent toutes les versions de photos et les évaluations. Leur
restauration vérifie aussi les photos du verso et les pièces de l'évaluation.
L'export JSON conserve la totalité de la provenance ; l'export HTML autonome
inclut le verso. Une proposition IA n'est jamais exportée comme un état confirmé.

## Validation

Tester sur des collections temporaires : migration 4→5, recto/verso séparés,
originaux transmis, droits de lecture/écriture, erreurs du fournisseur,
réponses incohérentes, évaluation sans mutation de la fiche, confirmation humaine,
photos remplacées, concurrence, sauvegarde/restauration et export hors connexion.
Sauvegarder avant migration de la collection réelle ; conserver le tunnel HTTPS
et redémarrer chaque serveur individuellement après validation.

Le 5 octobre 2026, le propriétaire confirme le fonctionnement attendu du parcours photo
Android verso/état. Le format de réponse Gemini a été validé séparément avec
deux mires synthétiques, pour lesquelles le modèle a reconnu l'absence de carte
réelle. Ces éléments valident le fonctionnement du parcours et le format des
réponses ; ils ne mesurent pas la fiabilité des états proposés sur des cartes réelles.
