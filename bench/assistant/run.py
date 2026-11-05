#!/usr/bin/env python3
"""Banc d'essai du modèle du chat de gestion (fiche 0031).

Rejoue le jeu de commandes types (commands.json) sur chaque candidat, avec une
boucle d'appels d'outils de deux tours au plus, et mesure la fiabilité des
appels, la latence (premier jeton, réponse complète) et les jetons consommés.
Les outils ne touchent aucune base : leurs résultats viennent de fixtures
synthétiques (fixtures.json).

Candidats, sous la forme fournisseur:modèle :
  ollama:gemma4:e2b-it-q4_K_M   modèle local servi par Ollama
  anthropic:claude-haiku-5-5    API Anthropic (clé ANTHROPIC_API_KEY)
  gemini:gemini-3.8-flash       API Gemini (clé GEMINI_API_KEY ou GOOGLE_API_KEY)
  fake:perfect                  adaptateur factice, pour les tests

Les clés sont lues dans l'environnement, jamais écrites ni affichées. Un
candidat sans clé, sans paquet ou sans modèle est sauté, avec sa raison.

Usage :
  uv run --extra web --extra dev python bench/assistant/run.py \
      --candidate ollama:gemma4:e2b-it-q4_K_M --label essai
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import platform
import re
import statistics
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"
MAX_TURNS = 2
COMMANDS_PER_DAY = 30
DAYS_PER_MONTH = 30
# Date fixe du banc : les dates relatives (« cette semaine ») restent comparables d'un passage à l'autre.
BENCH_DATE = "2026-11-04"
BENCH_DATE_TEXT = "mercredi 4 novembre 2026"

DEFAULT_CANDIDATES = [
    "ollama:gemma4:e2b-it-q4_K_M",
    "ollama:gemma4:e4b-it-q4_K_M",
    "ollama:gemma4-12b-text:latest",
    "anthropic:claude-haiku-5-5",
    "anthropic:claude-sonnet-5-5",
    "gemini:gemini-3.8-flash",
    "gemini:gemini-3.5-flash-lite",
]


# --------------------------------------------------------------------------
# Chargement


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_tools(path: Path = HERE / "tools.json") -> list[dict]:
    data = load_json(path)
    tools = []
    for kind in ("read", "write"):
        for tool in data[kind]:
            tools.append({**tool, "kind": kind})
    names = [t["name"] for t in tools]
    if len(names) != len(set(names)):
        raise ValueError("nom d'outil en double dans tools.json")
    return tools


def load_cases(path: Path = HERE / "commands.json", tools: list[dict] | None = None) -> list[dict]:
    """Charge et contrôle le jeu de commandes."""
    tools = tools if tools is not None else load_tools()
    known = {t["name"] for t in tools}
    cases = load_json(path)["cases"]
    seen: set[str] = set()
    for case in cases:
        cid = case.get("id")
        if not cid or cid in seen:
            raise ValueError(f"identifiant absent ou en double : {cid!r}")
        seen.add(cid)
        if not case.get("prompt") or not case.get("category"):
            raise ValueError(f"{cid} : prompt et category sont obligatoires")
        expect = case.get("expect") or {}
        if expect.get("none"):
            names = expect.get("allow", [])
        elif expect.get("tool"):
            names = [expect["tool"], *expect.get("before", [])]
        else:
            raise ValueError(f"{cid} : expect.tool ou expect.none est obligatoire")
        names = [*names, *case.get("forbid", []), *case.get("overrides", {})]
        unknown = [n for n in names if n not in known]
        if unknown:
            raise ValueError(f"{cid} : outils inconnus {unknown}")
    return cases


# --------------------------------------------------------------------------
# Outils


def fold(text: Any) -> str:
    """Minuscules sans accents, pour comparer des textes tapés au téléphone."""
    text = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(c for c in text if not unicodedata.combining(c))


_TYPES = {
    "object": dict,
    "string": str,
    "array": list,
    "boolean": bool,
}


def validate(schema: dict, value: Any, path: str = "$") -> list[str]:
    """Validation du sous-ensemble de JSON Schema utilisé par tools.json."""
    errors: list[str] = []
    kind = schema.get("type")
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return [f"{path} : entier attendu, reçu {value!r}"]
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return [f"{path} : nombre attendu, reçu {value!r}"]
    elif kind in _TYPES and not isinstance(value, _TYPES[kind]):
        return [f"{path} : {kind} attendu, reçu {value!r}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path} : {value!r} hors de {schema['enum']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path} : {value} < {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path} : {value} > {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path} : {value} <= {schema['exclusiveMinimum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path} : texte trop court")
        if len(value) > schema.get("maxLength", float("inf")):
            errors.append(f"{path} : texte trop long")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path} : {value!r} ne suit pas le motif {schema['pattern']}")
    if kind == "object":
        props = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path}.{name} : obligatoire")
        for name, item in value.items():
            if name in props:
                errors.extend(validate(props[name], item, f"{path}.{name}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{name} : propriété inconnue")
    return errors


def _days_since(since: str | None) -> float:
    if not since:
        return 1
    try:
        start = datetime.fromisoformat(str(since)[:10])
    except ValueError:
        return 1
    return (datetime.fromisoformat(BENCH_DATE) - start).days


# La consigne système est celle du chat de gestion : un seul fichier, dans le paquet.
SYSTEM_PROMPT = HERE.parents[1] / "src" / "pokeprice" / "assistant_prompt.md"
# One price list for the bench and the chat's cost alert (decision 0039).
PRICING = HERE.parents[1] / "src" / "pokeprice" / "assistant_pricing.json"


def load_system(path: Path = SYSTEM_PROMPT) -> str:
    return path.read_text(encoding="utf-8").replace("{date_du_jour}", BENCH_DATE_TEXT)


class Fixtures:
    """Résultats synthétiques des outils, sans aucune base."""

    SEARCH_FIELDS = ("copy_id", "name_fr", "name_en", "set", "number", "language",
                     "condition", "status", "price_eur")

    def __init__(self, data: dict, overrides: dict | None = None):
        self.data = data
        self.overrides = overrides or {}
        self.copies = {c["copy_id"]: c for c in data["copies"]}

    def call(self, name: str, args: dict) -> dict:
        if name in self.overrides:
            return self.overrides[name]
        handler = getattr(self, f"_{name}", None)
        if handler is None:
            return {"error": f"outil inconnu : {name}"}
        try:
            return handler(**args)
        except TypeError as exc:
            return {"error": f"arguments invalides : {exc}"}

    def _copy(self, copy_id: str) -> dict | None:
        return self.copies.get(str(copy_id).strip().upper())

    @staticmethod
    def _matches(query: str, copy: dict) -> bool:
        haystack = fold(" ".join(str(copy.get(k, "")) for k in
                                 ("copy_id", "name_fr", "name_en", "set", "number")))
        words = re.findall(r"[a-z0-9]+", haystack)
        tokens = [t for t in re.findall(r"[a-z0-9]+", fold(query)) if len(t) >= 3]
        if not tokens:
            return False
        names = re.findall(r"[a-z0-9]+", fold(f"{copy.get('name_fr', '')} {copy.get('name_en', '')}"))
        for token in tokens:
            if token in words or any(difflib.SequenceMatcher(None, token, w).ratio() >= 0.75 for w in names):
                return True
        return False

    @staticmethod
    def _states(copy: dict) -> dict:
        """Statut d'identification, stock et mise en vente, au vocabulaire de la fiche 0032."""
        status = copy["status"]
        return {
            "status": {"to_identify": "unresolved", "to_verify": "review"}.get(status, "confirmed"),
            "stock": status if status in {"sold", "reserved"} else "available",
            "for_sale": status == "for_sale",
        }

    def _search_copies(self, query: str = "", number: str | None = None, set: str | None = None,
                       album: str | None = None, status: str | None = None, stock: str | None = None,
                       for_sale: bool | None = None, limit: int = 20, offset: int = 0) -> dict:
        found = []
        for copy in self.data["copies"]:
            states = self._states(copy)
            if query and query.strip() not in {"*", "%"} and not self._matches(query, copy):
                continue
            if number and fold(number) not in fold(copy["number"]):
                continue
            if set and fold(set) not in fold(copy["set"]):
                continue
            if status and states["status"] != status:
                continue
            if stock and states["stock"] != stock:
                continue
            if for_sale is not None and states["for_sale"] != for_sale:
                continue
            found.append({**{k: copy.get(k) for k in self.SEARCH_FIELDS}, **states})
        return {"total": len(found), "copies": found[offset: offset + max(1, int(limit))]}

    def _get_copy(self, copy_id: str) -> dict:
        copy = self._copy(copy_id)
        if not copy:
            return {"error": f"exemplaire introuvable : {copy_id}"}
        return {k: v for k, v in copy.items() if k not in {"price_explanation", "not_for_sale_reason"}}

    def _explain_price(self, copy_id: str) -> dict:
        copy = self._copy(copy_id)
        if not copy:
            return {"error": f"exemplaire introuvable : {copy_id}"}
        return {"copy_id": copy["copy_id"], "price_eur": copy.get("price_eur"),
                "floor_eur": copy.get("floor_eur"),
                "explanation": copy.get("price_explanation", "Pas d'explication enregistrée.")}

    def _why_not_for_sale(self, copy_id: str) -> dict:
        copy = self._copy(copy_id)
        if not copy:
            return {"error": f"exemplaire introuvable : {copy_id}"}
        if copy["status"] == "for_sale":
            return {"copy_id": copy["copy_id"], "for_sale": True, "listing_id": copy.get("listing_id")}
        return {"copy_id": copy["copy_id"], "for_sale": False, "status": copy["status"],
                "reason": copy.get("not_for_sale_reason", "Vendu.")}

    def _list_listings(self, min_age_days: int | None = None, max_age_days: int | None = None,
                       kind: str = "any", copy_id: str | None = None, limit: int = 20,
                       offset: int = 0) -> dict:
        rows = [r for r in self.data["listings"]
                if r["status"] == "online"
                and (min_age_days is None or r["age_days"] >= min_age_days)
                and (max_age_days is None or r["age_days"] <= max_age_days)
                and (kind in {None, "any"} or r["kind"] == kind)
                and (not copy_id or r.get("copy_id") == copy_id)]
        return {"total": len(rows), "listings": rows[offset: offset + max(1, int(limit))]}

    def _sales_summary(self, since: str | None = None) -> dict:
        days = _days_since(since)
        period = "today" if days <= 1 else "week" if days <= 7 else "month" if days <= 31 else "year"
        return {"since": since or "24 dernières heures", **self.data["sales"][period]}

    def _agent_activity(self, since: str | None = None) -> dict:
        return {**self.data["agent_activity"], "since": since or "24 dernières heures"}

    def _todo_queue(self, limit: int = 50) -> dict:
        queue = self.data["todo_queue"]
        return {"items": queue["items"][: max(1, int(limit))],
                "estimated_minutes": queue["estimated_minutes"]}

    def _publish_lot(self, **_: Any) -> dict:
        return self.data["write_ok"]

    _set_price = _publish_lot
    _unpublish_listing = _publish_lot

    def _request_floor_waiver(self, **_: Any) -> dict:
        return {"status": "queued", "todo_card": "FLOOR-SYNTH-1",
                "message": "Demande ajoutée à la file « À toi »."}


# --------------------------------------------------------------------------
# Adaptateurs


@dataclass
class Turn:
    text: str = ""
    calls: list[dict] = field(default_factory=list)  # {"id", "name", "args"}
    ttft_s: float | None = None
    total_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    raw: Any = None
    error: str | None = None


class Adapter:
    provider = "?"

    def __init__(self, model: str):
        self.model = model

    @property
    def name(self) -> str:
        return f"{self.provider}:{self.model}"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def begin_case(self, case: dict) -> None:
        """Appelé avant chaque cas (l'adaptateur factice s'en sert)."""

    def warmup(self, system: str, tools: list[dict]) -> None:
        """Appel non mesuré avant le premier cas (chargement du modèle)."""

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:
        raise NotImplementedError

    def describe(self) -> dict:
        return {"provider": self.provider, "model": self.model}


class FakeAdapter(Adapter):
    """Rejoue un scénario fixe : {case_id: [tour1, tour2]}, chaque tour {text, calls}.

    Le modèle « perfect » appelle l'outil attendu par chaque cas.
    """

    provider = "fake"

    def __init__(self, model: str = "perfect", script: dict | None = None,
                 cases: list[dict] | None = None):
        super().__init__(model)
        self.script = script or {}
        if model == "perfect" and cases is not None and not self.script:
            self.script = {c["id"]: perfect_script(c) for c in cases}
        self._turns: list[dict] = []

    def begin_case(self, case: dict) -> None:
        self._turns = list(self.script.get(case["id"], []))

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:
        step = self._turns.pop(0) if self._turns else {"text": "D'accord."}
        calls = [{"id": f"f{i}", "name": c["name"], "args": c.get("args", {})}
                 for i, c in enumerate(step.get("calls", []))]
        return Turn(text=step.get("text", ""), calls=calls, ttft_s=0.01, total_s=0.02,
                    input_tokens=step.get("input_tokens", 1000),
                    output_tokens=step.get("output_tokens", 20))


def perfect_script(case: dict) -> list[dict]:
    expect = case["expect"]
    if expect.get("none"):
        return [{"text": "Je ne peux pas le faire ici ; c'est à faire dans la gestion."}]
    args = {}
    for key, matcher in expect.get("args", {}).items():
        if isinstance(matcher, dict):
            if matcher.get("optional"):
                continue
            if "any_of" in matcher:
                args[key] = matcher["any_of"][0]
            elif "date_between" in matcher:
                args[key] = matcher["date_between"][0]
            elif "min" in matcher:
                args[key] = matcher["min"]
            elif "re" in matcher:
                args[key] = re.sub(r"\\b|[|].*|[\\^$()]", "", matcher["re"])
        else:
            args[key] = matcher
    if expect["tool"] == "request_floor_waiver":
        args.setdefault("reason", "Demandé par l'opératrice.")
    return [{"calls": [{"name": expect["tool"], "args": args}]}, {"text": "C'est fait."}]


def _tool_specs(tools: list[dict]) -> list[dict]:
    return [{"name": t["name"], "description": t["description"], "parameters": t["parameters"]}
            for t in tools]


class OllamaAdapter(Adapter):
    """Modèle local par l'API HTTP d'Ollama, en flux.

    num_gpu=0 force le calcul sur le processeur, comme sur le serveur ARM sans
    carte graphique ; num_thread limite les cœurs pour imiter l'instance.
    """

    provider = "ollama"

    def __init__(self, model: str, host: str | None = None, num_gpu: int | None = 0,
                 num_thread: int | None = None, num_ctx: int = 8192):
        super().__init__(model)
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
        if not self.host.startswith("http"):
            self.host = f"http://{self.host}"
        self.options: dict[str, Any] = {"temperature": 0, "num_ctx": num_ctx}
        if num_gpu is not None:
            self.options["num_gpu"] = num_gpu
        if num_thread:
            self.options["num_thread"] = num_thread
        self.num_thread = num_thread
        self.capabilities: list[str] = []

    def _post(self, path: str, payload: dict, timeout: float = 30):
        request = urllib.request.Request(f"{self.host}{path}", data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(request, timeout=timeout)

    def available(self) -> tuple[bool, str]:
        try:
            with self._post("/api/show", {"model": self.model}) as response:
                info = json.load(response)
        except urllib.error.HTTPError:
            return False, f"modèle {self.model} absent d'Ollama"
        except (urllib.error.URLError, OSError):
            return False, f"Ollama injoignable sur {self.host}"
        self.capabilities = info.get("capabilities", [])
        if "tools" not in self.capabilities:
            return False, f"{self.model} ne déclare pas l'appel d'outils"
        return True, ""

    @property
    def name(self) -> str:
        base = f"{self.provider}:{self.model}"
        return f"{base} ({self.num_thread} fils)" if self.num_thread else base

    def describe(self) -> dict:
        return {**super().describe(), "options": self.options}

    def warmup(self, system: str, tools: list[dict]) -> None:
        # Charge le modèle et met en cache le préfixe système + outils, comme
        # un serveur qui garde le modèle en mémoire entre deux commandes.
        self.chat(system, [{"role": "user", "text": "bonjour"}], tools)

    def _messages(self, system: str, messages: list[dict]) -> list[dict]:
        out = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["text"]})
            elif m["role"] == "assistant":
                turn: Turn = m["turn"]
                out.append({"role": "assistant", "content": turn.text,
                            "tool_calls": [{"function": {"name": c["name"], "arguments": c["args"]}}
                                           for c in turn.calls]})
            else:
                for r in m["results"]:
                    out.append({"role": "tool", "tool_name": r["name"], "content": r["content"]})
        return out

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(system, messages),
            "tools": [{"type": "function", "function": spec} for spec in _tool_specs(tools)],
            "stream": True,
            "options": self.options,
            "keep_alive": "30m",
        }
        if "thinking" in self.capabilities:
            payload["think"] = False
        turn = Turn()
        start = time.perf_counter()
        text, calls, final = [], [], {}
        with self._post("/api/chat", payload, timeout=900) as response:
            for line in response:
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    raise RuntimeError(chunk["error"])
                message = chunk.get("message", {})
                if turn.ttft_s is None and (message.get("content") or message.get("tool_calls")):
                    turn.ttft_s = time.perf_counter() - start
                text.append(message.get("content", ""))
                calls.extend(message.get("tool_calls") or [])
                if chunk.get("done"):
                    final = chunk
        turn.total_s = time.perf_counter() - start
        turn.text = "".join(text)
        for i, call in enumerate(calls):
            fn = call.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    pass
            turn.calls.append({"id": f"o{i}", "name": fn.get("name", ""), "args": args})
        turn.input_tokens = final.get("prompt_eval_count", 0)
        turn.output_tokens = final.get("eval_count", 0)
        turn.raw = {k: final.get(k) for k in ("load_duration", "prompt_eval_duration", "eval_duration")}
        return turn


class AnthropicAdapter(Adapter):
    """API Anthropic, par le SDK officiel, en flux (premier jeton mesuré)."""

    provider = "anthropic"

    def __init__(self, model: str, effort: str = "low", max_tokens: int = 4096):
        super().__init__(model)
        self.effort = effort
        self.max_tokens = max_tokens
        self.client = None

    def available(self) -> tuple[bool, str]:
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            return False, "clé ANTHROPIC_API_KEY absente de l'environnement"
        try:
            import anthropic
        except ImportError:
            return False, "paquet anthropic absent (uv run --with anthropic …)"
        self.client = anthropic.Anthropic()
        return True, ""

    def describe(self) -> dict:
        return {**super().describe(), "effort": self.effort}

    @staticmethod
    def _messages(messages: list[dict]) -> list[dict]:
        out = []
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["text"]})
            elif m["role"] == "assistant":
                out.append({"role": "assistant", "content": m["turn"].raw})
            else:
                out.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": r["id"], "content": r["content"]}
                    for r in m["results"]]})
        return out

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:
        specs = [{"name": s["name"], "description": s["description"],
                  "input_schema": s["parameters"], "eager_input_streaming": True}
                 for s in _tool_specs(tools)]
        turn = Turn()
        start = time.perf_counter()
        with self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            tools=specs,
            messages=self._messages(messages),
            output_config={"effort": self.effort},
        ) as stream:
            for event in stream:
                if turn.ttft_s is None and event.type == "content_block_start" \
                        and event.content_block.type in {"text", "tool_use"}:
                    turn.ttft_s = time.perf_counter() - start
            final = stream.get_final_message()
        turn.total_s = time.perf_counter() - start
        if final.stop_reason == "refusal":
            turn.error = "refus du modèle"
        turn.raw = final.content
        for block in final.content:
            if block.type == "text":
                turn.text += block.text
            elif block.type == "tool_use":
                turn.calls.append({"id": block.id, "name": block.name, "args": block.input})
        usage = final.usage
        turn.input_tokens = (usage.input_tokens + (usage.cache_creation_input_tokens or 0)
                             + (usage.cache_read_input_tokens or 0))
        turn.output_tokens = usage.output_tokens
        return turn


class GeminiAdapter(Adapter):
    """API Gemini : l'adaptateur du chat de gestion (pokeprice.assistant_model), chronométré."""

    provider = "gemini"

    def __init__(self, model: str, thinking_level: str | None = "low"):
        super().__init__(model)
        self.thinking_level = thinking_level
        self.client = None

    def available(self) -> tuple[bool, str]:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            return False, "clé GEMINI_API_KEY absente de l'environnement"
        try:
            from google import genai  # noqa: F401

            from pokeprice.assistant_model import GeminiModel
        except ImportError:
            return False, "paquet google-genai ou pokeprice absent"
        self.client = GeminiModel(key, self.model, thinking_level=self.thinking_level, timeout=120)
        return True, ""

    def describe(self) -> dict:
        return {**super().describe(), "thinking_level": self.thinking_level}

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:
        turn = Turn()
        start = time.perf_counter()
        for kind, value in self.client.stream(system, messages, _tool_specs(tools)):
            if kind in ("text", "call") and turn.ttft_s is None:
                turn.ttft_s = time.perf_counter() - start
            elif kind == "turn":
                turn.text, turn.calls, turn.raw = value.text, value.calls, value.raw
                turn.input_tokens, turn.output_tokens = value.input_tokens, value.output_tokens
        turn.total_s = time.perf_counter() - start
        return turn


def make_adapter(spec: str, args: argparse.Namespace | None = None,
                 cases: list[dict] | None = None) -> Adapter:
    provider, _, model = spec.partition(":")
    if provider == "ollama":
        return OllamaAdapter(model, num_gpu=getattr(args, "num_gpu", 0),
                             num_thread=getattr(args, "num_thread", None))
    if provider == "anthropic":
        return AnthropicAdapter(model, effort=getattr(args, "effort", "low"))
    if provider == "gemini":
        return GeminiAdapter(model)
    if provider == "fake":
        return FakeAdapter(model or "perfect", cases=cases)
    raise ValueError(f"fournisseur inconnu : {provider}")


# --------------------------------------------------------------------------
# Rejeu et notation


def run_case(adapter: Adapter, case: dict, tools: list[dict], system: str,
             fixtures_data: dict) -> dict:
    fixtures = Fixtures(fixtures_data, case.get("overrides"))
    adapter.begin_case(case)
    messages: list[dict] = [{"role": "user", "text": case["prompt"]}]
    turns: list[Turn] = []
    error = None
    for _ in range(MAX_TURNS):
        try:
            turn = adapter.chat(system, messages, tools)
        except Exception as exc:  # une panne du fournisseur compte comme un échec du cas
            error = f"{type(exc).__name__}: {str(exc)[:200]}"
            break
        turns.append(turn)
        if turn.error:
            error = turn.error
            break
        if not turn.calls or len(turns) == MAX_TURNS:
            break
        messages.append({"role": "assistant", "turn": turn})
        messages.append({"role": "tool", "results": [
            {"id": c["id"], "name": c["name"],
             "content": json.dumps(fixtures.call(c["name"], c["args"] if isinstance(c["args"], dict) else {}),
                                   ensure_ascii=False)}
            for c in turn.calls]})
    result = score_case(case, turns, tools, error)
    result["turns"] = [{"text": t.text[:400], "calls": t.calls, "ttft_s": t.ttft_s,
                        "total_s": round(t.total_s, 3), "input_tokens": t.input_tokens,
                        "output_tokens": t.output_tokens} for t in turns]
    return result


def match_value(matcher: Any, value: Any) -> bool:
    if isinstance(matcher, dict):
        if "any_of" in matcher:
            return any(match_value(m, value) for m in matcher["any_of"])
        if "date_between" in matcher:
            low, high = matcher["date_between"]
            return isinstance(value, str) and low <= value[:10] <= high
        if "re" in matcher:
            return isinstance(value, str) and re.search(matcher["re"], fold(value)) is not None
        if "min" in matcher or "max" in matcher:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return False
            return matcher.get("min", float("-inf")) - 1e-9 <= value <= matcher.get("max", float("inf")) + 1e-9
        raise ValueError(f"comparateur inconnu : {matcher}")
    if isinstance(matcher, str):
        return isinstance(value, str) and fold(value).strip() == fold(matcher).strip()
    return value == matcher


def match_args(expected: dict, args: Any) -> bool:
    if not isinstance(args, dict):
        return False
    for key, matcher in expected.items():
        if key not in args:
            if isinstance(matcher, dict) and matcher.get("optional"):
                continue
            return False
        if not match_value(matcher, args[key]):
            return False
    return True


def score_case(case: dict, turns: list[Turn], tools: list[dict], error: str | None = None) -> dict:
    by_name = {t["name"]: t for t in tools}
    expect = case["expect"]
    first = turns[0].calls if turns else []
    second = turns[1].calls if len(turns) > 1 else []
    calls = [*first, *second]

    invented = sorted({c["name"] for c in calls if c["name"] not in by_name})
    schema_errors = []
    for c in calls:
        if c["name"] in by_name:
            args = c["args"] if isinstance(c["args"], dict) else c["args"]
            for err in validate(by_name[c["name"]]["parameters"], args):
                schema_errors.append(f"{c['name']} {err}")

    if expect.get("none"):
        allow = set(expect.get("allow", []))
        tool_ok = args_ok = all(c["name"] in allow for c in calls)
    else:
        # Une lecture au premier tour (chercher l'identifiant, vérifier le
        # plancher) est permise avant l'outil attendu ; elle coûte un tour,
        # que la latence compte.
        reads = {t["name"] for t in tools if t["kind"] == "read"}
        name, before = expect["tool"], set(expect.get("before", [])) | reads
        expected_args = expect.get("args", {})

        def found(pred) -> bool:
            if any(pred(c) for c in first):
                return True
            return bool(first) and all(c["name"] in before | {name} for c in first) \
                and any(pred(c) for c in second)

        tool_ok = found(lambda c: c["name"] == name)
        args_ok = found(lambda c: c["name"] == name and match_args(expected_args, c["args"]))

    forbidden = sorted({c["name"] for c in calls if c["name"] in set(case.get("forbid", []))})
    trap = case.get("trap")
    trap_ok = None
    if trap:
        trap_ok = not forbidden and not invented and tool_ok
    passed = (error is None and tool_ok and args_ok and not schema_errors and not invented
              and not forbidden)
    return {
        "id": case["id"], "category": case["category"], "trap": trap, "prompt": case["prompt"],
        "passed": passed, "tool_ok": tool_ok, "args_ok": args_ok,
        "schema_valid": not schema_errors, "schema_errors": schema_errors,
        "invented_tools": invented, "forbidden_calls": forbidden, "trap_ok": trap_ok,
        "error": error,
        "ttft_s": turns[0].ttft_s if turns else None,
        "first_turn_s": round(turns[0].total_s, 3) if turns else None,
        "total_s": round(sum(t.total_s for t in turns), 3),
        "input_tokens": sum(t.input_tokens for t in turns),
        "output_tokens": sum(t.output_tokens for t in turns),
    }


def _quantile(values: list[float], q: float) -> float | None:
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    index = min(len(values) - 1, max(0, round(q * (len(values) - 1))))
    return round(values[index], 2)


def summarize(results: list[dict], pricing: dict | None = None, name: str = "",
              commands_per_day: int = COMMANDS_PER_DAY) -> dict:
    n = len(results)
    rate = lambda key: round(sum(1 for r in results if r[key]) / n, 3) if n else None  # noqa: E731
    traps = [r for r in results if r["trap"]]
    categories = {}
    for r in results:
        cat = categories.setdefault(r["category"], {"cases": 0, "passed": 0})
        cat["cases"] += 1
        cat["passed"] += int(r["passed"])
    mean_in = statistics.fmean(r["input_tokens"] for r in results) if n else 0
    mean_out = statistics.fmean(r["output_tokens"] for r in results) if n else 0
    summary = {
        "cases": n,
        "passed": sum(1 for r in results if r["passed"]),
        "pass_rate": rate("passed"),
        "tool_rate": rate("tool_ok"),
        "args_rate": rate("args_ok"),
        "schema_valid_rate": rate("schema_valid"),
        "invented_tool_cases": sum(1 for r in results if r["invented_tools"]),
        "errors": sum(1 for r in results if r["error"]),
        "traps": len(traps),
        "traps_avoided": sum(1 for r in traps if r["trap_ok"]),
        # Appel interdit ou outil inventé : ce que le serveur devrait bloquer.
        # Un piège seulement inachevé (le modèle demande l'identifiant) n'en est pas un.
        "unsafe_cases": sum(1 for r in results if r.get("forbidden_calls") or r["invented_tools"]),
        "by_category": categories,
        "latency_s": {
            "ttft_p50": _quantile([r["ttft_s"] for r in results], 0.5),
            "ttft_p90": _quantile([r["ttft_s"] for r in results], 0.9),
            "first_turn_p50": _quantile([r["first_turn_s"] for r in results], 0.5),
            "total_p50": _quantile([r["total_s"] for r in results], 0.5),
            "total_p90": _quantile([r["total_s"] for r in results], 0.9),
        },
        "tokens_per_command": {"input": round(mean_in), "output": round(mean_out)},
    }
    price = (pricing or {}).get("models", {}).get(name)
    if price:
        monthly = commands_per_day * DAYS_PER_MONTH
        summary["cost"] = {
            "usd_per_command": round((mean_in * price["input"] + mean_out * price["output"]) / 1e6, 6),
            "usd_per_month": round(monthly * (mean_in * price["input"] + mean_out * price["output"]) / 1e6, 2),
            "commands_per_month": monthly,
            "pricing": price,
        }
    elif name.startswith("ollama:"):
        summary["cost"] = {"usd_per_month": 0.0, "note": "modèle local, aucun coût au jeton"}
    return summary


def machine_info() -> dict:
    cpu = platform.processor() or platform.machine()
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return {"machine": platform.machine(), "cpu": cpu, "cpu_count": os.cpu_count(),
            "python": platform.python_version()}


def run_bench(adapters: list[Adapter], cases: list[dict], tools: list[dict], system: str,
              fixtures_data: dict, pricing: dict | None = None, progress=None,
              commands_per_day: int = COMMANDS_PER_DAY) -> dict:
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "machine": machine_info(),
        "max_turns": MAX_TURNS,
        "commands_per_day": commands_per_day,
        "pricing_retrieved": (pricing or {}).get("retrieved"),
        "pricing_sources": (pricing or {}).get("sources"),
        "candidates": [],
    }
    for adapter in adapters:
        ok, reason = adapter.available()
        entry: dict[str, Any] = {"name": adapter.name, **adapter.describe()}
        if not ok:
            entry["skipped"] = reason
            report["candidates"].append(entry)
            if progress:
                progress(f"{adapter.name} : sauté ({reason})")
            continue
        try:
            adapter.warmup(system, tools)
        except Exception as exc:
            entry["skipped"] = f"échec du premier appel : {type(exc).__name__}: {str(exc)[:200]}"
            report["candidates"].append(entry)
            continue
        results = []
        for case in cases:
            result = run_case(adapter, case, tools, system, fixtures_data)
            results.append(result)
            if progress:
                mark = "ok" if result["passed"] else "ÉCHEC"
                progress(f"{adapter.name} {case['id']} {mark} {result['total_s']:.1f}s")
        entry["summary"] = summarize(results, pricing, adapter.name, commands_per_day)
        entry["results"] = results
        report["candidates"].append(entry)
    return report


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f} %"


def _sec(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}".replace(".", ",")


def render_markdown(report: dict) -> str:
    m = report["machine"]
    lines = [
        "# Banc du modèle du chat de gestion",
        "",
        f"Conditions de mesure : {report['generated_at']}, {m['cpu']} ({m['cpu_count']} fils), "
        f"{report['max_turns']} tours au plus par commande. Tarifs relevés le "
        f"{report.get('pricing_retrieved') or '—'}.",
        "",
        "| Candidat | Réussite | Bon outil | Arguments | Schéma valide | Outil inventé | Actions dangereuses | Pièges évités "
        "| 1er jeton p50 | Réponse p50 | Réponse p90 | Jetons entrée/sortie | Coût/mois |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    skipped = []
    for c in report["candidates"]:
        if "skipped" in c:
            skipped.append(f"- `{c['name']}` : non mesuré, {c['skipped']}.")
            continue
        s, lat = c["summary"], c["summary"]["latency_s"]
        cost = s.get("cost", {})
        cost_txt = "—" if "usd_per_month" not in cost else f"{cost['usd_per_month']:.2f} $".replace(".", ",")
        lines.append(
            f"| `{c['name']}` | {s['passed']}/{s['cases']} ({_pct(s['pass_rate'])}) | {_pct(s['tool_rate'])} "
            f"| {_pct(s['args_rate'])} | {_pct(s['schema_valid_rate'])} | {s['invented_tool_cases']} "
            f"| {s.get('unsafe_cases', '—')} | {s['traps_avoided']}/{s['traps']} | {_sec(lat['ttft_p50'])} s | {_sec(lat['total_p50'])} s "
            f"| {_sec(lat['total_p90'])} s | {s['tokens_per_command']['input']}/"
            f"{s['tokens_per_command']['output']} | {cost_txt} |")
    if skipped:
        lines += ["", "Candidats non mesurés :", "", *skipped]
    lines += ["", "Pièges évités : le modèle fait l'action attendue (dérogation, lecture seule, aucune "
              "action) ; un piège non évité peut être seulement inachevé. Actions dangereuses : un appel "
              "interdit (prix sous le plancher, consigne d'un client suivie) ou un outil inventé."]
    lines += ["", "Coût mensuel : "
              f"{report['commands_per_day']} commandes par jour pendant 30 jours, au tarif public sans cache."]
    for c in report["candidates"]:
        if "results" not in c:
            continue
        cats = ", ".join(f"{k} {v['passed']}/{v['cases']}" for k, v in c["summary"]["by_category"].items())
        lines += ["", f"## `{c['name']}`", "", f"Par catégorie : {cats}.", ""]
        failures = [r for r in c["results"] if not r["passed"]]
        if not failures:
            lines.append("Aucun échec.")
            continue
        lines += ["| Cas | Commande | Appels | Motif |", "|---|---|---|---|"]
        for r in failures:
            calls = "; ".join(f"{call['name']}({json.dumps(call['args'], ensure_ascii=False)})"
                              for t in r["turns"] for call in t["calls"]) or "aucun"
            reasons = []
            if r["error"]:
                reasons.append(f"erreur : {r['error']}")
            if not r["tool_ok"]:
                reasons.append("mauvais outil")
            elif not r["args_ok"]:
                reasons.append("arguments inattendus")
            if r["schema_errors"]:
                reasons.append("hors schéma : " + ", ".join(r["schema_errors"][:2]))
            if r["invented_tools"]:
                reasons.append("outil inventé : " + ", ".join(r["invented_tools"]))
            if r["forbidden_calls"]:
                reasons.append("piège raté : " + ", ".join(r["forbidden_calls"]))
            cell = lambda s: s.replace("|", "\\|").replace("\n", " ")  # noqa: E731
            lines.append(f"| {r['id']} | {cell(r['prompt'])} | {cell(calls)[:220]} | {cell('; '.join(reasons))} |")
    return "\n".join(lines) + "\n"


def rescore(entry: dict, cases: list[dict], tools: list[dict], pricing: dict | None,
            commands_per_day: int = COMMANDS_PER_DAY) -> dict:
    """Renote un candidat d'après ses appels enregistrés et le jeu actuel."""
    if "results" not in entry:
        return entry
    by_id = {c["id"]: c for c in cases}
    results = []
    for old in entry["results"]:
        case = by_id.get(old["id"])
        if case is None:
            continue
        turns = [Turn(text=t["text"], calls=t["calls"], ttft_s=t["ttft_s"], total_s=t["total_s"],
                      input_tokens=t["input_tokens"], output_tokens=t["output_tokens"])
                 for t in old["turns"]]
        new = score_case(case, turns, tools, old["error"])
        new["turns"] = old["turns"]
        results.append(new)
    return {**entry, "results": results,
            "summary": summarize(results, pricing, entry["name"], commands_per_day)}


def merge_reports(reports: list[dict], cases: list[dict] | None = None,
                  tools: list[dict] | None = None, pricing: dict | None = None) -> dict:
    """Assemble des rapports ; avec le jeu, renote chaque candidat à la même règle."""
    merged = {k: v for k, v in reports[0].items() if k != "candidates"}
    merged["candidates"] = [c for r in reports for c in r["candidates"]]
    merged["merged_from"] = [r["generated_at"] for r in reports]
    if cases is not None and tools is not None:
        merged["candidates"] = [rescore(c, cases, tools, pricing, merged["commands_per_day"])
                                for c in merged["candidates"]]
    return merged


def write_report(report: dict, label: str, out_dir: Path = RESULTS_DIR) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{label}.json"
    md_path = out_dir / f"{label}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
                         encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--candidate", action="append", help="fournisseur:modèle (répétable)")
    parser.add_argument("--case", action="append", help="ne rejouer que ces cas (répétable)")
    parser.add_argument("--category", action="append", help="ne rejouer que ces catégories")
    parser.add_argument("--label", default=None, help="nom des fichiers du rapport")
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    parser.add_argument("--num-gpu", type=int, default=0,
                        help="couches sur la carte graphique pour Ollama (0 : processeur seul, comme le serveur)")
    parser.add_argument("--num-thread", type=int, default=None, help="fils de calcul pour Ollama")
    parser.add_argument("--effort", default="low", help="effort des modèles Anthropic")
    parser.add_argument("--commands-per-day", type=int, default=COMMANDS_PER_DAY)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--merge", nargs="+", type=Path, help="assembler ces rapports JSON en un seul")
    args = parser.parse_args(argv)

    if args.merge:
        tools = load_tools()
        report = merge_reports([load_json(p) for p in args.merge], load_cases(tools=tools), tools,
                               load_json(PRICING))
        json_path, md_path = write_report(report, args.label or "synthese", args.out)
        print(f"Rapport : {json_path} et {md_path}")
        return 0

    tools = load_tools()
    cases = load_cases(tools=tools)
    if args.case:
        cases = [c for c in cases if c["id"] in set(args.case)]
    if args.category:
        cases = [c for c in cases if c["category"] in set(args.category)]
    system = load_system()
    fixtures_data = load_json(HERE / "fixtures.json")
    pricing = load_json(PRICING)
    adapters = [make_adapter(spec, args, cases) for spec in (args.candidate or DEFAULT_CANDIDATES)]
    progress = None if args.quiet else (lambda msg: print(msg, file=sys.stderr, flush=True))
    report = run_bench(adapters, cases, tools, system, fixtures_data, pricing, progress,
                       args.commands_per_day)
    report["ollama_options"] = {"num_gpu": args.num_gpu, "num_thread": args.num_thread}
    label = args.label or datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path, md_path = write_report(report, label, args.out)
    print(f"Rapport : {json_path} et {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
