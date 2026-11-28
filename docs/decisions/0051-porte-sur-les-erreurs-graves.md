# 0051 — La porte de l'agent de revue compte les erreurs d'état graves, et le réglage gouverne toute écriture automatique

> **Statut :** en vigueur, précise la porte de la [décision 0049](0049-etat-sans-manipulation.md) et de la feuille de route, modifiée par la [décision 0055](0055-etat-note-par-une-personne.md) (un réglage par facette, sans écriture hors du réglage) · **Date :** 2026-11-25

**Contexte.** Avant d'écrire, l'agent de revue doit passer une vérification à
l'aveugle : aucune variante fausse, et une borne haute à 95 % du taux
d'erreur d'état sous 10 %. Une erreur d'état comptait tout écart de note,
même d'un cran. La référence est la note qu'une personne donne au classeur,
sans carte de comparaison. Sur l'échantillon de 60 cartes, cette note diffère
de l'état enregistré en base sur 28 cartes, et de deux crans ou plus sur 11.
Un écart d'un cran mesure donc surtout le bruit de la référence. Sous 10 €,
il change le prix de quelques centimes. Un écart de deux crans fait entrer
dans un lot, ou dans une annonce, une carte jouée présentée comme
excellente : c'est le risque à mesurer.

L'écriture automatique avait aussi un chemin hors du réglage : une photo qui
répond à une demande relançait l'agent en écriture, même avec
`agent_review_apply` à faux. Sept demandes ouvertes, laissées par des
passages manuels, l'exposaient en production.

**Options.**
1. **Garder l'écart exact** : la porte reste fermée tant que la référence
   elle-même varie d'un cran.
2. **Compter les erreurs graves** : deux crans ou plus, dans un sens ou dans
   l'autre, sur les états que l'agent confirmerait.
3. **Comparer l'agent à l'état enregistré** : ouvrir dès que l'agent se
   trompe moins que la base. L'état enregistré n'a jamais été vérifié, et la
   différence ne se mesure pas sur 60 cartes.

**Décision.** Option 2.
- **Variante** : aucune variante fausse parmi celles que l'agent
  confirmerait (édition, finition, langue, tampon).
- **État** : parmi les états que l'agent confirmerait, la borne haute à 95 %
  (Clopper-Pearson) du taux d'erreur grave reste sous 10 %. Une erreur grave
  est un écart de deux crans ou plus sur l'échelle NM, EX, GD, LP, PL, PO.
  Les écarts d'un cran sont publiés, et ne comptent pas.
- Les cartes d'au moins 10 € restent à une personne.
- Le réglage `agent_review_apply` gouverne toute écriture automatique de
  l'agent : import, série Prises de près, et photo qui répond à une demande.
  Faux, la nouvelle photo est lue, et rien n'est écrit. Seule la commande
  `agent-review --apply`, lancée par l'opérateur, écrit hors du réglage, et
  jamais une identité importée.

**Mesure (protocole `card-condition-v2`, 60 cartes relues).**
- Variante : 34 justes sur 35 confirmations. Magirêve serait confirmée holo.
  Elle porte un dégradé imprimé, sans brillance, et une photo de face ne les
  distingue pas. **La porte échoue.**
- État : 57 cartes notées, 37 au cran exact, 13 à un cran, 7 à deux crans ou
  plus. Les 7 erreurs graves sont toutes optimistes. Parmi les 50 états que
  l'agent confirmerait, 5 erreurs graves : borne haute 21,8 %. **La porte
  échoue.**
- À titre de comparaison, l'état enregistré compte 11 erreurs graves sur 60.
- `agent_review_apply` reste faux.

**Conséquences.**
- Pour passer : aucune erreur grave sur au moins 36 confirmations, une au
  plus sur 54, ou deux au plus sur 70, et aucune variante fausse.
- Deux pistes, à mesurer sur un nouvel échantillon à l'aveugle, pas sur
  celui-ci : ne confirmer une finition holo sur photo de face que si le
  catalogue exclut la version mate, sinon exiger la prise au reflet ; et ne
  pas confirmer un état meilleur que l'état enregistré de deux crans ou plus.
- Les mesures et les réponses restent hors du dépôt, avec l'échantillon.

**Preuve.** `tests/test_agent_review.py` (photo lue sans écriture avant la
porte), mesure par `mesure_v2.py` sur les lectures de production.
