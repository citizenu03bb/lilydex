# Instantané initial de la collection

> **Pour qui :** toute personne qui doit retrouver les fichiers d'origine de la collection (photos des pages de classeurs, rapports de numérisation, corrections).
> **Vous y trouverez :** ce que contient l'instantané, où il est conservé, comment le vérifier, le restaurer et régénérer la bibliothèque sans réseau.
> **Statut :** rapport daté. L'instantané a été pris le 4 octobre 2026, avant la création de l'application de gestion ; il ne bouge plus. La collection gérée se sauvegarde chaque nuit : voir [Sauvegardes](DAILY-BACKUPS.md).

## Ce que contient l'instantané

**368 fichiers, dont les 80 photos originales** des trois premiers classeurs,
les CSV, checkpoints, corrections, exports et sources du projet de l'époque.
L'archive pèse 590 050 645 octets, environ 590 Mo.

L'archive quotidienne de la collection gérée ne contient pas ces 80 grandes
photos de pages de classeurs : elles ne sont que dans l'instantané.

Trois fichiers vont ensemble : `collection.tar.gz`, `manifest.json` et
`SHA256SUMS`. Le manifeste donne le chemin d'origine, la taille et l'empreinte
SHA-256 de chaque fichier, ainsi que le commit et l'état des modifications Git
au moment de la capture ; l'archive contient aussi son manifeste.

Ne sont pas inclus : les dépendances Python, les modèles d'IA, les dossiers Git
et les fichiers `.env*`, `.pem` et `.key`. Les sources et le verrou `uv.lock`
sont inclus. Les identifiants de services se reconfigurent à part.

## Où il est conservé

- **Sur le portable**, dans `outputs/snapshots/20261004T170658Z/`, hors du
  dépôt public.
- **Sur Google Drive**, dans le dossier privé des sauvegardes. Le connecteur
  Drive utilisé alors limitait chaque transfert à 100 Mio : `collection.tar.gz`
  y est découpé en sept parties de 90 Mio au plus, qui reconstituent exactement
  l'archive, avec `SHA256SUMS.parts`, `parts.json`, le manifeste initial et
  `RESTAURER.txt`. Tailles, dossier parent et permissions des fichiers Drive
  ont été relus : seul le propriétaire du compte y a accès.
- Les artefacts installables et les sources de la livraison de l'application
  sont aussi sur Drive. Pour reconstruire l'application de gestion, partez du
  dépôt Git (ou d'une wheel récente), pas du code de l'instantané, antérieur à
  l'application.

Les sommes de contrôle détectent une altération ; elles ne chiffrent pas les
photos.

## Vérifier et restaurer

Depuis la racine du projet, avec Python 3.12 ou plus récent, sans l'option `-O` :

```bash
python scripts/freeze_collection.py verify outputs/snapshots/20261004T170658Z
python scripts/freeze_collection.py restore outputs/snapshots/20261004T170658Z /tmp/collection-restauree
```

La destination doit être inexistante. La restauration vérifie l'archive avant
l'extraction, puis chaque fichier extrait. Elle crée `project/`, `photos/` et
`snapshot-manifest.json`, sans toucher aux dossiers d'origine.

`freeze_collection.py` fait partie de l'instantané : depuis une simple copie
du dossier, on retrouve le script en extrayant
`project/scripts/freeze_collection.py` avec un outil d'archivage.

Depuis Drive : téléchargez les sept parties, contrôlez-les avec
`SHA256SUMS.parts`, concaténez-les dans l'ordre, puis contrôlez l'archive
reconstituée avec `SHA256SUMS` avant de la restaurer comme ci-dessus.
`RESTAURER.txt`, rangé avec les parties, accompagne cette restauration.

## Régénérer la bibliothèque sans réseau

Ce contrôle utilise les modules du **projet restauré**, bloque le réseau et
régénère la bibliothèque avec les photos restaurées :

```bash
# L'environnement Python doit contenir les dépendances du projet.
uv run python scripts/verify_collection_snapshot.py /tmp/collection-restauree /tmp/controle-restauration
```

Le dossier de résultat doit lui aussi être inexistant. Les assertions du script
attendent les comptes et corrections de cet instantané. Le script a été ajouté
après la capture : il est dans le projet courant, pas dans l'instantané. Sans
lui, adaptez les chemins du manifeste vers `project/` et `photos/<album-id>/`,
puis utilisez la commande `library` du projet restauré.

## Les vérifications faites

**Restauration et régénération locales** (Python 3.13.2) :

| Contrôle | Résultat |
| --- | ---: |
| Fichiers restaurés et vérifiés | 368 |
| Exemplaires / éditions identifiées | 401 / 347 |
| Identités confirmées / non résolues | 400 / 1 |
| Identités confirmées sans prix | 22 |
| Vignettes intégrées identiques | 401 |
| Comptes Diamond & Pearl / Platinium / Platinium 3×3 | 111 / 110 / 180 |
| Pochettes exclues au verso / photos exclues du scan | 3 / 2 |

Les photos des entrées exclues sont conservées. Les CSV et données JSON
régénérés sont identiques, hormis les chemins des rapports déplacés par la
restauration. Octillery 58/127, Kirlia 51/127, Capidextre 35/100, Fossile Crâne
120/127 et PokéNav 81/106 sont contrôlés explicitement. Le résultat comprend
aussi un échantillon de 20 exemplaires et leurs photos, utilisé pour
l'[évaluation des logiciels existants](EVALUATION.md).

**Restauration depuis Drive**, le 12 octobre 2026, avec le remote rclone
`gdrive` : les sept parties téléchargées passent `SHA256SUMS.parts`, l'archive
reconstituée passe `SHA256SUMS`, `freeze_collection.py verify` et `restore`
contrôlent 368 fichiers, et la régénération sans réseau redonne le tableau
ci-dessus (401 vignettes identiques).

Les preuves de ces deux contrôles (`validation.json`,
`validation-drive-2026-10-12.json`) sont conservées hors du dépôt public, dans
`outputs/evaluation/step0/recovery-check/`.

## Faire un nouvel instantané

`python scripts/freeze_collection.py create` produit un nouveau dossier daté et
vérifie son contenu. Les instantanés et les installations d'évaluation en sont
exclus, pour ne pas les archiver à nouveau. Un nouvel instantané ne remplace pas
celui-ci.
