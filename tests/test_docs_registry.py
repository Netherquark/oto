"""Registry enforcement for the docs ecosystem.

docs/README.md is the class-tagged registry of owner documents. These tests
fail when a tracked Markdown file is not registered, when a registry entry
matches nothing on disk (stale row), or when a registry row lacks a Class.
"""

import fnmatch
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "docs" / "README.md"
CLASSES = ("dev", "operator", "shared")
GLOB_CHARS = "*?[]"


def _tracked_mds():
    out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    return sorted(p for p in out.splitlines() if p.endswith(".md"))


def _registry_md_tokens():
    return re.findall(r"`([^`\n]+?\.md)`", REGISTRY.read_text())


def _match(token, tracked):
    if any(c in token for c in GLOB_CHARS):
        return fnmatch.filter(tracked, token)
    return [p for p in tracked if p == token]


def test_every_tracked_md_is_registered():
    tracked = _tracked_mds()
    tokens = _registry_md_tokens()
    for p in tracked:
        assert any(p in _match(t, tracked) for t in tokens), (
            f"unregistered doc: {p} (add it to docs/README.md with a Class)")


def test_every_registry_entry_exists():
    tracked = _tracked_mds()
    for t in _registry_md_tokens():
        assert _match(t, tracked), f"registry entry matches no tracked file: {t}"


def test_registry_rows_carry_a_class():
    rows = [line for line in REGISTRY.read_text().splitlines()
            if line.startswith("| `") and ".md" in line]
    assert len(rows) >= 25
    for row in rows:
        assert any(f"| {c} |" in row for c in CLASSES), (
            f"registry row missing a Class tag: {row}")


def test_class_b_entry_routed_everywhere():
    registry = REGISTRY.read_text()
    claude = (ROOT / "claude.md").read_text()
    readme = (ROOT / "README.md").read_text()
    for text in (registry, claude, readme):
        assert "docs/operator/operator_runbook.md" in text
