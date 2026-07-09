(function () {
    "use strict";

    function readToken(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }

    function readPalette() {
        return {
            focal: readToken("--tp-color-brand-700"),
            focalSoft: readToken("--tp-color-brand-050"),
            chokepoint: readToken("--tp-color-amber-500"),
            chokepointSoft: readToken("--tp-color-amber-050"),
            plain: readToken("--tp-color-text-soft"),
            edge: readToken("--tp-color-border-strong"),
            ring: readToken("--tp-color-surface"),
            surfaceSoft: readToken("--tp-color-surface-soft"),
            text: readToken("--tp-color-text-primary"),
            textFaint: readToken("--tp-color-text-soft"),
            groups: [
                { fill: readToken("--tp-color-sage-050"), line: readToken("--tp-color-sage-500"), ink: readToken("--tp-color-sage-700") },
                { fill: readToken("--tp-color-rose-050"), line: readToken("--tp-color-rose-500"), ink: readToken("--tp-color-rose-700") },
                { fill: readToken("--tp-color-amber-050"), line: readToken("--tp-color-amber-500"), ink: readToken("--tp-color-amber-700") },
                { fill: readToken("--tp-color-brand-050"), line: readToken("--tp-color-brand-300"), ink: readToken("--tp-color-brand-700") }
            ]
        };
    }

    var GROUP_COLOR_COUNT = 4;

    function degreeToSize(degree) {
        return 16 + Math.min(degree || 0, 10) * 2.4;
    }

    function compactReactionLabel(label) {
        label = label || "";
        if (label.length <= 22) return label;
        return label.slice(0, 20) + "…";
    }

    function assignPrimaryPathway(nodes, focalPathwayIds) {
        var groupOrder = [];
        var groupOf = {};
        nodes.forEach(function (node) {
            var pathways = node.pathways || [];
            if (!pathways.length) return;
            var shared = pathways.find(function (p) { return focalPathwayIds.indexOf(p.external_id) !== -1; });
            var chosen = shared || pathways.slice().sort(function (a, b) { return a.name.localeCompare(b.name); })[0];
            var key = chosen.source + "__" + chosen.external_id;
            if (groupOrder.indexOf(key) === -1) groupOrder.push(key);
            groupOf[node.id] = { key: key, name: chosen.name };
        });
        return { groupOf: groupOf, groupOrder: groupOrder };
    }

    function buildElements(payload) {
        var elements = [];
        var nodes = payload.nodes || [];
        var focal = nodes.find(function (n) { return n.is_focal; });
        var focalPathwayIds = (focal && focal.pathways || []).map(function (p) { return p.external_id; });
        var assignment = assignPrimaryPathway(nodes, focalPathwayIds);

        assignment.groupOrder.forEach(function (key, i) {
            var groupName = null;
            nodes.forEach(function (n) { if (assignment.groupOf[n.id] && assignment.groupOf[n.id].key === key) groupName = assignment.groupOf[n.id].name; });
            elements.push({
                group: "nodes",
                data: { id: "group__" + key, label: groupName, isGroup: true, groupIndex: i % GROUP_COLOR_COUNT },
                classes: "pathway-group"
            });
        });

        nodes.forEach(function (node) {
            var chokepointRole = node.chokepoint_role || "none";
            var hasChokepoint = chokepointRole !== "none";
            var isLabeled = node.is_focal || hasChokepoint;
            var group = assignment.groupOf[node.id];
            elements.push({
                data: {
                    id: node.id,
                    label: node.name,
                    displayLabel: isLabeled ? compactReactionLabel(node.name) : "",
                    ecNumbers: node.ec_numbers,
                    keggReactionId: node.kegg_reaction_id,
                    reversible: node.reversible,
                    chokepointRole: chokepointRole,
                    isoenzymeCount: node.isoenzyme_count || 0,
                    isFocal: node.is_focal,
                    degree: node.degree,
                    genes: node.genes || [],
                    size: degreeToSize(node.degree),
                    pathwayNames: (node.pathways || []).map(function (p) { return p.name; }).join(", "),
                    parent: group ? ("group__" + group.key) : undefined
                },
                classes: [
                    hasChokepoint ? "has-chokepoint" : "",
                    node.is_focal ? "is-focal" : ""
                ].join(" ").trim()
            });
        });
        (payload.edges || []).forEach(function (edge) {
            var srcGroup = assignment.groupOf[edge.source] && assignment.groupOf[edge.source].key;
            var tgtGroup = assignment.groupOf[edge.target] && assignment.groupOf[edge.target].key;
            var isCross = Boolean(srcGroup && tgtGroup && srcGroup !== tgtGroup);
            elements.push({
                data: {
                    id: edge.source + "__" + edge.target,
                    source: edge.source,
                    target: edge.target
                },
                classes: isCross ? "edge-cross" : ""
            });
        });
        return elements;
    }

    function buildTooltipText(nodeData) {
        var parts = [nodeData.label];
        if (nodeData.ecNumbers) {
            parts.push("EC " + nodeData.ecNumbers);
        }
        parts.push(nodeData.pathwayNames ? nodeData.pathwayNames : "No pathway assigned");
        if (nodeData.chokepointRole && nodeData.chokepointRole !== "none") {
            parts.push("Chokepoint: " + nodeData.chokepointRole);
            parts.push(nodeData.isoenzymeCount > 1 ? nodeData.isoenzymeCount + " isoenzymes" : "no isoenzyme backup");
        }
        var genes = (nodeData.genes || []).map(function (g) { return g.locus_tag; });
        if (genes.length) {
            parts.push("Gene(s): " + genes.join(", "));
        }
        return parts.join(" — ");
    }

    function formatRole(role) {
        if (!role || role === "none") return "None";
        return role.replace(/_/g, " ");
    }

    function updateInspector(nodeData) {
        var inspector = document.getElementById("metabolic-network-inspector");
        if (!inspector || !nodeData) return;
        var genes = (nodeData.genes || []).map(function (g) { return g.locus_tag; }).filter(Boolean);
        var fields = {
            name: nodeData.label || nodeData.id || "-",
            ec: nodeData.ecNumbers || "-",
            pathway: nodeData.pathwayNames || "No pathway assigned",
            genes: genes.length ? genes.join(", ") : "-",
            role: formatRole(nodeData.chokepointRole),
            isoenzymes: nodeData.isoenzymeCount > 1 ? String(nodeData.isoenzymeCount) : "None"
        };
        Object.keys(fields).forEach(function (field) {
            var el = inspector.querySelector('[data-field="' + field + '"]');
            if (el) el.textContent = fields[field];
        });
    }

    function updateNetworkNote(container, payload) {
        var note = container.parentElement.querySelector(".metabolic-network-note");
        if (!note) {
            note = document.createElement("div");
            note.className = "metabolic-network-note";
            container.parentElement.appendChild(note);
        }
        var meta = payload.meta || {};
        var baseText = "Two-hop reaction neighborhood around this protein; pathway boxes use one primary KEGG route per reaction when several mappings exist.";
        if (meta.is_truncated) {
            note.textContent = baseText + " Display is capped at " + meta.max_nodes + " reactions for readability; use the genome-wide pathway page for route-level ranking.";
        } else {
            note.textContent = baseText;
        }
        note.hidden = false;
    }

    function navigateToNeighborGene(nodeData) {
        var genes = nodeData.genes || [];
        var target = genes.find(function (g) { return !g.is_current_protein && g.url; });
        if (target) {
            window.location.href = target.url;
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
                    "background-fill": "radial-gradient",
                    "background-gradient-stop-colors": palette.surfaceSoft + " " + palette.ring,
                    "background-gradient-stop-positions": "0 100",
                    "border-width": 1.6,
                    "border-color": palette.plain,
                    "border-opacity": 0.85,
                    "label": "data(displayLabel)",
                    "color": palette.textFaint,
                    "font-size": 9,
                    "font-weight": 500,
                    "text-valign": "bottom",
                    "text-margin-y": 5,
                    "text-wrap": "ellipsis",
                    "text-max-width": "110px",
                    "text-outline-color": palette.ring,
                    "text-outline-width": 2,
                    "opacity": 0.92
                }
            },
            {
                selector: ".has-chokepoint",
                style: {
                    "shape": "diamond",
                    "background-gradient-stop-colors": palette.chokepointSoft + " " + palette.ring,
                    "border-color": palette.chokepoint,
                    "border-width": 1.8,
                    "color": palette.chokepoint,
                    "font-weight": 700,
                    "opacity": 1,
                    "z-index": 10
                }
            },
            {
                selector: ".is-focal",
                style: {
                    "background-gradient-stop-colors": palette.focalSoft + " " + palette.ring,
                    "border-color": palette.focal,
                    "width": 32,
                    "height": 32,
                    "font-weight": 700,
                    "border-width": 3,
                    "color": palette.text,
                    "opacity": 1,
                    "z-index": 20
                }
            },
            {
                selector: "node:selected",
                style: {
                    "border-width": 3,
                    "border-color": palette.text
                }
            },
            {
                selector: "edge",
                style: {
                    "width": 1.4,
                    "line-color": palette.edge,
                    "curve-style": "bezier",
                    "opacity": 0.55,
                    "line-cap": "round"
                }
            },
            {
                selector: ".edge-cross",
                style: {
                    "width": 1.6,
                    "line-color": palette.textFaint,
                    "opacity": 0.85,
                    "line-style": "dashed",
                    "line-dash-pattern": [3, 3]
                }
            },
            {
                selector: ".pathway-group",
                style: {
                    "shape": "round-rectangle",
                    "background-opacity": 1,
                    "border-width": 1,
                    "border-opacity": 0.9,
                    "padding": "26px",
                    "corner-radius": 12,
                    "label": "data(label)",
                    "text-valign": "top",
                    "text-halign": "left",
                    "text-margin-x": 8,
                    "text-margin-y": -16,
                    "font-size": 10.5,
                    "font-weight": 700,
                    "text-transform": "uppercase"
                }
            }
        ];
        (palette.groups || []).forEach(function (g, i) {
            rules.push({
                selector: ".pathway-group[groupIndex = " + i + "]",
                style: { "background-color": g.fill, "border-color": g.line, "color": g.ink }
            });
        });
        return rules;
    }

    function initMetabolicNetwork() {
        var container = document.getElementById("metabolic-network-cy");
        if (!container || container.__tpMetabolicNetworkInitialized) {
            return;
        }
        container.__tpMetabolicNetworkInitialized = true;

        function setState(className, message) {
            container.classList.remove("metabolic-network-loading", "metabolic-network-empty", "metabolic-network-error");
            container.classList.add(className);
            container.textContent = message || "";
        }

        var networkUrl = container.getAttribute("data-network-url");
        if (!networkUrl) {
            setState("metabolic-network-error", "Metabolic network URL is not available.");
            return;
        }
        if (typeof window.cytoscape !== "function") {
            setState("metabolic-network-error", "Metabolic network viewer is not available. Rebuild the static bundle.");
            return;
        }
        setState("metabolic-network-loading", "Loading metabolic network…");

        var tooltip = document.createElement("div");
        tooltip.className = "metabolic-network-tooltip";
        tooltip.style.display = "none";
        container.parentElement.appendChild(tooltip);
        var lastTappedNodeId = null;
        var lastTappedAt = 0;

        fetch(networkUrl, { credentials: "same-origin" })
            .then(function (response) {
                if (!response.ok) throw new Error("network request failed");
                return response.json();
            })
            .then(function (payload) {
                if (!payload.nodes || !payload.nodes.length) {
                    setState("metabolic-network-empty", "No neighboring metabolic reactions were found.");
                    return;
                }
                updateNetworkNote(container, payload);
                container.classList.remove("metabolic-network-loading", "metabolic-network-empty", "metabolic-network-error");
                container.textContent = "";

                var cy = window.cytoscape({
                    container: container,
                    elements: buildElements(payload),
                    style: nodeStyleRules(readPalette()),
                    layout: {
                        name: "fcose",
                        animate: true,
                        animationDuration: 800,
                        animationEasing: "ease-out-cubic",
                        nodeRepulsion: 10500,
                        idealEdgeLength: 100,
                        nodeSeparation: 70,
                        gravity: 0.24,
                        padding: 44,
                        componentSpacing: 90
                    },
                    minZoom: 0.3,
                    maxZoom: 3.5,
                    wheelSensitivity: 0.25,
                    userZoomingEnabled: true,
                    userPanningEnabled: true,
                    boxSelectionEnabled: false
                });

                if ("MutationObserver" in window) {
                    var themeObserver = new MutationObserver(function () {
                        cy.style(nodeStyleRules(readPalette())).update();
                    });
                    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
                }

                cy.ready(function () {
                    var focal = cy.nodes(".is-focal").first();
                    if (focal.length) {
                        focal.select();
                        updateInspector(focal.data());
                    }
                    cy.one("layoutstop", function () { cy.fit(cy.elements(), 40); });
                });

                Array.prototype.forEach.call(document.querySelectorAll("[data-metabolic-action]"), function (button) {
                    button.addEventListener("click", function () {
                        var action = button.getAttribute("data-metabolic-action");
                        if (action === "fit") cy.fit(cy.elements(), 40);
                        if (action === "zoom-in") cy.zoom({ level: cy.zoom() * 1.18, renderedPosition: { x: container.clientWidth / 2, y: container.clientHeight / 2 } });
                        if (action === "zoom-out") cy.zoom({ level: cy.zoom() / 1.18, renderedPosition: { x: container.clientWidth / 2, y: container.clientHeight / 2 } });
                    });
                });

                cy.on("mouseover", "node", function (evt) {
                    if (evt.target.data("isGroup")) return;
                    var node = evt.target;
                    tooltip.textContent = buildTooltipText(node.data());
                    tooltip.style.display = "block";
                });
                cy.on("mousemove", "node", function (evt) {
                    if (evt.target.data("isGroup")) return;
                    var pos = evt.renderedPosition || evt.position;
                    tooltip.style.left = (pos.x + 12) + "px";
                    tooltip.style.top = (pos.y + 12) + "px";
                });
                cy.on("mouseout", "node", function () {
                    tooltip.style.display = "none";
                });
                cy.on("tap", "node", function (evt) {
                    if (evt.target.data("isGroup")) return;
                    var nodeData = evt.target.data();
                    var now = Date.now();
                    updateInspector(nodeData);
                    if (lastTappedNodeId === nodeData.id && now - lastTappedAt < 900) {
                        navigateToNeighborGene(nodeData);
                    }
                    lastTappedNodeId = nodeData.id;
                    lastTappedAt = now;
                });
            })
            .catch(function () {
                setState("metabolic-network-error", "Unable to load the metabolic network.");
            });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initMetabolicNetwork);
    } else {
        initMetabolicNetwork();
    }

    window.tpMetabolicNetwork = { init: initMetabolicNetwork };
})();
