"""The chat's ``knowledge`` tool: guide sections and business rules, no commands (decision 0035)."""

import shutil
import subprocess

import pytest

from pokeprice import assistant_knowledge as knowledge_module
from pokeprice.agent import AgentError
from pokeprice.assistant_knowledge import OPERATOR, ROOT, TOPICS, knowledge
from pokeprice.assistant_tools import call

COMMAND_WORDS = ("pokeprice-manage", "--apply", "--data", "/srv/", "/opt/", "sudo", "uv run", "```")


@pytest.mark.parametrize("name", list(TOPICS))
def test_every_topic_reads_its_section_without_commands(name):
    answer = call(None, "knowledge", {"topic": name})
    assert answer["topic"] == name and answer["title"] == TOPICS[name].title
    assert len(answer["text"]) > 150, "La section est vide : son titre a-t-il changé dans le guide ?"
    assert len(answer["text"]) <= knowledge_module.MAX_CHARS
    assert not OPERATOR.search(answer["text"])
    for word in COMMAND_WORDS:
        assert word not in answer["text"]


def test_the_rules_asked_for_are_there():
    assert {"plancher", "derogation", "autonomie", "lots", "ordre-du-classeur"} <= set(TOPICS)
    assert "85 %" in knowledge(None, {"topic": "plancher"})["text"]
    assert "remboursement" in knowledge(None, {"topic": "autonomie"})["text"]
    assert "pochette" in knowledge(None, {"topic": "ordre-du-classeur"})["text"]


def test_a_section_is_read_at_call_time_and_filtered(tmp_path, monkeypatch):
    guide = tmp_path / "docs" / "APP.md"
    guide.parent.mkdir()
    guide.write_text(
        "# Guide\n\n## Exporter\n\n"
        "Le menu **Exporter** donne un [tableau CSV](COMMANDES.md#csv). "
        "Sur le serveur, lancez `pokeprice-manage --data /srv/pokeprice/inventory export`.\n\n"
        "- Une ligne utile.\n- `--apply` écrit dans la base.\n\n"
        "```bash\nsudo -u pokeprice uv run python -m pokeprice.manage backup\n```\n\n"
        "<!-- note interne -->\n"
        "| Format | Commande |\n|---|---|\n| CSV | le menu |\n| JSON | `scripts/export.py` |\n\n"
        "Un détail (variable `POKEPRICE_EXPORT`) reste lisible.\n\n"
        "### Sous-partie\n\nAussi lue.\n\n## Sauvegarder\n\nPas lue.\n",
        encoding="utf-8")
    monkeypatch.setattr(knowledge_module, "ROOT", tmp_path)
    text = knowledge(None, {"topic": "exporter"})["text"]
    assert text.splitlines() == [
        "Le menu Exporter donne un tableau CSV.",
        "- Une ligne utile.",
        "| Format | Commande |",
        "| CSV | le menu |",
        "Un détail reste lisible.",
        "Sous-partie :",
        "Aussi lue.",
    ]


def test_bold_label_sections_of_a_decision_record():
    text = knowledge(None, {"topic": "autonomie"})["text"]
    assert text.startswith("Option 3.")
    assert "Conséquences" not in text


@pytest.mark.parametrize("query", ["", "   ", "météo", "rm -rf"])
def test_an_unknown_topic_lists_the_topics(query):
    answer = call(None, "knowledge", {"topic": query} if query else {})
    assert [t["topic"] for t in answer["topics"]] == list(TOPICS)
    assert ("unknown_topic" in answer) == bool(query.strip())


@pytest.mark.parametrize("query, name", [
    ("Plancher", "plancher"), ("plancher anti-bradage", "plancher"), ("Le plancher anti-bradage", "plancher"),
    ("dérogation", "derogation"), ("ordre du classeur", "ordre-du-classeur"), ("à toi", "brief"),
])
def test_topics_are_found_by_name_alias_or_title(query, name):
    assert knowledge(None, {"topic": query})["topic"] == name


def test_arguments_are_strict():
    for arguments in ({"topic": "x" * 81}, {"topic": 3}, {"sujet": "plancher"}):
        with pytest.raises(AgentError) as error:
            call(None, "knowledge", arguments)
        assert error.value.code == "invalid_arguments"


def test_a_server_without_the_guides_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge_module, "ROOT", tmp_path)
    with pytest.raises(AgentError) as error:
        knowledge(None, {"topic": "plancher"})
    assert error.value.status == 503 and error.value.code == "knowledge_unavailable"


def test_the_sources_are_shipped_by_the_deployment():
    """deploy/oci-deploy.sh copies `git ls-files` to the server: each source must be tracked."""
    assert "git ls-files" in (ROOT / "deploy" / "oci-deploy.sh").read_text(encoding="utf-8")
    if not shutil.which("git") or not (ROOT / ".git").exists():
        pytest.skip("hors d'un dépôt Git")
    files = sorted({path for topic in TOPICS.values() for path, _ in topic.sources})
    tracked = subprocess.run(["git", "ls-files", "--", *files], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.split()
    assert tracked == files
