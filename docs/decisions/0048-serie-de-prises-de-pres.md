# 0048 — Les prises de près se font en série, dans l'ordre du classeur, sur la liste que l'agent tient même en simulation

> **Statut :** en vigueur, complète les décisions [0022](0022-agent-confirme-ou-demande-photo.md) et [0047](0047-import-de-classeur-sur-le-serveur.md), modifiée par la [décision 0049](0049-etat-sans-manipulation.md) (« à examiner en main » devient « restent en l'état ») · **Date :** 2026-11-21

**Contexte.** Une photo de page suffit à identifier une carte, pas à la
confirmer. Sur les 105 cartes de la vérification à l'aveugle, l'agent de revue
demandait une photo pour 104 : coins de près 68, verso 18, reflet 18, recto 16.
Les deux erreurs de finition de cette vérification sont des couleurs imprimées
lues comme de la brillance ; une prise au reflet les tranche. Le critère S5
(100 cartes en moins d'une heure de travail humain) dépend donc de la vitesse
de ces prises. La liste « Photos demandées » existe, mais elle ne contient que
les demandes enregistrées, et l'agent n'enregistre rien en simulation : sur un
classeur importé, tant que `agent_review_apply` est faux, elle reste vide. Une
carte saisie en série prend environ 2 minutes.

**Options.**
1. **Enregistrer les demandes même en simulation** : la simulation écrirait,
   ce que la fiche 0047 exclut, et une annulation de passage ne saurait pas
   les retirer.
2. **Reprendre la fiche de chaque carte**, bouton par bouton : quatre à six
   gestes par carte, et la carte à chercher dans le classeur.
3. **Une série guidée**, dont la liste est le verdict courant de l'agent sur
   les cartes visées, recalculé à l'ouverture, sans rien écrire.

**Décision.** Option 3.

*La liste.* Un administrateur ouvre **Prises de près** pour un import, un
album ou une liste d'exemplaires. Le serveur fait passer l'agent en
simulation sur ces cartes et garde celles dont le verdict demande une photo.
La liste suit l'ordre du classeur : album, page, pochette. Une vue déjà prise
dans la série, ou déjà reprise pour une demande enregistrée, n'est pas
redemandée (règle de la fiche 0022) : la carte passe dans « à examiner en
main ». Une carte dont la reprise est en cours de lecture n'y figure pas.

*Une étape par carte.* L'écran montre la page, la pochette sur la grille de
l'import (3×3 sans import) et la vignette actuelle. Il dit quoi prendre, au
plus une photo par face, comme l'agent la demande : d'abord le recto (reflet,
coins de près ou recto net), puis le verso. Le reflet est la carte inclinée
sous une lumière rasante ; les coins de près, le recto hors pochette, les
quatre coins nets dans le cadre.

*La prise.* Une photo remplace la face qu'elle vise par le chemin de la fiche
(même contrôle du fichier, même redimensionnement, même journal). Une prise au
reflet est enregistrée comme telle (`GLINT_EVENT`) et passe par la lecture de
finition de la fiche 0047. La prise est aussi notée dans le journal de la carte
(`closeup-shot`, avec la vue et la photo). Le téléphone passe à la carte
suivante sans attendre le serveur ; les envois d'une même carte partent l'un
après l'autre.

*La nouvelle lecture.* Après la réponse, le serveur lit la carte sur ses
nouvelles photos (finition, édition par l'image, état), puis fait passer
l'agent sur elle seule. Il écrit si `agent_review_apply` est vrai ; sinon, la
simulation dit seulement ce qu'il confirmerait, et ce verdict est noté dans le
journal de la carte (`closeup-review`). Les lectures coûtent des appels Gemini,
comptés comme ceux d'une fiche.

*La reprise des 60 cartes de la vérification à l'aveugle.* La liste
d'exemplaires sert à reprendre en photo les mêmes cartes, pour comparer les
verdicts aux réponses déjà données au classeur.

**Conséquences.**
- Une carte demande une ou deux photos, et un geste par photo ; la personne ne
  cherche plus la carte dans le classeur.
- La liste coûte un passage de l'agent en simulation à chaque ouverture, sans
  appel Gemini ; elle n'est pas tenue à jour pendant la série.
- En simulation, une série ne confirme rien : elle produit les preuves et dit
  ce que l'agent ferait. Le gain de S5 n'est acquis qu'après la porte.
- Une prise ratée laisse la carte à l'examen en main, sans boucle de photos.

**Preuve.** `tests/test_closeups.py`, `scripts/bench_closeups.py`.
