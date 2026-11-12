"""Research helper for the doc agents: API-key-backed web/LLM calls.

Owns: turning an API key (from env or starter file) into a research callable
that agent-1/agent-2 can use. Falls back to a no-op when no key is present, so
the agents always run (with reduced content).

Provider auto-detect (``OTO_API_ENDPOINT`` always wins):
  - key starting with ``sk-ant-`` (or ``ANTHROPIC_API_KEY``)  -> Anthropic
    Messages API with the server-side web search tool enabled.
  - key starting with ``pplx-``                                -> Perplexity
    OpenAI-compatible chat completions (web-search backed, ``sonar``).
  - anything else (``OPENAI_API_KEY`` and friends)             -> OpenAI chat
    completions with the search-backed ``gpt-4o-mini-search-preview``
    default model.
  - ``OTO_API_MODEL`` overrides the provider default everywhere.

Never writes the key anywhere. Non-200 responses collapse to "" (with a
status-code-only warning on stderr); research is best-effort by design.

Public API: make_researcher(api_key, starter_text="", endpoint=None).
"""

from __future__ import annotations

import os
import sys
from typing import Callable, Optional, Tuple

try:
    import requests
    _HAS_REQUESTS = True
except ImportError:  # pragma: no cover
    _HAS_REQUESTS = False

_DEFAULT_OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
_PERPLEXITY_ENDPOINT = "https://api.perplexity.ai/chat/completions"
_ANTHROPIC_WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search",
                              "max_uses": 8}


def _extract_api_key(starter_text: str = "") -> Tuple[str, str]:
    """Read an API key from the starter text or environment.

    Returns ``(key, source)`` where source is one of ``starter``,
    ``OTO_API_KEY``, ``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY`` or ``""``.
    """
    import re
    m = re.search(r"api_key:\s*(\S+)", starter_text)
    if m:
        val = m.group(1).strip()
        if val and not val.startswith("$"):
            return val, "starter"
        if val.startswith("$"):
            return os.environ.get(val[1:], ""), "starter"
    for var in ("OTO_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        v = os.environ.get(var, "")
        if v:
            return v, var
    return "", ""


def _provider(key: str, source: str) -> str:
    if key.startswith("sk-ant-"):
        return "anthropic"
    if key.startswith("pplx-"):
        return "perplexity"
    if source == "ANTHROPIC_API_KEY":
        return "anthropic"
    if source == "OPENAI_API_KEY":
        return "openai"
    if source == "OTO_API_KEY":
        # Unknown bearer token: assume OpenAI-compatible (same as the
        # pre-auto-detect behaviour), the endpoint decides the rest.
        return "openai"
    return "none"  # no key


def _openai_compatible_research(key: str, endpoint: str, model: str,
                                query: str, timeout: int) -> str:
    resp = requests.post(
        endpoint,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        json={"model": model,
              "messages": [{"role": "user", "content": query}],
              "max_tokens": int(os.environ.get("OTO_API_MAX_TOKENS", "2048"))},
        timeout=timeout,
    )
    if resp.status_code != 200:
        print(f"research: HTTP {resp.status_code} from {endpoint}", file=sys.stderr)
        return ""
    data = resp.json()
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "")


def _anthropic_research(key: str, model: str, query: str, timeout: int) -> str:
    resp = requests.post(
        _ANTHROPIC_ENDPOINT,
        headers={"x-api-key": key,
                 "anthropic-version": "2023-06-01",
                 "Content-Type": "application/json"},
        json={"model": model,
              "max_tokens": int(os.environ.get("OTO_API_MAX_TOKENS", "2048")),
              "messages": [{"role": "user", "content": query}],
              "tools": [_ANTHROPIC_WEB_SEARCH_TOOL]},
        timeout=timeout,
    )
    if resp.status_code != 200:
        print(f"research: HTTP {resp.status_code} from Anthropic", file=sys.stderr)
        return ""
    blocks = resp.json().get("content", [])
    return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()


def make_researcher(api_key: str = "", starter_text: str = "",
                    endpoint: Optional[str] = None) -> Callable[[str], str]:
    """Return a research callable. No-op when no key/requests available."""
    if api_key:
        key, source = api_key, "arg"
    else:
        key, source = _extract_api_key(starter_text)
    ep = endpoint or os.environ.get("OTO_API_ENDPOINT", "")
    model_override = os.environ.get("OTO_API_MODEL", "")
    timeout = int(os.environ.get("OTO_API_TIMEOUT", "60"))

    def research(query: str) -> str:
        if not key or not _HAS_REQUESTS:
            return ""
        try:
            if ep:
                model = model_override or ("sonar" if "perplexity" in ep else
                                           "gpt-4o-mini-search-preview")
                return _openai_compatible_research(key, ep, model, query, timeout)
            provider = _provider(key, source)
            if provider == "anthropic":
                return _anthropic_research(key, model_override or "claude-sonnet-4-5",
                                           query, timeout)
            if provider == "perplexity":
                return _openai_compatible_research(
                    key, _PERPLEXITY_ENDPOINT, model_override or "sonar",
                    query, timeout)
            if provider == "openai":
                return _openai_compatible_research(
                    key, _DEFAULT_OPENAI_ENDPOINT,
                    model_override or "gpt-4o-mini-search-preview",
                    query, timeout)
        except Exception as exc:
            print(f"research: {exc.__class__.__name__}", file=sys.stderr)
        return ""

    return research
