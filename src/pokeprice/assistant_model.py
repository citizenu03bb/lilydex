"""Model adapters of the management chat (decisions 0029 and 0031).

An adapter turns the neutral conversation of ``assistant.py`` into one call to
a model, streamed, with tool calling. It knows nothing of the collection: it
receives the system instruction, the messages and the tool schemas
(``assistant_tools.tool_schemas``), and yields the answer as it comes.

Messages, in the neutral shape shared with the bench (``bench/assistant``):

- ``{"role": "user", "text": ...}``: the operator's question;
- ``{"role": "assistant", "turn": Turn}``: an earlier answer of the model;
- ``{"role": "tool", "results": [{"id", "name", "content"}]}``: tool results,
  ``content`` being JSON text. They reach the model as function responses,
  the provider's data channel, never as instructions.

``stream`` yields ``("text", delta)`` while the answer is written and
``("call", name)`` as a tool call arrives, then one
``("turn", Turn)`` with the whole turn: text, tool calls, tokens and the raw
parts some providers need back on the next call (Gemini's thought
signatures).

The Gemini adapter reads its own key, ``POKEPRICE_ASSISTANT_GEMINI_KEY``,
never the OCR's: a separate key keeps the chat on a paid plan, with its own
quota and bill, and can be revoked without stopping the OCR (decision 0031).
"""

import os
from dataclasses import dataclass, field

DEFAULT_MODEL = "gemini-3.8-flash"
# Short: the operator waits on a phone. A stuck call ends the question, not the app.
TIMEOUT_SECONDS = 30
KEY_VARIABLE = "POKEPRICE_ASSISTANT_GEMINI_KEY"
MODEL_VARIABLE = "POKEPRICE_ASSISTANT_MODEL"


class ModelError(RuntimeError):
    """The model did not answer: provider down, timeout, refused request."""


@dataclass
class Turn:
    text: str = ""
    calls: list = field(default_factory=list)  # {"id", "name", "args"}
    input_tokens: int = 0
    output_tokens: int = 0
    raw: object = None


class Model:
    """The adapter interface: one streamed model call."""

    provider = "?"
    model = "?"

    @property
    def name(self):
        return f"{self.provider}:{self.model}"

    def stream(self, system, messages, tools, *, allow_tools=True):
        raise NotImplementedError


class FakeModel(Model):
    """Replays a script, for tests and for the browser check without a key.

    ``script`` is a list of turns ``{"text": ..., "calls": [{"name", "args"}]}``,
    or a function ``(system, messages, tools, allow_tools) -> turn``. Every call
    is recorded in ``seen`` so a test can check what would leave the server.
    """

    provider = "fake"

    def __init__(self, script=None, model="script"):
        self.model = model
        self.script = list(script or []) if not callable(script) else script
        self.seen = []

    def stream(self, system, messages, tools, *, allow_tools=True):
        self.seen.append({"system": system, "messages": list(messages),
                          "tools": tools, "allow_tools": allow_tools})
        if callable(self.script):
            step = self.script(system, messages, tools, allow_tools)
        else:
            step = self.script.pop(0) if self.script else {"text": "D’accord."}
        if isinstance(step, Exception):
            raise step
        text = step.get("text", "")
        # Streamed word by word, as a provider would.
        words = text.split(" ")
        for index, word in enumerate(words):
            if word or index:
                yield "text", (" " if index else "") + word
        calls = [{"id": f"f{i}", "name": c["name"], "args": c.get("args", {})}
                 for i, c in enumerate(step.get("calls", []))]
        for call in calls:
            yield "call", call["name"]
        yield "turn", Turn(text=text, calls=calls,
                           input_tokens=step.get("input_tokens", 1000),
                           output_tokens=step.get("output_tokens", 20))


def gemini_schema(schema):
    """Drop the keywords the Gemini API refuses in a parameter schema."""
    if isinstance(schema, dict):
        return {k: gemini_schema(v) for k, v in schema.items() if k != "exclusiveMinimum"}
    if isinstance(schema, list):
        return [gemini_schema(v) for v in schema]
    return schema


class GeminiModel(Model):
    """The Gemini API through google-genai, streamed, tools called by us only."""

    provider = "gemini"

    def __init__(self, key, model=DEFAULT_MODEL, *, thinking_level="low",
                 timeout=TIMEOUT_SECONDS, client=None):
        if not key:
            raise ValueError("Clé Gemini du chat absente.")
        self.model = model
        self.thinking_level = thinking_level
        self._key = key
        self._timeout = timeout
        self._client = client

    def __repr__(self):  # Never the key, even in a traceback.
        return f"GeminiModel({self.model!r})"

    def client(self):
        if self._client is None:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=self._key,
                http_options=types.HttpOptions(timeout=int(self._timeout * 1000)),
            )
        return self._client

    def contents(self, messages):
        from google.genai import types

        contents = []
        for m in messages:
            if m["role"] == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=m["text"])]))
            elif m["role"] == "assistant":
                turn = m["turn"]
                parts = turn.raw if turn.raw else [types.Part(text=turn.text)]
                contents.append(types.Content(role="model", parts=parts))
            else:
                contents.append(types.Content(role="user", parts=[
                    types.Part.from_function_response(name=r["name"], response={"result": r["content"]})
                    for r in m["results"]]))
        return contents

    def config(self, system, tools, allow_tools):
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=system,
            temperature=0,
            tools=[types.Tool(function_declarations=[
                types.FunctionDeclaration(name=s["name"], description=s["description"],
                                          parameters_json_schema=gemini_schema(s["parameters"]))
                for s in tools])] if tools else None,
            # The model proposes calls; only assistant.py runs them, after its checks.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tool_config=None if allow_tools or not tools else types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="NONE")),
            thinking_config=(types.ThinkingConfig(thinking_level=self.thinking_level)
                             if self.thinking_level else None),
        )

    def stream(self, system, messages, tools, *, allow_tools=True):
        turn, parts, usage = Turn(), [], None
        try:
            chunks = self.client().models.generate_content_stream(
                model=self.model, contents=self.contents(messages),
                config=self.config(system, tools, allow_tools))
            for chunk in chunks:
                usage = chunk.usage_metadata or usage
                for candidate in chunk.candidates or []:
                    for part in (candidate.content.parts if candidate.content else None) or []:
                        parts.append(part)
                        if part.text and not part.thought:
                            yield "text", part.text
                        elif part.function_call:
                            yield "call", part.function_call.name
        except ImportError as error:
            raise ModelError("paquet google-genai absent") from error
        except Exception as error:  # The provider's own errors: never the key, only their kind.
            raise ModelError(type(error).__name__) from None
        turn.raw = parts
        for index, part in enumerate(parts):
            if part.function_call:
                turn.calls.append({"id": part.function_call.id or f"g{index}",
                                   "name": part.function_call.name,
                                   "args": dict(part.function_call.args or {})})
            elif part.text and not part.thought:
                turn.text += part.text
        if usage:
            turn.input_tokens = usage.prompt_token_count or 0
            turn.output_tokens = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
        yield "turn", turn


def from_env(environ=None):
    """The chat's model, or None when its own key is absent: the chat is then off."""
    environ = os.environ if environ is None else environ
    key = environ.get(KEY_VARIABLE, "").strip()
    if not key:
        return None
    return GeminiModel(key, environ.get(MODEL_VARIABLE, "").strip() or DEFAULT_MODEL)
