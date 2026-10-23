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
    recheck = actions.add_parser(
        "reference-recheck",
        help="Suspensions de cotations liées devenues incompatibles (après mise à jour des règles)",
    )
    recheck.add_argument(
        "--apply", action="store_true", help="Inscrire les suspensions au journal"
    )
    recheck.add_argument("--reason", default="Mise à jour du référentiel")
    archive = actions.add_parser(
        "reference-archive",
        help="Archiver une pièce justificative (PDF, HTML, JSON) par empreinte SHA-256",
    )
    archive.add_argument("document")
    user = actions.add_parser(
        "user", help="Créer un accès avec saisie confidentielle du mot de passe"
    )
    user.add_argument("username")
    user.add_argument("--role", choices=["admin", "editor", "reader"], default="reader")
    agents = actions.add_parser("agent-create", help="Déléguer un album à un agent")
    agents.add_argument("name")
    agents.add_argument("--owner", required=True, help="Compte de gestion délégant")
    agents.add_argument("--album", required=True)
    agents.add_argument(
        "--client", required=True, help="Client et destinataire des données/photos"
    )
    agents.add_argument("--days", type=int, default=7)
    agents.add_argument("--photos", action="store_true")
    agents.add_argument("--drafts", action="store_true")
    agents.add_argument(
        "--corrections",
        action="store_true",
        help="Appliquer seulement des corrections préautorisées",
    )
    agents.add_argument("--value-ceiling-eur", default="10")
    agents.add_argument(
        "--token-file",
        required=True,
        help="Nouveau fichier privé ; aucun secret sur stdout",
    )
    actions.add_parser("agent-list", help="Lister les délégations sans leurs secrets")
    revoke = actions.add_parser(
        "agent-revoke", help="Révoquer immédiatement un accès agent"
    )
    revoke.add_argument("grant_id")
    approve = actions.add_parser(
        "agent-approve-corrections",
        help="Autoriser un plan précis de rattachements catalogue",
    )
    approve.add_argument("grant_id")
    approve.add_argument("--request-file", required=True)
    approve.add_argument("--reason", required=True)
    actions.add_parser(
        "agent-schema", help="Contrat OpenAPI agent hors ligne, sans ouvrir de base"
    )
    server = actions.add_parser("serve", help="Interface locale privée")
    server.add_argument("--port", type=int, default=3820)
    server.add_argument(
        "--no-agent-api", action="store_true", help="Désactiver les routes agent"
    )
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
    server.add_argument(
        "--no-auto-checks",
        action="store_true",
        help="Ne pas lire la finition (Gemini) automatiquement après chaque saisie photo",
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
    actions.add_parser(
        "backup-key",
        help="Créer (une fois) la clé de chiffrement des copies Drive ; affiche la clé publique",
    )
    drive = actions.add_parser(
        "backup-drive", help="Copie Drive déterministe et restauration de contrôle"
    )
    drive.add_argument("--remote", default="gdrive")
    drive.add_argument("--rclone", default=None)
    for name, summary in (
        ("backup-server-pull", "Rapatrier et vérifier la sauvegarde du serveur"),
        ("backup-server-drive", "Copie Drive de la sauvegarde rapatriée du serveur"),
    ):
        mirrored = actions.add_parser(name, help=summary)
        mirrored.add_argument("--host", required=True, help="utilisateur@serveur")
        mirrored.add_argument(
            "--mirror",
            default="data/oci-backups",
            help="Archives rapatriées ; jamais un dossier de collection",
        )
        mirrored.add_argument("--ssh", default="ssh")
        if name == "backup-server-drive":
            mirrored.add_argument("--remote", default="gdrive")
            mirrored.add_argument("--rclone", default=None)
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
    prices.add_argument(
        "--unpriced",
        action="store_true",
        help="Seulement les cartes sans prix de référence, relevées ou non",
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
    pages = actions.add_parser(
        "repair-pages",
        help="Auditer les pages décalées par une couverture comptée comme page 1",
    )
    pages.add_argument("--apply", action="store_true", help="Appliquer le plan audité")
    names = actions.add_parser(
        "names",
        help="Noms des éditions en plusieurs langues (TCGdex, une fois par édition)",
    )
    names.add_argument("--languages", default="fr,en,de,it,es,pt")
    forget = actions.add_parser(
        "forget", help="Effacer un client de la vitrine (e-mail ou identifiant)"
    )
    forget.add_argument("client")
    forget.add_argument("--reason", default="Demande de la personne")
    actions.add_parser(
        "purge", help="Appliquer les durées de conservation des données clients"
    )
    exporter = actions.add_parser("export", help="Export de la collection gérée")
    exporter.add_argument("format", choices=["csv", "json", "html"])
    exporter.add_argument("output")
    args = parser.parse_args()
    if args.action == "agent-schema":
        from .agent_api import schema

        result = schema()
    elif args.action == "reference-audit":
        from .reference_service import audit_directory

        result = audit_directory(args.data)
    elif args.action == "reference-archive":
        from .reference_service import archive_document

        result = archive_document(args.data, args.document)
    elif args.action == "backup-key":
        from .drive_backup import create_key

        result = create_key()
    elif args.action == "restore":
        from .inventory_backup import restore_backup

        result = restore_backup(args.archive, args.data)
        from .privacy import Privacy, erasure_log

        # The archive may predate erasures: they are applied again.
        if erasure_log(args.data).exists():
            result["erasures"] = Privacy(Store(args.data)).replay()
    elif args.action in ("backup-server-pull", "backup-server-drive"):
        # The live base is on the server: --data is never opened here.
        from .server_backup import Mirror, pull_latest

        mirror = Mirror(args.mirror)
        if args.action == "backup-server-pull":
            result = pull_latest(mirror, args.host, ssh=args.ssh)
        else:
            from .drive_backup import upload_server

            result = upload_server(
                mirror,
                args.host,
                binary=args.rclone,
                remote=args.remote,
                ssh=args.ssh,
            )
    else:
        store = Store(args.data)
        if args.action == "import":
            from .inventory_import import import_collection

            result = import_collection(store, args.manifest)
        elif args.action in (
            "agent-create",
            "agent-list",
            "agent-revoke",
            "agent-approve-corrections",
        ):
            from .agent import AgentService
            from .inventory import cents

            agents = AgentService(store)
            if args.action == "agent-list":
                result = agents.grants()
            elif args.action == "agent-revoke":
                result = agents.revoke(args.grant_id)
            elif args.action == "agent-approve-corrections":
                from .agent_corrections import CorrectionService

                source = Path(args.request_file)
                if source.stat().st_size > 65536:
                    raise ValueError("Plan limité à 64 Ko.")
                result = CorrectionService(store).approve(
                    args.grant_id, json.loads(source.read_text()), args.reason
                )
            else:
                import os

                permissions = ["copies:read"]
                if args.photos:
                    permissions.append("photos:read")
                if args.drafts:
                    permissions.append("drafts:create")
                if args.corrections:
                    permissions.append("corrections:apply")
                path = Path(args.token_file)
                handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                grant = None
                try:
                    with os.fdopen(handle, "w") as stream:
                        grant = agents.issue(
                            args.name,
                            args.owner,
                            args.album,
                            permissions=permissions,
                            days=args.days,
                            client=args.client,
                            value_ceiling_cents=cents(args.value_ceiling_eur),
                        )
                        stream.write(grant["token"] + "\n")
                    result = {k: v for k, v in grant.items() if k != "token"}
                    result["token_file"] = str(path.resolve())
                except BaseException:
                    if grant:
                        agents.revoke(grant["id"])
                    path.unlink(missing_ok=True)
                    raise
        elif args.action == "status":
            result = store.summary()
        elif args.action == "reference-recheck":
            from .quote_ledger import recheck_all

            result = recheck_all(
                store, "system:reference-recheck", args.reason, apply=args.apply
            )
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
                    auto_checks=not args.no_auto_checks,
                    agent_enabled=not args.no_agent_api,
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
        elif args.action in ("forget", "purge"):
            from .privacy import Privacy

            privacy = Privacy(store)
            result = (
                privacy.forget(args.client, args.reason)
                if args.action == "forget"
                else privacy.purge()
            )
        elif args.action == "repair-prices":
            from .price_recovery import apply, candidates

            plan = candidates(store, copy_ids=args.copy_id)
            result = apply(store, plan) if args.apply else {"candidates": plan}
        elif args.action == "repair-pages":
            from .page_shift import apply, candidates

            plan = candidates(store)
            result = apply(store, plan) if args.apply else {"candidates": plan}
        elif args.action == "prices":
            from .cardmarket_guide import CardmarketGuide
            from .market_product import MarketProducts
            from .pricing import PriceService, fetch_card_with_guide

            guide = CardmarketGuide(store.root / "cardmarket", store)
            result = PriceService(
                store, fetch_card_with_guide(guide), market=MarketProducts(store)
            ).refresh_many(
                args.actor,
                album=args.album,
                only_missing=args.only_missing,
                unpriced=args.unpriced,
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
    # Output lands in the systemd journal: the private Drive folder stays out of it.
    print(json.dumps(without_drive_folder(result), ensure_ascii=False, indent=2))


def without_drive_folder(value):
    if isinstance(value, dict):
        return {
            key: without_drive_folder(item)
            for key, item in value.items()
            if key not in ("folder_id", "drive_folder_url")
        }
    return value


if __name__ == "__main__":
    main()
