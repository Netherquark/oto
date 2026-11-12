"""Research helper for the doc agents: API-key-backed web/LLM calls.

Owns: turning an API key (from env or starter file) into a research callable
that agent-1/agent-2 can use. Falls back to a no-op when no key is present, so
the agents always run (with reduced content).

Public API: make_researcher(api_key, endpoint=None).
"""

from __future__ import annotations

import os
from typing import Callable, Optional

try:
    import requests
    _HAS_REQUESTS = True
except ImportError:  # pragma: no cover
    _HAS_REQUESTS = False


def _extract_api_key(starter_text: str = "") -> str:
    """Read an API key from the starter text or environment."""
    import re
    m = re.search(r"api_key:\s*(\S+)", starter_text)
    if m:
        val = m.group(1).strip()
        if val and not val.startswith("$"):
            return val
        if val.startswith("$"):
            return os.environ.get(val[1:], "")
    for var in ("OTO_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        v = os.environ.get(var, "")
        if v:
            return v
    return ""


def make_researcher(api_key: str = "", starter_text: str = "",
                    endpoint: Optional[str] = None) -> Callable[[str], str]:
    """Return a research callable. No-op when no key/requests available."""
    key = api_key or _extract_api_key(starter_text)
    ep = endpoint or os.environ.get("OTO_API_ENDPOINT",
                                    "https://api.openai.com/v1/chat/completions")

    def research(query: str) -> str:
        if not key or not _HAS_REQUESTS:
            return ""
        try:
            resp = requests.post(
                ep,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={"model": os.environ.get("OTO_API_MODEL", "gpt-4o-mini"),
                      "messages": [{"role": "user", "content": query}],
                      "max_tokens": 512},
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception:
            pass
        return ""

    return research
