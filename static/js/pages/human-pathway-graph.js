/*
 * Human Targets — Pathways tab (KEGG gene/ortholog network).
 *
 * One shared Cytoscape instance, reused across pathway tabs (elements
 * swapped on tab click) -- same "one stage, reload content on demand"
 * pattern as human-protein-detail.js's structure viewer. Uses the global
 * `window.cytoscape` (+ dagre layout) already bundled site-wide for the
 * bacterial metabolic-network graphs (see bundle.js via js/entrypoint.js);
 * this file does NOT reuse those graphs' own JS (metabolic-network.js etc.)
 * since KEGG relation edges carry subtypes (activation/inhibition/binding...)
 * with no analog in that reaction-adjacency graph -- only the same rendering
 * conventions (dagre left-to-right, solid label background chips, restyle
 * via the Cytoscape API rather than resizing the container) are mirrored.
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

    var EDGE_STYLES = {
        "is-activation": { color: "#2e9e4f", style: "solid" },
        "is-inhibition": { color: "#c94b4b", style: "dashed" },
        "is-phosphorylation": { color: "#3b7dd8", style: "solid" },
        "is-binding": { color: "#8a93a6", style: "dashed" },
        "is-expression": { color: "#2e9e4f", style: "dashed" },
        "": { color: "#b7bfcc", style: "solid" }
    };

    function classForSubtypes(subtypes) {
        subtypes = subtypes || [];
        if (subtypes.indexOf("inhibition") !== -1 || subtypes.indexOf("repression") !== -1) return "is-inhibition";
        if (subtypes.indexOf("activation") !== -1) return "is-activation";
        if (subtypes.indexOf("phosphorylation") !== -1) return "is-phosphorylation";
        if (
            subtypes.indexOf("binding") !== -1 ||
            subtypes.indexOf("association") !== -1 ||
            subtypes.indexOf("binding/association") !== -1
        ) {
            return "is-binding";
        }
        if (subtypes.indexOf("expression") !== -1) return "is-expression";
        return "";
    }

    function buildElements(pathway) {
        var graph = pathway.graph_json || {};
        var elements = [];
        (graph.nodes || []).forEach(function (node) {
            elements.push({
                data: { id: node.id, label: node.label || node.id },
                classes: node.id === pathway.highlighted_node_id ? "is-focal" : "",
            });
        });
        (graph.edges || []).forEach(function (edge, index) {
            elements.push({
                data: { id: "e" + index, source: edge.source, target: edge.target },
                classes: classForSubtypes(edge.subtypes),
            });
        });
        return elements;
    }

    function initPathwayGraph() {
        var container = document.getElementById("human-pathway-graph");
        var dataEl = document.getElementById("human-pathway-data");
        if (!container || typeof window.cytoscape !== "function" || !dataEl) return;

        var pathways;
        try {
            pathways = JSON.parse(dataEl.textContent);
        } catch (err) {
            return;
        }
        if (!pathways.length) return;

        var rootStyle = getComputedStyle(document.documentElement);
        function token(name, fallback) {
            var value = (rootStyle.getPropertyValue(name) || "").trim();
            return value || fallback;
        }
        var accent = token("--human-accent", "#6a5acd");
        var nodeColor = token("--tp-color-border-strong", "#8a93a6");
        var textColor = token("--tp-color-text", "#1b1f27");
        var surfaceColor = token("--tp-color-surface", "#ffffff");

        var styleRules = [
            {
                selector: "node",
                style: {
                    shape: "ellipse",
                    "background-color": nodeColor,
                    label: "data(label)",
                    "font-size": 10,
                    color: textColor,
                    "text-valign": "bottom",
                    "text-margin-y": 4,
                    "text-background-color": surfaceColor,
                    "text-background-opacity": 0.85,
                    "text-background-shape": "roundrectangle",
                    "text-background-padding": 2,
                    "text-max-width": "90px",
                    "text-wrap": "ellipsis",
                    width: 18,
                    height: 18,
                },
            },
            {
                selector: "node.is-focal",
                style: {
                    shape: "round-rectangle",
                    "background-color": accent,
                    width: 30,
                    height: 20,
                    "font-weight": "bold",
                },
            },
            {
                selector: "edge",
                style: {
                    width: 1.5,
                    "curve-style": "bezier",
                    "target-arrow-shape": "triangle",
                    "arrow-scale": 0.8,
                    "line-color": EDGE_STYLES[""].color,
                    "target-arrow-color": EDGE_STYLES[""].color,
                },
            },
        ];
        Object.keys(EDGE_STYLES).forEach(function (cls) {
            if (!cls) return;
            styleRules.push({
                selector: "edge." + cls,
                style: {
                    "line-color": EDGE_STYLES[cls].color,
                    "target-arrow-color": EDGE_STYLES[cls].color,
                    "line-style": EDGE_STYLES[cls].style,
                },
            });
        });

        var cy = window.cytoscape({
            container: container,
            style: styleRules,
            elements: [],
            wheelSensitivity: 0.2,
        });

        function renderPathway(pathway) {
            cy.elements().remove();
            cy.add(buildElements(pathway));
            var layoutOptions = window.TP_CYTOSCAPE_DAGRE_AVAILABLE
                ? { name: "dagre", rankDir: "LR", nodeSep: 20, rankSep: 60 }
                : { name: "cose" };
            cy.layout(layoutOptions).run();
            cy.once("layoutstop", function () {
                cy.fit(undefined, 24);
            });
        }

        var byKeggId = {};
        pathways.forEach(function (pathway) {
            byKeggId[pathway.kegg_id] = pathway;
        });

        document.querySelectorAll("[data-pathway-tab]").forEach(function (tab) {
            tab.addEventListener("click", function () {
                var keggId = tab.getAttribute("data-pathway-tab");
                document.querySelectorAll("[data-pathway-tab]").forEach(function (t) {
                    t.classList.toggle("is-active", t === tab);
                });
                document.querySelectorAll("[data-pathway-meta]").forEach(function (panel) {
                    panel.classList.toggle("is-hidden", panel.getAttribute("data-pathway-meta") !== keggId);
                });
                if (byKeggId[keggId]) renderPathway(byKeggId[keggId]);
            });
        });

        renderPathway(pathways[0]);
    }

    ready(initPathwayGraph);
})();
