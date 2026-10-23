#!/usr/bin/env python3
"""The dashboard's static assets: CSS and the two inline scripts.

Owns: every byte of the dashboard's presentation that is not data. They are
constants rather than code so the renderer stays readable and so a presentation
change is reviewed as a presentation change -- the emitted HTML depends on the
exact whitespace here, so any edit must be diffed against the rendered
dashboard.
Does NOT own: the document skeleton (report_html) or the section markup
(report_sections).
Public API: DASHBOARD_CSS, JS_THEME_INIT, JS_THEME_TOGGLE, JS_COLLAPSIBLE.
"""
 
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

            // Expand/collapse coverage groups in the coverage table
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

            // Expand all button (includes family groups)
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


#: The whole dashboard stylesheet. NOTE: the dark palette is declared twice --
#: once as an explicit ``[data-theme="dark"]`` override and again inside the
#: ``prefers-color-scheme`` media query. That duplication is deliberate and is
#: recorded in incomplete_work.md; collapsing it would change which theme wins
#: when an operator has explicitly pinned a light theme.
DASHBOARD_CSS = """
        :root {
            --font-sans: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif;
            --font-mono: "IBM Plex Mono", "Menlo", "DejaVu Sans Mono",
                          "Bitstream Vera Sans Mono", Courier, monospace;
            --background: #f4f4f4;
            --layer-01: #ffffff;
            --layer-02: #f4f4f4;
            --layer-03: #ffffff;
            --field: #f4f4f4;
            --text-primary: #161616;
            --text-secondary: #525252;
            --text-placeholder: #8d8d8d;
            --icon-primary: #525252;
            --border-subtle: #e0e0e0;
            --border-strong: #8d8d8d;
            --link-primary: #0f62fe;
            --interactive: #0f62fe;
            --interactive-hover: #0043ce;
            --focus: #0f62fe;
            --support-success: #24a148;
            --support-error: #da1e28;
            --support-info: #0f62fe;
            --support-warning: #8e6a00;
            --tag-success-bg: #defbe6;
            --tag-error-bg: #fff1f1;
            --tag-info-bg: #edf5ff;
            --tag-warning-bg: #fff8dd;
            --track: #e0e0e0;
            --hover-row: #e8e8e8;
            --viz-1: #0f62fe;
            --viz-2: #009d9a;
            color-scheme: light;
        }
        [data-theme="dark"] {
            --background: #161616;
            --layer-01: #262626;
            --layer-02: #393939;
            --layer-03: #525252;
            --field: #262626;
            --text-primary: #f4f4f4;
            --text-secondary: #c6c6c6;
            --text-placeholder: #8d8d8d;
            --icon-primary: #c6c6c6;
            --border-subtle: #393939;
            --border-strong: #6f6f6f;
            --link-primary: #78a9ff;
            --interactive: #0f62fe;
            --interactive-hover: #0043ce;
            --focus: #78a9ff;
            --support-success: #24a148;
            --support-error: #da1e28;
            --support-info: #78a9ff;
            --support-warning: #f1c21b;
            --tag-success-bg: #12261a;
            --tag-error-bg: #2d1214;
            --tag-info-bg: #0f2b4d;
            --tag-warning-bg: #33270a;
            --track: #393939;
            --hover-row: #252525;
            --viz-1: #78a9ff;
            --viz-2: #08bdba;
            color-scheme: dark;
        }
        @media (prefers-color-scheme: dark) {
            :root:not([data-theme="light"]) {
                --background: #161616;
                --layer-01: #262626;
                --layer-02: #393939;
                --layer-03: #525252;
                --field: #262626;
                --text-primary: #f4f4f4;
                --text-secondary: #c6c6c6;
                --text-placeholder: #8d8d8d;
                --icon-primary: #c6c6c6;
                --border-subtle: #393939;
                --border-strong: #6f6f6f;
                --link-primary: #78a9ff;
                --interactive: #0f62fe;
                --interactive-hover: #0043ce;
                --focus: #78a9ff;
                --support-success: #24a148;
                --support-error: #da1e28;
                --support-info: #78a9ff;
                --support-warning: #f1c21b;
                --tag-success-bg: #12261a;
                --tag-error-bg: #2d1214;
                --tag-info-bg: #0f2b4d;
                --tag-warning-bg: #33270a;
                --track: #393939;
                --hover-row: #252525;
                --viz-1: #78a9ff;
                --viz-2: #08bdba;
            }
        }
        * { box-sizing: border-box; }
        html, body { margin: 0; padding: 0; }
        body {
            background: var(--background);
            color: var(--text-primary);
            font-family: var(--font-sans);
            font-size: 14px;
            line-height: 18px;
        }
        :focus-visible {
            outline: 2px solid var(--focus);
            outline-offset: 2px;
        }
        .shell {
            display: flex;
            align-items: center;
            justify-content: space-between;
            height: 48px;
            padding: 0 16px;
            border-bottom: 1px solid var(--border-subtle);
        }
        .shell-group { display: flex; align-items: baseline; gap: 12px; }
        .shell-title { font-size: 14px; font-weight: 600; color: var(--text-primary); }
        .shell-sub { font-size: 12px; color: var(--text-secondary); }
        .shell-actions { display: flex; align-items: center; gap: 8px; }
        .theme-toggle {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 32px;
            height: 32px;
            padding: 0;
            border: none;
            background: transparent;
            font-family: var(--font-sans);
            font-size: 16px;
            line-height: 1;
            color: var(--text-primary);
            cursor: pointer;
        }
        .page { padding: 16px; max-width: 1280px; margin: 0 auto; }
        .page-title {
            margin: 24px 0 4px 0;
            font-size: 20px;
            line-height: 28px;
            font-weight: 600;
            color: var(--text-primary);
        }
        .page-sub { margin: 0 0 24px 0; font-size: 14px; color: var(--text-secondary); }
        .metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }
        .metric {
            background: var(--layer-01);
            border: 1px solid var(--border-subtle);
            padding: 8px 16px;
        }
        .metric-label { font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-bottom: 2px; }
        .metric-value {
            font-size: 20px;
            line-height: 28px;
            font-weight: 400;
            color: var(--text-primary);
            font-variant-numeric: tabular-nums;
        }
        .section {
            background: var(--layer-01);
            margin-bottom: 16px;
        }
        .section-title {
            margin: 0;
            padding: 12px 16px;
            font-size: 14px;
            font-weight: 600;
            color: var(--text-primary);
            border-bottom: 1px solid var(--border-subtle);
        }
        .table-wrap { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 14px; }
        thead th {
            text-align: left;
            font-size: 12px;
            font-weight: 600;
            color: var(--text-primary);
            padding: 8px 16px;
            background: var(--layer-02);
            border-bottom: 2px solid var(--border-strong);
            white-space: nowrap;
        }
        tbody td {
            padding: 6px 16px;
            border-bottom: 1px solid var(--border-subtle);
            color: var(--text-primary);
            vertical-align: middle;
        }
        tbody tr:last-child td { border-bottom: none; }
        tbody tr:hover { background: var(--hover-row); }
        .mono { font-family: var(--font-mono); }
        .mono.strong { font-weight: 600; }
        .num {
            font-family: var(--font-sans);
            text-align: right;
            font-variant-numeric: tabular-nums;
        }
        .num.strong { font-weight: 600; color: var(--text-primary); }
        .num.secondary { color: var(--text-secondary); }
        code {
            font-family: var(--font-mono);
            font-size: 12px;
            color: var(--text-secondary);
        }
        .tag {
            display: inline-flex;
            align-items: center;
            font-size: 12px;
            font-weight: 600;
            line-height: 16px;
            padding: 2px 8px;
            white-space: nowrap;
        }
        .tag-pass { color: var(--support-success); background: var(--tag-success-bg); }
        .tag-fail { color: var(--support-error); background: var(--tag-error-bg); }
        .tag-win { color: var(--support-success); background: var(--tag-success-bg); }
        .tag-tie { color: var(--support-info); background: var(--tag-info-bg); }
        .tag-loss { color: var(--support-error); background: var(--tag-error-bg); }
        .tag-orange { color: var(--support-warning); background: var(--tag-warning-bg); }
        .section-note {
            margin: 0;
            padding: 12px 16px;
            font-size: 14px;
            line-height: 20px;
            color: var(--text-secondary);
            border-bottom: 1px solid var(--border-subtle);
        }
        .section-note strong { color: var(--text-primary); font-weight: 600; }
        tbody th[scope="row"], tbody th[scope="rowgroup"] {
            padding: 6px 16px;
            border-bottom: 1px solid var(--border-subtle);
            text-align: left;
            vertical-align: middle;
        }
        .family-row > *, .group-row > th {
            background: var(--layer-02);
            border-bottom: 1px solid var(--border-subtle);
        }
        .family-row > th, .group-row > th { font-weight: 600; }
        tbody th[scope="row"] { padding-left: 32px; font-weight: 400; }
        .group-row > th { padding: 8px 16px; }
        .group-row .group-name { margin-right: 12px; }
        .group-row .group-meta { font-weight: 400; color: var(--text-secondary); }
        tbody.family-group + tbody.family-group > tr:first-child > *,
        tbody.coverage-group + tbody.coverage-group > tr:first-child > * {
            border-top: 2px solid var(--border-strong);
        }
        .figure-appendix {
            margin-top: 12px;
            border: 1px solid var(--border-subtle);
            background: var(--layer-01);
        }
        .figure-appendix > summary { padding: 12px 16px; cursor: pointer; }
        .figure-appendix-title { font-weight: 600; }
        .figure-appendix-meta {
            display: block;
            padding-left: 20px;
            color: var(--text-secondary);
            font-size: 12px;
        }
        .figure-appendix-body {
            padding: 16px;
            border-top: 1px solid var(--border-subtle);
        }
        .figure-family + .figure-family {
            margin-top: 16px;
            border-top: 1px solid var(--border-subtle);
            padding-top: 16px;
        }
        .figure-family > summary {
            cursor: pointer;
            user-select: none;
            padding: 8px 0;
            list-style: none;
            font-size: 14px;
            line-height: 18px;
            font-weight: 600;
        }
        .figure-family > summary::-webkit-details-marker { display: none; }
        .figure-family > summary::before {
            content: "\\25B8";
            margin-right: 8px;
            font-size: 10px;
            color: var(--icon-primary);
        }
        .figure-family[open] > summary::before {
            content: "\\25BE";
        }
        .figure-family-title {
            display: inline;
            margin: 0 0 8px 0;
            font-size: 14px;
            line-height: 18px;
            font-weight: 600;
        }
        .figure-family .secondary {
            margin-left: 8px;
            font-weight: 400;
            color: var(--text-secondary);
        }
        .figure-family > .figure-grid {
            margin-top: 8px;
        }
        .figure-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(460px, 1fr));
            gap: 16px;
            padding: 16px;
        }
        .figure {
            margin: 0;
            border: 1px solid var(--border-subtle);
            background: var(--layer-01);
        }
        .figure img {
            display: block;
            width: 100%;
            height: auto;
            background: #ffffff;
        }
        .figure figcaption {
            padding: 8px 12px;
            font-size: 12px;
            line-height: 16px;
            color: var(--text-secondary);
            border-top: 1px solid var(--border-subtle);
        }
        .bar-wrap { display: inline-flex; align-items: center; gap: 4px; }
        .bar {
            display: inline-block;
            position: relative;
            width: 96px;
            height: 6px;
            background: var(--track);
            overflow: hidden;
        }
        .bar-fill { display: block; height: 100%; }
        .bar-viz1 { background: var(--viz-1); }
        .bar-viz2 { background: var(--viz-2); }
        .bar-marker {
            position: absolute;
            top: 0;
            bottom: 0;
            width: 2px;
            margin-left: -1px;
            background: var(--text-secondary);
            opacity: 0.65;
        }
        .bar-label {
            font-family: var(--font-sans);
            font-size: 12px;
            font-variant-numeric: tabular-nums;
            color: var(--text-primary);
        }
        /* Collapsible coverage groups */
        tbody.coverage-group[data-collapsed="true"] .coverage-row {
            display: none;
        }
        tbody.coverage-group[data-collapsed="false"] .group-row th::after {
            content: " \\25BE";
            font-size: 10px;
            color: var(--icon-primary);
        }
        tbody.coverage-group[data-collapsed="true"] .group-row th::after {
            content: " \\25B8";
            font-size: 10px;
            color: var(--icon-primary);
        }
        tbody.coverage-group .group-row {
            cursor: pointer;
            user-select: none;
        }
        /* Collapsible sections */
        .section.collapsible {
            border: 1px solid var(--border-subtle);
        }
        .section.collapsible > .section-title {
            cursor: pointer;
            user-select: none;
            padding-right: 32px;
            position: relative;
        }
        .section.collapsible > .section-title::after {
            content: "\\25BE";
            position: absolute;
            right: 12px;
            top: 50%;
            transform: translateY(-50%);
            font-size: 10px;
            color: var(--icon-primary);
            transition: transform 0.15s ease;
        }
        .section.collapsible[data-collapsed="true"] > .section-title::after {
            transform: translateY(-50%) rotate(-90deg);
        }
        .section.collapsible > .section-body {
            overflow: hidden;
        }
        .section.collapsible[data-collapsed="true"] > .section-body {
            display: none;
        }
        .section.collapsible:focus-within > .section-title {
            outline: 2px solid var(--focus);
            outline-offset: -2px;
        }
        /* Collapsible family groups */
        tbody.family-group[data-collapsed="true"] .size-row {
            display: none;
        }
        tbody.family-group[data-collapsed="false"] .family-row th::after {
            content: " \\25BE";
            font-size: 10px;
            color: var(--icon-primary);
        }
        tbody.family-group[data-collapsed="true"] .family-row th::after {
            content: " \\25B8";
            font-size: 10px;
            color: var(--icon-primary);
        }
        tbody.family-group .family-row {
            cursor: pointer;
            user-select: none;
        }
        /* Collapsible coverage groups */
        tbody.coverage-group[data-collapsed="true"] .coverage-row {
            display: none;
        }
        tbody.coverage-group[data-collapsed="false"] .group-row th::after {
            content: " \\25BE";
            font-size: 10px;
            color: var(--icon-primary);
        }
        tbody.coverage-group[data-collapsed="true"] .group-row th::after {
            content: " \\25B8";
            font-size: 10px;
            color: var(--icon-primary);
        }
        tbody.coverage-group .group-row {
            cursor: pointer;
            user-select: none;
        }
        /* Collapsible sections */
        .section.collapsible {
            border: 1px solid var(--border-subtle);
        }
        .section.collapsible > .section-title {
            cursor: pointer;
            user-select: none;
            padding-right: 32px;
            position: relative;
        }
        .section.collapsible > .section-title::after {
            content: "\\25BE";
            position: absolute;
            right: 12px;
            top: 50%;
            transform: translateY(-50%);
            font-size: 10px;
            color: var(--icon-primary);
            transition: transform 0.15s ease;
        }
        .section.collapsible[data-collapsed="true"] > .section-title::after {
            transform: translateY(-50%) rotate(-90deg);
        }
        .section.collapsible > .section-body {
            overflow: hidden;
        }
        .section.collapsible[data-collapsed="true"] > .section-body {
            display: none;
        }
        .section.collapsible:focus-within > .section-title {
            outline: 2px solid var(--focus);
            outline-offset: -2px;
        }
        .empty {
            padding: 24px 16px;
            text-align: center;
            color: var(--text-secondary);
        }
        /* Collapsible family groups in the family matrix */
        tbody.family-group[data-collapsed="true"] .size-row {
            display: none;
        }
        tbody.family-group[data-collapsed="false"] .family-row th::after {
            content: " \\25BE";
            font-size: 10px;
            color: var(--icon-primary);
        }
        tbody.family-group[data-collapsed="true"] .family-row th::after {
            content: " \\25B8";
            font-size: 10px;
            color: var(--icon-primary);
        }
        tbody.family-group .family-row {
            cursor: pointer;
            user-select: none;
        }
        @media (max-width: 640px) {
            .metrics { grid-template-columns: 1fr 1fr; }
            .shell { padding: 0 8px; }
            .figure-grid { grid-template-columns: 1fr; }
            .group-row .group-meta { display: block; margin: 2px 0 0 0; }
            .figure-appendix-meta { padding-left: 0; }
            .page { padding: 8px; }
            thead th, tbody td, tbody th[scope="row"], tbody th[scope="rowgroup"] {
                padding-left: 8px;
                padding-right: 8px;
            }
            tbody th[scope="row"] { padding-left: 20px; }
        }
        """
 
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

            // Expand/collapse coverage groups in the coverage table
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

            // Expand all button (includes family groups)
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

            // Expand/collapse coverage groups in the coverage table
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

            // Expand all button (includes family groups)
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

            // Expand/collapse coverage groups in the coverage table
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

            // Expand all button (includes family groups)
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
