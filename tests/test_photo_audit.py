"""Photo audit scripts (docs/AUDIT-PHOTOS.md): crop fit, catalogue lookup, proposals."""

import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from pokeprice.inventory import Store

ROOT = Path(__file__).resolve().parents[1] / "scripts"


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


crops = script("audit_photo_crops")
identity = script("audit_photo_identity")


def binder_page(left=0.08, top=0.05, block=0.86):
    """A 3×3 block of yellow-framed cards filling only part of the photo."""
    page = Image.new("RGB", (900, 1200), (60, 60, 70))
    draw = ImageDraw.Draw(page)
    cw, ch = block / 3 * 0.94, block / 3 * 0.94 * 900 / 1200 * 1.4
    for r in range(3):
        for c in range(3):
            l, t = left + c * block / 3, top + r * ch * 1.06
            box = [l * 900, t * 1200, (l + cw) * 900, (t + ch) * 1200]
            draw.rectangle(box, fill=(225, 190, 40))
            draw.rectangle([box[0] + 14, box[1] + 14, box[2] - 14, box[3] - 14], fill=(90, 140, 200))
    return page


def test_grid_fit_finds_the_card_block_and_flags_cut_corner_cards():
    page = binder_page()
    boxes = crops.card_boxes(page)
    assert len(boxes) >= 6
    copies = [{"pos": p, "page": 1} for p in range(1, 10)]
    rows = crops.audit_page(page, copies, (3, 3, 0.02))
    coverage = {r["pos"]: r["coverage"] for r in rows}
    # The block is smaller than the photo: the centre card is kept, the outer corner is cut.
    assert coverage[5] > coverage[9]
    assert {r["level"] for r in rows} <= {"grave", "partielle", "légère", "ok"}
    assert crops.level(0.5) == "grave" and crops.level(0.99) == "ok"


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "inventory")
    with store.connect(write=True) as db:
        db.execute("INSERT INTO albums VALUES(?,?)", ("darkrai", "Darkrai"))
        db.execute(
            "INSERT INTO catalog_lookups VALUES(?,?,?,?)",
            ("set:fr:pl3", 1, json.dumps({"pl3-97": "Ouisticram"}), "2026-10-16"),
        )
    photo = Image.new("RGB", (900, 1270), (230, 200, 60))
    path = tmp_path / "card.jpg"
    photo.save(path)
    copy = store.create_copy(
        dict(name="Ouisticram", set_name="Aube Majestueuse", number="57/100", language="fr",
             catalog_id="dp5-57", hp=50, album_id="darkrai", page=14, position=1,
             identification_status="confirmed", foil=False, condition="EX",
             photo=store.save_photo(path.read_bytes())),
        "import", "Import",
    )
    return store, copy


DETAIL = {"id": "pl3-97", "localId": "97", "name": "Ouisticram", "hp": 50,
          "set": {"id": "pl3", "name": "Vainqueurs Suprêmes", "cardCount": {"official": 147}}}


def test_lookup_reads_the_cached_set_lists_only(store):
    db = identity.readonly(store[0].root)
    assert identity.lookup(db, "pl3-97") == {"fr": "Ouisticram", "en": None}


def test_sheets_label_the_recorded_identity(store, tmp_path):
    s, copy = store
    rows = tmp_path / "copies.json"
    rows.write_text(json.dumps([{"copy_id": copy["id"], "niveau": "grave"}]))
    copies = identity.load_copies(s.root, rows, ["grave"])
    assert copies[0]["number"] == "57/100"
    assert len(identity.sheets(copies, s.photos, tmp_path / "sheets")) == 1
    assert len(identity.strips(copies, s.photos, tmp_path / "strips")) == 1


def test_proposals_are_left_to_verify_and_applied_with_backup(store, tmp_path):
    s, copy = store
    decisions = [{"copy_id": copy["id"], "catalog_id": "pl3-97", "observation": "97/147 PV50"}]
    patches = identity.propose(decisions, s.root, tmp_path / "cache", get_json=lambda url: DETAIL)
    assert patches[0]["changes"] == {
        "number": "97/147", "catalog_id": "pl3-97", "set_name": "Vainqueurs Suprêmes",
        "identification_status": "review",
    }
    assert "À vérifier par le propriétaire" in patches[0]["reason"]
    # Dry run: a temporary copy changes, the collection does not.
    trial, done, skipped = identity.apply(patches, s.root)
    assert trial.root != s.root and not skipped and done[0][2] == {}
    with s.connect() as db:
        assert db.execute("SELECT catalog_id FROM copies").fetchone()[0] == "dp5-57"
    _, done, skipped = identity.apply(patches, s.root, write=True, backup_dir=tmp_path / "backups")
    assert not skipped and list((tmp_path / "backups").glob("collection-*.zip"))
    with s.connect() as db:
        row = db.execute("SELECT catalog_id, identification_status, version FROM copies").fetchone()
    assert tuple(row) == ("pl3-97", "review", copy["version"] + 1)
    # The same proposal again is refused: its expected version is outdated.
    _, _, skipped = identity.apply(patches, s.root)
    assert skipped
