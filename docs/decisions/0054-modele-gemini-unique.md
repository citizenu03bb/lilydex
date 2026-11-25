# 0054 — La lecture des cartes reste sur Gemini 3.8 Flash, sous un nom de modèle unique et réglable

> **Statut :** en vigueur, complète la [décision 0031](0031-modele-du-chat.md) · **Date :** 2026-11-25

**Contexte.** Le sélecteur de modèles d'Antigravity, l'outil de code de
Google, marque Gemini 3.8 Flash « Leaving Soon ». Sa page des modèles le
retire **d'Antigravity** le 30 novembre 2026. L'API Gemini, celle
qu'appelle l'application, ne lui donne aucune date d'arrêt
([dépréciations](https://ai.google.dev/gemini-api/docs/deprecations), relevé
du 25 novembre 2026). Google y redirige même `gemini-2.5-pro` à partir du
1er décembre. Le tarif de 3.8 Flash double au 1er janvier 2027, de 0,75 /
3,75 $ à 1,50 / 7,50 $ par million de jetons en entrée et en sortie.

Le nom du modèle était écrit en dur à six endroits. La lecture de carte
(identité, finition, langue, tampon, état) n'avait pas de variable pour le
changer.

La famille Gemini 4, au tarif payant standard
([tarifs](https://aistudio.google.com/docs/pricing), relevé du 25 novembre
2026), en dollars par million de jetons :

| Modèle | Entrée | Sortie |
|---|---|---|
| `gemini-4-hydrogen` | 1,50 | 7,50 |
| `gemini-4-neon` | 3,00 | 15,00 |
| `gemini-4-argon`, `gemini-4-carbon` | 2,00, puis 4,00 au 1er décembre 2026 | 10,00, puis 20,00 |

Hydrogen, le moins cher, coûte le même prix au jeton que 3.8 Flash en 2027.
Google le présente comme le remplaçant de 3.8 Flash. Il n'existe pas de
Gemini 4 Flash-Lite.

**Options.**
1. **Passer à Gemini 4 Hydrogen.**
2. **Passer à un modèle moins cher**, par OpenRouter : GPT-6 Luna,
   Claude Haiku 5.5, Qwen 3.8 Flash, Gemma 4 31B, Nemotron 3.5 Super VL, de
   5 à 30 fois moins chers au jeton.
3. **Rester sur 3.8 Flash**, et rendre le modèle réglable pour changer sans
   nouvelle version le jour où une date d'arrêt est annoncée.

**Mesure.** L'état est la tâche où 3.8 Flash est le plus faible
([fiche 0051](0051-porte-sur-les-erreurs-graves.md)). Les candidats ont relu
les cartes de l'échantillon à l'aveugle de 60 cartes, avec les mêmes photos,
la même consigne `card-condition-v2` et le même schéma de réponse que la
relecture de production. La vérité est la note que le propriétaire donne en
main. Une erreur grave est un écart de deux crans ou plus.

| Modèle | Notes exactes | Erreurs graves | dont optimistes | $ pour 100 lectures d'état |
|---|---|---|---|---|
| 3.8 Flash, production | 37/57 | 7 | 7 | 0,45 (0,90 en 2027) |
| 3.8 Flash, second passage | 36/59 | 9 | 8 | même tarif |
| Gemini 4 Hydrogen | 24/59 | 8 | 3 | 1,27 |
| Claude Haiku 5.5 | 18/57 | 12 | 2 | 0,08 |
| GPT-6 Luna | 23/59 | 16 | 9 | 0,07 |
| Gemma 4 31B | 16/54 | 12 | 10 | 0,01 |
| Nemotron 3.5 Super VL | 24/53 | 16 | 16 | 0,12 |
| Qwen 3.8 Flash | 17/59 | 18 | 13 | 0,17 (46 s par carte) |

*Conditions de mesure : 59 cartes d'une seule collection notées en main à
l'aveugle, photos de la série Prises de près, consigne `card-condition-v2` ;
la production par l'API Gemini, les autres passages par OpenRouter, en
excluant les fournisseurs qui conservent les données ; coût calculé à partir
des jetons mesurés et des tarifs publics de Google pour Gemini, coût facturé
par OpenRouter pour les autres ; 25 novembre 2026. Coût total du banc :
1,29 $.*

- **Aucun modèle moins cher ne tient la qualité.** Tous donnent moins de
  notes exactes et autant ou plus d'erreurs graves.
- **Hydrogen se trompe autrement, pas moins.** Il donne 3 erreurs graves
  optimistes au lieu de 8, mais 12 notes exactes de moins. Une note trop
  sévère fait vendre une carte sous sa valeur. Il réfléchit davantage : 1 271
  jetons de sortie par carte contre 806. Il coûte donc 2,8 fois plus par
  lecture qu'aujourd'hui, et 1,4 fois plus en 2027.
- **Le bruit est du même ordre que les écarts.** Deux passages de 3.8 Flash
  donnent 7 puis 9 erreurs graves. Sur 59 cartes, 3 contre 8 erreurs
  optimistes reste une indication.
- La lecture de carte et la finition n'ont pas été mesurées. Aucun candidat
  n'ayant tenu l'état, le banc s'est arrêté là.

**Décision.** Option 3.
- La lecture des cartes, le pipeline d'albums, l'interprétation des prompts
  de lots et le chat gardent `gemini-3.8-flash`.
- Le nom du modèle vit dans un seul module, `pokeprice/gemini_model.py`.
  `POKEPRICE_GEMINI_MODEL` le change partout. Le chat
  (`POKEPRICE_ASSISTANT_MODEL`) et les prompts de lots
  (`POKEPRICE_LOTS_GEMINI_MODEL`) gardent leur propre variable, qui l'emporte
  sur la variable commune.
- Le modèle est lu à l'appel : chaque lecture enregistre le modèle qui l'a
  produite.

**Coût estimé, comparé à 3.8 Flash.**
- **Pour 100 cartes lues**, finition, contrôle d'édition et état compris :
  environ 0,8 € aujourd'hui et 1,6 € à partir de janvier 2027 avec 3.8 Flash.
  Avec Hydrogen, environ 2,2 € dès maintenant, d'après les jetons de réflexion
  mesurés sur l'état.
- **Pour le chat**, à 30 commandes par jour : 3,28 $ par mois aujourd'hui et
  6,56 $ en 2027 ([fiche 0031](0031-modele-du-chat.md)). Hydrogen n'a pas été
  passé au banc du chat. À jetons égaux, il coûterait le double jusqu'au
  31 décembre, puis autant.

**Conséquences.**
- Le jour où Google annonce une date d'arrêt pour 3.8 Flash, le changement se
  fait par la variable, après un nouveau passage au banc. Hydrogen est le
  premier candidat.
- Le banc de la consigne `card-condition-v3`
  ([fiche 0052](0052-pli-en-main-et-bareme-cardmarket.md)) reste à refaire
  pour chaque candidat : les chiffres ci-dessus portent sur la v2.
- Garder la note la plus sévère entre 3.8 Flash et Haiku 5.5 laisse une seule
  erreur grave optimiste sur ces 59 cartes, pour 0,08 $ de plus par 100
  cartes, mais 21 notes exactes seulement. Cette règle a été trouvée sur ces
  mêmes cartes : elle ne vaut qu'après mesure sur un nouvel échantillon à
  l'aveugle.
- L'API Batch de Google divise le prix par deux pour les lectures que
  personne n'attend : import de classeur, relecture par l'agent de revue,
  pipeline d'albums. Elle fait l'objet d'un travail à part.
- Le banc, les photos et les lectures restent hors du dépôt, avec
  l'échantillon à l'aveugle.

**Preuve.** `tests/test_gemini_model.py` (valeur par défaut, variable
commune, priorité des variables du chat et des lots, lecture à l'appel).
