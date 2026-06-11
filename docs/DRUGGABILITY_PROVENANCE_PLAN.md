# Druggability provenance plan - Klebsiella curated import

## Goal

Make the Klebsiella target-prioritization data scientifically consistent in TPW.

The main issue was that the curated TSV provides a selected druggability value and selected source structure per protein, but TPW initially did not always have that selected structure/pocket loaded. This produced confusing cases where the main `Druggability` score came from one structure, while the 3D viewer showed another structure or no matching pocket.

The target behavior is:

1. Preserve the curated TSV values as the main source of ranking.
2. Load the structure used by the curated selected evidence when possible.
3. Load the corresponding FPocket/P2Rank pockets when possible.
4. Make missing or failed evidence explicit instead of silently showing a mismatched structure.

## Structure priority

For the main table and selected target evidence, the priority agreed with the biology team is:

1. Experimental PDB
2. ColabFold / curated model
3. AlphaFold / UniProt model

If several structures of the same class are available, use the structure selected by the curated TSV, which usually corresponds to the best druggability source.

The main `Druggability` score must remain the TSV-curated value. Do not overwrite it with `druggability_2_csv`.

## Input datasets

Curated Klebsiella genomes:

- `public__KpATCC43816`
- `public__KpKP13`

Main curated TSVs:

- `results_table.tsv` for ATCC
- `KpKP13_results_table.tsv` for KP13

Important TSV columns loaded into TPW include:

- `druggability_score`
- `best_fpocket_structure`
- `fpocket_pocket`
- `best_p2rank_structure`
- `p2rank_probability`
- `p2rank_pocket`
- `colabfold_druggability_score`
- `colabfold_fpocket_pocket`
- `colabfold_p2rank_probability`
- `colabfold_p2rank_pocket`
- `colabfold_plddt`
- `core_roary`
- `core_corecruncher`
- `human_offtarget`
- `gut_microbiome_offtarget_norm`
- `gut_microbiome_offtarget_counts`
- `gut_microbiome_genomes_analyzed`
- `psortb_localization`
- UniProt mappings

## Completed work

### Curated TSV import

The curated TSV values were imported for both Klebsiella genomes.

Loaded values include:

- main `Druggability`
- selected FPocket/P2Rank source structure and pocket IDs
- ColabFold-specific evidence
- localization
- Roary/CoreCruncher conservation
- human off-target
- gut microbiome off-target
- pLDDT
- UniProt mapping

The main `Druggability` value now matches the curated TSV. Example checked:

- `VK055_0909`
  - TSV `Druggability = 0.336`
  - TPW `Druggability = 0.336`

### UI provenance

The protein detail UI was updated to show selected druggability evidence more clearly.

It now separates:

- selected FPocket evidence
- selected P2Rank evidence
- ColabFold model evidence
- whether the selected source is loaded in the viewer

This helps explain cases where the main curated score comes from a different structure than the currently displayed viewer structure.

### Experimental PDB selected structures

Selected PDB structures from the curated TSV were backfilled.

Final selected PDB structure status:

- ATCC:
  - selected PDB links loaded: complete
- KP13:
  - selected PDB links loaded: complete

### Experimental PDB pockets

FPocket and P2Rank were run for selected experimental PDB structures via SLURM and imported into TPW.

Final selected PDB pocket status:

- `public__KpATCC43816`
  - FPocket: `157/157`
  - P2Rank: `152/157`
  - expected `No_pockets`: `5`
  - missing real pockets: `0`

- `public__KpKP13`
  - FPocket: `153/153`
  - P2Rank: `147/153`
  - expected `No_pockets`: `6`
  - missing real pockets: `0`

### AlphaFold / UniProt selected structures

Selected AlphaFold/UniProt models from the curated TSV were backfilled.

Final selected AlphaFold structure status:

- `public__KpATCC43816`
  - selected AlphaFold rows: `9290`
  - missing rows: `0`

- `public__KpKP13`
  - selected AlphaFold rows: `10384`
  - missing rows: `0`

### AlphaFold / UniProt pockets

FPocket and P2Rank were run for selected AlphaFold structures via SLURM.

Final deduplicated SLURM result status before TPW import:

- `public__KpATCC43816`
  - expected rows: `4645`
  - FPocket: `4645/4645`
  - P2Rank: `3960/3960`
  - expected `No_pockets`: `685`
  - unresolved: `0`

- `public__KpKP13`
  - expected rows: `5192`
  - FPocket: `5191/5192`
  - P2Rank: `4325/4325`
  - expected `No_pockets`: `867`
  - unresolved: `1`

Remaining unresolved AlphaFold pocket case:

- `KP13_04817`
  - structure: `AF_A0A0H3GVM3`
  - FPocket: failed
  - P2Rank: OK

The AlphaFold pocket result tarballs were generated and copied back to nodo0:

- `public__KpATCC43816_selected_alphafold_pocket_results.tar.gz`
- `public__KpKP13_selected_alphafold_pocket_results.tar.gz`

Both tarballs were validated with `tar -tzf`.

## Current status

The AlphaFold pocket results are ready to import into TPW.

Next immediate step:

1. Import ATCC AlphaFold pockets.
2. Import KP13 AlphaFold pockets.
3. Validate selected AlphaFold pocket coverage in TPW.
4. Confirm the only unresolved AlphaFold case remains `KP13_04817 / AF_A0A0H3GVM3` FPocket, if still not loadable.

Do not run:

```bash
druggability_2_csv
```

The main Druggability score must stay as the curated TSV value.

## Final validation checklist

After importing AlphaFold pockets, validate for both genomes:

- selected PDB structures loaded
- selected PDB FPocket/P2Rank pockets loaded
- selected ColabFold/curated structures loaded
- selected ColabFold/curated pockets loaded
- selected AlphaFold/UniProt structures loaded
- selected AlphaFold/UniProt FPocket pockets loaded when expected
- selected AlphaFold/UniProt P2Rank pockets loaded when expected
- P2Rank `No_pockets` counted as expected absence
- no numeric mismatch between curated TSV `druggability_score` and TPW `Druggability`
- UI clearly distinguishes selected evidence from currently viewed structure

Do not run `druggability_2_csv` as part of this validation, because it would overwrite the curated main `Druggability` score.

## Pending audit: DEG / essentiality consistency

During Klebsiella validation, the biology team flagged that some proteins expected to have DEG support appear as `N` in TPW.

Example:

- `KP13_01905`
- gene/product: `murG`, undecaprenyl-PP-MurNAc-pentapeptide-UDPGlcNAc GlcNAc transferase
- TPW currently shows:
  - `hit_in_deg = N`
  - `deg_identity = 0`
  - `deg_evalue = 1`

This is biologically suspicious and should not be interpreted as a confirmed negative result yet.

Current finding:

- For `public__KpATCC43816`, FastTarget DEG source files were found, including:
  - `deg_blast.tsv`
  - `hit_in_deg.tsv`
- For `public__KpKP13`, no matching DEG/essentiality source files were found under the inspected FastTarget/data paths.
- Therefore, KP13 DEG values currently look like default/fallback “no hit” values rather than validated DEG BLAST results.

Interpretation:

- DEG evidence for ATCC is available and can be audited against FastTarget output.
- DEG evidence for KP13 should be treated as not validated until the source files are recovered or the DEG stage is rerun.
- Klebsiella target prioritization should not rely on KP13 DEG yet.

Next steps for DEG:

1. Recover the original KP13 DEG/FastTarget files if they exist outside the current container/data paths.
2. If they cannot be recovered, rerun the FastTarget essentiality/DEG stage for `public__KpKP13`.
3. Load real KP13 DEG outputs into TPW:
   - `hit_in_deg`
   - `deg_identity`
   - `deg_evalue`
4. Validate known control cases, especially:
   - `KP13_01905` / `murG`
5. Add a broader evidence audit for both Klebsiella genomes.

## Broader evidence audit

After closing pockets, run a consistency audit across both Klebsiella genomes for:

- DEG / essentiality
- human off-target
- gut microbiome off-target
- localization
- Roary/CoreCruncher conservation
- GO/EC/InterPro annotations
- UniProt mappings
- structures by source type
- FPocket/P2Rank pocket coverage
- ligand evidence

The goal is to detect cases where TPW shows default values, missing source files, or asymmetric coverage between ATCC and KP13.