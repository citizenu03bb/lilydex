# Une adresse client se prouve par le lien transmis par le vendeur

> **Statut :** en vigueur · **Date :** 2026-11-06

**Contexte.** Le nom de connexion d'un client est son e-mail. Le modifier
immédiatement permet à un compte approuvé de revendiquer une adresse libre et
de lire les futures demandes invitées envoyées avec cette adresse. Le site
ne dispose pas d'un parcours d'envoi automatique aux clients ; le vendeur
transmet déjà des liens de mot de passe depuis sa messagerie.

**Décision.** Le changement reste dans `pending_email` et ne change ni le
nom de connexion ni le rattachement des demandes. Le vendeur crée un lien
à usage unique, lié à sa destination, et l'envoie manuellement à cette
adresse. Son utilisation prouve l'adresse et confirme le changement en même
temps que le choix du mot de passe. Les sessions et anciens liens sont
révoqués. L'approbation d'un compte ne vaut pas preuve d'adresse.

Une demande invitée à une adresse non prouvée appartient à une identité
invitée distincte, sans adresse de connexion ni mot de passe utilisable.
Ses coordonnées sont figées dans la demande. Après preuve de l'adresse, les
demandes dont le contact d'origine est connu sont rattachées au compte du
destinataire. Le nom et l'adresse copiés dans un lot servent à l'effacement,
pas à établir l'origine d'une ancienne demande.

**Reprise.** Les anciennes demandes ne distinguent pas envoi connecté et
invité. Le profil courant, comme l'historique du lot, peut refléter un profil
modifié après réception de la demande : aucun ne prouve son origine. La
migration garde ces identités pour l'effacement, mais marque le contact
d'origine inconnu (`contact_known=0`). Les demandes restent dans la gestion
et sont exclues des comptes, même après preuve de leur adresse courante.
L'administrateur retrouve le destinataire dans sa propre correspondance puis
confirme ou corrige les coordonnées sur la demande, avec contrôle de version.
La preuve de cette adresse permet ensuite le rattachement au compte. Une
demande inconnue ne peut pas être acceptée avant cette confirmation.
La suppression par un compte ne maîtrisant pas ces demandes les détache dans une identité invitée
dans la même transaction, sans les effacer. L'opérateur les traite séparément.
Le journal d'effacement conserve la portée de cette suppression pour la
rejouer ; un ancien marqueur sans cette restriction garde son sens et efface
les demandes encore liées au compte après restauration. Les identifiants
immuables des demandes permettent aussi de retrouver un effacement après
confirmation du contact ou changement de compte.

**Alternatives.** Un canal d'e-mail automatique exige une nouvelle gestion
des envois et des échecs. Un simple changement par le vendeur sans preuve de
réception conserve le risque d'appropriation. Le lien déjà utilisé rend le
contrôle explicite et ne crée pas un nouveau service d'envoi.

**Conséquences.** Confirmer une adresse exige de choisir un mot de passe et
ferme les autres sessions. Les anciennes demandes peuvent demander une
nouvelle preuve ; cette contrainte évite de donner une conversation invitée
au seul détenteur d'un mot de passe de compte non vérifié. Les coordonnées
figées permettent l'effacement des noms et adresses copiés dans les lots,
même après changement de profil.

**Vérification.** `tests/test_client_identity.py` rejoue les changements en
attente, les liens révoqués, l'isolation des invités, l'effacement des anciens
noms et la migration d'une sauvegarde restaurée, sans service réel.
