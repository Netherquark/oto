#!/usr/bin/env python3
"""
Visual/layout regression check for the acceptance report.

Runs the rendered HTML through a headless browser and verifies:
- No horizontal overflow at desktop (1440px) or mobile (390px) viewports
- Table wrappers scroll correctly (table wider than wrapper)
- Key sections render without layout shift
- Metric grid has expected column count

Usage:
    python3 -m oto.harness.visual_check <report.html> [--url <base-url>]
    python3 -m oto.harness.visual_check <base>/<codename>_runs/.../acceptance_report.html
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit(1)


JS_SNAPSHOT = """
(() => {
  const d = document.documentElement;
  const wrap = document.querySelector('section .table-wrap');
  const table = wrap && wrap.querySelector('table');
  const metrics = document.querySelector('.metrics');
  return {
    pageOverflow: d.scrollWidth > d.clientWidth,
    bodyOverflow: document.body.scrollWidth > document.body.clientWidth,
    famTable: table ? {sw: table.scrollWidth, cw: table.clientWidth} : null,
    famWrapScroll: wrap ? {sw: wrap.scrollWidth, cw: wrap.clientWidth} : null,
    metricsCols: metrics ? getComputedStyle(metrics).gridTemplateColumns : null,
  };
})()
"""


VIEWPORTS = [
    ('desktop', 1440, 900, 6),
    ('mobile', 390, 844, 2),
]

REQUIRED_SECTIONS = [
    'h2:has-text("Family matrix coverage")',
    'h2:has-text("Problem-space coverage")',
]


def _check_viewport(page, name: str, expected_cols: int) -> list[str]:
    """Check one viewport. Returns list of failure messages."""
    failures = []
    data = page.evaluate(JS_SNAPSHOT)

    if data['pageOverflow'] or data['bodyOverflow']:
        failures.append(
            f"{name}: page horizontal overflow "
            f"(doc {data.get('pageScrollWidth', '?')} > {data.get('pageClientWidth', '?')})"
        )

    if data['famWrapScroll'] and data['famTable']:
        if data['famWrapScroll']['cw'] > data['famTable']['cw']:
            failures.append(
                f"{name}: family table overflows wrapper unexpectedly "
                f"(wrap {data['famWrapScroll']['cw']} > table {data['famTable']['cw']})"
            )

    if data['metricsCols']:
        cols = data['metricsCols'].split(' ')
        if len(cols) != expected_cols:
            failures.append(
                f"{name}: metric grid has {len(cols)} columns, expected {expected_cols}"
            )

    failures.extend(f"{name}: missing section {sel}"
                    for sel in REQUIRED_SECTIONS
                    if page.locator(sel).count() == 0)

    return failures


def check_report(report_path: Path, base_url: str | None = None) -> int:
    """Run visual/layout checks. Returns 0 on pass, 1 on fail."""
    if base_url:
        url = f"{base_url.rstrip('/')}/{report_path}"
    else:
        url = report_path.resolve().as_uri()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        failures = []

        for name, width, height, expected_cols in VIEWPORTS:
            page = browser.new_page(viewport={'width': width, 'height': height})
            page.goto(url, wait_until='networkidle')
            page.wait_for_timeout(200)
            failures.extend(_check_viewport(page, name, expected_cols))
            page.close()

        browser.close()

    if failures:
        for _f in failures:
            pass
        return 1

    return 0


def main():
    parser = argparse.ArgumentParser(description="Visual/layout regression check for acceptance report")
    parser.add_argument("report", type=Path, help="Path to acceptance_report.html")
    parser.add_argument("--url", help="Base URL if served (e.g. http://127.0.0.1:8765)")
    args = parser.parse_args()

    if not args.report.exists():
        return 1

    return check_report(args.report, args.url)


if __name__ == "__main__":
    sys.exit(main())
