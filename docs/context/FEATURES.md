# Feature notes

Moved out of `CLAUDE.md` so it only loads when needed.

## Cross-strain identical-sequence links
Several Klebsiella strains' genomes (ST11/VA569, KP13, ATCC43816 today) are uploaded to Target
separately, but a hand-curated TSV (produced outside the app, by BLAST/sequence-identity
comparison) says which proteins across them are 100% identical at the amino-acid level — e.g.
useful so a structure predicted for one strain's copy is visibly cross-linked from the other
strains' identical copies, instead of silently redone per-strain.
- **Live shared evidence**: `tpweb/services/shared_sequence_evidence.py` reads the
  original evidence rows through `IdenticalSequenceGroup`/`IdenticalSequenceMember`.
  KP13 and ATCC43816 are the curated sources, ahead of a recipient's automatic
  results. Structures/pockets share the original PDB object and source file;
  EC/GO/UniProt, sequence-specific scores, and ligands reuse their source records.
  Conservation (core and soft core) is shared too; only metabolic context (network
  topology and the curated metabolic priority) stays on each strain.
  Missing curated fields fall back to local results; pocket score/structure/ID
  bundles remain on the same source. Conflicting curated scalar values surface
  a notice with deterministic KP13 precedence. Source-genome and custom-column
  permissions are checked before sharing. The protein page, protein table,
  ranking, filters, structure viewer and downloads resolve this live evidence.
  No evidence rows are copied, so source edits appear on the next request.
  Structures are available in both directions, including uploads on VA569 or
  a later strain. When curated evidence is absent, local evidence takes
  precedence over other accessible identical occurrences.
- **Members don't require the sibling genome to exist yet** — `bioentry` starts null at import
  time. `python manage.py load_identical_sequence_groups <tsv> [--overwrite]` accepts
  `id_representativo` and `identicos_en_otras_cepas` (optional leading row ID).
  Representatives can come from any strain: MO417/KP13/VK055 prefixes determine the
  label, and VA569 is normalized to ST11_VA569. `--representative-strain` is only a
  fallback for unknown prefixes. Once a strain's genome finishes loading, run `python manage.py
  backfill_identical_sequence_links <internal_accession> <strain_label>` to resolve that
  strain's `bioentry` FKs by matching `locus_tag` against `Bioentry.accession` in its `_prots`
  Biodatabase — safe to re-run, only touches still-unlinked rows. `--all-loaded` can
  resolve all strains when each matches exactly one loaded proteome; ambiguous
  genomes require explicit arguments. Backfill rejects groups whose loaded sequences differ.
- `sync_genome_metadata` calls backfill with `--match-sequences` after loading
  a genome, covering both direct and Parsl pipelines at stage 3.
  A new strain can join an existing table-defined group by exact sequence,
  provided its loaded members agree and the sequence identifies one group.
  Original KP13/ATCC43816/VA569 occurrences follow Sol's explicit table rows.
- **Cleanup**: deleting a genome's workspace does not currently prune its
  `IdenticalSequenceMember.bioentry` links back to null — `on_delete=SET_NULL` means a deleted
  Bioentry just leaves the FK null again next time (effectively self-healing on a future
  `backfill_identical_sequence_links` run), not a dangling reference.

## Metabolic pathway integration
Incorporates genome-scale metabolic network topology (BioCyc/Pathway Tools MetaFlux) into
target analysis: which reactions/pathways a protein participates in, how central/bottleneck it
is (betweenness centrality, chokepoints), and a Reactome-style network diagram on the protein
detail page.
- **Not an in-app pipeline stage.** Like the Gates-Targets import, this is a manual/external
  step today — run `load_metabolism` (or `import_external_results` with the extra flags below)
  after the genome's GBK is loaded. Wiring it into `run_pipeline_direct.py` as a numbered stage
  is future work, once this becomes routine per-genome output.
- **Inputs** (produced by the vendored `fasttarget/ftscripts/pathways.py:run_metabolism_ptools`,
  outside the Django app, typically on a machine running Pathway Tools):
  - A MetaFlux SBML export (reactions, EC numbers, KEGG reaction IDs where available,
    gene-reaction associations).
  - A per-gene results TSV with `gene`, `PTOOLS_betweenness_centrality`, `PTOOLS_edges`,
    `PTOOLS_producing_chokepoints`, `PTOOLS_consuming_chokepoints`, `PTOOLS_both_chokepoints`.
  - `network.sif` — the reaction-reaction adjacency graph used to compute those metrics.
- **Models**: `tpweb/models/Metabolism.py` — `MetabolicPathway` (KEGG or BioCyc, global
  reference), `MetabolicReaction` (per-genome, keyed by BioCyc frame id), `GeneReactionLink`
  (`Bioentry` ↔ `MetabolicReaction`, carries `chokepoint_role`), `MetabolicReactionEdge`
  (per-genome reaction-reaction adjacency, powers the diagram).
- **Ingestion**: `python manage.py load_metabolism <genome_name> --sbml PATH
  --metabolic-results-tsv PATH --network-sif PATH [--overwrite] [--dry-run]`. Also reachable via
  `import_external_results` with the same three flags as an additional step. Centrality/chokepoint
  scalars feed the existing `ScoreParam`/`ScoreParamValue` system (`PTOOLS_betweenness_centrality`,
  `metabolic_chokepoint`) — no separate UI plumbing needed for filtering/CSV export/`ScoreFormula`
  prioritization weights.
- **Pathway naming**: KEGG pathway membership is derived from the KEGG reaction IDs already
  embedded in the SBML annotations, via a bundled static reference file
  `tpweb/data/kegg_reaction_pathways.json` (fetch/refresh with `python manage.py
  fetch_kegg_pathway_map`, which needs internet access to `rest.kegg.org` — this is global
  reference chemistry, not organism-specific, so it's fetched once and committed, not per genome).
  If that file is missing, reactions still import fine, just without pathway chips. A BioCyc
  SmartTable source (`MetabolicPathway.source = "BIOCYC"`) is modeled but not yet implemented —
  needs a real sample export to validate the parser against.
- **Visualization**: protein detail page, "Metabolic context" section — reaction list, pathway
  chips, centrality percentile, chokepoint badge, and a Cytoscape.js ego-network diagram (`static/js/pages/metabolic-network.js`,
  data from `MetabolismNetworkView` at `/protein/<id>/metabolic-network`) colored by chokepoint
  role, clickable to jump to neighboring targets that share a reaction.
- **Cleanup**: `genome_uploads._delete_workspace_biodatabases` deletes `MetabolicReaction` rows
  scoped by `genome_accession` (a string, not a FK to `Biodatabase`) alongside the genome's
  `Biodatabase` rows.

## Access control: login wall vs. IP blocking
Two separate layers, both in `tpweb/middleware/access_control.py`:
- **`LoginRequiredMiddleware`**: gates every path behind login except `EXEMPT_PATH_PREFIXES`
  (`/accounts/`, `/health/*`, `/robots.txt`). Anonymous requests get redirected to login, not
  denied outright — this is what the Activity dashboard's "Blocked by login wall" numbers reflect.
- **`BlockedIPMiddleware`**: a hard 403 for specific IPs in the `BlockedIP` model (`tpweb/models/BlockedIP.py`),
  with no exemptions at all (not even `/robots.txt`). Sits *before* `LoginRequiredMiddleware` in
  `settings.MIDDLEWARE` so a blocked IP never reaches the login-wall check. The blocked-IP set is
  cached (`tpweb/services/ip_blocking.py`, key `Target:blocked_ips`, 60s TTL, explicitly invalidated
  by `block_ip`/`unblock_ip`) rather than queried per request.
- **Auto-blocking**: the same middleware also blocks on first sight, no staff action needed — an
  anonymous request to a non-exempt path from a User-Agent classified `AI crawler` or `Generic bot`
  (see `AUTO_BLOCK_BOT_LABELS` / `classify_bot` in `tpweb/services/bot_detection.py`, shared with
  the dashboard's own bot classification) gets a `BlockedIP` row (`reason="auto: <label>"`,
  `blocked_by=None`) and a 403 right then. Deliberately excludes `HTTP client` (could be an internal
  monitor/test) and `Search crawler` (Googlebot/Bingbot; harmless against an already-private site).
  A bot that only ever requests `/robots.txt` is left alone — auto-block only triggers on a
  non-exempt path, same definition `_blocked_queryset` in `activity_dashboard.py` uses.
- **Fully automatic, no manual UI**: `ActivityDashboardView` is read-only (GET only, gated by
  `tpweb.can_view_activity`) — its "Blocked IPs" panel just lists current blocks (IP, blocked by,
  reason, since). There's no block/unblock button anywhere on the dashboard by design; the only way
  to manually block or unblock an IP is the Django admin (`BlockedIP`). `BlockedIPAdmin.delete_model`/
  `delete_queryset` route deletion through `unblock_ip()` rather than a plain `obj.delete()`, so
  deleting a row there also busts the middleware's cached blocked-IP set immediately instead of
  leaving that IP wrongly 403'd for up to the cache's TTL.

### "Only me" is private from admins too
- A researcher's formulas and uploaded columns set to "Only me" are visible to their owner alone.
  No superuser bypass exists in the data paths (`custom_param_sharing`, `protein_formula`); keep it
  that way.
- Settings → Researchers (superuser) shows per-person counts and only the *shared* items;
  private ones are counted, never named (`_researcher_summaries` in `SettingsView.py`).
- The Django admin hides every researcher-owned ScoreParam/Value/Option/Share and
  ScoreFormula/Param (`tpweb/admin/private_data.py`); it lists platform data only.
- Not encryption: anyone with direct DB or server access can still read the rows.

## Ligand synthesis routes
- Ligand page (`/binder/<id>`) "Synthesis routes": patent reactions whose product is the ligand
  (exact, canonical SMILES) or an analog (Morgan r2, Tanimoto ≥ 0.45, only when no exact hit).
  PDB/ChEMBL ligands only, bacterial and human alike. Stored in `LigandReaction`, keyed by
  sha256 of `Binders.smiles` as stored (no web-side canonicalization, so RDKit versions can differ).
- Datasets on the cluster, `/storage/home/agutson/reaction_datasets/`: `uspto50k/data_processed.csv`
  (USPTO-50K with Schneider classes, from connorcoley/retrosim) and
  `paroutes2/selected_reactions_all.csv` (PaRoutes v2, Zenodo 7341155, ~3.2 GB).
- Refresh: `python manage.py predict_ligand_reactions` (as root, in its own container) exports the
  distinct SMILES, runs `scripts/cluster/match_ligand_reactions.py` in one SLURM job (LigQ_2 conda
  env, 12 CPUs / 48G via `TPW_REACTIONS_SLURM_*`), copies `routes.tsv.gz` back and loads it with
  `load_ligand_reactions` (full replace). `--load-only` reloads the last file.
