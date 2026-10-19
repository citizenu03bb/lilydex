"""HTTP-only agent tools; this client never opens the collection database."""

import argparse
import ipaddress
import json
import os
import re
import stat
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_RESPONSE = 8 * 1024 * 1024
MAX_BINARY_RESPONSE = 128 * 1024 * 1024


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
            try:
                detail = json.loads(raw).get("detail", "Requête refusée.")
                if not isinstance(detail, str):
                    detail = "Paramètres de requête invalides."
            except ValueError:
                detail = "Réponse HTTP refusée."
            raise ValueError(
                f"HTTP {exc.code} : {detail}".replace(self.token, "[secret]")
            ) from None
        except (URLError, TimeoutError):
            raise ValueError(
                "Serveur agent injoignable. Réessayez la création avec la même clé."
            ) from None


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
    args = parser.parse_args(argv)
    try:
        client = AgentClient(args.url, load_token(args.token_file))
        encoded = quote(args.id, safe="") if hasattr(args, "id") else ""
        if args.action == "capabilities":
            result = client.request("/capabilities")
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
        return 1
    return 0


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
