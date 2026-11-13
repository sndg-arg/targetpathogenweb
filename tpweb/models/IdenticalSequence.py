from django.db import models

from bioseq.models.Bioentry import Bioentry


class IdenticalSequenceGroup(models.Model):
    """A set of proteins across different genomes (usually different strains
    of the same species) whose amino-acid sequences are 100% identical --
    seeded from a hand-curated TSV (see management command
    load_identical_sequence_groups) rather than computed in-app. Membership
    defines the original strain occurrences. New strains may join an existing
    group only after an exact current-sequence comparison.

    Shared evidence is read live from KP13/ATCC43816 through this group;
    evidence rows are not copied. Bioentry remains strain-specific so that
    conservation and metabolic context never propagate between strains."""

    created_at = models.DateTimeField(auto_now_add=True)
    source_note = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Where this group came from, e.g. the imported TSV filename.",
    )


class IdenticalSequenceMember(models.Model):
    """One strain's copy of a sequence shared by `group`.

    `bioentry` starts null at import time -- the TSV is produced
    independently of whether every strain's genome has finished loading in
    Target yet (see CLAUDE.md's Klebsiella cross-strain note). A separate
    `backfill_identical_sequence_links` management command resolves it once
    that strain's genome is loaded, by matching `locus_tag` against
    Bioentry.accession within that genome's `_prots` Biodatabase."""

    group = models.ForeignKey(
        IdenticalSequenceGroup, related_name="members", on_delete=models.CASCADE
    )
    strain_label = models.CharField(max_length=64)
    locus_tag = models.CharField(max_length=128)
    protein_accession = models.CharField(max_length=128, blank=True, default="")
    bioentry = models.ForeignKey(
        Bioentry,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="identical_sequence_memberships",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("strain_label", "locus_tag"),
                name="tpweb_identicalseqmember_strain_locus_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["bioentry"]),
        ]

    def __str__(self):
        return f"{self.strain_label}:{self.locus_tag}"
