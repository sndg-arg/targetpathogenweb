# UI Redesign Plan (Doctoral Project)

## Goal
Deliver a modern, consistent, and high-usability interface for genome/protein prioritization workflows, without breaking cluster-safe behavior or core scientific features.

## Phase 1: Global Foundation
- Unify visual system in base layout (colors, buttons, inputs, pagination, table shell).
- Improve sidebar collapsed mode (readable labels via tooltip, clearer navigation).
- Replace empty homepage areas with useful dashboard content.

Status: Completed

## Phase 2: Search Workspaces
- Reduce visual noise in `Genomes` and `Proteins`.
- Keep main tasks primary; move secondary actions to compact menus.
- Add optional hide/show for protein side detail panel.
- Improve list readability for long sessions and large result sets.

Status: Completed

## Phase 3: Protein Profile UX
- Improve hero readability (gene metadata handling, less noisy actions).
- Align DataTables/technical tables with design system.
- Improve 3D/pockets readability (score semantics and table clarity).

Status: In progress

## Phase 4: QA + Regression Safety
- Visual QA desktop + mobile.
- Functional QA for: search, filters, formula modal, table pagination, feature viewer, 3D actions.
- Confirm no regressions in anonymous/authenticated flows.
- Prepare clean commit checklist.

Status: Pending

## Acceptance Criteria
- Same visual language across `home`, `genomes`, `proteins`, and `protein detail`.
- No duplicated or unnecessary explanatory text in critical panels.
- Better first-time readability for non-bio users, while preserving technical depth.
- Existing routes and scientific views continue to work (`features`, `3D`, `binders`, `downloads`).
