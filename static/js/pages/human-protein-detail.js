/*
 * Human Targets — protein detail page behavior.
 *
 * Self-contained (no dependency on protein-detail.js): the bacteria
 * Structure section's NGL setup carries a lot of pathogen-specific
 * apparatus (pocket overlays, chain-toggle theming) that doesn't apply
 * here, so this file reimplements a smaller NGL loader for the four
 * structure sub-tabs (AlphaFold / AlphaFill / PDB X-ray / PDB NMR).
 * The binders tab-switching, filter-chip, and molecule-zoom-modal blocks
 * below are copied verbatim (behaviorally) from protein.html's inline
 * script -- that code is already generic over any `[data-binders-tab]`/
 * `.binder-filter-chip` markup, and this page reuses the exact same
 * `components/binders/*` partials, so the same behavior applies unchanged.
 */
(function () {
    "use strict";

    function ready(fn) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", fn);
        } else {
            fn();
        }
    }

    function initCopySequence() {
        var button = document.getElementById("copy-human-sequence");
        var source = document.getElementById("human-raw-sequence");
        if (!button || !source) return;
        var labelEl = button.querySelector("[data-copy-label]");
        button.addEventListener("click", function () {
            navigator.clipboard.writeText(source.value || "").then(function () {
                if (labelEl) {
                    var original = button.dataset.defaultLabel || labelEl.textContent;
                    labelEl.textContent = button.dataset.copiedLabel || "Copied";
                    setTimeout(function () {
                        labelEl.textContent = original;
                    }, 1400);
                }
            });
        });
    }

    function initStructureViewer() {
        var viewportEl = document.getElementById("human-structure-viewport");
        var loadingEl = document.getElementById("human-structure-loading");
        var dataEl = document.getElementById("human-structure-data");
        if (!viewportEl || typeof window.NGL !== "function" || !dataEl) return;

        var subTabs;
        try {
            subTabs = JSON.parse(dataEl.textContent);
        } catch (err) {
            return;
        }

        var stage = null;
        function getStage() {
            if (!stage) {
                var rootStyle = getComputedStyle(document.documentElement);
                var bg = (rootStyle.getPropertyValue("--tp-color-structure-bg") || "").trim()
                    || (rootStyle.getPropertyValue("--tp-color-surface-panel") || "").trim();
                stage = new window.NGL("human-structure-viewport", { backgroundColor: bg || undefined });
            }
            return stage;
        }

        function colorSchemeFor(source) {
            if (source === "alphafold") return "bfactor";
            if (source === "alphafill") return "uniform";
            return "chainname";
        }

        function loadEntry(entry, source, buttonEl) {
            if (loadingEl) {
                loadingEl.textContent = "Loading structure…";
                loadingEl.style.display = "flex";
            }
            document.querySelectorAll(".human-structure-entry.is-active").forEach(function (el) {
                el.classList.remove("is-active");
            });
            if (buttonEl) buttonEl.classList.add("is-active");

            var nglStage = getStage();
            nglStage.removeAllComponents();
            nglStage.loadFile(entry.url, { ext: "cif", defaultRepresentation: false }).then(function (component) {
                component.addRepresentation("cartoon", { colorScheme: colorSchemeFor(source) });
                component.addRepresentation("ball+stick", { sele: "hetero and not water", colorScheme: "element" });
                component.autoView();
                if (loadingEl) loadingEl.style.display = "none";
            }).catch(function () {
                if (loadingEl) {
                    loadingEl.textContent = "Unable to load 3D structure.";
                    loadingEl.style.display = "flex";
                }
            });
        }

        document.querySelectorAll("[data-structure-tab]").forEach(function (tab) {
            tab.addEventListener("click", function () {
                var key = tab.getAttribute("data-structure-tab");
                document.querySelectorAll("[data-structure-tab]").forEach(function (t) {
                    t.classList.toggle("is-active", t === tab);
                });
                document.querySelectorAll("[data-structure-panel]").forEach(function (panel) {
                    panel.classList.toggle("is-hidden", panel.getAttribute("data-structure-panel") !== key);
                });
            });
        });

        document.querySelectorAll(".human-structure-entry").forEach(function (entryButton) {
            entryButton.addEventListener("click", function () {
                var url = entryButton.getAttribute("data-structure-url");
                var source = entryButton.getAttribute("data-structure-source");
                loadEntry({ url: url }, source, entryButton);
            });
        });

        var firstTab = subTabs[0];
        if (firstTab && firstTab.entries && firstTab.entries.length) {
            var firstButton = document.querySelector(
                '.human-structure-panel[data-structure-panel="' + firstTab.key + '"] .human-structure-entry'
            );
            loadEntry(firstTab.entries[0], firstTab.key, firstButton);
        }
    }

    function initBindersTabs() {
        var tabs = document.querySelectorAll("[data-binders-tab]");
        var panels = document.querySelectorAll("[data-binders-panel]");
        if (!tabs.length || !panels.length) return;
        tabs.forEach(function (tab) {
            tab.addEventListener("click", function () {
                var target = tab.getAttribute("data-binders-tab");
                tabs.forEach(function (t) {
                    var isActive = t === tab;
                    t.classList.toggle("is-active", isActive);
                    t.setAttribute("aria-selected", isActive ? "true" : "false");
                });
                panels.forEach(function (panel) {
                    panel.classList.toggle("is-hidden", panel.getAttribute("data-binders-panel") !== target);
                });
            });
        });
    }

    function initBinderRowNavigation() {
        document.addEventListener("click", function (e) {
            var row = e.target.closest(".binder-tbl__row[data-href]");
            if (!row) return;
            window.location.href = row.getAttribute("data-href");
        });
    }

    window.copySmiles = window.copySmiles || function (cell) {
        var smiles = cell.dataset.smiles;
        navigator.clipboard.writeText(smiles).then(function () {
            var code = cell.querySelector("code");
            var orig = code ? code.textContent : "";
            if (code) code.textContent = "✓ Copied";
            cell.classList.add("binder-tbl__smiles--copied");
            setTimeout(function () {
                if (code) code.textContent = orig;
                cell.classList.remove("binder-tbl__smiles--copied");
            }, 1400);
        });
    };

    function initBinderMoleculeModal() {
        var modal = document.getElementById("binder-mol-modal");
        var panel = modal ? modal.querySelector(".binder-mol-modal__panel") : null;
        var title = document.getElementById("binder-mol-modal-title");
        var meta = document.getElementById("binder-mol-modal-meta");
        var body = document.getElementById("binder-mol-modal-body");
        var closeBtn = document.getElementById("binder-mol-modal-close");
        if (!modal || !panel || !title || !meta || !body) return;

        function closeModal() {
            modal.classList.remove("is-open");
            modal.setAttribute("aria-hidden", "true");
            document.body.classList.remove("binder-mol-modal-open");
            body.innerHTML = "";
        }

        function openModal(trigger) {
            var svg = trigger.querySelector("svg");
            if (!svg) return;
            title.textContent = trigger.dataset.binderName || "Ligand structure";
            meta.textContent = trigger.dataset.binderSource || "";
            body.innerHTML = "";
            body.appendChild(svg.cloneNode(true));
            modal.classList.add("is-open");
            modal.setAttribute("aria-hidden", "false");
            document.body.classList.add("binder-mol-modal-open");
            if (closeBtn) closeBtn.focus();
        }

        document.addEventListener("click", function (event) {
            var trigger = event.target.closest(".binder-mol-zoom-trigger");
            if (!trigger || trigger.disabled) return;
            event.preventDefault();
            event.stopPropagation();
            openModal(trigger);
        });
        if (closeBtn) closeBtn.addEventListener("click", closeModal);
        modal.addEventListener("click", function (event) {
            if (!panel.contains(event.target)) closeModal();
        });
        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && modal.classList.contains("is-open")) closeModal();
        });
    }

    function initBinderFilters() {
        function applyFilters(bar) {
            var panel = bar.closest(".binders-panel");
            var rows = panel.querySelectorAll(".binder-tbl__row");
            var activeChips = bar.querySelectorAll(".binder-filter-chip.is-active");
            var filters = Array.from(activeChips).map(function (c) { return c.dataset.filter; });
            var shown = 0;
            rows.forEach(function (row) {
                var visible = true;
                if (filters.includes("ro5") && row.dataset.li !== "ok") visible = false;
                if (filters.includes("nopains") && row.dataset.pa === "1") visible = false;
                if (filters.includes("mw500")) {
                    var mw = parseFloat(row.dataset.mw);
                    if (!isNaN(mw) && mw >= 500) visible = false;
                }
                if (filters.includes("pchembl6")) {
                    var s1 = parseFloat(row.dataset.score);
                    if (isNaN(s1) || s1 < 6) visible = false;
                }
                if (filters.includes("tanimoto07")) {
                    var s2 = parseFloat(row.dataset.score);
                    if (isNaN(s2) || s2 < 0.7) visible = false;
                }
                row.style.display = visible ? "" : "none";
                if (visible) shown++;
            });
            var countEl = bar.querySelector(".binder-filter-count");
            var clearBtn = bar.querySelector(".binder-filter-clear");
            if (filters.length > 0) {
                if (countEl) {
                    countEl.textContent = shown + " of " + rows.length + " compounds";
                    countEl.hidden = false;
                }
                if (clearBtn) clearBtn.hidden = false;
            } else {
                if (countEl) countEl.hidden = true;
                if (clearBtn) clearBtn.hidden = true;
                rows.forEach(function (r) { r.style.display = ""; });
            }
        }

        document.addEventListener("click", function (e) {
            var chip = e.target.closest(".binder-filter-chip");
            var clear = e.target.closest(".binder-filter-clear");
            if (chip) {
                e.stopPropagation();
                chip.classList.toggle("is-active");
                applyFilters(chip.closest(".binder-filter-bar"));
            }
            if (clear) {
                e.stopPropagation();
                clear.closest(".binder-filter-bar")
                    .querySelectorAll(".binder-filter-chip.is-active")
                    .forEach(function (c) { c.classList.remove("is-active"); });
                applyFilters(clear.closest(".binder-filter-bar"));
            }
        });
    }

    ready(function () {
        initCopySequence();
        initStructureViewer();
        initBindersTabs();
        initBinderRowNavigation();
        initBinderMoleculeModal();
        initBinderFilters();
    });
})();
