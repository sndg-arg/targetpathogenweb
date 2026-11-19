/* Standalone per-pathway reaction+metabolite graph (metabolism_pathway.html) -- replaces
 * the previous hand-drawn SVG substrate/reaction/product row diagram with a real
 * Cytoscape graph, built from the exact same shared element/style builder
 * (metabolic-reaction-graph.js) the genome-wide unified network uses when expanding a
 * pathway in place. This page renders it top-level (no parent/compound node) instead of
 * embedded under a collapsed pathway node.
 */
(function () {
    "use strict";

    function readToken(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }

    function readPalette() {
        return {
            plain: readToken("--tp-color-text-soft"),
            chokepoint: readToken("--tp-color-warning-ink"),
            chokepointSoft: readToken("--tp-color-warning-bg"),
            druggable: readToken("--tp-color-primary"),
            edge: readToken("--tp-color-text-primary"),
            ring: readToken("--tp-color-surface"),
            surfaceSoft: readToken("--tp-color-surface-soft"),
            text: readToken("--tp-color-text-primary"),
            textFaint: readToken("--tp-color-text-soft")
        };
    }

    // Dagre stacks disconnected sub-networks in one tall column, so the fit
    // zooms far out and labels shrink. Pack them into rows (largest first)
    // shaped like the canvas instead.
    function packComponents(cy, container) {
        var parts = cy.elements().components();
        if (parts.length < 2) return;
        var gap = 48;
        var boxes = parts.map(function (part) {
            return { part: part, bb: part.boundingBox({ includeLabels: true }) };
        }).sort(function (a, b) {
            return (b.bb.w * b.bb.h) - (a.bb.w * a.bb.h);
        });
        var area = boxes.reduce(function (sum, box) {
            return sum + (box.bb.w + gap) * (box.bb.h + gap);
        }, 0);
        var aspect = container.clientWidth / Math.max(container.clientHeight, 1);
        var rowWidth = Math.max(boxes[0].bb.w, Math.sqrt(area * aspect));
        var x = 0;
        var y = 0;
        var rowHeight = 0;
        boxes.forEach(function (box) {
            if (x > 0 && x + box.bb.w > rowWidth) {
                x = 0;
                y += rowHeight + gap;
                rowHeight = 0;
            }
            var dx = x - box.bb.x1;
            var dy = y - box.bb.y1;
            box.part.nodes().positions(function (node) {
                var pos = node.position();
                return { x: pos.x + dx, y: pos.y + dy };
            });
            x += box.bb.w + gap;
            rowHeight = Math.max(rowHeight, box.bb.h);
        });
    }

    function initPathwayGraph() {
        var container = document.getElementById("metabolic-pathway-graph-cy");
        var dataEl = document.getElementById("metabolic-pathway-graph-data");
        if (!container || container.__tpPathwayGraphInitialized) {
            return;
        }
        container.__tpPathwayGraphInitialized = true;

        if (typeof window.cytoscape !== "function" || !window.TPMetabolicReactionGraph) {
            container.textContent = "Pathway graph viewer is not available. Rebuild the static bundle.";
            return;
        }
        if (!dataEl) {
            container.textContent = "No pathway data available.";
            return;
        }

        var payload;
        try {
            payload = JSON.parse(dataEl.textContent);
        } catch (e) {
            container.textContent = "Unable to load the pathway graph.";
            return;
        }
        if (!payload.reactions || !payload.reactions.length) {
            container.textContent = "No reactions to show for this pathway.";
            return;
        }

        var tooltip = document.createElement("div");
        tooltip.className = "metabolic-network-tooltip";
        tooltip.style.display = "none";
        container.parentElement.appendChild(tooltip);

        var elements = window.TPMetabolicReactionGraph.buildElements(payload);
        var roots = window.TPMetabolicReactionGraph.suggestRoots(elements);
        var fontScale = 1;

        var cy = window.cytoscape({
            container: container,
            elements: elements,
            style: window.TPMetabolicReactionGraph.styleRules(readPalette()),
            minZoom: 0.2,
            maxZoom: 6,
            wheelSensitivity: 1,
            userZoomingEnabled: true,
            userPanningEnabled: true,
            boxSelectionEnabled: false
        });

        if ("MutationObserver" in window) {
            var themeObserver = new MutationObserver(function () {
                cy.style(window.TPMetabolicReactionGraph.styleRules(readPalette(), fontScale)).update();
            });
            themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
        }

        cy.one("layoutstop", function () {
            packComponents(cy, container);
            cy.fit(cy.elements(), 24);
            // Re-derive label/node size from the zoom this specific pathway actually fit
            // at, so a tiny pathway (fit zoomed way in) and a sprawling one (zoomed way
            // out) both read at roughly the same on-screen text size.
            fontScale = window.TPMetabolicReactionGraph.computeFontScale(cy.zoom());
            if (Math.abs(fontScale - 1) > 0.05) {
                cy.style(window.TPMetabolicReactionGraph.styleRules(readPalette(), fontScale)).update();
                packComponents(cy, container);
                cy.fit(cy.elements(), 24);
            }
            container.classList.add("is-ready");
        });
        // Laid out once without animation, then packed before the canvas fades in.
        cy.layout(window.TPMetabolicReactionGraph.flowLayout(roots, {
            nodeSep: 54,
            rankSep: 104,
            padding: 30,
            animate: false
        })).run();

        Array.prototype.forEach.call(
            document.querySelectorAll("[data-pathway-graph-action]"),
            function (button) {
                button.addEventListener("click", function () {
                    var action = button.getAttribute("data-pathway-graph-action");
                    if (action === "fit") cy.fit(cy.elements(), 24);
                    if (action === "zoom-in") cy.zoom({ level: cy.zoom() * 1.18, renderedPosition: { x: container.clientWidth / 2, y: container.clientHeight / 2 } });
                    if (action === "zoom-out") cy.zoom({ level: cy.zoom() / 1.18, renderedPosition: { x: container.clientWidth / 2, y: container.clientHeight / 2 } });
                });
            }
        );

        function clearHover() {
            cy.elements(".is-hovered").removeClass("is-hovered");
            cy.elements(".is-muted").removeClass("is-muted");
        }

        cy.on("mouseover", "node", function (evt) {
            var node = evt.target;
            var data = node.data();
            clearHover();
            var neighborhood = node.closedNeighborhood();
            cy.elements().not(neighborhood).addClass("is-muted");
            neighborhood.addClass("is-hovered");
            tooltip.innerHTML = data.isReaction
                ? window.TPMetabolicReactionGraph.tooltipForReaction(data)
                : window.TPMetabolicReactionGraph.tooltipForMetabolite(data);
            tooltip.style.display = "block";
        });
        cy.on("mousemove", "node", function (evt) {
            var pos = evt.renderedPosition || evt.position;
            tooltip.style.left = (container.offsetLeft + pos.x + 12) + "px";
            tooltip.style.top = (container.offsetTop + pos.y + 12) + "px";
        });
        cy.on("mouseout", "node", function () {
            clearHover();
            tooltip.style.display = "none";
        });

        // Reaction table -> graph: click a row to locate and highlight its node in the
        // diagram above. Some rows have no matching node -- very large pathways cap the
        // diagram at 45 reactions server-side (see MetabolismPathwayView.py), prioritizing
        // chokepoints -- so a missing node is a valid outcome, not a bug, and just no-ops.
        var activeRow = null;
        Array.prototype.forEach.call(
            document.querySelectorAll(".pathway-reaction-row[data-reaction-id]"),
            function (row) {
                row.addEventListener("click", function (evt) {
                    if (evt.target.closest("a")) return;
                    var reactionId = row.getAttribute("data-reaction-id");
                    var node = cy.getElementById("rxn::" + reactionId);
                    if (!node || node.empty()) return;
                    if (activeRow) activeRow.classList.remove("pathway-reaction-row--located");
                    activeRow = row;
                    row.classList.add("pathway-reaction-row--located");
                    clearHover();
                    var neighborhood = node.closedNeighborhood();
                    cy.elements().not(neighborhood).addClass("is-muted");
                    neighborhood.addClass("is-hovered");
                    cy.animate({ fit: { eles: neighborhood, padding: 60 } }, { duration: 400 });
                });
            }
        );
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initPathwayGraph);
    } else {
        initPathwayGraph();
    }
})();
