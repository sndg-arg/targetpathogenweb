---
name: tpw-metabolism-graphs
description: Cytoscape.js conventions for Target Pathogen Web's metabolic pathway/network diagrams — safe dynamic restyling vs. dangerous DOM/CSS resizing, dynamic (not fixed-guess) sizing philosophy, the standardized shape/color legend language, and label-legibility idioms. Load before editing static/js/pages/metabolic-*.js, the metabolism templates, or metabolism_network.py/protein_summary.py's graph-payload code.
---

# Target Pathogen Web — metabolic graph conventions (Cytoscape.js)

## The four files and how they relate

- `static/js/pages/metabolic-reaction-graph.js` — the shared bipartite (reaction + metabolite
  node) builder. Exposes a global `window.TPMetabolicReactionGraph` namespace (plain IIFE, no ES
  modules) with `buildElements`, `flowLayout` (dagre), `styleRules(palette, fontScale)`,
  `computeFontScale(zoom)`, `suggestRoots`, `tooltipForReaction`, `tooltipForMetabolite`. Consumed
  by **both** the pathway-detail page's own map and the genome-network drill-in — it is the single
  source of truth for bipartite-graph rendering, not something to fork.
- `static/js/pages/metabolic-pathway-graph.js` — pathway-detail page, calls into the shared
  namespace above.
- `static/js/pages/metabolic-network-genome.js` — genome-wide pathway overview, and (via the same
  shared namespace) the per-pathway drill-in.
- `static/js/pages/metabolic-network.js` — the per-protein ego network (its own, independent
  layout/style code — pathway-group compound boxes, the focal "this protein" node — does **not**
  go through the shared bipartite builder, since its node semantics are different).

**Each file defines its own local `FONT_STACK` constant separately** — there is no single shared
source for it. If you change one graph's font, grep for `FONT_STACK` across all four files and
decide deliberately whether the others should match, rather than assuming a shared constant exists.

## Two ways to make a graph responsive — one is safe, one is a trap

**Safe**: restyle through Cytoscape's own API — `cy.style(rules).update()`, or `node.style(prop,
value)` on individual nodes after `layoutstop`. This is pure JS state Cytoscape already owns; there
is no reflow-timing race because you're not fighting the browser's CSS layout pass. Use this for
anything that needs to react to actual rendered state (current zoom, a node's real post-layout
width).

**Dangerous**: resizing the *container* via CSS/DOM (e.g. toggling a `max-width` class on the
wrapping `<div>`) and expecting Cytoscape to notice. It won't, on its own — `cy.resize()` is
required, and even that races the browser's own reflow: if `cy.resize()` runs in the same tick as
the class toggle, Cytoscape may read the container's *old* dimensions. This was tried three times in
one session (add `cy.resize()`; add `void wrap.offsetWidth` forced-reflow before it; still broken
per live screenshot) before being abandoned entirely in favor of a structural fix (changing the
graph's own layout direction — see below) rather than continuing to patch the resize path blind.
**Default to avoiding post-hoc container resizing altogether** — size the container statically (CSS
`clamp()`/`min-height`) and let `cy.fit()` handle the content, rather than trying to shrink-wrap the
container to the content via JS.

## Layout direction should match the canvas's natural shape

All three dagre-based graphs (`metabolic-reaction-graph.js`'s shared `flowLayout`, and
`metabolic-network.js`'s own dagre config) run `rankDir: "LR"` (left-to-right), not `"TB"`. This was
a deliberate mid-session reversal: a top-to-bottom layout for long reaction chains produces a very
tall, narrow graph that doesn't fit a wide browser viewport, and no amount of container-resizing
patched that — switching the rank direction so the graph grows in the same direction as the
available canvas width fixed it structurally. This overrode an earlier biologist-validated
requirement for top-to-bottom layout, at the user's explicit request or delegated judgment call
("olvidate de lo que pidieron los biologos") — noted in `docs/TARGET_ROADMAP.md` as a decision not
yet re-validated with the biology side. If a future request pushes back on LR, that history is why
it's LR today, not an oversight.

## Dynamic sizing, not fixed-pixel guesses

Every fixed-pixel guess attempted this session for graph sizing turned out wrong for some real
piece of data (a `160px` static `text-max-width` for pathway-group labels still truncated "Vitamin
B6 metabolism"; earlier compaction math based on assumed content width didn't match actual rendered
width). The pattern that actually works: **measure Cytoscape's real, post-render state, then apply
it** — never guess a constant.

- **Font/node scale**: `computeFontScale(zoom)` in `metabolic-reaction-graph.js` —
  `clamp(REFERENCE_ZOOM / zoom, 0.7, 1.8)` with `REFERENCE_ZOOM = 1.3` — computed from the *actual*
  zoom level `cy.fit()` lands on (read `cy.zoom()` after fit, not before), then multiplied into
  every size-related style property (`width`, `height`, `font-size`, `text-margin-y`,
  `text-max-width`) via `styleRules(palette, fontScale)`.
- **Per-node label width**: for compound/group nodes whose box width varies with content (pathway-
  group boxes in `metabolic-network.js`), set `text-max-width` per node *after* `layoutstop`, from
  that node's own real `node.width()`:
  ```js
  cy.nodes(".pathway-group").forEach(function (node) {
      node.style("text-max-width", Math.max(80, node.width() * 0.82) + "px");
  });
  ```
- **Label truncation**: don't pre-truncate label text in JS with a fixed character count before
  Cytoscape ever sees it (a `compactLabel`/`compactReactionLabel`-style helper existed for this and
  was removed from all three graph files this session — it truncated labels that would have fit
  fine at the actual rendered size). Instead pass the **full** name as `displayLabel` and let
  Cytoscape's native `text-max-width` + `text-wrap: "ellipsis"` truncate dynamically based on real
  available space — this is strictly more accurate than any fixed-length JS truncation and needs no
  extra code once `text-max-width` is set per the point above.

## Label legibility over crossing edges

Use a solid label background chip — `text-background-color`, `text-background-opacity`,
`text-background-shape`, `text-background-padding` — not a thin `text-outline-color`/`-width`
halo. A halo doesn't fully occlude an edge crossing directly under the text; a solid background chip
does. This is the standard now for every label placed near potential edge crossings in these graphs.

## Standardized shape/color legend language — keep it consistent across all graphs

Established this session, applies to every Cytoscape instance in the app:
- **Circle (ellipse)** = a plain reaction node.
- **Diamond** = a chokepoint reaction (`.has-chokepoint`).
- **Rounded rectangle** = a container/focal-emphasis node — the per-protein ego network's "this
  protein" focal node (`.is-focal`), or a pathway-group compound box. Not used for a plain reaction.

Before changing the base `"node"` shape in any graph file, check whether a more specific class
(`.is-focal`, `.pathway-group`) is *relying on inheriting* that base shape — changing the base from
round-rectangle to ellipse this session would have silently also flattened `.is-focal` if an
explicit `"shape": "round-rectangle"` override hadn't been added to it at the same time.

**Whenever a node's shape or color changes, check the page's legend swatch for that node type and
update it to match in the same change.** A legend/node mismatch is a real, user-visible bug (caught
directly by the user asking "cual es la proteina? no se entiende" after the focal node's shape
changed but its legend dot in `protein-detail.css` — `.metabolic-legend-dot--focal` — was still a
plain solid circle from the old design). Legend copy matters too: don't call something "This
protein" in a legend when every node in the diagram, including that one, is actually a *reaction* —
say what it structurally is (e.g. "Reaction catalyzed by this protein").

## Currency metabolites are fully excluded, not just de-emphasized

`is_currency` metabolite nodes (ATP, NAD+, water, etc.) and their participant edges are skipped
entirely inside `buildElements()`'s forEach loops (an early `return`), not merely styled to look
faded. If you're looking for where currency metabolites went, they're filtered out at element-build
time, not hidden via CSS — there is no `.is-currency` style rule anymore, and adding one back
without also removing the `buildElements()` skip would do nothing.

## Verifying feasibility of an external-integration idea before proposing it

When a request suggests wiring in an external tool/reference (this session: BiGG IDs, Escher
diagrams, MetaCyc links), check what's actually true before promising anything:
- Grep the codebase/models for whether the data already exists (`MetabolicReaction.reaction_id` was
  confirmed, by reading `load_metabolism.py`, to already **be** the BioCyc/MetaCyc frame id — a
  MetaCyc link needed zero new data; a BiGG link would have needed a wholly new field plus an
  external ID-mapping step that doesn't exist).
- For a third-party library (Escher), use WebFetch to check what it actually does — Escher is real
  and embeddable, but its value comes from **manual curation** in its own builder UI, not automatic
  layout from arbitrary data, which doesn't fit an app that auto-generates a diagram per
  pathway per genome across many uploaded pathogen genomes. Decline explicitly with the reason, not
  silently.

## Reusing an existing service's computed data instead of building new computation

`tpweb/services/metabolism_network.py::build_genome_metabolism_network()` already computes every
pathway-pair edge (weighted by shared reaction-reaction adjacency) for a genome. When a new feature
needs "this one pathway's neighbors" (pathway-detail "Connected pathways" section, and the ranking
list's "Connects to N" note), **filter the existing computation's output** rather than writing new
graph-traversal logic — see `pathway_neighbors()` in the same file, which calls
`build_genome_metabolism_network()` and just filters `network["edges"]` for the one node id. Cheap,
low-risk, and automatically stays consistent with the full network view.

## Cache-busters

Every one of these JS/CSS files is loaded from templates with a `?v=N` query-string cache-buster.
Bump it in **every** template that loads the changed file whenever you edit
`metabolic-network.js`, `metabolic-network-genome.js`, `metabolic-pathway-graph.js`,
`metabolic-reaction-graph.js`, `metabolism-overview.css`, `metabolic-network-genome.css`, or
`protein-detail.css` — grep across `tpweb/templates/` for the file name to find every include site
(a file can be loaded from more than one template — `metabolic-reaction-graph.js` is loaded
wherever either `metabolic-pathway-graph.js` or the genome drill-in is used). Watch for
`replace_all` collisions when two different files happen to share the same old version-tag string;
re-grep with more specific surrounding context if an edit lands in the wrong place.
