"""Machine-readable docs ecosystem index for agentic routing.

Owns: generating and loading a JSON index of the docs ecosystem registry
(`docs/README.md`), so Class A (developer) and Class B (operator) agents can
discover which documents to read without parsing Markdown tables.

Does NOT own: the registry itself (docs/README.md), the docstrings (oto/**/*.py),
or the agent logic (oto/agents/*).

Public API: build_index, load_index, AGENT_CLASSES, doc_for_class.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "docs" / "README.md"
INDEX_PATH = ROOT / "docs" / "docs_index.json"

AGENT_CLASSES = {
    "A": {
        "name": "developer",
        "entry": "claude.md",
        "description": "Coding agent working on oto itself.",
        "reads": ["claude.md", "docs/agent_reference.md", "docs/docstrings.md",
                  "docs/harness_runbook.md", "docs/implementation_plan.md"],
        "never_needs": ["docs/operator_runbook.md", "docs/starter_*.md"],
        "tools": ["pytest", "ruff", "pyflakes", "generate_candidates", "check_candidates"],
    },
    "B": {
        "name": "operator",
        "entry": "docs/operator_runbook.md",
        "description": "Agent using oto to produce a best-effort library for an unsupported AMD platform.",
        "reads": ["docs/operator_runbook.md", "docs/starter_pair.md",
                  "docs/starter_template.md", "docs/gfx902_starter.md"],
        "never_needs": ["docs/implementation_plan.md", "docs/harness_runbook.md"],
        "must_not_write": ["oto/**/*.py", "tests/**/*.py", "*.py (root shims)"],
        "tools": ["oto doctor", "oto status", "oto tune", "oto library best-effort",
                  "oto check candidates", "oto verify all"],
    },
}


def _parse_registry(path: Path) -> list[dict[str, str]]:
    """Parse the Markdown table in docs/README.md into a list of doc entries."""
    entries: list[dict[str, str]] = []
    in_table = False
    for line in path.read_text().splitlines():
        if line.startswith("| File | Class |"):
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and line.startswith("|"):
            parts = [p.strip() for p in line.strip().strip("|").split("|")]
            if len(parts) >= 4 and parts[0] and parts[0] != "File":
                # strip backticks
                file_pat = parts[0].strip("`")
                cls = parts[1]
                kind = parts[2]
                owns = parts[3]
                entries.append({
                    "pattern": file_pat,
                    "class": cls,
                    "kind": kind,
                    "owns": owns,
                })
            continue
        if in_table and line.strip() == "":
            # blank line inside the table (formatting) — skip, don't end
            continue
        if in_table and not line.startswith("|"):
            in_table = False
    return entries


def _expand_globs(pattern: str, root: Path) -> list[str]:
    """Expand a registry pattern (may contain * or **) into tracked file paths."""
    import fnmatch
    import subprocess
    try:
        out = subprocess.run(["git", "ls-files", "*.md"], cwd=root,
                             capture_output=True, text=True, timeout=10)
        tracked = [ln for ln in out.stdout.splitlines() if ln.strip()]
    except Exception:
        tracked = [str(pp.relative_to(root)) for pp in root.rglob("*.md")
                   if ".git" not in str(pp)]
    tracked = sorted(set(tracked))
    if "*" in pattern:
        return [t for t in tracked if fnmatch.fnmatch(t, pattern)]
    return [pattern] if pattern in tracked else []


def build_index(root: Path | None = None) -> dict[str, Any]:
    """Build the machine-readable docs index from the registry."""
    root = root or ROOT
    registry = _parse_registry(root / "docs" / "README.md")
    docs: list[dict[str, Any]] = []
    for entry in registry:
        files = _expand_globs(entry["pattern"], root)
        docs.extend({
            "path": f,
            "class": entry["class"],
            "kind": entry["kind"],
            "owns": entry["owns"],
        } for f in files)
    # deduplicate by path
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for d in docs:
        if d["path"] not in seen:
            seen.add(d["path"])
            unique.append(d)
    return {
        "version": 1,
        "generated_from": "docs/README.md",
        "agent_classes": AGENT_CLASSES,
        "documents": unique,
        "total": len(unique),
    }


def load_index(path: Path | None = None) -> dict[str, Any]:
    """Load the pre-built index, or build it on the fly."""
    path = path or INDEX_PATH
    if path.exists():
        return json.loads(path.read_text())
    return build_index()


def doc_for_class(cls: str, root: Path | None = None) -> list[dict[str, Any]]:
    """Return the list of docs relevant to an agent class ('A' or 'B')."""
    idx = build_index(root)
    cls_name = "dev" if cls == "A" else "operator" if cls == "B" else cls
    return [d for d in idx["documents"]
                if d["class"] in (cls_name, "shared")]


def write_index(path: Path | None = None, root: Path | None = None) -> Path:
    """Write the index to disk. Returns the path written."""
    path = path or INDEX_PATH
    idx = build_index(root)
    path.write_text(json.dumps(idx, indent=2, sort_keys=True) + "\n")
    return path
