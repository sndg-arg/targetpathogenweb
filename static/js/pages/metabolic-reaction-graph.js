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

    // Matches the app's own body font (masterpage.html) -- monospace read as a raw data
    // dump rather than a designed diagram.
    var FONT_STACK = '"Source Sans 3", "Segoe UI", sans-serif';

    function escapeHtml(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
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
        var reactionById = {};

        (payload.metabolites || []).forEach(function (m) { metaboliteById[m.id] = m; });
        (payload.reactions || []).forEach(function (r) { reactionById[r.id] = r; });

        (payload.reactions || []).forEach(function (reaction) {
            var hasChokepoint = (reaction.chokepoint_role || "none") !== "none";
            var data = {
                id: idPrefix + "rxn::" + reaction.id,
                label: reaction.name,
                // Full name, not pre-truncated -- Cytoscape's own text-wrap: "ellipsis" +
                // text-max-width already truncates dynamically based on actual rendered
                // width (which now also scales with fontScale), so a name only gets an
                // ellipsis when it genuinely doesn't fit, instead of always.
                displayLabel: reaction.name,
                ecNumbers: reaction.ec_numbers || [],
                chokepointRole: reaction.chokepoint_role || "none",
                isoenzymeCount: reaction.isoenzyme_count || 0,
                reversible: Boolean(reaction.reversible),
                genes: reaction.genes || [],
                isReaction: true
            };
            if (parentId) data.parent = parentId;
            elements.push({
                data: data,
                classes: ["reaction-node", hasChokepoint ? "has-chokepoint" : ""].join(" ").trim()
            });
        });

        // Currency metabolites (ATP, water, NAD+...) are ubiquitous and don't carry real
        // pathway-specific signal -- biologists asked for them left out of the diagram
        // entirely, not just de-emphasized.
        (payload.metabolites || []).forEach(function (metabolite) {
            if (metabolite.is_currency) return;
            var data = {
                id: idPrefix + "met::" + metabolite.id,
                label: metabolite.name,
                displayLabel: metabolite.name,
                compartment: metabolite.compartment,
                isCurrency: false,
                isReaction: false
            };
            if (parentId) data.parent = parentId;
            elements.push({
                data: data,
                classes: "metabolite-node"
            });
        });

        (payload.participants || []).forEach(function (p, i) {
            var metabolite = metaboliteById[p.species_id];
            if (metabolite && metabolite.is_currency) return;
            var reaction = reactionById[p.reaction_id];
            var reactionNodeId = idPrefix + "rxn::" + p.reaction_id;
            var metaboliteNodeId = idPrefix + "met::" + p.species_id;
            var isReactant = p.role === "reactant";
            var classes = [isReactant ? "flow-in" : "flow-out"];
            if (reaction && reaction.reversible) classes.push("flow-reversible");
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
                // edge crossings within each layer -- much closer to curated pathway
                // diagrams than a generic force-directed layout. Left-to-right (not
                // top-to-bottom): a linear chain renders wide-and-short this way, matching
                // this app's canvas (always wide), instead of tall-and-narrow with dead
                // space either side -- top-to-bottom kept breaking for small/linear
                // pathways across several rounds of canvas-sizing fixes.
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

    function styleRules(palette, fontScale) {
        fontScale = fontScale || 1;
        return [
            {
                // A small labeled junction, not a text box -- metabolites are the diagram's
                // main characters; the reaction is what happens on the arrow between them.
                selector: ".reaction-node",
                style: {
                    "shape": "ellipse",
                    "width": 7 * fontScale,
                    "height": 7 * fontScale,
                    "background-fill": "radial-gradient",
                    "background-gradient-stop-colors": palette.surfaceSoft + " " + palette.ring,
                    "background-gradient-stop-positions": "0 100",
                    "border-width": 1.2,
                    "border-color": palette.plain,
                    "label": "data(displayLabel)",
                    "font-family": FONT_STACK,
                    "font-size": 7 * fontScale,
                    "font-weight": 600,
                    "color": palette.textFaint,
                    "text-valign": "top",
                    "text-halign": "center",
                    "text-margin-y": -4 * fontScale,
                    "text-max-width": (110 * fontScale) + "px",
                    "text-wrap": "ellipsis",
                    "text-background-color": palette.ring,
                    "text-background-opacity": 1,
                    "text-background-shape": "roundrectangle",
                    "text-background-padding": "2px"
                }
            },
            {
                selector: ".reaction-node.has-chokepoint",
                style: {
                    // Solid fill (not the gradient above) plus a diamond shape -- two
                    // non-color-dependent cues that this node is a chokepoint, since a
                    // pathway can have many of these and amber text on every other label
                    // would just read as noise rather than a signal.
                    "shape": "diamond",
                    "width": 10 * fontScale,
                    "height": 10 * fontScale,
                    "background-fill": "solid",
                    "background-color": palette.chokepointSoft,
                    "border-color": palette.chokepoint,
                    "border-width": 2,
                    "color": palette.text,
                    "font-size": 7.5 * fontScale,
                    "font-weight": 800
                }
            },
            {
                selector: ".metabolite-node",
                style: {
                    // A richer gradient (plain -> ring) than the reaction junctions'
                    // lighter one (surfaceSoft -> ring), preserving the size+color
                    // hierarchy: metabolites read as the diagram's main characters.
                    "shape": "ellipse",
                    "width": 17 * fontScale,
                    "height": 17 * fontScale,
                    "background-fill": "radial-gradient",
                    "background-gradient-stop-colors": palette.plain + " " + palette.ring,
                    "background-gradient-stop-positions": "0 100",
                    "border-width": 1,
                    "border-color": palette.ring,
                    "label": "data(displayLabel)",
                    "font-family": FONT_STACK,
                    "font-size": 8.5 * fontScale,
                    "font-weight": 700,
                    "color": palette.text,
                    "text-valign": "bottom",
                    "text-margin-y": 4 * fontScale,
                    "text-max-width": (80 * fontScale) + "px",
                    "text-wrap": "ellipsis",
                    "text-background-color": palette.ring,
                    "text-background-opacity": 1,
                    "text-background-shape": "roundrectangle",
                    "text-background-padding": "2px"
                }
            },
            {
                selector: ".flow-in, .flow-out",
                style: {
                    "curve-style": "bezier",
                    "width": 2,
                    "line-color": palette.edge,
                    "opacity": 0.92,
                    "target-arrow-shape": "triangle",
                    "target-arrow-color": palette.edge,
                    "arrow-scale": 1.15
                }
            },
            {
                // Reversible reactions get an arrowhead on both ends -- same MetaCyc-style
                // "double arrow" convention already used for the per-protein ego network.
                selector: ".flow-reversible",
                style: { "source-arrow-shape": "triangle", "source-arrow-color": palette.edge }
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
            '<dt>Reversible</dt><dd>' + (data.reversible ? "Yes" : "No") + '</dd>',
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

    // Base node/label sizes in styleRules() were tuned by eye at a "typical" fit zoom for a
    // medium-sized pathway. A tiny pathway fits at a much higher zoom (labels would look
    // small relative to all the empty room) and a sprawling one at a much lower zoom
    // (labels could shrink past legible) -- rescale from the zoom the fit actually landed
    // on so text reads at roughly the same size regardless of pathway size. REFERENCE_ZOOM
    // is a judgment call, not measured against real data; may need retuning once seen live.
    var REFERENCE_ZOOM = 1.3;
    function computeFontScale(zoom) {
        return Math.max(0.7, Math.min(1.8, REFERENCE_ZOOM / (zoom || 1)));
    }

    window.TPMetabolicReactionGraph = {
        FONT_STACK: FONT_STACK,
        buildElements: buildElements,
        suggestRoots: suggestRoots,
        flowLayout: flowLayout,
        styleRules: styleRules,
        computeFontScale: computeFontScale,
        tooltipForReaction: tooltipForReaction,
        tooltipForMetabolite: tooltipForMetabolite
    };
})();
