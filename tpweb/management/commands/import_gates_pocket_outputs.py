import csv
import os
import re

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.management.commands import backfill_pockets_experimental as bpe
from tpweb.management.commands.import_selected_pdb_pocket_results import (
    fallback_fpocket_to_json,
    fpocket_json_is_empty,
)
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB, PDBResidueSet


FP_RESIDUE_SET = "FPocketPocket"
P2_RESIDUE_SET = "P2RankPocket"


def clean(value):
    value = str(value or "").strip()
    if value.lower() in {"", "nan", "none", "null"}:
        return ""
    return value


def is_pdb_code(value):
    value = clean(value).upper()
    return len(value) == 4 and value[0].isdigit() and value.isalnum()


def parse_pdb_chain_source(value):
    value = clean(value).upper()
    match = re.match(r"^(?:PDB_)?([0-9][A-Z0-9]{3})_CHAIN_(.+)$", value)
    if not match:
        return None
    return match.group(1), match.group(2)


def is_no_pocket(value):
    return clean(value).lower() in {"no_pockets", "no pockets", "no-pocket"}


def selected_sources(row):
    return [
        {
            "method": "fpocket",
            "source": clean(row.get("best_fpocket_structure")),
            "pocket": clean(row.get("fpocket_pocket")),
            "residue_set": FP_RESIDUE_SET,
        },
        {
            "method": "p2rank",
            "source": clean(row.get("best_p2rank_structure")),
            "pocket": clean(row.get("p2rank_pocket")),
            "residue_set": P2_RESIDUE_SET,
        },
    ]


def colabfold_sources(row, locus):
    return [
        {
            "method": "fpocket",
            "source": f"CB_{locus}",
            "pocket": clean(row.get("colabfold_fpocket_pocket")),
            "residue_set": FP_RESIDUE_SET,
        },
        {
            "method": "p2rank",
            "source": f"CB_{locus}",
            "pocket": clean(row.get("colabfold_p2rank_pocket")),
            "residue_set": P2_RESIDUE_SET,
        },
    ]


class Command(BaseCommand):
    help = (
        "Import precomputed Gates FPocket/P2Rank outputs from structures/*/pockets "
        "without recalculating them."
    )

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument("--results-tsv", required=True)
        parser.add_argument("--structures-dir", required=True)
        parser.add_argument("--datadir", default="./data")
        parser.add_argument(
            "--scope",
            choices=("selected", "colabfold", "both"),
            default="selected",
            help=(
                "Which Gates pocket sources to import. 'selected' follows "
                "best_fpocket_structure/best_p2rank_structure from the TSV."
            ),
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Delete existing FPocket/P2Rank residue sets for the target structure before loading.",
        )
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=0)

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        results_tsv = options["results_tsv"]
        structures_dir = options["structures_dir"]
        scope = options["scope"]
        dry_run = options["dry_run"]
        limit = options["limit"]

        if not os.path.isfile(results_tsv):
            raise CommandError(f"Results TSV not found: {results_tsv}")
        if not os.path.isdir(structures_dir):
            raise CommandError(f"Structures dir not found: {structures_dir}")

        proteome_name = genome_name + Biodatabase.PROT_POSTFIX
        try:
            db = Biodatabase.objects.get(name=proteome_name)
        except Biodatabase.DoesNotExist as exc:
            raise CommandError(f"Protein database not found: {proteome_name}") from exc

        with open(results_tsv, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if "gene" not in (reader.fieldnames or []):
                raise CommandError("Results TSV must have a 'gene' column.")
            rows = list(reader)

        loaded = skipped = skipped_existing = failed = missing_output = missing_structure = 0
        planned = planned_structure_loads = structure_loads = 0
        examples = []

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Gates pocket output import for {genome_name}"
        ))
        self.stdout.write(f"Rows in TSV: {len(rows)}")
        self.stdout.write(f"Scope: {scope}")

        for row in rows:
            locus = clean(row.get("gene"))
            if not locus:
                continue
            try:
                bioentry = Bioentry.objects.get(biodatabase=db, accession=locus)
            except Bioentry.DoesNotExist:
                missing_structure += 1
                continue

            source_items = []
            if scope in {"selected", "both"}:
                source_items.extend(selected_sources(row))
            if scope in {"colabfold", "both"}:
                source_items.extend(colabfold_sources(row, locus))

            for item in source_items:
                source = item["source"]
                method = item["method"]
                residue_set = item["residue_set"]
                if not source or is_no_pocket(item["pocket"]):
                    skipped += 1
                    continue

                target = self._resolve_target(bioentry, locus, source, method, structures_dir)
                if not target:
                    missing_output += 1
                    if len(examples) < 20:
                        examples.append(f"missing output: {locus} {method} {source}")
                    continue

                struct_code = target["struct_code"]
                output_dir = target["output_dir"]
                pdb = PDB.objects.filter(code__iexact=struct_code, deprecated=False).first()
                if pdb is None and target.get("structure_file"):
                    planned_structure_loads += 1
                    if dry_run:
                        planned += 1
                        continue
                    try:
                        pdb = self._load_structure(
                            bioentry=bioentry,
                            struct_code=struct_code,
                            structure_file=target["structure_file"],
                            experiment=target["experiment"],
                            datadir=options["datadir"],
                            chain=target.get("chain"),
                        )
                        structure_loads += 1
                    except Exception as exc:
                        missing_structure += 1
                        if len(examples) < 20:
                            examples.append(f"structure load failed: {locus} {struct_code}: {exc}")
                        continue

                if pdb is None:
                    missing_structure += 1
                    if len(examples) < 20:
                        examples.append(f"missing TPW structure: {locus} {method} {struct_code}")
                    continue

                if not dry_run:
                    self._ensure_structure_link(bioentry, pdb, target.get("chain"))

                planned += 1
                if dry_run:
                    continue

                try:
                    existing = PDBResidueSet.objects.filter(
                        pdb=pdb,
                        residue_set__name=residue_set,
                    )
                    if existing.exists() and not options["force"]:
                        skipped_existing += 1
                        continue
                    if options["force"]:
                        existing.delete()

                    pocket_json = self._to_pocket_json(method, output_dir, struct_code)
                    if not pocket_json:
                        failed += 1
                        if len(examples) < 20:
                            examples.append(f"conversion failed: {locus} {method} {source}")
                        continue

                    call_command(
                        "load_fpocket",
                        pdb.code,
                        pocket_json=pocket_json,
                        P2rank_pocket=(method == "p2rank"),
                        datadir=options["datadir"],
                        verbosity=0,
                    )
                    loaded += 1
                except Exception as exc:
                    failed += 1
                    if len(examples) < 20:
                        examples.append(f"load failed: {locus} {method} {source}: {exc}")

                if limit and loaded >= limit:
                    break
            if limit and loaded >= limit:
                break

        if dry_run:
            self.stdout.write(f"[dry-run] Would load pocket sets: {planned}")
            self.stdout.write(f"[dry-run] Would load missing structures first: {planned_structure_loads}")
        else:
            self.stdout.write(f"Loaded pocket sets: {loaded}")
            self.stdout.write(f"Loaded missing structures: {structure_loads}")
        self.stdout.write(f"Skipped no-source/no-pocket: {skipped}")
        self.stdout.write(f"Skipped existing: {skipped_existing}")
        self.stdout.write(f"Missing original output: {missing_output}")
        self.stdout.write(f"Missing TPW structure: {missing_structure}")
        self.stdout.write(f"Failed: {failed}")
        if examples:
            self.stdout.write("Examples:")
            for example in examples:
                self.stdout.write(f"  {example}")

    def _resolve_target(self, bioentry, locus, source, method, structures_dir):
        source = clean(source)
        prot_dir = os.path.join(structures_dir, locus)
        pockets_dir = os.path.join(prot_dir, "pockets")
        if not os.path.isdir(pockets_dir):
            return None

        suffix = f"_{method}"
        if source == f"CB_{locus}" or source == f"CB_{locus}_relaxed1":
            prefix = f"CB_{locus}_relaxed1"
            candidate = os.path.join(pockets_dir, prefix + suffix)
            if not os.path.isdir(candidate):
                return None
            return {
                "struct_code": locus,
                "output_dir": candidate,
                "structure_file": os.path.join(prot_dir, f"{prefix}.pdb"),
                "experiment": "CF",
                "chain": None,
            }

        pdb_chain_source = parse_pdb_chain_source(source)
        if is_pdb_code(source) or pdb_chain_source:
            if pdb_chain_source:
                pdb_code, requested_chain = pdb_chain_source
                chains = [requested_chain]
            else:
                pdb_code = source.upper()
                chains = self._linked_chains(bioentry, pdb_code)

            candidates = []
            for chain in chains:
                if chain:
                    candidates.append((chain, os.path.join(
                        pockets_dir,
                        f"PDB_{pdb_code}_chain_{chain}{suffix}",
                    )))
            candidates.extend(
                (self._chain_from_pocket_dir(pdb_code, method, name), os.path.join(pockets_dir, name))
                for name in sorted(os.listdir(pockets_dir))
                if name.startswith(f"PDB_{pdb_code}_chain_") and name.endswith(suffix)
            )
            for chain, candidate in candidates:
                if os.path.isdir(candidate):
                    struct_code = self._pdb_chain_struct_code(pdb_code, chain) if chain else pdb_code
                    return {
                        "struct_code": struct_code,
                        "output_dir": candidate,
                        "structure_file": self._find_pdb_chain_file(prot_dir, pdb_code, chain),
                        "experiment": "EX",
                        "chain": chain,
                    }
            return None

        accession = source.split("|", 1)[0]
        struct_code = f"AF_{accession}"
        candidate = os.path.join(pockets_dir, struct_code + suffix)
        if not os.path.isdir(candidate):
            return None
        return {
            "struct_code": struct_code,
            "output_dir": candidate,
            "structure_file": self._find_af_file(prot_dir, accession),
            "experiment": "AF",
            "chain": None,
        }

    def _linked_chains(self, bioentry, pdb_code):
        return list(
            BioentryStructure.objects.filter(
                bioentry=bioentry,
                pdb__code__iexact=pdb_code,
                pdb__deprecated=False,
            )
            .exclude(chain__isnull=True)
            .values_list("chain", flat=True)
        )

    def _chain_from_pocket_dir(self, pdb_code, method, dirname):
        match = re.match(rf"^PDB_{re.escape(pdb_code)}_chain_(.+)_{method}$", dirname)
        return match.group(1) if match else ""

    def _pdb_chain_struct_code(self, pdb_code, chain):
        safe_chain = re.sub(r"[^A-Za-z0-9]+", "_", clean(chain)).strip("_") or "chain"
        return f"{pdb_code}_chain_{safe_chain}"

    def _find_pdb_chain_file(self, prot_dir, pdb_code, chain):
        if not chain:
            return ""
        wanted = {
            f"PDB_{pdb_code}_chain_{chain}.pdb".lower(),
            f"PDB_{pdb_code}_chain_{chain}.pdb.gz".lower(),
        }
        return self._find_file_under_protein(prot_dir, wanted)

    def _find_af_file(self, prot_dir, accession):
        wanted = {
            f"AF_{accession}.pdb".lower(),
            f"AF_{accession}.pdb.gz".lower(),
        }
        return self._find_file_under_protein(prot_dir, wanted)

    def _find_file_under_protein(self, prot_dir, wanted_names):
        for dirpath, dirnames, filenames in os.walk(prot_dir):
            dirnames[:] = [name for name in dirnames if name != "pockets"]
            for filename in filenames:
                if filename.lower() in wanted_names:
                    return os.path.join(dirpath, filename)
        return ""

    def _ensure_structure_link(self, bioentry, pdb, chain=None):
        link, _created = BioentryStructure.objects.get_or_create(
            bioentry=bioentry,
            pdb=pdb,
        )
        if chain and link.chain != chain:
            link.chain = chain
            link.save(update_fields=["chain"])
        return link

    def _load_structure(self, bioentry, struct_code, structure_file, experiment, datadir, chain=None):
        if not structure_file or not os.path.isfile(structure_file):
            raise CommandError(f"Source structure file not found for {struct_code}")

        try:
            with open(os.devnull, "w") as devnull:
                call_command(
                    "load_af_model",
                    struct_code,
                    structure_file,
                    bioentry.accession,
                    experiment=experiment,
                    datadir=datadir,
                    stdout=devnull,
                    stderr=devnull,
                )
        except SystemExit as exc:
            if exc.code not in (0, None):
                raise CommandError(f"load_af_model exited with {exc.code}") from exc
        pdb = PDB.objects.get(code__iexact=struct_code, deprecated=False)
        if chain:
            BioentryStructure.objects.filter(bioentry=bioentry, pdb=pdb).update(chain=chain)
        return pdb

    def _to_pocket_json(self, method, output_dir, struct_code):
        if method == "fpocket":
            pocket_json = bpe._fpocket_to_json(output_dir)
            if not pocket_json or fpocket_json_is_empty(pocket_json):
                pocket_json = fallback_fpocket_to_json(output_dir)
            return pocket_json
        return bpe._p2rank_to_json(output_dir, struct_code)
