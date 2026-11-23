"""Recover numeric counts discarded by the historical hit/no_hit adapter."""

from pathlib import Path
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.services.microbiome_counts import read_counts, read_normalization
from tpweb.services.structure_files import compute_folder_path
from tpweb.management.commands.index_p2rank_scores import has_value


class Command(BaseCommand):
    help = (
        "Recover missing microbiome counts from original scoped TSVs. No normalization is inferred."
    )

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument("--counts-tsv")
        parser.add_argument("--include-normalization", action="store_true")
        parser.add_argument("--datadir", default="/app/targetpathogenweb/data")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        genome = options["genome_name"]
        proteins = dict(
            Bioentry.objects.filter(
                biodatabase__name=genome + Biodatabase.PROT_POSTFIX,
            ).values_list("accession", "pk")
        )
        if not proteins:
            raise CommandError("Genome has no loaded proteins.")
        if options.get("counts_tsv"):
            path = Path(options["counts_tsv"])
        else:
            folder = Path(compute_folder_path(options["datadir"], genome))
            candidates = [
                root / subfolder / "gut_microbiome_offtarget_counts.tsv"
                for root in (
                    folder / "fasttarget_remote" / "output",
                    Path("/app/fasttarget/organism") / genome,
                )
                for subfolder in ("tables", "offtarget", "offtarget/species_blast_results")
            ]
            path = next((candidate for candidate in candidates if candidate.is_file()), None)
            if path is None:
                self.stdout.write(
                    "Microbiome counts: no original counts TSV found; nothing inferred or changed."
                )
                return
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                counts = read_counts(handle, known_loci=proteins)
            sources = {"gut_microbiome_offtarget_counts": counts}
            if options.get("include_normalization"):
                if set(counts) != set(proteins):
                    raise ValueError(
                        "Normalization recovery requires counts for the full proteome."
                    )
                with (
                    (path.parent / "gut_microbiome_genomes_analyzed.tsv").open(
                        encoding="utf-8-sig", newline=""
                    ) as totals_handle,
                    (path.parent / "gut_microbiome_offtarget_norm.tsv").open(
                        encoding="utf-8-sig", newline=""
                    ) as fractions_handle,
                ):
                    totals, fractions = read_normalization(counts, totals_handle, fractions_handle)
                sources.update(
                    gut_microbiome_genomes_analyzed=totals,
                    gut_microbiome_offtarget_norm=fractions,
                )
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if not options["apply"] or not counts:
            self.stdout.write(
                f"Validated microbiome counts: {len(counts)} proteins from {path}; no data changed."
            )
            return
        from tpweb.services.score_params import ensure_system_score_param

        with transaction.atomic():
            params = {name: ensure_system_score_param(name) for name in sources}
            rows = ScoreParamValue.objects.select_for_update().filter(
                bioentry_id__in=proteins.values(),
                score_param__in=params.values(),
            )
            existing = {(row.bioentry_id, row.score_param_id): row for row in rows}
            creates, updates = [], []
            preserved = 0
            conflicts = 0
            for gene in counts:
                protein_id = proteins[gene]
                # Do not attach a denominator/fraction from another source to curated counts.
                if options.get("include_normalization"):
                    conflict = False
                    for name, param in params.items():
                        row = existing.get((protein_id, param.pk))
                        if row is not None and has_value(row):
                            try:
                                raw = (
                                    row.numeric_value
                                    if row.numeric_value is not None
                                    else row.value
                                )
                                value = Decimal(str(raw))
                                if not value.is_finite() or abs(
                                    value - Decimal(str(sources[name][gene]))
                                ) > Decimal("1e-12"):
                                    conflict = True
                            except (InvalidOperation, ValueError):
                                conflict = True
                    if conflict:
                        conflicts += 1
                        continue
                for name, param in params.items():
                    count = sources[name][gene]
                    row = existing.get((protein_id, param.pk))
                    if row is not None and has_value(row):
                        preserved += 1
                    elif row is None:
                        creates.append(
                            ScoreParamValue(
                                bioentry_id=protein_id,
                                score_param=param,
                                value=str(count),
                                numeric_value=count,
                            )
                        )
                    else:
                        row.value, row.numeric_value = str(count), count
                        updates.append(row)
            ScoreParamValue.objects.bulk_create(creates, batch_size=500)
            ScoreParamValue.objects.bulk_update(updates, ["value", "numeric_value"], batch_size=500)
        self.stdout.write(
            f"Microbiome values recovered: {len(creates) + len(updates)}; "
            f"existing values preserved: {preserved}; conflicting proteins skipped: {conflicts}; "
            f"validated columns: {', '.join(sources)}; source: {path}. "
            "No denominator or normalized signal was inferred."
        )
