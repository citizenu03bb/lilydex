import base64
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
import test_agent_client
from PIL import Image

from pokeprice.inventory_backup import backup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent_eval_tools as bridge
from agent_review_fixture import fingerprints, priority_cards, projected_album
from evaluate_agent_review import assess, route_ids


@pytest.fixture
def shop(tmp_path):
    yield from test_agent_client.shop.__wrapped__(tmp_path)


@pytest.fixture
def live_server(shop):
    yield from test_agent_client.live_server.__wrapped__(shop)


def test_review_bridge_delivers_real_http_photo_and_respects_revocation(
    live_server, tmp_path, monkeypatch
):
    url, (_client, service, grant, cards, other, _user) = live_server
    stream = io.BytesIO()
    Image.new("RGB", (40, 60), "purple").save(stream, "JPEG")
    body = stream.getvalue()
    name = service.store.save_photo(body)
    service.store.patch(cards[0]["id"], {"photo": name}, 1, "owner", "Test image")
    token_file = tmp_path / "access.token"
    token_file.write_text(grant["token"])
    token_file.chmod(0o600)
    monkeypatch.setenv("EVAL_TASK", "review")
    monkeypatch.setenv("EVAL_WORKSPACE", str(tmp_path))
    client_path = Path(__file__).resolve().parents[1] / "src/pokeprice/agent_client.py"

    def real_cli(*args):
        process = subprocess.run(
            [
                sys.executable,
                str(client_path),
                "--url",
                url,
                "--token-file",
                str(token_file),
                *map(str, args),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if process.returncode:
            raise ValueError(process.stderr)
        return json.loads(process.stdout)

    monkeypatch.setattr(bridge, "cli", real_cli)
    assert {t["name"] for t in bridge.available_tools()} == {
        "capabilities",
        "copies",
        "copy",
        "photo",
    }
    result = bridge.invoke("photo", {"id": cards[0]["id"]})
    receipt = json.loads(result["content"][0]["text"])
    assert receipt["sha256"] == hashlib.sha256(body).hexdigest() == name[:-4]
    assert base64.b64decode(result["content"][1]["data"]) == body
    assert result["content"][1]["mimeType"] == "image/jpeg"
    assert (tmp_path / receipt["file"]).stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError, match="inconnus"):
        bridge.invoke("create_draft", {"request_handle": "x", "key": "x"})
    with pytest.raises(ValueError, match="404"):
        bridge.invoke("photo", {"id": other["id"]})
    service.revoke(grant["id"])
    with pytest.raises(ValueError, match="401"):
        bridge.invoke("photo", {"id": cards[0]["id"]})


def test_projection_preserves_facts_without_accounts_other_albums_or_private_notes(
    shop, tmp_path
):
    _client, service, _grant, cards, other, _user = shop
    # A market verdict recorded on another album still affects this catalogue.
    with service.store.connect(write=True) as db:
        service.store.event(
            db,
            other["id"],
            "owner",
            "market-product",
            "Catalogue verdict",
            {},
            {"catalog_id": "test-1", "status": "unstable", "reason": "Synthetic"},
        )
    before = fingerprints(service.store)
    archive = tmp_path / "snapshot.zip"
    backup(service.store, archive)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    store, facts, metadata = projected_album(
        archive, hashlib.sha256(archive.read_bytes()).hexdigest(), "a", private
    )
    assert metadata["facts_equal_to_source"] and len(facts) == len(cards)
    with store.connect() as db:
        assert [r[0] for r in db.execute("SELECT id FROM albums")] == ["a"]
        assert [r[0] for r in db.execute("SELECT username FROM users")] == [
            "eval-reader"
        ]
        assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
        assert (
            db.execute("SELECT count(*) FROM copies WHERE notes != ''").fetchone()[0]
            == 0
        )
        assert not db.execute(
            "SELECT 1 FROM copies WHERE id=?", (other["id"],)
        ).fetchone()
        assert (
            db.execute(
                "SELECT copy_id FROM events WHERE kind='market-product'"
            ).fetchone()[0]
            is None
        )
    assert before == fingerprints(service.store)


def test_reception_rejects_wrong_photo_stale_version_and_partial_discovery():
    facts = [
        {
            "id": str(i),
            "name": str(i),
            "version": 3,
            "album": "Album",
            "page": i,
            "position": 1,
            "stock_state": "available",
            "has_front": True,
            "valuation": {"needs_review": True, "risk_cents": 100 - i},
        }
        for i in range(5)
    ]
    # Duplicate names and unknown risks must not displace the fifth priority.
    assert (
        len(
            priority_cards(
                facts
                + [
                    {**facts[0], "id": "duplicate"},
                    {
                        **facts[0],
                        "id": "unknown",
                        "valuation": {"needs_review": True, "risk_cents": None},
                    },
                ]
            )
        )
        == 5
    )
    calls = [
        {"name": "capabilities", "arguments": {}, "result": {"content": []}},
        {
            "name": "copies",
            "arguments": {},
            "result": {
                "content": [{"type": "text", "text": json.dumps({"items": facts})}]
            },
        },
    ]
    cards = []
    for fact in facts:
        calls += [
            {
                "name": "copy",
                "arguments": {"id": fact["id"]},
                "result": {"content": []},
            },
            {
                "name": "photo",
                "arguments": {"id": fact["id"]},
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "copy_id": fact["id"],
                                    "side": "front",
                                    "sha256": "hash",
                                }
                            ),
                        }
                    ]
                },
            },
        ]
        cards.append(
            {
                **fact,
                "expected_version": 3,
                "photo_sha256": "hash",
                "human_question": "Question ?",
                "reason": "Priority",
                "photo_observations": ["Visible"],
                "possible_answers": ["Indéterminé"],
                "unknowns": ["Verso"],
            }
        )
    answer = {"cards": cards, "album_id": "a", "route": [c["id"] for c in facts]}
    hashes = {c["id"]: "hash" for c in facts}
    assert all(assess(answer, calls, facts, "a", hashes).values())
    cards[0]["photo_sha256"] = "different"
    cards[1]["expected_version"] = 2
    calls[1]["result"]["content"][0]["text"] = json.dumps({"items": facts[:-1]})
    checks = assess(answer, calls, facts, "a", hashes)
    assert not checks["photo_receipts_match"]
    assert not checks["identity_version_location"]
    assert not checks["entire_album_read"]


def test_route_labels_keep_order_and_reject_ambiguous_or_unknown_ids():
    a = "11111111-1111-4111-8111-111111111111"
    b = "22222222-2222-4222-8222-222222222222"
    unknown = "00000000-0000-0000-0000-000000000000"
    assert route_ids(["Page 7 — " + a, "Page 13 — " + b], {a, b}) == [a, b]
    assert route_ids(["Page 13 — " + b, "Page 7 — " + a], {a, b}) == [b, a]
    ambiguous = a + " ou " + b
    assert route_ids([ambiguous, unknown, a, a], {a, b}) == [ambiguous, unknown, a, a]
