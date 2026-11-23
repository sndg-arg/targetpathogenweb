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

    // Side-chain classes for a pocket's composition bar. His counts as polar
    // (mostly neutral at physiological pH).
    var RESIDUE_CLASSES = [
        { key: "hydrophobic", label: "Hydrophobic", codes: ["ALA", "VAL", "LEU", "ILE", "MET", "PRO"] },
        { key: "aromatic", label: "Aromatic", codes: ["PHE", "TRP", "TYR"] },
        { key: "polar", label: "Polar", codes: ["SER", "THR", "ASN", "GLN", "CYS", "GLY", "HIS"] },
        { key: "charged", label: "Charged", codes: ["ASP", "GLU", "LYS", "ARG"] }
    ];

    function residueComposition(residues) {
        var counts = {};
        var total = 0;
        (residues || "").trim().split(/\s+/).forEach(function (token) {
            var code = token.slice(0, 3).toUpperCase();
            RESIDUE_CLASSES.forEach(function (cls) {
                if (cls.codes.indexOf(code) !== -1) {
                    counts[cls.key] = (counts[cls.key] || 0) + 1;
                    total += 1;
                }
            });
        });
        if (!total) return null;
        return RESIDUE_CLASSES.map(function (cls) {
            return { key: cls.key, label: cls.label, pct: Math.round(((counts[cls.key] || 0) / total) * 100) };
        });
    }

    // "Same-site prediction: FPocket 109 (1.6 Å center distance, 25 shared
    // residues, 100% of the smaller site)" -> key/value rows; any other
    // "Key (note): value" keeps its note as a tooltip.
    function parseProperty(part) {
        var same = part.match(/^Same-site prediction:\s*(.+?)\s*\((.+)\)\s*$/);
        if (same) {
            return {
                key: "Same site as",
                value: same[1],
                detail: same[2]
                    .replace(" center distance", " apart")
                    .replace(" of the smaller site", " overlap")
                    .split(/,\s*/)
                    .join(" · "),
                title: part
            };
        }
        var colon = part.indexOf(": ");
        if (colon > 0 && colon < 80) {
            var key = part.slice(0, colon);
            return { key: key.replace(/\s*\(.*\)\s*$/, ""), value: part.slice(colon + 2), title: key };
        }
        return { note: part };
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
                if (count) {
                    var list = document.createElement("button");
                    list.type = "button";
                    list.className = "sv-pocket-inspector-link js-show-residues";
                    list.setAttribute("data-residues", value.trim());
                    list.setAttribute("data-residues-title", pocketInspector.getAttribute("data-current-title") || "");
                    list.textContent = "List";
                    target.appendChild(document.createTextNode(" · "));
                    target.appendChild(list);
                }
                return;
            }
            if (field === "composition") {
                renderComposition(target, value);
                return;
            }
            target.textContent = value || "-";
        }

        function renderComposition(target, residues) {
            target.textContent = "";
            var parts = residueComposition(residues);
            if (!parts) {
                target.textContent = "-";
                return;
            }
            var bar = document.createElement("span");
            bar.className = "sv-composition-bar";
            var legend = document.createElement("span");
            legend.className = "sv-composition-legend";
            parts.forEach(function (part) {
                if (part.pct) {
                    var seg = document.createElement("span");
                    seg.className = "sv-composition-seg sv-composition--" + part.key;
                    seg.style.width = part.pct + "%";
                    seg.title = part.label + " " + part.pct + "%";
                    bar.appendChild(seg);
                }
                var item = document.createElement("span");
                item.className = "sv-composition-item";
                item.innerHTML = '<i class="sv-composition-dot sv-composition--' + part.key + '"></i>';
                item.appendChild(document.createTextNode(part.label + " " + part.pct + "%"));
                legend.appendChild(item);
            });
            target.appendChild(bar);
            target.appendChild(legend);
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
                var prop = parseProperty(part);
                if (prop.note) {
                    var note = document.createElement("span");
                    note.className = "sv-pocket-property-note";
                    note.textContent = prop.note;
                    target.appendChild(note);
                    return;
                }
                var row = document.createElement("span");
                row.className = "sv-pocket-property";
                if (prop.title) row.title = prop.title;
                var key = document.createElement("span");
                key.className = "sv-pocket-property-key";
                key.textContent = prop.key;
                var val = document.createElement("span");
                val.className = "sv-pocket-property-value";
                val.textContent = prop.value;
                if (prop.detail) {
                    var detail = document.createElement("span");
                    detail.className = "sv-pocket-property-detail";
                    detail.textContent = prop.detail;
                    val.appendChild(detail);
                }
                row.appendChild(key);
                row.appendChild(val);
                target.appendChild(row);
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
            var scoreLabel = card.getAttribute("data-pocket-score-label") || "";
            var rawScore = card.getAttribute("data-pocket-score") || "";
            if (rawScore && scoreLabel.indexOf(" · ") !== -1) {
                scoreLabel = rawScore + scoreLabel.slice(scoreLabel.indexOf(" · "));
            }
            setPocketInspectorField("score", scoreLabel || rawScore);
            setPocketInspectorField(
                "layer",
                coreBtn ? (coreBtn.getAttribute("data-layer-label") || coreBtn.textContent || "") : defaultLayerLabel
            );
            if (pocketInspector) pocketInspector.setAttribute("data-current-title", card.getAttribute("data-pocket-title") || "");
            setPocketInspectorField("residues", card.getAttribute("data-pocket-residues") || "");
            setPocketInspectorField("composition", card.getAttribute("data-pocket-residues") || "");
            setPocketInspectorField("properties", card.getAttribute("data-pocket-properties") || "");
            if (pocketInspector) {
                pocketInspector.hidden = false;
                // Replay the settle-in animation on every selection.
                pocketInspector.classList.remove("is-entering");
                void pocketInspector.offsetWidth;
                pocketInspector.classList.add("is-entering");
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
