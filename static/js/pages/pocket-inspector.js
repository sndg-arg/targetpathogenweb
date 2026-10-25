(function (global) {
    "use strict";

    // Scroll el into view inside its own scrolling panel only. scrollIntoView
    // also scrolls the page, which on the full viewer (a fixed-height layout)
    // pushed the whole viewer up and left a blank band below it.
    function scrollWithinPanel(el, block) {
        var panel = el.parentElement;
        while (panel && panel !== document.body) {
            var overflowY = getComputedStyle(panel).overflowY;
            if ((overflowY === "auto" || overflowY === "scroll") && panel.scrollHeight > panel.clientHeight) break;
            panel = panel.parentElement;
        }
        if (!panel || panel === document.body) {
            el.scrollIntoView({ behavior: "smooth", block: block });
            return;
        }
        var offset = el.getBoundingClientRect().top - panel.getBoundingClientRect().top;
        if (block === "center") offset -= (panel.clientHeight - el.offsetHeight) / 2;
        panel.scrollBy({ top: offset - 8, behavior: "smooth" });
    }

    /**
     * Shared pocket-card / pocket-inspector DOM layer used by both the embedded
     * structure viewer (protein.html) and the fullscreen one (structure.html).
     * Each page keeps its own NGL init (representations differ too much between
     * the two: 3Dmol fallback and alt/primary table switching only exist in
     * protein.html), but this selection/inspector/toggle logic is identical --
     * it only touches DOM attributes/classes plus the page's own globally
     * exposed window.toogle_view/window.ngl_zoom_to and window.representations.
     * Extracted after a real regression (inspectPocket() left the inspector
     * panel hidden) shipped duplicated in both files and had to be fixed twice.
     */
    function createPocketInspector(config) {
        config = config || {};
        var pocketInspector = config.pocketInspector || null;
        var pocketClearBtn = config.pocketClearBtn || null;
        var pocketShowOnlyBtn = config.pocketShowOnlyBtn || null;
        var defaultLayerLabel = config.defaultLayerLabel || "Pocket core";
        var showOnlySelectedPocket = false;
        // The layer inspectPocket() switched on by itself. Selecting another
        // pocket switches it off again, so clicking pocket 1 then pocket 2
        // shows pocket 2 -- layers the user turned on by hand stay on.
        var autoLayerBtn = null;

        function setCardVisibilityState(card) {
            if (!card) return;
            var hasVisibleLayer = !!card.querySelector('.js-repr-toggle[aria-pressed="true"]');
            card.classList.toggle("is-visible-in-viewer", hasVisibleLayer);
        }

        function setReprButtonPressed(btn, pressed) {
            if (!btn) return;
            var isPressed = btn.getAttribute("aria-pressed") === "true";
            if (isPressed === pressed) return;
            var reprs = (btn.getAttribute("data-repr") || "").trim().split(/\s+/).filter(Boolean);
            reprs.forEach(function (r) {
                if (typeof global.toogle_view === "function") global.toogle_view(r);
            });
            btn.setAttribute("aria-pressed", pressed ? "true" : "false");
            setCardVisibilityState(btn.closest(".pocket-card, .residueset-row"));
        }

        function setPocketInspectorField(field, value) {
            if (!pocketInspector) return;
            var target = pocketInspector.querySelector('[data-pocket-field="' + field + '"]');
            if (!target) return;
            if (field === "properties") {
                renderPropertyChips(target, value);
                return;
            }
            if (field === "score") {
                // "0.99 · High — P2Rank binding-site probability (0-1)": the
                // value fits the cell, the scale explanation goes to the tooltip.
                var parts = (value || "").split(" — ");
                target.textContent = parts[0] || "-";
                target.title = parts.slice(1).join(" — ");
                return;
            }
            if (field === "residues") {
                var count = (value || "").trim().split(/\s+/).filter(Boolean).length;
                target.textContent = count ? (count + (count === 1 ? " residue" : " residues")) : "-";
                return;
            }
            target.textContent = value || "-";
        }

        function renderPropertyChips(target, value) {
            target.textContent = "";
            var parts = (value || "").split(" | ").map(function (part) {
                return part.trim();
            }).filter(Boolean);
            if (!parts.length) {
                target.textContent = "-";
                return;
            }
            // Short values (volume, counts) read as chips; a sentence-long note
            // wrapped inside a pill looks broken, so it stays plain text.
            parts.forEach(function (part) {
                var item = document.createElement("span");
                item.className = part.length > 32 ? "sv-pocket-property-note" : "tp-chip";
                item.textContent = part;
                target.appendChild(item);
            });
        }

        function setShowOnlySelectedPocket(on) {
            showOnlySelectedPocket = on;
            if (pocketShowOnlyBtn) pocketShowOnlyBtn.setAttribute("aria-pressed", on ? "true" : "false");
        }

        function setStructureFocusDim(on) {
            var reps = global.representations || {};
            var cartoon = reps.__main_cartoon;
            if (cartoon && typeof cartoon.setParameters === "function") {
                cartoon.setParameters({ opacity: on ? 0.32 : 1 });
            }
        }

        function clearPocketSelection() {
            document.querySelectorAll(".pocket-card.is-selected-pocket").forEach(function (card) {
                card.classList.remove("is-selected-pocket");
            });
            if (pocketInspector) pocketInspector.hidden = true;
            setShowOnlySelectedPocket(false);
            setStructureFocusDim(false);
        }

        // Used only by the "Clear selection" button itself -- also switches
        // off the selected pocket's own visible layer(s). clearPocketSelection()
        // stays layer-agnostic because inspectPocket() reuses it internally when
        // switching pockets, and switching must not clear other active layers.
        function clearPocketSelectionAndLayers() {
            autoLayerBtn = null;
            document.querySelectorAll(".pocket-card.is-selected-pocket").forEach(function (card) {
                card.querySelectorAll('.js-repr-toggle[aria-pressed="true"]').forEach(function (btn) {
                    setReprButtonPressed(btn, false);
                });
            });
            clearPocketSelection();
            if (typeof global.ngl_reset_zoom === "function") global.ngl_reset_zoom();
        }

        function inspectPocket(card) {
            if (!card) return;
            if (autoLayerBtn && !card.contains(autoLayerBtn)) {
                setReprButtonPressed(autoLayerBtn, false);
            }
            autoLayerBtn = null;
            var hasVisibleLayer = !!card.querySelector('.js-repr-toggle[aria-pressed="true"]');
            clearPocketSelection();
            card.classList.add("is-selected-pocket");

            var coreRepr = card.getAttribute("data-pocket-core-repr") || "";
            var coreBtn = coreRepr ? card.querySelector('.js-repr-toggle[data-repr="' + coreRepr + '"]') : null;
            if (!hasVisibleLayer) {
                autoLayerBtn = coreBtn || card.querySelector(".js-repr-toggle");
                setReprButtonPressed(autoLayerBtn, true);
            }
            setCardVisibilityState(card);

            var zoomKey = card.getAttribute("data-pocket-zoom");
            if (zoomKey && typeof global.ngl_zoom_to === "function") {
                global.ngl_zoom_to(zoomKey);
            }

            setPocketInspectorField("title", card.getAttribute("data-pocket-title") || "");
            setPocketInspectorField("method", card.getAttribute("data-pocket-method") || "");
            setPocketInspectorField(
                "score",
                card.getAttribute("data-pocket-score-label") || card.getAttribute("data-pocket-score") || ""
            );
            setPocketInspectorField(
                "layer",
                coreBtn ? (coreBtn.getAttribute("data-layer-label") || coreBtn.textContent || "") : defaultLayerLabel
            );
            setPocketInspectorField("residues", card.getAttribute("data-pocket-residues") || "");
            setPocketInspectorField("properties", card.getAttribute("data-pocket-properties") || "");
            if (pocketInspector) {
                pocketInspector.hidden = false;
                scrollWithinPanel(pocketInspector, "start");
            }
        }

        document.addEventListener("click", function (event) {
            var inspectBtn = event.target.closest(".js-inspect-pocket");
            if (inspectBtn) {
                inspectPocket(inspectBtn.closest(".pocket-card"));
                return;
            }
            var btn = event.target.closest(".js-repr-toggle");
            if (!btn) return;
            if (showOnlySelectedPocket && !btn.closest(".pocket-card.is-selected-pocket")) {
                return; // locked to the selected pocket -- ignore toggles on other pockets/residue sets
            }
            var isPressed = btn.getAttribute("aria-pressed") === "true";
            setReprButtonPressed(btn, !isPressed);
            if (btn === autoLayerBtn) autoLayerBtn = null;
            var selectedCard = btn.closest(".pocket-card.is-selected-pocket");
            if (selectedCard && !isPressed) {
                setPocketInspectorField("layer", btn.getAttribute("data-layer-label") || btn.textContent || "");
            }
        });

        document.addEventListener("keydown", function (event) {
            if (event.key !== "Enter" && event.key !== " ") return;
            var inspectBtn = event.target.closest(".js-inspect-pocket");
            if (!inspectBtn) return;
            event.preventDefault();
            inspectPocket(inspectBtn.closest(".pocket-card"));
        });

        if (pocketClearBtn) {
            pocketClearBtn.addEventListener("click", clearPocketSelectionAndLayers);
        }

        if (pocketShowOnlyBtn) {
            pocketShowOnlyBtn.addEventListener("click", function () {
                var selectedCard = document.querySelector(".pocket-card.is-selected-pocket");
                if (!selectedCard) return;
                setShowOnlySelectedPocket(!showOnlySelectedPocket);
                setStructureFocusDim(showOnlySelectedPocket);
                if (showOnlySelectedPocket) {
                    document.querySelectorAll(
                        '.pocket-card .js-repr-toggle[aria-pressed="true"], .residueset-row .js-repr-toggle[aria-pressed="true"]'
                    ).forEach(function (otherBtn) {
                        if (!selectedCard.contains(otherBtn)) setReprButtonPressed(otherBtn, false);
                    });
                }
            });
        }

        return {
            clearPocketSelection: clearPocketSelection,
            inspectPocket: inspectPocket,
            setCardVisibilityState: setCardVisibilityState,
            setReprButtonPressed: setReprButtonPressed
        };
    }

    global.tpPocketInspector = { createPocketInspector: createPocketInspector };
})(window);
