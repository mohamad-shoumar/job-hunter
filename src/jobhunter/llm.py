"""Shared helpers for the model calls (ai_check.py, contacts.py, pitch.py, cv.py).

The rule they all follow: text the model returns is only trusted when code can
check it. `find_quote` checks a quote word for word against text the API itself
returned (a fetched page, a cited passage, a search result title), never
against text the model wrote.
"""

from __future__ import annotations

import re

# USD per million tokens (input, output), platform.claude.com/docs/en/models/overview,
# checked 2026-09-27. Only used for the cost estimates runs print.
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5": (2.0, 10.0), "claude-haiku-4-5": (1.0, 5.0),
          # api-docs.deepseek.com/quick_start/pricing, checked 2026-09-28, peak-hour cache-miss rates.
          "deepseek-flash": (0.3, 1.2), "deepseek-v4-flash": (0.3, 1.2), "deepseek-v4-pro": (1.32, 3.96)}
SEARCH_PRICE = 10.0 / 1000

# Models that reject a forced tool_choice ({"type": "tool"}) with a 400.
_NO_FORCED_TOOL = ("claude-opus-5-5", "claude-fable-5-1", "claude-mythos-5-1")


def plain(obj) -> dict:
    """SDK objects and test dicts alike, so new block types never break parsing."""
    if obj is None:
        return {}
    return obj if isinstance(obj, dict) else obj.model_dump()


def forced_tool_choice(model: str, name: str) -> dict:
    """Force a tool call where the model allows it; elsewhere `auto`, and the prompt asks for the call."""
    if model.startswith(_NO_FORCED_TOOL):
        return {"type": "auto"}
    return {"type": "tool", "name": name}


def _words(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.lower()))


def find_quote(quote: str, pages: list[tuple[str, str]], stated_url: str = "") -> str | None:
    """Where the quote appears word for word (case and punctuation ignored), or None.

    Fewer than three words proves nothing ("Remote" is on every page).
    """
    wanted = _words(quote)
    if wanted.count(" ") < 2:
        return None
    for url, text in sorted(pages, key=lambda page: page[0] != stated_url):
        if f" {wanted} " in f" {_words(text)} ":
            return url
    return None


def pages_read(blocks: list[dict], search_titles: bool = False):
    """(url, text) for everything the API itself returned from the web.

    search_titles adds each search result's title ("Jane Doe - CTO - Acme |
    LinkedIn"). The page text of a search result is encrypted, so for a
    search-only lookup the titles and cited passages are all there is.
    """
    for block in blocks:
        if block.get("type") == "web_fetch_tool_result":
            result = block.get("content") or {}
            source = (result.get("content") or {}).get("source") or {}
            if result.get("type") == "web_fetch_result" and source.get("type") == "text" and source.get("data"):
                yield result.get("url") or "", source["data"]
        elif block.get("type") == "web_search_tool_result" and search_titles:
            content = block.get("content")
            if isinstance(content, list):  # an error comes back as a single object
                for item in content:
                    if item.get("type") == "web_search_result" and item.get("title"):
                        yield item.get("url") or "", item["title"]
        elif block.get("type") == "text":
            # cited_text is extracted by the API from the page, not written by the model.
            for citation in block.get("citations") or []:
                if citation.get("cited_text") and citation.get("url"):
                    yield citation["url"], citation["cited_text"]


class Usage:
    def __init__(self) -> None:
        self.input = self.output = self.cache_write = self.cache_read = self.searches = 0

    def add(self, usage) -> None:
        u = plain(usage)
        self.input += u.get("input_tokens") or 0
        self.output += u.get("output_tokens") or 0
        self.cache_write += u.get("cache_creation_input_tokens") or 0
        self.cache_read += u.get("cache_read_input_tokens") or 0
        self.searches += (u.get("server_tool_use") or {}).get("web_search_requests") or 0

    def cost(self, model: str) -> float | None:
        price = next((p for name, p in PRICES.items() if model.startswith(name)), None)
        if price is None:
            return None
        per_in, per_out = price
        tokens = self.input * per_in + self.cache_write * per_in * 1.25 + self.cache_read * per_in * 0.1
        return round((tokens + self.output * per_out) / 1e6 + self.searches * SEARCH_PRICE, 4)


def model_params(model: str) -> dict:
    """Keep the call cheap: no thinking where it can be turned off, low effort where it cannot."""
    if model.startswith(("claude-opus-5-5", "claude-fable")):
        return {"output_config": {"effort": "low"}}
    if model.startswith(("claude-sonnet-5", "claude-opus-5")):
        return {"thinking": {"type": "disabled"}}
    return {}


DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"


# "claude-code" or "claude-code:<model>" ("claude-code:sonnet"): the Claude Code CLI (`claude -p`),
# signed in with your Claude account, so no ANTHROPIC_API_KEY is needed.
CLAUDE_CODE = "claude-code"
CLAUDE_CODE_TIMEOUT = 300
# Where the native installer puts it: launchd's PATH (the daily run) does not include it.
_CLAUDE_CODE_PLACES = ("~/.local/bin/claude", "~/.claude/local/claude")


def claude_code_bin() -> str | None:
    """The `claude` program: CLAUDE_CODE_BIN in .env, else PATH, else where the installer puts it."""
    import os
    import shutil

    for place in (os.environ.get("CLAUDE_CODE_BIN"), shutil.which("claude"), *_CLAUDE_CODE_PLACES):
        if place and os.access(os.path.expanduser(place), os.X_OK):
            return os.path.expanduser(place)
    return None


def run_claude_code(args: list[str], prompt: str, timeout: int) -> str:
    """Runs `claude -p` in an empty folder and returns what it printed. Tests replace this (conftest).

    Without ANTHROPIC_API_KEY in its environment, so it uses your Claude login and never bills the API key
    that .env may have for the other steps."""
    import os
    import subprocess
    import tempfile

    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    with tempfile.TemporaryDirectory() as folder:
        try:
            done = subprocess.run(args, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=folder,
                                  env=env)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"claude -p took longer than {timeout} seconds") from None
    if done.returncode and not done.stdout.strip():
        raise RuntimeError(f"claude -p failed ({done.returncode}): {' '.join(done.stderr.split())[:300]}")
    return done.stdout


def key_note(model: str, what: str) -> str | None:
    """Why `model` cannot be used right now (its API key is not set), or None."""
    import os

    if model.startswith(CLAUDE_CODE):
        return None if claude_code_bin() else (f"{what} needs the Claude Code CLI (`claude`): install it, "
                                               "or set CLAUDE_CODE_BIN in .env")
    name = "DEEPSEEK_API_KEY" if model.startswith("deepseek") else "ANTHROPIC_API_KEY"
    return None if os.environ.get(name) else f"{what} needs {name} in .env (the model is {model})"


class JsonModel:
    """One JSON object per call: Claude with the schema enforced, DeepSeek in JSON mode, or Claude Code.

    DeepSeek only promises valid JSON, not the schema, so callers check every
    field anyway. `example` (a JSON object in words) is added to DeepSeek's
    prompt, which JSON mode needs.
    """

    def __init__(self, model: str, claude=None, deepseek_key: str | None = None, http=None, tools: str = "",
                 timeout: int = CLAUDE_CODE_TIMEOUT):
        self.model = model
        self.claude = claude
        self._key = deepseek_key
        self._http = http
        # Claude Code only: built-in tools it may use without asking ("WebSearch,WebFetch"); empty means none.
        self.tools = tools
        self.timeout = timeout

    def ask(self, system: str, messages: list[dict], schema: dict, usage: Usage, example: str,
            max_tokens: int = 4096) -> dict:
        if self.model.startswith("deepseek"):
            return self._deepseek(system, messages, usage, example, max_tokens)
        if self.model.startswith(CLAUDE_CODE):
            return self._claude_code(system, messages, schema, usage)
        params = model_params(self.model)
        output_config = {**params.pop("output_config", {}), "format": {"type": "json_schema", "schema": schema}}
        response = self.claude.messages.create(model=self.model, max_tokens=max_tokens, system=system,
                                               messages=messages, output_config=output_config, **params)
        usage.add(response.usage)
        text = next((plain(b).get("text") for b in response.content if plain(b).get("type") == "text"), None)
        return _json_object(text)

    def _deepseek(self, system: str, messages: list[dict], usage: Usage, example: str, max_tokens: int) -> dict:
        if self._http is None:
            import httpx

            self._http = httpx.Client(timeout=180)
        body = {
            "model": self.model, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": f"{system}\n\nAnswer with one JSON object only, like:\n{example}"},
                         *messages],
            "response_format": {"type": "json_object"}, "thinking": {"type": "disabled"},
        }
        response = self._http.post(DEEPSEEK_URL, json=body, headers={"Authorization": f"Bearer {self._key}"})
        response.raise_for_status()  # the key is in a header, never in the error text
        data = response.json()
        tokens = data.get("usage") or {}
        usage.add({"input_tokens": tokens.get("prompt_tokens"), "output_tokens": tokens.get("completion_tokens")})
        try:
            return _json_object(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError):
            return {}

    def _claude_code(self, system: str, messages: list[dict], schema: dict, usage: Usage) -> dict:
        """One `claude -p` run with only `self.tools` and none of your settings, CLAUDE.md or memory.

        `-p` takes one prompt, so a retry sends the earlier turns as text."""
        import json

        _, _, model = self.model.partition(":")
        args = [claude_code_bin() or "claude", "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
                "--system-prompt", system, "--tools", self.tools, *(["--allowedTools", self.tools] if self.tools else []),
                "--setting-sources", "", "--strict-mcp-config",
                "--disable-slash-commands", "--no-session-persistence", *(["--model", model] if model else [])]
        out = run_claude_code(args, _as_one_prompt(messages), self.timeout)
        data = _json_object(out)
        if data.get("is_error") or not data:
            raise RuntimeError(f"claude -p: {' '.join(str(data.get('result') or out).split())[:300]}")
        usage.add(data.get("usage"))
        answer = data.get("structured_output")
        return answer if isinstance(answer, dict) else _json_object(data.get("result"))


def _as_one_prompt(messages: list[dict]) -> str:
    """The conversation as one prompt: the first message, then each answer and what was said back."""
    parts = []
    for n, message in enumerate(messages):
        if n == 0:
            parts.append(message["content"])
        elif message["role"] == "assistant":
            parts.append(f"Your answer was:\n{message['content']}")
        else:
            parts.append(message["content"])
    return "\n\n".join(parts)


def _json_object(text: str | None) -> dict:
    import json

    try:
        data = json.loads(text or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def json_model(model: str, what: str, claude=None) -> tuple[JsonModel | None, str | None]:
    """(the model, None), or (None, why it is off)."""
    import os

    note = key_note(model, what)
    if note:
        return None, note
    if model.startswith("deepseek"):
        return JsonModel(model, deepseek_key=os.environ["DEEPSEEK_API_KEY"]), None
    if model.startswith(CLAUDE_CODE):
        return JsonModel(model), None
    return JsonModel(model, claude=claude or anthropic_client()), None


def anthropic_client():
    """None when ANTHROPIC_API_KEY is not set, so callers can say why a step is off."""
    import os

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic

    return anthropic.Anthropic(max_retries=4, timeout=300)


def error_line(exc: Exception) -> str:
    # The key travels in a header, so it is never part of these messages.
    return " ".join(f"{type(exc).__name__}: {exc}".split())[:300]
