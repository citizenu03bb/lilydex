"""Binder import (decision 0047): pages, pockets, resumable steps and the budget.

No real service: the reader, the catalogue and the checks are fakes.
"""

import hashlib
import io
import json

import pytest
from PIL import Image, ImageDraw

from pokeprice.binder_import import (
    CHUNK_BYTES,
    BinderImports,
    budget_from_env,
    copy_id_for,
)
from pokeprice.gemini_usage import record
from pokeprice.inventory import Conflict, Store

PRICING = {"models": {"gemini:gemini-3.8-flash": {"input": 1.0, "output": 1.0}}}


def page_photo(colors=None, size=(900, 1200)):
    """A 3×3 page: each pocket a flat colour, so each crop differs."""
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    w, h = size[0] // 3, size[1] // 3
    for index in range(9):
        r, c = divmod(index, 3)
        color = (colors or {}).get(index + 1, (20 * index, 100, 200 - 15 * index))
        draw.rectangle([c * w + 10, r * h + 10, (c + 1) * w - 10, (r + 1) * h - 10], fill=color)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=92)
    return out.getvalue()


class Response:
    """What google-genai returns, as far as the meter reads it."""

    class usage_metadata:  # noqa: N801 - mirrors the SDK attribute.
        prompt_token_count = 400_000
        candidates_token_count = 50_000
        thoughts_token_count = 50_000


class Reader:
    """Card names by call order; ``fail`` raises transient errors, ``blank`` no front."""

    def __init__(self, names=None, fail=0, blank=()):
        self.names, self.fail, self.blank, self.calls = list(names or []), fail, set(blank), 0

    def __call__(self, photo):
        self.calls += 1
        record("gemini-3.8-flash", Response)
        if self.fail:
            self.fail -= 1
            raise RuntimeError("Lecture Gemini indisponible ou réponse invalide.")
        if self.calls in self.blank:
            raise ValueError("Le recto d’une seule carte doit être lisible.")
        name = self.names.pop(0) if self.names else f"Carte {self.calls}"
        observation = {"name": name, "number": "58/127", "language": "fr", "hp": 60,
                       "readable_front": True, "flaws": "", "notes": "", "stamp_text": ""}
        return observation, json.dumps(observation)


def lookup(query):
    if query["name"] == "Pikachu":
        return {"exact": True, "message": "", "candidates": [{
            "id": "ex13-78", "name": "Pikachu", "set_name": "Fantômes Holon",
            "number": "58/127", "language": "fr", "hp": 60, "printed_name": "Pikachu",
            "printed_number": "58/127", "image": "", "source": "", "pricing": None,
            "variants": None}]}
    return {"exact": False, "message": "", "candidates": []}


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "inventory")


def service(store, reader=None, **options):
    options.setdefault("pricing", PRICING)
    options.setdefault("eur_per_usd", 1.0)
    options.setdefault("default_budget_eur", 100.0)
    return BinderImports(store, reader=reader or Reader(), lookup=lookup, **options)


def upload(imports, import_id, page, data, position=0):
    sha = hashlib.sha256(data).hexdigest()
    state = imports.begin_upload(import_id, page, position, len(data), sha)
    while not state["done"]:
        chunk = data[state["received"]:state["received"] + CHUNK_BYTES]
        state = imports.put_chunk(state["id"], state["received"], chunk)
    return state


def copies(store):
    with store.connect() as db:
        return [dict(r) for r in db.execute(
            "SELECT id,name,set_name,number,catalog_id,identification_status,page,position,"
            "source_key,photo,version FROM copies ORDER BY page,position")]


def test_a_page_becomes_nine_copies_to_check_in_binder_order(store):
    imports = service(store, Reader(["Pikachu"]))
    item = imports.create("admin", album_name="Classeur bleu")
    upload(imports, item["id"], 1, page_photo())
    imports.run_until_idle()
    result = imports.get(item["id"])
    assert result["progress"] == {"pockets": 9, "settled": 9, "pages_done": 1}
    found = copies(store)
    assert [(c["page"], c["position"]) for c in found] == [(1, p) for p in range(1, 10)]
    assert {c["identification_status"] for c in found} == {"review"}
    # One exact edition is kept, never confirmed.
    assert found[0]["catalog_id"] == "ex13-78" and found[0]["set_name"] == "Fantômes Holon"
    assert found[1]["catalog_id"] is None
    assert found[0]["id"] == copy_id_for(item["id"], 1, 1)
    # Each pocket is its own photo, cut from the page.
    assert len({c["photo"] for c in found}) == 9


def test_steps_run_again_without_duplicates(store):
    moment = [0.0]
    imports = service(store, clock=lambda: moment[0])
    item = imports.create("admin", album_name="A")
    upload(imports, item["id"], 1, page_photo())
    imports.run_until_idle(limit=6)  # Interrupted mid-page, as by a restart.
    # A new process, the same state: a lost update sends the pocket back a step.
    with imports.connect(write=True) as db:
        db.execute("UPDATE pockets SET status='read' WHERE position=1")
    restarted = service(store, clock=lambda: moment[0])
    assert restarted.step() is None  # The dead process's lease still runs.
    moment[0] += 121
    restarted.run_until_idle()
    assert len(copies(store)) == 9


def test_resumable_upload_survives_a_dropped_connection(store):
    imports = service(store)
    item = imports.create("admin", album_name="A")
    data = page_photo()
    sha = hashlib.sha256(data).hexdigest()
    state = imports.begin_upload(item["id"], 1, 0, len(data), sha)
    state = imports.put_chunk(state["id"], 0, data[:1000])
    # The phone drops; announcing the same photo again resumes at the offset.
    again = imports.begin_upload(item["id"], 1, 0, len(data), sha)
    assert again == {**state, "done": False} and again["received"] == 1000
    # A chunk sent twice is ignored, the offset says where to go on.
    assert imports.put_chunk(state["id"], 0, data[:1000])["received"] == 1000
    final = imports.put_chunk(state["id"], 1000, data[1000:])
    assert final["done"]
    assert imports.get(item["id"])["pages"][0]["status"] == "received"


def test_altered_upload_restarts(store):
    imports = service(store)
    item = imports.create("admin", album_name="A")
    data = page_photo()
    state = imports.begin_upload(item["id"], 1, 0, len(data), "0" * 64)
    with pytest.raises(ValueError, match="altérée"):
        imports.put_chunk(state["id"], 0, data)
    assert imports.begin_upload(item["id"], 1, 0, len(data), "0" * 64)["received"] == 0


def test_gemini_errors_wait_and_resume_on_their_own(store):
    moment = [1000.0]
    reader = Reader(fail=2)
    imports = service(store, reader, clock=lambda: moment[0])
    item = imports.create("admin", album_name="A")
    upload(imports, item["id"], 1, page_photo())
    imports.run_until_idle()
    state = imports.get(item["id"])
    assert state["retry_at"] == 1060 and "nouvel essai" in state["note"]
    assert copies(store) == []
    moment[0] = 1061
    imports.run_until_idle()  # Fails once more, waits twice as long.
    assert imports.get(item["id"])["retry_at"] == 1061 + 120
    moment[0] = 2000
    imports.run_until_idle()
    assert imports.get(item["id"])["progress"]["settled"] == 9
    assert len(copies(store)) == 9


def test_a_pocket_that_keeps_failing_alone_is_retaken(store):
    moment = [0.0]

    class Flaky(Reader):
        def __call__(self, photo):
            # The first pocket's photo always fails; the others read.
            if photo == self.bad:
                record("gemini-3.8-flash", Response)
                raise RuntimeError("Lecture Gemini indisponible.")
            return super().__call__(photo)

    reader = Flaky()
    imports = service(store, reader, clock=lambda: moment[0])
    item = imports.create("admin", album_name="A")
    upload(imports, item["id"], 1, page_photo())
    imports.run_until_idle(limit=1)  # Cut.
    with imports.connect() as db:
        first = db.execute("SELECT reading_json,photo FROM pockets WHERE position=1").fetchone()
    from pokeprice.photo_processing import prepare_photo

    reader.bad = prepare_photo((store.photos / first["photo"]).read_bytes())[0]
    for _ in range(40):
        moment[0] += 3600
        imports.run_until_idle()
    pockets = imports.get(item["id"])["pages"][0]["pockets"]
    assert pockets[0]["status"] == "failed"
    assert [p["status"] for p in pockets[1:]] == ["checked"] * 8


def test_unreadable_pocket_waits_for_a_retake_or_is_marked_empty(store):
    imports = service(store, Reader(blank={9}))
    item = imports.create("admin", album_name="A")
    upload(imports, item["id"], 1, page_photo())
    imports.run_until_idle()
    page = imports.get(item["id"])["pages"][0]
    assert page["pockets"][8]["status"] == "retake" and page["status"] == "done"
    assert len(copies(store)) == 8
    imports.mark_empty(item["id"], 1, 9, "admin")
    assert imports.get(item["id"])["pages"][0]["pockets"][8]["status"] == "empty"


def test_retaking_one_card_replaces_its_photo_and_reading(store):
    imports = service(store, Reader(["Mew", *["X"] * 8, "Pikachu"]))
    item = imports.create("admin", album_name="A")
    upload(imports, item["id"], 1, page_photo())
    imports.run_until_idle()
    before = copies(store)[0]
    card = page_photo({1: (250, 10, 10)})
    upload(imports, item["id"], 1, card, position=1)
    imports.run_until_idle()
    after = copies(store)
    assert len(after) == 9
    assert after[0]["id"] == before["id"] and after[0]["photo"] != before["photo"]
    assert after[0]["name"] == "Pikachu" and after[0]["catalog_id"] == "ex13-78"


def test_a_retake_keeps_what_a_person_changed(store):
    imports = service(store, Reader(["Mew", *["X"] * 8, "Pikachu"]))
    item = imports.create("admin", album_name="A")
    upload(imports, item["id"], 1, page_photo())
    imports.run_until_idle()
    first = copies(store)[0]
    store.patch(first["id"], {"name": "Mew ex"}, first["version"], "lily", "Corrigé")
    upload(imports, item["id"], 1, page_photo({1: (1, 200, 1)}), position=1)
    imports.run_until_idle()
    after = copies(store)[0]
    assert after["name"] == "Mew ex" and after["photo"] != first["photo"]


def test_budget_stops_the_import_and_the_admin_decides(store):
    sent = []
    # Each fake call costs 0.5 € (400 000 + 100 000 tokens at 1 $ per million).
    imports = service(store, notify=lambda title, body: sent.append(title))
    item = imports.create("admin", album_name="A", budget_eur=1.0)
    upload(imports, item["id"], 1, page_photo())
    imports.run_until_idle()
    state = imports.get(item["id"])
    assert state["status"] == "paused_budget"
    assert state["cost"]["eur"] == 1.0 and state["cost"]["calls"] == 2
    assert len(copies(store)) == 2
    assert sent == ["Import : budget Gemini atteint (1,00 €)"]
    imports.run_until_idle()  # Nothing moves without the admin.
    assert len(copies(store)) == 2
    imports.continue_budget(item["id"], "admin")
    imports.run_until_idle()
    state = imports.get(item["id"])
    assert state["budget_eur"] == 2.0 and state["status"] == "paused_budget"
    assert len(copies(store)) == 4 and len(sent) == 2
    assert state["pages"][0]["cost_eur"] == 2.0


def test_checks_are_metered_and_the_review_runs_per_page(store):
    checked, reviewed = [], []

    def checks(copy_id):
        record("gemini-3.8-flash", Response)
        checked.append(copy_id)

    def review(ids, apply):
        reviewed.append((list(ids), apply))
        return {"run_id": None, "confirmed": [{"copy_id": ids[0]}], "photo_requests": [],
                "skipped": [{"copy_id": i} for i in ids[1:]]}

    imports = service(store, checks=checks, review=review, apply=lambda: False)
    item = imports.create("admin", album_name="A", budget_eur=50)
    upload(imports, item["id"], 1, page_photo())
    imports.run_until_idle()
    state = imports.get(item["id"])
    assert len(checked) == 9 and state["cost"]["calls"] == 18
    assert reviewed == [([c["id"] for c in copies(store)], False)]
    assert state["pages"][0]["review"]["applied"] is False
    assert state["pages"][0]["review"]["would_confirm"] == [copies(store)[0]["id"]]


def test_a_card_per_photo_import(store):
    imports = service(store, Reader(["Pikachu", "Mew"]))
    item = imports.create("admin", album_name="Cartes seules", grid="single")
    upload(imports, item["id"], 1, page_photo())
    upload(imports, item["id"], 2, page_photo())
    imports.run_until_idle()
    assert [(c["page"], c["position"], c["name"]) for c in copies(store)] == [
        (1, 1, "Pikachu"), (2, 1, "Mew")]


def test_one_worker_at_a_time(store):
    first, second = service(store), service(store)
    item = first.create("admin", album_name="A")
    upload(first, item["id"], 1, page_photo())
    assert first.step() is not None
    assert second.step() is None
    first.release()
    assert second.step() is not None


def test_places_and_photos_are_checked(store):
    imports = service(store)
    item = imports.create("admin", album_name="A")
    with pytest.raises(Conflict, match="page entière"):
        imports.begin_upload(item["id"], 1, 3, 10, "a" * 64)
    with pytest.raises(ValueError, match="Pochette invalide"):
        imports.begin_upload(item["id"], 1, 10, 10, "a" * 64)
    with pytest.raises(ValueError, match="JPEG"):
        imports.add_photo(item["id"], 1, 0, b"not a photo")
    with pytest.raises(ValueError, match="Grille"):
        imports.create("admin", album_name="A", grid="5x5")
    imports.close(item["id"], "admin")
    with pytest.raises(Conflict, match="clos"):
        imports.begin_upload(item["id"], 1, 0, 10, "a" * 64)


def test_budget_variable():
    assert budget_from_env({}) == 3.0
    assert budget_from_env({"POKEPRICE_IMPORT_BUDGET_EUR": "4,5"}) == 4.5
    with pytest.raises(ValueError):
        budget_from_env({"POKEPRICE_IMPORT_BUDGET_EUR": "-1"})


def test_raw_page_stays_out_of_the_photo_reserve(store):
    imports = service(store)
    item = imports.create("admin", album_name="A")
    data = page_photo()
    upload(imports, item["id"], 1, data)
    name = hashlib.sha256(data).hexdigest() + ".jpg"
    assert not (store.photos / name).exists()
    assert list(imports.uploads_dir.glob("page-*.bin"))
    imports.run_until_idle()
    assert not list(imports.uploads_dir.glob("page-*"))
    page = imports.get(item["id"])["pages"][0]
    assert (store.photos / page["photo"]).exists()


def test_retaking_a_page_rereads_it_onto_the_same_copies(store):
    imports = service(store)
    item = imports.create("admin", album_name="A")
    upload(imports, item["id"], 1, page_photo())
    imports.run_until_idle()
    before = copies(store)
    upload(imports, item["id"], 1, page_photo({5: (0, 0, 0)}))
    imports.run_until_idle()
    after = copies(store)
    assert [c["id"] for c in after] == [c["id"] for c in before]
    assert after[4]["photo"] != before[4]["photo"]
    assert imports.get(item["id"])["pages"][0]["status"] == "done"


def test_review_apply_setting_is_admin_only_and_logged(store):
    from pokeprice.agent_review import review_apply, set_review_apply
    from pokeprice.floor_requests import HumanOnly
    from pokeprice.passwords import password_hash

    with store.connect(write=True) as db:
        db.execute(
            "INSERT INTO users(id,username,password_hash,role,created_at) VALUES(?,?,?,?,?)",
            ("u1", "admin", password_hash("x" * 12), "admin", "2026-11-20"),
        )
        db.execute(
            "INSERT INTO users(id,username,password_hash,role,created_at) VALUES(?,?,?,?,?)",
            ("u2", "lily", password_hash("x" * 12), "editor", "2026-11-20"),
        )
    assert review_apply(store) is False
    with pytest.raises(HumanOnly):
        set_review_apply(store, True, "lily", "porte passée")
    with pytest.raises(ValueError, match="aveugle"):
        set_review_apply(store, True, "admin", "")
    assert set_review_apply(store, True, "admin", "60 cartes, 0 variante fausse") == {
        "apply": True, "previous": False}
    assert review_apply(store) is True
    set_review_apply(store, False, "admin", "")
    assert review_apply(store) is False
    with store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM events WHERE kind='agent-review-apply'").fetchone()[0] == 2


def test_command_line_import_uses_the_same_service(store, tmp_path):
    from argparse import Namespace

    from pokeprice.manage import binder_import
    from pokeprice.passwords import password_hash

    with store.connect(write=True) as db:
        db.execute(
            "INSERT INTO users(id,username,password_hash,role,created_at) VALUES(?,?,?,?,?)",
            ("u1", "admin", password_hash("x" * 12), "admin", "2026-11-20"),
        )
    photos = []
    for index in (1, 2):
        path = tmp_path / f"page{index}.jpg"
        path.write_bytes(page_photo({1: (index * 40, 0, 0)}))
        photos.append(str(path))
    args = Namespace(actor="admin", import_id=None, album="Classeur rouge", grid="3x3",
                     budget_eur=None, photos=photos, first_page=3, no_run=False)
    result = binder_import(store, args, imports=service(store))
    assert result["progress"] == {"pockets": 18, "settled": 18, "pages_done": 2}
    assert [p["page"] for p in result["pages"]] == [3, 4]
    with pytest.raises(ValueError, match="administrateur"):
        binder_import(store, Namespace(**{**vars(args), "actor": "nobody"}), imports=service(store))


def test_worker_stops_after_its_step_and_releases_the_lease(store):
    import threading

    from pokeprice.binder_worker import run_worker

    imports = service(store)
    item = imports.create("admin", album_name="A")
    upload(imports, item["id"], 1, page_photo())
    stop = threading.Event()
    original = imports.step

    def step():
        work = original()
        if work is None:
            stop.set()
        return work

    imports.step = step
    thread = threading.Thread(target=run_worker, args=(imports, stop, 0.01))
    thread.start()
    thread.join(10)
    assert not thread.is_alive()
    assert imports.get(item["id"])["progress"]["pages_done"] == 1
    assert service(store).claim()


def test_meter_counts_thinking_as_output_and_nothing_outside_a_block():
    from pokeprice.gemini_usage import metering

    record("gemini-3.8-flash", Response)  # Outside: dropped.
    with metering() as calls:
        record("gemini-3.8-flash", Response)
        record("gemini-3.8-flash", object())
    assert calls == [
        {"model": "gemini:gemini-3.8-flash", "input_tokens": 400_000, "output_tokens": 100_000},
        {"model": "gemini:gemini-3.8-flash", "input_tokens": 0, "output_tokens": 0},
    ]
