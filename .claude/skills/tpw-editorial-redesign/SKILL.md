---
name: tpw-editorial-redesign
description: Art-direction standard for de-genericizing Target Pathogen Web's UI — replaces the rounded "AI SaaS template" look (999px pill chips/buttons, 50% icon circles, Space Grotesk headings, shadow-heavy floating cards) with a sober academic-editorial aesthetic (Nature/Science-journal register, UBA institutional DNA) that still reads as an active tool, not a passive article — built on square/hairline geometry, classic serif display type, the existing color palette, and confident hover/motion affordance. Includes a page-by-page rollout checklist. Load before any hero/layout redesign, button/chip/badge rework, card-panel restructuring, or typography pass. Composes with tpw-frontend-styling (token/hex/verification rules) — load both for CSS work.
---

# Target Pathogen Web — editorial/anti-AI redesign standard

## Mission

This is a doctoral-level bioinformatics platform (FCEN UBA), not a consumer SaaS product. The
target register is a top-tier scientific journal (Nature/Science editorial pages) crossed with
UBA's institutional identity: sobriety, precision, prestige, generous negative space, drastic
type contrast. Dense scientific data (sequences, scores, structures) should breathe inside a
clinical, minimal layout instead of being boxed into bubbly cards.

**Critical distinction from a literal journal site**: this is a *tool* people act in — upload
genomes, run BLAST, filter proteins, launch pipelines — not an article people passively read.
Every flattening move below must be paired with a deliberate affordance move (hover states,
underline reveals, subtle lift/motion, cursor feedback) so buttons and interactive rows still
read as unmistakably clickable even without a pill shape or a drop shadow to lean on. Flat does
not mean flat *feeling* — see "Interaction & motion" below.

**Non-negotiable geometry rule**: no pill-shaped buttons/badges, no circular icon frames, no
shadow-heavy floating cards for static content. Primary blocks (heroes, panels, buttons, chips)
go fully flat (0px). Small interactive controls (text inputs, checkboxes, filter tags) get a
2-4px hairline radius only, because a dead-square corner on those specific controls reads as a
rendering bug rather than a design choice.

**No hardcoded values — defer to `tpw-frontend-styling` for how, this skill only adds what's new.**
`tpw-frontend-styling` is the source of truth for the token inventory (colors, spacing, type,
shadow, radius), the hex-only-in-masterpage rule, and the reusable component idioms (`.tp-chip`,
`.tp-btn`, `.tp-ui-panel`, stat cards, etc.) — **load it alongside this skill for every CSS
change**, don't re-derive those conventions from scratch here. This skill's job is narrower: it
only introduces two new radius tokens (below) and a handful of new modifier variants for the
flattened look; every one of those new tokens/variants gets added to `masterpage.html` /
`ui-system.css` following that skill's existing patterns, not as one-off literals in page files.
Existing color tokens are the base palette and stay as-is — flattening a component should change
its shape, not send you hunting for a new hex.

## What's producing the generic-AI look today (audited against this repo)

- **Pill everything**: `border-radius: 999px` appears **105 times** across `static/css/`. Core
  offenders in the shared component sheet: `.tp-chip` and all its modifiers
  ([ui-system.css:631](static/css/components/ui-system.css#L631)), plus buttons/badges at
  [ui-system.css:183](static/css/components/ui-system.css#L183),
  [259](static/css/components/ui-system.css#L259),
  [1002](static/css/components/ui-system.css#L1002),
  [1007](static/css/components/ui-system.css#L1007),
  [1091](static/css/components/ui-system.css#L1091),
  [1173](static/css/components/ui-system.css#L1173),
  [1557](static/css/components/ui-system.css#L1557). The remainder are page-local repeats in
  `static/css/pages/*.css` (genome-overview, genome-upload, genomes-list, home,
  human-protein-detail, metabolic-network-genome, metabolism-overview, protein-detail,
  proteins-list, structure-fullscreen, annotation-explorer, formula-form, customparam,
  agent-drawer, binder-detail, data-sources).
- **Circular icon wrappers**: `border-radius: 50%` icon frames in `data-sources.css`,
  `protein-detail.css`, `proteins-list.css`, `structure-fullscreen.css`. (Not in scope: the
  `border-radius: 50%` uses inside `masterpage.html`'s `.tp-page-loader-*`/`.tp-page-action-loading`
  rules are the spinning-ring/pulsing-dot loading animation — functionally circular, not a
  decorative icon bubble, and exempt from this rule.)
- **Rounded geometric heading font**: "Space Grotesk" — the same typeface family that shows up in
  countless AI-generated template sites — is the only display font, loaded at
  [masterpage.html:25](tpweb/templates/base/masterpage.html#L25) and applied at
  [masterpage.html:371,1279,2030](tpweb/templates/base/masterpage.html#L371). There is currently
  no serif anywhere in the type system.
- **Soft-radius panels**: `--tp-radius-lg: 26px` / `--tp-radius-md: 20px`
  ([masterpage.html:162-163](tpweb/templates/base/masterpage.html#L162)) feed
  `--tp-ui-radius-panel` / `--tp-ui-radius-hero`
  ([ui-system.css:21-23](static/css/components/ui-system.css#L21)), so every `.tp-ui-panel` and
  hero block currently rounds at 20-26px — the "floating bubble card" look.
- **Elevation instead of division**: `--tp-shadow-lg: 0 8px 32px rgba(0,0,0,0.10)`
  ([masterpage.html:157](tpweb/templates/base/masterpage.html#L157)) is used on static hero/panel
  content ([ui-system.css:108](static/css/components/ui-system.css#L108),
  [masterpage.html:1885,1945](tpweb/templates/base/masterpage.html#L1885)) rather than being
  reserved for genuinely floating overlays.
- **What's already correct, don't rebuild it**: "JetBrains Mono" is already the monospace/data
  font, used consistently for sequences, accessions, and codes
  ([ui-system.css:653,692,756](static/css/components/ui-system.css#L653),
  `binder-detail.css`, `customparam.css`, `data-sources.css`, `blast.css`). The color token system
  is comprehensive and stays as the base palette (see above).

## Target tokens — add, don't repurpose in place

Add new tokens to `masterpage.html`'s `:root` block (light values near line 154-163, plus the
parallel dark-mode override block further down) rather than redefining `--tp-radius-lg`/`-md` in
place — a global redefinition silently reshapes every existing consumer at once, including ones
this pass hasn't reviewed yet. New tokens let components opt in deliberately, page by page:

- `--tp-radius-flat: 0px` — hero sections, primary content panels, buttons, chips.
- `--tp-radius-hairline: 3px` — reserved *only* for text inputs, checkboxes/radios, and small
  interactive filter tags. Not for decorative use anywhere else.
- `--tp-font-heading: "Source Serif 4", Georgia, "Times New Roman", serif` — display serif.
- `--tp-font-body: "Source Sans 3", "Segoe UI", sans-serif` — body copy + dense subheads.
- `--tp-font-mono: "JetBrains Mono", "SFMono-Regular", Menlo, Consolas, monospace` — technical/data
  strings.

All three font-family tokens (and the two radius tokens above) already exist in `masterpage.html`
— reference `var(--tp-font-heading|body|mono)` in every subsequent step rather than retyping the
literal stacks, per the no-hardcoded-values rule above.

## Typography

- **`h1`/`h2`** (hero titles/section titles) → `var(--tp-font-heading)` — classic editorial serif,
  already wired into `masterpage.html`'s base `h1, h2 {}` rule. Sober, high legibility, reads as
  "paper" academic tradition rather than "fashion editorial".
- **`h3`/`h4`/`h5`** (dense in-card subheads) → `var(--tp-font-body)`, *not* the serif — a serif at
  small sizes inside dense data tables hurts legibility, and this is also where the "drastic
  type-contrast" the brief asks for actually comes from: a large serif headline sitting directly
  above small sans subheads/labels, not a third typeface competing with both.
- **Body copy**: `var(--tp-font-body)` — no visual change from before, now tokenized.
- **Technical/data strings** (sequences, accessions, scores, codes): `var(--tp-font-mono)` — no
  visual change from before, now tokenized; already correct site-wide, just not yet routed through
  the token in every page file (see rollout).
- Pair the serif with **wide letter-spacing on labels/eyebrows** (uppercase micro-labels via the
  existing `--tp-font-label` token) for the drastic type-contrast the brief asks for.
- **"Space Grotesk" is still loaded** in the Google Fonts `<link>` and still referenced literally
  in ~24 `static/css/pages/*.css` files (plus `agent-drawer.css`) — it was only removed from
  `masterpage.html`'s own rules (base headings, sidebar brand, page-loader title). Don't remove it
  from the font `<link>` until every one of those call sites has been migrated to
  `var(--tp-font-heading)`/`var(--tp-font-body)` in the later rollout steps (see step 9 below) —
  removing it early would silently fall back those un-migrated headings to the browser's default
  sans-serif before their turn in the checklist.

## Component-by-component directive

- **Buttons** (`.tp-btn*`, currently `--tp-ui-radius-control: 12px` at
  [ui-system.css:21](static/css/components/ui-system.css#L21)): switch to `--tp-radius-flat`, add
  tracked letter-spacing on the label, drop the pill shape with no exceptions — including
  `.tp-btn--sm`. Compensate for the lost pill affordance with a confident hover state (see
  Interaction & motion).
- **Chips/badges** (`.tp-chip*`, `border-radius: 999px` at
  [ui-system.css:631](static/css/components/ui-system.css#L631) plus its `--meta`, `--count`,
  `--ec`, `--go`, `--state`, etc. modifiers): replace the pill with a rectangular low-contrast
  frame (`border: 1px solid var(--tp-color-border-soft)`, `border-radius:
  var(--tp-radius-flat)`), or for pure metadata rows (genome/protein counters) drop the frame
  entirely and separate values with a vertical bar (`│`) instead. Route the text through the
  existing `--tp-font-label` size + uppercase + tracked letter-spacing treatment rather than
  inventing a new label style.
- **Icon wrappers** (50% circles in `data-sources.css`, `protein-detail.css`,
  `proteins-list.css`, `structure-fullscreen.css` — **not** the loader/spinner circles in
  `masterpage.html`, which are exempt, see audit note above): unwrap to
  bare linear SVG icons aligned to the text baseline. If a background frame is genuinely needed
  for click-target size, use a flat square — never a circle.
- **Panels/cards** (`.tp-ui-panel`, hero blocks on `--tp-ui-radius-panel`/`-hero`): flatten to
  `--tp-radius-flat`. Replace `box-shadow: var(--tp-shadow-lg/-md)` used as a section separator
  with a single 1px `border-top`/`border-bottom: 1px solid var(--tp-color-border-soft)` hairline.
  Keep `--tp-shadow-xs`/`-sm` for genuinely floating/overlay elements only (modals, dropdowns,
  tooltips, the agent drawer) — not for static content sections sitting in the page flow.
- **Section fusion — the more important structural move, not just a radius swap.** Flat corners
  alone still read as "SaaS dashboard" if the page is a vertical stack of N separately-bordered
  `.tp-ui-panel` boxes with gaps between them (hero card, then a gap, then an "about" card, then a
  gap, then another card). Merge siblings like that into **one continuous bordered sheet**: drop
  `.tp-ui-panel`/individual borders from each section, give the *outer wrapping container* a
  single `border: 1px solid var(--tp-color-border-soft)` (no gap, no per-section background), and
  add a hairline `border-top` between consecutive sibling `<section>`s instead — use `section ~
  section` (general sibling), not `section + section` (adjacent), since a conditional script tag
  or modal-backdrop `<div>` can sit between two sections in the DOM without breaking the divider.
  Reference implementation: `home.css`'s `.home-page`/`.home-page > section ~ section` (redesign
  step 3). Apply the same fusion wherever a page stacks multiple `.tp-ui-panel`/`.tp-card`
  sections vertically with gaps — check each page in steps 5-7 for this pattern, not just radius.
- **Seamless mosaic for card grids** (already documented in `tpw-frontend-styling`): when a section
  contains a grid of small equal-weight cards (e.g. home's 6-card "Data sources" methodology
  grid), don't give each card its own border/radius/shadow — set the grid container's `gap: 1px`
  + `background: var(--tp-color-border-soft)`, and give each card `background: var(--tp-color-
  surface)` only. The 1px gaps read as hairline dividers, and a hover state becomes a background
  tint (`var(--tp-color-surface-soft)`) instead of a border/shadow/lift change. Reference:
  `home.css`'s `.home-about-grid`/`.home-about-card`.

## Interaction & motion — keep the app feeling like a tool, not a page

Flattening geometry removes two affordance cues at once (pill shape, drop shadow). Recover that
affordance through motion and state changes instead of reintroducing curves:

- Buttons/links: on hover, shift `border-color` to a stronger token
  (`--tp-color-border-strong`/brand) and/or a small `translateY(-1px)` lift using the existing
  `--tp-ui-motion-fast` / `--tp-ui-ease-standard` tokens — never add radius on hover to "soften"
  it back in.
- Table/list rows and clickable cards: a hairline left-border accent (2-3px, brand color) that
  appears on hover rather than a shadow lift, reinforcing the "editorial index/table of contents"
  feel while staying obviously interactive.
- Always respect `prefers-reduced-motion: reduce` (existing site convention) — kill both
  `animation` and `transition` in that query, not just one.
- This project's users respond well to subtle premium micro-interactions — don't undershoot into
  static/inert flatness in the name of sobriety. Sober geometry, lively interaction.

## Rollout checklist — token-first, then propagate by page

Work in this order; each step should be a separately reviewable change.

1. **Tokens**: add `--tp-radius-flat`/`--tp-radius-hairline` and the serif font-family
   `<link>` update to `masterpage.html` (light block + its dark-mode twin further down).
2. **Shared components** (`static/css/components/ui-system.css`): `.tp-btn*`, `.tp-chip*`,
   `.tp-ui-panel`, the hero block, icon-wrapper base classes. Most pages inherit from here, so
   this step alone fixes buttons/chips/panels site-wide before touching a single page file.
3. **Home** (`home.css` + its template) — the front door, highest-visibility hero/CTA surface.
   Do this first among pages so the new direction is visible end-to-end early.
4. **Masterpage chrome** — nav, topbar, global banner elements not already covered by
   `ui-system.css`.
5. **List/index pages** — `genomes-list.css`, `proteins-list.css`, `genome-overview.css`,
   `human-protein-list.css` (missed in the original audit — a plain text search input, already
   flattened to hairline): these are the most "editorial index" surfaces (tables, filters, counts)
   and benefit most from the journal-table treatment.
6. **Detail pages** — `protein-detail.css`, `human-protein-detail.css`, `binder-detail.css`.
7. **Workflow/utility pages** — `genome-upload.css`, `blast.css`, `customparam.css`,
   `formula-form.css`, `annotation-explorer.css`, `data-sources.css`, `auth.css`,
   `metabolism-overview.css`, `metabolic-network-genome.css`.
8. **Overlays last** — `structure-fullscreen.css`, `agent-drawer.css`: these are legitimately
   floating UI, so they keep more shadow/elevation than static content; revisit them only for the
   pill/circle cleanup, not the shadow-to-hairline swap.
9. **Cleanup**: once every page-local `"Space Grotesk"` reference from step 3-8 is migrated to
   `var(--tp-font-heading)`/`var(--tp-font-body)`, remove `Space+Grotesk` from the Google Fonts
   `<link>` in `masterpage.html` and grep the whole repo for the literal string `"Space Grotesk"`
   to confirm zero remaining consumers before deleting the import.

**Progress so far**: steps 1 and 2 are done.
- Step 1: `--tp-radius-flat`, `--tp-radius-hairline`, `--tp-font-heading`, `--tp-font-body`,
  `--tp-font-mono` are live in `masterpage.html`; the Source Serif 4 `<link>` is added;
  `body`/`h1`/`h2`/`h3-h5`/sidebar-brand/page-loader-title reference the new font tokens.
- Step 2: every `border-radius` in `ui-system.css` and in `masterpage.html`'s shared chrome
  (`.btn`/`.tp-btn` + all its color modifiers, `.tp-chip*`, `.tp-ui-panel`, `.tp-page-hero`,
  form controls, sidebar/nav, tooltips, pagination, breadcrumbs, the page loader, `.tp-card`,
  `.tp-file-input`) now resolves to `var(--tp-radius-flat)` or `var(--tp-radius-hairline)` — no
  literal numeric `border-radius` remains except the four `50%` loader-spinner circles, which are
  exempt (see audit note). `--tp-btn`/`.btn` also got a hover `translateY(-1px)` lift (was
  `transform: none`) to recover the affordance the pill shape used to carry.
- **Bonus win**: `--tp-ui-radius-panel`/`--tp-ui-radius-hero` (in `ui-system.css`) were repointed
  from `--tp-radius-md`/`-lg` straight to `--tp-radius-flat`. Those two tokens feed **~26 call
  sites across 14 page files** (`home.css`, `blast.css`, `customparam.css`, `formula-form.css`,
  `genome-overview.css`, `genome-upload.css`, `genomes-list.css`, `protein-detail.css`,
  `proteins-list.css`, `binder-detail.css`, `annotation-explorer.css`, `auth.css`,
  `metabolic-network-genome.css`, `agent-drawer.css`) — every page hero and content panel is
  already flat-cornered site-wide as of step 2, *without* individually editing those files. Steps
  3-8 below are now mainly about: (a) the page-local `"Space Grotesk"` → token migration, (b) any
  page-local pill/circle badges those files style directly (not through `.tp-chip`), and (c) the
  static-content shadow-to-hairline swap on any page-local card that isn't already `.tp-ui-panel`/
  `.tp-card`/`.tp-page-hero`. Radius is *not* the remaining work for most of them anymore.

After each file: grep the diff for stray `#hex` codes (per `tpw-frontend-styling`'s hard rule) and
confirm brace balance. There is no local rendering environment in this working setup — flag
explicitly to the user that a visual pass in their own browser is required after each step, since
tag/brace balance only proves the syntax survived, not that the redesign reads correctly.

## Non-negotiables inherited from CLAUDE.md / tpw-frontend-styling

- Hex colors stay confined to `masterpage.html`'s `:root` block — new tokens follow the same rule.
- One CSS file per page stays intact; this is a value-level redesign, not a file-structure
  rewrite.
- Every new or changed token needs its dark-mode counterpart — don't break dark-mode parity while
  chasing the light-mode look.