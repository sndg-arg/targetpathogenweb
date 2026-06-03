# UX and Bioinformatics Product Guide

## UX principles for this app

- Show pipeline status in context:
  - Global status on index.
  - Per-genome/per-assembly status near entity title.
- Keep scientific information scannable:
  - Primary facts first (organism/accession/protein count).
  - Secondary annotations in compact metadata rows.
- Reduce visual noise:
  - Limit simultaneous CTA blocks.
  - Keep one dominant action per section.

## Visual system

- Follow semantic color variables from `masterpage.html` and `docs/COLOR_SYSTEM.md`.
- Keep contrast high for scientific dashboards and long reading sessions.
- Reserve accent color for interactive hierarchy and active state.
- Use subtle gradients for hero/cards to keep scientific UI premium without editorial excess.

## Bioinfo product backlog (prioritized)

1. Pipeline timeline per genome:
   - show completed/current/pending stages with timestamps.
2. Run history:
   - store and render recent runs by genome accession.
3. Export reproducibility bundle:
   - inputs, selected parameters, formula and outputs metadata.
4. Structured failure states:
   - explicit reason and recovery action when pipeline stops.
5. Performance UX:
   - skeleton loaders and partial rendering for large protein tables.

## Definition of done for new screens

- Works desktop/mobile.
- Meets palette and spacing standards.
- Clarifies what is running and for which genome.
- Includes empty/loading/error states.
