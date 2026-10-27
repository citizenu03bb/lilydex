# 0018 — Une réservation se demande sans compte

> **Statut :** en vigueur · **Date :** 2026-10-27

**Contexte.** Pour réserver, un visiteur devait créer un compte, attendre
qu'un administrateur le valide, puis revenir de lui-même : le site n'envoie
pas d'e-mails et ne le prévenait pas. La vitrine n'avait aucun inscrit. La
validation tenait lieu de vérification de l'adresse ; or le vendeur écrit de
toute façon au client pour le paiement, et sa réponse vérifie l'adresse.

**Options.**
1. Garder la validation préalable.
2. Laisser un compte en attente se connecter et envoyer des demandes : le mot
   de passe et l'inscription restent avant la première demande.
3. Demander une réservation avec un nom et un e-mail, sans mot de passe ;
   valider le client à l'acceptation.

**Décision.** Option 3. Une adresse inconnue reçoit un compte en attente sans
mot de passe utilisable ; une adresse connue reçoit la demande. La réponse est
la même dans tous les cas. Pour choisir un mot de passe, le vendeur colle dans
son e-mail un lien à usage unique, valable 7 jours, créé dans la gestion.

**Conséquences.**
- N'importe qui peut envoyer une demande au nom d'une adresse, et l'ajouter
  au compte qui la porte. Une demande ne bloque aucune carte ; le vendeur s'en
  aperçoit en écrivant. Limites : 5 envois par heure et par adresse IP,
  3 demandes en attente par e-mail.
- Atteindre la limite de 3 révèle qu'une adresse a déjà des demandes : un
  écart accepté, rare et sans autre donnée.
- Le même lien règle l'oubli de mot de passe. Un service d'envoi d'e-mails,
  s'il arrive, enverra ce lien à la place du vendeur sans changer le principe.
