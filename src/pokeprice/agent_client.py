"""HTTP-only agent tools; this client never opens the collection database."""

import argparse
import ipaddress
import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_RESPONSE = 8 * 1024 * 1024
MAX_BINARY_RESPONSE = 128 * 1024 * 1024
MAX_REQUEST_FILE = 65536


class AgentRequestError(ValueError):
    """Refus du serveur agent ou serveur injoignable, avec son code stable.

    ``status`` vaut ``None`` quand le serveur n'a pas répondu ; ``code`` est le
    code d'erreur du serveur (``stale_plan``, ``draft_quota``…) ou
    ``unreachable`` ; ``retry_after`` reprend l'en-tête d'une réponse 429 ;
    ``idempotency_key`` est la clé à réutiliser pour réessayer une écriture.
    """

    def __init__(self, message, *, status=None, code="", retry_after=None):
        super().__init__(message)
        self.status, self.code, self.retry_after = status, code, retry_after
        self.idempotency_key = None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A bearer token is never forwarded to a redirect destination.
        return None


class AgentClient:
    def __init__(self, url, token, *, timeout=30):
        parsed = urlsplit(url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "URL agent sans identifiants, requête ou fragment requise."
            )
        loopback = parsed.hostname == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            pass
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise ValueError("HTTPS requis, sauf sur l’interface locale de boucle.")
        if not parsed.hostname or parsed.path.rstrip("/") not in ("", "/api/agent/v1"):
            raise ValueError("URL de serveur ou /api/agent/v1 requise.")
        if not re.fullmatch(r"pp_agent_[A-Za-z0-9_-]{43}", token):
            raise ValueError("Jeton agent invalide.")
        self.base = url.rstrip("/") + (
            "" if parsed.path.rstrip("/") else "/api/agent/v1"
        )
        self.token, self.timeout = token, timeout
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, path, *, parameters=None, data=None, key=None, binary=False):
        url = self.base + path + ("?" + urlencode(parameters) if parameters else "")
        headers = {
            "Authorization": "Bearer " + self.token,
            "Accept": "application/json",
        }
        body = None
        if data is not None:
            body = json.dumps(data, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        if key:
            headers["Idempotency-Key"] = key
        try:
            with self.opener.open(
                Request(url, data=body, headers=headers), timeout=self.timeout
            ) as response:
                maximum = MAX_BINARY_RESPONSE if binary else MAX_RESPONSE
                content = response.read(maximum + 1)
                if len(content) > maximum:
                    raise ValueError("Réponse agent trop volumineuse.")
                return content if binary else json.loads(content)
        except HTTPError as exc:
            raw = exc.read(65536).decode("utf-8", "replace")
            code = ""
            try:
                payload = json.loads(raw)
                detail = payload.get("detail", "Requête refusée.")
                if not isinstance(detail, str):
                    detail = "Paramètres de requête invalides."
                code = payload.get("code", "")
                if not isinstance(code, str) or not re.fullmatch(r"[a-z_]{1,40}", code):
                    code = ""
            except (ValueError, AttributeError):
                detail = "Réponse HTTP refusée."
            label = f"HTTP {exc.code} {code}" if code else f"HTTP {exc.code}"
            retry = exc.headers.get("Retry-After") if exc.headers else None
            raise AgentRequestError(
                f"{label} : {detail}".replace(self.token, "[secret]"),
                status=exc.code,
                code=code,
                retry_after=retry,
            ) from None
        except (URLError, TimeoutError):
            raise AgentRequestError(
                "Serveur agent injoignable. Réessayez la création avec la même clé.",
                code="unreachable",
            ) from None

    def idempotent(self, path, data, key=None):
        """Écriture avec ``Idempotency-Key`` : une clé neuve, sauf celle d'un nouvel essai."""
        key = key or new_key()
        try:
            return self.request(path, data=data, key=key)
        except AgentRequestError as exc:
            exc.idempotency_key = key
            raise

    # Outil des lots : lots:read
    def lots_pool(self, max_per_lot=20):
        return self.request("/lots/pool", parameters={"max_per_lot": max_per_lot})

    def lots_status(self):
        return self.request("/lots/status")

    def lots_plan(self, recipe):
        return self.request("/lots/plan", data={"recipe": recipe})

    def lots_publication(self, sale_id):
        return self.request("/lots/" + segment(sale_id) + "/publication")

    # Outil des lots : lots:compose
    def lots_compose(self, recipe, plan_id, *, asking_cents=None, key=None):
        data = {"recipe": recipe, "plan_id": plan_id}
        if asking_cents is not None:
            data["asking_cents"] = asking_cents
        return self.idempotent("/lots", data, key)

    def lots_rotate(self, *, dry_run=True, limit=None, key=None):
        data = {"dry_run": dry_run}
        if limit is not None:
            data["limit"] = limit
        return self.idempotent("/lots/rotate", data, key)

    def lots_cancel(self, sale_id, *, expected_version, reason):
        return self.request(
            "/lots/" + segment(sale_id) + "/cancel",
            data={"expected_version": expected_version, "reason": reason},
        )

    def lots_raise(self, sale_id, *, expected_version, asking_cents):
        return self.request(
            "/lots/" + segment(sale_id) + "/raise",
            data={"expected_version": expected_version, "asking_cents": asking_cents},
        )

    # Outil des lots : lots:publish
    def lots_publish(self, sale_id, *, expected_version, dry_run=True, key=None):
        return self.idempotent(
            "/lots/" + segment(sale_id) + "/publish",
            {"expected_version": expected_version, "dry_run": dry_run},
            key,
        )

    def lots_unpublish(self, listing_id, *, expected_version, reason):
        return self.request(
            "/lots/" + segment(listing_id) + "/unpublish",
            data={"expected_version": expected_version, "reason": reason},
        )


def new_key():
    return "lots-" + uuid.uuid4().hex


def segment(identifier):
    if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", identifier or ""):
        raise ValueError("Identifiant de vente ou d’annonce invalide.")
    return identifier


def read_json_file(path):
    source = Path(path)
    if source.stat().st_size > MAX_REQUEST_FILE:
        raise ValueError("Fichier de requête limité à 64 Ko.")
    return json.loads(source.read_text())


def load_token(path=None):
    token = os.environ.get("POKEPRICE_AGENT_TOKEN", "")
    path = path or os.environ.get("POKEPRICE_AGENT_TOKEN_FILE")
    if path:
        if token:
            raise ValueError(
                "Choisissez un fichier de jeton ou la variable de jeton, pas les deux."
            )
        source = Path(path)
        if stat.S_IMODE(source.stat().st_mode) & 0o077:
            raise ValueError("Le fichier de jeton doit être privé (mode 0600).")
        token = source.read_text().strip()
    return token


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Outils agent Pokeprice : lecture et brouillons délégués"
    )
    parser.add_argument(
        "--url", default=os.environ.get("POKEPRICE_AGENT_URL", "http://127.0.0.1:3820")
    )
    parser.add_argument(
        "--token-file",
        help="Fichier privé du jeton ; aucune valeur secrète en argument",
    )
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("capabilities")
    actions.add_parser("corrections", help="Lire les corrections préautorisées")
    apply = actions.add_parser(
        "apply-correction", help="Appliquer un plan précis, sans champ libre"
    )
    apply.add_argument("id")
    apply.add_argument("--expected-version", type=int, required=True)
    apply.add_argument("--approval-sha256", required=True)
    copies = actions.add_parser("copies")
    copies.add_argument("--query", default="")
    copies.add_argument("--limit", type=int, default=60)
    copies.add_argument("--offset", type=int, default=0)
    copy = actions.add_parser("copy")
    copy.add_argument("id")
    photo = actions.add_parser("photo")
    photo.add_argument("id")
    photo.add_argument("--side", choices=["front", "back"], default="front")
    photo.add_argument("--output", required=True)
    lot = actions.add_parser("prepare-lot")
    lot.add_argument("--keep", type=int, default=1)
    lot.add_argument("--maximum", type=int, default=20)
    lot.add_argument("--language", default="")
    lot.add_argument("--request-output", help="Nouveau JSON prêt pour create-draft")
    lot.add_argument("--title", default="Lot de doublons Pokémon")
    create = actions.add_parser("create-draft")
    create.add_argument("--request-file", required=True)
    create.add_argument("--key", required=True)
    draft = actions.add_parser("draft")
    draft.add_argument("id")
    package = actions.add_parser("package")
    package.add_argument("id")
    package.add_argument("--output", required=True)
    add_lots_commands(actions)
    args = parser.parse_args(argv)
    try:
        client = AgentClient(args.url, load_token(args.token_file))
        encoded = quote(args.id, safe="") if hasattr(args, "id") else ""
        if args.action.startswith("lots-"):
            result = run_lots(client, args)
        elif args.action == "capabilities":
            result = client.request("/capabilities")
        elif args.action == "corrections":
            result = client.request("/corrections")
        elif args.action == "apply-correction":
            result = client.request(
                "/copies/" + encoded + "/apply-correction",
                data={
                    "expected_version": args.expected_version,
                    "approval_sha256": args.approval_sha256,
                },
            )
        elif args.action == "copies":
            result = client.request(
                "/copies",
                parameters={
                    "q": args.query,
                    "limit": args.limit,
                    "offset": args.offset,
                },
            )
        elif args.action == "copy":
            result = client.request("/copies/" + encoded)
        elif args.action == "prepare-lot":
            result = client.request(
                "/prepare-lot",
                parameters={
                    "keep": args.keep,
                    "maximum": args.maximum,
                    "language": args.language,
                },
            )
            if args.request_output:
                if not result["selected"]:
                    raise ValueError(
                        "Aucun doublon éligible ; consultez les exclusions."
                    )
                request = {
                    "title": args.title,
                    "description": result["description"],
                    "reason": f"Préparation déléguée de doublons ; {args.keep} exemplaire(s) conservé(s) par référence.",
                    "keep_per_reference": args.keep,
                    "copies": [
                        {"id": c["id"], "expected_version": c["version"]}
                        for c in result["selected"]
                    ],
                }
                write_private(
                    args.request_output,
                    json.dumps(request, ensure_ascii=False, indent=2).encode(),
                )
                result["request_file"] = str(Path(args.request_output).resolve())
        elif args.action == "create-draft":
            source = Path(args.request_file)
            if source.stat().st_size > 65536:
                raise ValueError("Fichier de requête limité à 64 Ko.")
            result = client.request(
                "/drafts", data=json.loads(source.read_text()), key=args.key
            )
        elif args.action == "draft":
            result = client.request("/drafts/" + encoded)
        else:
            path = (
                ("/copies/" + encoded + "/photo")
                if args.action == "photo"
                else "/drafts/" + encoded + "/package"
            )
            content = client.request(
                path,
                parameters={"side": args.side} if args.action == "photo" else None,
                binary=True,
            )
            write_private(args.output, content)
            result = {"path": str(Path(args.output).resolve()), "bytes": len(content)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        key = getattr(exc, "idempotency_key", None)
        if key:
            print(f"Clé d’idempotence : {key} (--key pour réessayer)", file=sys.stderr)
        return 1
    return 0


def add_lots_commands(actions):
    """Sous-commandes de l'outil des lots, une par route de ``/api/agent/v1/lots``."""
    pool = actions.add_parser("lots-pool", help="Gisement des doublons (lots:read)")
    pool.add_argument("--max-per-lot", type=int, default=20)
    actions.add_parser("lots-status", help="Brouillons, lots en ligne et plafond")
    plan = actions.add_parser("lots-plan", help="Essai de composition d’une recette")
    plan.add_argument("--recipe-file", required=True)
    check = actions.add_parser("lots-publication", help="Vérification de publication")
    check.add_argument("sale_id")
    compose = actions.add_parser("lots-compose", help="Brouillon d’un plan (lots:compose)")
    compose.add_argument("--recipe-file", required=True)
    compose.add_argument("--plan-id", required=True)
    compose.add_argument("--asking-cents", type=int)
    compose.add_argument("--key", help="Clé d’un nouvel essai ; neuve par défaut")
    rotate = actions.add_parser("lots-rotate", help="Rotation, à blanc sauf --apply")
    rotate.add_argument("--apply", action="store_true")
    rotate.add_argument("--limit", type=int)
    rotate.add_argument("--key", help="Clé d’un nouvel essai ; neuve par défaut")
    cancel = actions.add_parser("lots-cancel", help="Annuler un brouillon de l’outil")
    cancel.add_argument("sale_id")
    cancel.add_argument("--expected-version", type=int, required=True)
    cancel.add_argument("--reason", required=True)
    lift = actions.add_parser("lots-raise", help="Relever le prix d’un brouillon")
    lift.add_argument("sale_id")
    lift.add_argument("--expected-version", type=int, required=True)
    lift.add_argument("--asking-cents", type=int, required=True)
    publish = actions.add_parser(
        "lots-publish", help="Publier un brouillon (lots:publish), à blanc sauf --apply"
    )
    publish.add_argument("sale_id")
    publish.add_argument("--expected-version", type=int, required=True)
    publish.add_argument("--apply", action="store_true")
    publish.add_argument("--key", help="Clé d’un nouvel essai ; neuve par défaut")
    unpublish = actions.add_parser("lots-unpublish", help="Retirer une annonce de lot")
    unpublish.add_argument("listing_id")
    unpublish.add_argument("--expected-version", type=int, required=True)
    unpublish.add_argument("--reason", required=True)


def run_lots(client, args):
    action = args.action
    if action == "lots-pool":
        return client.lots_pool(args.max_per_lot)
    if action == "lots-status":
        return client.lots_status()
    if action == "lots-plan":
        return client.lots_plan(read_json_file(args.recipe_file))
    if action == "lots-publication":
        return client.lots_publication(args.sale_id)
    if action == "lots-compose":
        return client.lots_compose(
            read_json_file(args.recipe_file),
            args.plan_id,
            asking_cents=args.asking_cents,
            key=args.key,
        )
    if action == "lots-rotate":
        return client.lots_rotate(dry_run=not args.apply, limit=args.limit, key=args.key)
    if action == "lots-cancel":
        return client.lots_cancel(
            args.sale_id, expected_version=args.expected_version, reason=args.reason
        )
    if action == "lots-raise":
        return client.lots_raise(
            args.sale_id,
            expected_version=args.expected_version,
            asking_cents=args.asking_cents,
        )
    if action == "lots-publish":
        return client.lots_publish(
            args.sale_id,
            expected_version=args.expected_version,
            dry_run=not args.apply,
            key=args.key,
        )
    return client.lots_unpublish(
        args.listing_id, expected_version=args.expected_version, reason=args.reason
    )


def write_private(path, body):
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(body)
    except BaseException:
        Path(path).unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
