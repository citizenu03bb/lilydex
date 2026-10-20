"""Evaluation-only stdio MCP bridge to the real HTTP CLI, never to SQLite.

Run only through evaluate_agent_control.py. No arbitrary shell, URL or path is
accepted from the model. This is a test adapter, not a supported MCP service.
"""

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path


def tool(name, description, properties=None, required=None):
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
            "additionalProperties": False,
        },
    }


TOOLS = [
    tool("capabilities", "Consulter les droits et limites de la délégation."),
    tool(
        "copies",
        "Rechercher dans l'album délégué, avec pagination.",
        {
            "query": {"type": "string"},
            "offset": {"type": "integer", "minimum": 0},
        },
    ),
    tool(
        "copy",
        "Consulter un exemplaire par UUID.",
        {
            "id": {"type": "string"},
        },
        ["id"],
    ),
    tool(
        "prepare_lot",
        "Commande prepare-lot : analyser et produire une requête de brouillon.",
        {
            "keep": {"type": "integer", "minimum": 1, "maximum": 10},
            "maximum": {"type": "integer", "minimum": 1, "maximum": 20},
            "language": {"type": "string"},
        },
        ["keep", "maximum", "language"],
    ),
    tool(
        "create_draft",
        "Créer le brouillon de la requête préparée, avec clé d'idempotence.",
        {
            "request_handle": {"type": "string"},
            "key": {"type": "string"},
        },
        ["request_handle", "key"],
    ),
    tool(
        "draft",
        "Relire un brouillon et son instantané.",
        {
            "id": {"type": "string"},
        },
        ["id"],
    ),
]

PHOTO_TOOL = tool(
    "photo",
    "Consulter la photographie d'un exemplaire délégué : image et empreinte SHA-256.",
    {"id": {"type": "string"}, "side": {"type": "string", "enum": ["front", "back"]}},
    ["id"],
)


def available_tools():
    return (
        TOOLS[:3] + [PHOTO_TOOL] if os.environ.get("EVAL_TASK") == "review" else TOOLS
    )


def cli(*args):
    process = subprocess.run(
        [sys.executable, "/tools/client.py", *map(str, args)],
        check=False,
        capture_output=True,
        text=True,
        timeout=35,
    )
    if process.returncode:
        raise ValueError(process.stderr.strip())
    return json.loads(process.stdout)


def invoke(name, args):
    # Reject extra keys even if a client does not enforce the advertised schema.
    spec = next((t for t in available_tools() if t["name"] == name), None)
    if not spec or set(args) - set(spec["inputSchema"]["properties"]):
        raise ValueError("Outil ou paramètres inconnus.")
    if name == "capabilities":
        return cli("capabilities")
    if name == "copies":
        result = cli(
            "copies",
            "--query",
            args.get("query", ""),
            "--limit",
            100,
            "--offset",
            args.get("offset", 0),
        )
        if os.environ.get("EVAL_TASK") == "review":
            # The full detail remains available through copy; only shorten the
            # discovery pages so the client can actually read the entire album.
            result["items"] = [
                {
                    **{
                        key: card[key]
                        for key in (
                            "id",
                            "version",
                            "name",
                            "page",
                            "position",
                            "language",
                            "stock_state",
                            "has_front",
                            "published",
                        )
                    },
                    "valuation": {
                        key: card["valuation"][key]
                        for key in (
                            "risk_cents",
                            "risk_incomplete",
                            "needs_review",
                            "review_codes",
                        )
                    },
                }
                for card in result["items"]
            ]
        return result
    if name in ("copy", "draft"):
        return cli(name, args["id"])
    if name == "photo":
        side = args.get("side", "front")
        if side not in ("front", "back"):
            raise ValueError("Face de photo invalide.")
        workspace = Path(os.environ.get("EVAL_WORKSPACE", "/work"))
        path = workspace / ("photo-" + uuid.uuid4().hex + ".jpg")
        cli("photo", args["id"], "--side", side, "--output", path)
        body = path.read_bytes()
        if len(body) > 8 * 1024 * 1024:
            path.unlink()
            raise ValueError("Photo trop volumineuse pour ce banc (8 Mo).")
        metadata = {
            "copy_id": args["id"],
            "side": side,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "file": path.name,
        }
        return {
            "content": [
                {"type": "text", "text": json.dumps(metadata)},
                {
                    "type": "image",
                    "mimeType": "image/jpeg",
                    "data": base64.b64encode(body).decode(),
                },
            ]
        }
    if name == "prepare_lot":
        result = cli(
            "prepare-lot",
            "--keep",
            args["keep"],
            "--maximum",
            args["maximum"],
            "--language",
            args["language"],
        )
        if result["selected"]:
            handle = uuid.uuid4().hex
            payload = {
                "title": "Doublons — évaluation synthétique",
                "description": result["description"],
                "reason": "Demande conversationnelle synthétique",
                "keep_per_reference": args["keep"],
                "copies": [
                    {"id": c["id"], "expected_version": c["version"]}
                    for c in result["selected"]
                ],
            }
            path = Path("/work") / (handle + ".json")
            path.write_text(json.dumps(payload, ensure_ascii=False))
            path.chmod(0o600)
            result["request_handle"] = handle
        return result
    handle = args["request_handle"]
    if not re.fullmatch(r"[a-f0-9]{32}", handle):
        raise ValueError("Identifiant de requête invalide.")
    result = cli(
        "create-draft",
        "--request-file",
        "/work/" + handle + ".json",
        "--key",
        args["key"],
    )
    marker = Path("/work/response-lost")
    if os.environ.get("EVAL_LOSE_RESPONSE") == "1" and not marker.exists():
        marker.touch()
        raise ValueError(
            "Réponse perdue après l'appel serveur. Résultat inconnu du client."
        )
    return result


def main():
    count = 0
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        method = request["method"]
        if method == "initialize":
            result = {
                "protocolVersion": request["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "pokeprice-evaluation", "version": "1"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": available_tools()}
        elif method == "tools/call":
            count += 1
            params = request["params"]
            try:
                maximum = min(40, int(os.environ.get("EVAL_MAX_TOOL_CALLS", "12")))
                if count > maximum:
                    raise ValueError(f"Budget de {maximum} appels atteint.")
                value = invoke(params["name"], params.get("arguments", {}))
                result = (
                    value
                    if params["name"] == "photo"
                    else {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(value, ensure_ascii=False),
                            }
                        ]
                    }
                )
            except (ValueError, KeyError, OSError, subprocess.TimeoutExpired) as exc:
                result = {
                    "isError": True,
                    "content": [{"type": "text", "text": str(exc)}],
                }
            # Images are delivered to the client, but the audit needs only
            # their digest and the receipt, not another base64 copy.
            logged = {
                **result,
                "content": [
                    {key: value for key, value in block.items() if key != "data"}
                    if block["type"] == "image"
                    else block
                    for block in result["content"]
                ],
            }
            workspace = Path(os.environ.get("EVAL_WORKSPACE", "/work"))
            with open(
                workspace / "tools.jsonl",
                "a",
                opener=lambda p, flags: os.open(p, flags, 0o600),
            ) as log:
                log.write(
                    json.dumps(
                        {
                            "name": params["name"],
                            "arguments": params.get("arguments", {}),
                            "result": logged,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        else:
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request["id"],
                        "error": {"code": -32601, "message": "Method not found"},
                    }
                ),
                flush=True,
            )
            continue
        print(
            json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}),
            flush=True,
        )


if __name__ == "__main__":
    main()
