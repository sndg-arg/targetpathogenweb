/* Proteins-list page: filters drawer, saved presets, pending-changes
 * tracking, structure/EC/GO/ligand filter chips, formula/columns modals,
 * protein-search autocomplete. Reads translated copy from window.TPW_PROTEINS_I18N
 * and per-request state from window.TPW_PROTEINS_STATE (both set by a small
 * inline <script> in proteins.html, right before this file loads) instead of
 * embedding {% trans %}/{{ }} directly -- this file is a plain static asset,
 * not a Django template.
 */
function setDrawerState(isOpen) {
    const overlay = document.getElementById("filters-overlay");
    const drawer = document.getElementById("filters-drawer");
    if (!overlay || !drawer) return;
    overlay.classList.toggle("open", isOpen);
    drawer.classList.toggle("open", isOpen);
    drawer.setAttribute("aria-hidden", isOpen ? "false" : "true");
}

function setFormulaState(isOpen) {
    const overlay = document.getElementById("formula-overlay");
    const modal = document.getElementById("formula-modal");
    if (!overlay || !modal) return;
    overlay.classList.toggle("open", isOpen);
    modal.classList.toggle("open", isOpen);
    modal.setAttribute("aria-hidden", isOpen ? "false" : "true");
}

function setColumnsState(isOpen) {
    const overlay = document.getElementById("columns-overlay");
    const modal = document.getElementById("columns-modal");
    if (!overlay || !modal) return;
    overlay.classList.toggle("open", isOpen);
    modal.classList.toggle("open", isOpen);
    modal.setAttribute("aria-hidden", isOpen ? "false" : "true");
}

function jsloaded() {
    const searchForm = document.getElementById("protein-search-form");
    const pageSizeSelect = document.getElementById("pageSizeSelect");
    const structureSourceSelect = document.getElementById("structureSourceSelect");
    const pageSizeControl = document.querySelector(".per-page-control");
    const searchInput = document.getElementById("protein-search-input");
    const searchSubmitBtn = document.getElementById("protein-search-submit");
    const autocompleteRoot = document.getElementById("protein-search-autocomplete");
    const suggestionsBox = document.getElementById("protein-search-suggestions");
    const suggestUrl = autocompleteRoot ? autocompleteRoot.getAttribute("data-suggest-url") : "";
    const scoreFormulaSelect = document.getElementById("score_formula_select");
    const applyFormulaBtn = document.getElementById("apply-formula-btn");
    const filterSearchInput = document.getElementById("filter-search-input");
    const filterSearchClearBtn = document.getElementById("filter-search-clear");
    const filterCatalogue = document.getElementById("drawer-filter-catalogue");
    const filterExpandAllBtn = document.getElementById("filter-expand-all");
    const filterSearchNoResults = document.getElementById("filter-search-no-results");
    const filtersApplyForm = document.getElementById("filters-apply-form");
    const filtersApplyBtn = document.getElementById("filters-apply-btn");
    const filterPresetSaveForm = document.getElementById("filter-preset-save-form");
    const filterPendingSummary = document.getElementById("filter-pending-summary");
    const filterPendingCount = document.getElementById("filter-pending-count");
    const filterPendingList = document.getElementById("filter-pending-list");
    let suggestionsTimer = null;
    let suggestionRequestId = 0;
    let activeSuggestionIndex = -1;
    const AUTOCOMPLETE_CONFIG = Object.freeze({
        minChars: 2,
        debounceMs: 180,
        limit: 8,
        blurDelayMs: 120
    });
    const UI_TEXT = Object.freeze({
        suggestionRequestFailed: autocompleteRoot ? (autocompleteRoot.getAttribute("data-suggest-error") || "") : ""
    });
    const CURRENT_FILTER_STATE = Object.freeze({
        structureSource: window.TPW_PROTEINS_STATE.structureSource,
        annotationKind: window.TPW_PROTEINS_STATE.annotationKind,
        annotationValue: window.TPW_PROTEINS_STATE.annotationValue
    });
    // pendingToggleMap: keyed by filter_option_id, value = payload.
    // Clicking the same chip twice cancels the pending action.
    let pendingToggleMap = new Map();
    // pendingAppendEntries: non-toggleable (numeric, text, special-add), as
    // {id, payload, form} -- payload is exactly what gets JSON.stringify'd for
    // the server (see syncPendingFilterForms), so the form reference is kept
    // only in this wrapper, never merged into payload itself.
    let pendingAppendEntries = [];
    let nextPendingAppendId = 1;
    let pendingStructureSource = CURRENT_FILTER_STATE.structureSource;
    let pendingAnnotationKind = CURRENT_FILTER_STATE.annotationKind;
    let pendingAnnotationValue = CURRENT_FILTER_STATE.annotationValue;

    function getAllPendingActions() {
        return pendingAppendEntries.map(function (entry) { return entry.payload; })
            .concat(Array.from(pendingToggleMap.values()).map(function (entry) { return entry.payload; }));
    }

    function hasPendingChanges() {
        const structureChanged = (pendingStructureSource || "") !== (CURRENT_FILTER_STATE.structureSource || "");
        const annotationChanged = (pendingAnnotationKind || "") !== (CURRENT_FILTER_STATE.annotationKind || "")
            || (pendingAnnotationValue || "") !== (CURRENT_FILTER_STATE.annotationValue || "");
        return getAllPendingActions().length > 0 || structureChanged || annotationChanged;
    }

    // Set right before any navigation this page itself already asked
    // about (its own confirm() dialog, or a submission that actually
    // *resolves* the pending changes rather than discarding them) --
    // beforeunload below only needs to catch navigation nothing here
    // warned about yet (typing a URL, closing the tab, browser back).
    let suppressBeforeUnloadWarning = false;

    function confirmDiscardPending(message) {
        if (!hasPendingChanges()) return true;
        const confirmed = confirm(message);
        if (confirmed) suppressBeforeUnloadWarning = true;
        return confirmed;
    }

    function cleanPendingValue(value) {
        return String(value || "").trim().replace(",", ".");
    }

    function getFormParamLabel(form) {
        if (!form) return "";
        const explicit = (form.getAttribute("data-param-label") || "").trim();
        if (explicit) return explicit;
        const label = form.closest(".filter-param")?.querySelector(".filter-param-label");
        return label ? label.textContent.trim() : "";
    }

    function numericOperationLabel(operation) {
        if (operation === "lte") return "<=";
        if (operation === "between") return "between";
        return ">=";
    }

    function buildPendingActionLabel(payload, form) {
        const paramLabel = getFormParamLabel(form);
        if (payload.action === "add_numeric_filter") {
            const operation = payload.numeric_operation || "gte";
            const value = cleanPendingValue(payload.value);
            const valueMax = cleanPendingValue(payload.value_max);
            const base = operation === "between"
                ? paramLabel + ": " + value + " - " + valueMax
                : paramLabel + ": " + numericOperationLabel(operation) + " " + value;
            const activeLabel = form?.closest(".filter-param")?.querySelector(".filter-chip--active:not(.filter-chip--pending) .filter-chip-label")?.textContent.trim();
            return activeLabel ? base + " (" + window.TPW_PROTEINS_I18N.replaces + " " + activeLabel + ")" : base;
        }
        if (payload.action === "add_special_filter") {
            const value = String(payload.special_value || "").trim();
            return (paramLabel || payload.special_kind || window.TPW_PROTEINS_I18N.filter) + ": " + value;
        }
        if (payload.action === "remove_filter") {
            const chipLabel = form?.querySelector(".filter-chip-label")?.textContent.trim();
            return window.TPW_PROTEINS_I18N.remove + ": " + (chipLabel || paramLabel || window.TPW_PROTEINS_I18N.criterion);
        }
        if (payload.action === "add_filter") {
            const chipLabel = form?.querySelector(".filter-chip-label")?.textContent.trim();
            return (paramLabel ? paramLabel + ": " : "") + (chipLabel || window.TPW_PROTEINS_I18N.criterion);
        }
        return paramLabel || window.TPW_PROTEINS_I18N.filterChange;
    }

    function pendingActionLabel(payload) {
        return payload && payload._summary_label ? payload._summary_label : window.TPW_PROTEINS_I18N.filterChange;
    }

    let filtersToolbarMetaOriginal = null;

    function updateFiltersToolbarMeta(pendingCount) {
        // Looked up directly (not via the outer openFiltersBtn const) --
        // this runs from the eager syncPendingFilterForms() call near the
        // top of jsloaded(), before that const's declaration further down
        // the script would otherwise be initialized (TDZ ReferenceError).
        const btn = document.getElementById("open-filters-btn");
        if (!btn) return;
        const meta = btn.querySelector(".toolbar-action-btn__meta");
        if (!meta) return;
        if (filtersToolbarMetaOriginal === null) filtersToolbarMetaOriginal = meta.textContent;
        if (pendingCount > 0) {
            meta.textContent = filtersToolbarMetaOriginal.trim() + " · " + pendingCount + " " + window.TPW_PROTEINS_I18N.pending;
            btn.classList.add("has-pending-filters");
        } else {
            meta.textContent = filtersToolbarMetaOriginal;
            btn.classList.remove("has-pending-filters");
        }
    }

    function pendingSummaryItems() {
        var items = pendingAppendEntries.map(function (entry) {
            return { kind: "append", key: entry.id, label: pendingActionLabel(entry.payload) };
        });
        pendingToggleMap.forEach(function (entry, optionId) {
            items.push({ kind: "toggle", key: optionId, label: pendingActionLabel(entry.payload) });
        });
        return items;
    }

    function removePendingAppendEntry(id) {
        const index = pendingAppendEntries.findIndex(function (entry) { return entry.id === id; });
        if (index === -1) return;
        const entry = pendingAppendEntries[index];
        pendingAppendEntries.splice(index, 1);
        const form = entry.form;
        const stillPendingForSameForm = pendingAppendEntries.some(function (e) { return e.form === form; });
        if (form && !stillPendingForSameForm) {
            form.classList.remove("has-pending-filter");
            const button = form.querySelector("button[type='submit'], .filter-text-add, .filter-numeric-apply");
            if (button) {
                button.classList.remove("filter-chip--pending");
                button.removeAttribute("data-pending");
            }
            const message = form.closest(".filter-param")?.querySelector(".filter-input-message");
            if (message) message.textContent = "";
        }
        syncPendingFilterForms();
    }

    function renderPendingSummary(pendingCount, structureChanged, annotationChanged) {
        if (!filterPendingSummary) return;
        filterPendingSummary.hidden = pendingCount === 0;
        if (filterPendingCount) filterPendingCount.textContent = String(pendingCount);
        if (!filterPendingList) return;
        filterPendingList.innerHTML = "";
        if (pendingCount === 0) return;
        var items = pendingSummaryItems();
        if (structureChanged) items.push({ kind: "structure", key: null, label: window.TPW_PROTEINS_I18N.structureFilterChanged });
        if (annotationChanged) items.push({ kind: "annotation", key: null, label: window.TPW_PROTEINS_I18N.annotationFilterChanged });
        items.forEach(function (item) {
            const li = document.createElement("li");
            li.className = "filter-pending-summary__item";
            const labelSpan = document.createElement("span");
            labelSpan.className = "filter-pending-summary__item-label";
            labelSpan.textContent = item.label;
            labelSpan.title = item.label;
            li.appendChild(labelSpan);
            if (item.kind === "append" || item.kind === "toggle") {
                const removeBtn = document.createElement("button");
                removeBtn.type = "button";
                removeBtn.className = "filter-pill-remove filter-pending-summary__remove";
                removeBtn.setAttribute("aria-label", window.TPW_PROTEINS_I18N.removePendingChange);
                removeBtn.textContent = "\xD7";
                removeBtn.addEventListener("click", function () {
                    if (item.kind === "append") {
                        removePendingAppendEntry(item.key);
                    } else {
                        cancelPendingToggle(item.key);
                        syncPendingFilterForms();
                    }
                });
                li.appendChild(removeBtn);
            }
            filterPendingList.appendChild(li);
        });
    }

    function syncPendingFilterForms() {
        const actionPayload = JSON.stringify(getAllPendingActions());
        [filtersApplyForm, filterPresetSaveForm].forEach(function (form) {
            if (!form) return;
            const actionsInput = form.querySelector("input[name='filter_actions_json']");
            const structureInput = form.querySelector("input[name='pending_structure_source']");
            const annotationKindInput = form.querySelector("input[name='pending_annotation_kind']");
            const annotationValueInput = form.querySelector("input[name='pending_annotation_value']");
            if (actionsInput) actionsInput.value = actionPayload;
            if (structureInput) structureInput.value = pendingStructureSource || "";
            if (annotationKindInput) annotationKindInput.value = pendingAnnotationKind || "";
            if (annotationValueInput) annotationValueInput.value = pendingAnnotationValue || "";
        });

        const structureChanged = (pendingStructureSource || "") !== (CURRENT_FILTER_STATE.structureSource || "");
        const annotationChanged = (pendingAnnotationKind || "") !== (CURRENT_FILTER_STATE.annotationKind || "")
            || (pendingAnnotationValue || "") !== (CURRENT_FILTER_STATE.annotationValue || "");
        const pendingCount = getAllPendingActions().length + (structureChanged ? 1 : 0) + (annotationChanged ? 1 : 0);
        renderPendingSummary(pendingCount, structureChanged, annotationChanged);
        updateFiltersToolbarMeta(pendingCount);
        if (filtersApplyBtn) {
            filtersApplyBtn.disabled = pendingCount === 0;
            var badge = filtersApplyBtn.querySelector(".apply-btn-count");
            if (pendingCount > 0) {
                if (!badge) {
                    badge = document.createElement("span");
                    badge.className = "apply-btn-count";
                    badge.setAttribute("aria-hidden", "true");
                    filtersApplyBtn.appendChild(badge);
                }
                badge.textContent = String(pendingCount);
            } else if (badge) {
                badge.remove();
            }
        }
        updateGroupSummaries();
    }

    function formDataToObject(form) {
        const data = new FormData(form);
        const payload = {};
        data.forEach(function (value, key) {
            if (key === "csrfmiddlewaretoken" || key === "return_query") return;
            payload[key] = value;
        });
        return payload;
    }

    function setChipGlyph(button, active) {
        var existing = button.querySelector(".filter-chip-glyph");
        if (active && !existing) {
            var glyph = document.createElement("span");
            glyph.className = "filter-chip-glyph";
            glyph.setAttribute("aria-hidden", "true");
            glyph.textContent = "\xD7";
            button.appendChild(glyph);
        } else if (!active && existing) {
            existing.remove();
        }
    }

    function updateGroupSummaries() {
        if (!filterCatalogue) return;
        filterCatalogue.querySelectorAll("[data-filter-group]").forEach(function(group) {
            var meta = group.querySelector(".filter-group-meta");
            if (!meta) return;

            // Count chips that are currently visually active in this group.
            // This includes server-applied filters and pending-add, and
            // correctly excludes filters pending removal (chip lost --active).
            var activeCount = group.querySelectorAll(".filter-chip.filter-chip--active").length;

            // Active dot — show/hide without removing (server may have rendered it)
            var dot = meta.querySelector(".filter-group-active-dot");
            if (activeCount > 0) {
                if (!dot) {
                    dot = document.createElement("span");
                    dot.className = "filter-group-active-dot";
                    dot.setAttribute("aria-label", window.TPW_PROTEINS_I18N.hasActiveCriteria);
                    meta.insertBefore(dot, meta.firstChild);
                }
                dot.hidden = false;
            } else if (dot) {
                dot.hidden = true;
            }

            // Selected-count badge — teal pill next to the dot
            var badge = meta.querySelector(".filter-group-selected-count");
            if (activeCount > 0) {
                if (!badge) {
                    badge = document.createElement("span");
                    badge.className = "filter-group-selected-count";
                    var insertRef = meta.querySelector(".filter-group-count") || meta.querySelector(".filter-group-chevron");
                    meta.insertBefore(badge, insertRef);
                }
                badge.hidden = false;
                badge.textContent = String(activeCount);
            } else if (badge) {
                badge.hidden = true;
            }
        });
    }

    function cancelPendingToggle(optionId) {
        var entry = pendingToggleMap.get(optionId);
        if (!entry) return;
        pendingToggleMap.delete(optionId);
        var form = entry.form;
        var button = form ? form.querySelector(".filter-chip") : null;
        var serverActive = button ? button.dataset.serverActive === "true" : false;
        if (button) {
            button.classList.toggle("filter-chip--active", serverActive);
            button.setAttribute("aria-pressed", serverActive ? "true" : "false");
            button.classList.remove("filter-chip--pending");
            button.removeAttribute("data-pending");
            setChipGlyph(button, serverActive);
        }
        if (!entry.isKeyOverride && form) {
            var actionInput = form.querySelector("input[name='action']");
            if (actionInput) actionInput.value = serverActive ? "remove_filter" : "add_filter";
        }
    }

    function handleToggleChip(form, payload, keyOverride) {
        var optionId = keyOverride !== undefined ? keyOverride : String(payload.filter_option_id || "");
        if (!optionId) return;

        if (pendingToggleMap.has(optionId)) {
            // Second click: cancel, restore to server state
            cancelPendingToggle(optionId);
        } else {
            // First click: add to pending
            var button = form.querySelector(".filter-chip");
            var serverActive = button ? button.dataset.serverActive === "true" : false;
            pendingToggleMap.set(optionId, { payload: payload, form: form, isKeyOverride: keyOverride !== undefined });
            // For special-key chips (EC class), willBeActive is the inverse of server state.
            // For regular chips, derive it from the action field.
            var willBeActive = keyOverride !== undefined ? !serverActive : payload.action === "add_filter";
            if (button) {
                button.classList.toggle("filter-chip--active", willBeActive);
                button.setAttribute("aria-pressed", willBeActive ? "true" : "false");
                button.classList.add("filter-chip--pending");
                button.setAttribute("data-pending", "true");
                setChipGlyph(button, willBeActive);
            }
            if (!keyOverride) {
                var actionInput2 = form.querySelector("input[name='action']");
                if (actionInput2) actionInput2.value = willBeActive ? "remove_filter" : "add_filter";
            }
        }
    }

    function handleDeferredFilterSubmit(event) {
        if (event.defaultPrevented) return;
        const form = event.target;
        if (!form || !form.closest || !form.closest("#filters-drawer")) return;
        if (!form.matches(".filter-chip-form, .filter-text-form, .filter-numeric-form")) return;
        event.preventDefault();
        const payload = formDataToObject(form);
        if (!payload.action) return;
        payload._summary_label = buildPendingActionLabel(payload, form);

        if (payload.action === "set_structure_filter") {
            const requestedStructure = payload.structure_source || "";
            pendingStructureSource = pendingStructureSource === requestedStructure ? "" : requestedStructure;
            document.querySelectorAll("#filters-drawer input[name='action'][value='set_structure_filter']").forEach(function (input) {
                const optionForm = input.closest("form");
                const optionButton = optionForm ? optionForm.querySelector(".filter-chip") : null;
                const optionValue = optionForm ? (optionForm.querySelector("input[name='structure_source']") || {}).value : "";
                if (!optionButton) return;
                const active = optionValue && optionValue === pendingStructureSource;
                optionButton.classList.toggle("filter-chip--active", active);
                optionButton.classList.toggle("filter-chip--pending", optionValue === requestedStructure);
                optionButton.setAttribute("aria-pressed", active ? "true" : "false");
            });
            syncPendingFilterForms();
            return;
        }

        // EC class chips (and similar) send add_special_filter but behave as toggles.
        if (payload.action === "add_special_filter" && payload.special_kind && payload.special_value && form.querySelector(".filter-chip")) {
            var specialKey = "special:" + payload.special_kind + ":" + payload.special_value;
            handleToggleChip(form, payload, specialKey);
            syncPendingFilterForms();
            return;
        }

        if (payload.action === "add_filter" || payload.action === "remove_filter") {
            handleToggleChip(form, payload);
            syncPendingFilterForms();
            return;
        }

        // Numeric, text, special-add.
        // Numeric filters are single-value-per-param (matching the server's own
        // normalize_selected_parameters dedup) -- replace any existing pending
        // entry for the same score_param_id instead of queuing a second,
        // contradictory one. EC/GO text entries legitimately coexist as
        // separate chips, so those are never deduped this way.
        if (payload.action === "add_numeric_filter") {
            const existingIndex = pendingAppendEntries.findIndex(function (entry) {
                return entry.payload.action === "add_numeric_filter"
                    && entry.payload.score_param_id === payload.score_param_id;
            });
            if (existingIndex !== -1) pendingAppendEntries.splice(existingIndex, 1);
        }
        pendingAppendEntries.push({ id: nextPendingAppendId++, payload: payload, form: form });
        const button = form.querySelector("button[type='submit'], .filter-text-add, .filter-numeric-apply");
        if (button) {
            button.classList.add("filter-chip--pending");
            button.setAttribute("data-pending", "true");
        }
        if (form.matches(".filter-text-form, .filter-numeric-form")) {
            form.reset();
            form.classList.remove("has-numeric-error");
            form.classList.remove("is-between");
            const primaryLabel = form.querySelector('[data-numeric-field="primary"] .filter-numeric-field-label');
            const secondaryInput = form.querySelector('[data-numeric-field="secondary"] input');
            if (primaryLabel) primaryLabel.textContent = window.TPW_PROTEINS_I18N.minimum;
            if (secondaryInput) secondaryInput.value = "";
            form.classList.add("has-pending-filter");
            const message = form.closest(".filter-param")?.querySelector(".filter-input-message");
            if (message) {
                message.textContent = window.TPW_PROTEINS_I18N.queued + ": " + payload._summary_label + ". " + window.TPW_PROTEINS_I18N.useApplyFilters;
            }
        }
        syncPendingFilterForms();
    }

    function submitSearchForm() {
        if (!searchForm) return;
        searchForm.submit();
    }

    function hasSearchText() {
        return Boolean(searchInput && (searchInput.value || "").trim().length > 0);
    }

    function syncSearchSubmitState() {
        if (!searchSubmitBtn) return;
        searchSubmitBtn.disabled = !hasSearchText();
    }

    if (pageSizeSelect) {
        pageSizeSelect.addEventListener("change", submitSearchForm);
    }

    var pageJumpInput = document.getElementById("pageJumpInput");
    if (pageJumpInput) {
        function navigateToPage() {
            var page = parseInt(pageJumpInput.value, 10);
            var max = parseInt(pageJumpInput.max, 10);
            if (!page || page < 1) page = 1;
            if (page > max) page = max;
            if (page === window.TPW_PROTEINS_STATE.paginationNumber) return;
            if (!confirmDiscardPending(window.TPW_PROTEINS_I18N.confirmLeavePage)) {
                return;
            }
            var params = new URLSearchParams(window.location.search);
            params.set("page", page);
            if (window.TPPageLoader) window.TPPageLoader.show();
            window.location.search = params.toString();
        }
        pageJumpInput.addEventListener("keydown", function (e) {
            if (e.key === "Enter") { e.preventDefault(); navigateToPage(); }
        });
        pageJumpInput.addEventListener("blur", navigateToPage);
    }

    if (searchForm) {
        searchForm.addEventListener("submit", function (event) {
            if (event.submitter !== searchSubmitBtn) return;
            if (hasSearchText()) return;
            event.preventDefault();
            syncSearchSubmitState();
            if (searchInput) searchInput.focus();
        });
    }

    if (pageSizeControl && pageSizeSelect) {
        pageSizeControl.addEventListener("click", function (event) {
            if (event.target.closest(".tp-select-trigger") || event.target.closest(".tp-select-menu")) return;
            const enhancedWrapper = pageSizeSelect.closest(".tp-select");
            const enhancedTrigger = enhancedWrapper ? enhancedWrapper.querySelector(".tp-select-trigger") : null;
            if (enhancedTrigger) {
                enhancedTrigger.click();
                return;
            }
            if (event.target === pageSizeSelect) return;
            if (typeof pageSizeSelect.showPicker === "function") {
                pageSizeSelect.showPicker();
            } else {
                pageSizeSelect.focus();
                pageSizeSelect.click();
            }
        });
    }

    function getSuggestionButtons() {
        if (!suggestionsBox) return [];
        return Array.from(suggestionsBox.querySelectorAll(".search-suggestion-item"));
    }

    function setSuggestionsExpanded(isExpanded) {
        if (!searchInput) return;
        searchInput.setAttribute("aria-expanded", isExpanded ? "true" : "false");
    }

    function setActiveSuggestion(index) {
        const suggestionButtons = getSuggestionButtons();
        activeSuggestionIndex = -1;
        suggestionButtons.forEach(function (button) {
            button.classList.remove("is-active");
            button.setAttribute("aria-selected", "false");
        });
        if (!searchInput) return;
        searchInput.setAttribute("aria-activedescendant", "");
        if (index < 0 || index >= suggestionButtons.length) return;
        activeSuggestionIndex = index;
        const activeButton = suggestionButtons[index];
        activeButton.classList.add("is-active");
        activeButton.setAttribute("aria-selected", "true");
        searchInput.setAttribute("aria-activedescendant", activeButton.id || "");
    }

    function applySuggestion(button) {
        if (!button || !searchInput) return;
        const selectedValue = button.getAttribute("data-accession") || "";
        const detailUrl = button.getAttribute("data-url") || "";
        searchInput.value = selectedValue;
        searchInput.focus();
        hideSuggestions();
        if (detailUrl) {
            if (window.TPPageLoader) {
                if (window.TPPageLoader.showForUrl) {
                    window.TPPageLoader.showForUrl(detailUrl);
                } else {
                    window.TPPageLoader.show();
                }
            }
            window.location.assign(detailUrl);
            return;
        }
        submitSearchForm();
    }

    function hideSuggestions() {
        if (!suggestionsBox) return;
        suggestionsBox.innerHTML = "";
        suggestionsBox.hidden = true;
        activeSuggestionIndex = -1;
        setSuggestionsExpanded(false);
        if (searchInput) {
            searchInput.setAttribute("aria-activedescendant", "");
        }
    }

    function renderSuggestions(items) {
        if (!suggestionsBox) return;
        suggestionsBox.innerHTML = "";
        activeSuggestionIndex = -1;
        if (!items || !items.length) {
            suggestionsBox.hidden = true;
            setSuggestionsExpanded(false);
            return;
        }

        items.forEach(function (item, index) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "search-suggestion-item";
            button.id = "protein-search-suggestion-" + index;
            button.setAttribute("role", "option");
            button.setAttribute("aria-selected", "false");
            button.setAttribute("data-accession", item.accession || "");
            if (item.url) {
                button.setAttribute("data-url", item.url);
            }

            const accession = document.createElement("span");
            accession.className = "search-suggestion-accession";
            accession.textContent = item.accession || "";
            button.appendChild(accession);

            if (item.gene) {
                const gene = document.createElement("span");
                gene.className = "search-suggestion-gene";
                gene.textContent = "Gene: " + item.gene;
                button.appendChild(gene);
            }

            if (item.description) {
                const description = document.createElement("span");
                description.className = "search-suggestion-description";
                description.textContent = item.description;
                button.appendChild(description);
            }

            button.addEventListener("mousedown", function (event) {
                event.preventDefault();
            });

            button.addEventListener("click", function () {
                applySuggestion(button);
            });

            suggestionsBox.appendChild(button);
        });

        suggestionsBox.hidden = false;
        setSuggestionsExpanded(true);
    }

    function fetchSuggestions(query) {
        if (!suggestUrl || !query || query.length < AUTOCOMPLETE_CONFIG.minChars) {
            hideSuggestions();
            return;
        }
        suggestionRequestId += 1;
        const currentRequestId = suggestionRequestId;
        const url = suggestUrl + "?q=" + encodeURIComponent(query) + "&limit=" + AUTOCOMPLETE_CONFIG.limit;
        fetch(url, {
            headers: {
                "X-Requested-With": "XMLHttpRequest"
            }
        })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error(UI_TEXT.suggestionRequestFailed);
                }
                return response.json();
            })
            .then(function (payload) {
                if (currentRequestId !== suggestionRequestId) return;
                renderSuggestions(payload && payload.results ? payload.results : []);
            })
            .catch(function () {
                if (currentRequestId !== suggestionRequestId) return;
                hideSuggestions();
            });
    }

    if (searchInput) {
        searchInput.addEventListener("input", function () {
            const query = (searchInput.value || "").trim();
            syncSearchSubmitState();
            window.clearTimeout(suggestionsTimer);
            suggestionsTimer = window.setTimeout(function () {
                fetchSuggestions(query);
            }, AUTOCOMPLETE_CONFIG.debounceMs);
        });
        searchInput.addEventListener("keydown", function (event) {
            const suggestionButtons = getSuggestionButtons();
            const hasSuggestions = suggestionsBox && !suggestionsBox.hidden && suggestionButtons.length > 0;
            if (event.key === "Escape") {
                hideSuggestions();
                return;
            }
            if (!hasSuggestions) return;
            if (event.key === "ArrowDown") {
                event.preventDefault();
                const nextIndex = activeSuggestionIndex >= suggestionButtons.length - 1 ? 0 : activeSuggestionIndex + 1;
                setActiveSuggestion(nextIndex);
                return;
            }
            if (event.key === "ArrowUp") {
                event.preventDefault();
                const prevIndex = activeSuggestionIndex <= 0 ? suggestionButtons.length - 1 : activeSuggestionIndex - 1;
                setActiveSuggestion(prevIndex);
                return;
            }
            if (event.key === "Enter" && activeSuggestionIndex >= 0) {
                event.preventDefault();
                applySuggestion(suggestionButtons[activeSuggestionIndex]);
            }
        });
        searchInput.addEventListener("blur", function () {
            window.setTimeout(hideSuggestions, AUTOCOMPLETE_CONFIG.blurDelayMs);
        });
        searchInput.addEventListener("focus", function () {
            const query = (searchInput.value || "").trim();
            if (query.length >= AUTOCOMPLETE_CONFIG.minChars) {
                fetchSuggestions(query);
            }
        });
        searchInput.addEventListener("change", syncSearchSubmitState);
    }

    syncSearchSubmitState();

    document.addEventListener("click", function (event) {
        if (!autocompleteRoot || !autocompleteRoot.contains(event.target)) {
            hideSuggestions();
        }
    });

    function applyFilterCatalogueSearch() {
        if (!filterCatalogue) return;
        const query = filterSearchInput ? (filterSearchInput.value || "").trim().toLowerCase() : "";
        const groups = filterCatalogue.querySelectorAll("[data-filter-group]");
        let matchedTotal = 0;
        groups.forEach(function (group) {
            const params = group.querySelectorAll("[data-filter-param]");
            const groupCategory = (group.getAttribute("data-category") || "").toLowerCase();
            const categoryMatches = Boolean(query) && groupCategory.indexOf(query) >= 0;
            let visibleParams = 0;
            params.forEach(function (param) {
                const text = (param.getAttribute("data-search-text") || "").toLowerCase();
                const matches = !query || text.indexOf(query) >= 0 || categoryMatches;
                param.classList.toggle("is-search-hidden", !matches);
                if (matches) visibleParams += 1;
            });
            const groupVisible = visibleParams > 0;
            group.classList.toggle("is-search-hidden", !groupVisible);
            if (query && groupVisible) {
                group.open = true;
            }
            if (groupVisible) matchedTotal += visibleParams;
        });
        if (filterSearchNoResults) {
            filterSearchNoResults.hidden = matchedTotal !== 0;
        }
        if (filterSearchClearBtn) {
            filterSearchClearBtn.hidden = !query;
        }
    }

    function setExpandAllState(expanded) {
        if (!filterCatalogue) return;
        const groups = filterCatalogue.querySelectorAll("[data-filter-group]");
        groups.forEach(function (group) {
            if (expanded) {
                group.open = true;
            } else {
                const hasActive = group.querySelector(".filter-chip--active");
                group.open = Boolean(hasActive);
            }
        });
        if (filterExpandAllBtn) {
            filterExpandAllBtn.setAttribute("data-expand-all", expanded ? "true" : "false");
            const expandLabel = filterExpandAllBtn.querySelector("[data-expand-all-label]");
            if (expandLabel) {
                expandLabel.textContent = expanded ? window.TPW_PROTEINS_I18N.collapseAll : window.TPW_PROTEINS_I18N.expandAll;
            }
        }
    }

    // Smooth open/close for these <details> panels is handled globally
    // by static/js/global/smooth-details.js via the .js-smooth-details
    // class on the markup -- see that file for how it works. The
    // programmatic group.open assignments above (search-as-you-type,
    // expand/collapse all) stay instant on purpose, since animating
    // every keystroke's toggle would feel laggy; that script only
    // wires up user clicks on <summary>, so those paths are untouched.

    if (filterSearchInput) {
        filterSearchInput.addEventListener("input", applyFilterCatalogueSearch);
        filterSearchInput.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                filterSearchInput.value = "";
                applyFilterCatalogueSearch();
            }
        });
    }
    if (filterSearchClearBtn) {
        filterSearchClearBtn.addEventListener("click", function () {
            if (!filterSearchInput) return;
            filterSearchInput.value = "";
            filterSearchInput.focus();
            applyFilterCatalogueSearch();
        });
    }
    if (filterExpandAllBtn) {
        filterExpandAllBtn.addEventListener("click", function () {
            const isExpanded = filterExpandAllBtn.getAttribute("data-expand-all") === "true";
            setExpandAllState(!isExpanded);
        });
    }
    document.addEventListener("submit", handleDeferredFilterSubmit);
    syncPendingFilterForms();
    applyFilterCatalogueSearch();

    function syncApplyFormulaState() {
        if (!scoreFormulaSelect || !applyFormulaBtn) return;
        const selectedFormula = (scoreFormulaSelect.value || "").trim();
        const currentFormula = (scoreFormulaSelect.getAttribute("data-current-value") || "").trim();
        applyFormulaBtn.disabled = selectedFormula === currentFormula;
    }

    if (scoreFormulaSelect) {
        scoreFormulaSelect.addEventListener("change", syncApplyFormulaState);
        scoreFormulaSelect.addEventListener("input", syncApplyFormulaState);
    }

    syncApplyFormulaState();

    const openFiltersBtn = document.getElementById("open-filters-btn");
    const closeFiltersBtn = document.getElementById("close-filters-btn");
    const filtersOverlay = document.getElementById("filters-overlay");

    const openFormulaBtn = document.getElementById("open-formula-btn");
    const closeFormulaBtn = document.getElementById("close-formula-btn");
    const formulaOverlay = document.getElementById("formula-overlay");
    const openColumnsBtn = document.getElementById("open-columns-btn");
    const closeColumnsBtn = document.getElementById("close-columns-btn");
    const columnsOverlay = document.getElementById("columns-overlay");
    const columnsVisibleList = document.getElementById("columns-visible-list");
    const columnsLibraryList = document.getElementById("columns-library-list");
    const columnsSelectedCount = document.getElementById("columns-selected-count");
    const columnsSelectedList = document.getElementById("columns-selected-list");
    const columnsVisibleEmpty = document.getElementById("columns-visible-empty");
    const columnsVisiblePanelCount = document.getElementById("columns-visible-panel-count");
    let draggedColumnRow = null;

    function openOnly(target) {
        setDrawerState(target === "filters");
        setFormulaState(target === "scoring");
        setColumnsState(target === "columns");
    }

    if (openFiltersBtn) openFiltersBtn.addEventListener("click", function () { setPresetsDropdownOpen(false); openOnly("filters"); });
    if (closeFiltersBtn) closeFiltersBtn.addEventListener("click", function () { setDrawerState(false); });
    if (filtersOverlay) filtersOverlay.addEventListener("click", function () { setDrawerState(false); });

    // Presets dropdown
    const presetsWrap = document.getElementById("toolbar-presets-wrap");
    const openPresetsBtn = document.getElementById("open-presets-btn");
    const presetsDropdown = document.getElementById("toolbar-presets-dropdown");
    const tpdOpenDrawerBtn = document.getElementById("tpd-open-drawer-btn");

    function setPresetsDropdownOpen(open) {
        if (!presetsDropdown || !openPresetsBtn) return;
        presetsDropdown.hidden = !open;
        if (presetsWrap) presetsWrap.classList.toggle("is-presets-open", open);
        const toolbarCard = presetsWrap ? presetsWrap.closest(".toolbar-card") : null;
        if (toolbarCard) toolbarCard.classList.toggle("is-presets-open", open);
        openPresetsBtn.setAttribute("aria-expanded", open ? "true" : "false");
    }

    if (openPresetsBtn) {
        openPresetsBtn.addEventListener("click", function (e) {
            e.stopPropagation();
            setPresetsDropdownOpen(presetsDropdown && presetsDropdown.hidden);
        });
    }

    document.querySelectorAll(".tpd-apply-form").forEach(function (form) {
        form.addEventListener("submit", function (e) {
            if (!confirmDiscardPending(window.TPW_PROTEINS_I18N.confirmApplyPreset)) {
                e.preventDefault();
            }
        });
    });

    const drawerResetForm = document.querySelector(".drawer-reset-form");
    if (drawerResetForm) {
        drawerResetForm.addEventListener("submit", function (e) {
            if (!confirmDiscardPending(window.TPW_PROTEINS_I18N.confirmClearAll)) {
                e.preventDefault();
            }
        });
    }

    if (filtersApplyForm) {
        // Applying resolves the pending changes, it never discards
        // them -- must never trigger the beforeunload warning below.
        filtersApplyForm.addEventListener("submit", function () {
            suppressBeforeUnloadWarning = true;
        });
    }

    if (filterPresetSaveForm) {
        // The comment this replaced claimed saving a preset "only captures
        // the already-applied filters, not anything still pending" -- false:
        // syncPendingFilterForms() (called on every pending-state change,
        // see its own definition) keeps this form's filter_actions_json /
        // pending_structure_source / pending_annotation_kind|value hidden
        // inputs in exact sync with filtersApplyForm's, and the backend's
        // save_filter_preset action folds filter_actions_json in via
        // _apply_filter_changes_payload -- so a save here genuinely
        // includes every pending change, the same as clicking Apply first
        // would. The warning was simply wrong, and never discards anything,
        // so -- like filtersApplyForm -- it only needs to suppress the
        // generic beforeunload warning during its own redirect.
        filterPresetSaveForm.addEventListener("submit", function () {
            suppressBeforeUnloadWarning = true;
        });
    }

    document.addEventListener("click", function (e) {
        const paginationLink = e.target.closest(".pagination a");
        if (!paginationLink) return;
        if (!confirmDiscardPending(window.TPW_PROTEINS_I18N.confirmLeavePage)) {
            e.preventDefault();
        }
    });

    window.addEventListener("beforeunload", function (e) {
        if (suppressBeforeUnloadWarning || !hasPendingChanges()) return;
        e.preventDefault();
        e.returnValue = "";
    });

    if (tpdOpenDrawerBtn) {
        tpdOpenDrawerBtn.addEventListener("click", function () {
            setPresetsDropdownOpen(false);
            openOnly("filters");
        });
    }

    document.addEventListener("click", function (e) {
        if (!presetsWrap || !presetsDropdown || presetsDropdown.hidden) return;
        if (!presetsWrap.contains(e.target)) setPresetsDropdownOpen(false);
    });

    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && presetsDropdown && !presetsDropdown.hidden) {
            setPresetsDropdownOpen(false);
            if (openPresetsBtn) openPresetsBtn.focus();
        }
    });

    if (openFormulaBtn) openFormulaBtn.addEventListener("click", function () { openOnly("scoring"); });
    if (closeFormulaBtn) closeFormulaBtn.addEventListener("click", function () { setFormulaState(false); });
    if (formulaOverlay) formulaOverlay.addEventListener("click", function () { setFormulaState(false); });
    if (openColumnsBtn) openColumnsBtn.addEventListener("click", function () { openOnly("columns"); });
    if (closeColumnsBtn) closeColumnsBtn.addEventListener("click", function () { setColumnsState(false); });
    if (columnsOverlay) columnsOverlay.addEventListener("click", function () { setColumnsState(false); });

    function getColumnRows() {
        return Array.from(document.querySelectorAll("[data-column-row]"));
    }

    function getVisibleColumnRows() {
        if (!columnsVisibleList) return [];
        return Array.from(columnsVisibleList.querySelectorAll("[data-column-row]"));
    }

    function getLibraryRows() {
        if (!columnsLibraryList) return [];
        return Array.from(columnsLibraryList.querySelectorAll("[data-column-row]"));
    }

    function moveRowToVisibleList(row) {
        if (!columnsVisibleList || !row) return;
        columnsVisibleList.appendChild(row);
    }

    function moveRowToLibrary(row) {
        if (!columnsLibraryList || !row) return;
        const label = (row.getAttribute("data-column-label") || "").toLowerCase();
        const rows = getLibraryRows().filter(function (candidate) { return candidate !== row; });
        const nextRow = rows.find(function (candidate) {
            const candidateLabel = (candidate.getAttribute("data-column-label") || "").toLowerCase();
            return candidateLabel.localeCompare(label) > 0;
        });
        if (nextRow) {
            columnsLibraryList.insertBefore(row, nextRow);
            return;
        }
        columnsLibraryList.appendChild(row);
    }

    function syncColumnsSummary() {
        const visibleRows = getVisibleColumnRows();
        if (columnsSelectedCount) {
            columnsSelectedCount.textContent = String(visibleRows.length);
        }
        if (columnsVisiblePanelCount) {
            columnsVisiblePanelCount.textContent = String(visibleRows.length);
        }
        if (columnsVisibleEmpty) {
            columnsVisibleEmpty.hidden = visibleRows.length > 0;
        }
        if (!columnsSelectedList) return;
        columnsSelectedList.innerHTML = "";
        if (!visibleRows.length) {
            const chip = document.createElement("span");
            chip.className = "tp-chip tp-chip--meta tp-chip--sm columns-selected-chip columns-selected-chip--empty";
            chip.textContent = "No optional columns visible";
            columnsSelectedList.appendChild(chip);
            return;
        }
        visibleRows.forEach(function (row) {
            const chip = document.createElement("span");
            chip.className = "tp-chip tp-chip--meta tp-chip--sm columns-selected-chip";
            chip.textContent = row.getAttribute("data-column-label") || "";
            columnsSelectedList.appendChild(chip);
        });
    }

    function syncColumnRow(row, visibleRows, rowIndex) {
        if (!row) return;
        const checkbox = row.querySelector(".columns-option-input");
        const toggleBtn = row.querySelector("[data-columns-toggle]");
        const orderIndex = row.querySelector(".columns-order-index");
        const dragHandle = row.querySelector("[data-columns-drag-handle]");
        const isSelected = Boolean(checkbox && checkbox.checked);
        row.setAttribute("data-selected", isSelected ? "true" : "false");
        row.classList.toggle("is-hidden", !isSelected);
        row.classList.toggle("columns-row--selected", isSelected);
        row.classList.toggle("columns-row--available", !isSelected);
        row.draggable = isSelected;
        if (toggleBtn) {
            const label = isSelected ? "Hide column" : "Show column";
            toggleBtn.setAttribute("aria-label", label);
            toggleBtn.setAttribute("title", label);
        }
        if (orderIndex) {
            orderIndex.textContent = isSelected && typeof rowIndex === "number" ? String(rowIndex + 1) : "—";
        }
        if (dragHandle) {
            dragHandle.disabled = !isSelected;
        }
    }

    function syncLibrarySectionVisibility() {
        if (!columnsLibraryList) return;
        const wrapper = columnsLibraryList.closest(".columns-section");
        if (!wrapper) return;
        wrapper.hidden = columnsLibraryList.children.length === 0;
    }

    function syncAllColumnRows() {
        const visibleRows = getVisibleColumnRows();
        getColumnRows().forEach(function (row) {
            const rowIndex = visibleRows.indexOf(row);
            syncColumnRow(row, visibleRows, rowIndex >= 0 ? rowIndex : null);
        });
        syncColumnsSummary();
        syncLibrarySectionVisibility();
    }

    function getDragAfterElement(container, y) {
        const draggableElements = Array.from(container.querySelectorAll("[data-column-row][data-selected='true']:not(.is-dragging)"));
        let closest = { offset: Number.NEGATIVE_INFINITY, element: null };
        draggableElements.forEach(function (element) {
            const box = element.getBoundingClientRect();
            const offset = y - box.top - box.height / 2;
            if (offset < 0 && offset > closest.offset) {
                closest = { offset: offset, element: element };
            }
        });
        return closest.element;
    }

    if (columnsVisibleList && columnsLibraryList) {
        document.addEventListener("click", function (event) {
            const toggleButton = event.target.closest("[data-columns-toggle]");
            if (toggleButton) {
                const row = toggleButton.closest("[data-column-row]");
                const checkbox = row ? row.querySelector(".columns-option-input") : null;
                if (!row || !checkbox) return;
                checkbox.checked = !checkbox.checked;
                if (checkbox.checked) {
                    moveRowToVisibleList(row);
                } else {
                    moveRowToLibrary(row);
                }
                syncAllColumnRows();
            }
        });

        columnsVisibleList.addEventListener("dragstart", function (event) {
            const row = event.target.closest("[data-column-row]");
            if (!row || row.getAttribute("data-selected") !== "true") return;
            draggedColumnRow = row;
            row.classList.add("is-dragging");
            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = "move";
            }
        });

        columnsVisibleList.addEventListener("dragend", function () {
            if (draggedColumnRow) {
                draggedColumnRow.classList.remove("is-dragging");
            }
            draggedColumnRow = null;
            syncAllColumnRows();
        });

        columnsVisibleList.addEventListener("dragover", function (event) {
            if (!draggedColumnRow) return;
            event.preventDefault();
            const afterElement = getDragAfterElement(columnsVisibleList, event.clientY);
            if (!afterElement) {
                columnsVisibleList.appendChild(draggedColumnRow);
                return;
            }
            if (afterElement !== draggedColumnRow) {
                columnsVisibleList.insertBefore(draggedColumnRow, afterElement);
            }
        });

        syncAllColumnRows();
    }

    const proteinTableShell = document.querySelector(".protein-table-panel .tp-table-shell");
    const proteinTableScrollNote = document.getElementById("protein-table-scroll-note");
    const proteinTableTopScroll = document.getElementById("protein-table-top-scroll");
    const proteinTableTopScrollInner = document.getElementById("protein-table-top-scroll-inner");

    function syncProteinTableScrollNote() {
        if (!proteinTableShell || !proteinTableScrollNote) return;
        const scrollHost = proteinTableShell.querySelector(":scope > .tp-table-shell__scroll") || proteinTableShell;
        if (!scrollHost) return;
        const table = scrollHost.querySelector("#proteins_table");
        const contentWidth = Math.max(
            scrollHost.clientWidth || 1,
            table ? Math.ceil(table.getBoundingClientRect().width) : 0,
            table ? table.scrollWidth : 0
        );
        const maxScrollLeft = Math.max(0, contentWidth - scrollHost.clientWidth);
        if (maxScrollLeft <= 0) {
            scrollHost.scrollLeft = 0;
        } else if (scrollHost.scrollLeft > maxScrollLeft) {
            scrollHost.scrollLeft = maxScrollLeft;
        }
        const hasOverflow = maxScrollLeft > 16;
        proteinTableScrollNote.hidden = !hasOverflow;
        if (proteinTableTopScroll && proteinTableTopScrollInner) {
            proteinTableTopScroll.hidden = !hasOverflow;
            const trackInset = 6;
            const trackWidth = Math.max(1, (proteinTableTopScroll.clientWidth || scrollHost.clientWidth || 1) - trackInset);
            const proportionalThumb = Math.round((scrollHost.clientWidth / contentWidth) * trackWidth);
            const thumbWidth = hasOverflow
                ? Math.min(
                    Math.round(trackWidth * 0.72),
                    Math.max(88, proportionalThumb)
                )
                : trackWidth;
            const maxThumbOffset = Math.max(0, trackWidth - thumbWidth);
            const thumbOffset = hasOverflow
                ? Math.round((scrollHost.scrollLeft / maxScrollLeft) * maxThumbOffset)
                : 0;

            proteinTableTopScroll.classList.toggle("is-disabled", !hasOverflow);
            proteinTableTopScroll.style.setProperty("--protein-scroll-thumb-size", `${thumbWidth}px`);
            proteinTableTopScroll.style.setProperty("--protein-scroll-thumb-offset", `${thumbOffset}px`);
            proteinTableTopScrollInner.style.width = contentWidth + "px";
        }
    }

    if (proteinTableShell && proteinTableScrollNote) {
        const scrollHost = proteinTableShell.querySelector(":scope > .tp-table-shell__scroll") || proteinTableShell;
        if (scrollHost) {
            scrollHost.addEventListener("scroll", syncProteinTableScrollNote, { passive: true });
            if (proteinTableTopScroll) {
                let isDraggingTopScroll = false;

                const moveTableScrollFromTrack = function (clientX) {
                    const trackRect = proteinTableTopScroll.getBoundingClientRect();
                    const trackInset = 6;
                    const trackWidth = Math.max(1, trackRect.width - trackInset);
                    const trackLeft = trackRect.left + (trackInset / 2);
                    const table = scrollHost.querySelector("#proteins_table");
                    const contentWidth = Math.max(
                        scrollHost.clientWidth || 1,
                        table ? Math.ceil(table.getBoundingClientRect().width) : 0,
                        table ? table.scrollWidth : 0
                    );
                    const maxScrollLeft = Math.max(0, contentWidth - scrollHost.clientWidth);
                    if (maxScrollLeft <= 0) return;
                    const proportionalThumb = Math.round((scrollHost.clientWidth / contentWidth) * trackWidth);
                    const thumbWidth = Math.min(
                        Math.round(trackWidth * 0.72),
                        Math.max(88, proportionalThumb)
                    );
                    const maxThumbOffset = Math.max(0, trackWidth - thumbWidth);
                    const centeredOffset = Math.min(
                        Math.max(0, clientX - trackLeft - (thumbWidth / 2)),
                        maxThumbOffset
                    );
                    const centeredRatio = maxThumbOffset > 0 ? (centeredOffset / maxThumbOffset) : 0;
                    scrollHost.scrollLeft = centeredRatio * maxScrollLeft;
                };

                proteinTableTopScroll.addEventListener("mousedown", function (event) {
                    if (proteinTableTopScroll.classList.contains("is-disabled")) return;
                    isDraggingTopScroll = true;
                    proteinTableTopScroll.classList.add("is-dragging");
                    moveTableScrollFromTrack(event.clientX);
                    event.preventDefault();
                });

                window.addEventListener("mousemove", function (event) {
                    if (!isDraggingTopScroll) return;
                    moveTableScrollFromTrack(event.clientX);
                });

                window.addEventListener("mouseup", function () {
                    if (!isDraggingTopScroll) return;
                    isDraggingTopScroll = false;
                    proteinTableTopScroll.classList.remove("is-dragging");
                });
            }
        }
        window.addEventListener("resize", syncProteinTableScrollNote);
        setTimeout(syncProteinTableScrollNote, 0);
        setTimeout(syncProteinTableScrollNote, 180);
    }

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
            setDrawerState(false);
            setFormulaState(false);
            setColumnsState(false);
        }
    });

    document.querySelectorAll(".filter-param-help").forEach(function (help) {
        const tooltipText = help.getAttribute("data-filter-tooltip") || "";
        if (!tooltipText) return;
        const tooltip = document.createElement("span");
        tooltip.className = "filter-param-tooltip";
        tooltip.setAttribute("role", "tooltip");
        tooltip.textContent = tooltipText;
        document.body.appendChild(tooltip);

        function positionTooltip() {
            const pad = 12;
            const gap = 10;
            const maxWidth = Math.min(340, window.innerWidth - (pad * 2));
            const anchor = help.getBoundingClientRect();
            tooltip.style.width = maxWidth + "px";
            tooltip.classList.remove("is-above");

            const size = tooltip.getBoundingClientRect();
            let left = anchor.left + (anchor.width / 2) - (maxWidth / 2);
            left = Math.max(pad, Math.min(left, window.innerWidth - pad - maxWidth));

            let top = anchor.bottom + gap;
            const canFitBelow = top + size.height <= window.innerHeight - pad;
            const canFitAbove = anchor.top - size.height - gap >= pad;
            if (!canFitBelow && canFitAbove) {
                top = anchor.top - size.height - gap;
                tooltip.classList.add("is-above");
            }

            const arrowLeft = anchor.left + (anchor.width / 2) - left;
            tooltip.style.left = left + "px";
            tooltip.style.top = top + "px";
            tooltip.style.setProperty("--tooltip-arrow-left", Math.max(12, Math.min(maxWidth - 12, arrowLeft)) + "px");
        }

        function showTooltip() {
            positionTooltip();
            tooltip.classList.add("is-visible");
        }

        function hideTooltip() {
            tooltip.classList.remove("is-visible");
        }

        help.addEventListener("mouseenter", showTooltip);
        help.addEventListener("mouseleave", hideTooltip);
        help.addEventListener("focusin", showTooltip);
        help.addEventListener("focusout", hideTooltip);
        window.addEventListener("resize", positionTooltip);
        document.addEventListener("scroll", function () {
            if (help.matches(":hover") || help.contains(document.activeElement)) {
                positionTooltip();
            }
        }, true);
    });

    document.querySelectorAll(".filter-numeric-form").forEach(function (form) {
        const primaryLabel = form.querySelector('[data-numeric-field="primary"] .filter-numeric-field-label');
        const primaryInput = form.querySelector('[data-numeric-field="primary"] input');
        const secondaryInput = form.querySelector('[data-numeric-field="secondary"] input');
        const applyButton = form.querySelector(".filter-numeric-apply");
        const message = form.querySelector(".filter-numeric-message");

        function parseDecimal(input) {
            const raw = (input && input.value ? input.value : "").trim();
            if (!raw) return null;
            if (!/^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)$/.test(raw)) return NaN;
            return Number(raw.replace(",", "."));
        }

        let validationAttempted = false;

        function setNumericState(isValid, text, showMessage) {
            const visibleText = showMessage ? (text || "") : "";
            form.classList.toggle("has-numeric-error", Boolean(visibleText));
            if (message) message.textContent = visibleText;
            if (applyButton) applyButton.disabled = !isValid;
        }

        function validateNumericFilter(showMessage) {
            const selected = form.querySelector('input[name="numeric_operation"]:checked');
            const mode = selected ? selected.value : "gte";
            const primaryValue = parseDecimal(primaryInput);
            const secondaryValue = parseDecimal(secondaryInput);

            if (mode === "between") {
                if (primaryValue === null && secondaryValue === null) {
                    setNumericState(false, "Enter a lower and upper bound.", showMessage);
                    return false;
                }
                if (primaryValue === null || secondaryValue === null) {
                    setNumericState(false, "Both bounds are required for a range.", showMessage);
                    return false;
                }
                if (Number.isNaN(primaryValue) || Number.isNaN(secondaryValue)) {
                    setNumericState(false, "Use a valid decimal number.", showMessage);
                    return false;
                }
                if (primaryValue > secondaryValue) {
                    setNumericState(false, "Lower bound must be less than or equal to upper bound.", showMessage);
                    return false;
                }
                setNumericState(true, "", showMessage);
                return true;
            }

            if (primaryValue === null) {
                setNumericState(false, "Enter a numeric value.", showMessage);
                return false;
            }
            if (Number.isNaN(primaryValue)) {
                setNumericState(false, "Use a valid decimal number.", showMessage);
                return false;
            }
            setNumericState(true, "", showMessage);
            return true;
        }

        function syncNumericMode() {
            const selected = form.querySelector('input[name="numeric_operation"]:checked');
            const mode = selected ? selected.value : "gte";
            form.classList.toggle("is-between", mode === "between");
            if (primaryLabel) {
                if (mode === "lte") primaryLabel.textContent = "Maximum";
                else if (mode === "between") primaryLabel.textContent = "Lower bound";
                else primaryLabel.textContent = "Minimum";
            }
            if (secondaryInput && mode !== "between") {
                secondaryInput.value = "";
            }
            if (validationAttempted) {
                validateNumericFilter(true);
            } else if (applyButton) {
                applyButton.disabled = false;
            }
        }

        form.querySelectorAll('input[name="numeric_operation"]').forEach(function (input) {
            input.addEventListener("change", syncNumericMode);
        });
        [primaryInput, secondaryInput].forEach(function (input) {
            if (!input) return;
            input.addEventListener("input", function () {
                if (validationAttempted) validateNumericFilter(true);
            });
            input.addEventListener("blur", function () {
                if (validationAttempted) validateNumericFilter(true);
            });
        });
        form.addEventListener("submit", function (event) {
            validationAttempted = true;
            if (!validateNumericFilter(true)) {
                event.preventDefault();
            }
        });
        syncNumericMode();
    });
}

const copyShareLinkBtn = document.getElementById("copy-share-link-btn");
if (copyShareLinkBtn) {
    copyShareLinkBtn.addEventListener("click", function () {
        const url = copyShareLinkBtn.getAttribute("data-share-url") || "";
        const defaultLabel = copyShareLinkBtn.getAttribute("data-default-label") || "Copy link";
        const copiedLabel = copyShareLinkBtn.getAttribute("data-copied-label") || "Copied";
        const label = copyShareLinkBtn.querySelector("[data-copy-label]");
        (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject())
            .then(function () {
                if (label) label.textContent = copiedLabel;
                window.setTimeout(function () {
                    if (label) label.textContent = defaultLabel;
                }, 1300);
            })
            .catch(function () {});
    });
}

if (window.jQuery) {
    $(document).ready(jsloaded);
} else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", jsloaded);
} else {
    jsloaded();
}
