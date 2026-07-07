(function () {
    "use strict";

    var CHOKEPOINT_COLORS = {
        none: "#9aa5ab",
        producing: "#c9822a",
        consuming: "#5a7fb0",
        both: "#b0475a"
    };

    function degreeToSize(degree) {
        var size = 24 + Math.min(degree, 10) * 4;
        return size;
    }

    function buildElements(payload) {
        var elements = [];
        (payload.nodes || []).forEach(function (node) {
            elements.push({
                data: {
                    id: node.id,
                    label: node.name,
                    ecNumbers: node.ec_numbers,
                    keggReactionId: node.kegg_reaction_id,
                    reversible: node.reversible,
                    chokepointRole: node.chokepoint_role,
                    isFocal: node.is_focal,
                    degree: node.degree,
                    genes: node.genes || [],
                    size: degreeToSize(node.degree)
                },
                classes: [
                    "chokepoint-" + (node.chokepoint_role || "none"),
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
                                "label": "data(label)",
                                "width": "data(size)",
                                "height": "data(size)",
                                "font-size": 9,
                                "text-valign": "bottom",
                                "text-margin-y": 4,
                                "color": "#4a5560",
                                "text-wrap": "ellipsis",
                                "text-max-width": "90px"
                            }
                        },
                        { selector: ".chokepoint-producing", style: { "background-color": CHOKEPOINT_COLORS.producing } },
                        { selector: ".chokepoint-consuming", style: { "background-color": CHOKEPOINT_COLORS.consuming } },
                        { selector: ".chokepoint-both", style: { "background-color": CHOKEPOINT_COLORS.both } },
                        {
                            selector: ".is-focal",
                            style: {
                                "border-width": 3,
                                "border-color": "#1f6f43",
                                "font-weight": "bold"
                            }
                        },
                        {
                            selector: "edge",
                            style: {
                                "width": 1.5,
                                "line-color": "#c7ccd1",
                                "curve-style": "bezier"
                            }
                        }
                    ],
                    layout: { name: "fcose", animate: false, nodeRepulsion: 8000 },
                    minZoom: 0.2,
                    maxZoom: 3
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
                    navigateToNeighborGene(evt.target.data());
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
