"""What the management chat may explain, read from the repository's guides (decision 0035).

The ``knowledge`` tool returns, on demand, one section of the app guide
(``docs/APP.md``) or one business rule from the skills and decision records.
Nothing is copied: ``TOPICS`` maps a stable topic name to a file and a section
title, and the section is read at call time, so the answer follows the guide.

Only explanations leave: fenced code, HTML comments and images are dropped,
then every sentence that names an operator command or a server detail
(``pokeprice-manage``, a ``--flag``, a server path, a script, an environment
variable, an API route…) is removed. Lily acts through the app, never through
a terminal.

The files are read from the source tree the package runs from: the server
runs ``/opt/pokeprice``, a copy of the Git-tracked files with an editable
install (``deploy/oci-deploy.sh``). A wheel install has no ``docs/`` and the
tool then answers 503 ``knowledge_unavailable`` (decision 0035).
"""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .agent import AgentError

ROOT = Path(__file__).resolve().parents[2]
MAX_CHARS = 4000

APP = "docs/APP.md"
AUTONOMY = "skills/pokeprice-autonome/SKILL.md"
LOTS = "skills/pokeprice-lots/SKILL.md"
D0021 = "docs/decisions/0021-autonomie-maximale.md"
D0030 = "docs/decisions/0030-derogations-plancher.md"
TRIAGE = "docs/RESOLUTION_CARTES.md"


@dataclass(frozen=True)
class Topic:
    name: str
    title: str
    sources: tuple  # ((file, section title), ...)
    aliases: tuple = ()


def _topic(name, title, *sources, aliases=()):
    return Topic(name, title, tuple(sources), tuple(aliases))


TOPICS = {
    topic.name: topic
    for topic in (
        # The app guide, in the order of docs/APP.md.
        _topic("installer-telephone", "Installer la gestion sur le téléphone",
               (APP, "Installer la gestion sur le téléphone"), aliases=("installer", "telephone")),
        _topic("notifications", "Recevoir les notifications sur le téléphone",
               (APP, "Recevoir les notifications sur le téléphone"), aliases=("push",)),
        _topic("acces-equipe", "Donner un accès à l'équipe", (APP, "Donner un accès à l'équipe"),
               aliases=("comptes", "acces")),
        _topic("brief", "Le brief et la file « À toi »", (APP, "Le brief et la file « À toi »"),
               aliases=("a-toi", "file", "file-a-toi")),
        _topic("assistant", "L'assistant", (APP, "L'assistant"), aliases=("chat",)),
        _topic("ajouter-carte", "Ajouter une carte", (APP, "Ajouter une carte"), aliases=("ajouter", "saisir")),
        _topic("photo", "Prendre ou téléverser une photo", (APP, "Prendre ou téléverser une photo"),
               (APP, "Préparer la photo"), aliases=("photos",)),
        _topic("saisie-serie", "Saisir en série", (APP, "Saisir en série"), aliases=("serie",)),
        _topic("deplacer", "Déplacer une sélection de cartes", (APP, "Déplacer une sélection de cartes"),
               aliases=("ranger", "deplacement")),
        _topic("page-classeur", "Déposer une page de classeur (3×3)",
               (APP, "Déposer une page de classeur (3×3)"), aliases=("page",)),
        _topic("corriger-fiche", "Corriger une fiche", (APP, "Corriger une fiche"), aliases=("fiche", "corriger")),
        _topic("variante", "La variante : Standard ou Foil", (APP, "La variante : Standard ou Foil"),
               aliases=("finition", "reverse", "holo")),
        _topic("tampon", "Le tampon", (APP, "Le tampon")),
        _topic("verso-etat", "Le verso et l'état", (APP, "Le verso et l'état"), aliases=("etat", "verso")),
        _topic("a-examiner", "Repérer les cartes à examiner", (APP, "Repérer les cartes à examiner"),
               aliases=("examiner", "examen")),
        _topic("relever-prix", "Relever le prix d'une carte", (APP, "Relever le prix d'une carte"),
               (APP, "Ce que devient le prix"), aliases=("prix", "cote")),
        _topic("prix-cardmarket", "Estimer le prix de vente depuis Cardmarket",
               (APP, "Estimer le prix de vente depuis Cardmarket"), aliases=("cardmarket",)),
        _topic("totaux", "Les totaux de la collection", (APP, "Les totaux de la collection"),
               aliases=("valeur", "total")),
        _topic("constituer-lot", "Constituer un lot", (APP, "Constituer un lot"), aliases=("creer-lot",)),
        _topic("suivre-lot", "Suivre un lot", (APP, "Suivre un lot"), aliases=("vente", "ventes", "expedier")),
        _topic("annonce", "Préparer une annonce", (APP, "Préparer une annonce"), aliases=("brouillon-annonce",)),
        _topic("vitrine", "Publier en vitrine", (APP, "Publier en vitrine"), aliases=("publier",)),
        _topic("demandes-clients", "Les clients et leurs demandes", (APP, "Les clients et leurs demandes"),
               aliases=("demandes", "reservation", "clients")),
        _topic("rechercher", "Rechercher et filtrer", (APP, "Rechercher et filtrer"),
               aliases=("filtres", "recherche", "trier")),
        _topic("supprimer", "Supprimer ou restaurer un exemplaire", (APP, "Supprimer ou restaurer un exemplaire"),
               aliases=("restaurer",)),
        _topic("exporter", "Exporter", (APP, "Exporter"), aliases=("export",)),
        _topic("sauvegarder", "Sauvegarder", (APP, "Sauvegarder"), aliases=("sauvegarde",)),
        _topic("limites-app", "Ce que l'application ne fait pas", (APP, "Ce que l'application ne fait pas"),
               aliases=("limites",)),
        # Business rules, from the skills and decision records.
        _topic("plancher", "Le plancher anti-bradage", (AUTONOMY, "Le plancher anti-bradage"),
               aliases=("plancher-anti-bradage", "bradage", "prix-minimum")),
        _topic("derogation", "Un prix sous le plancher : la dérogation", (D0030, "Décision."), (D0030, "Conséquences."),
               aliases=("derogations", "sous-le-plancher")),
        _topic("autonomie", "Ce que les agents font seuls, ce qui reste humain", (D0021, "Décision."),
               aliases=("decisions-humaines", "agents", "humain")),
        _topic("photo-demandee", "Quand l'agent demande une nouvelle photo",
               (AUTONOMY, "Quand vous ne tranchez pas : demander une photo"),
               aliases=("demande-photo", "photo-a-reprendre")),
        _topic("lots", "Les lots de doublons composés par l'agent", (LOTS, "Overview"),
               aliases=("doublons", "rotation")),
        _topic("ordre-du-classeur", "L'ordre du classeur",
               (TRIAGE, "Étape 1 — Sélectionner par `risk_cents`, parcourir par `(page, pochette)`"),
               (APP, "Rechercher et filtrer"), aliases=("classeur", "ordre")),
    )
}

# A sentence that names one of these is an operator's or a developer's, not Lily's.
OPERATOR = re.compile(
    r"pokeprice-manage|pokeprice-agent\b|pokeprice[-_]lots|(?<![\w-])--[a-z]"
    r"|/srv/|/opt/|/etc/|~/|\.venv|\bsudo\b|\bssh\b|\brsync\b|\bsystemctl\b|\buv (?:run|sync)\b"
    r"|\bpython|scripts/|src/|tests/|\.py\b|\.sh\b|\.service\b|\.timer\b|\.env\b"
    r"|POKEPRICE_|\b(?:GET|POST|PUT|PATCH|DELETE) /|/api/",
    re.IGNORECASE,
)
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
BOLD_LABEL = re.compile(r"^\*\*([^*]+\.)\*\*")
ITEM = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")
LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
ASIDE = re.compile(r"\s*\([^()]*\)")
SENTENCE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÀ-ÖØ-Þ«*`(\[0-9])")


def fold(text):
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def find(query):
    """The topic a query names: its name, an alias or its folded title."""
    key = fold(query)
    for topic in TOPICS.values():
        if key in (topic.name, fold(topic.title), *topic.aliases):
            return topic
    return None


def catalogue():
    return [{"topic": t.name, "title": t.title} for t in TOPICS.values()]


def unavailable():
    return AgentError(503, "knowledge_unavailable", "Les guides de l'application sont introuvables sur ce serveur.")


def section(path, title):
    """Lines of one section: a Markdown heading with its subsections, or a bold label paragraph."""
    file = ROOT / path
    if not file.is_file():
        raise unavailable()
    lines = file.read_text(encoding="utf-8").splitlines()
    for start, line in enumerate(lines):
        heading = HEADING.match(line)
        if heading and heading.group(2) == title:
            level = len(heading.group(1))
            end = next((i for i in range(start + 1, len(lines))
                        if (h := HEADING.match(lines[i])) and len(h.group(1)) <= level), len(lines))
            return lines[start + 1:end]
        label = BOLD_LABEL.match(line)
        if label and label.group(1) == title:
            end = next((i for i in range(start + 1, len(lines))
                        if BOLD_LABEL.match(lines[i]) or HEADING.match(lines[i])), len(lines))
            return [line[label.end():].lstrip(), *lines[start + 1:end]]
    raise unavailable()


def blocks(lines):
    """Paragraphs, list items, table rows and subheadings, code and comments left out."""
    out, current, fenced, comment = [], [], False, False

    def close():
        if current:
            out.append(current.copy())
            current.clear()

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            close()
            fenced = not fenced
            continue
        if fenced:
            continue
        if comment or stripped.startswith("<!--"):
            comment = "-->" not in stripped
            continue
        if not stripped or stripped == "---":
            close()
        elif HEADING.match(stripped) or stripped.startswith("|") or ITEM.match(line):
            close()
            current.append(line.rstrip())
            if not ITEM.match(line):
                close()
        else:
            current.append(stripped)
    close()
    return out


def clean(block):
    """One block in plain text, without the sentences that carry an operator command."""
    first = block[0]
    heading = HEADING.match(first)
    if heading:
        text = heading.group(2)
        return None if OPERATOR.search(text) else text.replace("`", "") + " :"
    if first.lstrip().startswith("|"):
        if set(first.replace("|", "").strip()) <= set("-: "):
            return None
        text = LINK.sub(r"\1", first).replace("`", "")
        return None if OPERATOR.search(text) else text
    marker = ""
    item = ITEM.match(first)
    if item:
        indent = len(first) - len(first.lstrip())
        marker = " " * indent + first.strip()[: item.end() - indent].strip() + " "
        block = [first[item.end():], *block[1:]]
    joined = " ".join(part.strip() for part in block)
    if joined.startswith(">"):
        return None
    joined = LINK.sub(r"\1", joined)
    # An aside that names code or a command goes, the sentence around it stays.
    joined = ASIDE.sub(lambda m: "" if "`" in m.group() or OPERATOR.search(m.group()) else m.group(), joined)
    joined = joined.replace("**", "")
    kept = [s for s in SENTENCE.split(joined) if s and not OPERATOR.search(s)]
    if not kept:
        return None
    return marker + " ".join(kept).replace("`", "")


def text_of(topic):
    parts = []
    for path, title in topic.sources:
        cleaned = [c for c in (clean(b) for b in blocks(section(path, title))) if c]
        parts.append("\n".join(cleaned))
    return "\n\n".join(parts)


def knowledge(_ctx, values):
    """The ``knowledge`` tool: one topic in plain text, or the list of topics."""
    query = values.get("topic") or ""
    topic = find(query) if query.strip() else None
    if topic is None:
        answer = {"topics": catalogue()}
        if query.strip():
            answer["unknown_topic"] = query[:80]
        return answer
    text = text_of(topic)
    truncated = len(text) > MAX_CHARS
    if truncated:
        cut = text.rfind("\n", 0, MAX_CHARS)
        text = text[: cut if cut > 0 else MAX_CHARS].rstrip()
    return {
        "topic": topic.name,
        "title": topic.title,
        "sources": [f"{path} · {title.replace('`', '')}" for path, title in topic.sources],
        "text": text,
        "truncated": truncated,
    }
