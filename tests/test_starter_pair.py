"""Tests for the starter Markdown+JSON pair and the agent research plumbing.

No network: every provider test mocks ``requests.post``. Written for R2-C4.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oto.agents import research
from oto.agents.orchestrator import run as meta_run
from oto.agents.research import make_researcher
from oto.device.loader import load_profile, load_profile_from_starter


def _profile_dict(codename: str) -> dict:
    data = json.loads((Path(__file__).resolve().parent.parent
                       / "profiles" / "gfx90c.json").read_text())
    data["codename"] = codename
    return data


def _write_pair(tmp_path: Path, codename: str) -> Path:
    md = tmp_path / "testbed_starter.md"
    md.write_text(f"# Testbed starter\n\ncodename: {codename}\n\nNarrative.\n")
    (tmp_path / "testbed_starter.json").write_text(json.dumps(_profile_dict(codename)))
    return md


def test_pair_loads_from_sibling_json(tmp_path):
    md = _write_pair(tmp_path, "testbed1")
    prof = load_profile_from_starter(md)
    assert prof.codename == "testbed1"
    # facts come from the JSON half of the pair, not from the markdown
    assert prof.num_cus == load_profile("gfx90c").num_cus


def test_pair_codename_mismatch_rejected(tmp_path):
    md = _write_pair(tmp_path, "testbed1")
    md.write_text("codename: wrongname\n")
    with pytest.raises(ValueError, match="mismatch"):
        load_profile_from_starter(md)


def test_fenced_json_still_loads(tmp_path):
    md = tmp_path / "fenced.md"
    md.write_text("```json\n" + json.dumps(_profile_dict("testbed2")) + "\n```\n")
    assert load_profile_from_starter(md).codename == "testbed2"


def test_starter_without_any_facts_fails_loudly(tmp_path):
    md = tmp_path / "empty.md"
    md.write_text("# nothing useful\n")
    with pytest.raises(ValueError):
        load_profile_from_starter(md)


class _Resp:
    def __init__(self, code, payload):
        self.status_code = code
        self._payload = payload

    def json(self):
        return self._payload


def test_anthropic_autodetect_with_web_search_tool(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, json=json)
        return _Resp(200, {"content": [{"type": "text", "text": "fact sheet"}]})

    monkeypatch.setattr(research.requests, "post", fake_post)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-testFAKEKEY000")
    monkeypatch.delenv("OTO_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = make_researcher()("research the testbed chip")
    assert out == "fact sheet"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-ant-testFAKEKEY000"
    tool = captured["json"]["tools"][0]
    assert tool["name"] == "web_search"


def test_perplexity_prefix_routes_to_sonar(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, json=json)
        return _Resp(200, {"choices": [{"message": {"content": "pplx facts"}}]})

    monkeypatch.setattr(research.requests, "post", fake_post)
    monkeypatch.setenv("OTO_API_KEY", "pplx-testFAKEKEY000")
    out = make_researcher()("q")
    assert out == "pplx facts"
    assert "perplexity" in captured["url"]
    assert captured["json"]["model"] == "sonar"


def test_openai_defaults_to_search_backed_model(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, json=json)
        return _Resp(200, {"choices": [{"message": {"content": "oai facts"}}]})

    monkeypatch.setattr(research.requests, "post", fake_post)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-testFAKEKEY000")
    monkeypatch.delenv("OTO_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = make_researcher()("q")
    assert out == "oai facts"
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["json"]["model"] == "gpt-4o-mini-search-preview"


def test_explicit_endpoint_and_model_override(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, json=json)
        return _Resp(200, {"choices": [{"message": {"content": "custom"}}]})

    monkeypatch.setattr(research.requests, "post", fake_post)
    monkeypatch.setenv("OTO_API_KEY", "tok-testFAKEKEY000")
    monkeypatch.setenv("OTO_API_ENDPOINT", "https://example.test/v1/chat/completions")
    monkeypatch.setenv("OTO_API_MODEL", "my-model")
    out = make_researcher()("q")
    assert out == "custom"
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["json"]["model"] == "my-model"


def test_no_key_is_a_clean_noop(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("network must not be touched without a key")

    monkeypatch.setattr(research.requests, "post", boom)
    for var in ("OTO_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert make_researcher()("q") == ""


def test_http_error_collapses_to_empty(monkeypatch):
    monkeypatch.setattr(research.requests, "post",
                        lambda *a, **kw: _Resp(500, {}))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-testFAKEKEY000")
    assert make_researcher()("q") == ""


def test_api_key_never_reaches_generated_docs(monkeypatch, tmp_path):
    """C4.3: key is used in headers only, never persisted into docs."""
    monkeypatch.setattr(research.requests, "post",
                        lambda *a, **kw: _Resp(200, {
                            "content": [{"type": "text", "text": "web facts"}]}))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-testFAKEKEYNEVERPERSIST")
    prof = load_profile("gfx90c")
    res = meta_run(prof, starter_text="codename: gfx90c",
                   research=make_researcher(starter_text="codename: gfx90c"))
    for doc in (res["theoretical_limits"], res["tuning_context"]):
        assert "sk-ant-testFAKEKEYNEVERPERSIST" not in doc


def test_gfx902_unverified_stub_refuses_to_load():
    """The committed gfx902 stub carries identity only (codename + ISA from
    LLVM's public docs); every silicon fact is zeroed, so the loader must
    refuse it until a human verifies and fills it."""
    md = Path(__file__).resolve().parent.parent / "docs" / "gfx902_starter.md"
    with pytest.raises(ValueError, match="unverified profile"):
        load_profile_from_starter(md)


def test_starter_template_refuses_to_load():
    md = Path(__file__).resolve().parent.parent / "docs" / "starter_template.md"
    with pytest.raises(ValueError, match="unverified profile"):
        load_profile_from_starter(md)
