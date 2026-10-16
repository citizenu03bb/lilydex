# Vitrine publique et demandes de réservation — plan d'implémentation

Plan du 16 octobre 2026. Les décisions viennent de la [roadmap](ROADMAP.md)
(section Décisions et « Après le MVP »). Rien n'est encore implémenté.

## Objectif

Une **vitrine ouverte** sur <https://lilydex.duckdns.org> montre, sans compte,
une sélection explicite de cartes à vendre. Un visiteur s'inscrit pour
**demander une réservation**. Le vendeur valide le compte, accepte la demande
(en tout ou en partie) : l'acceptation crée un **lot réservé** dans le circuit
de vente existant (paiement déclaré, expédition, clôture). Pas de paiement en
ligne, pas de service d'e-mail au départ : le vendeur contacte le client depuis
sa boîte.

## Décisions (16 octobre)

| Sujet | Décision |
|---|---|
| Visibilité | vitrine ouverte, sans compte ; l'inscription sert à demander |
| Prix affiché | tendance Cardmarket arrondie, plancher 0,50 €, pour NM/EX à état et variante confirmés ; sinon prix fixé à la main ou tiré des offres ; sous le plancher : lots ou cadeaux |
| Comptes clients | inscription libre, compte **en attente** jusqu'à validation par un administrateur |
| Réservation | une demande ne bloque rien ; les cartes sont réservées à l'**acceptation** |
| E-mail | aucun service au départ ; Brevo ou Mailjet plus tard, avec un domaine deSEC (SPF/DKIM) |

## Ce qui est public, et ce qui ne l'est jamais

Public, pour une carte **publiée et disponible** uniquement : photo recto
(verso si présent), nom, extension, numéro, langue, variante, état **confirmé**,
tampon et distribution, prix affiché et sa date, identifiant de publication.

Jamais exposé hors gestion : notes, provenance, événements, relevés et
historique de prix, prix de référence brut, alertes, état estimé non confirmé,
album/page/pochette, autres exemplaires, lots, ventes, acheteurs, comptes.
L'identifiant public est celui de la publication, pas l'UUID de l'exemplaire.

## Modèle de données (migration de schéma 15)

La migration suit la règle du projet : copie de la base avant migration,
transaction, `PRAGMA user_version` incrémenté.

- `users` : le rôle `client` s'ajoute aux rôles existants. La contrainte
  `CHECK(role IN …)` impose une reconstruction de la table (SQLite). Nouvelles
  colonnes `email` (unique, insensible à la casse, NULL pour les comptes
  existants), `display_name`, `status` (`pending`, `active`, `refused`),
  `consent_at` (acceptation de la politique de confidentialité).
- `listings` : une publication par exemplaire. `id` (public), `copy_id`
  (unique), `state` (`online`, `offline`), `price_cents`, `price_mode`
  (`trend`, `manual`, `offers`), `price_source`, `price_date`,
  `published_at`, `published_by`, `version`. Un lot vendu d'un bloc est une
  publication à plusieurs exemplaires : table `listing_items(listing_id,
  copy_id)`, la publication simple n'ayant qu'une ligne.
- `requests` : `id`, `client_id`, `status` (`sent`, `accepted`,
  `partially_accepted`, `refused`, `expired`, `cancelled`), `message`,
  `sale_id` (lot créé à l'acceptation), `created_at`, `expires_at`,
  `version`.
- `request_items` : `request_id`, `listing_id`, `price_cents` figé à la
  demande, `outcome` (`pending`, `accepted`, `unavailable`, `refused`).

Le statut vu par le client après acceptation suit celui du lot (`reserved`,
`sold`, `shipped`, `completed`, `cancelled`, `returned`).

## Prix calculé

Fonction pure `display_price(card, snapshot)` dans `pricing.py` :

1. Carte non confirmée, variante ou état non confirmés, ou état hors NM/EX :
   pas de prix automatique, publication refusée sans prix manuel.
2. Tendance du dernier relevé arrondie au dixième supérieur ; sous 0,50 € :
   pas de publication unitaire (proposer un lot).
3. Prix manuel ou issu d'une estimation d'offres : prioritaire, avec sa source.
4. Le prix figé dans la publication est revu au republier ; un relevé plus
   récent signale l'écart au vendeur, sans changer le prix publié.

## Routes

Publiques, sans cookie, en lecture seule, avec limitation de débit par IP :

- `GET /vitrine` : page HTML légère et séparée de l'application de gestion
  (`web/storefront.html`, `storefront.js`) ; aucun code de gestion chargé.
- `GET /api/public/listings` : filtres extension, Pokémon, langue, prix ;
  pagination ; seulement `online` et dont tous les exemplaires sont
  `available`.
- `GET /api/public/listings/{id}` et `GET /api/public/listings/{id}/photo` :
  photo servie par identifiant de publication, 404 si non publiée.

Client (cookie de session, rôle `client` actif) :

- `POST /api/public/signup` : e-mail, nom, mot de passe (10 caractères),
  consentement ; crée un compte `pending` ; limitation de débit et
  temporisation identique qu'il existe déjà ou non (pas d'énumération).
- `POST /api/login` existant : un compte `pending` reçoit « compte en attente
  de validation », sans session.
- `GET/POST /api/me/requests`, `POST /api/me/requests/{id}/cancel`.

Gestion (rôles existants) :

- `GET /api/clients`, `PATCH /api/clients/{id}` (valider, refuser, désactiver).
- `PUT/DELETE /api/copies/{id}/listing`, publication par sélection.
- `GET /api/requests`, `POST /api/requests/{id}/accept` (liste des cartes
  retenues) : transaction unique qui crée le lot avec `create_sale`, le passe
  en `reserved`, et marque `unavailable` les cartes déjà prises ; la contrainte
  `single_reservation` arbitre deux acceptations concurrentes.
- `POST /api/requests/{id}/refuse`.

**Garde-fou central** : la dépendance `current_user` actuelle laisse passer tout
compte connecté. Elle est scindée : `staff` (admin, editor, reader) pour toutes
les routes de gestion existantes, `client` pour `/api/me/*`. Un test parcourt
toutes les routes de l'application et vérifie qu'un client reçoit 403 partout
hors de `/api/public/*` et `/api/me/*`.

## Interface

Vitrine : grille de cartes, filtres, fiche (photos, détails, prix et date),
« Ajouter à ma demande », demande avec message (envoi ou remise en main
propre), inscription, connexion, « Mes demandes » avec statuts. Mobile d'abord,
multilingue (FR et EN au départ ; voir le public international de la roadmap).

Gestion : badge « inscriptions en attente » et « demandes reçues » ; action
« Publier » sur une fiche ou une sélection, avec le prix proposé et le motif
d'un refus ; écran des demandes (accepter tout ou partie, refuser) ouvrant le
lot créé.

## Sécurité et conformité

- Limitation de débit : inscription, connexion, demandes, vitrine.
- Cookies `Secure`, `HttpOnly`, `SameSite=Lax` ; jeton CSRF sur les
  formulaires clients.
- Page « Confidentialité » : données collectées (e-mail, nom, demandes),
  finalité, durée de conservation, droit d'accès et de suppression ; suppression
  d'un compte client par l'administrateur.
- Expiration des demandes non traitées (7 jours) par une tâche quotidienne.
- Indexation : la page porte `noindex` ; vitrine indexable ou non, à décider avant ouverture.

## Tranches

1. **Rôles et garde-fou** : migration 15 (rôle `client`, statut, e-mail),
   séparation `staff`/`client`, test de couverture des routes. Aucun écran.
   *Livrée le 16 octobre (branche `vitrine-tranche-1`)* : `users` reconstruite
   avec contrôle des clés étrangères dans la transaction ; 11 routes de gestion
   passées de « connecté » à `staff` ; un compte `pending` n'obtient pas de
   session (« compte en attente de validation », dit seulement après un mot de
   passe juste), un compte `refused` est traité comme inconnu ; une session
   cesse dès que le compte n'est plus actif. Sur 69 routes, seules 8 restent
   hors `staff`, listées dans `tests/test_storefront_access.py`.
2. **Publication et prix** : tables `listings`, `display_price`, actions de
   publication dans la gestion, tests du calcul et du plancher.
   *Livrée le 16 octobre (branche `vitrine-tranche-2`)* : migration 16
   (`listings`, `listing_items`, index `single_listing` : un exemplaire dans
   une seule publication en ligne) ; `display_price` dans `pricing.py`, plancher
   comparé avant arrondi, cartes à 10 € ou plus renvoyées aux offres ou au prix
   manuel ; module `listings.py` et routes de gestion (`editor` pour publier,
   `staff` pour consulter) ; bloc **Vitrine** de la fiche, **Publier en
   vitrine** et **Publier en lot** sur la sélection, filtre **Publiés en
   vitrine**. Le détail est dans [APP.md](APP.md#publier-en-vitrine).
3. **Vitrine publique** : routes `/api/public/*`, page `storefront`, photos par
   publication, limitation de débit, test « aucun champ privé dans les
   réponses publiques ».
   *Livrée le 16 octobre (branche `vitrine-tranche-3`)* : `Storefront` dans
   `listings.py` (liste blanche de champs, état seulement s'il est confirmé),
   `/vitrine` avec `storefront.html/js/css` séparés de la gestion, recherche,
   langue, prix maximum, tri, fiche recto-verso, lots ; 300 lectures par minute
   et par adresse ; `noindex` en attendant la décision sur l'indexation ; essai
   au navigateur en largeur ordinateur et téléphone sur une base temporaire.
4. **Inscription et demandes** : signup, validation des comptes, demandes,
   acceptation transactionnelle vers `create_sale`, concurrence testée.
5. **Finitions** : expiration, page confidentialité, multilingue, essai de bout
   en bout sur une copie de la base, puis déploiement sur lilydex après
   sauvegarde rapatriée.

**Terminé lorsque :** un visiteur voit les cartes publiées sans compte ; un
client inscrit et validé envoie une demande ; son acceptation crée un lot
réservé ; deux acceptations concurrentes ne réservent jamais deux fois le même
exemplaire ; aucune réponse publique ou client ne contient de champ privé.
