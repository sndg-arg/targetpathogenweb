/* Shared reaction+metabolite Cytoscape graph builder -- a real bipartite graph (reactions
 * and metabolites as separate nodes, directed substrate/product edges between them), not
 * a per-reaction row diagram. A metabolite produced by one reaction and consumed by
 * another renders as a single connecting node, so the flow through a pathway is actually
 * visible as a graph.
 *
 * Reaction nodes are deliberately tiny (a labeled junction point, not a text box) so
 * metabolites -- the thing biologists actually scan for -- read as the main characters and
 * the diagram approximates a MetaCyc-style pathway chart (compound-to-compound flow, the
 * enzyme/reaction name as a light label on the step). A literal edge-per-reaction-name
 * model was considered and rejected: a reaction with 2 reactants and 2 products would need
 * 4 direct compound-to-compound edges, two of which (e.g. substrate-to-byproduct) don't
 * represent a real transformation -- keeping a (visually minimal) junction node is the only
 * way to keep N:M reactions topologically correct.
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

    // Metabolite nodes with in-degree 0 within this subgraph (never the target of a
    // flow-out edge, i.e. never produced by any reaction shown) -- the natural "start"
    // points for a directed/layered layout. A fully cyclic pathway (e.g. TCA cycle) may
    // have none, in which case the caller's layout falls back to its own root choice.
    function suggestRoots(elements) {
        var producedIds = {};
        elements.forEach(function (el) {
            if (el.classes && el.classes.indexOf("flow-out") !== -1) {
                producedIds[el.data.target] = true;
            }
        });
        var roots = [];
        elements.forEach(function (el) {
            if (el.classes && el.classes.indexOf("metabolite-node") !== -1 && !producedIds[el.data.id]) {
                roots.push(el.data.id);
            }
        });
        return roots;
    }

    function supportsDagre() {
        return Boolean(window.TP_CYTOSCAPE_DAGRE_AVAILABLE);
    }

    function flowLayout(roots, options) {
        options = options || {};
        if (supportsDagre()) {
            return {
                // Dagre/Sugiyama puts the pathway into ordered layers and minimizes
                // edge crossings within each layer. That is much closer to curated
                // pathway diagrams than a generic force-directed layout.
                name: "dagre",
                rankDir: "LR",
                ranker: "network-simplex",
                acyclicer: "greedy",
                nodeSep: options.nodeSep || 46,
                rankSep: options.rankSep || 92,
                edgeSep: options.edgeSep || 18,
                padding: options.padding || 30,
                animate: options.animate !== false,
                animationDuration: options.animationDuration || 700,
                animationEasing: "ease-out-cubic",
                nodeDimensionsIncludeLabels: true
            };
        }
        return {
            name: "breadthfirst",
            directed: true,
            roots: roots && roots.length ? roots : undefined,
            spacingFactor: options.spacingFactor || 1.35,
            avoidOverlap: true,
            animate: options.animate !== false,
            animationDuration: options.animationDuration || 700,
            animationEasing: "ease-out-cubic",
            padding: options.padding || 30,
            nodeDimensionsIncludeLabels: true
        };
    }

    function styleRules(palette) {
        return [
            {
                // A small labeled junction, not a text box -- metabolites are the diagram's
                // main characters; the reaction is what happens on the arrow between them.
                selector: ".reaction-node",
                style: {
                    "shape": "ellipse",
                    "width": 7,
                    "height": 7,
                    "background-color": palette.surfaceSoft,
                    "border-width": 1.2,
                    "border-color": palette.plain,
                    "label": "data(displayLabel)",
                    "font-family": FONT_STACK,
                    "font-size": 7,
                    "font-weight": 600,
                    "color": palette.textFaint,
                    "text-valign": "top",
                    "text-halign": "center",
                    "text-margin-y": -4,
                    "text-max-width": "110px",
                    "text-wrap": "ellipsis",
                    "text-outline-color": palette.ring,
                    "text-outline-width": 2
                }
            },
            {
                selector: ".reaction-node.has-chokepoint",
                style: {
                    "width": 10,
                    "height": 10,
                    "background-color": palette.chokepointSoft,
                    "border-color": palette.chokepoint,
                    "border-width": 2,
                    "color": palette.chokepoint,
                    "font-size": 7.5,
                    "font-weight": 800
                }
            },
            {
                selector: ".metabolite-node",
                style: {
                    "shape": "ellipse",
                    "width": 17,
                    "height": 17,
                    "background-color": palette.plain,
                    "border-width": 1,
                    "border-color": palette.ring,
                    "label": "data(displayLabel)",
                    "font-family": FONT_STACK,
                    "font-size": 8.5,
                    "font-weight": 700,
                    "color": palette.text,
                    "text-valign": "bottom",
                    "text-margin-y": 4,
                    "text-max-width": "80px",
                    "text-wrap": "ellipsis",
                    "text-outline-color": palette.ring,
                    "text-outline-width": 2
                }
            },
            {
                // Currency metabolites (ATP, water, NAD+...) are ubiquitous and would
                // clutter every step if labeled by default -- kept small and unlabeled,
                // name still one hover away, matching how MetaCyc de-emphasizes them.
                selector: ".metabolite-node.is-currency",
                style: { "width": 8, "height": 8, "opacity": 0.55, "label": "" }
            },
            {
                selector: ".metabolite-node.is-currency.is-hovered",
                style: { "label": "data(displayLabel)", "font-size": 7 }
            },
            {
                selector: ".flow-in, .flow-out",
                style: {
                    "curve-style": "bezier",
                    "width": 1.5,
                    "line-color": palette.edge,
                    "opacity": 0.75,
                    "target-arrow-shape": "triangle",
                    "target-arrow-color": palette.edge,
                    "arrow-scale": 0.75
                }
            },
            {
                selector: ".flow-currency",
                style: { "opacity": 0.2, "width": 1 }
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
        suggestRoots: suggestRoots,
        flowLayout: flowLayout,
        styleRules: styleRules,
        tooltipForReaction: tooltipForReaction,
        tooltipForMetabolite: tooltipForMetabolite
    };
})();
