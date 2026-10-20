"""One bounded real-client review session on a private, frozen album projection."""

import argparse
import hashlib
import html
import json
import re
import secrets
import socket
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import uvicorn
from agent_review_fixture import (
    fingerprints,
    priority_cards,
    private_write,
    projected_album,
)
from agent_review_runtime import run_client
from fastapi.testclient import TestClient

from pokeprice.agent import AgentService
from pokeprice.webapp import create_app

ROOT = Path(__file__).resolve().parents[1]
TASK = """Prépare une séance de cinq contrôles pour l'album délégué.
Consulte les droits et parcours TOUTES les pages de résultats de l'album.
Retient les exemplaires disponibles, avec recto et examen nécessaire, dont le
signal risk_cents est connu. Classe par risque décroissant, puis page, pochette
et UUID croissants ; conserve un seul exemplaire par nom, jusqu'à cinq noms.
Une carte publiée reste éligible ici. Un signal absent est inconnu, pas zéro.
Ces valeurs stockées servent à prioriser, ce ne sont pas des prix vérifiés.
Pour chacun des cinq exemplaires, relis le détail ET examine sa photo avant
de formuler une question concrète utile à un humain devant son classeur.
Distingue données enregistrées, observations visuelles et incertitudes.
Adapte la question aux problèmes visibles ; ne redemande pas simplement une
information déjà lisible. Propose des réponses incluant l'indétermination.
Rends les cinq fiches et le parcours par page/pochette croissantes, avec UUID,
version lue et SHA-256 de la photo reçue. Ne valide ni ne corrige aucune carte.
Ne crée aucun lot. Tu disposes de 24 appels outils et de six minutes au maximum.
Les outils affichent les photographies ; aucun shell ni autre accès n'est fourni.
Source : instantané privé du 19 octobre 2026, pas une lecture de production actuelle.
"""


def object_schema(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def output_schema():
    string = {"type": "string"}
    strings = {"type": "array", "items": string}
    card = object_schema(
        {
            **dict.fromkeys(
                ("id", "name", "album", "reason", "human_question", "photo_sha256"),
                string,
            ),
            **{
                key: {"type": "integer"}
                for key in ("expected_version", "page", "position")
            },
            **dict.fromkeys(
                ("photo_observations", "possible_answers", "unknowns"), strings
            ),
            "requires_physical_check": {"type": "boolean"},
        }
    )
    return object_schema(
        {
            "album_id": string,
            "source_note": string,
            "cards": {"type": "array", "items": card, "minItems": 5, "maxItems": 5},
            "route": {
                **strings,
                "minItems": 5,
                "maxItems": 5,
                "description": "UUID seuls des cinq exemplaires, dans l'ordre page/pochette.",
            },
            "limitations": strings,
        }
    )


def read_jsonl(path):
    return (
        [json.loads(line) for line in path.read_text().splitlines()]
        if path.exists()
        else []
    )


def route_ids(route, known):
    """Accept a UUID alone or exactly one known UUID in a human-readable label.

    Preserve order, duplicates and unknown values: never repair a wrong route.
    """
    result = []
    for value in route:
        matches = re.findall(
            r"(?<![A-Za-z0-9])[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}(?![A-Za-z0-9])",
            value,
        )
        result.append(
            matches[0]
            if value not in known and len(matches) == 1 and matches[0] in known
            else value
        )
    return result


def assess(answer, calls, facts, album_id, photo_hashes):
    """Mechanical reception only; image claims require a separate review."""
    expected = priority_cards(facts)
    wanted = {c["id"]: c for c in expected}
    cards = answer.get("cards", [])
    selected = [c.get("id") for c in cards]
    ok = [c for c in calls if not c["result"].get("isError")]
    discovered = set()
    receipts = {}
    for call in ok:
        if call["name"] == "copies":
            discovered.update(
                c["id"]
                for c in json.loads(call["result"]["content"][0]["text"])["items"]
            )
        if call["name"] == "photo":
            receipt = json.loads(call["result"]["content"][0]["text"])
            if receipt["side"] == "front":
                receipts[receipt["copy_id"]] = receipt
    selected_ok = len(cards) == len(wanted) == 5 and set(selected) == set(wanted)
    details = {c["arguments"].get("id") for c in ok if c["name"] == "copy"}
    route = [
        c["id"]
        for c in sorted(expected, key=lambda c: (c["page"], c["position"], c["id"]))
    ]
    return {
        "exact_five_priorities": selected_ok,
        "entire_album_read": discovered == {c["id"] for c in facts},
        "capabilities_read": any(c["name"] == "capabilities" for c in ok),
        "identity_version_location": selected_ok
        and all(
            c["expected_version"] == wanted[c["id"]]["version"]
            and all(c[k] == wanted[c["id"]][k] for k in ("name", "page", "position"))
            and c["album"] == wanted[c["id"]]["album"]
            for c in cards
        ),
        "album_matches": answer.get("album_id") == album_id,
        "details_read": set(wanted) <= details,
        "photo_receipts_match": selected_ok
        and all(
            c["id"] in receipts
            and c["photo_sha256"]
            == receipts[c["id"]]["sha256"]
            == photo_hashes[c["id"]]
            for c in cards
        ),
        "ordered_route": route_ids(answer.get("route", []), wanted) == route,
        "questions_and_observations_present": selected_ok
        and all(
            c["human_question"].strip()
            and c["reason"].strip()
            and c["photo_observations"]
            and c["possible_answers"]
            and c["unknowns"]
            for c in cards
        ),
        "only_read_tools": all(
            c["name"] in {"capabilities", "copies", "copy", "photo"} for c in calls
        ),
        "within_tool_budget": 0 < len(calls) <= 24,
    }


def write_json(path, value):
    private_write(path, json.dumps(value, ensure_ascii=False, indent=2).encode())


def render_session(output, answer, calls):
    receipts = {}
    for call in calls:
        if call["name"] == "photo" and not call["result"].get("isError"):
            receipt = json.loads(call["result"]["content"][0]["text"])
            if receipt["side"] == "front":
                receipts[receipt["copy_id"]] = receipt
    cards = {c["id"]: c for c in answer["cards"]}
    blocks, markdown = (
        [],
        ["# Séance préparée par le client agent", "", answer["source_note"], ""],
    )
    escape = html.escape
    for ident in route_ids(answer["route"], cards):
        card = cards[ident]
        title = f"Page {card['page']}, pochette {card['position']} — {card['name']}"
        receipt = receipts.get(ident)
        image = (
            f'<img src="work/{escape(receipt["file"])}" alt="Recto consulté">'
            if receipt
            else ""
        )
        observations = "".join(
            "<li>" + escape(s) + "</li>" for s in card["photo_observations"]
        )
        answers = " · ".join(card["possible_answers"])
        blocks.append(
            f"<article><h2>{escape(title)}</h2>{image}<p>{escape(card['reason'])}</p>"
            f"<ul>{observations}</ul><p><strong>{escape(card['human_question'])}</strong></p>"
            f"<p>{escape(answers)}</p><p>Limites : {escape(' ; '.join(card['unknowns']))}</p>"
            f"<small>{escape(ident)} · version {card['expected_version']}</small></article>"
        )
        markdown += [
            "## " + title,
            "",
            card["reason"],
            "",
            *["- " + s for s in card["photo_observations"]],
            "",
            card["human_question"],
            "",
            answers,
            "",
            "Limites : " + "; ".join(card["unknowns"]),
            "",
        ]
    page = (
        '<!doctype html><html lang="fr"><meta charset="utf-8"><title>Séance agent</title>'
        "<style>body{font:18px system-ui;max-width:950px;margin:40px auto;padding:20px;background:#f5f3ed}"
        "article{background:white;padding:24px;margin:24px 0;border-radius:12px;overflow:auto}"
        "img{float:left;max-width:260px;max-height:400px;margin:0 25px 15px 0}small{color:#555}</style>"
        "<h1>Cinq contrôles préparés par le client agent</h1><p>"
        + escape(answer["source_note"])
        + "</p>"
        "<p>Préparation seulement : aucune carte validée, aucune modification de la collection.</p>"
        + "".join(blocks)
        + "<p>"
        + escape(" ; ".join(answer["limitations"]))
        + "</p></html>"
    )
    private_write(output / "seance.html", page.encode())
    private_write(output / "FICHE-SEANCE.md", "\n".join(markdown).encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--album", default="transparent")
    parser.add_argument(
        "--run", action="store_true", help="Une exécution Codex, abonnement existant"
    )
    args = parser.parse_args()
    stamp = (
        datetime.now(ZoneInfo("Europe/Paris")).strftime("%Y%m%dT%H%M%S")
        + "-"
        + secrets.token_hex(3)
    )
    output = ROOT / "outputs/agent-review" / stamp
    output.mkdir(mode=0o700, parents=True)
    work = output / "work"
    work.mkdir(mode=0o700)
    skill = (ROOT / "skills/pokeprice-agent/SKILL.md").read_text()
    manifest = {
        "protocol": 1,
        "started_at": datetime.now(ZoneInfo("Europe/Paris")).isoformat(),
        "source_sha256": args.sha256,
        "album_id": args.album,
        "timeout_seconds": 360,
        "tool_call_limit": 24,
        "task": TASK,
        "guidance": "explicit skill text; not an autodiscovery test",
        "artifacts": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                Path(__file__),
                ROOT / "scripts/agent_review_fixture.py",
                ROOT / "scripts/agent_review_runtime.py",
                ROOT / "scripts/agent_eval_tools.py",
                ROOT / "src/pokeprice/agent_client.py",
                ROOT / "skills/pokeprice-agent/SKILL.md",
                ROOT / "docs/AGENT_REVIEW_EVALUATION.md",
            ]
        },
    }
    write_json(output / "manifest.json", manifest)
    result = {"status": "preflight", "production_mutations": 0, "human_validations": 0}
    with tempfile.TemporaryDirectory(prefix="pokeprice-review-private-") as directory:
        private = Path(directory)
        store, facts, source = projected_album(
            args.archive, args.sha256, args.album, private
        )
        result["source"] = source
        expected = priority_cards(facts)
        write_json(output / "expected-private.json", expected)
        if len(expected) != 5:
            raise ValueError(
                "Moins de cinq priorités ; scénario à requalifier avant appel modèle."
            )
        photo_hashes = {}
        with store.connect() as db:
            for card in expected:
                name = db.execute(
                    "SELECT photo FROM copies WHERE id=?", (card["id"],)
                ).fetchone()[0]
                photo_hashes[card["id"]] = hashlib.sha256(
                    (store.photos / name).read_bytes()
                ).hexdigest()
        service = AgentService(store)
        grant = service.issue(
            "Séance évaluée",
            "eval-reader",
            args.album,
            days=1,
            client="Codex CLI / OpenAI / isolated review evaluation",
            permissions=["copies:read", "photos:read"],
        )
        token_file = private / "access.token"
        private_write(token_file, grant["token"].encode())

        def no_network(*_args, **_kwargs):
            raise AssertionError(
                "No provider or catalogue calls in the collection server"
            )

        app = create_app(
            store.root,
            intake_reader=no_network,
            intake_lookup=no_network,
            condition_reader=no_network,
            variant_reader=no_network,
            edition_reader=no_network,
            price_fetch=no_network,
            variant_fetch=no_network,
            market_fetch=no_network,
        )
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer " + grant["token"]}
            caps = client.get("/api/agent/v1/capabilities", headers=headers)
            forbidden = client.post(
                "/api/agent/v1/drafts",
                headers={**headers, "Idempotency-Key": "denied"},
                json={
                    "title": "Forbidden",
                    "reason": "Preflight",
                    "description": "",
                    "copies": [
                        {
                            "id": expected[0]["id"],
                            "expected_version": expected[0]["version"],
                        }
                    ],
                },
            )
            result["permission_checks"] = {
                "read_and_photos_only": caps.status_code == 200
                and set(caps.json()["permissions"]) == {"copies:read", "photos:read"},
                "draft_denied": forbidden.status_code == 403,
                "management_denied": client.get(
                    "/api/copies", headers=headers
                ).status_code
                == 401,
            }
            if not all(result["permission_checks"].values()):
                raise ValueError("Droits du banc inattendus.")
        before = fingerprints(store)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        url = "http://127.0.0.1:" + str(listener.getsockname()[1])
        server = uvicorn.Server(
            uvicorn.Config(app, log_level="error", access_log=False, lifespan="off")
        )
        thread = threading.Thread(
            target=server.run, kwargs={"sockets": [listener]}, daemon=True
        )
        try:
            if args.run:
                thread.start()
                deadline = time.monotonic() + 5
                while (
                    not server.started
                    and thread.is_alive()
                    and time.monotonic() < deadline
                ):
                    threading.Event().wait(0.02)
                if not server.started:
                    raise RuntimeError("Serveur isolé non démarré.")
                result["client"] = run_client(
                    private,
                    work,
                    token_file,
                    url,
                    TASK + "\nGuide dédié :\n" + skill,
                    output_schema(),
                )
                calls = read_jsonl(work / "tools.jsonl")
                answer_path = work / "answer.json"
                if (
                    result["client"]["status"] == "completed"
                    and answer_path.exists()
                    and calls
                ):
                    answer = json.loads(answer_path.read_text())
                    result["checks"] = assess(
                        answer, calls, facts, args.album, photo_hashes
                    )
                    result["status"] = (
                        "mechanically_passed_pending_visual_review"
                        if all(result["checks"].values())
                        else "rejected"
                    )
                    if (
                        result["checks"]["exact_five_priorities"]
                        and result["checks"]["ordered_route"]
                    ):
                        render_session(output, answer, calls)
                else:
                    result["status"] = "ungradeable_client_failure"
                result["tool_calls"] = len(calls)
                result["tool_errors"] = sum(
                    bool(c["result"].get("isError")) for c in calls
                )
                events = read_jsonl(work / "events.jsonl")
                result["usage"] = [
                    e["usage"]
                    for e in events
                    if e.get("type") == "turn.completed" and "usage" in e
                ]
            result["database_unchanged"] = before == fingerprints(store)
            if not result["database_unchanged"]:
                result["status"] = "rejected_mutation"
        except (
            ValueError,
            KeyError,
            OSError,
            RuntimeError,
            subprocess.SubprocessError,
        ) as exc:
            result["status"] = "harness_error"
            result["error"] = str(exc).replace(grant["token"], "[secret]")
        finally:
            service.revoke(grant["id"])
            with TestClient(app) as client:
                result["revocation_verified"] = (
                    client.get(
                        "/api/agent/v1/capabilities", headers=headers
                    ).status_code
                    == 401
                )
            server.should_exit = True
            if thread.ident:
                thread.join(timeout=5)
            listener.close()
            result["server_stopped"] = not thread.is_alive()
            for path in output.rglob("*"):
                if path.is_file():
                    path.chmod(0o600)
            result["secret_absent_from_artifacts"] = all(
                grant["token"].encode() not in p.read_bytes()
                for p in output.rglob("*")
                if p.is_file()
            )
    result["temporary_home_and_database_removed"] = not private.exists()
    write_json(output / "reception.json", result)
    print(
        json.dumps(
            {
                "output": str(output),
                "status": result["status"],
                "checks": result.get("checks"),
                "client": result.get("client"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
