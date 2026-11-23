import csv
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tpweb.models import IdenticalSequenceGroup, IdenticalSequenceMember

# "MO417_00005 (WHR12791.1)" -> ("MO417_00005", "WHR12791.1")
_ID_RE = re.compile(r"^\s*(?P<locus_tag>\S+)\s*\(\s*(?P<accession>[^)]*)\s*\)\s*$")
_STRAIN_PREFIXES = {"MO417_": "ST11_VA569", "KP13_": "KP13", "VK055_": "ATCC43816"}


def _strain_label(label):
    label = label.strip().upper()
    return "ST11_VA569" if label in {"VA569", "ST11/VA569", "ST11_VA569"} else label


def _representative_strain(locus_tag, fallback):
    for prefix, label in _STRAIN_PREFIXES.items():
        if locus_tag.startswith(prefix):
            return label
    if fallback:
        return _strain_label(fallback)
    raise CommandError(f"Cannot infer strain for {locus_tag}; supply --representative-strain")


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
        if not _sep:
            raise CommandError(f"Missing strain label in match: {chunk}")
        parsed = _parse_id(rest)
        if parsed is None:
            continue
        parsed["strain_label"] = _strain_label(strain_label)
        inferred = _representative_strain(parsed["locus_tag"], parsed["strain_label"])
        if inferred != parsed["strain_label"]:
            raise CommandError(f"Strain/locus mismatch: {chunk}")
        matches.append(parsed)
    return matches


def _table_members(rows, fallback=None):
    """Accept Sol's two-column TSV and the legacy version with a leading row ID."""
    header = [column.strip().lstrip("\ufeff") for column in rows[0]]
    try:
        rep_index = header.index("id_representativo")
        match_index = header.index("identicos_en_otras_cepas")
    except ValueError as exc:
        raise CommandError(
            "Expected id_representativo and identicos_en_otras_cepas headers"
        ) from exc
    groups = []
    skipped = 0
    seen = set()
    for number, row in enumerate(rows[1:], 2):
        if not row or not any(value.strip() for value in row):
            continue
        if len(row) <= max(rep_index, match_index):
            raise CommandError(f"Incomplete TSV row {number}")
        representative = _parse_id(row[rep_index])
        if representative is None:
            raise CommandError(f"Missing representative in TSV row {number}")
        matches = _parse_matches(row[match_index])
        if not matches:
            skipped += 1
            continue
        members = [
            {
                **representative,
                "strain_label": _representative_strain(representative["locus_tag"], fallback),
            },
            *matches,
        ]
        keys = [(m["strain_label"], m["locus_tag"]) for m in members]
        if len(set(keys)) != len(keys) or seen.intersection(keys):
            raise CommandError(f"Repeated protein in TSV groups at row {number}")
        seen.update(keys)
        groups.append(members)
    return groups, skipped


class Command(BaseCommand):
    help = (
        "Imports a hand-curated TSV of 100%% sequence-identical proteins across "
        "Klebsiella strains (id_representativo and identicos_en_otras_cepas; "
        "an optional leading row id is accepted). Known locus prefixes determine the strain. "
        "Creates an IdenticalSequenceGroup + IdenticalSequenceMember per matched row -- "
        "bioentry links are resolved later by backfill_identical_sequence_links, once "
        "each strain's genome is loaded. Safe to re-run with --overwrite."
    )

    def add_arguments(self, parser):
        parser.add_argument("tsv_path")
        parser.add_argument(
            "--representative-strain",
            default="",
            help="Fallback label for unknown locus prefixes; known Klebsiella loci are inferred.",
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
        groups, skipped_no_match = _table_members(rows, representative_strain)

        created_groups = 0
        created_members = 0
        skipped_duplicate = 0

        with transaction.atomic():
            if options["overwrite"]:
                deleted, _ = IdenticalSequenceGroup.objects.filter(source_note=source_note).delete()
                if deleted:
                    self.stdout.write(f"Removed {deleted} existing rows for {source_note}.")
            for members in groups:
                existing = set(
                    IdenticalSequenceMember.objects.filter(
                        strain_label__in=[m["strain_label"] for m in members],
                        locus_tag__in=[m["locus_tag"] for m in members],
                    ).values_list("strain_label", "locus_tag")
                )
                present = [m for m in members if (m["strain_label"], m["locus_tag"]) in existing]
                if present and len(present) != len(members):
                    raise CommandError("Partially imported group; re-run with --overwrite")
                if present:
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
