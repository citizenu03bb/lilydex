# Données personnelles : registre et procédures

La vitrine publique fait de Lilydex un traitement de données personnelles au
sens du RGPD. L'exemption « usage domestique » ne vaut pas pour un site ouvert
au public. Ce document tient lieu de **registre des traitements** (article 30)
et décrit les **procédures** : demandes des personnes, violation de données.
L'information des personnes est la page `/a-propos#donnees`. Ses durées et
celles de [privacy.py](../src/pokeprice/privacy.py) doivent rester identiques.

Le **responsable du traitement** est le propriétaire de la collection, un
particulier. Son nom et son adresse de contact ne figurent pas dans ce dépôt
public : le serveur les lit dans `POKEPRICE_CONTROLLER_NAME` et
`POKEPRICE_CONTACT_EMAIL` (voir [DEPLOYMENT.md](DEPLOYMENT.md)). Ni délégué à la
protection des données ni analyse d'impact ne sont requis : il n'y a ni
données sensibles, ni suivi à grande échelle, ni profilage.

## Registre des traitements

Mis à jour le 18 octobre 2026.

### 1. Comptes clients et demandes de réservation

| | |
|---|---|
| Finalité | Permettre à un visiteur de réserver des cartes et au vendeur de lui répondre |
| Base légale | Mesures précontractuelles à la demande de la personne (art. 6.1.b) |
| Personnes | Clients inscrits sur la vitrine |
| Données | E-mail (aussi identifiant), nom affiché, mot de passe haché (scrypt), dates d'inscription et de lecture de la notice, statut du compte, demandes (cartes, prix, message, réponse du vendeur) |
| Accès | Équipe de gestion : administrateurs (comptes et demandes), éditeurs et lecteurs (demandes, avec l'e-mail) |
| Sous-traitants | Oracle Cloud Infrastructure, région Marseille (hébergement) ; Google Drive (copies de sauvegarde **chiffrées** avec age : Google ne peut pas les lire) |
| Transferts hors UE | Copies chiffrées sur Google Drive, sous le Data Privacy Framework UE–États-Unis |
| Durées | Compte refusé : 30 jours après l'inscription ; jamais validé : 90 jours ; demande sans suite : 6 mois ; compte sans demande depuis 3 ans : effacé ; sauvegardes : 12 mois au plus, puis 30 jours de corbeille |
| Sécurité | HTTPS, cookie de session `HttpOnly`/`Secure`/`SameSite=Strict`, contrôle d'origine, limitation par adresse, service systemd isolé, sauvegardes vérifiées et chiffrées hors du serveur ([SECURITY.md](../SECURITY.md), [AUDIT-SECURITE.md](AUDIT-SECURITE.md)) |

Une vente conclue reste dans les comptes du vendeur avec ses montants ; à
l'effacement du client, son nom, son e-mail et son message en sont retirés.

### 2. Sécurité du site : limitation de débit et journal technique

| | |
|---|---|
| Finalité | Protéger le site contre les abus (inscriptions, connexions, lectures en masse) et diagnostiquer les pannes |
| Base légale | Intérêt légitime à sécuriser le service (art. 6.1.f) |
| Personnes | Visiteurs de la vitrine et de la gestion |
| Données | Adresse IP, date, requête (journal d'accès d'uvicorn dans journald) ; compteurs par adresse en mémoire seulement |
| Accès | Administrateur du serveur |
| Durées | Mémoire : quelques minutes à une heure, perdue au redémarrage ; journal systemd : 3 mois (`MaxRetentionSec`, posé par `oci-provision.sh`) |

### 3. Comptes de l'équipe de gestion

| | |
|---|---|
| Finalité | Gérer la collection et tracer qui a modifié quoi |
| Base légale | Intérêt légitime à organiser et tracer le travail sur la collection (art. 6.1.f) |
| Personnes | Membres de l'équipe |
| Données | Identifiant, mot de passe haché, rôle, sessions ; identifiant de l'auteur dans les historiques |
| Durées | Le temps de la participation ; les historiques gardent l'identifiant, qui peut être un pseudonyme |

### 4. Ventes par d'autres canaux

Les lots vendus ailleurs (salon, autre site) n'enregistrent pas d'acheteur. Les
**notes libres** d'un lot ne doivent contenir ni adresse postale ni coordonnées
d'un acheteur au-delà du temps de l'envoi : les retirer une fois la vente
terminée. `forget` ne retrouve pas ce qui y a été tapé à la main.

### Hors traitement

Les photos envoyées à Gemini pour lire les cartes ne montrent que des cartes :
ne photographier ni personne ni document. Les photos stockées sont ré-encodées
sans métadonnées EXIF ni GPS.

## Demandes des personnes

Un client connecté corrige son nom et son e-mail, télécharge ses données et
supprime son compte lui-même, dans **Mon compte**. Pour une demande reçue par
e-mail :

1. **Vérifier l'identité** : la demande doit venir de l'adresse du compte, ou
   le client se connecte et utilise **Mon compte**. Ne rien envoyer à une autre
   adresse.
2. **Répondre sous un mois** (art. 12). Ce délai peut être prolongé de deux
   mois pour une demande complexe, en prévenant la personne.
3. Selon la demande :
   - **accès ou portabilité** : la personne télécharge le fichier JSON dans
     **Mon compte** ; à défaut, l'administrateur lui transmet le même contenu ;
   - **rectification** : **Mon compte**, ou correction par l'administrateur ;
   - **effacement** : sur le serveur, lancer
     `sudo -u pokeprice env HOME=/srv/pokeprice /opt/pokeprice/.venv/bin/python -m pokeprice.manage --data /srv/pokeprice/inventory forget <e-mail>`
     (voir [APP.md](APP.md)), puis relire les notes des lots de ce client.
     Sans `--data`, la commande viserait une autre base, vide, et n'effacerait rien ;
   - **opposition au journal technique** : pas de suppression ciblée possible
     dans journald ; répondre que le journal s'efface au bout de 3 mois.
4. Garder la trace de la réponse (date, demande, suite donnée) dans un fichier
   privé hors du dépôt, sans recopier les données de la personne.

## Violation de données

Une violation est toute perte de confidentialité, d'intégrité ou de
disponibilité de données personnelles : serveur compromis, base ou sauvegarde
copiée, clé de sauvegarde perdue avec une copie Drive, compte de gestion
utilisé par un tiers, données supprimées par erreur sans sauvegarde.

1. **Contenir** : arrêter le service (`sudo systemctl stop pokeprice`), fermer
   toutes les sessions (service arrêté :
   `sudo -u pokeprice /opt/pokeprice/.venv/bin/python -c "import sqlite3; c = sqlite3.connect('/srv/pokeprice/inventory/collection.sqlite3'); c.execute('DELETE FROM sessions'); c.commit()"`), changer les mots de passe de
   l'équipe, révoquer et remplacer les clés concernées (Gemini, SSH, jeton
   Drive ; une nouvelle clé de sauvegarde par `backup-key` après avoir déplacé
   l'ancienne).
2. **Évaluer** : quelles données, combien de personnes, depuis quand, quel
   risque pour elles. Une copie chiffrée dont la clé n'a pas fui ne présente pas
   de risque.
3. **Notifier la CNIL sous 72 heures** après la découverte, sauf si la
   violation n'engendre pas de risque, par le
   [téléservice de notification](https://notifications.cnil.fr/notifications/index).
   Une notification incomplète peut être complétée ensuite.
4. **Informer les personnes** sans tarder si le risque est élevé, par exemple
   des e-mails et mots de passe hachés copiés : par e-mail, en clair, avec les
   mesures à prendre (changer un mot de passe réutilisé ailleurs).
5. **Consigner chaque violation**, même sans notification : date, faits,
   effets, mesures prises. Ce journal est privé, hors du dépôt, à côté du suivi
   des demandes.

## Clé des sauvegardes

La clé qui déchiffre les copies Drive est `~/.config/pokeprice/backup-key.txt`
sur le portable ([DAILY-BACKUPS.md](DAILY-BACKUPS.md)). Elle doit avoir une
copie hors ligne, sur un disque externe distinct du portable. Sans cette copie,
perdre le portable rend toutes les copies Drive illisibles : c'est une
violation de disponibilité.
