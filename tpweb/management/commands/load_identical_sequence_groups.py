import csv
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tpweb.models import IdenticalSequenceGroup, IdenticalSequenceMember

# "MO417_00005 (WHR12791.1)" -> ("MO417_00005", "WHR12791.1")
_ID_RE = re.compile(r"^\s*(?P<locus_tag>\S+)\s*\(\s*(?P<accession>[^)]*)\s*\)\s*$")


def _parse_id(raw):
    raw = (raw or "").strip()
    if not raw or raw == "-":
        return None
    match = _ID_RE.match(raw)
    if match is None:
        # No parenthesized accession -- still usable as a bare locus tag.
        return {"locus_tag": raw, "protein_accession": ""}
    return {
        "locus_tag": match.group("locus_tag"),
        "protein_accession": match.group("accession").strip(),
    }


def _parse_matches(raw):
    """ "KP13: KP13_07341 (ANJ86556.1); ATCC43816: VK055_3362 (AIK81919.1)" ->
    [{"strain_label": "KP13", "locus_tag": ..., "protein_accession": ...}, ...].
    "-" or empty means no identical match in any other strain."""
    raw = (raw or "").strip()
    if not raw or raw == "-":
        return []
    matches = []
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        strain_label, _sep, rest = chunk.partition(":")
        parsed = _parse_id(rest)
        if parsed is None:
            continue
        parsed["strain_label"] = strain_label.strip()
        matches.append(parsed)
    return matches


class Command(BaseCommand):
    help = (
        "Imports a hand-curated TSV of 100%% sequence-identical proteins across "
        "Klebsiella strains (columns: row id, representative id "
        "'locus_tag (accession)', and 'STRAIN: locus_tag (accession); ...' or '-'). "
        "Creates an IdenticalSequenceGroup + IdenticalSequenceMember per matched row -- "
        "bioentry links are resolved later by backfill_identical_sequence_links, once "
        "each strain's genome is loaded. Safe to re-run with --overwrite."
    )

    def add_arguments(self, parser):
        parser.add_argument("tsv_path")
        parser.add_argument(
            "--representative-strain",
            required=True,
            help="Strain label for the TSV's representative-id column, e.g. ST11_VA569.",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help=(
                "Delete every existing IdenticalSequenceGroup tagged with this "
                "source file's note before importing (idempotent re-runs)."
            ),
        )

    def handle(self, *args, **options):
        tsv_path = options["tsv_path"]
        representative_strain = options["representative_strain"].strip()
        source_note = tsv_path.replace("\\", "/").rsplit("/", 1)[-1]

        try:
            handle = open(tsv_path, newline="", encoding="utf-8")
        except OSError as exc:
            raise CommandError(f"Unable to open {tsv_path}: {exc}") from exc

        with handle:
            reader = csv.reader(handle, delimiter="\t")
            rows = list(reader)

        if not rows:
            raise CommandError(f"{tsv_path} is empty")
        rows = rows[1:]  # header: id, id_representativo, identicos_en_otras_cepas

        if options["overwrite"]:
            deleted, _ = IdenticalSequenceGroup.objects.filter(source_note=source_note).delete()
            if deleted:
                self.stdout.write(f"Removed {deleted} existing rows for {source_note}.")

        created_groups = 0
        created_members = 0
        skipped_no_match = 0
        skipped_duplicate = 0

        with transaction.atomic():
            for row in rows:
                if len(row) < 2:
                    continue
                representative_raw = row[1] if len(row) > 1 else ""
                matches_raw = row[2] if len(row) > 2 else ""

                representative = _parse_id(representative_raw)
                if representative is None:
                    continue
                matches = _parse_matches(matches_raw)
                if not matches:
                    skipped_no_match += 1
                    continue

                members = [
                    {
                        "strain_label": representative_strain,
                        "locus_tag": representative["locus_tag"],
                        "protein_accession": representative["protein_accession"],
                    },
                    *matches,
                ]

                existing = set(
                    IdenticalSequenceMember.objects.filter(
                        strain_label__in=[m["strain_label"] for m in members],
                        locus_tag__in=[m["locus_tag"] for m in members],
                    ).values_list("strain_label", "locus_tag")
                )
                members = [
                    m for m in members if (m["strain_label"], m["locus_tag"]) not in existing
                ]
                if len(members) < 2:
                    # Nothing new to link, or only one side of the group
                    # survived a prior partial import -- skip rather than
                    # create a one-member "group" that links to nothing.
                    skipped_duplicate += 1
                    continue

                group = IdenticalSequenceGroup.objects.create(source_note=source_note)
                created_groups += 1
                IdenticalSequenceMember.objects.bulk_create(
                    [IdenticalSequenceMember(group=group, **m) for m in members]
                )
                created_members += len(members)

        self.stdout.write(
            f"Created {created_groups} groups ({created_members} members). "
            f"Skipped {skipped_no_match} rows with no cross-strain match, "
            f"{skipped_duplicate} rows already imported."
        )
