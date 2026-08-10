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

- **Colors**: `--tp-color-text-{primary,secondary,muted,soft}`, `--tp-color-link{,-hover}`,
  `--tp-color-brand-{900,800,700,600,500,300,200,100,050}`, `--tp-color-rose-{900,700,500,300,100,050}`,
  `--tp-color-sage-{900,700,500,200,100,050}`, `--tp-color-amber-{900,700,500,200,100,050}`,
  `--tp-color-nav-{900,800,700,600}`, `--tp-color-surface{,-soft,-muted,-panel,-alt}`,
  `--tp-color-border{,-soft,-strong,-accent}`, `--tp-color-{success,info,idle,warning,danger}-{ink,bg,border}`
  (this is the semantic set to use for "good/present" vs "warning" vs "error" states — reach for
  these before raw brand/rose/sage/amber), `--tp-color-structure-*` (3D-viewer-specific),
  `--tp-color-on-accent`, `--tp-color-highlight`, `--tp-color-selection`.
- **Spacing**: `--tp-space-1..8` = 4/8/12/16/20/24/32/40px.
- **Type**: `--tp-font-size-{xs:0.78rem, sm:0.88rem, md:0.98rem, lg:1.12rem, xl:1.28rem, 2xl:clamp(...)}`,
  `--tp-font-label: 0.75rem` (the uppercase-micro-label size used everywhere), `--tp-font-weight-{normal,medium,semibold,bold}`.
- **Shadows**: `--tp-shadow-{xs,sm,md,lg}`.
- **Radius**: `--tp-radius-{lg:26px, md:20px}` only. There is no small-radius token — `12px` is the
  established de-facto small-card radius used throughout `protein-detail.css` and friends; reuse
  that literal value for small cards rather than inventing a new token or picking an arbitrary number.

## File layout

One CSS file per page under `static/css/pages/<page>.css` (CLAUDE.md rule). Shared, cross-page
component classes live in `static/css/components/ui-system.css` — e.g. `.tp-view-head`,
`.tp-view-head-copy`, `.tp-view-head-actions`, generic `.tp-btn*`. **Check `ui-system.css` before
assuming a class is undefined** — a `grep` across `static/css/` for the class name will tell you
whether it's page-local or shared; don't duplicate a shared class's styling into a page file.

## Reusable component idioms — extend these, don't invent parallel ones

- `.tp-ui-panel` / `.protein-card`-style panel shell: bordered card, `tp-shadow-xs`, hover raises to
  `tp-shadow-sm` and darkens the border.
- `.section-head.tp-ui-panel-head`: the h2 + subtitle + optional right-aligned tools/button row that
  opens every content card.
- `.target-evidence-card` (in `protein-detail.css`): the "stat card" idiom — small uppercase
  `.target-evidence-label` + a bold `.target-evidence-value` + optional `.target-evidence-meta`
  key/value rows below a hairline divider. Modifiers: `--compact` (small text value instead of the
  large display-font number, for short strings), `--warning` (amber/warning tint), `--secondary`
  (muted background variant), `--fpocket`/`--p2rank` (colored left accent bar). Reach for this
  before building a new stat-card pattern from scratch.
- The "seamless mosaic" grid trick for a hairline-divided card grid with no per-item borders:
  container gets `gap: 1px` + `background: var(--tp-color-border-soft)`, each grid item gets
  `background: var(--tp-color-surface)` — the 1px gaps read as thin dividers. See
  `.target-profile-grid` in `protein-detail.css`.
- `.tp-chip` / `.tp-chip--{sm,meta,link,count,ec,go,...}` for small pill labels/links.
- `.tp-btn` / `.tp-btn--{primary,neutral,outline}` + `.tp-btn--sm/md`, always paired with
  `.btn` for base sizing.
- `.tp-state-note--{empty,error}` for "nothing here yet" / error inline messages.

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
