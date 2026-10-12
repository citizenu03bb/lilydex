# pokeprice

Numériser, identifier, estimer et vendre une collection de cartes Pokémon.

Le projet a deux parties qui partagent les mêmes données :

- **un pipeline d'albums en ligne de commande** (`pokeprice`) : il découpe les
  photos de pages de classeur, lit chaque carte (Gemma 4 en local via Ollama, ou
  Gemini) et la rapproche du catalogue [TCGdex](https://tcgdex.dev), avec les
  cotations Cardmarket (€) et TCGplayer ($) ;
- **une application privée de gestion** (`pokeprice-manage`, FastAPI + SQLite),
  utilisable sur ordinateur et Android : exemplaires, photos, corrections
  versionnées, variantes, prix, lots et ventes, sauvegardes vérifiées.

Où en est le projet et où il va : [roadmap du MVP](docs/ROADMAP.md).

## Démarrage

```bash
uv sync --extra web --extra dev
uv run --extra web pokeprice-manage serve
```

Ouvrir <http://127.0.0.1:3820> et créer le compte administrateur au premier
démarrage. Pour une installation neuve, importer d'abord les albums scannés :

```bash
uv run --extra web pokeprice-manage import pokeprice_library_manifest.json
```

Accès depuis le téléphone sur le Wi-Fi : `pokeprice-manage serve --host <adresse-wifi>`.
Les données (base, photos, sauvegardes) vivent dans `data/`, hors de git.
La lecture des cartes dans l'application utilise Gemini : une clé
`GEMINI_API_KEY` ou `GOOGLE_API_KEY` dans `~/.env`, jamais envoyée au navigateur.
Détails : [APP.md](docs/APP.md).

## Parcours principaux

**Numériser un classeur.** Photographier chaque page, puis :

```bash
uv run ./pokeprice.py scan ./photos_album/ --grid 3x3 -o album.csv
```

Ajouter l'album au manifeste et l'importer. Un réimport n'ajoute aucun doublon
et n'écrase aucune correction faite dans l'application.

**Saisir des cartes une à une ou en série** (Collection → Ajouter une carte, ou
Saisie en série) : photo, lecture Gemini, choix de l'édition, recto et verso.
Sur ordinateur, la caméra affiche une mire de cadrage ; un téléphone peut servir
de webcam (montage `scrcpy` et `v4l2loopback` décrit dans [APP.md](docs/APP.md)).
Les photos sont recadrées, redressées et équilibrées sur le serveur ; l'original
est toujours conservé.

**Vérifier la variante.** Une carte est **Standard** si elle est telle
qu'imprimée d'origine, Rare Holo comprise, et **Foil** si elle brille davantage :
reverse (fond holographique hors illustration) ou illustration holo sur une
carte normalement mate. Le symbole de rareté ne suffit pas à trancher ; la fiche
indique la version standard selon TCGdex. Un **tampon** imprimé sur l'illustration
(promo, par exemple « EX Fantômes Holon ») se saisit dans son propre champ.

**Relever le prix et estimer la vente.** Dans la fiche ou sur une sélection :

- **Relever le prix (TCGdex)** enregistre un relevé daté (prix bas, moyennes,
  tendance) ; la tendance devient la référence, avec des alertes à partir de 2 €
  (variante douteuse, marché instable, peu d'offres) ;
- **Voir les offres Cardmarket** ouvre la page filtrée sur la langue, l'état et
  la variante ;
- **Estimer le prix de vente** : coller les offres copiées depuis cette page ;
  le prix de marché est la médiane des offres au même état.

Le prix de référence est une tendance, pas un prix de vente.

**Vendre.** Sélectionner des exemplaires, créer un lot, préparer l'annonce
(dossier ZIP avec photos), puis suivre réservation, vente, frais et retours.

**Sauvegarder.** Sauvegarde locale quotidienne restaurée et vérifiée, copie
privée sur Google Drive : [DAILY-BACKUPS.md](docs/DAILY-BACKUPS.md). Avant toute
opération de masse : `uv run --extra web pokeprice-manage backup`.

## Ligne de commande

| Commande | Usage |
|---|---|
| `pokeprice scan <photo ou dossier>` | Découpe (`--grid auto\|3x3\|2x2\|…`), lecture (`--backend ollama\|gemini`), rapprochement ; reprise avec `--resume`, corrections avec `--corrections fichier.json` |
| `pokeprice lookup "Nom" "4/106" [--holo] [--pv 80]` | Cote d'une carte (nom français) |
| `pokeprice report album.csv` | Résumé d'un rapport |
| `pokeprice html album.csv photos/ -o album.html` | Rapport HTML autonome, photo réelle et officielle côte à côte |
| `pokeprice library manifeste.json -o bibliotheque` | Bibliothèque HTML consolidée des albums d'origine |
| `pokeprice-manage serve \| import \| status \| export \| backup \| restore \| user` | Application de gestion : voir [APP.md](docs/APP.md) |

Le pipeline d'albums lit en local par défaut (Ollama, modèle
`gemma4:e4b-it-q4_K_M`). `--backend gemini` envoie les photos au service cloud,
qui peut être facturé. Les corrections d'albums d'origine passent par
`--corrections` ; celles faites dans l'application vivent dans la base, et
s'exportent avec `pokeprice-manage export`.

## Développement

```bash
uv run --extra web --extra dev pytest
```

Les tests n'utilisent ni réseau ni modèle IA. Les scripts JavaScript de
l'interface sont aussi testés via Node. Code : `src/pokeprice/`, interface :
`src/pokeprice/web/`, tests : `tests/`.

Le [banc d'essai de reconnaissance](scripts/bench_recognition.py) compare Gemini,
Tesseract, la recherche d'images (DINOv2, CLIP) et des agents Claude sur des
cartes vérifiées. Ses résultats guident la roadmap.

## Documentation

| Document | Contenu |
|---|---|
| [ROADMAP.md](docs/ROADMAP.md) | MVP : critères de sortie, jalons, décisions, risques |
| [APP.md](docs/APP.md) | Application de gestion : saisie, photos, variantes, prix, lots, imports et exports |
| [CONDITION-ASSESSMENT.md](docs/CONDITION-ASSESSMENT.md) | Verso et aide à l'évaluation de l'état |
| [DAILY-BACKUPS.md](docs/DAILY-BACKUPS.md), [RECOVERY.md](docs/RECOVERY.md) | Sauvegardes et restauration |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md), [TUNNEL.md](docs/TUNNEL.md) | Déploiement préparé et tunnel de développement |
| [EVALUATION.md](docs/EVALUATION.md) | Évaluation des logiciels existants (octobre 2026) |
| [archive/](docs/archive/) | Roadmap et journal du 5 octobre 2026 |
