"""F-REPORT-4 — a degenerate analytics path must mark report provenance.

Two cases, both v1-relevant:

1. When no like-for-like analytics exist anywhere on the device,
   ``_report_inputs`` falls back to the unfiltered per-run walk, and the
   acceptance report's JSON payload must carry ``protocol_fallback: true``
   so a downstream reader never takes an all-zero grid for "clean coverage".
2. Every normal report carries ``protocol_fallback: false``.
"""

import json

from oto.metrics.acceptance_report import AcceptanceReporter


class TestProtocolFallbackFlag:
    def test_degenerate_report_marks_protocol_fallback(self, tmp_path):
        rep = AcceptanceReporter(tmp_path)
        report = rep.generate_acceptance_report(
            run_id="r1",
            ab_verdicts=[],
            all_analytics=[],
            red_list=[],
            protocol_fallback=True,
        )
        assert report.protocol_fallback is True
        out = tmp_path / "rep.json"
        rep.write_report(report, out)
        got = json.loads(out.read_text())
        assert got["protocol_fallback"] is True

    def test_normal_report_defaults_protocol_fallback_false(self, tmp_path):
        rep = AcceptanceReporter(tmp_path)
        report = rep.generate_acceptance_report(
            run_id="r1",
            ab_verdicts=[],
            all_analytics=[],
            red_list=[],
        )
        assert report.protocol_fallback is False
        out = tmp_path / "rep.json"
        rep.write_report(report, out)
        got = json.loads(out.read_text())
        assert got["protocol_fallback"] is False
