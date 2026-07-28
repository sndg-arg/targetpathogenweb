/* Genome-wide unified metabolic network graph: pathway-level nodes on load; clicking one
 * drills into a full-canvas view of just that pathway's reactions/metabolites (Krona-style
 * zoom, not an in-place compound expansion) so a biologist never has to parse an overview
 * graph with several already-expanded pathways overlapping each other. A "back" breadcrumb
 * returns to the collapsed overview. Because each drill-in/out is a full element swap
 * (cy.elements().remove() + cy.add() + fresh layout), there is no compound-node nesting and
 * no incremental layout to reason about -- every layout run starts from a clean slate.
 *
 * A fork of metabolic-network.js (the per-protein ego-network), not a parametrization of
 * it -- the payload shape (pathway-level aggregate stats) and interaction model (drill-in/
 * drill-out full-graph swap, vs. single fetch-then-render) differ enough that one shared
 * file would need a branchy "mode" through nearly every function.
 */
(function () {
    "use strict";

    var FONT_STACK = '"JetBrains Mono", "SFMono-Regular", Menlo, Consolas, monospace';

    function readToken(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }

    function readPalette() {
        return {
            plain: readToken("--tp-color-text-soft"),
            chokepoint: readToken("--tp-color-amber-500"),
            chokepointSoft: readToken("--tp-color-amber-050"),
            edge: readToken("--tp-color-text-primary"),
            ring: readToken("--tp-color-surface"),
            surfaceSoft: readToken("--tp-color-surface-soft"),
            text: readToken("--tp-color-text-primary"),
            textFaint: readToken("--tp-color-text-soft")
        };
    }

    function escapeHtml(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function compactLabel(label, max) {
        label = label || "";
        max = max || 20;
        if (label.length <= max) return label;
        return label.slice(0, max - 3) + "...";
    }

    // Pathway node size by reaction count -- sqrt scaling so a handful of very large
    // pathways don't dwarf everything else. Bounds validated against real KpATCC43816 data
    // (78 real pathways, median 7-8 reactions, p90 ~20, max 69): the floor of 28 is never
    // hit (no pathway has 0 reactions) and the cap of 90 is only reached by the artificial
    // "Unassigned metabolic reactions" bucket, which is the desired behavior.
    function pathwayDegreeToSize(reactionCount) {
        var n = reactionCount || 0;
        return Math.max(28, Math.min(90, 28 + Math.sqrt(n) * 7));
    }

    // Cutoffs validated against real KpATCC43816 chokepoint-density-per-pathway data: ~37%
    // of real pathways sit at 0%, so a "high density" tier starting at 35% was labeling
    // nearly 40% of all pathways as standouts. Raised to isolate roughly the top decile
    // (density-4, >=65%) and the next ~13% (density-3, >=45%).
    function densityTier(pct) {
        pct = pct || 0;
        if (pct >= 65) return "density-4";
        if (pct >= 45) return "density-3";
        if (pct >= 20) return "density-2";
        return "density-1";
    }

    function densityMixColor(palette, tierIndex) {
        var pct = [10, 28, 52, 82][tierIndex];
        return "color-mix(in srgb, " + palette.chokepoint + " " + pct + "%, " + palette.surfaceSoft + ")";
    }

    function maxEdgeWeight(edges) {
        var max = 1;
        (edges || []).forEach(function (e) {
            if ((e.weight || 0) > max) max = e.weight;
        });
        return max;
    }

    function buildCollapsedElements(payload) {
        var elements = [];
        var nodes = payload.nodes || [];
        var edges = payload.edges || [];
        var maxWeight = maxEdgeWeight(edges);

        var bestScore = 0;
        var bestNodeId = null;
        nodes.forEach(function (node) {
            if ((node.best_target_score || 0) > bestScore) {
                bestScore = node.best_target_score;
                bestNodeId = node.id;
            }
        });

        nodes.forEach(function (node) {
            var tier = densityTier(node.chokepoint_density_pct);
            var classes = [tier];
            var isTopTarget = node.id === bestNodeId && bestScore > 0;
            if (isTopTarget) classes.push("is-top-target");
            var size = pathwayDegreeToSize(node.reaction_count);
            // A real genome has dozens of pathway nodes -- labeling every one turns the
            // overview into an illegible wall of overlapping text. Only the pathways worth
            // noticing at a glance (large, chokepoint-dense, or the single best target)
            // get a permanent label; the rest are a bare dot, name still available via the
            // hover tooltip and revealed on hover through the .is-hovered label rule below.
            var showLabel = isTopTarget || tier === "density-3" || tier === "density-4" || size >= 55;
            elements.push({
                data: {
                    id: node.id,
                    label: node.name,
                    displayLabel: showLabel ? compactLabel(node.name, 20) : "",
                    source: node.source,
                    externalId: node.external_id,
                    reactionCount: node.reaction_count,
                    proteinCount: node.protein_count,
                    chokepointCount: node.chokepoint_count,
                    chokepointDensityPct: node.chokepoint_density_pct,
                    bestTargetScore: node.best_target_score,
                    meanTargetScore: node.mean_target_score,
                    topTargets: node.top_targets || [],
                    size: size
                },
                classes: classes.join(" ")
            });
        });

        edges.forEach(function (edge) {
            var weight = edge.weight || 1;
            elements.push({
                data: {
                    id: "pw-edge__" + edge.source + "__" + edge.target,
                    source: edge.source,
                    target: edge.target,
                    weight: weight,
                    width: 1 + Math.min(weight / maxWeight, 1) * 4
                }
            });
        });

        return elements;
    }

    function buildPathwayTooltip(nodeData) {
        var topTarget = (nodeData.topTargets || [])[0] || null;
        var bestLine = topTarget
            ? escapeHtml(topTarget.accession) + " &middot; " + nodeData.bestTargetScore
            : String(nodeData.bestTargetScore);
        return [
            '<div class="metabolic-network-tooltip-title">' + escapeHtml(nodeData.label || nodeData.id) + '</div>',
            '<dl>',
            '<dt>Reactions</dt><dd>' + nodeData.reactionCount + '</dd>',
            '<dt>Proteins</dt><dd>' + nodeData.proteinCount + '</dd>',
            '<dt>Chokepoints</dt><dd>' + nodeData.chokepointCount + ' (' + nodeData.chokepointDensityPct + '%)</dd>',
            '<dt>Best target</dt><dd>' + bestLine + '</dd>',
            '</dl>',
            '<div class="metabolic-network-tooltip-hint">Click to expand this pathway’s reactions.</div>'
        ].join("");
    }

    // Best target score isn't bounded to a known max here (formula-dependent), so the bar
    // clamps against a practical ceiling (1.0 covers the plain druggability+bonus fallback
    // heuristic in metabolism_network.py; custom ScoreFormula values above that just fill
    // the bar to 100% rather than overflow it).
    function scoreToBarPct(score) {
        var value = Number(score) || 0;
        return Math.max(0, Math.min(100, value * 100));
    }

    function updateInspectorForPathway(nodeData, pathwayUrlTemplate) {
        var inspector = document.getElementById("metabolic-network-genome-inspector");
        if (!inspector) return;
        var fields = {
            reactions: nodeData.reactionCount,
            proteins: nodeData.proteinCount,
            chokepoints: nodeData.chokepointCount + " (" + nodeData.chokepointDensityPct + "%)",
            score: nodeData.bestTargetScore
        };
        var title = inspector.querySelector('[data-field="name"]');
        if (title) title.textContent = nodeData.label || nodeData.id;
        Object.keys(fields).forEach(function (field) {
            var el = inspector.querySelector('[data-field="' + field + '"]');
            if (el) el.textContent = String(fields[field]);
        });
        var scoreBar = inspector.querySelector('[data-field="score-bar"]');
        if (scoreBar) scoreBar.style.width = scoreToBarPct(nodeData.bestTargetScore) + "%";
        var openMap = document.getElementById("metabolic-network-genome-open-map");
        if (openMap && pathwayUrlTemplate) {
            var url = pathwayUrlTemplate
                .replace("__SOURCE__", encodeURIComponent(nodeData.source))
                .replace("__EXTERNAL_ID__", encodeURIComponent(nodeData.externalId));
            openMap.href = url;
            openMap.hidden = false;
        }
    }

    function nodeStyleRules(palette) {
        var rules = [
            {
                selector: "node",
                style: {
                    "shape": "ellipse",
                    "width": "data(size)",
                    "height": "data(size)",
                    "border-width": 1.6,
                    "border-color": palette.plain,
                    "border-opacity": 0.85,
                    "label": "data(displayLabel)",
                    "color": palette.textFaint,
                    "font-family": FONT_STACK,
                    "font-size": 9.5,
                    "font-weight": 600,
                    "text-valign": "bottom",
                    "text-margin-y": 5,
                    "text-wrap": "ellipsis",
                    "text-max-width": "110px",
                    "text-background-color": palette.ring,
                    "text-background-opacity": 1,
                    "text-background-shape": "roundrectangle",
                    "text-background-padding": "2px",
                    "opacity": 0.96,
                    "transition-property": "opacity, border-width, border-color, width, height, background-color",
                    "transition-duration": "160ms",
                    "transition-timing-function": "ease-out"
                }
            },
            { selector: ".density-1", style: { "background-color": densityMixColor(palette, 0) } },
            { selector: ".density-2", style: { "background-color": densityMixColor(palette, 1) } },
            {
                selector: ".density-3",
                style: {
                    "background-color": densityMixColor(palette, 2),
                    "border-color": palette.chokepoint
                }
            },
            {
                selector: ".density-4",
                style: {
                    "background-color": densityMixColor(palette, 3),
                    "border-color": palette.chokepoint,
                    "border-width": 2.2,
                    "color": palette.chokepoint,
                    "font-weight": 800
                }
            },
            {
                selector: ".is-top-target",
                style: {
                    "overlay-color": palette.chokepoint,
                    "overlay-opacity": 0.14,
                    "overlay-padding": 10
                }
            },
            {
                selector: "node:selected",
                style: { "border-width": 3, "border-color": palette.text, "z-index": 40 }
            },
            {
                selector: ".is-hovered",
                style: { "border-width": 3, "border-color": palette.text, "opacity": 1, "z-index": 45 }
            },
            {
                // Scoped to the density-* classes (only ever set on pathway nodes) rather
                // than a bare "node.is-hovered", so it can't fight the reaction/metabolite
                // label rules from the shared reaction-graph module for specificity.
                selector: ".density-1.is-hovered, .density-2.is-hovered, .density-3.is-hovered, .density-4.is-hovered",
                style: { "label": "data(label)" }
            },
            { selector: ".is-muted", style: { "opacity": 0.18 } },
            {
                selector: "edge",
                style: {
                    "width": "data(width)",
                    "line-color": palette.edge,
                    "curve-style": "bezier",
                    "target-arrow-shape": "none",
                    "opacity": 0.55,
                    "line-cap": "round",
                    "transition-property": "opacity, width, line-color",
                    "transition-duration": "160ms"
                }
            },
            { selector: "edge.is-muted", style: { "opacity": 0.08 } },
            { selector: "edge.is-hovered", style: { "opacity": 0.9, "z-index": 30 } }
        ];
        // .reaction-node/.metabolite-node/.flow-in/.flow-out styling for a drilled-into
        // pathway's contents comes from the shared metabolic-reaction-graph.js module
        // (window.TPMetabolicReactionGraph.styleRules), concatenated onto this array by
        // the caller -- not duplicated here.
        return rules;
    }

    // Overview layout: tuned for a handful of large pathway-level nodes.
    function overviewLayout(extra) {
        var layout = {
            name: "fcose",
            animationEasing: "ease-out-cubic",
            nodeRepulsion: 11000,
            idealEdgeLength: 130,
            nodeSeparation: 80,
            gravity: 0.28,
            padding: 40,
            componentSpacing: 100,
            nodeDimensionsIncludeLabels: true
        };
        Object.keys(extra || {}).forEach(function (key) { layout[key] = extra[key]; });
        return layout;
    }

    // Detail layout: directed/layered and crossing-aware. The shared helper prefers
    // Dagre/Sugiyama when available and falls back to Cytoscape breadthfirst for old
    // bundles, keeping deploys tolerant while giving route maps a clearer flow.
    function detailLayout(roots) {
        return window.TPMetabolicReactionGraph.flowLayout(roots, {
            nodeSep: 54,
            rankSep: 104,
            padding: 30
        });
    }

    function initMetabolicNetworkGenome() {
        var container = document.getElementById("metabolic-network-genome-cy");
        if (!container || container.__tpMetabolicNetworkGenomeInitialized) {
            return;
        }
        container.__tpMetabolicNetworkGenomeInitialized = true;

        var note = document.getElementById("metabolic-network-genome-note");
        var hint = document.getElementById("metabolic-network-genome-hint");
        var breadcrumb = document.getElementById("metabolic-network-genome-breadcrumb");
        var breadcrumbCurrent = document.getElementById("metabolic-network-genome-breadcrumb-current");
        var backButton = document.getElementById("metabolic-network-genome-back");
        var inspector = document.getElementById("metabolic-network-genome-inspector");
        var inspectorDefaultName = inspector ? (inspector.querySelector('[data-field="name"]') || {}).textContent : "";
        var openMap = document.getElementById("metabolic-network-genome-open-map");

        function setNote(message) {
            if (!note) return;
            note.textContent = message || "";
            note.hidden = !message;
        }

        function dismissHint() {
            if (!hint) return;
            hint.classList.remove("is-visible");
            hint.classList.add("is-dismissed");
        }

        function resetInspector() {
            if (!inspector) return;
            var title = inspector.querySelector('[data-field="name"]');
            if (title) title.textContent = inspectorDefaultName;
            ["reactions", "proteins", "chokepoints", "score"].forEach(function (field) {
                var el = inspector.querySelector('[data-field="' + field + '"]');
                if (el) el.textContent = "-";
            });
            var scoreBar = inspector.querySelector('[data-field="score-bar"]');
            if (scoreBar) scoreBar.style.width = "0%";
            if (openMap) openMap.hidden = true;
        }

        var networkUrl = container.getAttribute("data-network-url");
        var expandUrlTemplate = container.getAttribute("data-expand-url-template");
        var pathwayUrlTemplate = container.getAttribute("data-pathway-url-template");
        if (!networkUrl || typeof window.cytoscape !== "function") {
            setNote("Metabolic network viewer is not available. Rebuild the static bundle.");
            return;
        }

        function expandUrl(source, externalId) {
            return expandUrlTemplate
                .replace("__SOURCE__", encodeURIComponent(source))
                .replace("__EXTERNAL_ID__", encodeURIComponent(externalId));
        }

        var tooltip = document.createElement("div");
        tooltip.className = "metabolic-network-tooltip";
        tooltip.style.display = "none";
        container.parentElement.appendChild(tooltip);

        var expandedPayloads = {};

        function clearHover(cy) {
            cy.elements(".is-hovered").removeClass("is-hovered");
            cy.elements(".is-muted").removeClass("is-muted");
        }

        function focusNeighborhood(cy, node) {
            clearHover(cy);
            var neighborhood = node.closedNeighborhood();
            cy.elements().not(neighborhood).addClass("is-muted");
            neighborhood.addClass("is-hovered");
            node.addClass("is-hovered");
        }

        fetch(networkUrl, { credentials: "same-origin" })
            .then(function (response) {
                if (!response.ok) throw new Error("network request failed");
                return response.json();
            })
            .then(function (payload) {
                if (!payload.nodes || !payload.nodes.length) {
                    setNote("No metabolic pathways are loaded for this genome yet.");
                    return;
                }
                setNote("");

                var collapsedElements = buildCollapsedElements(payload);
                var detailFontScale = 1;

                function combinedStyle(fontScale) {
                    var palette = readPalette();
                    return nodeStyleRules(palette).concat(window.TPMetabolicReactionGraph.styleRules(palette, fontScale));
                }

                var cy = window.cytoscape({
                    container: container,
                    elements: collapsedElements,
                    style: combinedStyle(1),
                    layout: overviewLayout({ animate: true, animationDuration: 900, randomize: true }),
                    minZoom: 0.2,
                    maxZoom: 6,
                    wheelSensitivity: 1,
                    userZoomingEnabled: true,
                    userPanningEnabled: true,
                    boxSelectionEnabled: false
                });

                if ("MutationObserver" in window) {
                    var themeObserver = new MutationObserver(function () {
                        cy.style(combinedStyle(detailFontScale)).update();
                    });
                    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
                }

                // A large pathway's reaction+metabolite subgraph (dozens of boxes) fit to a
                // small container can shrink well below the point where its labels are
                // legible -- the very information (which reactions are chokepoints) the
                // drill-in view exists to surface. Floor the zoom after fit so reaction
                // labels stay readable on entry, at the cost of not showing 100% of a very
                // large pathway without panning.
                var MIN_DETAIL_ZOOM = 0.7;
                var isDetailView = false;
                var firstLoad = true;
                cy.on("layoutstop", function () {
                    cy.fit(cy.elements(), 30);
                    if (isDetailView) {
                        // Rescale reaction/metabolite label size from the zoom this specific
                        // pathway's drill-in actually fit at (see item 4's base-size comment
                        // in metabolic-reaction-graph.js), before the min-zoom floor below.
                        detailFontScale = window.TPMetabolicReactionGraph.computeFontScale(cy.zoom());
                        if (Math.abs(detailFontScale - 1) > 0.05) {
                            cy.style(combinedStyle(detailFontScale)).update();
                            cy.fit(cy.elements(), 30);
                        }
                        if (cy.zoom() < MIN_DETAIL_ZOOM) {
                            cy.zoom({
                                level: MIN_DETAIL_ZOOM,
                                renderedPosition: { x: container.clientWidth / 2, y: container.clientHeight / 2 }
                            });
                        }
                    }
                    container.classList.add("is-ready");
                    if (firstLoad) {
                        firstLoad = false;
                        if (hint) hint.classList.add("is-visible");
                        window.setTimeout(dismissHint, 6000);
                    }
                });

                function showOverview() {
                    container.classList.remove("is-ready");
                    clearHover(cy);
                    tooltip.style.display = "none";
                    isDetailView = false;
                    detailFontScale = 1;
                    cy.elements().remove();
                    cy.add(collapsedElements);
                    cy.layout(overviewLayout({ animate: true, animationDuration: 700, randomize: true })).run();
                    if (breadcrumb) breadcrumb.hidden = true;
                    resetInspector();
                }

                function showDetail(nodeData, expandPayload) {
                    container.classList.remove("is-ready");
                    clearHover(cy);
                    tooltip.style.display = "none";
                    cy.elements().remove();
                    var detailElements = window.TPMetabolicReactionGraph.buildElements(expandPayload);
                    var roots = window.TPMetabolicReactionGraph.suggestRoots(detailElements);
                    cy.add(detailElements);
                    isDetailView = true;
                    cy.layout(detailLayout(roots)).run();
                    if (breadcrumb) breadcrumb.hidden = false;
                    if (breadcrumbCurrent) breadcrumbCurrent.textContent = nodeData.label || nodeData.id;
                }

                if (backButton) {
                    backButton.addEventListener("click", showOverview);
                }

                Array.prototype.forEach.call(
                    document.querySelectorAll("[data-metabolic-network-genome-action]"),
                    function (button) {
                        button.addEventListener("click", function () {
                            var action = button.getAttribute("data-metabolic-network-genome-action");
                            if (action === "fit") cy.fit(cy.elements(), 30);
                            if (action === "zoom-in") cy.zoom({ level: cy.zoom() * 1.18, renderedPosition: { x: container.clientWidth / 2, y: container.clientHeight / 2 } });
                            if (action === "zoom-out") cy.zoom({ level: cy.zoom() / 1.18, renderedPosition: { x: container.clientWidth / 2, y: container.clientHeight / 2 } });
                        });
                    }
                );

                cy.on("mouseover", "node", function (evt) {
                    var node = evt.target;
                    var data = node.data();
                    focusNeighborhood(cy, node);
                    if (data.isReaction === true) {
                        tooltip.innerHTML = window.TPMetabolicReactionGraph.tooltipForReaction(data);
                    } else if (data.isReaction === false) {
                        tooltip.innerHTML = window.TPMetabolicReactionGraph.tooltipForMetabolite(data);
                    } else {
                        tooltip.innerHTML = buildPathwayTooltip(data);
                        container.style.cursor = "pointer";
                    }
                    tooltip.style.display = "block";
                });
                cy.on("mousemove", "node", function (evt) {
                    var pos = evt.renderedPosition || evt.position;
                    tooltip.style.left = (container.offsetLeft + pos.x + 12) + "px";
                    tooltip.style.top = (container.offsetTop + pos.y + 12) + "px";
                });
                cy.on("mouseout", "node", function () {
                    clearHover(cy);
                    tooltip.style.display = "none";
                    container.style.cursor = "";
                });

                cy.on("tap", "node", function (evt) {
                    var node = evt.target;
                    var nodeData = node.data();

                    if (typeof nodeData.isReaction === "boolean") {
                        return; // reaction/metabolite detail is hover-only for now (tooltip above)
                    }

                    dismissHint();
                    updateInspectorForPathway(nodeData, pathwayUrlTemplate);

                    if (expandedPayloads[nodeData.id]) {
                        showDetail(nodeData, expandedPayloads[nodeData.id]);
                        return;
                    }

                    fetch(expandUrl(nodeData.source, nodeData.externalId), { credentials: "same-origin" })
                        .then(function (response) {
                            if (!response.ok) throw new Error("expand request failed");
                            return response.json();
                        })
                        .then(function (expandPayload) {
                            if (!expandPayload.reactions || !expandPayload.reactions.length) return;
                            expandedPayloads[nodeData.id] = expandPayload;
                            showDetail(nodeData, expandPayload);
                        })
                        .catch(function () {
                            /* leave the overview as-is; hover tooltip still works */
                        });
                });
            })
            .catch(function () {
                setNote("Unable to load the metabolic network.");
            });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initMetabolicNetworkGenome);
    } else {
        initMetabolicNetworkGenome();
    }

    window.tpMetabolicNetworkGenome = { init: initMetabolicNetworkGenome };
})();
