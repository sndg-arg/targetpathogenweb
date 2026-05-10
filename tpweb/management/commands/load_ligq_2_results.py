import re
from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from tqdm import tqdm

from bioseq.models.Bioentry import Bioentry
from tpweb.models.Binders import Binders


def _parse_first_token(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    s = str(value).strip()
    if not s or s in ("[]", "['']", "[\"\"]"):
        return ""
    match = re.search(r"['\"]([^'\"]+)['\"]", s)
    return match.group(1) if match else ""


def _safe_float(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _short(value, limit=200):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(value).strip()
    if not s:
        return ""
    if len(s) > limit:
        return s[: limit - 3] + "..."
    return s


class Command(BaseCommand):
    help = (
        "Load ligands predicted by LigQ_2 (known + zinc) into the Binders table. "
        "Reads known_ligands.tsv and zinc_ligands.tsv from the LigQ_2 output dir."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "output_dir",
            help="LigQ_2 output directory containing known_ligands.tsv and zinc_ligands.tsv.",
        )
        parser.add_argument(
            "--max-zinc-per-protein",
            type=int,
            default=50,
            help="Top-N zinc binders per protein, ordered by tanimoto desc (default 50).",
        )
        parser.add_argument(
            "--min-tanimoto",
            type=float,
            default=0.5,
            help="Drop zinc binders with tanimoto below this value (default 0.5).",
        )
        parser.add_argument(
            "--max-known-per-protein",
            type=int,
            default=100,
            help="Top-N known binders per protein, ordered by pchembl desc, NaN last (default 100).",
        )
        parser.add_argument(
            "--locustag-fallback",
            default=None,
            help=(
                "Bioentry accession to use as locustag for known_ligands.tsv rows when "
                "the file has no 'qseqid' column (single-protein LigQ_2 run)."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and filter only; do not write to the database.",
        )

    def handle(self, *args, **options):
        out_dir = Path(options["output_dir"]).resolve()
        if not out_dir.is_dir():
            raise CommandError(f"Output directory not found: {out_dir}")

        known_path = out_dir / "known_ligands.tsv"
        zinc_path = out_dir / "zinc_ligands.tsv"
        if not known_path.exists() and not zinc_path.exists():
            raise CommandError(
                f"Neither known_ligands.tsv nor zinc_ligands.tsv found in {out_dir}"
            )

        known_stats = {"raw": 0, "kept": 0, "written": 0, "skipped_locustag": 0}
        zinc_stats = {"raw": 0, "kept": 0, "written": 0, "skipped_locustag": 0}

        if known_path.exists():
            self._load_known(
                known_path,
                max_per_protein=options["max_known_per_protein"],
                locustag_fallback=options["locustag_fallback"],
                dry_run=options["dry_run"],
                stats=known_stats,
            )
        else:
            self.stdout.write(self.style.WARNING("Skipping known_ligands.tsv (file not present)"))

        if zinc_path.exists():
            self._load_zinc(
                zinc_path,
                max_per_protein=options["max_zinc_per_protein"],
                min_tanimoto=options["min_tanimoto"],
                dry_run=options["dry_run"],
                stats=zinc_stats,
            )
        else:
            self.stdout.write(self.style.WARNING("Skipping zinc_ligands.tsv (file not present)"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== LigQ_2 load summary ==="))
        self.stdout.write(
            f"  known: raw={known_stats['raw']}  kept={known_stats['kept']}  "
            f"written={known_stats['written']}  missing_locustag={known_stats['skipped_locustag']}"
        )
        self.stdout.write(
            f"  zinc:  raw={zinc_stats['raw']}   kept={zinc_stats['kept']}   "
            f"written={zinc_stats['written']}   missing_locustag={zinc_stats['skipped_locustag']}"
        )
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("(dry-run: no rows were written)"))

    def _load_known(self, path, *, max_per_protein, locustag_fallback, dry_run, stats):
        df = pd.read_csv(path, sep="\t")
        stats["raw"] = len(df)
        self.stdout.write(self.style.NOTICE(f"known_ligands.tsv: {len(df)} raw rows"))

        if "qseqid" in df.columns:
            df["_locustag"] = df["qseqid"].astype(str)
        elif locustag_fallback:
            df["_locustag"] = str(locustag_fallback)
            self.stdout.write(
                f"  using --locustag-fallback={locustag_fallback} for all known rows"
            )
        else:
            raise CommandError(
                "known_ligands.tsv has no 'qseqid' column. "
                "Pass --locustag-fallback <accession> to map rows to a Bioentry."
            )

        df["_pchembl_sort"] = pd.to_numeric(df.get("pchembl"), errors="coerce")
        df = df.sort_values(
            ["_locustag", "_pchembl_sort"], ascending=[True, False], na_position="last"
        )
        df = df.groupby("_locustag", as_index=False, sort=False).head(max_per_protein)
        stats["kept"] = len(df)
        self.stdout.write(f"  after top-{max_per_protein}/protein filter: {len(df)} rows")

        if dry_run:
            return

        bioentry_map = self._bioentry_map(df["_locustag"].unique())

        with transaction.atomic():
            for _, row in tqdm(df.iterrows(), total=len(df), desc="known"):
                locustag = row["_locustag"]
                bioentry = bioentry_map.get(locustag)
                if bioentry is None:
                    stats["skipped_locustag"] += 1
                    continue

                chem_comp_id = str(row.get("chem_comp_id", "") or "").strip()
                smiles = str(row.get("smiles", "") or "").strip()
                if not chem_comp_id or not smiles:
                    continue

                pdb_first = _parse_first_token(row.get("pdb_ids"))
                uniprot = str(row.get("uniprot_id", "") or "").strip()
                score = _safe_float(row.get("pchembl"))

                notes = self._format_known_notes(row)

                try:
                    Binders.objects.update_or_create(
                        ccd_id=chem_comp_id,
                        pdb_id=pdb_first,
                        uniprot=uniprot,
                        locustag=bioentry,
                        defaults={
                            "smiles": smiles,
                            "source": Binders.SOURCE_PDB,
                            "score": score,
                            "notes": notes,
                        },
                    )
                    stats["written"] += 1
                except IntegrityError:
                    continue

    def _load_zinc(self, path, *, max_per_protein, min_tanimoto, dry_run, stats):
        df = pd.read_csv(path, sep="\t")
        stats["raw"] = len(df)
        self.stdout.write(self.style.NOTICE(f"zinc_ligands.tsv: {len(df)} raw rows"))

        if "qseqid" not in df.columns:
            raise CommandError("zinc_ligands.tsv missing required column 'qseqid'.")

        df["_tani"] = pd.to_numeric(df.get("tanimoto"), errors="coerce")
        df = df.dropna(subset=["_tani"])
        df = df[df["_tani"] >= min_tanimoto]
        self.stdout.write(f"  after tanimoto >= {min_tanimoto}: {len(df)} rows")

        df["_locustag"] = df["qseqid"].astype(str)
        df = df.sort_values(["_locustag", "_tani"], ascending=[True, False])
        df = df.groupby("_locustag", as_index=False, sort=False).head(max_per_protein)
        stats["kept"] = len(df)
        self.stdout.write(f"  after top-{max_per_protein}/protein filter: {len(df)} rows")

        if dry_run:
            return

        bioentry_map = self._bioentry_map(df["_locustag"].unique())

        with transaction.atomic():
            for _, row in tqdm(df.iterrows(), total=len(df), desc="zinc"):
                locustag = row["_locustag"]
                bioentry = bioentry_map.get(locustag)
                if bioentry is None:
                    stats["skipped_locustag"] += 1
                    continue

                chem_comp_id = str(row.get("chem_comp_id", "") or "").strip()
                smiles = str(row.get("smiles", "") or "").strip()
                if not chem_comp_id or not smiles:
                    continue

                uniprot = str(row.get("uniprot_id", "") or "").strip()
                score = _safe_float(row.get("tanimoto"))

                notes = self._format_zinc_notes(row)

                try:
                    Binders.objects.update_or_create(
                        ccd_id=chem_comp_id,
                        pdb_id="",
                        uniprot=uniprot,
                        locustag=bioentry,
                        defaults={
                            "smiles": smiles,
                            "source": Binders.SOURCE_PROPOSED,
                            "score": score,
                            "notes": notes,
                        },
                    )
                    stats["written"] += 1
                except IntegrityError:
                    continue

    @staticmethod
    def _format_known_notes(row):
        parts = []
        search_type = _short(row.get("search_type"), 32)
        if search_type:
            parts.append(f"LigQ {search_type}")
        src = _short(row.get("source"), 32)
        if src:
            parts.append(f"source={src}")
        mech = _short(row.get("mechanism"), 200)
        if mech:
            parts.append(f"mechanism: {mech}")
        act = _short(row.get("activity_comment"), 200)
        if act:
            parts.append(f"activity: {act}")
        cur = _short(row.get("curation_method"), 64)
        if cur:
            parts.append(f"curation={cur}")
        bs = _short(row.get("binding_sites"), 100)
        if bs:
            parts.append(f"binding_sites={bs}")
        return " | ".join(parts)

    @staticmethod
    def _format_zinc_notes(row):
        parts = []
        search_type = _short(row.get("search_type"), 32)
        if search_type:
            parts.append(f"LigQ {search_type}")
        query_id = _short(row.get("query_id"), 64)
        if query_id:
            parts.append(f"query={query_id}")
        sseqid = _short(row.get("sseqid"), 32)
        if sseqid:
            parts.append(f"homolog={sseqid}")
        return " | ".join(parts)

    @staticmethod
    def _bioentry_map(accessions):
        clean = list({str(a) for a in accessions if a and str(a).strip()})
        if not clean:
            return {}
        return {
            be.accession: be
            for be in Bioentry.objects.filter(accession__in=clean)
        }
