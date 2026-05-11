import re
from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from tqdm import tqdm

from bioseq.models.Bioentry import Bioentry
from tpweb.models.Binders import Binders


HET_DENYLIST = frozenset({
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
    "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
    "HOH", "DOD", "WAT",
    "NA", "K", "MG", "CA", "CL", "ZN", "FE", "CU", "MN", "CO", "NI", "CD",
    "HG", "FE2", "BR", "IOD", "LI", "BA", "CS", "SR", "AL", "RB", "PT",
    "GOL", "EDO", "MPD", "PEG", "PG4", "PGE", "P6G", "1PE",
    "FMT", "ACT", "CIT", "TRS", "IMD", "DMS", "BME", "EPE", "MES", "BCN",
    "SO4", "PO4", "NO3", "CO3", "SCN", "ACE",
})


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
        "Expects the LigQ_2 output layout: <output_dir>/search_results/<qseqid>/{known,zinc}_ligands.tsv. "
        "Also accepts a flat layout with known_ligands.tsv / zinc_ligands.tsv at the root."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "output_dir",
            help="LigQ_2 output directory (containing 'search_results/' or flat TSVs).",
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
                "Bioentry accession to assign as locustag for flat-layout TSVs that have "
                "no 'qseqid' column (only useful when output_dir contains flat files)."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and filter only; do not write to the database.",
        )
        parser.add_argument(
            "--keep-noise-het",
            action="store_true",
            help=(
                "Keep PDB HET codes that are typically crystallization noise "
                "(amino acids, water, simple ions, buffers, cryoprotectants). "
                "By default these are dropped so the PDB tab shows only drug-like ligands."
            ),
        )

    def handle(self, *args, **options):
        out_dir = Path(options["output_dir"]).resolve()
        if not out_dir.is_dir():
            raise CommandError(f"Output directory not found: {out_dir}")

        known_df, zinc_df = self._collect_tables(out_dir, options["locustag_fallback"])

        if known_df is None and zinc_df is None:
            raise CommandError(
                f"No known_ligands.tsv or zinc_ligands.tsv found under {out_dir}. "
                "Expected layout: <output_dir>/search_results/<qseqid>/*.tsv or flat at root."
            )

        known_stats = {"raw": 0, "kept": 0, "written": 0, "skipped_locustag": 0}
        zinc_stats = {"raw": 0, "kept": 0, "written": 0, "skipped_locustag": 0}

        if known_df is not None:
            self._load_known(
                known_df,
                max_per_protein=options["max_known_per_protein"],
                dry_run=options["dry_run"],
                stats=known_stats,
                skip_noise_het=not options["keep_noise_het"],
            )
        else:
            self.stdout.write(self.style.WARNING("No known_ligands.tsv files found"))

        if zinc_df is not None:
            self._load_zinc(
                zinc_df,
                max_per_protein=options["max_zinc_per_protein"],
                min_tanimoto=options["min_tanimoto"],
                dry_run=options["dry_run"],
                stats=zinc_stats,
            )
        else:
            self.stdout.write(self.style.WARNING("No zinc_ligands.tsv files found"))

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

    def _collect_tables(self, out_dir, locustag_fallback):
        known_frames = []
        zinc_frames = []
        protein_count = 0

        search_root = out_dir / "search_results"
        if search_root.is_dir():
            per_protein_dirs = sorted(p for p in search_root.iterdir() if p.is_dir())
            for prot_dir in per_protein_dirs:
                qseqid = prot_dir.name
                protein_count += 1
                kf = prot_dir / "known_ligands.tsv"
                if kf.exists() and kf.stat().st_size > 0:
                    df = pd.read_csv(kf, sep="\t")
                    if not df.empty:
                        df["_locustag"] = qseqid
                        known_frames.append(df)
                zf = prot_dir / "zinc_ligands.tsv"
                if zf.exists() and zf.stat().st_size > 0:
                    df = pd.read_csv(zf, sep="\t")
                    if not df.empty:
                        df["_locustag"] = qseqid
                        zinc_frames.append(df)
            self.stdout.write(
                self.style.NOTICE(
                    f"Walked search_results/: {protein_count} protein dirs, "
                    f"{len(known_frames)} non-empty known TSVs, "
                    f"{len(zinc_frames)} non-empty zinc TSVs"
                )
            )

        flat_known = out_dir / "known_ligands.tsv"
        if flat_known.exists() and flat_known.stat().st_size > 0:
            df = pd.read_csv(flat_known, sep="\t")
            if "qseqid" in df.columns:
                df["_locustag"] = df["qseqid"].astype(str)
            elif locustag_fallback:
                df["_locustag"] = str(locustag_fallback)
                self.stdout.write(
                    f"  flat known_ligands.tsv: using --locustag-fallback={locustag_fallback}"
                )
            else:
                raise CommandError(
                    "Flat known_ligands.tsv has no 'qseqid' column. "
                    "Pass --locustag-fallback <accession>."
                )
            if not df.empty:
                known_frames.append(df)

        flat_zinc = out_dir / "zinc_ligands.tsv"
        if flat_zinc.exists() and flat_zinc.stat().st_size > 0:
            df = pd.read_csv(flat_zinc, sep="\t")
            if "qseqid" in df.columns:
                df["_locustag"] = df["qseqid"].astype(str)
            elif locustag_fallback:
                df["_locustag"] = str(locustag_fallback)
            else:
                raise CommandError(
                    "Flat zinc_ligands.tsv has no 'qseqid' column. "
                    "Pass --locustag-fallback <accession>."
                )
            if not df.empty:
                zinc_frames.append(df)

        known_df = pd.concat(known_frames, ignore_index=True) if known_frames else None
        zinc_df = pd.concat(zinc_frames, ignore_index=True) if zinc_frames else None
        return known_df, zinc_df

    def _load_known(self, df, *, max_per_protein, dry_run, stats, skip_noise_het=True):
        stats["raw"] = len(df)
        self.stdout.write(self.style.NOTICE(f"known: {len(df)} raw rows"))

        if skip_noise_het:
            ccd_upper = df.get("chem_comp_id", "").astype(str).str.strip().str.upper()
            keep_mask = ~ccd_upper.isin(HET_DENYLIST)
            dropped = (~keep_mask).sum()
            if dropped:
                self.stdout.write(
                    f"  skipping {dropped} non-drug-like HET codes (amino acids, water, ions, buffers)"
                )
            df = df[keep_mask].copy()

        df["_inner_source"] = df.get("source", "").apply(
            lambda v: str(v).strip().lower() if v is not None else ""
        )
        pdb_mask = df["_inner_source"] == "pdb"
        pdb_rows = df[pdb_mask].copy()
        affinity_rows = df[~pdb_mask].copy()
        self.stdout.write(
            f"  inner split: pdb-crystallized={len(pdb_rows)}, affinity/predicted={len(affinity_rows)}"
        )

        pdb_rows = self._top_n_by_pchembl(pdb_rows, max_per_protein)
        affinity_rows = self._top_n_by_pchembl(affinity_rows, max_per_protein)
        stats["kept"] = len(pdb_rows) + len(affinity_rows)
        self.stdout.write(
            f"  after top-{max_per_protein}/protein filter: "
            f"pdb={len(pdb_rows)}, chembl={len(affinity_rows)}"
        )

        if dry_run:
            return

        all_locustags = set(pdb_rows["_locustag"].unique()) | set(
            affinity_rows["_locustag"].unique()
        )
        bioentry_map = self._bioentry_map(all_locustags)

        with transaction.atomic():
            self._write_known_rows(
                pdb_rows, Binders.SOURCE_PDB, bioentry_map, stats, desc="known/pdb"
            )
            self._write_known_rows(
                affinity_rows,
                Binders.SOURCE_CHEMBL,
                bioentry_map,
                stats,
                desc="known/chembl",
            )

    @staticmethod
    def _top_n_by_pchembl(df, n):
        if df.empty:
            return df
        df = df.copy()
        df["_pchembl_sort"] = pd.to_numeric(df.get("pchembl"), errors="coerce")
        df = df.sort_values(
            ["_locustag", "_pchembl_sort"], ascending=[True, False], na_position="last"
        )
        return df.groupby("_locustag", as_index=False, sort=False).head(n)

    def _write_known_rows(self, df, target_source, bioentry_map, stats, *, desc):
        for _, row in tqdm(df.iterrows(), total=len(df), desc=desc):
            bioentry = bioentry_map.get(row["_locustag"])
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
                        "source": target_source,
                        "score": score,
                        "notes": notes,
                    },
                )
                stats["written"] += 1
            except IntegrityError:
                continue

    def _load_zinc(self, df, *, max_per_protein, min_tanimoto, dry_run, stats):
        stats["raw"] = len(df)
        self.stdout.write(self.style.NOTICE(f"zinc: {len(df)} raw rows"))

        df["_tani"] = pd.to_numeric(df.get("tanimoto"), errors="coerce")
        df = df.dropna(subset=["_tani"])
        df = df[df["_tani"] >= min_tanimoto]
        self.stdout.write(f"  after tanimoto >= {min_tanimoto}: {len(df)} rows")

        df = df.sort_values(["_locustag", "_tani"], ascending=[True, False])
        df = df.groupby("_locustag", as_index=False, sort=False).head(max_per_protein)
        stats["kept"] = len(df)
        self.stdout.write(f"  after top-{max_per_protein}/protein filter: {len(df)} rows")

        if dry_run:
            return

        bioentry_map = self._bioentry_map(df["_locustag"].unique())

        with transaction.atomic():
            for _, row in tqdm(df.iterrows(), total=len(df), desc="zinc"):
                bioentry = bioentry_map.get(row["_locustag"])
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
