# Glossaire

> **Pour qui :** toute personne qui découvre Lilydex.
> **Vous y trouverez :** les mots du projet, leur sens précis, leur équivalent anglais et, entre guillemets, le libellé de l'interface quand il diffère.

## Le produit

| Terme | Anglais | Définition |
|---|---|---|
| **Lilydex** | Lilydex | Le produit et le site : une vitrine publique et une gestion privée (`/gestion`). |
| **pokeprice** | pokeprice | Le nom technique du paquet Python et de ses commandes : `pokeprice` (pipeline d'albums), `pokeprice-manage` (application et exploitation), `pokeprice-agent` (pilote agent). |
| **Gestion** | management app | La partie privée, réservée à l'équipe : collection, photos, prix, lots, ventes, sauvegardes. |
| **Vitrine** | storefront | La partie publique, à la racine du site : les cartes publiées se consultent sans compte ; un client inscrit et validé peut demander une réservation. |
| **Rôles** | roles | Administration (« admin »), gestion (« editor ») et consultation (« reader ») pour l'équipe ; client pour la vitrine, sans accès à la gestion. |
| **Pipeline d'albums** | album pipeline | La commande `pokeprice scan` : découpe les photos de pages, lit chaque carte et la rapproche du catalogue. |
| **Serveur / portable** | server / laptop | Le serveur de production détient la base qui fait foi. Le portable numérise, rapatrie les sauvegardes et sert aux essais ; sa base est une ancienne copie. |
| **Pilote agent** | agent pilot | Un agent IA agit sur un album dans les limites d'une délégation révocable ; il ne prépare que des brouillons de lots. |

## Les cartes

| Terme | Anglais | Définition |
|---|---|---|
| **Exemplaire** | copy | Une carte physique précise, avec son identifiant durable. Deux cartes identiques font deux exemplaires. |
| **Édition** | print | Une impression précise : extension, numéro imprimé (78/110) et langue. |
| **Identifiant TCGdex** | TCGdex id | Le code qui désigne une édition sans ambiguïté (`ex13-78`). |
| **TCGdex** | TCGdex | Le catalogue ouvert de cartes qui sert de référence, avec les prix de Cardmarket et de TCGplayer. |
| **Cardmarket** | Cardmarket | La place de marché européenne qui fournit les prix en euros. |
| **Classeur, album, pochette** | binder, album, pocket | Le classeur est l'objet physique, l'album sa fiche dans l'application, la pochette une case d'une page. |
| **PV** | HP | Les points de vie imprimés sur la carte ; ils aident à départager deux éditions. |
| **État** | condition | L'état physique sur l'échelle de Cardmarket : MT, NM, EX, GD, LP, PL, PO. Une personne le retient ; l'aide à l'état ne fait que proposer. |

## Les variantes

| Terme | Anglais | Définition |
|---|---|---|
| **Finition observée** | observed finish | Ce qu'une personne voit sur la carte : mate, illustration holo, cadre holo, reverse, spéciale. |
| **Standard / Foil** | normal / foil | La série de prix Cardmarket retenue. Standard : la carte telle qu'imprimée d'origine, Rare Holo comprise. Foil : une version qui brille davantage (reverse, ou illustration holo sur une carte normalement mate). |
| **Reverse** | reverse holo | Un fond holographique autour d'une illustration mate. Il se voit mal sur une photo. |
| **Tampon** | stamp | Une marque imprimée sur l'illustration (une promo, par exemple). Il se saisit dans son propre champ. |
| **Confirmation physique** | physical check | La case cochée après examen de la carte en main. Elle est annulée si l'identité ou la photo change. |

## Les prix

| Terme | Anglais | Définition |
|---|---|---|
| **Relevé** | price snapshot | Un instantané daté des prix d'une édition (prix bas, moyennes, tendance) avec sa source. |
| **Prix de référence** | reference price | La tendance retenue, ou un prix saisi à la main. Ce n'est pas un prix de vente. |
| **Valeur prudente** | prudent value | Le plus bas entre la tendance et la moyenne à 30 jours. |
| **Valeur en jeu** | value at stake | La plus haute valeur prudente parmi les identités ou variantes encore possibles pour un exemplaire. |
| **Seuil de valeur** | value threshold | 10 € par défaut : au-delà, une incertitude envoie l'exemplaire dans « À examiner ». |
| **Estimation de vente** | sale estimate | La médiane des offres Cardmarket collées, au même état ; faute d'offre à cet état, une décote affichée de 0,75 par cran d'état. |
| **Prix de vitrine** | storefront price | Le prix public figé au moment de publier une carte. |
| **Lot** | lot | Des exemplaires vendus ensemble, du brouillon à la clôture : réservation, vente, paiement déclaré, expédition, retour. |

## Le contrôle

| Terme | Anglais | Définition |
|---|---|---|
| **« À examiner »** | review queue | La file des exemplaires qui demandent encore une décision humaine. |
| **« À vérifier »** | to check | Une identité proposée, qu'aucune personne n'a encore confirmée. |
| **Lecture (Gemini)** | reading | Gemini, un modèle vision-langage, lit la photo. Le résultat est une proposition, jamais une valeur confirmée. |
| **Contrôle d'édition par l'image** | image edition check | DINOv2 compare la photo aux images des éditions de même nom. Il signale un doute ; il ne modifie jamais la fiche. |
| **Porte énergie** | energy gate | Dans le pipeline d'albums, reconnaît par l'image les énergies de base pour éviter un appel à Gemini. |
| **Banc d'essai** | recognition bench | Des cartes vérifiées sur la carte physique, qui servent à mesurer les lecteurs et de test de non-régression. |
| **Référentiel des impressions** | print reference | Des règles appuyées sur des preuves : quelles impressions existent et quel produit Cardmarket leur correspond. |
| **Mode audit** | audit mode | Le référentiel s'affiche et se contrôle, sans encore remplacer l'ancien calcul de prix. |
| **Preuve, pièce scellée** | evidence | Un document source archivé sous son empreinte SHA-256, qui change si un seul octet change. |

## Les sauvegardes

| Terme | Anglais | Définition |
|---|---|---|
| **Sauvegarde quotidienne** | daily backup | Une archive ZIP (base et photos) faite chaque nuit sur le serveur et vérifiée par une restauration d'essai. |
| **Copie Drive** | Drive copy | La même archive, rapatriée par le portable, chiffrée avec l'outil age puis envoyée sur Google Drive. |
| **Instantané initial** | initial snapshot | La copie figée des fichiers d'origine, faite avant la création de l'application. |

## Les repères du projet

| Terme | Définition |
|---|---|
| **MVP** | La première version utilisable de bout en bout, décrite dans la [feuille de route](ROADMAP.md). |
| **M0 à M5** | Les jalons du MVP. M1.1 est le référentiel des impressions. |
| **Tranche** | Une partie livrable d'un jalon (M2-3, vitrine-3). |
| **C01 à C20** | Les scénarios de réception du [contrat du référentiel](PRINT_REFERENCE_CONTRACT.md). |
