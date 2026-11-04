# Fiches de décision

> **Pour qui :** toute personne qui veut comprendre pourquoi le projet est construit ainsi.
> **Vous y trouverez :** une fiche par choix important : contexte, options, mesure, décision, conséquences.

Une décision remplacée n'est pas réécrite : la fiche suivante la cite et
l'ancienne passe au statut « remplacée ».

| N° | Décision | Date |
|---|---|---|
| [0001](0001-application-maison.md) | Une application maison plutôt qu'un logiciel existant | 2026-10-04 |
| [0002](0002-oracle-cloud-serveur-fait-foi.md) | Oracle Cloud gratuit, et le serveur fait foi | 2026-10-16 |
| [0003](0003-drive-depuis-le-portable-chiffre.md) | Seul le portable accède à Drive, et les copies sont chiffrées | 2026-10-18 |
| [0004](0004-gemini-seul-lecteur.md) | Gemini seul lecteur de texte | 2026-10-13 |
| [0005](0005-langue-sans-tesseract.md) | Un contrôle de cohérence de la langue plutôt que Tesseract | 2026-10-14 |
| [0006](0006-dinov2-marge.md) | DINOv2 plutôt que CLIP, avec une marge de 0,05 | 2026-10-13 |
| [0007](0007-seuils-confort-securite.md) | Seuils de confort et seuils de sécurité, jugés sur le pire de deux passages | 2026-10-13 |
| [0008](0008-reverses-examen-physique.md) | Les reverses de valeur sont vérifiées à la main | 2026-10-13 |
| [0009](0009-torch-cpu-arm.md) | torch pour processeur seul sur le serveur ARM | 2026-10-18 |
| [0010](0010-porte-energie.md) | La porte énergie, avec une marge de 0,10 | 2026-10-16 |
| [0011](0011-referentiel-mode-audit.md) | Le référentiel des impressions en mode audit | 2026-10-13 |
| [0012](0012-agent-brouillons.md) | Le pilote agent n'écrit que des brouillons | 2026-10-19 |
| [0013](0013-pas-de-synchronisation.md) | Pas de synchronisation entre le portable et le serveur | 2026-10-20 |
| [0014](0014-corrections-agent-autorisees.md) | L’agent applique seulement les corrections déjà autorisées | 2026-10-20 |
| [0015](0015-energies-de-base-en-vrac.md) | Les énergies de base confirmées partent en vrac | 2026-10-23 |
| [0016](0016-guide-des-prix-cardmarket.md) | Le guide des prix officiel de Cardmarket complète TCGdex | 2026-10-23 |
| [0017](0017-python-3-11-minimum.md) | Python 3.11 au minimum | 2026-10-27 |
| [0018](0018-reservation-sans-compte.md) | Une réservation se demande sans compte | 2026-10-27 |
| [0019](0019-les-cartes-de-lily.md) | Le produit s'appelle Les cartes de Lily | 2026-10-27 |
| [0020](0020-textes-dans-des-dictionnaires.md) | Les textes de la vitrine vivent dans des dictionnaires JSON | 2026-10-27 |
| [0021](0021-autonomie-maximale.md) | Les agents agissent seuls, sauf l'argent, l'irréversible et le bradage | 2026-11-03 |
| [0022](0022-agent-confirme-ou-demande-photo.md) | L'agent confirme sur preuves concordantes, sinon il demande une photo | 2026-11-03 |
| [0023](0023-cote-retenue-marche-instable.md) | La cotation en lot retient une cote qu'un marché instable ferait bondir | 2026-11-03 |
| [0024](0024-deplacements-en-lot.md) | Un déplacement en lot refuse les cartes engagées dans un lot ou une vente et s'applique tout ou rien | 2026-11-04 |
| [0025](0025-photo-page-classeur-gestion.md) | Une photo de page de classeur 3×3 se dépose dans la gestion comme un lot de photos annulable | 2026-11-03 |
| [0026](0026-plancher-anti-bradage-gestion.md) | Le plancher anti-bradage s'applique aussi aux prix fixés depuis la gestion | 2026-11-04 |
| [0027](0027-frais-de-port-et-conditions-de-vente.md) | Les frais de port s'affichent avant la réservation avec recommandé obligatoire dès 50 € et remise en main propre gratuite | 2026-11-04 |
| [0028](0028-reserve-de-photos-par-empreinte.md) | Le serveur garde ses photos une seule fois, dans une réserve par empreinte, et le portable reconstitue l'archive autonome | 2026-11-04 |
| [0029](0029-assistant-de-gestion.md) | Un assistant de gestion : un brief du jour, une file « À toi », puis un chat qui ne passe que par des outils fermés (proposée) | 2026-11-04 |
| [0030](0030-derogations-plancher.md) | Un prix sous le plancher devient une demande de dérogation qu'une personne tranche | 2026-11-04 |
| [0031](0031-modele-du-chat.md) | Le chat de gestion passe par Gemini Flash, avec une clé à lui, tant qu'aucun modèle local ne tient sur le serveur | 2026-11-04 |
| [0032](0032-outils-assistant-lecture.md) | Le chat de gestion lit par huit outils fermés, sous une portée de délégation en lecture seule (proposée) | 2026-11-04 |
| [0033](0033-notifications-web-push.md) | La gestion installée reçoit ses alertes par Web Push ; ntfy reste en secours (proposée) | 2026-11-04 |
| [0034](0034-conversations-du-chat.md) | Les conversations du chat restent 30 jours au plus, dans un fichier à part, hors des sauvegardes | 2026-11-04 |

## Écrire une fiche

Copiez une fiche existante. Le titre dit la décision, pas le sujet. Donnez les
options réellement envisagées, avec leurs chiffres quand ils existent, et les
conséquences acceptées, y compris les mauvaises.
