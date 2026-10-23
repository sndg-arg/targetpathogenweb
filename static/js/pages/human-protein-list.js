/* Human Targets protein list: the same Filters and Columns drawers as the
 * pathogen protein list (proteins-list.js), on plain GET parameters. Filters
 * are chips over checkboxes/radios in one GET form, applied together; column
 * visibility is a per-browser convenience kept in localStorage.
 */
(function () {
    function setPanel(drawerId, overlayId, isOpen) {
        const drawer = document.getElementById(drawerId);
        const overlay = document.getElementById(overlayId);
        if (!drawer || !overlay) return;
        drawer.classList.toggle("open", isOpen);
        overlay.classList.toggle("open", isOpen);
        drawer.setAttribute("aria-hidden", isOpen ? "false" : "true");
    }

    function bindPanel(openId, closeId, drawerId, overlayId, onOpen) {
        const openBtn = document.getElementById(openId);
        const closeBtn = document.getElementById(closeId);
        const overlay = document.getElementById(overlayId);
        if (openBtn) {
            openBtn.addEventListener("click", function () {
                if (onOpen) onOpen();
                setPanel(drawerId, overlayId, true);
            });
        }
        [closeBtn, overlay].forEach(function (el) {
            if (el) el.addEventListener("click", function () { setPanel(drawerId, overlayId, false); });
        });
    }

    document.addEventListener("keydown", function (event) {
        if (event.key !== "Escape") return;
        setPanel("filters-drawer", "filters-overlay", false);
        setPanel("columns-modal", "columns-overlay", false);
    });

    // Rows per page: the select belongs to the search form.
    const pageSize = document.getElementById("human-page-size");
    if (pageSize && pageSize.form) {
        pageSize.addEventListener("change", function () { pageSize.form.submit(); });
    }

    // ---- Filters drawer ------------------------------------------------
    bindPanel("open-filters-btn", "close-filters-btn", "filters-drawer", "filters-overlay");
    const applyBtn = document.getElementById("filters-apply-btn");
    const chips = Array.prototype.slice.call(document.querySelectorAll(".human-filter-chip"));

    function syncChips() {
        let pending = 0;
        chips.forEach(function (chip) {
            const input = chip.querySelector("input");
            const wasOn = chip.dataset.serverActive === "true";
            chip.classList.toggle("filter-chip--active", input.checked);
            chip.classList.toggle("filter-chip--pending", input.checked !== wasOn);
            if (input.checked !== wasOn) pending += 1;
        });
        if (applyBtn) applyBtn.disabled = pending === 0;
    }

    chips.forEach(function (chip) {
        const input = chip.querySelector("input");
        if (input.type === "radio") {
            // A second click on the chosen option clears it (radios can't by default).
            let wasChecked = false;
            chip.addEventListener("pointerdown", function () { wasChecked = input.checked; });
            chip.addEventListener("click", function (event) {
                if (event.target !== input) return;
                if (wasChecked) input.checked = false;
                wasChecked = false;
                syncChips();
            });
        }
        input.addEventListener("change", syncChips);
    });

    const searchInput = document.getElementById("filter-search-input");
    const searchClear = document.getElementById("filter-search-clear");
    const noResults = document.getElementById("filter-search-no-results");
    const groups = Array.prototype.slice.call(document.querySelectorAll("[data-filter-group]"));

    function filterCatalogue() {
        const query = (searchInput.value || "").trim().toLowerCase();
        let matched = 0;
        groups.forEach(function (group) {
            let visible = false;
            group.querySelectorAll("[data-filter-param]").forEach(function (param) {
                const hit = !query || (param.dataset.searchText || "").indexOf(query) !== -1;
                param.classList.toggle("is-search-hidden", !hit);
                if (hit) visible = true;
            });
            group.classList.toggle("is-search-hidden", !visible);
            if (query && visible) group.open = true;
            if (visible) matched += 1;
        });
        if (noResults) noResults.hidden = matched !== 0;
        if (searchClear) searchClear.hidden = !query;
    }

    if (searchInput) searchInput.addEventListener("input", filterCatalogue);
    if (searchClear) {
        searchClear.addEventListener("click", function () {
            searchInput.value = "";
            filterCatalogue();
            searchInput.focus();
        });
    }

    const expandAll = document.getElementById("filter-expand-all");
    if (expandAll) {
        expandAll.addEventListener("click", function () {
            const expand = expandAll.dataset.expandAll !== "true";
            groups.forEach(function (group) { group.open = expand; });
            expandAll.dataset.expandAll = expand ? "true" : "false";
            const label = expandAll.querySelector("[data-expand-all-label]");
            if (label) label.textContent = expand ? expandAll.dataset.labelCollapse : expandAll.dataset.labelExpand;
        });
    }

    // ---- Columns drawer ------------------------------------------------
    const STORAGE_KEY = "tpw:human-protein-columns";
    const rows = Array.prototype.slice.call(document.querySelectorAll(".human-columns-row"));
    const meta = document.querySelector("[data-columns-meta]");
    const count = document.getElementById("columns-selected-count");
    const styleEl = document.createElement("style");
    document.head.appendChild(styleEl);

    function defaults() {
        return rows.filter(function (row) { return row.dataset.default !== "true"; })
            .map(function (row) { return row.dataset.columnName; });
    }

    function loadHidden() {
        try {
            const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY));
            if (Array.isArray(stored)) return stored;
        } catch (error) {
            /* storage unavailable or corrupt: use the defaults */
        }
        return defaults();
    }

    function saveHidden(hidden) {
        try {
            window.localStorage.setItem(STORAGE_KEY, JSON.stringify(hidden));
        } catch (error) {
            /* not remembered, still applied */
        }
    }

    function markRows(hidden) {
        rows.forEach(function (row) {
            const off = hidden.indexOf(row.dataset.columnName) !== -1;
            row.classList.toggle("is-hidden", off);
            const btn = row.querySelector("[data-columns-toggle]");
            btn.setAttribute("aria-pressed", off ? "false" : "true");
            btn.setAttribute("aria-label", off ? btn.dataset.labelShow : btn.dataset.labelHide);
            btn.title = btn.getAttribute("aria-label");
        });
        if (count) count.textContent = String(rows.length - hidden.length);
    }

    function applyHidden(hidden) {
        styleEl.textContent = hidden.map(function (name) {
            return '#human-proteins-table [data-col="' + name + '"]{display:none}';
        }).join("\n");
        if (meta) meta.textContent = (rows.length - hidden.length) + " " + meta.dataset.label;
        markRows(hidden);
    }

    function draftHidden() {
        return rows.filter(function (row) { return row.classList.contains("is-hidden"); })
            .map(function (row) { return row.dataset.columnName; });
    }

    applyHidden(loadHidden());
    // Reopening discards unapplied toggles.
    bindPanel("open-columns-btn", "close-columns-btn", "columns-modal", "columns-overlay", function () {
        markRows(loadHidden());
    });

    rows.forEach(function (row) {
        row.querySelector("[data-columns-toggle]").addEventListener("click", function () {
            row.classList.toggle("is-hidden");
            markRows(draftHidden());
        });
    });

    const restoreBtn = document.getElementById("columns-restore-btn");
    if (restoreBtn) restoreBtn.addEventListener("click", function () { markRows(defaults()); });

    const columnsApply = document.getElementById("columns-apply-btn");
    if (columnsApply) {
        columnsApply.addEventListener("click", function () {
            const hidden = draftHidden();
            saveHidden(hidden);
            applyHidden(hidden);
            setPanel("columns-modal", "columns-overlay", false);
        });
    }
})();
