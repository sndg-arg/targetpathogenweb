# Druggability Provenance and Curated Structure Plan

## Goal

Make protein-level target prioritization scientifically traceable when curated result tables provide multiple structure-derived scores.

The immediate driver is the Klebsiella curated import. The same design should later be extended to normal pipeline runs so file-based imports and pipeline-generated genomes expose comparable evidence.

## Biological Rule For The Main Table

The main protein table, top-target cards, and default sorting should show the best curated structure-derived druggability score using this priority order, confirmed by the biology team:

1. PDB experimental structures.
2. ColabFold or another curated model provided by the data source.
3. AlphaFold / UniProt models.

If several PDB structures exist for the same protein, use the PDB-derived pocket with the highest druggability.

Important: the main Druggability value is a selected protein-level score. It is not necessarily the best pocket of the structure currently open in the 3D viewer.

## Current Problem

The TSV contains selected/best structure scores and ColabFold-specific scores.

Selected/best structure columns:

- `druggability_score`
- `best_fpocket_structure`
- `fpocket_pocket`
- `p2rank_probability`
- `best_p2rank_structure`
- `p2rank_pocket`

ColabFold-specific columns:

- `colabfold_druggability_score`
- `colabfold_fpocket_pocket`
- `colabfold_p2rank_probability`
- `colabfold_p2rank_pocket`

TPW currently shows the imported `Druggability` value, but the 3D viewer may show a different structure.

Example: `VK055_0909` has the main curated score from `A0A0H3GT32`, while the viewer only has the ColabFold model loaded. The visible pocket score can therefore differ from the main Druggability score.

The data are not necessarily wrong. The UI is missing provenance: which structure and pocket produced the main score.

## Source Files For Klebsiella

Local Windows copies:

- `C:\Users\54116\Desktop\Exactas\KpATCC43816_results_table.tsv`
- `C:\Users\54116\Desktop\Exactas\KpKP13_results_table.tsv`

Nodo0/container paths currently used:

- ATCC: `/app/targetpathogenweb/data/imports/Klebsiella/results_table.tsv`
- KP13: `/app/targetpathogenweb/data/uploads/KpKP13_results_table.tsv`

## TSV Columns To Preserve

### Main Selected Pocket Evidence

These define the score shown in the main table and top-target cards:

- `druggability_score`
- `best_fpocket_structure`
- `fpocket_pocket`
- `p2rank_probability`
- `best_p2rank_structure`
- `p2rank_pocket`

### ColabFold-Specific Evidence

These explain the scores shown when the active structure is the ColabFold model:

- `colabfold_plddt`
- `colabfold_druggability_score`
- `colabfold_fpocket_pocket`
- `colabfold_p2rank_probability`
- `colabfold_p2rank_pocket`

### Structure Inventory

- `structure`

This field can contain many entries. It should not be blindly loaded in full into TPW as a first implementation step, because some proteins have many PDBs.

### Conservation

Already imported, but needs clearer UI:

- `core_roary`
- `core_corecruncher`

A protein should be highlighted as conserved/core only when both are true.

### Microbiome Context

Display together:

- `gut_microbiome_offtarget_norm`
- `gut_microbiome_offtarget_counts`
- `gut_microbiome_genomes_analyzed`

Example:

`86 / 4744 gut microbiome genomes`, plus the normalized score.

### Structural Human Off-Target / FoldSeek

Useful, but second phase:

- `FS_*`
- `FS_CB_*`

They describe structural similarity to human proteins from different query structures.

## Implementation Phases

### Phase 1: Persist Score Provenance From Curated TSVs

Update the curated import path so these fields are saved per protein:

- existing main `Druggability` from `druggability_score`
- `best_fpocket_structure`
- `fpocket_pocket`
- `best_p2rank_structure`
- `p2rank_probability`
- `p2rank_pocket`
- `colabfold_druggability_score`
- `colabfold_fpocket_pocket`
- `colabfold_p2rank_probability`
- `colabfold_p2rank_pocket`
- `gut_microbiome_genomes_analyzed`

Preferred first implementation: store these as `ScoreParamValue` rows to avoid a larger schema change.

If string provenance fields become awkward, introduce a dedicated curated evidence model later.

Validation examples:

- `VK055_0909`: main score remains `0.336`; source shows `A0A0H3GT32`, `Pocket 2`.
- `VK055_0891`: PDB-rich protein; main score should point to the selected PDB structure and pocket from the TSV.
- `VK055_0893`: ColabFold-only example; main and ColabFold source may be the same.

### Phase 2: Protein Detail UI

Separate these concepts:

1. Main selected score.
   - Label: `Selected Druggability` or `Curated Druggability`.
   - Show score.
   - Show source structure.
   - Show source pocket.
   - Show source method when inferable: PDB, curated/ColabFold, or AlphaFold/UniProt.

2. Active viewer structure.
   - Show which structure is currently displayed.
   - If it differs from `best_fpocket_structure`, show a clear note: visible pockets belong to the active structure and may not match the selected main score.

3. ColabFold pocket summary.
   - Show ColabFold-specific scores when present.
   - Do not overwrite the main selected score with the ColabFold score unless the selected structure is ColabFold.

4. P2Rank summary.
   - Mirror the same provenance for `p2rank_probability`.

### Phase 3: Core Conservation UI

In Target Profile, show:

- `Roary: core` or `Roary: accessory`
- `CoreCruncher: core` or `CoreCruncher: accessory`
- emphasized badge only when both are true: `Conserved core gene`

### Phase 4: Gut Microbiome UI

Show raw count and denominator together:

- `gut_microbiome_offtarget_counts / gut_microbiome_genomes_analyzed`
- normalized value as supporting detail

Example:

`Gut microbiome off-target: hit in 86 / 4744 genomes (normalized 0.018)`.

### Phase 5: Curated Structure Loading Policy

Do not load every entry in the `structure` set by default in the first pass.

Recommended policy:

1. Ensure structures referenced by `best_fpocket_structure` and `best_p2rank_structure` are represented or at least named in the UI.
2. If the referenced selected structure is missing from TPW, show: `Selected score source not loaded in viewer`.
3. Add controlled backfill commands for missing selected structures:
   - PDB code: load/fetch selected PDB only.
   - UniProt/AlphaFold ID: fetch selected AlphaFold model only.
   - ColabFold/curated model: use existing local curated model.
4. Load the full `structure` set only in a separate opt-in backfill, with UI limits and clear runtime expectations.

### Phase 6: FoldSeek Evidence

Add after Phases 1-4 are stable.

Potential storage: new `FoldSeekHit` model with:

- `bioentry`
- `query_type`
- `query_structure`
- `human_structure_hit`
- `alnlen`
- `qcov`
- `tcov`
- `lddt`
- `qtmscore`
- `ttmscore`
- `alntmscore`
- `rmsd`
- `prob`
- `pident`
- `evalue`

UI: add a structural human off-target card. If selected and ColabFold queries differ, show both.

### Phase 7: Normal Pipeline Parity

After curated import and UI are correct, update the standard pipeline so non-curated genomes produce comparable values:

- selected best FPocket score and source structure
- selected FPocket pocket id
- selected best P2Rank score and source structure
- selected P2Rank pocket id
- ColabFold-specific pocket scores when ColabFold exists
- microbiome denominator
- FoldSeek structural human off-target output when enabled

Likely touch points:

- `druggability_2_csv` or equivalent output step
- P2Rank export/parsing
- microbiome/off-target export
- FastTarget/FoldSeek export
- pipeline plan/status docs

## Suggested Execution Order

1. Persist provenance fields from TSV in `import_external_results`.
2. Backfill these fields for ATCC and KP13 without running heavy stages.
3. Update protein detail UI for selected score provenance.
4. Add core conservation and microbiome denominator UI.
5. Validate with representative proteins and screenshots.
6. Document the biological rule and interpretation.
7. Implement selected-structure backfill and FoldSeek.
8. Extend the normal pipeline.

## Non-Goals For First Pass

- Do not recompute Druggability from loaded pockets for curated Klebsiella unless explicitly requested.
- Do not run heavy workloads on Nodo0.
- Do not load every PDB from `structure` automatically.
- Do not treat viewer pocket scores and main selected Druggability as interchangeable.


## Current Implementation Status

### Done In This Branch

- Curated TSV imports preserve selected pocket provenance as per-protein score values.
- Protein detail separates the main selected/curated `Druggability` value from the active 3D viewer structure.
- Protein detail shows selected FPocket, selected P2Rank, and ColabFold-specific pocket values when present.
- Target profile shows Roary/CoreCruncher, conserved-core status, and gut microbiome count/denominator plus normalized value.
- Categorical score import now ignores empty/NaN values instead of creating noisy score options.

### Still Pending

- Dedicated curated-evidence model; this pass stores provenance in `ScoreParamValue`.
- Selected-structure backfill/loading policy for missing selected source structures.
- FoldSeek structural human off-target storage and UI.
- Normal pipeline parity for non-curated genomes.

### Nodo0 Deployment Commands

After pulling this branch on nodo0, re-run `import_external_results` for both Klebsiella genomes. This reloads metadata/scores only; it does not run heavy stages or SLURM jobs.

ATCC:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue   /opt/conda/envs/tpv2/bin/python manage.py import_external_results public__KpATCC43816   --results-tsv /app/targetpathogenweb/data/imports/Klebsiella/results_table.tsv   --datadir /app/targetpathogenweb/data   --overwrite
```

KP13:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue   /opt/conda/envs/tpv2/bin/python manage.py import_external_results public__KpKP13   --results-tsv /app/targetpathogenweb/data/uploads/KpKP13_results_table.tsv   --datadir /app/targetpathogenweb/data   --overwrite
```

Validation example for `VK055_0909`: main `Druggability` should remain `0.336`, with `best_fpocket_structure=A0A0H3GT32` and `fpocket_pocket=Pocket 2`; ColabFold-specific FPocket remains separate.

