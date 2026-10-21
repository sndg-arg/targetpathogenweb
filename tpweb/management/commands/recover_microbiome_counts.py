"""Recover numeric counts discarded by the historical hit/no_hit adapter."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.services.microbiome_counts import read_counts
from tpweb.services.structure_files import compute_folder_path
from tpweb.management.commands.index_p2rank_scores import has_value


class Command(BaseCommand):
    help = (
        "Recover missing microbiome counts from original scoped TSVs. No normalization is inferred."
    )

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument("--counts-tsv")
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
                for subfolder in ("tables", "offtarget")
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
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if not options["apply"] or not counts:
            self.stdout.write(
                f"Validated microbiome counts: {len(counts)} proteins from {path}; no data changed."
            )
            return
        from tpweb.services.score_params import ensure_system_score_param

        with transaction.atomic():
            param = ensure_system_score_param("gut_microbiome_offtarget_counts")
            rows = ScoreParamValue.objects.select_for_update().filter(
                bioentry_id__in=proteins.values(),
                score_param=param,
            )
            existing = {row.bioentry_id: row for row in rows}
            creates, updates = [], []
            preserved = 0
            for gene, count in counts.items():
                protein_id = proteins[gene]
                row = existing.get(protein_id)
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
            f"Microbiome counts recovered: {len(creates) + len(updates)}; "
            f"existing values preserved: {preserved}; source: {path}. "
            "Analyzed-genome denominator and normalized signal were not inferred."
        )
