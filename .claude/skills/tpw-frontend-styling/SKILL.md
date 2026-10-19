---
name: tpw-frontend-styling
description: Design-token, CSS, and Django-template conventions for Target Pathogen Web. Load before editing any file under static/css/pages/, static/css/components/, or tpweb/templates/ — covers the hex-color rule, the token inventory, reusable component idioms (stat cards, panels, chips), dark mode, motion, cache-busters, and how to verify a template/CSS change without a local execution environment. For Cytoscape.js graph rendering specifically (static/js/pages/metabolic-*.js), load tpw-metabolism-graphs instead/in addition.
---

# Target Pathogen Web — frontend styling conventions

## The hard rule (non-negotiable, from CLAUDE.md)

Hex colors are allowed **only** inside `tpweb/templates/base/masterpage.html`'s `:root` block
(light-mode values, then a dark-mode override block further down in the same file). Every other
CSS file — everything under `static/css/` — must reference a `var(--tp-*)` token. Before writing
`background: #...` or `color: #...` anywhere else, stop and find (or add, in masterpage.html only)
the token instead. After editing any CSS file, `grep` the diff for `#[0-9a-fA-F]{3,8}` to confirm
none slipped through.

## Token inventory (defined in masterpage.html, light values + parallel dark overrides)

This is the whole system (standardized 2026-10-17). Nothing outside it: no literal px radii,
no raw rem font sizes, no raw shadows, no page-local color aliases (`--blast-ink` style).
- **Colors**: brand `--tp-color-brand-{900..050}`; neutrals `--tp-color-text-{primary,secondary,muted,soft}`,
  `--tp-color-surface{,-soft,-muted}`, `--tp-color-border{-soft,,-strong}`; links
  `--tp-color-link{,-hover}` (= brand-700/900); `--tp-color-primary{,-hover}`, `--tp-color-accent-line`;
  five tones `--tp-color-{success,info,warning,danger,idle}-{ink,bg,border}` + `--tp-color-danger-fill`;
  `--tp-color-nav-900` (top bar), `--tp-color-on-accent`, `--tp-color-scrim`, `--tp-tooltip-*`;
  viewer-only `--tp-color-structure-*`, `-sstruc-*`, `-plddt-*`. The old rose/sage/amber scales,
  surface-panel/alt, border-accent, page-start/end and `--tp-ink`-style aliases are gone — use tones.
  Data-viz palettes in JS read tones too (`success-ink`, `danger-ink`, `warning-ink`, `info-ink`).
- **Spacing**: `--tp-space-1..8` = 4/8/12/16/20/24/32/40px for every padding/margin/gap (literal px only
  for <=3px nudges and rare >44px layout). The page inset is `--tp-space-5` (20px).
- **Type**: families `--tp-font-{head,body,mono}`; sizes `--tp-font-size-{2xs .7, xs .78, sm .88,
  md .98, lg 1.12, xl 1.28}rem` + `--tp-heading-{md,lg,xl}`; tracking `--tp-tracking-label` (uppercase
  labels) / `--tp-tracking-tight` (display headings); weights only 400/500/600 (no 700, not loaded).
- **Shadows**: `--tp-shadow-sm` (menus, tooltips, popovers) and `--tp-shadow-lg` (modals, drawers,
  FAB). In-flow content is flat. Focus = `--tp-focus-outline` (or `outline: 2px solid var(--tp-focus-color)`).
- **Radius**: `--tp-radius-{xs:4, sm:8, md:12, pill:999}`. Circles may use `50%`.
- **Controls**: `--tp-ui-control-height` 38px / `-compact` 32px (fields = buttons).
- **Page header**: `<section class="tp-page-hero …">` + `tp-view-eyebrow/title/lead`; spacing comes
  from ui-system, pages never restyle them.

## Palette: deep petrol, one accent (since 2026-10-16)

**`/design`** (`tpweb/templates/about/design_system.html`, `static/css/pages/design-system.css`) is a
public showcase (anyone with the link; menu entry for Gates collaborators/superusers) shared at stands.
English, plain titles, **no code, class names, token names or explanatory prose**. Each component is a
title + a variant matrix (`.ds-matrix`: columns = states such as Default/Hover/Selected/Disabled, rows
= types or sizes), built from the real classes. Never show keyboard focus. When you add or change a
component, add/update its matrix there. design-system.css may only place samples (e.g. `.ds-fab`
un-fixes the assistant button), never restyle them. This skill is the developer reference.
- The brand scale is low-chroma petrol (brand-800 `#1d4b5a` = primary). Never reintroduce bright
  cyan (`#39a6be`-style) values or `rgba(57,166,190,...)` glows.
- **One-accent rule**: brand color only for (1) the one primary action per view, (2) links,
  (3) the active tab/section line (`--tp-color-accent-line`). Hover states are neutral grays;
  selected = brand-800 fill; pending = dashed brand-700 border (no double rings); focus = a thin
  petrol line, not a glowing halo.

## File layout

One CSS file per page or page family under `static/css/pages/` (genome-overview.css = genome pages,
protein-detail.css = protein pages incl. human, metabolism-overview.css = metabolism views, auth.css = account). Shared, cross-page
component classes live in `static/css/components/ui-system.css` — e.g. `.tp-view-head`,
`.tp-view-head-copy`, `.tp-view-head-actions`, generic `.tp-btn*`. **Check `ui-system.css` before
assuming a class is undefined** — a `grep` across `static/css/` for the class name will tell you
whether it's page-local or shared; don't duplicate a shared class's styling into a page file.

## Reusable component idioms — extend these, don't invent parallel ones

Components (all on /design). There is no `.tp-ui-panel`/`.tp-ui-panel-head` any more.
- `.target-evidence-card` (protein-detail.css): stat card — uppercase label, value, optional
  key/value meta rows; `--secondary` = muted fill. Reuse it for any new evidence card.
- Filters: `.filter-chip` (available) + `--active` or `[aria-pressed="true"]` (applied, filled
  primary) + `--pending` (dashed); tone variants for risk/favorable.
- Select: `.tp-select` (custom dropdown, `.tp-select-option.is-selected`). Fields: `.form-control`.
- Messages: `.tp-message--{success,info,warning,error}` (dismissible flash). Notes are `tp-state-note`.
- Navigation: `.tp-pagination` (quiet: plain numbers, current = brand-100), `.tp-breadcrumb`, `.quick-nav`.
- Tooltips: `.tp-global-tooltip` (`--tp-tooltip-*`, `.is-below`), one for the whole site.
- Assistant button: `.tp-agent-fab` + `.tp-agent-fab-ring` (agent-drawer.css) — a circle (pill
  radius) that grows into a labelled pill on hover; the ring's comet uses `--tp-color-accent-line`.
- Export CSV (table-utilities.js) is a standard `tp-btn--secondary tp-btn--sm` with icon.
- Page loader: `.tp-page-loader` (surface veil + blur, the one blurred overlay) > `.tp-page-loader-card`.
- Chip `.tp-chip` (neutral by default, one size) + only: `--code` (mono ids: EC/GO/scores),
  `--link`, `--success`, `--warning`, `--danger`, `--muted`, `--filter` (removable applied
  filter), `--state` + `idle|running|finished|failed`.
- Buttons: **four types, two sizes, nothing else** — `btn tp-btn` + `--primary` (the one main action),
  `--secondary` (everything else), `--danger` (destructive; fills `--tp-color-danger-fill` on
  hover), `--ghost` (icon-only, close, in-row). Size: default 38px or `tp-btn--sm` 32px. All aliases
  (neutral/outline/clear/success/info/md, Bootstrap btn-*) were removed from CSS and markup — they no
  longer render. A page class may set size/layout only, never colors. Hover everywhere is neutral
  (surface-soft fill, text-muted/border-strong border, text-primary ink) — never a brand tint.
  Selected = filled `--tp-color-primary`. Toggle groups use `.tp-segmented` (ui-system.css).
- Frozen states for /design: `.is-hover` / `.is-focus` are matched by the real rules — add them to
  any new hover/focus rule you want shown there.
- `.tp-state-note--{empty,loading,success,warning,error}` for every inline status message (left
  bar, left-aligned, never centered or boxed).
- `.tp-code-block` for a formula, command, log or long identifier (SMILES, InChI). Lists are
  hairline rows (`border-bottom`), never one box per row. Counts and scores are plain text, not tinted.
- Weights: 400 text, 500 labels, 600 emphasis/headings (no 700; fonts load only these).
  Overlays/backdrops: `--tp-color-scrim`, no blur. Transitions: 140ms state changes, 180ms movement.
  No ad-hoc `color-mix()` tints: use the token it approximates.
- `.tp-card` only for repeated grid items (border, no shadow). Sections are never boxed.
- `.tp-metrics` > `.metric-pill` (+ `--success|--warning|--danger|--link`) for every "number in a pill".
- `.tp-tabs` > `.tp-tab` (+ `.tp-count`) for every tab set inside a section; `.tp-count` for any number next to a label.
- Tables: `table tp-table` (+ `tp-table--compact` for big data tables) inside `.tp-table-shell`. No zebra, no
  Bootstrap `table-striped/-hover/-sm`; page table classes set column widths/alignment only.
- Paragraph width: `max-width: var(--tp-measure)` (72ch), never a px value.
- Missing data (no structure, no score, not computed) is neutral gray, never a warning tone. Warning is
  for something that needs a second look; statuses use `tp-chip--state idle|running|finished|failed`.
- `.tp-view-eyebrow` is the one uppercase rótulo above any title (page or section).
- Section header: `.section-head` > title `h2` + optional `.section-subtitle`, tools in `.section-tools`.
  A section title outside a `.section-head` uses `.tp-section-title`. No page-specific title classes.
- Dialogs: `.tp-modal` (backdrop, `.is-open` shows it) > `.tp-modal-panel[--sm|--lg]` >
  `.tp-modal-head` (`.tp-modal-title`, optional `.tp-modal-meta`, close =
  `btn tp-btn tp-btn--ghost tp-btn--sm tp-modal-close` with `icons/x.html`) + `.tp-modal-body` +
  `.tp-modal-actions` (Cancel = secondary, then the main action). Keep the page's own id/class
  next to these for its JS; page CSS only styles what's inside the body.

## Cache-busters

Static files are loaded from templates with a `?v=N` query-string cache-buster. Bump it in
**every** template that loads a static file you changed — grep across `tpweb/templates/` for the
file's name to find every include site, since the same JS/CSS file is often loaded from more than
one template. Watch for `replace_all` hitting the wrong spot when two different files happen to
share the same old version-number string; if that happens, re-grep with more specific surrounding
context rather than trusting a blind global replace.

## Modifier classes for content that varies by context, not a shared default on the base class

If a shared base class currently hardcodes context-specific content (e.g. a `::after { content:
"KEGG" }` badge on a class that's reused for multiple different external-link types), don't leave
the hardcoded value in place once a second variant is needed — split it into modifier classes
(`--kegg`, `--metacyc`, etc.), each with its own `::after` content, and update every existing call
site to add the right modifier. Leaving the base class's default in place "for the common case" is
how a second call site silently inherits the wrong label.

## Django `{% trans %}` string safety

When a translated string needs to contain a literal apostrophe, wrap the whole `{% trans %}` value
in single quotes rather than escaping a double quote inside it — Django's template tag parser is
strict about quoting, and an escaped `\"` inside a `{% trans "..." %}` is a real parse risk, not
just a style preference.

## Dark mode

`masterpage.html` defines a complete parallel dark token set (light block first, dark overrides
further down, activated via `.tp-dark` on a root ancestor and/or `prefers-color-scheme`). If a
component only ever references `var(--tp-color-*)` tokens, dark mode is automatic — do not add a
`.tp-dark .my-class {}` override unless there's a genuine asymmetry the token swap doesn't cover
(rare — e.g. quick-nav's active state needed a stronger token specifically in dark mode).

## Motion

Always respect `prefers-reduced-motion: reduce` — kill **both** `animation` and `transition` in
that media query, not just one (a common half-fix that leaves a static ghost element behind).

When staggering an entrance animation across a set of sibling cards with `:nth-child`/`:nth-of-type`,
prefer **`:nth-of-type`** if any non-animated structural element (e.g. a section-divider `<div>`)
might be interspersed among the animated cards. `:nth-child` counts position among *all* siblings
regardless of tag; `:nth-of-type` counts position only among same-tag siblings. If the cards are all
`<section class="protein-card">` and dividers are `<div>`, `:nth-of-type` keeps the stagger's
per-card delay stable no matter how many dividers get inserted between them — `:nth-child` would
silently reassign delays to the wrong cards.

## Icons

Reuse `tpweb/templates/components/icons/*.html` (e.g. `check.html`, `download.html`) via
`{% include %}` instead of inlining a duplicate SVG — check that directory before hand-writing an
SVG that might already exist there.

## Verifying a change with no local execution environment

This working setup typically has no local Docker/Python/browser — a rendering check isn't
available. After any template edit:
- Grep-count matching Django tag pairs to confirm balance: `{% if %}`/`{% endif %}`,
  `{% for %}`/`{% endfor %}`, `{% with %}`/`{% endwith %}`, `{% regroup %}` (no closing tag of its
  own — it lives inside a surrounding `{% for %}`).
- Grep-count matching HTML tag pairs for any structure you touched (`<div>`/`</div>`,
  `<section>`/`</section>`, `<dl>`/`</dl>`, etc.).

After any CSS edit, grep the diff for stray hex codes (see the hard rule above) and confirm brace
balance (`{` vs `}` counts should match).

Flag explicitly to the user that visual changes need a live check in their actual environment —
tag/brace balance proves the syntax didn't break, not that it looks right.
