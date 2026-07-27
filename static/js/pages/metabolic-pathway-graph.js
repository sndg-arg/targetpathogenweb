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
            chokepoint: readToken("--tp-color-amber-500"),
            chokepointSoft: readToken("--tp-color-amber-050"),
            edge: readToken("--tp-color-border-strong"),
            ring: readToken("--tp-color-surface"),
            surfaceSoft: readToken("--tp-color-surface-soft"),
            text: readToken("--tp-color-text-primary"),
            textFaint: readToken("--tp-color-text-soft")
        };
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

        var cy = window.cytoscape({
            container: container,
            elements: elements,
            style: window.TPMetabolicReactionGraph.styleRules(readPalette()),
            layout: window.TPMetabolicReactionGraph.flowLayout(roots, {
                nodeSep: 54,
                rankSep: 104,
                padding: 30
            }),
            minZoom: 0.2,
            maxZoom: 6,
            wheelSensitivity: 1,
            userZoomingEnabled: true,
            userPanningEnabled: true,
            boxSelectionEnabled: false
        });

        if ("MutationObserver" in window) {
            var themeObserver = new MutationObserver(function () {
                cy.style(window.TPMetabolicReactionGraph.styleRules(readPalette())).update();
            });
            themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
        }

        cy.one("layoutstop", function () {
            cy.fit(cy.elements(), 24);
            container.classList.add("is-ready");
        });

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
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initPathwayGraph);
    } else {
        initPathwayGraph();
    }
})();
