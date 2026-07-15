/* Genome-wide unified metabolic network graph: pathway-level nodes, collapsed on load,
 * expand in place (as Cytoscape compound/child nodes) on click. A fork of
 * metabolic-network.js (the per-protein ego-network), not a parametrization of it -- the
 * payload shape (pathway-level aggregate stats) and interaction model (tap-to-expand plus
 * a second fetch and incremental element-add, vs. single fetch-then-render) differ enough
 * that one shared file would need a branchy "mode" through nearly every function.
 *
 * Two things are unverified against a live browser in this sandbox and should be smoke-
 * tested first on a real genome: (1) that a plain leaf node correctly becomes a Cytoscape
 * compound parent once children referencing its id are cy.add()-ed after the fact --
 * standard, well-supported Cytoscape.js behavior (the same mechanism cytoscape-expand-
 * collapse itself relies on), but not run against a live instance here; (2) that re-running
 * fcose with randomize:false reads as "growing in place" rather than a visible reshuffle --
 * plausible (existing node positions seed the simulation instead of being randomized) but
 * also not confirmed live here.
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
            edge: readToken("--tp-color-border-strong"),
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
    // pathways (100+ reactions) don't dwarf everything else. Concrete bounds picked from
    // typical bacterial KEGG-pathway reaction-count ranges (roughly 1-100); recalibrate
    // against a real genome's actual distribution (e.g. KpATCC43816) once this is deployed.
    function pathwayDegreeToSize(reactionCount) {
        var n = reactionCount || 0;
        return Math.max(28, Math.min(90, 28 + Math.sqrt(n) * 7));
    }

    function densityTier(pct) {
        pct = pct || 0;
        if (pct >= 60) return "density-4";
        if (pct >= 35) return "density-3";
        if (pct >= 15) return "density-2";
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
            if (node.id === bestNodeId && bestScore > 0) classes.push("is-top-target");
            elements.push({
                data: {
                    id: node.id,
                    label: node.name,
                    displayLabel: compactLabel(node.name, 20),
                    source: node.source,
                    externalId: node.external_id,
                    reactionCount: node.reaction_count,
                    proteinCount: node.protein_count,
                    chokepointCount: node.chokepoint_count,
                    chokepointDensityPct: node.chokepoint_density_pct,
                    bestTargetScore: node.best_target_score,
                    meanTargetScore: node.mean_target_score,
                    topTargets: node.top_targets || [],
                    size: pathwayDegreeToSize(node.reaction_count),
                    isGroup: false
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
                    "text-outline-color": palette.ring,
                    "text-outline-width": 3,
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
            { selector: "edge.is-hovered", style: { "opacity": 0.9, "z-index": 30 } },
            {
                selector: ".pathway-group",
                style: {
                    "shape": "round-rectangle",
                    "background-color": palette.surfaceSoft,
                    "background-opacity": 1,
                    "border-width": 1.5,
                    "border-color": palette.plain,
                    "border-opacity": 1,
                    "padding": "24px",
                    "corner-radius": 14,
                    "label": "data(displayLabel)",
                    "text-valign": "top",
                    "text-halign": "left",
                    "text-margin-x": 8,
                    "text-margin-y": -20,
                    "font-family": FONT_STACK,
                    "font-size": 12,
                    "font-weight": 800,
                    "text-transform": "uppercase",
                    "text-outline-color": palette.ring,
                    "text-outline-width": 2,
                    "overlay-opacity": 0
                }
            },
        ];
        // .reaction-node/.metabolite-node/.flow-in/.flow-out styling for an expanded
        // pathway's contents comes from the shared metabolic-reaction-graph.js module
        // (window.TPMetabolicReactionGraph.styleRules), concatenated onto this array by
        // the caller -- not duplicated here.
        return rules;
    }

    function baseLayout(extra) {
        var layout = {
            name: "fcose",
            animationEasing: "ease-out-cubic",
            nodeRepulsion: 11000,
            idealEdgeLength: 130,
            nodeSeparation: 80,
            gravity: 0.28,
            padding: 40,
            componentSpacing: 100,
            nestingFactor: 0.5,
            nodeDimensionsIncludeLabels: true
        };
        Object.keys(extra || {}).forEach(function (key) { layout[key] = extra[key]; });
        return layout;
    }

    function initMetabolicNetworkGenome() {
        var container = document.getElementById("metabolic-network-genome-cy");
        if (!container || container.__tpMetabolicNetworkGenomeInitialized) {
            return;
        }
        container.__tpMetabolicNetworkGenomeInitialized = true;

        var note = document.getElementById("metabolic-network-genome-note");

        function setNote(message) {
            if (!note) return;
            note.textContent = message || "";
            note.hidden = !message;
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

        var expanded = {};

        function clearHover(cy) {
            cy.elements(".is-hovered").removeClass("is-hovered");
            cy.elements(".is-muted").removeClass("is-muted");
        }

        function focusNeighborhood(cy, node) {
            clearHover(cy);
            var neighborhood = node.closedNeighborhood();
            cy.elements().not(neighborhood).not(".pathway-group").addClass("is-muted");
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

                function combinedStyle() {
                    var palette = readPalette();
                    return nodeStyleRules(palette).concat(window.TPMetabolicReactionGraph.styleRules(palette));
                }

                var cy = window.cytoscape({
                    container: container,
                    elements: buildCollapsedElements(payload),
                    style: combinedStyle(),
                    layout: baseLayout({ animate: true, animationDuration: 900, randomize: true }),
                    minZoom: 0.2,
                    maxZoom: 3.5,
                    wheelSensitivity: 1,
                    userZoomingEnabled: true,
                    userPanningEnabled: true,
                    boxSelectionEnabled: false
                });

                if ("MutationObserver" in window) {
                    var themeObserver = new MutationObserver(function () {
                        cy.style(combinedStyle()).update();
                    });
                    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
                }

                cy.one("layoutstop", function () {
                    cy.fit(cy.elements(), 30);
                    container.classList.add("is-ready");
                });

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
                });

                cy.on("tap", "node", function (evt) {
                    var node = evt.target;
                    var nodeData = node.data();

                    if (typeof nodeData.isReaction === "boolean") {
                        return; // reaction/metabolite detail is hover-only for now (tooltip above)
                    }

                    updateInspectorForPathway(nodeData, pathwayUrlTemplate);

                    if (expanded[nodeData.id]) {
                        return; // already expanded -- no re-fetch, no collapse-back in v1
                    }

                    fetch(expandUrl(nodeData.source, nodeData.externalId), { credentials: "same-origin" })
                        .then(function (response) {
                            if (!response.ok) throw new Error("expand request failed");
                            return response.json();
                        })
                        .then(function (expandPayload) {
                            if (!expandPayload.reactions || !expandPayload.reactions.length) return;
                            expanded[nodeData.id] = true;
                            node.removeClass("density-1 density-2 density-3 density-4 is-top-target");
                            node.addClass("pathway-group");
                            node.data("isGroup", true);
                            cy.add(window.TPMetabolicReactionGraph.buildElements(expandPayload, {
                                idPrefix: nodeData.id + "::",
                                parentId: nodeData.id
                            }));
                            cy.layout(baseLayout({ animate: true, animationDuration: 500, randomize: false, fit: false })).run();
                        })
                        .catch(function () {
                            /* leave the node collapsed; hover tooltip still works */
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
