---
name: tpw-editorial-redesign
description: Layout-fusion standard for Target Pathogen Web — removes the "stacked separately-boxed cards floating on a gray canvas" pattern by merging page-level sections onto one continuous white background with hairline dividers, while keeping the site's rounded-corner geometry, Space Grotesk headings, and pill-shaped chips/buttons exactly as they are. Load before restructuring any page's top-level layout (multiple `.tp-ui-panel`/`.tp-card` sections stacked with gaps between them). Composes with tpw-frontend-styling (token/hex/verification rules) — load both for CSS work.
---

# Target Pathogen Web — layout fusion standard

## What this is (and isn't)

This is a **structural** change, not a geometry one. An earlier version of this skill also
flattened corners and swapped in a serif typeface — that direction was tried, reverted, and
explicitly rejected. **Rounded corners, Space Grotesk headings, and pill-shaped
buttons/chips/badges stay exactly as they already are everywhere in the codebase.** Don't touch
`border-radius` on buttons, chips, form controls, or individual small cards as part of this work.

The only thing this skill changes: **how page-level sections sit relative to each other and to the
page background.**

## The pattern (validated on Home, `tpweb/templates/index.html` + `static/css/pages/home.css`)

**Before**: a page is `<div class="home-page">` containing several `<section class="... tp-ui-panel">`
blocks (hero, "Data sources", "About us", etc.), each with its own `border` + `background:
var(--tp-color-surface)`, separated by a `gap` in the parent's grid. This reads as a stack of
white cards floating on the page's (gray) background — "mil cards, y esas mil cards en una card
gigante flotando sobre el fondo."

**After**:
1. The page background itself is plain white (`--tp-color-page-start`/`-end` now equal
   `--tp-color-surface`, `#ffffff`, in `masterpage.html` — this is already global/site-wide, not
   per-page, so every page already sits on a white background without any page-specific fix).
2. The wrapping container (`.home-page`) has **no border, no background, no gap** — just width/
   max-width/margin. Content sits directly on the page's own white background.
3. Each former `.tp-ui-panel` section loses that class — no individual border/background/radius.
4. Consecutive top-level sections get a hairline divider instead of a gap + separate boxes:
   ```css
   .the-page > section ~ section {
       border-top: 1px solid var(--tp-color-border-soft);
   }
   ```
   Use `~` (general sibling), not `+` (adjacent) — a conditional script tag, modal backdrop `<div>`,
   or any other non-`<section>` element can sit between two sections in the DOM without breaking
   the divider chain.
5. If a section's own horizontal padding differs from its siblings' (e.g. a hero with more
   generous padding than the panels below it), align them — a mismatch that a card border used to
   hide becomes visible once sections share one continuous background.

## The exception: small equal-weight content tiles keep their card treatment

Not everything inside a fused section becomes borderless. A grid of small, equal-weight tiles
(Home's 6-item "Data sources" methodology grid: Target profile / 3D Structure / Binding sites /
etc. — icon + heading + short paragraph + tag chips) is closer in spirit to a chip/tag than to a
page section, and **keeps** its individual `border` + `border-radius` + `box-shadow` + hover lift.
Don't seamless-mosaic these (an earlier attempt did, and it read as "cuadrado"/wrong once
rounded corners came back) — the rule is about page-level section framing, not every card-shaped
thing on the page. When evaluating a candidate: "is this a distinct page section (hero, a whole
methodology write-up, an operations panel)" → fuse it. "Is this one tile among several
same-shaped siblings, closer to a tag than a section" → leave its card styling alone.

## Site-wide chrome already handled — don't redo per page

- **Masthead accent bar**: lives on `.tp-main::before`/`::after` in `masterpage.html` (gradient
  bar + one-time load-in shimmer, `prefers-reduced-motion`-aware). Applies to every page
  automatically already — nothing to add per page.
- **White page background**: `--tp-color-page-start`/`-end` = `#ffffff` in light mode, dark mode
  untouched, already global in `masterpage.html`.
- **`.tp-main`/`.tp-shell`**: merged into a single `.tp-main` wrapper (the old `.tp-shell` div was
  fully inert and unused by any JS/other template) — nothing to reference here, just know the
  extra wrapper is gone.

## Rollout — pages with multiple `.tp-ui-panel` blocks, by size (grep count as of this pass)

Audited via `grep -o "tp-ui-panel\b" <template> | wc -l` across `tpweb/templates/`, only counting
templates with more than one occurrence (a single `.tp-ui-panel` isn't a "stacked cards" case):

- **Small/quick wins**: `search/genomes.html` (2), `genomic/metabolism_network.html` (2),
  `genomic/metabolism.html` (2), `genomic/customparam.html` (2).
- **Medium**: `search/formulaform.html` (6), `genomic/metabolism_pathway.html` (6),
  `about/about_us.html` (6), `genomic/protein_metabolic_network.html` (8).
- **Large — needs careful per-panel judgment** (many of these ~20 occurrences will be legitimate
  "small tile" exceptions per the rule above, not page-sections to fuse — don't blind-strip every
  `.tp-ui-panel` class without checking what each one actually renders):
  `user/upload_data.html` (13), `human/human_protein.html` (12), `genomic/assembly.html` (14),
  `genomic/binder.html` (16), `genomic/protein.html` (20), `about/data_sources.html` (20).
- Corresponding CSS: `search/proteins.html` (genomes/proteins list pages), `genomic/assembly.html`
  → `genome-overview.css`; check each page's own CSS file under `static/css/pages/` for its
  `.tp-ui-panel`/`.tp-card`-based section styling before editing the template.

For each page: identify the top-level sections (usually direct children of the page's outermost
wrapper div), decide fuse-vs-keep per the exception rule above, remove `tp-ui-panel`/`tp-card`
from the ones that fuse, add the `> section ~ section` (or equivalent sibling selector matching
that page's actual DOM) hairline rule, bump that page's CSS cache-buster in its template, verify
brace balance + no stray hex, commit, push.
