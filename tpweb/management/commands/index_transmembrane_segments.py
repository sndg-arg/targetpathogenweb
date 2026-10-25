"""Count each protein's transmembrane segments from the InterProScan topology
predictions already loaded as sequence features (Phobius / TMHMM), and store
the count as the "transmembrane_segments" ScoreParamValue so it can be shown,
sorted, filtered and scored in the protein list. Overlapping predictions from
the two predictors count once, as on the protein page's topology drawing.

Proteins of a genome with topology predictions but none for them get 0.
Re-running replaces the genome's previous counts.

Usage: python manage.py index_transmembrane_segments public__KpATCC43816 [more genomes]
"""

from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from bioseq.models.Seqfeature import Seqfeature
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.services.protein_list import TM_PREDICTOR_DBS, TM_SEGMENT_ID_RE
from tpweb.services.score_params import ensure_system_score_param
from tpweb.services.topology_diagram import count_transmembrane_segments


def segment_counts(rows):
    """rows: (bioentry_id, start, end) per predicted segment -> {bioentry_id: count}."""
    segments = defaultdict(list)
    for bioentry_id, start, end in rows:
        if start is None or end is None:
            continue
        segments[bioentry_id].append({"start": start, "end": end, "kind": "membrane"})
    return {
        bioentry_id: count_transmembrane_segments(items) for bioentry_id, items in segments.items()
    }


class Command(BaseCommand):
    help = "Stores each protein's predicted transmembrane segment count (Phobius / TMHMM)."

    def add_arguments(self, parser):
        parser.add_argument("accessions", nargs="+", help="internal genome accession(s)")

    def handle(self, *args, **options):
        score_param = ensure_system_score_param("transmembrane_segments")
        for accession in options["accessions"]:
            genome = Biodatabase.objects.filter(name=accession + Biodatabase.PROT_POSTFIX).first()
            if genome is None:
                raise CommandError(f"genome '{accession}' does not exist")

            predicted = Seqfeature.objects.filter(
                bioentry__biodatabase=genome,
                type_term__ontology__name__in=TM_PREDICTOR_DBS,
            )
            if not predicted.exists():
                self.stderr.write(
                    f"{accession}: no Phobius/TMHMM predictions loaded (run InterProScan first), skipped"
                )
                continue
            counts = segment_counts(
                predicted.filter(type_term__identifier__iregex=TM_SEGMENT_ID_RE).values_list(
                    "bioentry_id", "locations__start_pos", "locations__end_pos"
                )
            )
            protein_ids = list(
                Bioentry.objects.filter(biodatabase=genome).values_list("pk", flat=True)
            )
            with transaction.atomic():
                ScoreParamValue.objects.filter(
                    bioentry__biodatabase=genome, score_param=score_param
                ).delete()
                ScoreParamValue.objects.bulk_create(
                    [
                        ScoreParamValue(
                            score_param=score_param,
                            bioentry_id=protein_id,
                            value=str(counts.get(protein_id, 0)),
                            numeric_value=float(counts.get(protein_id, 0)),
                        )
                        for protein_id in protein_ids
                    ],
                    batch_size=2000,
                )
            membrane = sum(1 for protein_id in protein_ids if counts.get(protein_id))
            self.stdout.write(
                f"{accession}: {len(protein_ids)} proteins, {membrane} with transmembrane segments"
            )
