# 0027 — Les frais de port s'affichent avant la réservation avec recommandé obligatoire dès 50 € et remise en main propre gratuite

> **Statut :** proposée · **Date :** 2026-11-04

**Contexte.** Les acheteurs de la vitrine pouvaient réserver des cartes sans
connaître le montant total exact ni les frais de port applicables. L'opératrice
devait calculer manuellement l'affranchissement, vérifier les tranches de poids
de La Poste et rédiger un message de confirmation avec les coordonnées de
paiement. Sans conditions de vente publiées, les modalités de rétractation
(délai légal de 14 jours pour les consommateurs, exclusions pour vente entre
particuliers), les délais de réponse (48 h avec les alertes au vendeur, 120 h sans) et les
règles d'expédition manquaient de transparence.

**Options.**
1. Frais de port forfaitaires uniques (par exemple 3 € par commande) : simple,
   mais déficitaire pour les envois volumineux ou de valeur nécessitant une
   assurance, et dissuasif pour une commande d'une seule carte commune.
2. Lettre suivie systématique avec recommandé facultatif au choix du client,
   quel que soit le montant : laisse le risque de perte postale non indemnisée
   à la charge du vendeur ou de l'acheteur sur les cartes de valeur (la lettre
   suivie n'indemnise pas le contenu).
3. Lettre suivie calculée au poids (poids estimé des cartes + emballage rigide de
   10 g), recommandé avec accusé et signature R2 obligatoire dès 50 € de cartes
   (seuil de confort inspiré de Cardmarket pour sécuriser l'envoi), remise en
   main propre gratuite à 0 €, et publication de conditions de vente bilingues
   détaillant les délais de garde de 7 jours, les moyens de paiement et la
   politique de retour.

**Décision.** Option 3.
- Les tarifs postaux officiels 2026 de La Poste (Lettre suivie et Recommandé R2)
  sont définis une seule fois (`reservations.py`) : le devis
  (`shipping_quote`), le panier (`/api/public/shipping`) et les pages de
  conditions en sont tirés.
- Le devis s'actualise en temps réel dans le panier de la vitrine dès que les
  cartes sont ajoutées ou retirées, et bascule immédiatement entre expédition
  postale et remise en main propre (`[delivery:hand]`).
- Dès que le sous-total des cartes atteint ou dépasse 50,00 €, le palier
  recommandé R2 est automatiquement appliqué pour l'expédition postale afin de
  garantir une indemnisation adaptée jusqu'à 153 €.
- Une réponse préremplie complète est générée en 1 clic dans l'interface de
  gestion pour l'opératrice, reprenant le décompte des cartes, l'affranchissement,
  le total à régler, les instructions de virement/Wero et le délai de garde de 7 jours.
- Deux pages statiques bilingues `/conditions` et `/en/conditions` exposent la
  grille tarifaire, les délais de réponse (48 h avec les alertes au vendeur, 120 h sans),
  l'absence de droit de rétractation entre particuliers et les règles d'expédition.

**Conséquences.**
- L'acheteur voit le coût total exact avant de réserver et s'engage en
  connaissance de cause.
- Le seuil de 50 € évite les litiges d'acheminement sur les cartes de collection.
- L'opératrice n'a plus à calculer les frais ni à rédiger manuellement ses
  messages de confirmation.

**Preuve.** `tests/test_shipping_and_conditions.py`, `tests/test_reservations.py`.
