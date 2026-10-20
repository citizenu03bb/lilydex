# Améliorations pour les six prochains classeurs

Décision du 5 octobre 2026 : implémenter les recommandations avec priorité à
la conservation des données et au scan Android en série. Destination externe
choisie par le propriétaire : dossier privé Google Drive « Poképrice — sauvegardes ».

| Priorité | Livraison | Critère de réception |
| --- | --- | --- |
| 1 | Sauvegardes quotidiennes et état visible | ZIP base/photos restauré ; copie Drive vérifiée ; erreurs visibles |
| 2 | Alertes de doublons | Emplacement occupé ou même photo ; choix explicite sans fusion automatique |
| 3 | Saisie Android en série | Album/pochettes conservés ; recto/verso ; reprise après rafraîchissement/redémarrage ; aucune double création |
| 4 | Vue par édition | Quantités par stock et accès aux exemplaires distincts ; recherche et URL conservées |
| 5 | Photos existantes par lot | Simulation avant/après ; sélection ; sauvegarde ; versions contrôlées ; retour arrière |
| 6 | Brouillons d'annonces | ZIP description/photos/liste des informations manquantes ; aucune publication |

## Sauvegarde

Une tâche locale produit quotidiennement un ZIP SQLite cohérent avec toutes les
photos, puis restaure une copie temporaire pour le vérifier. Les sept dernières
sauvegardes quotidiennes sont conservées localement ; les sauvegardes manuelles
ne sont jamais purgées. Depuis le 6 octobre, la copie Drive utilise rclone avec
l'autorisation `gdrive` existante et un timer utilisateur. Elle reste privée. L'application
montre les dates de succès local/externe et les erreurs. Aucun jeton de connector
ni clé Gemini n'est transmis au navigateur. Les tâches dépendent du portable,
de la session utilisateur et du réseau ; le transfert ne dépend plus de Codex.

## Saisie et doublons

La session appartient à un utilisateur. Choisir/créer un album, la première page,
la première pochette et le nombre de pochettes par page. Les champs et les deux
photos de la carte en cours sont conservés côté serveur ; fermer le dialogue
permet de reprendre. Le verso est facultatif. La lecture Gemini reste une action
explicite. Seule la validation de la carte crée un exemplaire.

La création et l'avancement sont transactionnels et idempotents : une répétition
du dernier enregistrement retrouve la même carte. L'emplacement suivant est
proposé, jamais imposé. Les alertes concernent les emplacements occupés et les
photos de recto identiques ; les copies légitimes d'une édition restent permises.
L'utilisateur peut ouvrir une fiche existante ou confirmer un exemplaire distinct.
Les alertes sont revérifiées au moment de l'écriture pour couvrir la concurrence.

## Consultation, photos et annonces

La vue édition regroupe les exemplaires sans modifier leurs UUID, photos, états
ou emplacements. Les éditions non identifiées restent séparées. Les filtres
portent sur les exemplaires ; les compteurs indiquent aussi les quantités globales.

Une simulation photo traite au maximum vingt exemplaires sélectionnés à la fois,
sans Gemini. Elle utilise l'image avant correction lorsqu'elle est disponible,
sinon signale la limite. L'application des résultats choisis contrôle toutes les
versions dans une transaction, conserve une sauvegarde et écrit la provenance.
Un retour arrière refuse les fiches modifiées depuis l'application du lot.

Le dossier d'annonce contient un texte modifiable, les photos recto/verso et
une liste de points à compléter. Les états non confirmés restent présentés comme
tels. Les notes privées, comptes, coordonnées, paiements et historique sont
exclus. Aucun prix n'est inventé, aucun exemplaire n'est réservé et rien n'est publié.

## Vérification

Tests sur collections temporaires : migration, isolation des utilisateurs,
reprise de session, idempotence, concurrence, vrais doublons autorisés,
photos originales, rollback, exports, sauvegardes/restauration et rôles.
Essais Chrome sur copie et format mobile ; capture matérielle Android à confirmer
par le propriétaire après livraison. Sauvegarde avant migration ; conserver le tunnel actif.

## Réception du 5 octobre 2026

Les six fonctions sont livrées sur l'instance HTTPS existante. 147 tests passent.
La comparaison des onze tables métier avant/après la migration 6→7 est
identique : 404 exemplaires actifs et un exemplaire en corbeille. Aucun nouveau
scan Gemini, prix ou mouvement de vente n'a été déclenché sur la collection réelle.

Chrome sur copie : reprise de champs après F5, page 1/pochette 9 vers page 2/1,
vue édition et URL, simulation/application/annulation photo et historique après
rafraîchissement. Le rendu mobile 390×844 ne déborde pas. Le nouveau parcours
série sur Android matériel reste à confirmer ; les deux faces sont couvertes
par les tests API, l'upload automatisé Chrome exige une permission d'extension
actuellement désactivée.

Le service local de sauvegarde et son timer ont été exécutés avec succès ;
l'automation Drive est active. Le ZIP local est restauré, les copies Drive
sont contrôlées par métadonnées. Les sources initiales sont copiées en sept
parties privées. Voir [DAILY-BACKUPS.md](DAILY-BACKUPS.md) pour les limites
de disponibilité et le téléchargement de contrôle encore à effectuer.

**Mise à jour du 6 octobre :** transfert déterministe livré avec rclone,
contrôle des permissions privées, archive stable, reprise après réponse perdue
et protection contre les doublons. L'archive quotidienne du 6 octobre a été
retéléchargée, son SHA-256 contrôlé et son contenu restauré : 404 exemplaires
actifs. Les 157 tests passent, dont dix nouveaux tests de transfert et d'échec.
Le timer Drive remplace l'automation Codex ; les parties du snapshot initial
restent à télécharger et à restaurer pour leur propre exercice de réception.
