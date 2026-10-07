# pokeprice 🃏⚡

**pokeprice** est un pipeline complet d'automatisation pour numériser, identifier et estimer la valeur marchande d'albums et classeurs de cartes Pokémon, propulsé par la vision multimodale locale **Gemma 4 E4B** (via Ollama) et l'API **TCGdex** (avec cotations **Cardmarket en €** et **TCGplayer en $**).

---

## ✨ Fonctionnalités

* 🤖 **Vision locale par défaut** : Ollama (`gemma4:e4b-it-q4_K_M`) analyse les photos localement. L'identification et les prix utilisent l'API publique TCGdex. Gemini est disponible uniquement avec `--backend gemini` : ce choix envoie les photos au service cloud et peut être facturé.
* 🇫🇷 **Support Natif des Cartes Françaises** : Reconnaissance des noms français (*Tic, Gruikui, Kapoera, Ortide, Férosinge, Goupix, etc.*) et extensions officielles françaises.
* 💶 **Cotations Cardmarket (EUR)** : Récupération des prix de tendance (`trend`), prix moyen (`avg`), prix minimum (`low`) et surcote holographique (`trend-holo`).
* 📐 **Auto-Découpe Intelligente (Grid Slicer)** :
  * Détection automatique de l'orientation portrait/paysage.
  * Découpe automatique des pages 9 pochettes (**3×3**) ou mini-albums 4 pochettes (**2×2**).
  * Marge intérieure paramétrable (`--inset`) pour éliminer les coutures et reflets plastiques des pochettes.
* 🔍 **Identification avec vérification** : Recherche exacte en français puis en anglais, comparaison de la référence complète et des PV. Les corrections de nom ou de numéro restent des propositions à vérifier. Une référence ambiguë ne reçoit pas de valeur confirmée.
* 📊 **Rapports Complets** : CSV, Excel avec filtres et en-têtes fixes, HTML avec comparaison photo/référence, et résumé terminal. Les valeurs inconnues restent vides. Les cartes au verso ou illisibles sont conservées.
* 💾 **Reprise des scans** : Un checkpoint est sauvegardé après chaque pochette. Les échecs OCR sont réessayés et restent visibles dans les résultats partiels.

---

## 🚀 Installation Rapide

Ce projet utilise [uv](https://docs.astral.sh/uv/) pour la gestion ultra-rapide des dépendances Python :

```bash
cd ~/Projects/pokeprice
uv sync --extra dev
```

### Prérequis Modèle Local (Ollama)

Assurez-vous qu'Ollama est actif et dispose du modèle multimodal Gemma 4 E4B :
```bash
ollama run gemma4:e4b-it-q4_K_M
```

---

## 📖 Utilisation

### 1. Scanner une Page ou un Dossier Complet de Photos

```bash
# Scanner une seule page d'album (découpe automatique 3x3 ou 2x2)
uv run ./pokeprice.py scan ./photos/page_01.jpg -o resultat.csv

# Scanner un dossier entier de 80 photos de classeur vers Excel
uv run ./pokeprice.py scan ./photos_album/ --grid 3x3 -o collection.xlsx

# Sauvegarder les images découpées de chaque carte pour vérification visuelle
uv run ./pokeprice.py scan ./photos/page_01.jpg --save-crops ./decoupes_cartes/
```

#### Options de `scan` :
* `--grid [auto|3x3|2x2|4x3|3x4|single]` : Disposition des pochettes, toujours **lignes × colonnes** (défaut: `auto`).
* `--rotate [auto|0|90|180|270]` : Force une rotation si les photos sont penchées (défaut: `auto`).
* `--output, -o <fichier>` : Nom du fichier de sortie (`.csv` ou `.xlsx`).
* `--save-crops <dossier>` : Sauvegarde les vignettes individuelles des cartes.
* `--inset <float>` : Marge de rognage intérieur des cases (défaut: `0.02` = 2%).
* `--backend [ollama|gemini]` : Permet de basculer sur l'API cloud Gemini Flash si besoin.
* `--condition [NM|EX|GD|LP|PL|PO|NM/EX]` : Force le grade physique de toutes les cartes. Sans cette option, le grade OCR est utilisé ; un grade inconnu reste à vérifier. `NM/EX` utilise la décote EX.
* `--retries <0..5>` : Nombre de réessais OCR après échec (défaut : 2).
* `--resume` : Reprend le fichier `.checkpoint.json` associé au même chemin de sortie. Les images et paramètres doivent être identiques. Les pochettes en échec sont réessayées.
* `--corrections <fichier.json>` : Applique les références corrigées par fichier et position, tout en conservant la lecture OCR initiale. Les champs optionnels `card_name` et `card_id` permettent de confirmer un nom et une édition ; `card_hp` conserve séparément les PV revérifiés sur la photo ; `card_language` (`fr` ou `en`) précise la langue de la référence explicite ; le numéro, le nom et les PV sont contrôlés pour une édition explicite. Exemple de fichier : `[{"image_file":"page.jpg","position":4,"card_number":"58/127","source":"Vérification manuelle"}]`.

```bash
uv run ./pokeprice.py scan ./photos_album/ -o collection.xlsx --resume
uv run ./pokeprice.py html collection.csv ./photos_album/ -o collection.html
```

Les rapports distinguent les correspondances exactes (`confirmed`), les propositions (`review`), les identités non résolues (`unresolved`) et les échecs (`failed`). Le HTML affiche par défaut les **prix de référence TCGdex** et leur somme pour les identités confirmées. Le tri et le filtre « Référence > 10 € » utilisent ces références. Les états estimés par l’IA ou fournis par l’utilisateur restent **à confirmer**.

La case **« Afficher une simulation selon l’état »**, désactivée par défaut, révèle les montants simulés, le total, les coefficients et les exclusions. Ces coefficients (NM × 1, EX × 0,85, GD × 0,70, LP × 0,55, PL × 0,40, PO × 0,15) sont des hypothèses sans calibration sur des ventes comparables. Le prix de référence n’est pas une cote NM garantie. Seules les identités confirmées avec prix, grade connu et sans incohérence entrent dans la simulation. Une incohérence de reflet ou de PV demande une vérification ; elle ne prouve pas une contrefaçon.

Les exports utilisent `Prix_Reference_EUR`, `Prix_Simule_EUR`, `Coefficient_Simulation_Etat`, `Hypothese_Decote_Etat`, `Source_Etat` et `Etat_A_Confirmer`. Les colonnes de simulation sont masquées par défaut dans Excel et peuvent être affichées manuellement. Les anciennes colonnes `Prix_Estime_EUR`, `Prix_Catalogue_EUR`, `Prix_Ajuste_EUR` et `Decote_Etat` restent acceptées à la lecture et sont migrées lors de la régénération.

Les nouveaux scans conservent la géométrie de découpe, le modèle OCR, la réponse brute, l'identifiant TCGdex, la langue et la date de mise à jour du prix. Les photos réelles sont intégrées au HTML ; les illustrations officielles nécessitent une connexion Internet. Les anciens exports sans géométrie peuvent être régénérés avec `html --grid ... --rotate ... --inset ...`.

---

### 2. Recherche Directe d'une Carte (Lookup)

Vérifiez instantanément la cote et l'extension d'une carte spécifique en ligne de commande :

```bash
# Recherche simple
uv run ./pokeprice.py lookup "Darkrai" "4/106" --holo

# Sortie :
# Nom officiel       : Darkrai
# Extension          : Duels au Sommets
# Numéro / Rareté    : 4/106 (Rare Holo)
# Tendance Cardmarket: 13.68 €
# Tendance Holo / Rev: 9.07 €
# TCGplayer Market   : $39.94
# Lien Cardmarket    : https://www.cardmarket.com/fr/Pokemon/Products/Singles/277905
```

---

### 3. Afficher le Résumé d'un Rapport Existant

```bash
uv run ./pokeprice.py report resultat.csv
```

---

## 📸 Conseils pour Photographier Vos Albums

> [!WARNING]
> **Cartes empilées dans les pochettes :**
> Dans beaucoup d'albums d'enfance, plusieurs cartes communes ou doublons sont glissées derrière la carte visible. Pensez à vérifier l'épaisseur des pochettes pour ne pas manquer de cartes.

1. **Éclairage Indirect :** Prenez les photos sous une lumière naturelle ou oblique pour éviter le reflet blanc des ampoules sur le film plastique.
2. **Cadrage :** Cadrez la page complète de face en laissant un léger bord noir autour de la page.
3. **Orientation :** L'auto-rotation remet automatiquement les photos en mode portrait.

---

## 🧪 Tests Unitaires

Exécutez la suite de tests avec pytest :

```bash
uv run pytest
uv run python -m pytest
```

Les tests utilisent des réponses simulées et ne nécessitent ni accès réseau ni modèle IA.

## Bibliothèque globale

`pokeprice library pokeprice_library_manifest.json -o pokeprice_library` regroupe les rapports existants sans relancer l’OCR ni rechercher de nouveaux prix. Le manifeste associe chaque album à son CSV et à son dossier de photos ; les chemins relatifs sont résolus à partir du manifeste.

Le HTML permet une recherche par nom (avec ou sans accents), extension, numéro ou album. Le résultat donne le nombre d’exemplaires et le nombre d’éditions identifiées. Chaque édition se déplie pour afficher les photos, les variantes Foil, l’état estimé et l’emplacement précis de chaque exemplaire. Un filtre limite la recherche à un album ; le tri par quantité fait ressortir les doublons.

Les exemplaires d’une même édition sont regroupés par identifiant TCGdex et langue. Les cartes japonaises confirmées manuellement utilisent leur nom, extension et référence. Les identités non confirmées restent des entrées séparées. Chaque pochette est conservée : une carte répétée dans deux albums compte deux fois. Le CSV consolide les exemplaires avec leurs sources ; le JSON conserve les groupes et les quantités.

La bibliothèque est un export : régénérer avec la même commande après toute correction d’album. Les rapports individuels et les photos restent les sources de référence.

## Roadmap de l'application de gestion

La [roadmap](docs/ROADMAP.md) décrit l'évaluation des applications existantes,
la migration de la collection, la gestion des exemplaires et des ventes, puis
le déploiement avec sauvegardes. Elle retient SQLite comme hypothèse de départ
pour une application légère et prévoit un choix après les essais de migration.

L'[instantané du 4 octobre 2026 et sa restauration](docs/RECOVERY.md) préservent
les 401 exemplaires, les corrections et les 80 photos originales. Une copie
hors de cet appareil reste à réaliser. L'[évaluation des applications](docs/EVALUATION.md)
consigne les essais de Bindarr et PokéCollect, l'examen de PokéCollector et la
recommandation d'une gestion légère autour de pokeprice avec SQLite.

## Application privée de gestion

La première application FastAPI/SQLite ajoute des exemplaires durables,
corrections avec historique, photos privées, comptes et suivi des lots et ventes.
Les 401 cartes ont été importées sans modifier les sources des albums.

```bash
uv sync --extra web --extra dev
uv run --extra web pokeprice-manage serve
```

Ouvrir [http://127.0.0.1:3820](http://127.0.0.1:3820), puis créer son accès privé
au premier démarrage. Pour une installation neuve, importer d'abord avec
`uv run --extra web pokeprice-manage import pokeprice_library_manifest.json`.

La [documentation de l'application](docs/APP.md) décrit les imports, exports et
sauvegardes. Utiliser ses exports pour les corrections faites dans la gestion.
La [préparation du déploiement](docs/DEPLOYMENT.md) prévoit HTTPS et sauvegardes,
avec serveur, domaine et budget à valider. Le
[skill dédié](skills/pokeprice-collection/SKILL.md) conserve les workflows du projet.
