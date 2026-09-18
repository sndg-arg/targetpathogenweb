/* Table CSV export + horizontal-scroll hint pill -- present on every page
 * (loaded directly from masterpage.html, matching the existing plain-script
 * convention used by agent-drawer.js/nav-toggle.js).
 *
 * Reads translated copy from window.TPW_I18N (set by a small inline <script>
 * in masterpage.html, right before this file loads) instead of embedding a
 * {% trans %} call directly -- this file is a plain static asset, not a
 * Django template.
 */
(function () {
    function isElementVisible(element) {
        if (!element || element.hidden) return false;
        const style = window.getComputedStyle(element);
        return style.display !== "none" && style.visibility !== "hidden";
    }

    function tableFilename(table) {
        const rawTitle = table.dataset.exportTitle || document.title || "table";
        const normalized = rawTitle
            .toLowerCase()
            .replace(/[^a-z0-9._-]+/g, "-")
            .replace(/^-+|-+$/g, "");
        return (normalized || "table") + ".csv";
    }

    function visibleCells(row) {
        return Array.from(row.children).filter(isElementVisible);
    }

    function normalizedCellText(cell) {
        return (cell.textContent || "")
            .replace(/\s+/g, " ")
            .replace(/\u00a0/g, " ")
            .trim();
    }

    function collectVisibleTableRows(table) {
        const headerRow = table.tHead && table.tHead.rows.length
            ? table.tHead.rows[table.tHead.rows.length - 1]
            : null;
        const headers = headerRow
            ? visibleCells(headerRow).map(normalizedCellText)
            : [];

        const bodyRows = Array.from(table.tBodies || []).flatMap(function (tbody) {
            return Array.from(tbody.rows || []);
        }).filter(isElementVisible);

        const rows = bodyRows
            .map(function (row) {
                return visibleCells(row).map(normalizedCellText);
            })
            .filter(function (row) {
                return row.length > 0 && row.some(function (value) { return value.length > 0; });
            });

        return { headers: headers, rows: rows };
    }

    function downloadCsv(filename, headers, rows) {
        const csvRows = [];
        if (headers.length) {
            csvRows.push(headers);
        }
        rows.forEach(function (row) {
            csvRows.push(row);
        });
        const csv = csvRows.map(function (row) {
            return row.map(function (value) {
                const text = value == null ? "" : String(value);
                const escaped = text.replace(/"/g, "\"\"");
                return /[",\n]/.test(escaped) ? `"${escaped}"` : escaped;
            }).join(",");
        }).join("\n");
        const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8;" });
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        window.URL.revokeObjectURL(url);
    }

    function tableExportAction(event) {
        event.preventDefault();
        const button = event.currentTarget;
        if (button.classList.contains("is-disabled")) return;
        const table = document.querySelector(button.dataset.tableExportTarget);
        if (!table) return;

        const exportUrl = table.dataset.exportUrl;
        if (exportUrl) {
            window.location.href = exportUrl;
            return;
        }

        const payload = collectVisibleTableRows(table);
        downloadCsv(tableFilename(table), payload.headers, payload.rows);
    }

    function createExportButton(table, targetSelector) {
        const button = document.createElement(table.dataset.exportUrl ? "a" : "button");
        button.className = "tp-table-export-btn";
        button.innerHTML = [
            '<span class="tp-table-export-btn__icon" aria-hidden="true">',
            '<svg viewBox="0 0 16 16" width="16" height="16" focusable="false" aria-hidden="true">',
            '<path d="M8 2.5v7"></path>',
            '<path d="m5.25 7.75 2.75 2.75 2.75-2.75"></path>',
            '<path d="M3 12.25h10"></path>',
            '</svg>',
            '</span>',
            '<span class="tp-table-export-btn__label">Export CSV</span>',
        ].join("");
        button.dataset.tableExportTarget = targetSelector;
        if (button.tagName === "BUTTON") {
            button.type = "button";
        } else {
            button.href = table.dataset.exportUrl || "#";
        }
        const payload = collectVisibleTableRows(table);
        if (!table.dataset.exportUrl && payload.rows.length === 0) {
            button.classList.add("is-disabled");
            button.setAttribute("aria-disabled", "true");
        }
        button.addEventListener("click", tableExportAction);
        return button;
    }

    function initTableExports(root) {
        const scope = root || document;
        const tables = Array.from(scope.querySelectorAll("table.tp-table")).filter(function (table) {
            return table.dataset.tableExport !== "off" && !table.dataset.tableExportBound;
        });

        tables.forEach(function (table, index) {
            const host = table.closest(".tp-table-shell") || table.parentElement;
            if (!host) return;
            const content = (table.parentElement === host)
                ? table
                : (table.closest(".tp-dt-wrapper, .dataTables_wrapper") || table);

            if (!table.id) {
                table.id = "tp-table-export-" + index + "-" + Math.random().toString(36).slice(2, 8);
            }

            const bar = document.createElement("div");
            bar.className = "tp-table-export-bar";
            host.classList.add("tp-table-shell--with-export");
            if (host.dataset.tableScrollWrap === "off") {
                if (!host.contains(content)) {
                    host.appendChild(content);
                }
            } else {
                let scroll = host.querySelector(":scope > .tp-table-shell__scroll");
                if (!scroll) {
                    scroll = document.createElement("div");
                    scroll.className = "tp-table-shell__scroll";
                    host.appendChild(scroll);
                }
                if (!scroll.contains(content)) {
                    scroll.appendChild(content);
                }
            }
            bar.appendChild(createExportButton(table, "#" + table.id));
            host.insertBefore(bar, host.firstChild);
            table.dataset.tableExportBound = "1";
        });
    }

    window.tpInitTableExports = initTableExports;

    function refreshTableScrollHints(root) {
        const scope = root || document;
        const hosts = [];
        if (scope instanceof Element && scope.matches(".tp-table-shell")) {
            hosts.push(scope);
        }
        hosts.push.apply(hosts, Array.from(scope.querySelectorAll ? scope.querySelectorAll(".tp-table-shell") : []));

        hosts.forEach(function (host) {
            const scroll = host.querySelector(":scope > .tp-table-shell__scroll") || host;
            if (!scroll) return;

            let hint = host.querySelector(":scope > .tp-table-scroll-hint");
            if (!hint) {
                hint = document.createElement("div");
                hint.className = "tp-table-scroll-hint";
                hint.textContent = window.TPW_I18N.scrollHint;
                host.appendChild(hint);
            }

            const hasHorizontalOverflow = (scroll.scrollWidth - scroll.clientWidth) > 16;
            const atEnd = (scroll.scrollLeft + scroll.clientWidth) >= (scroll.scrollWidth - 4);
            const atStart = scroll.scrollLeft <= 4;

            host.classList.toggle("is-h-scrollable", hasHorizontalOverflow);
            host.classList.toggle("is-h-scroll-end", !hasHorizontalOverflow || atEnd);
            host.classList.toggle("is-h-scroll-start", atStart);
            hint.hidden = !hasHorizontalOverflow;

            if (!scroll.dataset.tpScrollHintBound) {
                scroll.addEventListener("scroll", function () {
                    refreshTableScrollHints(host);
                }, { passive: true });
                scroll.dataset.tpScrollHintBound = "1";
            }
        });
    }

    window.tpRefreshTableScrollHints = refreshTableScrollHints;
})();
