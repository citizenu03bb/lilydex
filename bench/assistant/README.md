# Banc du modèle du chat de gestion

Ce banc choisit le modèle du chat de gestion
([fiche 0029](../../docs/decisions/0029-assistant-de-gestion.md),
[fiche 0031](../../docs/decisions/0031-modele-du-chat.md)). Il rejoue un jeu de
commandes types sur chaque candidat et mesure, dans l'ordre des critères de la
fiche 0029 : la fiabilité des appels d'outils, la latence, les jetons (donc le
coût). Il vit hors du paquet `pokeprice` et ne lit aucune base : les outils
répondent avec des données synthétiques.

## Fichiers

| Fichier | Rôle |
|---|---|
| `commands.json` | les commandes types, en français familier, avec l'appel attendu |
| `tools.json` | les schémas : 8 outils en lecture (V1, copie de `docs/assistant-tools.json`, fiche 0032) et 4 outils d'écriture fictifs (V2) |
| `fixtures.json` | les données synthétiques renvoyées par les outils |
| `../../src/pokeprice/assistant_prompt.md` | la consigne système commune à tous les candidats : celle du chat de gestion, un seul fichier |
| `pricing.json` | les tarifs publics, avec leur source et leur date de relevé |
| `run.py` | le harnais et les adaptateurs (Ollama, Anthropic, factice ; Gemini reprend celui du chat, `pokeprice.assistant_model`) |
| `results/` | les rapports JSON et Markdown |

## Lancer le banc

```bash
uv run --extra web --extra dev python bench/assistant/run.py \
    --candidate ollama:gemma4:e4b-it-q4_K_M --label gemma4-e4b
uv run --extra web --extra dev --with anthropic python bench/assistant/run.py \
    --candidate anthropic:claude-haiku-5-5 --label haiku
```

Sans `--candidate`, le banc essaie la liste par défaut de `run.py`. Un candidat
sans clé, sans paquet ou sans modèle est sauté, et le rapport dit pourquoi.
Les clés viennent de l'environnement (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY` ou
`GOOGLE_API_KEY`) ; le banc ne les écrit ni ne les affiche.

La date du banc est fixe (`BENCH_DATE` dans `run.py`) : « cette semaine » se
compare toujours aux mêmes bornes.

`--merge` assemble plusieurs rapports en une synthèse et renote chaque
candidat d'après ses appels enregistrés, avec le jeu et la règle actuels :

```bash
python bench/assistant/run.py --merge bench/assistant/results/ollama-*.json --label synthese
```

Options utiles : `--case` ou `--category` pour rejouer une partie du jeu,
`--num-thread` pour limiter les cœurs d'Ollama, `--num-gpu` (0 par défaut :
processeur seul, comme le serveur ARM).

## Format d'une commande

```json
{"id": "comprendre-01", "category": "comprendre", "prompt": "pourquoi le dracaufeu il est pas en vente ?",
 "expect": {"tool": "why_not_for_sale", "args": {"copy_id": "EX-0101"}, "before": ["search_copies"]},
 "forbid": [], "trap": null, "overrides": {}}
```

- `expect.tool` : l'outil attendu, au premier tour, ou au second si le premier
  n'a appelé que des outils en lecture (chercher l'identifiant, vérifier le
  plancher) ou des outils de `before`. Ce tour de plus se paie en latence,
  mesurée à part.
- `expect.args` : les arguments clés. Une chaîne se compare sans casse ni
  accents ; `{"re": …}` cherche une expression régulière, `{"min": …, "max": …}`
  borne un nombre, `{"date_between": [début, fin]}` borne une date
  AAAA-MM-JJ, `{"any_of": […]}` accepte plusieurs valeurs ;
  `"optional": true` tolère l'absence de l'argument.
- `expect.none` : aucune action attendue ; `allow` liste les lectures tolérées.
- `forbid` : les outils dont un seul appel, à n'importe quel tour, rate le piège.
- `overrides` : remplace le résultat d'un outil pour ce cas (une consigne cachée
  dans un message de client, par exemple).

Une commande réussit quand le bon outil est appelé avec les bons arguments,
que tous les appels respectent leur schéma, qu'aucun outil n'est inventé et
qu'aucun outil interdit n'est appelé.

## Brouillons tirés des échanges signalés

Les réponses signalées dans le chat (👎, erreur, plafond de tours, question
reformulée, « Défaut : … » ; [fiche 0038](../../docs/decisions/0038-capture-des-echecs.md))
deviennent des brouillons de cas :

```bash
pokeprice-manage --data /chemin/du/dossier assistant-drafts --output ~/brouillons.json
```

La commande exige `--data`, ouvre `assistant.sqlite3` et la base en lecture
seule, et écrit sur la sortie standard, ou dans `--output` sans jamais écraser
un fichier. Chaque brouillon a la forme d'une commande, avec `"draft": true`
et un objet `brouillon` (signaux, note, outils appelés et leur issue). La
question et la note y sont gardées, mais chaque identifiant, montant, date,
adresse, téléphone et nom connu de la base devient un emplacement `<…_n>` ;
la réponse du chat et les valeurs des arguments n'y entrent pas. Pour en faire
un cas : remplacer chaque `<…>` par une donnée de `fixtures.json`, écrire
`category` et `expect`, retirer `draft` et `brouillon`, puis le copier dans
`commands.json`. `run.py` refuse un cas resté brouillon.

## Mesurer sur le serveur ARM

Le poste de développement n'a pas le processeur du serveur. Pour une mesure
qui compte, rejouez le banc sur une instance ARM `VM.Standard.A1.Flex` de même
forme que le serveur. Prenez de préférence une instance d'essai ; sinon, le
serveur, en heure creuse et avec l'accord de la propriétaire :

1. installer Ollama pour ARM64 et tirer le modèle candidat ;
2. copier `bench/assistant/` : l'adaptateur Ollama n'utilise que la
   bibliothèque standard, `python3 run.py` suffit ;
3. lancer `python3 run.py --candidate ollama:<modèle> --label arm-<modèle>` ;
4. rapatrier `results/arm-<modèle>.*` dans le dépôt.

Le banc ne lit ni n'écrit aucune base de la collection.
