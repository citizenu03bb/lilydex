"""The management scripts as the page loads them, for the Node runtimes of the tests.

`index.html` is the reference: its script tags give the files and their order.
`app.js` may be split into several parts (`app.js`, then `app-*.js`); a runtime
that slices functions out of "the app script" gets the parts concatenated in
that order, written next to the other interface files so that a runtime
reading `components.js` or `messages/` beside its argument still finds them.
"""

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/pokeprice/web"
SCRIPT_TAG = re.compile(r'<script src="/assets/([\w.-]+\.js)"')
APP_PART = re.compile(r"app(-[\w-]+)?\.js")


def management_scripts():
    """The scripts of the management page, in the order of its script tags."""
    return SCRIPT_TAG.findall((WEB / "index.html").read_text())


def app_parts():
    """The parts of the management app script, in load order."""
    return [name for name in management_scripts() if APP_PART.fullmatch(name)]


def app_source(tmp_path):
    """A file holding the app parts concatenated, beside links to the other web files."""
    folder = tmp_path / "web"
    folder.mkdir()
    parts = app_parts()
    for entry in WEB.iterdir():
        if entry.name not in parts:
            (folder / entry.name).symlink_to(entry)
    (folder / "app.js").write_text("\n".join((WEB / name).read_text() for name in parts))
    return str(folder / "app.js")
