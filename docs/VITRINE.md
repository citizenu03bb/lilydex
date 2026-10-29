# La vitrine publique

> **Pour qui :** toute personne qui veut comprendre ou faire évoluer la partie publique du site.
> **Vous y trouverez :** ce que fait la vitrine, ce qui est public et ce qui ne l'est jamais, le prix affiché, le modèle de données, les routes, les garde-fous et les prochaines étapes.
> **Statut :** en vigueur. Le mode d'emploi pour l'équipe est dans le [guide de l'application](APP.md#publier-en-vitrine).

La vitrine est la page d'accueil du site, ouverte sans compte. Elle montre une
sélection explicite de cartes à vendre. Un visiteur **demande une réservation**
avec son nom et son e-mail, sans compte ni mot de passe ; le vendeur accepte la
demande en tout ou en partie : l'acceptation crée un **lot réservé** dans le
circuit de vente habituel (paiement déclaré, expédition, clôture) et valide le
client. Il n'y a ni paiement en ligne, ni service d'e-mail : le vendeur
contacte le client depuis sa propre messagerie, et c'est sa réponse qui
vérifie l'adresse.

La vitrine s'affiche sous le nom **Les cartes de Lily**. Ce nom vient de
`SITE_NAME` (`src/pokeprice/brand.py`), que le serveur insère dans chaque page à
la place de `{{site_name}}` ; le logotype (`{{site_wordmark}}`) le coupe avant
son dernier « de ». Son en-tête compact présente la collection, sans bouton
d'exploration : la recherche est directement visible. **Comment réserver** reste accessible, y compris sur téléphone, à côté
de **Ma sélection**. Le menu **Compte** réunit connexion, inscription, suivi
des demandes et choix du thème. La palette crème, sauge et terracotta suit les
thèmes Clair, Sombre et Dense ; les polices restent locales et la politique de
sécurité des contenus reste inchangée.

Les vignettes montrent toute la photo, sans en recadrer les bords. Une seule
phrase explique leur provenance. L'état estimé ne devient pas une affirmation :
une vignette sans état confirmé indique « État à confirmer ». Un lot porte son
nombre de cartes et précise que son prix concerne l'ensemble. Dans **Ma
sélection**, chaque ligne montre aussi le recto de la première carte.

## Les règles

| Sujet | Règle |
|---|---|
| Visibilité | Vitrine ouverte, sans compte ; un compte sert seulement à suivre ses demandes |
| Prix affiché | Voir [le prix affiché](#le-prix-affiché) ; plancher 0,50 € ; sous le plancher, lots ou cadeaux |
| Comptes clients | Créés par une première demande (sans mot de passe) ou par l'inscription ; **en attente** jusqu'à l'acceptation d'une demande ou la validation par un administrateur |
| Mot de passe | Choisi par un lien à usage unique que le vendeur colle dans son e-mail ; le même lien sert en cas d'oubli |
| Réservation | Une demande ne bloque rien ; les cartes sont réservées à l'**acceptation** |
| Paiement | Wero, virement ou PayPal, réglés par l'administrateur ; le client voit les coordonnées, le montant et la référence du lot seulement tant que le lot est réservé et non payé ; `/a-propos` nomme les moyens, sans coordonnées |
| E-mail | Aucun service d'envoi ; Brevo ou Mailjet, avec un domaine deSEC pour SPF et DKIM, quand le volume ou les mots de passe oubliés le justifieront |
| Indexation | La vitrine porte `noindex` tant que l'indexation n'est pas décidée |

## Ce qui est public, et ce qui ne l'est jamais

**Public**, pour une carte publiée dont tous les exemplaires sont disponibles :
photo du recto (et du verso s'il est photographié, sinon la fiche le dit), nom,
extension, numéro, langue, variante, état **s'il est confirmé** (sinon « état
non confirmé : voir la photo »), tampon et distribution, prix affiché et sa
date, identifiant de la publication.

Le tri « Les plus récentes » range les publications par jour, puis par nom : une
publication en masse se lit dans l'ordre alphabétique. Les tris par prix
départagent les égalités de la même façon.

La recherche lit le nom de la carte, son extension, son numéro et ses noms du
catalogue TCGdex dans les autres langues (`catalog_names`) : « eevee » trouve
Évoli. Sans résultat exact, elle pardonne une faute de frappe (lettre en trop,
en moins, changée ou inversée) dans les mots de cinq lettres ou plus, et la
page annonce des résultats approchés.

Les filtres **Extension**, **Langue**, **Budget max**, **Finition**, **État** et le tri
sont visibles sur ordinateur. Sur téléphone, la recherche et le tri restent
accessibles ; **Filtres** ouvre une vue dédiée avec les mêmes champs, le nombre
de critères actifs, la remise à zéro et **Voir les N annonces**. Fermer cette
vue ou appuyer sur Échap conserve les critères et ramène le focus au bouton.
Les critères actifs s'affichent aussi sous forme de boutons à retirer.

La vue Filtres conserve la recherche, le compteur et les critères actifs à
l'écran. Les changements s'appliquent immédiatement ; la fermeture conserve les
choix. Le titre principal reste accessible et le lien d'évitement mène toujours
au champ de recherche. Les contrôles de saisie ont une bordure distincte des
séparateurs pour rester repérables dans chaque thème.

Pendant une recherche, un statut visible et annoncé accompagne le chargement.
Si le réseau ou la réponse du serveur échoue, la vitrine affiche un message dans
la langue de la page et **Réessayer**, aussi accessible hors de la vue Filtres.
Les résultats précédents restent identifiés comme tels ; la recherche et les
critères sont conservés. Après l'échec d'**Afficher plus**, la reprise recharge
la page manquante sans retirer les cartes déjà affichées. Une recherche sans
résultat propose **Voir toutes les annonces** pour remettre les critères à zéro.

Le serveur applique tous les critères avant la pagination de 48 publications.
Le compteur indique le total des annonces correspondantes, cartes seules et
lots compris. Pour un lot, Langue, Extension, Finition et État doivent correspondre
à un **même exemplaire** ; la recherche textuelle examine l'ensemble du lot.
Le budget porte sur le prix du lot entier, dont la fiche conserve toutes les
cartes. Une carte réservée ou retirée fait disparaître toute sa publication.

Les choix de langue, extension, finition et état viennent de toutes les publications
disponibles, indépendamment du filtre et de la page courants (`languages`,
`extensions`, `finishes`, `conditions` dans la réponse). Une finition non renseignée n'est
pas assimilée à « Normale ». La finition affichée et filtrée reste celle de
l'exemplaire, selon la même liste de libellés publics que la fiche.

Le filtre d'état utilise uniquement le grade confirmé. **Non renseigné** réunit
les grades absents ou non confirmés, même si la gestion possède une estimation.
NM/EX est distinct de NM et EX ; MT reste reconnu pour les grades historiques.
Un lot peut correspondre à plusieurs états sans que tous ses membres les
partagent. La légende des grades rappelle qu'ils ne constituent pas une
certification externe. Un critère partagé reste retirable même si sa dernière
publication disparaît.

Chaque carte a son adresse, `/carte/<identifiant de la publication>`, que la
fiche permet de copier. Une carte retirée renvoie 404 avec la vitrine et un
message. Les filtres s'écrivent après le `#`
(`/#q=eevee&langue=en&extension=Jungle&finition=reverse&condition=EX&tri=price`) :
le serveur ne les voit pas, et `/` garde sa redirection des anciens liens de
gestion. Le bouton Retour ferme la fiche ouverte. Les vignettes sont des liens
vers cette adresse : un clic ouvre la fiche sur place, un clic milieu ou
Ctrl+clic l'ouvre dans un nouvel onglet. Le filtre de langue ne propose que les langues
d'au moins une carte en vente (`languages` dans la réponse de recherche).

La vitrine existe en français, à `/`, et en anglais, à `/en/` : mêmes cartes,
mêmes adresses sous le préfixe (`/en/carte/<identifiant>`, `/en/a-propos`). Un
lien dans l’en-tête mène à l'autre langue sur la même carte, avec les mêmes
filtres. La langue suit l'adresse, sans cookie ni redirection. Les textes sont
dans `web/messages/` ([fiche 0020](decisions/0020-textes-dans-des-dictionnaires.md)) ;
l'API publique envoie des codes (finition, statut), que la page nomme. Une
erreur que le visiteur peut rencontrer (carte retirée, mot de passe erroné,
trop de requêtes…) arrive avec son `detail` en français et un `code`, que la
page affiche dans sa langue ; un `detail` sans code connu s'affiche tel quel.

La fiche est une visionneuse : une photo à la fois, en grand, et les
informations dessous. **Verso** (ou **R**) retourne la carte ; pour un lot, le
même bouton passe d'une photo à la suivante. ‹ et › (ou ← et →, ou un
glissement horizontal sur la photo au téléphone) passent à la carte voisine
dans l'ordre de la liste filtrée, en chargeant la suite au besoin ; l'adresse
suit la carte affichée sans ajouter d'étape à l'historique, si bien que Retour
ramène toujours à la liste. Sur téléphone la fiche occupe tout l'écran ; sur
ordinateur, **Agrandir la fiche** (ou **F**) met la photo à gauche et les
informations à droite, un choix mémorisé sur l'appareil.

**Zoomer la photo** ouvre le mode photo dans la même fiche. Le curseur et les
boutons +/− règlent le grossissement, **Ajuster** montre tous les bords.
La souris déplace la photo agrandie ; sur téléphone, le défilement reste natif.
Au clavier, les flèches déplacent l'image lorsque sa zone a le focus. Elles ne
changent alors pas de carte. Le premier Échap revient à la fiche et le suivant
la ferme. Changer de face ou de publication réinitialise le zoom. Le contrôleur
de zoom est partagé avec la visionneuse de gestion ; les routes photo et les
dialogues restent propres à chaque interface.

La grille choisit une définition JPEG selon la place réellement occupée et la
densité d'écran. La fiche utilise une variante de consultation WebP, si disponible,
avec repli JPEG. Une petite source n'est jamais agrandie pour fabriquer une
variante ; un JPEG déjà adapté et sans métadonnée privée évite une recompression
inutile. La photo complète de consultation se charge à la demande du zoom,
sans précharger les voisines. L'original privé de prise de vue n'est pas exposé.

Les dimensions réelles et les variantes par face sont publiques dans `media`,
à côté du tableau `photos`. Les dérivés sont un cache reconstructible, lié au
contenu et aux paramètres d'encodage. Remplacer une photo change le dérivé ;
chaque accès vérifie à nouveau la disponibilité de la publication avant de
servir le cache.

L'entretien du cache public s'exécute séparément des sauvegardes. Il conserve
les dérivés des rectos et versos encore référencés par les exemplaires, y compris
hors vitrine, réservés ou supprimés. Il retire uniquement des dérivés reconnus
et non référencés, âgés d'au moins 30 jours, dans une limite de 200 fichiers et
64 Mio par passage. La base et les photos sources restent intactes. La commande
manuelle présente une simulation avant `--apply` ; la procédure figure dans
[Héberger le site](DEPLOYMENT.md#entretenir-le-cache-public).

Le serveur produit le titre, la description et les métadonnées Open Graph et de
carte sociale dans le HTML initial, sans JavaScript, en français et en anglais.
Un lot conserve son prix global et sa première photo publique. L'origine
`POKEPRICE_PUBLIC_ORIGIN` fournit les URL absolues ; sans cette configuration,
les titres et descriptions restent présents, les URL et images sociales sont
omises. Une publication indisponible répond 404 avec des métadonnées génériques.
`noindex` reste en place. Le site refuse la photo au prochain accès après
retrait ; un service tiers peut conserver un aperçu déjà copié.

Les actions de la fiche suivent les informations dans le défilement : elles ne
recouvrent ni le prix ni l'état. Sur téléphone, la hauteur de la photo laisse
de la place au nom et au prix, tandis que les faits et les actions restent
accessibles en faisant défiler la fiche.

**Jamais exposé hors de la gestion** : notes, provenance, événements, relevés
et historique de prix, prix de référence brut, alertes, état estimé non
confirmé, album, page et pochette, autres exemplaires, lots, ventes, acheteurs,
comptes. L'identifiant public est celui de la publication, jamais celui de
l'exemplaire. Les réponses publiques sont construites champ par champ, à partir
d'une liste blanche (`Storefront` dans `listings.py`).

## Le prix affiché

La fonction pure `display_price` de `pricing.py` propose le prix d'un
exemplaire, ou les raisons pour lesquelles il ne peut pas être publié seul. Le
prix proposé est le premier disponible dans cet ordre :

1. le prix saisi au moment de publier ;
2. si l'état est confirmé, l'estimation sur les offres Cardmarket au même état,
   arrondie au dixième supérieur ;
3. si l'état est confirmé, le prix saisi à la main sur la fiche, arrondi de
   même ;
4. la tendance du dernier relevé, arrondie au dixième supérieur, si la variante
   est confirmée, l'état MT, NM ou EX et la tendance inférieure à 10 €.

Aucune décote selon l'état n'est appliquée. Le plancher de 0,50 € se compare
au montant avant l'arrondi : une carte à 0,41 € va dans un lot ou se donne. Un
lot publié d'un bloc doit valoir au moins 0,50 €. Le prix figé dans une
publication ne change que si le vendeur le change ; un relevé plus récent est
seulement signalé.

## Le modèle de données

Chaque évolution de la base suit la règle du projet : copie de la base avant la
migration, transaction, `PRAGMA user_version` incrémenté.

- `users` accueille le rôle `client`, avec `email` (unique, insensible à la
  casse, vide pour les comptes de l'équipe), `display_name`, `status`
  (`pending`, `active`, `refused`) et `consent_at`. Un client né d'une demande
  sans compte a pour mot de passe le hachage d'une valeur aléatoire oubliée
  aussitôt : aucune connexion n'est possible avant un lien.
- `password_links` : `token_hash`, `user_id`, `created_by`, `created_at`,
  `expires_at`.
- `listings` : une publication. `id` (public), `state` (`online`, `offline`),
  `price_cents`, `price_mode` (`trend`, `manual`, `offers`), `price_source`,
  `price_date`, `published_at`, `published_by`, `version`. Ses exemplaires
  sont dans `listing_items(listing_id, copy_id)` : une seule ligne pour une
  carte, plusieurs pour un lot. L'index `single_listing` garantit qu'un
  exemplaire n'est que dans une publication en ligne.
- `requests` : `id`, `client_id`, `status` (`sent`, `accepted`,
  `partially_accepted`, `refused`, `expired`, `cancelled`), `message`,
  `sale_id` (le lot créé à l'acceptation), `created_at`, `expires_at`,
  `version`.
- `request_items` : `request_id`, `listing_id`, `price_cents` figé à la
  demande, `outcome` (`pending`, `accepted`, `unavailable`, `refused`).
- `settings` : `key`, `value_json`, `updated_by`, `updated_at`. La clé
  `payment` garde l'identifiant Wero (téléphone ou e-mail), l'IBAN, vérifié par
  sa clé, son titulaire et le PayPal (e-mail ou lien paypal.me) ; une valeur
  vide signifie que le moyen n'est pas proposé.

Après l'acceptation, le client voit le statut du lot : `reserved`, `sold`,
`shipped`, `completed`, `cancelled` ou `returned`, et la référence de paiement
du lot (`LILY-` suivi de huit caractères de son identifiant). Tant que le lot
est réservé et non payé, la demande porte aussi `payment` : total (prix du lot
et port facturé), port, référence et moyens de paiement.

## Les routes

**Publiques**, sans cookie, en lecture seule, limitées à 300 lectures par
minute et par adresse :

- `GET /` : la vitrine (`web/storefront.html`, `.js`, `.css`), séparée de la
  gestion : elle ne charge aucun code de gestion. `/vitrine` y redirige.
- `GET /en/` et `GET /en/carte/{id}` : la même vitrine en anglais ; `/en` y
  redirige.
- `GET /a-propos` : qui vend, comment se passe un achat, données conservées,
  contact, code source. `GET /en/a-propos` en est la traduction anglaise
  (`web/about.en.html`) ; elle annonce que la version française fait foi.
- `GET /api/public/listings` : recherche `q` (nom, extension, numéro), `language`,
  `extension` (nom exact), `finish` (`non_holo`, `holo`, `holo_border`, `reverse`
  ou `special`), `condition` (grade exact ou `unknown`), `max_eur`, `sort`, `limit`,
  `offset` ; seulement les publications
  en ligne dont tous les exemplaires sont disponibles. Un critère vide ne filtre
  pas ; les finitions inconnues sont refusées.
- `GET /api/public/listings/{id}` et `GET /api/public/listings/{id}/photo` :
  détail et photo par identifiant de publication, 404 si la carte n'est plus
  publiée. Le détail reçoit `view=1` à chaque ouverture de fiche pour mesurer
  cette ouverture ; les tailles de photos et le zoom ne la comptent pas à nouveau.
  La photo accepte `item`, `side`, `size` (`thumb`, `full`, `grid2`, `grid3`, `view`,
  `view2`) et `format` (`jpeg`, `webp` selon les variantes proposées). `thumb` et
  `full` conservent leur format JPEG ; les dimensions annoncées sont celles
  réellement produites.
- `POST /api/public/signup` : e-mail, nom, mot de passe de 10 caractères au
  moins, lecture de l'information sur les données ; crée un compte `pending`.
  La réponse et son délai sont les mêmes, que l'adresse soit connue ou non ;
  5 inscriptions par heure et par adresse au plus.
- `POST /api/public/requests` : la demande sans compte (cartes, message, nom,
  e-mail, lecture de l'information sur les données). Une adresse inconnue
  reçoit un compte `pending` sans mot de passe utilisable ; une adresse
  connue reçoit la demande, sauf un compte refusé, désactivé ou de l'équipe,
  qui ne reçoit rien. La réponse et son délai sont les mêmes dans tous les
  cas ; 5 demandes par heure et par adresse IP, 3 demandes en attente par
  e-mail au plus.
- `POST /api/public/password` : jeton d'un lien et nouveau mot de passe ; active
  le compte, efface ses autres liens et sessions, puis ouvre une session. Le
  lien a la forme `/#mot-de-passe=<jeton>` : le jeton reste après le `#`, que
  le navigateur n'envoie jamais au serveur ni dans le `Referer`, et la vitrine
  le retire de l'adresse dès l'ouverture.

**Client** (session, rôle `client` actif) :

- `GET`, `PATCH /api/me`, `GET /api/me/export`, `POST /api/me/delete` : voir,
  corriger, exporter ou supprimer son compte.
- `GET`, `POST /api/me/requests` et `POST /api/me/requests/{id}/cancel` : les
  demandes.
- `POST /api/login` (commun) : un compte `pending` reçoit « compte en attente
  de validation », seulement après un mot de passe juste et sans session ; un
  compte `refused` est traité comme inconnu ; une session cesse dès que le
  compte n'est plus actif.

**Équipe** :

- `GET /api/clients`, `PATCH /api/clients/{id}` : valider, refuser, désactiver.
- `POST /api/clients/{id}/password-link` (administrateur) : un lien à usage
  unique, valable 7 jours, qui remplace les précédents ; seule l'empreinte
  SHA-256 du jeton est gardée (`password_links`). Refusé pour un compte refusé
  ou désactivé.
- `GET`, `PUT`, `DELETE /api/copies/{id}/listing`, `GET`, `POST /api/listings`,
  `POST /api/listings/{id}/unpublish` : publier, changer le prix, retirer. Le
  rôle gestion publie ; la consultation voit seulement.
- `GET`, `PUT /api/settings/payment` (administrateur) : les moyens de
  paiement ; un IBAN sans titulaire ou à la clé fausse est refusé.
- `GET /api/requests`, `POST /api/requests/{id}/accept` (les cartes retenues),
  `POST /api/requests/{id}/refuse` (avec un motif). L'acceptation est une
  transaction unique : elle crée le lot, le réserve, valide un client en
  attente et marque `unavailable` les cartes déjà prises ; si un exemplaire est réservé entre-temps, le brouillon
  est annulé. La contrainte `single_reservation` arbitre deux acceptations
  concurrentes.

## Les garde-fous

- **Séparation des rôles.** Les routes de gestion exigent un compte de
  l'équipe (`staff` : admin, editor ou reader) ; les routes `/api/me/*`, un
  client. Un test (`tests/test_storefront_access.py`) parcourt toutes les
  routes et vérifie qu'un client reçoit 403 partout ailleurs que dans
  `/api/public/*` et `/api/me/*` ; la liste des routes ouvertes hors `staff` y
  est fixée. Les clients n'apparaissent pas dans `/api/users`.
- **Sessions.** Cookies `HttpOnly`, `SameSite=Strict` et `Secure` derrière
  HTTPS ; toute requête qui modifie vérifie l'en-tête `Origin`.
- **Débit.** Lectures publiques, inscriptions, connexions et demandes sont
  limitées.
- **Demandes.** Dix demandes en attente au plus par client ; une demande sans
  réponse expire au bout de 7 jours, constaté à la lecture.
- **Données des clients.** Durées de conservation appliquées chaque nuit par
  `purge`, droits exercés dans **Mon compte**, effacement par `forget` : voir
  [Données personnelles](RGPD.md).
- **Indexation.** `noindex` sur la vitrine ; `X-Robots-Tag: noindex, nofollow`
  sur la gestion et l'API.

## Les prochaines étapes

- D'autres langues que l'anglais ([feuille de route](ROADMAP.md#prévu)).
- Un essai de bout en bout automatisé sur une copie de la base (jalon M5).
- La décision sur l'indexation par les moteurs de recherche.
- Un service d'envoi d'e-mails, puis des intégrations autorisées aux
  plateformes de vente.

**Critère de réception**, tenu : un visiteur voit les cartes publiées sans
compte et envoie une demande avec son seul e-mail ; son acceptation crée
un lot réservé ; deux acceptations concurrentes ne réservent jamais deux fois le
même exemplaire ; aucune réponse publique ou client ne contient de champ privé.

## Confort, chargement et reprise

La grille propose deux colonnes sur téléphone, trois sur tablette et quatre
sur grand écran. Les noms longs gardent le prix dans sa propre zone. La fiche
rapproche photo et informations sur grand écran ; le mode agrandi reste disponible.
À propos reprend les couleurs et la marque de la vitrine, avec des liens directs
vers le catalogue et le contact.

Le menu Compte se ferme à Échap et au clic extérieur. Les formulaires se focalisent
sur leur premier champ ; leur fermeture revient au bouton Compte. Une soumission
en cours est annoncée et les activations répétées sont ignorées jusqu'à la réponse.
La sélection vide et la demande envoyée proposent un retour aux cartes.

La zone des résultats réserve de la place avant leur chargement et se réduit
lorsqu'aucune carte ne correspond. Une photo en échec présente un repli explicite ;
la fiche permet de réessayer. Sans JavaScript, un message mène au contact.

Les fichiers statiques publics se conservent avec revalidation obligatoire : une
empreinte ETag inchangée produit une réponse 304 sans corps. Le favicon se conserve
un jour sans requête réseau, puis se revalide par ETag ; ouvrir ou fermer une fiche
réutilise ainsi l'icône en cache. HTML, API, comptes et
photos restent en `no-store`. Une publication retirée cesse donc de servir ses
photos à toute nouvelle requête. Les photos et les appels de catalogue disposent
chacun d'un budget de lectures publiques ; une réponse 429 indique le délai de
reprise par `Retry-After`.
