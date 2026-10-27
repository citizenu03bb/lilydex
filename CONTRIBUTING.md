# Contribuer à Lilydex

> **Pour qui :** toute personne qui veut corriger, améliorer ou documenter Lilydex.
> **Vous y trouverez :** installer le projet, lancer les tests, écrire la documentation, proposer un changement.

Lilydex est tenu par une seule personne. Les issues et les pull requests sont
bienvenues ; la réponse peut prendre quelques jours.

## Installer et lancer les tests

Il vous faut Python 3.11 ou plus récent, [uv](https://docs.astral.sh/uv/) et
Node.js (pour les tests des scripts de l'interface).

```bash
uv sync --extra web --extra dev
uv run --extra web --extra dev pytest
```

Ajoutez `--extra vision` pour installer torch et lancer aussi les tests du
contrôle par l'image ; sans cette option, ils sont ignorés.

Les tests n'appellent aucun service : Gemini, DINOv2 et TCGdex y sont remplacés
par des imitations. Ils ne lisent pas vos clés d'API. N'écrivez jamais un test
qui touche une vraie collection : utilisez un dossier temporaire (`tmp_path`).

Le code est dans `src/pokeprice/`, l'interface web dans `src/pokeprice/web/`,
les tests dans `tests/`.

## Proposer un changement

1. Une branche par sujet, des commits courts au format
   `type(portée): résumé` en français (`fix(web): …`, `docs: …`).
2. La suite de tests passe, y compris le contrôle de la documentation.
3. Une modification de la base de données passe par une migration et se teste
   sur une copie restaurée d'une sauvegarde.
4. Un changement visible met à jour la page de documentation concernée **dans
   le même commit**.

## Écrire la documentation

La documentation est en français, au vouvoiement dans les guides, au présent.
Le [glossaire](docs/GLOSSAIRE.md) fixe le vocabulaire.

- **Pas de date dans une page qui décrit le fonctionnement.** Ce qui s'est
  passé va dans le [journal](docs/JOURNAL.md), ce qui a été décidé dans une
  [fiche de décision](docs/decisions/README.md). Seule exception : une ligne
  « Conditions de mesure » sous un chiffre mesuré.
- **Pas de compteur qui vieillit** (nombre de tests, version du schéma, taille
  de la collection) : décrivez la règle stable.
- **Pas de lien vers `outputs/` ou `data/`** : git les ignore, le lien serait
  mort sur GitHub. Une preuve privée se dit privée.
- **Rien de personnel** : ni nom, ni e-mail, ni adresse IP, ni identifiant de
  dossier Drive.
- Une mesure donne son échantillon. On cite le chiffre le plus prudent.

`scripts/check_docs.py` vérifie les liens, les dates des pages réécrites
(liste `PAGES_VIVANTES`) et une liste privée de motifs interdits, lue hors du
dépôt. Il tourne avec la suite de tests ; vous pouvez aussi le lancer seul :

```bash
python scripts/check_docs.py
```

## Signaler une faille

Pas d'issue publique : suivez [SECURITY.md](SECURITY.md).
