/* Shared reaction+metabolite Cytoscape graph builder -- a real bipartite graph (reactions
 * and metabolites as separate nodes, directed substrate/product edges between them), not
 * a per-reaction row diagram. A metabolite produced by one reaction and consumed by
 * another renders as a single connecting node, so the flow through a pathway is actually
 * visible as a graph.
 *
 * Used by two independent call sites, which is why this lives in its own small shared
 * file instead of being duplicated or folded into either: (1) metabolic-network-genome.js,
 * embedding this as children under an already-expanded pathway-group node; (2) the
 * standalone per-pathway page, rendering it as its own top-level Cytoscape instance
 * (replacing the previous hand-drawn SVG substrate/reaction/product row diagram).
 */
(function () {
    "use strict";

    var FONT_STACK = '"JetBrains Mono", "SFMono-Regular", Menlo, Consolas, monospace';

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
        max = max || 16;
        if (label.length <= max) return label;
        return label.slice(0, max - 3) + "...";
    }

    function formatRole(role) {
        if (!role || role === "none") return "None";
        return role.replace(/_/g, " ");
    }

    function buildElements(payload, options) {
        options = options || {};
        var idPrefix = options.idPrefix || "";
        var parentId = options.parentId || null;
        var elements = [];
        var metaboliteById = {};

        (payload.metabolites || []).forEach(function (m) { metaboliteById[m.id] = m; });

        (payload.reactions || []).forEach(function (reaction) {
            var hasChokepoint = (reaction.chokepoint_role || "none") !== "none";
            var data = {
                id: idPrefix + "rxn::" + reaction.id,
                label: reaction.name,
                displayLabel: compactLabel(reaction.name, hasChokepoint ? 20 : 16),
                ecNumbers: reaction.ec_numbers || [],
                chokepointRole: reaction.chokepoint_role || "none",
                isoenzymeCount: reaction.isoenzyme_count || 0,
                genes: reaction.genes || [],
                isReaction: true
            };
            if (parentId) data.parent = parentId;
            elements.push({
                data: data,
                classes: ["reaction-node", hasChokepoint ? "has-chokepoint" : ""].join(" ").trim()
            });
        });

        (payload.metabolites || []).forEach(function (metabolite) {
            var data = {
                id: idPrefix + "met::" + metabolite.id,
                label: metabolite.name,
                displayLabel: compactLabel(metabolite.name, metabolite.is_currency ? 10 : 16),
                compartment: metabolite.compartment,
                isCurrency: metabolite.is_currency,
                isReaction: false
            };
            if (parentId) data.parent = parentId;
            elements.push({
                data: data,
                classes: ["metabolite-node", metabolite.is_currency ? "is-currency" : ""].join(" ").trim()
            });
        });

        (payload.participants || []).forEach(function (p, i) {
            var metabolite = metaboliteById[p.species_id];
            var isCurrency = Boolean(metabolite && metabolite.is_currency);
            var reactionNodeId = idPrefix + "rxn::" + p.reaction_id;
            var metaboliteNodeId = idPrefix + "met::" + p.species_id;
            var isReactant = p.role === "reactant";
            var classes = [isReactant ? "flow-in" : "flow-out"];
            if (isCurrency) classes.push("flow-currency");
            elements.push({
                data: {
                    id: idPrefix + "edge::" + i,
                    source: isReactant ? metaboliteNodeId : reactionNodeId,
                    target: isReactant ? reactionNodeId : metaboliteNodeId
                },
                classes: classes.join(" ")
            });
        });

        return elements;
    }

    function styleRules(palette) {
        return [
            {
                selector: ".reaction-node",
                style: {
                    "shape": "round-rectangle",
                    "width": "label",
                    "height": 22,
                    "padding": "6px",
                    "background-color": palette.surfaceSoft,
                    "border-width": 1.4,
                    "border-color": palette.plain,
                    "label": "data(displayLabel)",
                    "font-family": FONT_STACK,
                    "font-size": 9,
                    "font-weight": 700,
                    "color": palette.text,
                    "text-valign": "center",
                    "text-halign": "center",
                    "text-max-width": "130px",
                    "text-wrap": "ellipsis"
                }
            },
            {
                selector: ".reaction-node.has-chokepoint",
                style: {
                    "background-color": palette.chokepointSoft,
                    "border-color": palette.chokepoint,
                    "color": palette.chokepoint,
                    "border-width": 2,
                    "font-weight": 800
                }
            },
            {
                selector: ".metabolite-node",
                style: {
                    "shape": "ellipse",
                    "width": 14,
                    "height": 14,
                    "background-color": palette.plain,
                    "border-width": 1,
                    "border-color": palette.ring,
                    "label": "data(displayLabel)",
                    "font-family": FONT_STACK,
                    "font-size": 7.5,
                    "font-weight": 500,
                    "color": palette.textFaint,
                    "text-valign": "bottom",
                    "text-margin-y": 3,
                    "text-max-width": "70px",
                    "text-outline-color": palette.ring,
                    "text-outline-width": 2
                }
            },
            {
                selector: ".metabolite-node.is-currency",
                style: { "width": 8, "height": 8, "opacity": 0.6, "font-size": 6.5 }
            },
            {
                selector: ".flow-in, .flow-out",
                style: {
                    "curve-style": "bezier",
                    "width": 1.3,
                    "line-color": palette.edge,
                    "opacity": 0.6,
                    "target-arrow-shape": "triangle",
                    "target-arrow-color": palette.edge,
                    "arrow-scale": 0.7
                }
            },
            {
                selector: ".flow-currency",
                style: { "opacity": 0.22, "width": 1 }
            },
            {
                selector: "node:selected",
                style: { "border-width": 3, "border-color": palette.text, "z-index": 40 }
            }
        ];
    }

    function tooltipForReaction(data) {
        var genes = (data.genes || []).map(function (g) { return g.accession; });
        var role = data.chokepointRole && data.chokepointRole !== "none" ? formatRole(data.chokepointRole) : "";
        var roleBadge = role ? '<span class="metabolic-network-tooltip-badge">' + escapeHtml(role) + '</span>' : "";
        return [
            '<div class="metabolic-network-tooltip-title">' + escapeHtml(data.label || data.id) + roleBadge + '</div>',
            '<dl>',
            '<dt>EC</dt><dd>' + escapeHtml(data.ecNumbers && data.ecNumbers.length ? data.ecNumbers.join(", ") : "-") + '</dd>',
            '<dt>Genes</dt><dd>' + escapeHtml(genes.length ? genes.join(", ") : "-") + '</dd>',
            '</dl>'
        ].join("");
    }

    function tooltipForMetabolite(data) {
        return [
            '<div class="metabolic-network-tooltip-title">' + escapeHtml(data.label || data.id) + '</div>',
            '<dl>',
            '<dt>Compartment</dt><dd>' + escapeHtml(data.compartment || "model") + '</dd>',
            '<dt>Type</dt><dd>' + (data.isCurrency ? "Currency metabolite" : "Metabolite") + '</dd>',
            '</dl>'
        ].join("");
    }

    window.TPMetabolicReactionGraph = {
        FONT_STACK: FONT_STACK,
        buildElements: buildElements,
        styleRules: styleRules,
        tooltipForReaction: tooltipForReaction,
        tooltipForMetabolite: tooltipForMetabolite
    };
})();
