(function () {
    "use strict";

    var CHOKEPOINT_COLORS = {
        none: "#b8c4ca",
        producing: "#f3b43f",
        consuming: "#5f7fd5",
        both: "#c84d7d"
    };

    function degreeToSize(degree) {
        var size = 18 + Math.min(degree || 0, 10) * 3.2;
        return size;
    }

    function compactReactionLabel(label) {
        label = label || "";
        if (label.length <= 20) return label;
        return label.slice(0, 18) + "...";
    }

    function labelToWidth(label) {
        return Math.max(104, Math.min(178, (label || "").length * 7.4 + 28));
    }

    function buildElements(payload) {
        var elements = [];
        (payload.nodes || []).forEach(function (node) {
            var chokepointRole = node.chokepoint_role || "none";
            var isLabeled = node.is_focal || chokepointRole !== "none";
            var displayLabel = isLabeled ? compactReactionLabel(node.name) : "";
            elements.push({
                data: {
                    id: node.id,
                    label: node.name,
                    displayLabel: displayLabel,
                    ecNumbers: node.ec_numbers,
                    keggReactionId: node.kegg_reaction_id,
                    reversible: node.reversible,
                    chokepointRole: chokepointRole,
                    isFocal: node.is_focal,
                    degree: node.degree,
                    genes: node.genes || [],
                    size: degreeToSize(node.degree),
                    nodeWidth: isLabeled ? labelToWidth(displayLabel) : degreeToSize(node.degree)
                },
                classes: [
                    "chokepoint-" + chokepointRole,
                    node.is_focal ? "is-focal" : ""
                ].join(" ").trim()
            });
        });
        (payload.edges || []).forEach(function (edge) {
            elements.push({
                data: {
                    id: edge.source + "__" + edge.target,
                    source: edge.source,
                    target: edge.target
                }
            });
        });
        return elements;
    }

    function buildTooltipText(nodeData) {
        var parts = [nodeData.label];
        if (nodeData.ecNumbers) {
            parts.push("EC " + nodeData.ecNumbers);
        }
        if (nodeData.chokepointRole && nodeData.chokepointRole !== "none") {
            parts.push("Chokepoint: " + nodeData.chokepointRole);
        }
        var genes = (nodeData.genes || []).map(function (g) { return g.locus_tag; });
        if (genes.length) {
            parts.push("Gene(s): " + genes.join(", "));
        }
        return parts.join(" - ");
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
            genes: genes.length ? genes.join(", ") : "-",
            role: formatRole(nodeData.chokepointRole)
        };
        Object.keys(fields).forEach(function (field) {
            var el = inspector.querySelector('[data-field="' + field + '"]');
            if (el) el.textContent = fields[field];
        });
    }

    function navigateToNeighborGene(nodeData) {
        var genes = nodeData.genes || [];
        var target = genes.find(function (g) { return !g.is_current_protein && g.url; });
        if (target) {
            window.location.href = target.url;
        }
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
        setState("metabolic-network-loading", "Loading metabolic network...");

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
                container.classList.remove("metabolic-network-loading", "metabolic-network-empty", "metabolic-network-error");
                container.textContent = "";

                var cy = window.cytoscape({
                    container: container,
                    elements: buildElements(payload),
                    style: [
                        {
                            selector: "node",
                            style: {
                                "background-color": CHOKEPOINT_COLORS.none,
                                "label": "data(displayLabel)",
                                "width": "data(size)",
                                "height": "data(size)",
                                "shape": "ellipse",
                                "font-size": 8,
                                "font-weight": 700,
                                "text-valign": "bottom",
                                "text-margin-y": 6,
                                "color": "#1f3550",
                                "text-wrap": "ellipsis",
                                "text-max-width": "102px",
                                "text-background-color": "#fbfaf5",
                                "text-background-opacity": 0.96,
                                "text-background-padding": 2,
                                "text-border-opacity": 0,
                                "border-width": 2,
                                "border-color": "#ffffff",
                                "opacity": 0.82
                            }
                        },
                        {
                            selector: ".chokepoint-producing, .chokepoint-consuming, .chokepoint-both",
                            style: {
                                "shape": "round-rectangle",
                                "width": "data(nodeWidth)",
                                "height": 36,
                                "text-valign": "center",
                                "text-halign": "center",
                                "text-margin-y": 0,
                                "font-size": 8,
                                "text-wrap": "none",
                                "text-max-width": "data(nodeWidth)",
                                "text-background-opacity": 0,
                                "border-width": 2.5,
                                "border-color": "#ffffff",
                                "opacity": 1
                            }
                        },
                        { selector: ".chokepoint-producing", style: { "background-color": CHOKEPOINT_COLORS.producing, "color": "#3b2a05" } },
                        { selector: ".chokepoint-consuming", style: { "background-color": CHOKEPOINT_COLORS.consuming, "color": "#ffffff" } },
                        { selector: ".chokepoint-both", style: { "background-color": CHOKEPOINT_COLORS.both, "color": "#ffffff" } },
                        {
                            selector: ".is-focal",
                            style: {
                                "shape": "round-rectangle",
                                "background-color": "#00a6a6",
                                "color": "#ffffff",
                                "border-width": 3.5,
                                "border-color": "#143b5c",
                                "font-weight": "bold",
                                "width": "data(nodeWidth)",
                                "height": 38,
                                "text-valign": "center",
                                "text-halign": "center",
                                "text-background-opacity": 0,
                                "opacity": 1
                            }
                        },
                        {
                            selector: "node:selected",
                            style: {
                                "label": "data(displayLabel)",
                                "border-width": 4,
                                "border-color": "#143b5c",
                                "z-index": 20
                            }
                        },
                        {
                            selector: "edge",
                            style: {
                                "width": 1.6,
                                "line-color": "#9fb2be",
                                "curve-style": "bezier",
                                "opacity": 0.58
                            }
                        }
                    ],
                    layout: {
                        name: "fcose",
                        animate: false,
                        nodeRepulsion: 13000,
                        idealEdgeLength: 96,
                        nodeSeparation: 56,
                        gravity: 0.22,
                        padding: 46
                    },
                    minZoom: 0.18,
                    maxZoom: 3.5,
                    userZoomingEnabled: false,
                    boxSelectionEnabled: false
                });

                cy.ready(function () {
                    var focal = cy.nodes(".is-focal").first();
                    if (focal.length) {
                        focal.select();
                        updateInspector(focal.data());
                    }
                    cy.fit(cy.elements(), 46);
                });

                Array.prototype.forEach.call(document.querySelectorAll("[data-metabolic-action]"), function (button) {
                    button.addEventListener("click", function () {
                        var action = button.getAttribute("data-metabolic-action");
                        if (action === "fit") cy.fit(cy.elements(), 46);
                        if (action === "zoom-in") cy.zoom({ level: cy.zoom() * 1.18, renderedPosition: { x: container.clientWidth / 2, y: container.clientHeight / 2 } });
                        if (action === "zoom-out") cy.zoom({ level: cy.zoom() / 1.18, renderedPosition: { x: container.clientWidth / 2, y: container.clientHeight / 2 } });
                    });
                });

                cy.on("mouseover", "node", function (evt) {
                    var node = evt.target;
                    tooltip.textContent = buildTooltipText(node.data());
                    tooltip.style.display = "block";
                });
                cy.on("mousemove", "node", function (evt) {
                    var pos = evt.renderedPosition || evt.position;
                    tooltip.style.left = (pos.x + 12) + "px";
                    tooltip.style.top = (pos.y + 12) + "px";
                });
                cy.on("mouseout", "node", function () {
                    tooltip.style.display = "none";
                });
                cy.on("tap", "node", function (evt) {
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
