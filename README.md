# pokeprice 🃏⚡

**pokeprice** est un pipeline complet d'automatisation pour numériser, identifier et estimer la valeur marchande d'albums et classeurs de cartes Pokémon, propulsé par la vision multimodale locale **Gemma 4 E4B** (via Ollama) et l'API **TCGdex** (avec cotations **Cardmarket en €** et **TCGplayer en $**).

---

## ✨ Fonctionnalités

* 🤖 **100% Local & Gratuit** : Fonctionne directement sur votre GPU via Ollama (`gemma4:e4b-it-q4_K_M`), sans aucun coût d'API cloud.
* 🇫🇷 **Support Natif des Cartes Françaises** : Reconnaissance des noms français (*Tic, Gruikui, Kapoera, Ortide, Férosinge, Goupix, etc.*) et extensions officielles françaises.
* 💶 **Cotations Cardmarket (EUR)** : Récupération des prix de tendance (`trend`), prix moyen (`avg`), prix minimum (`low`) et surcote holographique (`trend-holo`).
* 📐 **Auto-Découpe Intelligente (Grid Slicer)** :
  * Détection automatique de l'orientation portrait/paysage.
  * Découpe automatique des pages 9 pochettes (**3×3**) ou mini-albums 4 pochettes (**2×2**).
  * Marge intérieure paramétrable (`--inset`) pour éliminer les coutures et reflets plastiques des pochettes.
* 🔍 **Fuzzy Matching & Auto-Snap** : Correction automatique du bruit OCR (ex. si le numéro *15/114* est lu *12/114*, le pipeline recalcule automatiquement le bon ID dans l'extension *Noir & Blanc*).
* 📊 **Rapports Complets** : Export en CSV, Excel (`.xlsx` stylisé), et résumé terminal avec classement des cartes les plus chères.

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
* `--grid [auto|3x3|2x2|single]` : Spécifie la disposition des pochettes (défaut: `auto`).
* `--rotate [auto|0|90|180|270]` : Force une rotation si les photos sont penchées (défaut: `auto`).
* `--output, -o <fichier>` : Nom du fichier de sortie (`.csv` ou `.xlsx`).
* `--save-crops <dossier>` : Sauvegarde les vignettes individuelles des cartes.
* `--inset <float>` : Marge de rognage intérieur des cases (défaut: `0.02` = 2%).
* `--backend [ollama|gemini]` : Permet de basculer sur l'API cloud Gemini Flash si besoin.

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
```
