(function (global) {
    "use strict";

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
            parts.forEach(function (part) {
                var chip = document.createElement("span");
                chip.className = "pocket-property-chip";
                chip.textContent = part;
                target.appendChild(chip);
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

        function inspectPocket(card) {
            if (!card) return;
            var hasVisibleLayer = !!card.querySelector('.js-repr-toggle[aria-pressed="true"]');
            clearPocketSelection();
            card.classList.add("is-selected-pocket");
            setStructureFocusDim(true);

            var coreRepr = card.getAttribute("data-pocket-core-repr") || "";
            var coreBtn = coreRepr ? card.querySelector('.js-repr-toggle[data-repr="' + coreRepr + '"]') : null;
            if (!hasVisibleLayer) {
                setReprButtonPressed(coreBtn || card.querySelector(".js-repr-toggle"), true);
            }
            setCardVisibilityState(card);

            var zoomKey = card.getAttribute("data-pocket-zoom");
            if (zoomKey && typeof global.ngl_zoom_to === "function") {
                global.ngl_zoom_to(zoomKey);
            }

            setPocketInspectorField("title", card.getAttribute("data-pocket-title") || "");
            setPocketInspectorField("method", card.getAttribute("data-pocket-method") || "");
            setPocketInspectorField("score", card.getAttribute("data-pocket-score") || "");
            setPocketInspectorField(
                "layer",
                coreBtn ? (coreBtn.getAttribute("data-layer-label") || coreBtn.textContent || "") : defaultLayerLabel
            );
            setPocketInspectorField("residues", card.getAttribute("data-pocket-residues") || "");
            setPocketInspectorField("properties", card.getAttribute("data-pocket-properties") || "");
            if (pocketInspector) pocketInspector.hidden = false;
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
            pocketClearBtn.addEventListener("click", clearPocketSelection);
        }

        if (pocketShowOnlyBtn) {
            pocketShowOnlyBtn.addEventListener("click", function () {
                var selectedCard = document.querySelector(".pocket-card.is-selected-pocket");
                if (!selectedCard) return;
                setShowOnlySelectedPocket(!showOnlySelectedPocket);
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
