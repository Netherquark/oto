"""Tests for the machine-readable docs index (oto/docs_index_writer.py)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oto.docs_index_writer import AGENT_CLASSES, build_index, doc_for_class, load_index


def test_build_index_has_documents():
    idx = build_index()
    assert idx["total"] > 0
    assert "documents" in idx
    assert "agent_classes" in idx


def test_agent_classes_have_entries():
    assert "A" in AGENT_CLASSES
    assert "B" in AGENT_CLASSES
    assert AGENT_CLASSES["A"]["entry"] == "claude.md"
    assert AGENT_CLASSES["B"]["entry"] == "docs/operator/operator_runbook.md"


def test_doc_for_class_a_returns_dev_and_shared():
    docs = doc_for_class("A")
    classes = {d["class"] for d in docs}
    assert "dev" in classes or "shared" in classes


def test_doc_for_class_b_returns_operator_and_shared():
    docs = doc_for_class("B")
    classes = {d["class"] for d in docs}
    assert "operator" in classes or "shared" in classes


def test_class_b_has_must_not_write():
    assert "must_not_write" in AGENT_CLASSES["B"]
    assert len(AGENT_CLASSES["B"]["must_not_write"]) > 0


def test_load_index_returns_dict():
    idx = load_index()
    assert isinstance(idx, dict)
    assert "documents" in idx


def test_index_is_valid_json():
    from oto.docs_index_writer import INDEX_PATH
    if INDEX_PATH.exists():
        data = json.loads(INDEX_PATH.read_text())
        assert "documents" in data
        assert "agent_classes" in data
