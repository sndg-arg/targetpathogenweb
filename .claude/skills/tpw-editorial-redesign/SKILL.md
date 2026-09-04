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

## When a hairline divider earns its place — and when it's noise

A divider isn't the default for every section boundary. It has one job: mark a seam that would
otherwise be ambiguous. Two clear cases:

- **Use it** when a page has a small number of sections (roughly 2-4) and/or adjacent sections
  don't already carry a strong heading/eyebrow of their own — the line is doing real work marking
  where one block ends and the next begins. Home (hero/operations/about/team), Genomes
  (hero/toolbar/table), Metabolism (hero/panel) all fall here.
- **Skip it** (spacing only — a generous `margin-top`, no `border-top`) when a page stacks many
  sections in a row (5+) and each one already opens with its own bold `h2`/eyebrow. A line before
  *every single one* on top of that duplicates a signal the heading already gives, and starts
  reading as a ruled form/spreadsheet rather than an editorial page. Assembly
  (`genome-overview.css`'s `.genome-grid`, six sections: targets/evidence/browse/downloads/
  details/danger) is the reference case — `.genome-grid > * ~ *` uses `margin-top: 40px` only, no
  border.
- **Skip it** when one of the two sections already carries its own distinct boundary treatment
  (a callout with its own border/background/accent stripe, e.g. Proteins' `.filter-tray`) — a
  hairline on top of that is a second signal for one seam. Exclude that section from the sibling
  selector on both sides (`section:not(.filter-tray) ~ section:not(.filter-tray)`), relying on its
  own margin for spacing instead.

There's no fixed section-count threshold — 2-4 defaults to "use it," 5+ with strong per-section
headings defaults to "skip it," but read the actual page rather than mechanically applying a
number. When unsure, ask rather than guessing again — this exact question came up mid-rollout and
changed how several already-shipped pages were adjusted.

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

## Any element that keeps its own border needs a margin, not just padding

This bit as a real bug across several pages before it got caught: once a page's hero/sections are
fused (no border, inset via `padding: <v> 18px`), anything that's *intentionally* left boxed
(quick-nav, a workbench card, a callout) still needs `margin: 0 18px` on the box itself. Without
it, the box's border sits flush at the page's raw edge (`margin: 0` by default) while everything
else's *text* starts 18px in via padding — the border visibly pokes out to the left of all the
unboxed content around it. Padding alone only controls where a box's own content sits *inside* the
box; it does nothing for where the box's edge sits *relative to its siblings*. Checklist for any
element you deliberately leave boxed: does it sit next to (or between) unboxed, padding-inset
content? If yes, it needs `margin: 0 18px` (or equivalent) so the border lines up. Also watch for
`width: 100%` combined with that margin — it overflows the container (100% + 36px); use `width:
auto` (or drop the explicit width and rely on grid stretch/flex sizing) instead.

## Site-wide chrome already handled — don't redo per page

- **White page background**: `--tp-color-page-start`/`-end` = `#ffffff` in light mode, dark mode
  untouched, already global in `masterpage.html`.
- **`.tp-main`/`.tp-shell`**: merged into a single `.tp-main` wrapper (the old `.tp-shell` div was
  fully inert and unused by any JS/other template) — nothing to reference here, just know the
  extra wrapper is gone.

## Rollout — pages with multiple `.tp-ui-panel` blocks, by size (grep count as of this pass)

Audited via `grep -o "tp-ui-panel\b" <template> | wc -l` across `tpweb/templates/`, only counting
templates with more than one occurrence (a single `.tp-ui-panel` isn't a "stacked cards" case):

- **Done**: `index.html` (Home), `search/genomes.html`, `search/proteins.html`,
  `genomic/assembly.html`, `genomic/metabolism.html`, `genomic/metabolism_network.html`,
  `genomic/metabolism_pathway.html`, `genomic/protein_metabolic_network.html`,
  `genomic/customparam.html`. Assembly/metabolism/metabolism_network/metabolism_pathway/
  protein_metabolic_network share `.genome-hero`/`.genome-card` in `genome-overview.css`, fixed
  once there rather than per page.
- **Done (all)**: `search/formulaform.html`, `about/about_us.html`, `user/upload_data.html`,
  `human/human_protein.html`, `genomic/binder.html`, `genomic/protein.html`,
  `about/data_sources.html`, `genomic/annotation_explorer.html` (single-hero page, missed by the
  original ">1 tp-ui-panel" scan — re-audit with `grep -rln "tp-page-hero" tpweb/templates` to
  catch that class of miss, not just the multi-panel one). Every `.tp-page-hero` usage site-wide is
  gone as of this pass — confirm that stays true (`grep -rln tp-page-hero tpweb/templates` should
  return nothing) before considering a new page "done."
- Workbench/tool-style pages keep one card boxed on purpose: `formula-form.css`'s editor+variables
  cards and footer, `customparam.css`'s form+guide, `genome-upload.css`'s submit-form+guide,
  `annotation-explorer.css`'s single `.explorer-card`. `protein-detail.css`'s
  `.target-summary-panel` (tone-colored executive summary) and `.protein-interpretation-guide`
  (collapsible info box) are callout-style exceptions, not workbench ones, but the same "boxed
  element needs `margin: 0 18px` for border alignment" fix applies to all of them.
- Check each page's own CSS file under `static/css/pages/` for its `.tp-ui-panel`/`.tp-card`-based
  section styling before editing the template — several pages (genomes-list, proteins-list,
  customparam) duplicate the shared class's box styling directly under a page-specific class name,
  so removing the HTML class alone isn't enough; the page CSS needs its own edit too. Conversely,
  if a page-specific class is applied *alongside* a shared class that still has its old box styling
  (e.g. `tp-ui-panel` left in the HTML after only editing the page CSS), the shared class's box
  reappears — pull both, or neither, per element.

For each page: identify the top-level sections (usually direct children of the page's outermost
wrapper div), decide fuse-vs-keep per the exception rule above, remove `tp-ui-panel`/`tp-card`
from the ones that fuse, add the `> section ~ section` (or equivalent sibling selector matching
that page's actual DOM) hairline rule, bump that page's CSS cache-buster in its template, verify
brace balance + no stray hex, commit, push.
