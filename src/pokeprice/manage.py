"""Local management commands, separate from OCR and its service credentials."""

import argparse
import json
from pathlib import Path

from .inventory import Store


def main():
    parser = argparse.ArgumentParser(
        description="Gestion privée de la collection Pokémon"
    )
    parser.add_argument(
        "--data", default="data/inventory", help="Dossier persistant de base et photos"
    )
    actions = parser.add_subparsers(dest="action", required=True)
    importer = actions.add_parser(
        "import", help="Import conservateur, sans écraser les modifications"
    )
    importer.add_argument("manifest")
    actions.add_parser("status", help="Comptes et rapprochement de la collection")
    actions.add_parser(
        "reference-audit",
        help="Audit local du référentiel et des références héritées ; aucune migration ou correction",
    )
    user = actions.add_parser(
        "user", help="Créer un accès avec saisie confidentielle du mot de passe"
    )
    user.add_argument("username")
    user.add_argument("--role", choices=["admin", "editor", "reader"], default="reader")
    server = actions.add_parser("serve", help="Interface locale privée")
    server.add_argument("--port", type=int, default=3820)
    server.add_argument(
        "--host",
        default="127.0.0.1",
        help="Adresse d’écoute : 127.0.0.1 ou l’adresse Wi-Fi pour le réseau local",
    )
    server.add_argument(
        "--secure-cookie",
        action="store_true",
        help="Cookie HTTPS derrière un proxy local",
    )
    server.add_argument(
        "--allowed-host", action="append", help="Nom d’hôte autorisé derrière le proxy"
    )
    saver = actions.add_parser("backup", help="Sauvegarde SQLite cohérente et photos")
    saver.add_argument(
        "output", nargs="?", help="ZIP ; par défaut, archive datée dans data/backups"
    )
    daily = actions.add_parser(
        "backup-daily", help="Sauvegarde quotidienne et restauration de contrôle"
    )
    daily.add_argument("--force", action="store_true")
    actions.add_parser("backup-status", help="État local et copie externe")
    drive = actions.add_parser(
        "backup-drive", help="Copie Drive déterministe et restauration de contrôle"
    )
    drive.add_argument("--remote", default="gdrive")
    drive.add_argument("--rclone", default=None)
    actions.add_parser(
        "backup-record-failure", help="Signaler un échec de copie externe"
    )
    uploaded = actions.add_parser(
        "backup-record-upload",
        help="Enregistrer une copie Drive après contrôle de ses métadonnées",
    )
    uploaded.add_argument("archive")
    uploaded.add_argument("file_id")
    uploaded.add_argument("size", type=int)
    uploaded.add_argument(
        "--expected-sha256", help="SHA-256 capturé avant le téléversement"
    )
    restore = actions.add_parser(
        "restore", help="Restaurer dans un nouveau dossier --data"
    )
    restore.add_argument("archive")
    prices = actions.add_parser(
        "prices", help="Relevé TCGdex des identités confirmées (prix et variantes)"
    )
    prices.add_argument("--album", default="", help="Limiter à un album (identifiant)")
    prices.add_argument(
        "--only-missing",
        action="store_true",
        help="Seulement les cartes jamais relevées",
    )
    prices.add_argument("--limit", type=int, default=None)
    prices.add_argument(
        "--actor", default="manage", help="Auteur inscrit dans l'historique"
    )
    repair = actions.add_parser(
        "repair-prices",
        help="Auditer les cotations perdues après précision de finition",
    )
    repair.add_argument("--apply", action="store_true", help="Appliquer le plan audité")
    repair.add_argument(
        "--copy-id", action="append", help="Limiter aux exemplaires indiqués"
    )
    names = actions.add_parser(
        "names",
        help="Noms des éditions en plusieurs langues (TCGdex, une fois par édition)",
    )
    names.add_argument("--languages", default="fr,en,de,it,es,pt")
    exporter = actions.add_parser("export", help="Export de la collection gérée")
    exporter.add_argument("format", choices=["csv", "json", "html"])
    exporter.add_argument("output")
    args = parser.parse_args()
    if args.action == "reference-audit":
        from .reference_service import audit_directory

        result = audit_directory(args.data)
    elif args.action == "restore":
        from .inventory_backup import restore_backup

        result = restore_backup(args.archive, args.data)
    else:
        store = Store(args.data)
        if args.action == "import":
            from .inventory_import import import_collection

            result = import_collection(store, args.manifest)
        elif args.action == "status":
            result = store.summary()
        elif args.action == "user":
            import getpass

            from .webapp import UserCreate, add_user

            password = getpass.getpass("Mot de passe (10 caractères minimum) : ")
            if password != getpass.getpass("Confirmation : "):
                raise ValueError("Les mots de passe diffèrent.")
            with store.connect(write=True) as db:
                result = add_user(
                    db,
                    UserCreate(
                        username=args.username, password=password, role=args.role
                    ),
                )
        elif args.action == "serve":
            import uvicorn

            from .webapp import create_app

            uvicorn.run(
                create_app(
                    args.data,
                    secure_cookie=args.secure_cookie,
                    allowed_hosts=args.allowed_host
                    or ["127.0.0.1", "localhost", args.host],
                ),
                host=args.host,
                port=args.port,
            )
            return
        elif args.action == "backup":
            from datetime import datetime, timezone

            from .inventory_backup import backup

            target = args.output or store.root.parent / "backups" / (
                "collection-"
                + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                + ".zip"
            )
            result = backup(store, target)
        elif args.action in (
            "backup-drive",
            "backup-daily",
            "backup-status",
            "backup-record-upload",
            "backup-record-failure",
        ):
            from .daily_backup import daily, record_external, record_failure, status

            if args.action == "backup-drive":
                from .drive_backup import upload_daily

                result = upload_daily(store, binary=args.rclone, remote=args.remote)
            elif args.action == "backup-daily":
                result = daily(store, force=args.force)
            elif args.action == "backup-status":
                result = status(store)
            elif args.action == "backup-record-failure":
                result = record_failure(store)
            else:
                result = record_external(
                    store,
                    args.archive,
                    args.file_id,
                    args.size,
                    expected_sha256=args.expected_sha256,
                )
        elif args.action == "repair-prices":
            from .price_recovery import apply, candidates

            plan = candidates(store, copy_ids=args.copy_id)
            result = apply(store, plan) if args.apply else {"candidates": plan}
        elif args.action == "prices":
            from .pricing import PriceService

            result = PriceService(store).refresh_many(
                args.actor,
                album=args.album,
                only_missing=args.only_missing,
                limit=args.limit,
            )
            from .names import NameCatalog

            # New editions get their names too; known ones cost no request.
            result["names"] = NameCatalog(store).refresh()
        elif args.action == "names":
            from .names import NameCatalog

            result = NameCatalog(store).refresh(tuple(args.languages.split(",")))
        elif args.action == "export":
            from .inventory_backup import export_csv, export_data, export_html

            output = Path(args.output)
            if output.exists():
                raise ValueError("Le fichier de sortie existe déjà.")
            output.parent.mkdir(parents=True, exist_ok=True)
            body = {
                "csv": export_csv,
                "html": export_html,
                "json": lambda s: json.dumps(
                    export_data(s), ensure_ascii=False, indent=2
                ),
            }[args.format](store)
            output.write_text(body, encoding="utf-8")
            result = {"path": str(output)}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
