import json
import re
import urllib.request
from pathlib import Path

from django.core.management.base import BaseCommand

ENZYME_DAT_URL = "https://ftp.expasy.org/databases/enzyme/enzyme.dat"
ENZCLASS_TXT_URL = "https://ftp.expasy.org/databases/enzyme/enzclass.txt"
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "ec_hierarchy_labels.json"

CLASS_LABELS = {
    "1": "Oxidoreductases",
    "2": "Transferases",
    "3": "Hydrolases",
    "4": "Lyases",
    "5": "Isomerases",
    "6": "Ligases",
    "7": "Translocases",
}


def _download(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_enzyme_dat(text):
    """Parse ExPASy enzyme.dat into a dict of {accession: name} for level-4 enzymes."""
    entries = {}
    current_id = None
    current_de_lines = []

    for line in text.splitlines():
        if line.startswith("ID   "):
            current_id = line[5:].strip()
            current_de_lines = []
        elif line.startswith("DE   "):
            current_de_lines.append(line[5:].strip())
        elif line.startswith("//"):
            if current_id and current_de_lines:
                name = " ".join(current_de_lines)
                if name.endswith("."):
                    name = name[:-1]
                if not name.startswith("Transferred entry") and not name.startswith("Deleted entry"):
                    entries[current_id] = name
            current_id = None
            current_de_lines = []

    return entries


def parse_enzclass_txt(text):
    """Parse ExPASy enzclass.txt into subclass and sub-subclass label dicts.

    Each line looks like:
      1. 1.-.-  Oxidoreductases acting on ...
      1. 1. 1.- ...
    The accession is extracted by taking the dot-separated numeric parts
    before the first dash.
    """
    subclass_labels = {}
    subsubclass_labels = {}

    pattern = re.compile(
        r"^\s*(\d+)\.\s*(\d+)\.\s*(\d+|-)\.\s*-\s+(.+?)\s*\.?\s*$"
    )

    for line in text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        c1, c2, c3, name = match.groups()
        name = name.strip().rstrip(".")

        if c3 == "-":
            accession = f"{c1}.{c2}"
            subclass_labels[accession] = name
        else:
            accession = f"{c1}.{c2}.{c3}"
            subsubclass_labels[accession] = name

    return subclass_labels, subsubclass_labels


def build_hierarchy_labels(enzyme_names, subclass_labels, subsubclass_labels):
    """Combine all EC hierarchy levels into the output JSON structure."""
    return {
        "class_labels": CLASS_LABELS,
        "subclass_labels": subclass_labels,
        "subsubclass_labels": subsubclass_labels,
        "enzyme_names": enzyme_names,
    }


class Command(BaseCommand):
    help = (
        "Download the official EC nomenclature from ExPASy (enzyme.dat + "
        "enzclass.txt) and rebuild tpweb/data/ec_hierarchy_labels.json with "
        "complete labels for all hierarchy levels including individual enzymes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default=str(OUTPUT_PATH),
            help=f"Output JSON path (default: {OUTPUT_PATH})",
        )

    def handle(self, *args, **options):
        output = Path(options["output"])

        self.stdout.write(f"Downloading {ENZYME_DAT_URL} ...")
        enzyme_dat_text = _download(ENZYME_DAT_URL)
        self.stdout.write(f"  Downloaded {len(enzyme_dat_text):,} bytes")

        enzyme_names = parse_enzyme_dat(enzyme_dat_text)
        self.stdout.write(f"  Parsed {len(enzyme_names):,} enzyme entries (level 4)")

        self.stdout.write(f"Downloading {ENZCLASS_TXT_URL} ...")
        enzclass_text = _download(ENZCLASS_TXT_URL)
        self.stdout.write(f"  Downloaded {len(enzclass_text):,} bytes")

        subclass_labels, subsubclass_labels = parse_enzclass_txt(enzclass_text)
        self.stdout.write(
            f"  Parsed {len(subclass_labels)} subclasses (level 2), "
            f"{len(subsubclass_labels)} sub-subclasses (level 3)"
        )

        hierarchy = build_hierarchy_labels(enzyme_names, subclass_labels, subsubclass_labels)
        stats = {k: len(v) for k, v in hierarchy.items()}
        self.stdout.write(f"  Hierarchy totals: {stats}")

        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as f:
            json.dump(hierarchy, f, indent=2, ensure_ascii=False)
            f.write("\n")

        self.stdout.write(self.style.SUCCESS(f"Wrote {output}"))
