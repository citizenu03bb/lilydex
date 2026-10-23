# Plan d'action : les exemplaires sans prix

> **Pour qui :** le propriétaire de la collection et toute personne qui l'aide à résorber les exemplaires sans prix.
> **Vous y trouverez :** l'état de la collection au moment du plan, les cinq causes d'absence de prix, une action par cause, l'ordre recommandé et la décision qui reste à prendre.
> **Statut :** plan daté du 23 octobre 2026, non tenu à jour. Les parcours de référence sont dans [Résoudre les cartes](RESOLUTION_CARTES.md#3-parcours-2--confirmer-les-cartes--à-vérifier--et-combler-les-prix-manquants) ; ce qui sera fait ira dans le [journal](JOURNAL.md).

## Le constat

Sur 1 737 exemplaires, 276 n'ont pas de prix de référence. La moitié sont des
énergies de base (137), que Lilydex ne cote jamais par choix
([fiche 0010](decisions/0010-porte-energie.md)). Le reste relève de quatre
causes, chacune avec son propre remède.

| Groupe | Exemplaires | Cause | Action |
|---|---:|---|---|
| Énergies de base | 137 | Jamais cotées par conception : 82 passées par la porte énergie (non identifiées), 49 confirmées sans lien catalogue, 6 à vérifier | [A1](#a1--sortir-les-énergies-de-base-du-compteur) |
| À vérifier | 73 | Une identité est proposée, pas confirmée : le prix est retiré en attendant ; toutes ont une photo | [A2](#a2--confirmer-en-lot-les-identités-proposées) |
| Liées, sans cotation en euros | 40 | Le relevé TCGdex existe, sans montant Cardmarket (35 Standard, 5 Foil), surtout des extensions anciennes | [A5](#a5--laisser-inconnu-ce-que-le-marché-ne-cote-pas) |
| À identifier | 15 | Aucune lecture exploitable ; toutes ont une photo | [A3](#a3--identifier-les-15-cartes-restantes) |
| Confirmées sans lien | 11 | Identité saisie à la main, jamais rattachée au catalogue | [A4](#a4--rattacher-les-11-cartes-confirmées-sans-lien) |

*Conditions de mesure : requêtes en lecture seule sur la base du serveur, le
23 octobre 2026 ; une énergie de base est repérée à son nom par la règle de la
porte énergie, qui exclut les énergies spéciales et les dresseurs.*

## Les principes

- Le temps humain va là où une erreur coûte de l'argent ; le reste part en
  lots, au prix du vrac.
- Ni le code ni un agent ne confirment une variante ou un état sur photo.
- Une confirmation d'identité acquiert le relevé TCGdex ; aucun prix n'est
  saisi sans source.
- Toute écriture se fait sur le serveur, après une sauvegarde (`backup`), par
  l'application ou une commande lancée avec `--data`.

## Les actions

### A1 — Sortir les énergies de base du compteur

**Objectif :** que « sans prix » ne compte plus les 140 énergies de base, qui
ont une valeur de vrac et non une cote à chercher.

**Décidé : option 1** ([fiche 0015](decisions/0015-energies-de-base-en-vrac.md)). Les options étaient :

1. **Une règle dans le code** (recommandée) : une énergie de base confirmée
   est classée « vrac », comptée à part dans les totaux et proposée en lot,
   jamais en carte seule. Les 83 énergies passées par la porte doivent d'abord
   être confirmées comme énergies de base, en lot, sur planche.
2. **Une référence sourcée saisie à la main** pour chaque énergie, d'après le
   prix du vrac sur Cardmarket : plus rapide à écrire, mais 140 saisies et une
   valeur qui vieillit.

Reste à confirmer en lot les 88 énergies proposées par la porte ou à vérifier.

**Fin :** le compteur « sans prix » ne contient plus d'énergie de base.

### A2 — Confirmer en lot les identités proposées

**Objectif :** confirmer les 73 identités proposées ; le relevé TCGdex arrive
avec la confirmation.

1. Préparer une planche de contrôle (`scripts/audit_photo_identity.py
   sheets`) : chaque photo, avec un zoom sur le numéro, étiquetée de
   l'identité proposée. En cas de doute, la fiche montre l'image TCGdex de
   l'édition à côté du recto.
2. Le propriétaire valide ou écarte chaque carte sur la planche.
3. Approuver le lot validé sur le serveur
   (`pokeprice-manage agent-approve-corrections`), qui revérifie nom, numéro
   complet, PV et empreinte du recto.
4. L'agent délégué applique les corrections approuvées
   (`pokeprice-agent apply-correction`), sans toucher aux états physiques.

**Fin :** aucune carte « à vérifier » avec un lien catalogue ; les cartes
écartées passent en A3.

### A3 — Identifier les 15 cartes restantes

**Objectif :** donner une identité aux 15 cartes « À identifier ».

1. Contrôler les découpes (`scripts/audit_photo_crops.py`) : une pochette mal
   découpée tronque souvent le nom ou le numéro.
2. Rapprocher hors ligne contre le cache TCGdex et DINOv2
   (`scripts/audit_photo_identity.py`), puis valider comme en A2.
3. Ce qui reste : « Identifier la carte » dans la fiche, avec la carte en main.

**Fin :** chaque carte est identifiée, ou marquée hors catalogue avec sa raison.

### A4 — Rattacher les 11 cartes confirmées sans lien

**Objectif :** relier au catalogue les 11 cartes saisies à la main.

- 8 cartes françaises ou anglaises ont nom, numéro et PV : « Identifier la
  carte », puis « Rechercher ». Le suffixe de niveau (« NIV. 31 ») n'est pas en
  cause : le rapprochement l'ignore déjà.
- Héricendre (45/101) a une langue inconnue : la lire sur la carte d'abord.
- Les 2 cartes japonaises Neo portent un numéro de Pokédex, pas un numéro de
  carte : vérifier si TCGdex les connaît ; sinon, référence sourcée seulement
  si la carte a de la valeur.

**Fin :** chaque carte a un lien catalogue, ou une raison écrite de ne pas en
avoir.

### A5 — Laisser inconnu ce que le marché ne cote pas

**Objectif :** ne pas inventer de prix pour les 40 cartes que TCGdex ne cote
pas en euros.

- Laisser le prix inconnu : c'est l'information exacte.
- Pour une carte mise en vente ou de valeur visible, coller les offres
  Cardmarket de même état (estimation de vente,
  [valeur en jeu](VALUATION.md)).
- Relancer un relevé de temps en temps : TCGdex complète ses cotations.

**Fin :** aucune action de masse ; chaque vente part d'offres réelles.

## L'ordre recommandé

| Ordre | Action | Effort | Effet sur « sans prix » |
|---|---|---|---|
| 1 | A1 — énergies de base | règle faite ; confirmer en lot les 88 proposées | −137 |
| 2 | A2 — identités proposées | une séance sur planche | jusqu'à −73 |
| 3 | A4 — confirmées sans lien | 11 fiches | jusqu'à −11 |
| 4 | A3 — à identifier | une séance, carte en main pour le reste | jusqu'à −15 |
| 5 | A5 — sans cotation | au fil des ventes | — |

Après A1 et A2, il resterait environ 66 exemplaires sans prix, si les
identités proposées se confirment presque toutes. Aucune de ces actions ne
demande d'examen physique de variante : ce travail reste dans la file
« À examiner ».
