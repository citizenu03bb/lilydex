"""Every management dialog exposes its visible title as its accessible name."""

import json
import re
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path

import pytest


class DialogNames(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.stack, self.dialogs = [], []
        self.ids = defaultdict(list)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        hidden = ("hidden" in attrs or attrs.get("aria-hidden") == "true"
                  or any(node["hidden"] for node in self.stack))
        node = {"tag": tag, "attrs": attrs, "hidden": hidden, "text": ""}
        if "id" in attrs:
            self.ids[attrs["id"]].append(node)
        if tag == "dialog":
            self.dialogs.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        for node in self.stack:
            node["text"] += data


@pytest.mark.parametrize("language", ["fr", "en"])
def test_each_management_dialog_has_a_unique_nonempty_visible_title(language):
    web = Path(__file__).resolve().parents[1] / "src/pokeprice/web"
    words = json.loads((web / "messages" / f"{language}.json").read_text())
    page = re.sub(r"\{\{t:([\w.]+)\}\}", lambda m: words[m[1]], (web / "index.html").read_text())
    parsed = DialogNames()
    parsed.feed(page)
    assert parsed.dialogs
    for dialog in parsed.dialogs:
        attrs = dialog["attrs"]
        targets = attrs.get("aria-labelledby", "").split()
        assert targets, attrs.get("id")
        for target in targets:
            [title] = parsed.ids[target]
            assert title["text"].strip(), target
            assert not title["hidden"], target
