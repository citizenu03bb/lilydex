# Contribuer au projet

> **Pour qui :** toute personne qui veut corriger, améliorer ou documenter Les cartes de Lily.
> **Vous y trouverez :** installer le projet, lancer les tests, écrire la documentation, proposer un changement.

Le projet est tenu par une seule personne. Les issues et les pull requests sont
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

### Recette de la vitrine dans les navigateurs

La recette [Playwright](tests/browser/playwright.config.cjs) s'exécute dans
Firefox et WebKit sous Linux, en français et en anglais, aux largeurs 320,
390 et 1440 pixels. Elle vérifie les filtres, le zoom, les commandes tactiles,
le clavier et la reprise après erreur. Pour la lancer depuis la racine :

```bash
cd tests/browser
npm ci
npx playwright install --with-deps firefox webkit
npm test
```

Conservez `uv` dans votre chemin : Playwright démarre le serveur Python avec
les dépendances web et dev verrouillées. Le serveur écoute uniquement sur
la boucle locale et crée sa collection et ses photos dans un dossier
temporaire supprimé à l'arrêt. Il refuse de réutiliser un serveur existant.
Les requêtes externes et les écritures HTTP sont bloquées et font échouer
la recette si elles sont tentées ; les services Python sont remplacés par
des fonctions de test. Aucun secret ni jeu de données local n'est nécessaire.

Le [workflow CI](.github/workflows/tests.yml) lance un job par moteur sur
chaque pull request et chaque push sur `master`. Les versions npm et les
actions sont verrouillées ; un échec fait échouer le workflow, sans relance
automatique. Un échec dans un moteur n'interrompt pas l'autre.
Les artefacts `storefront-firefox` et `storefront-webkit` conservent les
rapports HTML, JSON et JUnit, les captures et les audits réseau pendant sept
jours. Les échecs ajoutent une capture et une trace Playwright. Localement,
`npm run report` ouvre le rapport HTML ; les résultats sont exclus de Git.

Les petits formats activent le toucher ; WebKit active aussi `isMobile`,
option indisponible dans Firefox. Les touchers simples sont émulés par
Playwright ; les flux de pointeurs supplémentaires restent synthétiques.
Cette recette ne qualifie ni Safari/iOS réel, ni VoiceOver, ni le pincement
et l'inertie du défilement sur un appareil physique.

Le code est dans `src/pokeprice/`, l'interface web dans `src/pokeprice/web/`,
les tests dans `tests/`.

Les textes de la vitrine sont dans `src/pokeprice/web/messages/fr.json`, pas
dans le HTML ni le JavaScript : `{{t:clé}}` dans une page, `t("clé")` dans un
script. Une clé qui finit par `_html` peut contenir du HTML ; les autres sont
du texte ([fiche 0020](docs/decisions/0020-textes-dans-des-dictionnaires.md)).

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
