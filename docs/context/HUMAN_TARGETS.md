# Human Targets

Moved out of `CLAUDE.md` so it only loads when needed.

## Human Targets (Target Human)
Sister feature to the bacterial-genome side of this app, deliberately in a **separate Django
app** (`human_target/`, not inside `tpweb/`) rather than a genome-upload/pipeline entity: one
small, fixed, already-known human protein set (UniProt-keyed) with several different analyses
layered on top over time, rather than "upload a genome, run the same pipeline, repeat." Shares
only the visual design system with Target Pathogen (`base/masterpage.html`, `--tp-*` tokens,
shared components) — zero data/functionality crossover.
- **Storage**: reuses `bioseq.Bioentry`/`Biodatabase` as a generic storage primitive (a synthetic
  `Biodatabase` named `human_curated_prots`, see `human_target/services/human_targets.py`) since
  `Binders`, `BioentryStructure`, `PDB`, and the EC/GO dbxref infra already key off `Bioentry` —
  this `Biodatabase` is purely an internal storage container, never surfaced via `GenomesView`/the
  Genomes list/upload flow. `HumanProtein` (`human_target/models/HumanProtein.py`) holds the
  parsed UniProt content, JSON-favoring at this pilot scale (10 curated proteins) rather than
  fully normalized, same pattern as `CuratedImportJob.summary_json`/`PipelineRun.payload`.
- **Reused unmodified from the bacterial side** (both already generic over any `Bioentry`, no
  genome coupling): `load_af_model` (structures), `load_ligq_2_results` (ligand evidence →
  `Binders`), `binder_summary.create_binders_dict`, `functional_annotations.persist_ec_go_annotations`.
- **Pilot ingest**: `python manage.py import_human_curated_proteins /path/to/new_data` reads a
  local `new_data/<ACC>/` tree (from the `target-human-web` reference repo's Zenodo archive — a
  sibling directory, front-end-only, used only to understand data shapes, never to be copied as
  code) for the 10 accessions in `DEMO_ACCESSIONS`. Writes a `UnipSp`/`UnipTr` `BioentryDbxref`
  pointing the `Bioentry` at its own accession (human `Bioentry.accession` already *is* the UniProt
  accession) — without this, `load_ligq_2_results`'s `is_direct` ligand classification silently
  defaults every match to "homolog."
- **Tabs**: Overview, Function, Sequence, Structure, Ligands, Cross-refs are built
  (`human_target/services/human_protein_summary.py` + `human_structure_summary.py`,
  `human_target/templates/human/human_protein.html`). Diseases, Expression, Pathways are not yet
  built — `HumanProtein.disease_comments` is captured at ingest but unused by any template.
- **URLs**: `/human/proteins` (`human_target:human_protein_list`), `/human/protein/<accession>`
  (`human_target:human_protein`), `/human/ligands` (`human_target:human_ligand_atlas`, Ligand
  coverage: proteome-wide LigQ_2 summary from `services/human_ligand_atlas.py`, cached and re-warmed
  by `refresh_human_target_summary`) — routed via `human_target/urls.py`, included from
  `tpwebconfig/urls.py`. Visible in the nav (top-bar "Human Targets" link + mobile nav item in
  `masterpage.html`).
- **Deploy**: no separate Docker service — `human_target` is just another entry in
  `LOCAL_APPS`, loaded by the existing `web`/`queue` containers, same as `bioseq`.
- **Scaling past the 10-protein pilot** (not yet built): AlphaFold DB already publishes
  precomputed per-UniProt-accession models at a stable public URL
  (`https://alphafold.ebi.ac.uk/files/AF-{accession}-F1-model_v4.cif`) and AlphaFill has a similar
  public per-accession API — for human proteins (near-total AlphaFold DB coverage), direct
  download is simpler than running the bacterial AlphaFold/ColabFold *prediction* pipeline, which
  is genome-shaped and not a good fit here. Ligand evidence at scale would reuse
  `pipeline/ligq_remote.py`'s SLURM steps unchanged, swapping only its genome-scoped FASTA dump
  for one keyed off `human_target`'s own `Bioentry` queryset.
- **Cross-app template gotcha**: Django's `{% extends "../base/masterpage.html" %}` (relative
  path, used throughout `tpweb/templates/*`) resolves relative to the *rendering template's own
  file location*, not to a fixed app root — it only works because every one of those templates
  lives one directory under `tpweb/templates/`, alongside `tpweb/templates/base/`. A template
  living in a different app (like `human_target/templates/human/*.html`) must use the absolute,
  non-relative form `{% extends "base/masterpage.html" %}` instead — Django's `app_directories`
  loader then finds it by searching every installed app's `templates/` dir for that name, landing
  correctly on `tpweb/templates/base/masterpage.html` regardless of which app the calling template
  belongs to.
- **Scaling to the full proteome** (in progress, ~20,400 accessions, proteome `UP000005640`):
  built around bulk downloads instead of 20,400 individual API calls, confirmed real this session:
  - **UniProt**: `https://rest.uniprot.org/uniprotkb/stream?query=proteome:UP000005640&format=json&compressed=true`
    — one streamed call for every entry. Confirmed field-by-field identical in shape to the
    single-accession/fixture shape `_build_human_protein_fields` already expects (only diff
    observed: normal `entryAudit.entryVersion` upstream drift) — zero parser changes needed.
  - **AlphaFold DB**: `https://ftp.ebi.ac.uk/pub/databases/alphafold/latest/UP000005640_9606_HUMAN_v6.tar`
    (4.8GB, 23,586 structures — some isoforms/fragments beyond the canonical accession set).
  - **KEGG pathways — implemented**: `python manage.py load_human_pathways_bulk
    [--accession ... | --accession-file PATH] [--dry-run] [--sleep 0.34]`. One call to
    `https://rest.kegg.jp/link/pathway/hsa` (every human gene→pathway link, `hsa:<entrez_id>\t
    path:hsa<id>`) resolved against our proteins' own `GeneID` cross-references (already stored,
    no extra call per protein), then one `rest.kegg.jp/get/<id>/kgml` fetch per *distinct*
    pathway actually needed (~350 total across the whole proteome, not one per protein). KGML
    parsing lives in `human_target/services/kegg_kgml.py` (`parse_kgml_root`/`parse_kgml_file`),
    extracted unchanged from `import_human_curated_proteins.py`'s old `_parse_kgml` (still
    importable under that name there, aliased) so both the pilot's local-file path and this
    live-fetch path share one parser.
  - **Bgee — implemented**: `https://www.bgee.org/ftp/current/download/calls/expr_calls/Homo_sapiens_expr_simple.tsv.gz`
    (confirmed 2026-10-22, ~170MB, Bgee 15.2; fetched by `fetch_human_proteome_bulk.sh`). Load with
    `python manage.py load_human_expression_bulk --bgee-tsv PATH [--accession ...|--accession-file PATH]
    [--dry-run]`: streams the gzipped file one gene at a time, matches Ensembl gene ids through the
    proteins' stored UniProt `Bgee`/`Ensembl` cross-references, and writes `expression_json` in the
    same shape as the pilot's per-protein heatmap loader (anatomical entity as "tissue").
  - **AlphaFill — opt-in bulk support**: the official bank is available at
    `rsync://rsync.alphafill.eu/alphafill/` (https://alphafill.eu/download). Stage the human
    subset on the login node with `bash scripts/cluster/fetch_human_alphafill_bulk.sh
    ACCESSIONS.txt [DEST_DIR] [--dry-run]`, where the input contains one stored HumanProtein
    accession per line. Filters include only canonical F1 CIFs and their metadata, plus the
    source license; the full multispecies bank is never mirrored. Import staged files with
    `python manage.py load_human_structures_bulk --skip-alphafold --skip-experimental
    --alphafill-dir PATH [--accession ...] [--datadir PATH]`. Supports flat and two-level
    rsync layouts, selects the newest numeric file version, skips existing nondeprecated links,
    and retries failures on rerun. Uses `AFILL_<accession>` / experiment `AFILL`, the same as
    the pilot and existing Structure tab. Loading parses atoms/residues: run the full pass on
    a compute node with SLURM, with access to the application DB/data, never directly on nodo0.
    Run `refresh_human_target_summary` after import to update cached coverage counts.
    Implemented locally; full-proteome download/import remains to be run and audited.
  - One-time bulk download: `scripts/cluster/fetch_human_proteome_bulk.sh`, run by hand over SSH on
    the login node (**neocranex**, not nodo0, not a SLURM compute node — mirrors FastTarget's
    one-time cluster setup), staging into the 2TB IT assigned there
    (`/storage/home/agutson/human_proteome_raw/` by default), kept separate from nodo0's
    `/data/targetpathogen/` RAID. Only the per-accession subset Django needs gets rsync'd down to
    nodo0 afterward.
  - Ingestion: `human_target/management/commands/import_human_proteome_bulk.py` — full-proteome
    analog of `import_human_curated_proteins`, streams the bulk JSON with `ijson` (don't
    `json.load()` a multi-GB file), reuses the same pure parsing helpers unchanged. Also writes a
    `bioseq.models.Biosequence` row per protein (`seq`/`length`) — needed so the bacterial-shared
    `dump_genome_proteins_fasta` command (for the eventual full-proteome LigQ_2 run) can find a
    sequence for human proteins at all; `import_human_curated_proteins` was patched to do the same.
  - **Structures — implemented**: `python manage.py load_human_structures_bulk --alphafold-dir
    /path/to/extracted [--accession ... | --accession-file PATH] [--datadir PATH] [--overwrite]
    [--workers 4] [--skip-alphafold] [--skip-experimental]`. AlphaFold-own-model: the extracted
    bulk archive (from `fetch_human_proteome_bulk.sh`) is indexed once by filename
    (`AF-<accession>-F1-model_v<N>.cif[.gz]`), not globbed per accession. Experimental PDB: one
    `files.rcsb.org/download/<id>.cif` fetch per *distinct* PDB id referenced by our proteins' own
    `cross_references_raw` (no extra call to look the IDs up), downloaded once and linked to every
    protein sharing it — reuses `load_af_model` unchanged, same as the pilot, including its
    re-link-on-existing-row branch (now load-bearing at this scale, since sharing one PDB entry
    across many human proteins is the common case, not the exception). That branch also exposed a
    latent bug in the pilot's own `_load_structures`: it skipped writing `ExperimentalStructureXref`
    whenever `load_af_model` raised `SystemExit` at all, which includes the *successful* re-link
    case — harmless at 10-protein pilot scale (PDB entries essentially never collide), would have
    silently dropped the xref for every protein past the first to share one at bulk scale. Fixed in
    both places: the xref write only skips on a real `CommandError`, not a re-link `SystemExit`.
    The experimental-PDB pass is the real bottleneck at full scale (~75K distinct PDB ids measured
    against the full proteome) — fetched with `--workers` parallel threads (`ThreadPoolExecutor`,
    default 4, same concurrency convention as the bacterial pipeline's own stage 15/17 workers) and
    resumable: a PDB id already loaded by an earlier (possibly interrupted) run is detected up front
    via a DB check and never re-downloaded, only re-linked for whichever proteins still need it —
    safe to stop (`kill`) and restart this command at any time without losing or re-fetching
    completed work. Running this inside a container that gets restarted (e.g. by `make up`/`make
    build` for an unrelated change) silently kills the job and wipes its `/tmp` log — always confirm
    with `ps aux | grep load_human_structures_bulk` after any container restart during a long run.
  - **LigQ_2 — implemented**: `python manage.py predict_human_ligq [--accession ...] [--chunk-size
    1000] [--max-chunks N] [--keep-output] [--include-unreviewed] [--dry-run]`. Reviewed proteins
    by default; `--include-unreviewed` adds TrEMBL entries after existing chunks. One SLURM job per
    chunk via `ligq_remote.run_ligq_job` (stage 24's runner minus the genome FASTA dump), loaded with
    `load_ligq_2_results`. Chunk membership is fixed in `data/human_ligq/chunk_NNN/proteins.fasta`;
    `FETCHED`/`LOADED` markers make it resumable, and a loaded chunk's output is deleted locally and
    on the cluster. Run it in its own container (a web redeploy kills `docker exec` jobs).
  - Full plan (phased, pause-and-review between each step, row-count/disk-footprint estimates):
    see the session's saved plan file.
