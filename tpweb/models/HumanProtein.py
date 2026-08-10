"""Human Targets — per-protein content for the human curated-protein set.

Unlike the bacteria side, human proteins are NOT genome-upload/pipeline
entities (see CLAUDE.md "Human Targets" section): one small, fixed, already
-known protein set with several different analyses layered on top over time,
rather than "upload a genome, run the same pipeline, repeat." This model
holds the parsed UniProt content for the Overview/Function/Sequence/
Cross-refs tabs. It deliberately favors JSON fields over full normalization
at this scale (10 curated proteins) -- same pattern as
`CuratedImportJob.summary_json` / `PipelineRun.payload` elsewhere in this
app for irregular per-record data.
"""

from django.db import models

from bioseq.models.Bioentry import Bioentry


class HumanProtein(models.Model):
    bioentry = models.OneToOneField(
        Bioentry, on_delete=models.CASCADE, related_name="human_protein"
    )
    uniprot_accession = models.CharField(max_length=32, db_index=True, unique=True)

    # Scalar fields -- Overview quick-fact tiles, list page columns.
    protein_name = models.CharField(max_length=512, blank=True, default="")
    gene_symbol = models.CharField(max_length=64, blank=True, default="")
    organism_name = models.CharField(max_length=255, blank=True, default="")
    taxon_id = models.IntegerField(null=True, blank=True)
    sequence_length = models.IntegerField(null=True, blank=True)
    mass_da = models.IntegerField(null=True, blank=True)
    annotation_score = models.FloatField(null=True, blank=True)
    entry_version = models.IntegerField(null=True, blank=True)
    is_reviewed = models.BooleanField(default=True)
    chromosome = models.CharField(max_length=64, blank=True, default="")

    # Rich per-tab content, parsed from <ACC>_full.json at ingest time.
    lineage = models.JSONField(default=list, blank=True)
    keywords = models.JSONField(default=list, blank=True)
    subcellular_locations = models.JSONField(default=list, blank=True)
    function_text = models.TextField(blank=True, default="")
    caution_text = models.TextField(blank=True, default="")
    subunit_text = models.TextField(blank=True, default="")
    polymorphism_text = models.TextField(blank=True, default="")
    # Captured at ingest for future use; the Diseases tab itself is out of
    # scope for this pass (see CLAUDE.md "Human Targets" non-goals).
    disease_comments = models.JSONField(default=list, blank=True)
    catalytic_activity = models.JSONField(default=list, blank=True)
    go_terms = models.JSONField(default=list, blank=True)
    publications = models.JSONField(default=list, blank=True)
    features_raw = models.JSONField(default=list, blank=True)
    cross_references_raw = models.JSONField(default=list, blank=True)
    sequence = models.TextField(blank=True, default="")

    # Full original record, kept as a fallback/audit trail.
    uniprot_raw = models.JSONField(default=dict, blank=True)
    ingest_source_path = models.CharField(max_length=1024, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["gene_symbol", "uniprot_accession"]

    def __str__(self):
        return f"{self.uniprot_accession} ({self.gene_symbol or self.protein_name})"
