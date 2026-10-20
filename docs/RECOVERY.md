# Instantané et restauration de la collection

État vérifié le 4 octobre 2026, avant l'évaluation des applications.

L'instantané contient **368 fichiers, dont les 80 photos originales** des trois
albums, les CSV, checkpoints, corrections, exports et sources du projet.
L'archive mesure 590 050 645 octets, soit environ 590 Mo.

Emplacement : `outputs/snapshots/20261004T170658Z/` (hors du dépôt public).
Conserver ensemble `collection.tar.gz`, `manifest.json` et `SHA256SUMS`.
Le manifeste détaille les chemins d'origine, tailles et SHA-256 des fichiers,
ainsi que le commit et l'état des modifications Git au moment de la capture.
L'archive contient également son manifeste.

**Copie externe réalisée le 5 octobre 2026** dans le dossier privé
Snapshot initial — 4 octobre 2026 (dossier Drive privé),
sous Poképrice — sauvegardes (dossier Drive privé).
Le transfert est limité à 100 Mio par fichier : les sept parties de
`collection.tar.gz` reproduisent localement le SHA-256 initial après concaténation.
Les manifestes, sommes de contrôle et `RESTAURER.txt` sont également copiés.
Tailles, dossier parent et permissions ont été relus pour les fichiers Drive :
seul le propriétaire a accès.

**Restauration depuis Drive vérifiée le 12 octobre 2026** avec le remote rclone
`gdrive` : les sept parties téléchargées passent `SHA256SUMS.parts`, l'archive
reconstituée passe `SHA256SUMS`, `freeze_collection.py verify` et `restore`
contrôlent 368 fichiers, et la régénération sans réseau donne les mêmes résultats
que le tableau ci-dessous (401 vignettes identiques). Preuve :
`outputs/evaluation/step0/recovery-check/validation-drive-2026-10-12.json`.
Les sommes de contrôle détectent une altération ; elles ne chiffrent pas les photos.
Voir [DAILY-BACKUPS.md](DAILY-BACKUPS.md) pour la collection gérée et l'application récente.

## Vérification et restauration

Depuis la racine du projet, avec Python 3.12 ou supérieur, sans l'option `-O` :

```bash
python scripts/freeze_collection.py verify outputs/snapshots/20261004T170658Z
python scripts/freeze_collection.py restore outputs/snapshots/20261004T170658Z /tmp/pokeprice-restored
```

La destination doit être inexistante. La restauration vérifie l'archive avant
extraction, puis chaque fichier extrait. Elle crée `project/`, `photos/` et
`snapshot-manifest.json` ; elle ne remplace pas les dossiers d'origine.

Le script `freeze_collection.py` fait partie de l'instantané. Une copie externe
du dossier de sauvegarde permet donc de retrouver ce script en extrayant
`project/scripts/freeze_collection.py` de l'archive avec un outil d'archivage.
Les dépendances Python, modèles IA, dossiers Git et fichiers `.env*`, `.pem` et
`.key` ne sont pas inclus. Les sources et le verrou `uv.lock` sont inclus ; les
identifiants de services devront être reconfigurés séparément si nécessaire.

## Régénération vérifiée sans réseau

Le contrôle suivant utilise les modules du **projet restauré**, bloque les
sockets réseau et régénère la bibliothèque avec les photos restaurées :

```bash
# L'environnement Python doit contenir les dépendances du projet.
.venv/bin/python scripts/verify_collection_snapshot.py /tmp/pokeprice-restored /tmp/pokeprice-recovery-check
```

Le dossier de résultat doit lui aussi être inexistant. Ce contrôle est lié à
l'instantané actuel : ses assertions attendent les comptes et corrections
validés ci-dessous. Le script de contrôle a été ajouté après la capture ; il se
trouve dans le projet courant. Pour une régénération ultérieure sans ce script,
adapter les chemins du manifeste vers `project/` et `photos/<album-id>/`, puis
utiliser la commande `library` du projet restauré.

Résultat de l'exercice déjà effectué :

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
restauration. Octillery 58/127, Kirlia 51/127, Capidextre 35/100,
Fossile Crâne 120/127 et PokéNav 81/106 sont contrôlés explicitement.

Preuve : validation.json (`outputs/evaluation/step0/recovery-check/validation.json`, hors du dépôt public).
La restauration et la régénération ont été exécutées avec Python 3.13.2.
Le résultat comprend aussi un échantillon de 20 exemplaires et leurs photos,
utilisé pour l'[évaluation](EVALUATION.md).

Pour une prochaine capture, `python scripts/freeze_collection.py create`
produit un nouveau dossier daté et vérifie son contenu. Les snapshots et les
installations d'évaluation sont exclus pour éviter de les archiver à nouveau.
Un nouvel instantané ne remplace pas celui-ci.
