# 0045 — Une carte qui quitte un lot revient seule en vitrine à partir de 1 €

> **Statut :** en vigueur, amende la [décision 0044](0044-outil-des-lots-par-l-api-agent.md) · **Date :** 2026-11-11

**Contexte.** Publier un lot retire les annonces unitaires de ses cartes. La
[décision 0044](0044-outil-des-lots-par-l-api-agent.md) laissait ces cartes
sans annonce quand le lot est retiré ou remplacé : elles attendaient leur
prochaine composition. Avec la rotation des lots en ligne, chaque remplacement
libère les cartes que le remplaçant ne reprend pas, et des cartes qui valent
quelque chose resteraient hors de la vitrine. Un relevé en lecture seule des
cinq lots en ligne de l'outil compte 91 cartes pour 189 € : les 30 cartes
d'au moins 1 € en portent environ 170 €, les 58 sous 1 € environ 19 €. Avoir eu
une annonce unitaire avant le lot ne sépare rien : la valeur du jour, si.

**Options.**
1. Laisser les cartes sans annonce jusqu'au prochain lot : environ 170 € hors
   vitrine à chaque rotation.
2. Rétablir les annonces unitaires d'avant le lot : leur prix est périmé, et
   les cartes jamais publiées seules restent dehors.
3. Remettre en annonce unitaire, au prix du jour relevé au plancher, toute
   carte qui en vaut au moins 1 €, qu'elle ait eu une annonce ou non.

**Décision.** Option 3, confirmée par le propriétaire. Quand une carte quitte
une annonce de lot de l'outil par la rotation d'un lot en ligne
(`POST /lots/rotate`) ou par un retrait (`POST /lots/{listing_id}/unpublish`),
et que le remplaçant ne la reprend pas, elle revient seule en vitrine si son
prix du jour, relevé au plancher anti-bradage, atteint 1 €.

- **Prix.** Le prix d'une carte seule aujourd'hui (`display_price` : offres au
  même état, prix fixé à la main, ou tendance arrondie au dixième), relevé au
  plancher du jour (référence moins la marge de l'administrateur, jamais sous
  0,50 €). Sans prix automatique pour une carte seule (état à confirmer ou
  sans tendance, par exemple), le plancher seul fait le prix. Jamais le prix
  qu'elle avait avant le lot.
- **Jamais remise en annonce.** Une carte sans cote, à l'identité à confirmer,
  à examiner, que les règles du plancher refusent, ou sous 1 € après le
  plancher. Elle retourne au gisement des doublons pour le prochain lot, comme
  avant. Les exemplaires de l'album restent hors de l'outil des lots.
- **Écriture.** Dans la transaction du retrait ou du remplacement, par la
  publication unitaire de la vitrine (`Listings.publish`) : auteur
  `agent:<accès>`, seulement avec `lots:publish`, vitrine seule (aucune
  plateforme externe). Une carte que la publication refuse n'écrit rien et la
  réponse le dit ; tout autre échec annule le retrait entier.
- **Quota.** Ces annonces unitaires ne comptent pas dans le quota des lots
  publiés par jour : ce ne sont pas des lots, et leur nombre par appel est
  borné par les cartes du lot qui vient d'être retiré.
- **Réponse.** `relisted` (exemplaire, annonce, prix, plancher) et
  `not_relisted` (exemplaire et motif : `in_replacement`, `stock_unavailable`,
  `already_listed`, `identity_unconfirmed`, `review_needed`, `no_price`,
  `below_minimum`, `refused`).

**Conséquences.**
- La conséquence de la décision 0044 « Les annonces unitaires remplacées par
  un lot ne reviennent pas… » ne vaut plus pour les cartes d'au moins 1 € ;
  elle vaut encore pour les autres.
- Une carte remise en annonce reste dans le gisement : un lot suivant peut la
  reprendre, et sa publication retire l'annonce unitaire comme toute autre.
- Le script de l'opérateur (`scripts/pokeprice_lots.py --data`) ne retire ni
  ne remplace de lot en ligne : rien n'y change.
- Une carte relevée au plancher se vend au prix le plus bas que la marge
  autorise ; c'est accepté, à revoir avec de vraies ventes.
