# Audit des photos d'exemplaires et des identités

Les classeurs importés le 14 octobre 2026 ont révélé deux problèmes liés. D'abord, la découpe
des pages en tiers uniformes coupait les cartes, car le bloc de 9 cartes n'occupe que 83 à 91 %
de la photo. Ensuite, l'identité avait été lue (OCR Gemini) sur ces découpes décalées. Les deux
outils ci-dessous refont ce contrôle sans Gemini. Ils lisent la base en lecture seule et
n'écrivent qu'avec `--apply`, après accord du propriétaire.

## 1. Découpe : `scripts/audit_photo_crops.py`

```bash
uv run --extra web python scripts/audit_photo_crops.py audit outputs/decoupes --album darkrai
uv run --extra web python scripts/audit_photo_crops.py recrop outputs/decoupes/audit.json outputs/decoupes/recrop darkrai:18:7
```

- `audit` repère les cadres jaunes des cartes, ajuste une grille 3×3 régulière et mesure la
  **couverture** : la part de la carte réelle présente dans la photo stockée. Niveaux, calibrés à
  l'œil : grave < 80 %, partielle < 93 %, légère < 97 %, ok. Sorties : `audit.csv` et des planches
  par page (`pages/`), où le cadre est vert si la carte est entière et rouge sinon. Contrôler ces
  planches à l'œil.
- `recrop` découpe la carte ajustée, avec une marge de 10 %, dans la page d'origine
  (`~/Downloads/Pokedex - <album>/`, modifiable avec `--pages-root`). La découpe passe ensuite par
  `normalize_photo` et `prepare_photo`, avec les réglages de l'app. Sans `--apply`, les images vont
  seulement dans le dossier de sortie. Avec `--apply`, chaque exemplaire est patché avec la version
  de l'audit : une fiche modifiée entre-temps est sautée. `--validated` ajoute la preuve
  `photo-preparation` (libellé « validation humaine ») : à réserver au cas où le propriétaire a
  validé les planches avant/après.

## 2. Identité : `scripts/audit_photo_identity.py`

Une identité lue sur une photo dépend de son découpage. Après un redécoupage ou une nouvelle photo,
nom, numéro et PV sont à revérifier. L'entrée est un CSV ou JSON d'exemplaires (colonne `copy_id`
ou `id`, éventuellement `niveau`/`level`), par exemple `audit.csv`.

| Étape | Commande | Rôle |
|---|---|---|
| Planches | `sheets <copies> <dossier> --level grave` | carte entière, zoom sur le numéro et l'extension, identité enregistrée en légende |
| Bandeaux | `strips <copies> <dossier>` | bandeau nom/PV et bandeau numéro seulement : revue rapide de centaines de fiches |
| Catalogue | `lookup pl3-97 dp5-57` | nom à ce numéro, d'après les listes d'extensions TCGdex en cache (`catalog_lookups`), sans réseau |
| Image | `score <copies> scores.json` (`--extra vision`) | DINOv2 : score et rang de la référence enregistrée dans la galerie locale, test à 180°, part de bleu (dos visible) |
| Propositions | `propose decisions.csv propositions.json` | patchs à partir des décisions relues |
| Application | `apply propositions.json` puis `--apply` | essai sur copie temporaire, puis sauvegarde et écriture |

Méthode qui a fonctionné le 16 octobre (680 photos, 140 corrections, 22 cartes à retourner) :

1. Relire toutes les planches et noter, pour chaque écart, le nom, le PV et le numéro visibles.
   Zoomer quand le numéro est douteux.
2. Vérifier chaque lecture avec `lookup` : le numéro lu doit donner le nom lu. Une lecture fausse
   ne tombe presque jamais sur le bon nom.
3. Classer avec `score`. La référence attendue doit arriver en tête. Les écarts restants viennent
   surtout d'illustrations identiques (énergies de base, kits Dresseur, réimpressions) ou de
   reflets de pochette. Ce classement n'est qu'un recoupement : il ne remplace pas la lecture.
4. Écrire `decisions.csv` avec les colonnes `copy_id`, puis `catalog_id`, ou `name` et `language`
   seuls, puis `observation` et `note`. Lancer ensuite `propose`, puis `apply` sans `--apply`.

Règles des propositions :

- Le statut devient `review` (« À vérifier »). Proposer une référence ne la confirme pas : seul
  le propriétaire confirme. Une correction d'identité retire le prix de référence.
- Les patchs n'ont pas d'`evidence`, dont le libellé affirmerait une confirmation humaine. La
  provenance est dans le motif.
- Les cartes face cachée ou tête en bas sont signalées à part et ne sont pas patchées : la
  correction se fait dans le classeur, puis on rephotographie.
- La langue se lit carte par carte : beaucoup d'énergies anglaises étaient enregistrées sous un nom
  français.

## Pièges constatés

- La correspondance `exact` de l'import ne prouve rien. Gemini a lu des numéros qui existent au
  catalogue sans être ceux de la carte : Ouisticram enregistré 57/100 au lieu de 97/147, Obalie
  46/160 au lieu de 24/106, Terhal 92/168 au lieu de 83/145.
- « À identifier » correspond souvent à une carte face cachée (dos bleu).
- Certaines pochettes contiennent plusieurs cartes. La carte de derrière peut fausser une lecture.
