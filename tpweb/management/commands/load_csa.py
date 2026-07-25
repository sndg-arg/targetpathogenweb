"""
load_csa - import catalytic-site annotations (Catalytic Site Atlas / M-CSA) into Target.

CSA/M-CSA keys catalytic residues by PDB code + author chain + author residue number - the same
numbering `Residue.chain`/`Residue.resid` already use (populated from the deposited PDB file via
Biopython, see `tpweb/io/PDB2SQL.py`). That means, unlike a UniProt-feature-based importer, no
sequence-position mapping is needed here: a CSA row matches directly against an already-loaded
`Residue` row, when one exists.

This only touches structures already loaded into Target (via `PDB.objects.filter(code=...)`) - it
is a one-time bulk backfill against existing data, not a pipeline stage and not a live external
service call.

Once imported, no further code changes are needed for the sites to show up: `StructureView.py`'s
"nearest annotated site" comparison (used by the FPocket/P2Rank pocket inspector) already treats
any `ResidueSet` other than "FPocketPocket"/"P2RankPocket" as a comparison target, keyed only by
having at least one linked atom per residue (so a geometric center can be computed).

Caveat - **written from the general public CSA/M-CSA CSV format, not a verified sample file**.
Column names are therefore all configurable via flags rather than hardcoded, since the exact
export schema needs to be confirmed against whatever file you actually obtain. This needs to be
run against real CSA data (and reviewed) before being trusted - it has not been executed or
tested in this environment.

Usage
-----
python manage.py load_csa residues.csv \\
    --pdb-column PDB --chain-column "CHAIN ID" --resid-column RESID \\
    --site-column "M-CSA ID" --role-column ROLE \\
    [--overwrite] [--dry-run]

Column flags default to a few commonly-seen header names (case-insensitive) and only need to be
passed if your export uses different ones - the command will list the columns it actually found
if none of the guesses match.
"""

import os

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from tqdm import tqdm

from tpweb.models.pdb import PDB, Atom, PDBResidueSet, Residue, ResidueSet, ResidueSetResidue, AtomResidueSet

RESIDUE_SET_NAME = "CSA"
RESIDUE_SET_DESCRIPTION = "Catalytic Site Atlas / M-CSA catalytic residues"

DEFAULT_COLUMN_ALIASES = {
    "pdb": ["pdb", "pdb_id", "pdb id", "pdb code"],
    "chain": ["chain", "chain_id", "chain id", "chain/id"],
    "resid": ["resid", "residue_id", "residue id", "residue_number", "residue number", "pdb_resid"],
    "site": ["m-csa id", "mcsa_id", "mcsa id", "csa_id", "csa id", "site_number", "site number", "site_id"],
    "role": ["role", "roles", "function_location_abv", "residue_role"],
}


class Command(BaseCommand):
    help = "Import Catalytic Site Atlas (CSA/M-CSA) residue annotations into the ResidueSet model."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Path to the CSA/M-CSA residues export (CSV).")
        parser.add_argument("--pdb-column", default=None, metavar="NAME")
        parser.add_argument("--chain-column", default=None, metavar="NAME")
        parser.add_argument("--resid-column", default=None, metavar="NAME")
        parser.add_argument("--site-column", default=None, metavar="NAME",
                             help="Column that groups residues into one catalytic site "
                                  "(e.g. M-CSA ID). Required to avoid merging unrelated sites "
                                  "that happen to share a PDB code.")
        parser.add_argument("--role-column", default=None, metavar="NAME",
                             help="Optional column with a human-readable role/description per "
                                  "residue, stored on the imported site for display.")
        parser.add_argument("--overwrite", action="store_true",
                             help="Replace any previously-imported CSA sites for the PDB codes "
                                  "found in this file. Without this flag, a PDB code that already "
                                  "has CSA sites imported is left untouched.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        csv_path = options["csv_path"]
        if not os.path.isfile(csv_path):
            raise CommandError(f"File not found: {csv_path}")

        df = pd.read_csv(csv_path, low_memory=False)
        if df.empty:
            raise CommandError("CSV file has no rows.")

        column_lookup = {str(col).strip().lower(): col for col in df.columns}

        def resolve_column(flag_value, kind, required=True):
            candidates = [flag_value] if flag_value else []
            candidates += DEFAULT_COLUMN_ALIASES[kind]
            for candidate in candidates:
                match = column_lookup.get(str(candidate).strip().lower())
                if match is not None:
                    return match
            if not required:
                return None
            raise CommandError(
                f"Could not find a '{kind}' column (tried: {candidates}). "
                f"Columns in this file: {list(df.columns)}. "
                f"Pass --{kind}-column to point at the right one."
            )

        pdb_col = resolve_column(options["pdb_column"], "pdb")
        chain_col = resolve_column(options["chain_column"], "chain")
        resid_col = resolve_column(options["resid_column"], "resid")
        site_col = resolve_column(options["site_column"], "site")
        role_col = resolve_column(options["role_column"], "role", required=False)

        overwrite = options["overwrite"]
        dry_run = options["dry_run"]

        work = pd.DataFrame({
            "pdb": df[pdb_col].astype(str).str.strip().str.upper(),
            "chain": df[chain_col].astype(str).str.strip(),
            "resid": pd.to_numeric(df[resid_col], errors="coerce"),
            "site": df[site_col].astype(str).str.strip(),
        })
        if role_col:
            work["role"] = df[role_col].astype(str).str.strip()

        before = len(work)
        work = work.dropna(subset=["resid", "pdb", "chain", "site"])
        work = work[(work["pdb"] != "") & (work["chain"] != "") & (work["site"] != "")]
        work["resid"] = work["resid"].astype(int)
        dropped = before - len(work)
        if dropped:
            self.stdout.write(self.style.WARNING(
                f"  Skipped {dropped} row(s) missing PDB/chain/residue number/site id."
            ))

        pdb_codes_in_file = set(work["pdb"].unique())
        known_pdb_codes = set(
            PDB.objects.filter(code__in=pdb_codes_in_file).values_list("code", flat=True)
        )
        matched = work[work["pdb"].isin(known_pdb_codes)]
        unmatched_pdb_count = len(pdb_codes_in_file) - len(known_pdb_codes)

        sites = list(matched.groupby(["pdb", "site"]))

        self.stdout.write(self.style.HTTP_INFO(
            f"{len(work)} residue row(s) across {len(pdb_codes_in_file)} PDB code(s) in the file; "
            f"{len(known_pdb_codes)} of those are already loaded in Target "
            f"({unmatched_pdb_count} PDB code(s) in the file are not loaded here and will be skipped) "
            f"-> {len(sites)} catalytic site(s) to import."
        ))

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                f"[dry-run] Would attempt to import {len(sites)} catalytic site(s). "
                "No database changes made."
            ))
            return

        if not sites:
            self.stdout.write(self.style.WARNING("Nothing to import."))
            return

        residue_set, _ = ResidueSet.objects.get_or_create(
            name=RESIDUE_SET_NAME,
            defaults={"description": RESIDUE_SET_DESCRIPTION},
        )

        created_sites = 0
        skipped_sites_existing = 0
        skipped_residues_not_found = 0
        skipped_sites_no_match = 0

        with transaction.atomic():
            if overwrite:
                PDBResidueSet.objects.filter(
                    residue_set=residue_set, pdb__code__in=known_pdb_codes
                ).delete()

            pdb_by_code = {pdb.code: pdb for pdb in PDB.objects.filter(code__in=known_pdb_codes)}

            for (pdb_code, site_id), group in tqdm(sites):
                pdb_obj = pdb_by_code.get(pdb_code)
                if pdb_obj is None:
                    continue

                already_exists = PDBResidueSet.objects.filter(
                    pdb=pdb_obj, residue_set=residue_set, name=str(site_id)[:100]
                ).exists()
                if already_exists and not overwrite:
                    skipped_sites_existing += 1
                    continue

                description = ""
                if role_col and "role" in group.columns:
                    roles = [r for r in group["role"].dropna().unique() if r]
                    description = "; ".join(roles[:3])

                prs = PDBResidueSet.objects.create(
                    pdb=pdb_obj,
                    residue_set=residue_set,
                    name=str(site_id)[:100],
                    description=description[:65535] if description else "",
                )

                linked_any = False
                for _, row in group.iterrows():
                    residue = Residue.objects.filter(
                        pdb=pdb_obj, chain=row["chain"], resid=int(row["resid"])
                    ).first()
                    if residue is None:
                        skipped_residues_not_found += 1
                        continue
                    rsr = ResidueSetResidue.objects.create(residue=residue, pdbresidue_set=prs)
                    # At least the CA atom is required so a geometric center can be
                    # computed later (StructureView.py's _residue_set_core_points walks
                    # residue_set_residue -> atoms -> atom, averaging their coordinates;
                    # a ResidueSetResidue with no linked atom is silently skipped there).
                    ca_atom = Atom.objects.filter(residue=residue, name="CA").first()
                    if ca_atom is not None:
                        AtomResidueSet.objects.create(atom=ca_atom, pdb_set=rsr)
                        linked_any = True

                if linked_any:
                    created_sites += 1
                else:
                    skipped_sites_no_match += 1
                    prs.delete()

        self.stdout.write(self.style.SUCCESS(
            f"Imported {created_sites} catalytic site(s) across "
            f"{matched['pdb'].nunique()} PDB structure(s)."
        ))
        if skipped_sites_existing:
            self.stdout.write(
                f"  {skipped_sites_existing} site(s) skipped (already imported; pass --overwrite to replace)."
            )
        if skipped_sites_no_match:
            self.stdout.write(self.style.WARNING(
                f"  {skipped_sites_no_match} site(s) had no residue that matched the loaded "
                "structure (wrong chain/resid, or the structure only covers part of the chain) "
                "and were not created."
            ))
        if skipped_residues_not_found:
            self.stdout.write(self.style.WARNING(
                f"  {skipped_residues_not_found} individual residue row(s) did not match any "
                "loaded residue and were skipped within otherwise-created sites."
            ))
