#!/usr/bin/env python3
"""Banc des prises de près en série (fiche 0048), sur une base temporaire.

Crée un classeur importé de N cartes « à vérifier » dont les demandes de
l'agent suivent la répartition de la vérification à l'aveugle (coins 68,
verso 18, reflet 18, recto 16 sur 105), avec des lecteurs factices : aucun
service réel, aucune clé. Puis, carte après carte dans l'ordre du classeur,
envoie la prise demandée par la route de la série et fait relire la carte,
comme le serveur le fait après la réponse.

Mesure le temps du serveur : la file, chaque envoi, chaque nouvelle lecture
(hors appel Gemini, factice ici). Le temps humain se lit à la fin d'une vraie
série, sur le téléphone (« s par carte, médiane »).

Usage : uv run --extra web --extra dev python scripts/bench_closeups.py [--cartes 100]
        [--servir 8797]   garde la base et sert l'application sur 127.0.0.1
"""

from __future__ import annotations

import argparse
import copy
import io
import json
import secrets
import statistics
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from fastapi.testclient import TestClient  # noqa: E402
from test_agent_review import ConditionReader, MATTE_WITH_REVERSE, ORIGINAL_HOLO  # noqa: E402
from test_edition_check import Reader as EditionReader  # noqa: E402
from test_edition_check import png, tcgdex  # noqa: E402
from test_pricing import CARD  # noqa: E402
from test_verification import Reader as FinishReader  # noqa: E402
from test_verification import reading  # noqa: E402

from pokeprice.webapp import create_app  # noqa: E402

# Requests of the blind check, out of 105 cards.
MIX = (("corner", 68), ("back", 18), ("holo", 18), ("front", 16))


def photo(seed, size=(1200, 1680)):
    """A card-sized JPEG, close to what a phone sends after resizing."""
    image = Image.new("RGB", size, ((seed * 37) % 255, (seed * 91) % 255, (seed * 53) % 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((90, 120, size[0] - 90, size[1] // 2), fill=(235, 224, 197))
    for line in range(0, size[1], 24):
        draw.line((0, line, size[0], line + seed % 17), fill=(seed % 255, 40, 90), width=3)
    output = io.BytesIO()
    image.save(output, "JPEG", quality=88)
    return output.getvalue()


class Stakes:
    """The value at stake and catalogue snapshot, per copy."""

    def __init__(self):
        self.by_copy = {}

    def __call__(self, copy_id, threshold):
        risk, snapshot, foil = self.by_copy.get(copy_id, (300, ORIGINAL_HOLO, None))
        hypotheses = [{"foil": False, "prudent_cents": risk}]
        if foil is not None:
            hypotheses.append({"foil": True, "prudent_cents": foil})
        return snapshot, {"risk_cents": risk, "threshold_cents": threshold,
                          "hypotheses": hypotheses}


def kinds(count):
    """The wanted view of each card, spread over the binder as in the blind check."""
    total = sum(n for _, n in MIX)
    out = []
    for index in range(count):
        point = (index * 41) % total  # A fixed shuffle, the same every run.
        for kind, n in MIX:
            if point < n:
                out.append(kind)
                break
            point -= n
    return out


def build(root, count):
    readers = {"finish": FinishReader(), "condition": ConditionReader(), "edition": EditionReader()}
    catalogue = copy.deepcopy(CARD)
    catalogue["variants"] = ORIGINAL_HOLO["variants"]
    app = create_app(
        root / "inventory",
        variant_reader=readers["finish"], condition_reader=readers["condition"],
        edition_reader=readers["edition"], edition_get_json=tcgdex,
        edition_fetch=lambda url: png(), auto_checks=False,
        price_fetch=lambda catalog_id, *_: {**catalogue, "id": catalog_id},
    )
    stakes = Stakes()
    app.state.agent_review.inputs = stakes
    password = secrets.token_urlsafe(18)
    (root / "identifiants.txt").write_text(f"admin\n{password}\n")
    client = TestClient(app)
    client.__enter__()
    client.post("/api/setup", json={"username": "admin", "password": password})
    album = client.post("/api/binder-imports", json={"album_name": "Classeur du banc"}).json()
    store, state = app.state.store, app.state
    wanted = kinds(count)
    for index, kind in enumerate(wanted):
        page, position = index // 9 + 1, index % 9 + 1
        card = store.create_copy(
            {"name": "Gourgeist", "number": "077/203", "set_name": "Evolving Skies",
             "language": "en", "hp": 120, "album_id": album["album_id"], "page": page,
             "position": position, "catalog_id": CARD["id"], "identification_status": "review",
             "source_key": f"binder:{album['id']}:{page}:{position}"},
            "system:import", "Import du classeur",
            evidence={"type": "binder-import", "exact_catalogue_match": True,
                      "chosen_catalog_id": CARD["id"],
                      "observation": {"name": "Gourgeist", "language": "en"}},
        )
        draft = client.post("/api/intake/photo", content=photo(index, (420, 588))).json()
        card = client.post(f"/api/copies/{card['id']}/photo-from-intake",
                           json={"token": draft["token"], "expected_version": card["version"],
                                 "side": "front"}).json()
        readers["finish"].result = reading()
        readers["condition"].quality = "adequate"
        readers["edition"].scores = {"swsh7-077": 0.91, "xy4-56": 0.62, "sm1-60": 0.55}
        if kind == "corner":
            readers["condition"].quality = "limited"
        elif kind == "holo":
            stakes.by_copy[card["id"]] = (300, MATTE_WITH_REVERSE, 4300)
            readers["finish"].result = reading(artwork="matte")
        elif kind == "back":
            # A card of value: decision 0022 wants its back.
            stakes.by_copy[card["id"]] = (1500, ORIGINAL_HOLO, None)
        elif kind == "front":
            readers["edition"].scores = {"swsh7-077": 0.80, "xy4-56": 0.78, "sm1-60": 0.5}
        state.variant_checks.evaluate_new_copy(
            card["id"], "system:import", lambda copy_id: stakes(copy_id, 1000))
        state.edition_checks.evaluate_new_copy(card["id"], "system:import")
        version = client.get(f"/api/copies/{card['id']}").json()["version"]
        state.conditions.evaluate(card["id"], version, "system:import")
    # The new photos read well: the readings the agent gets after each shot.
    readers["finish"].result = reading(artwork="matte", background_shine="not_visible")
    readers["condition"].quality = "adequate"
    readers["edition"].scores = {"swsh7-077": 0.91, "xy4-56": 0.62, "sm1-60": 0.55}
    return app, client, album


def run(client, app, album):
    started = time.perf_counter()
    response = client.post("/api/closeups/queue", json={"import_id": album["id"]})
    response.raise_for_status()
    queue = response.json()
    queue_seconds = time.perf_counter() - started
    views = {}
    for step in queue["steps"]:
        for view in step["views"]:
            views[view["view"]] = views.get(view["view"], 0) + 1
    shots, readings, per_card = [], [], []
    for number, step in enumerate(queue["steps"]):
        card_started = time.perf_counter()
        version = step["version"]
        for view in step["views"]:
            data = photo(1000 + number)
            begin = time.perf_counter()
            response = client.put(
                f"/api/closeups/{step['copy_id']}/shot?version={version}&view={view['view']}",
                content=data, headers={"Content-Type": "image/jpeg"},
            )
            response.raise_for_status()
            shots.append(time.perf_counter() - begin)
            version = response.json()["version"]
        begin = time.perf_counter()
        app.state.closeups.after_shot(step["copy_id"])
        readings.append(time.perf_counter() - begin)
        per_card.append(time.perf_counter() - card_started)
    results = client.post("/api/closeups/results", json={"import_id": album["id"]}).json()
    outcomes = {}
    for row in results:
        outcome = (row["verdict"] or {}).get("outcome", "pending")
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    after = client.post("/api/closeups/queue", json={"import_id": album["id"]}).json()
    return {
        "cartes": queue["cards"],
        "cartes_a_reprendre": len(queue["steps"]),
        "photos": queue["shots"],
        "vues": views,
        "file_s": round(queue_seconds, 2),
        "envoi_s_mediane": round(statistics.median(shots), 3) if shots else None,
        "relecture_s_mediane": round(statistics.median(readings), 3) if readings else None,
        "serveur_par_carte_s_mediane": round(statistics.median(per_card), 3) if per_card else None,
        "gestes_par_carte": round(queue["shots"] / max(1, len(queue["steps"])), 2),
        "verdicts": outcomes,
        "file_apres": {"a_reprendre": len(after["steps"]), "en_main": len(after["handed"])},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cartes", type=int, default=100)
    parser.add_argument("--servir", type=int, default=0,
                        help="sert la base sur 127.0.0.1:PORT au lieu de mesurer")
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="banc-prises-"))
    app, client, album = build(root, args.cartes)
    if args.servir:
        import threading

        import uvicorn

        # The fake app runs no background checks: read again after each shot here.
        closeups = app.state.closeups
        record = closeups.record_shot

        def record_then_read(copy_id, *rest):
            record(copy_id, *rest)
            threading.Timer(0.2, closeups.after_shot, (copy_id,)).start()

        closeups.record_shot = record_then_read
        print(f"Base : {root} ; identifiants dans {root / 'identifiants.txt'}", flush=True)
        uvicorn.run(app, host="127.0.0.1", port=args.servir, log_level="warning")
        return
    print(json.dumps(run(client, app, album), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
