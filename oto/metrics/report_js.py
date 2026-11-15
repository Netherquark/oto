#!/usr/bin/env python3
"""The dashboard report's inline JavaScript literals.

Owns: the JS_* script blocks the HTML report inlines (theme bootstrap, theme
toggle, collapsible sections). Split from report_css.py so the CSS and JS
literals each have one home; byte-for-byte identical to what was inline.
Does NOT own: the CSS (`oto.metrics.report_css`) or the HTML assembly.
Public API: JS_THEME_INIT, JS_THEME_TOGGLE, JS_COLLAPSIBLE.
"""

from __future__ import annotations

__all__ = ["JS_COLLAPSIBLE", "JS_THEME_INIT", "JS_THEME_TOGGLE"]

#: Collapsible section handler + expand-all button.

#: Theme bootstrap, run before first paint so there is no flash.
JS_THEME_INIT = """
        <script>
        (function () {
            var t = null;
            try { t = localStorage.getItem('report-theme'); } catch (e) {}
            var dark = t ? t === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
            document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
        })();
        </script>
        """

#: Collapsible section handler + expand-all button.

#: The theme-toggle button handler.
JS_THEME_TOGGLE = r"""
        <script>
        (function () {
            var btn = document.getElementById('theme-toggle');
            if (!btn) return;
            var SUN = '\u2600\uFE0E';
            var MOON = '\u263E';
            function update() {
                var dark = document.documentElement.getAttribute('data-theme') === 'dark';
                if (dark) {
                    btn.textContent = SUN;
                    btn.setAttribute('aria-label', 'Switch to light mode');
                } else {
                    btn.textContent = MOON;
                    btn.setAttribute('aria-label', 'Switch to dark mode');
                }
            }
            btn.addEventListener('click', function () {
                var dark = document.documentElement.getAttribute('data-theme') === 'dark';
                document.documentElement.setAttribute('data-theme', dark ? 'light' : 'dark');
                try { localStorage.setItem('report-theme', dark ? 'light' : 'dark'); } catch (e) {}
                update();
            });
            update();
        })();
        </script>
        """

#: Collapsible section handler + expand-all button.

#: Collapsible section handler + expand-all button.
JS_COLLAPSIBLE = r"""
        <script>
        (function () {
            // Expand/collapse section on title click
            document.querySelectorAll('.section.collapsible > .section-title').forEach(function (title) {
                title.addEventListener('click', function (e) {
                    if (e.target !== title) return;
                    var section = title.parentElement;
                    var collapsed = section.getAttribute('data-collapsed') === 'true';
                    section.setAttribute('data-collapsed', collapsed ? 'false' : 'true');
                    title.setAttribute('aria-expanded', collapsed ? 'true' : 'false');
                });
                title.addEventListener('keydown', function (e) {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        title.click();
                    }
                });
            });

            // Expand/collapse family groups in the family matrix
            document.querySelectorAll('tbody.family-group').forEach(function (group) {
                var header = group.querySelector('.family-row');
                if (header) {
                    header.addEventListener('click', function (e) {
                        var collapsed = group.getAttribute('data-collapsed') === 'true';
                        group.setAttribute('data-collapsed', collapsed ? 'false' : 'true');
                        header.setAttribute('aria-expanded', collapsed ? 'true' : 'false');
                    });
                    header.addEventListener('keydown', function (e) {
                        if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            header.click();
                        }
                    });
                }
            });

            // Expand/collapse coverage groups
            document.querySelectorAll('tbody.coverage-group').forEach(function (group) {
                var header = group.querySelector('.group-row');
                if (header) {
                    header.addEventListener('click', function (e) {
                        var collapsed = group.getAttribute('data-collapsed') === 'true';
                        group.setAttribute('data-collapsed', collapsed ? 'false' : 'true');
                        header.setAttribute('aria-expanded', collapsed ? 'true' : 'false');
                    });
                    header.addEventListener('keydown', function (e) {
                        if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            header.click();
                        }
                    });
                }
            });

            // Expand all button
            var expandBtn = document.getElementById('expand-all');
            if (expandBtn) {
                expandBtn.addEventListener('click', function () {
                    var allCollapsed = document.querySelectorAll('.section.collapsible[data-collapsed="true"]');
                    var isExpanding = allCollapsed.length > 0;
                    document.querySelectorAll('.section.collapsible').forEach(function (section) {
                        section.setAttribute('data-collapsed', isExpanding ? 'false' : 'true');
                        var title = section.querySelector('.section-title');
                        if (title) title.setAttribute('aria-expanded', isExpanding ? 'true' : 'false');
                    });
                    document.querySelectorAll('tbody.family-group').forEach(function (group) {
                        group.setAttribute('data-collapsed', isExpanding ? 'false' : 'true');
                        var header = group.querySelector('.family-row');
                        if (header) header.setAttribute('aria-expanded', isExpanding ? 'true' : 'false');
                    });
                    document.querySelectorAll('tbody.coverage-group').forEach(function (group) {
                        group.setAttribute('data-collapsed', isExpanding ? 'false' : 'true');
                        var header = group.querySelector('.group-row');
                        if (header) header.setAttribute('aria-expanded', isExpanding ? 'true' : 'false');
                    });
                    expandBtn.textContent = isExpanding ? '\u25B4' : '\u25BE';
                    expandBtn.setAttribute('aria-label', isExpanding ? 'Collapse all sections' : 'Expand all sections');
                });
            }
        })();
        </script>
        """

