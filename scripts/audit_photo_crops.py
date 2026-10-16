"""Photo crops of imported binder pages: audit, then recrop from the original page.

The import cut each page into uniform thirds; the 3×3 card block often fills only
83–91 % of the photo, so corner cards were cut. ``audit`` finds the yellow card
frames, fits a regular 3×3 grid and measures, for every copy, the share of the
real card inside its stored photo (``coverage``). The database is opened
read-only. ``recrop`` crops the fitted card box (plus margin) from the page,
through the app's photo path; nothing is written without ``--apply``.

    uv run --extra web python scripts/audit_photo_crops.py audit <out> --album darkrai
    uv run --extra web python scripts/audit_photo_crops.py recrop <out>/audit.json <out>/recrop \
        darkrai:18:7 [--apply [--validated]]

Apply only after ``pokeprice-manage backup`` and the owner's agreement. Without
``--validated`` the patch carries no photo-preparation evidence, whose fixed label
claims a human validation. See docs/AUDIT-PHOTOS.md.
"""

import argparse
import csv
import io
import json
import sqlite3
import statistics
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

from pokeprice.photo_processing import components_of, pixel_values
from pokeprice.slicer import normalize_orientation, slice_grid

W = 480
MARGIN = 0.10  # of the card size on each side, so the app's contour crop has room
# Calibrated by eye on the 14 October binders (see docs/AUDIT-PHOTOS.md).
LEVELS = ((0.80, "grave"), (0.93, "partielle"), (0.97, "légère"), (9, "ok"))
VARIANTS = [(False, 0), (True, 0), (False, 3), (True, 3), ("loose", 0), ("loose", 3), (True, 5)]


def yellow_mask(small, strict=False, erode=0):
    k = {True: 0.28, False: 0.36, "loose": 0.40}[strict]
    lo = 70 if strict == "loose" else 100
    mask = Image.new("L", small.size)
    mask.putdata(
        [
            255 if r > lo and g > lo - 5 and 0.90 < r / max(g, 1) < 1.40 and b < (r + g) * k else 0
            for r, g, b in pixel_values(small)
        ]
    )
    mask = mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    return mask.filter(ImageFilter.MinFilter(erode)) if erode else mask


def card_boxes(page):
    """Boxes (fractions of the page, then fill ratio) of yellow-framed card shapes."""
    small = page.copy()
    small.thumbnail((W, W * 2))
    small = small.filter(ImageFilter.MedianFilter(3))
    w, h = small.size
    out = []
    for strict, erode in VARIANTS:
        grow = erode // 2
        for count, (l, t, r, b), _ in components_of(yellow_mask(small, strict, erode)):
            l, t, r, b = l - grow, t - grow, r + grow, b + grow
            bw, bh = r - l, b - t
            if not (w * 0.15 <= bw <= w * 0.40 and h * 0.12 <= bh <= h * 0.40):
                continue
            if not 0.55 <= bw / bh <= 0.85:
                continue
            box = (l / w, t / h, r / w, b / h, count / (bw * bh))
            # The same card found by another variant: keep the first.
            if any(
                abs((o[0] + o[2]) - (box[0] + box[2])) < 0.05
                and abs((o[1] + o[3]) - (box[1] + box[3])) < 0.05
                for o in out
            ):
                continue
            out.append(box)
    return out


def clusters(values, gap):
    values = sorted(values)
    groups = [[values[0]]]
    for v in values[1:]:
        if v - groups[-1][-1] < gap:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [statistics.mean(g) for g in groups]


def fit_axis(centres, size, n=3):
    """Centres of the n slots along one axis from detected card centres, pitch, fit count, residual."""
    cs = clusters(centres, size * 0.5)
    pitches = [b - a for a, b in zip(cs, cs[1:]) if size * 0.95 < b - a < size * 1.4]
    pitch = statistics.median(pitches) if pitches else size * 1.06
    uniform = [(i + 0.5) / n for i in range(n)]
    best = None
    for offset in range(-1, n):
        valid = [
            (i, c)
            for i, c in ((offset + round((c - cs[0]) / pitch), c) for c in cs)
            if 0 <= i < n
        ]
        if not valid:
            continue
        a = statistics.mean(c - i * pitch for i, c in valid)
        # Clusters left outside belong to the neighbouring page.
        cost = sum(abs(a + i * pitch - uniform[i]) for i in range(n)) + 0.5 * (len(cs) - len(valid))
        if best is None or cost < best[0]:
            best = (cost, a, valid)
    _, a, valid = best
    residual = max(abs(a + i * pitch - c) for i, c in valid)
    return [a + i * pitch for i in range(n)], pitch, len(valid), residual


def overlap(a, b):
    w = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return w * h


def level(coverage):
    return next(name for limit, name in LEVELS if coverage < limit)


def page_path(pages_root, album_name, filename):
    return Path(pages_root).expanduser() / f"Pokedex - {album_name}" / filename


def audit_page(page, copies, rows_cols_inset, photos=None):
    """Coverage of each copy's stored crop by the card fitted on this page."""
    nr, nc, inset = rows_cols_inset
    cells = dict(slice_grid(page, nr, nc, inset))
    boxes = card_boxes(page)
    fitted = None
    if len(boxes) >= 2:
        cw = statistics.median(b[2] - b[0] for b in boxes)
        ch = statistics.median(b[3] - b[1] for b in boxes)
        xs, _, nx, rx = fit_axis([(b[0] + b[2]) / 2 for b in boxes], cw, nc)
        ys, _, ny, ry = fit_axis([(b[1] + b[3]) / 2 for b in boxes], ch, nr)
        fitted = (xs, ys, cw, ch, nx, ny, max(rx, ry))
    rows = []
    for copy in sorted(copies, key=lambda c: c["pos"]):
        p = copy["pos"]
        r_, c_ = divmod(p - 1, nc)
        cw_, ch_ = 1 / nc, 1 / nr
        cell = (
            c_ * cw_ + cw_ * inset,
            r_ * ch_ + ch_ * inset,
            (c_ + 1) * cw_ - cw_ * inset,
            (r_ + 1) * ch_ - ch_ * inset,
        )
        row = dict(copy, detected=len(boxes))
        if photos is not None and copy.get("photo"):
            crop = cells[p].convert("RGB")
            crop.thumbnail((400, 560))
            with Image.open(Path(photos) / copy["photo"]) as stored:
                stored = stored.convert("RGB")
            row["stored_is_uniform_crop"] = stored.size == crop.size and (
                max(ImageStat.Stat(ImageChops.difference(stored, crop)).mean) < 6
            )
        if fitted:
            xs, ys, cw, ch, nx, ny, resid = fitted
            card = (xs[c_] - cw / 2, ys[r_] - ch / 2, xs[c_] + cw / 2, ys[r_] + ch / 2)
            coverage = overlap(card, cell) / (cw * ch)
            row.update(
                coverage=round(coverage, 3),
                level=level(coverage),
                card_box=[round(v, 4) for v in card],
                card_outside_photo=round(max(0, -card[0], -card[1], card[2] - 1, card[3] - 1), 3),
                dx=round((xs[c_] - (cell[0] + cell[2]) / 2) / cw_, 3),
                dy=round((ys[r_] - (cell[1] + cell[3]) / 2) / ch_, 3),
                fit_cols=nx,
                fit_rows=ny,
                resid=round(resid, 3),
            )
        rows.append(row)
    return rows


def audit(args):
    data = Path(args.data)
    out = Path(args.output)
    (out / "pages").mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(f"file:{data / 'collection.sqlite3'}?mode=ro", uri=True)
    marks = ",".join("?" * len(args.album))
    pages = {}
    for cid, album, aname, page, pos, name, number, status, photo, version, raw in db.execute(
        "SELECT cp.id, cp.album_id, a.name, cp.page, cp.position, cp.name, cp.number, "
        "cp.identification_status, cp.photo, cp.version, s.raw_json "
        "FROM copies cp JOIN albums a ON a.id=cp.album_id JOIN sources s ON s.copy_id=cp.id "
        f"WHERE cp.deleted_at='' AND cp.album_id IN ({marks})",
        args.album,
    ):
        r = json.loads(raw)
        key = (album, aname, r["Fichier_Image"], r["Rotation"],
               r["Grille_Lignes"], r["Grille_Colonnes"], r["Marge_Decoupe"])
        pages.setdefault(key, []).append(
            dict(album=aname, page=page, pos=pos, name=name, number=number, status=status,
                 id=cid, version=version, file=r["Fichier_Image"], photo=photo)
        )
    rows = []
    for (album, aname, fn, rot, nr, nc, inset), copies in sorted(
        pages.items(), key=lambda kv: (kv[0][0], kv[1][0]["page"])
    ):
        with Image.open(page_path(args.pages_root, aname, fn)) as im:
            page = normalize_orientation(im, rot).convert("RGB")
        found = audit_page(page, copies, (nr, nc, inset), data / "photos")
        small = page.copy()
        small.thumbnail((W, W * 2))
        draw = ImageDraw.Draw(small)
        for row in found:
            if "card_box" in row:
                l, t, r, b = row["card_box"]
                draw.rectangle(
                    [l * small.width, t * small.height, r * small.width, b * small.height],
                    outline="lime" if row["coverage"] >= 0.95 else "red",
                    width=2,
                )
                draw.text((l * small.width + 4, t * small.height + 4),
                          f"{row['pos']} {row['coverage']:.2f}", fill="white")
        small.save(out / "pages" / f"{album}_p{copies[0]['page']:02d}.jpg")
        rows += found
        print(album, copies[0]["page"], found[0]["detected"], flush=True)
    for row in rows:
        row.pop("photo", None)
    (out / "audit.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    fields = ["level", "album", "page", "pos", "name", "number", "status", "coverage",
              "dx", "dy", "resid", "file", "id", "version", "card_box"]
    with open(out / "audit.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: r.get("coverage", 9)))
    print(len(rows), "exemplaires ->", out / "audit.csv")


def recrop_row(row, page):
    """Original and prepared photo bytes of the fitted card box, via the app's photo path."""
    from pokeprice.intake import normalize_photo
    from pokeprice.photo_processing import prepare_photo

    l, t, r, b = row["card_box"]
    mx, my = (r - l) * MARGIN, (b - t) * MARGIN
    box = [
        max(0, round((l - mx) * page.width)),
        max(0, round((t - my) * page.height)),
        min(page.width, round((r + mx) * page.width)),
        min(page.height, round((b + my) * page.height)),
    ]
    buf = io.BytesIO()
    page.crop(box).save(buf, format="JPEG", quality=95)
    original = normalize_photo(buf.getvalue())  # the app's "photo entière"
    prepared, details = prepare_photo(original)  # app defaults
    source = {"page_file": row["file"], "page_box_px": box, "fitted_card_box": row["card_box"],
              "margin": MARGIN, "previous_photo_coverage": row["coverage"]}
    return original, prepared, details, source


def recrop(args):
    from pokeprice.inventory import Conflict, Store

    rows = {f"{r['album']}:{r['page']}:{r['pos']}": r
            for r in json.loads(Path(args.audit).read_text())}
    keys = list(args.keys)
    for key in [k for k in keys if k.startswith("@")]:
        keys.remove(key)
        keys += [k for k in Path(key[1:]).read_text().splitlines() if k]
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    store = Store(args.data) if args.apply else None
    for key in keys:
        row = rows[key]
        with Image.open(page_path(args.pages_root, row["album"], row["file"])) as im:
            page = normalize_orientation(im, "auto").convert("RGB")
        original, prepared, details, source = recrop_row(row, page)
        stem = key.replace(" ", "_").replace(":", "_")
        (out / f"{stem}_original.jpg").write_bytes(original)
        (out / f"{stem}_prepared.jpg").write_bytes(prepared)
        print(key, row["name"], details["crop_source"], details["message"], flush=True)
        if not args.apply:
            continue
        changes = {"photo": store.save_photo(prepared), "photo_original": store.save_photo(original),
                   "condition_confirmed": False}
        evidence = None
        if args.validated:
            evidence = {"type": "photo-preparation", "side": "front",
                        "original_photo": changes["photo_original"],
                        "prepared_photo": changes["photo"],
                        "processing": details, "source_page": source}
        reason = (
            "Redécoupage depuis la photo de page d'origine : la découpe 3×3 uniforme de l'import "
            f"ne contenait pas la carte entière (couverture {row['coverage']:.0%}). "
            "Revérifier nom, numéro et PV sur la nouvelle photo."
        )
        try:
            result = store.patch(row["id"], changes, row["version"], "claude", reason, evidence=evidence)
        except Conflict as error:  # the copy changed since the audit
            print("  SKIPPED:", error)
            continue
        print("  patched -> version", result["version"], result["photo"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data", default="data/inventory")
    parser.add_argument("--pages-root", default="~/Downloads",
                        help="dossier contenant « Pokedex - <album> »")
    actions = parser.add_subparsers(dest="action", required=True)
    a = actions.add_parser("audit", help="mesurer la couverture des photos (lecture seule)")
    a.add_argument("output")
    a.add_argument("--album", action="append", required=True, help="identifiant d'album")
    r = actions.add_parser("recrop", help="redécouper depuis la page d'origine")
    r.add_argument("audit")
    r.add_argument("output")
    r.add_argument("keys", nargs="+", help="album:page:position, ou @fichier")
    r.add_argument("--apply", action="store_true")
    r.add_argument("--validated", action="store_true",
                   help="le propriétaire a validé les planches avant/après")
    args = parser.parse_args(argv)
    {"audit": audit, "recrop": recrop}[args.action](args)


if __name__ == "__main__":
    main()
