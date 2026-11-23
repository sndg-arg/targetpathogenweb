#!/usr/bin/env python
"""Match ligand SMILES to literature reactions that make them (or a close analog).

Runs on a SLURM CPU node with RDKit (the LigQ_2 conda env), submitted by
`manage.py predict_ligand_reactions`; never on nodo0.

Inputs:
  --ligands   one SMILES per line, exactly as stored in Binders.smiles
  --uspto50k  USPTO-50K with Schneider reaction classes (retrosim's
              data_processed.csv: class, id, rxn_smiles)
  --paroutes  PaRoutes v2 selected_reactions_all.csv (tab-separated: id,
              rsmi_processed, classification)
Output (gzipped TSV, one row per ligand-reaction match):
  ligand_smiles db match similarity reaction_id reaction_class reaction_name
  reactants reagents product

A reaction matches exactly when its canonical product equals the ligand's,
and by similarity (Morgan r2/2048, Tanimoto >= --min-similarity) only for
ligands without an exact match in that dataset.
"""

import argparse
import csv
import gzip
import re
import sys
import time
from multiprocessing import Pool

import numpy as np
from rdkit import Chem, DataStructs, RDLogger
from rdkit.Chem import rdFingerprintGenerator

RDLogger.DisableLog("rdApp.*")
csv.field_size_limit(sys.maxsize)

# Per ligand, per dataset: (exact, similar) reactions kept; reactions kept per product.
LIMITS = {"us50k": (5, 3, 5), "par2": (3, 2, 2)}
SCHNEIDER_CLASSES = {
    1: "Heteroatom alkylation and arylation",
    2: "Acylation",
    3: "C–C bond formation",
    4: "Heterocycle formation",
    5: "Protection",
    6: "Deprotection",
    7: "Reduction",
    8: "Oxidation",
    9: "Functional group interconversion",
    10: "Functional group addition",
}
MAP_RE = re.compile(r":\d+\]")
_FPGEN = None
_FPS = None


def _fpgen():
    global _FPGEN
    if _FPGEN is None:
        _FPGEN = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
    return _FPGEN


def strip_maps(smiles):
    return MAP_RE.sub("]", smiles)


def canonical(smiles):
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    return Chem.MolToSmiles(mol) if mol is not None else None


def _fingerprint(smiles):
    mol = Chem.MolFromSmiles(smiles)
    return _fpgen().GetFingerprint(mol).ToBinary() if mol is not None else None


def _parse_reaction(reactants, reagents, product):
    """(canonical product, fingerprint bytes, display reactants, reagents, product)."""
    product = canonical(strip_maps(product))
    if not product or "." in product:
        return None
    shown = [canonical(strip_maps(s)) or strip_maps(s) for s in reactants.split(".") if s]
    return product, _fingerprint(product), ".".join(shown), strip_maps(reagents), product


def parse_us50k(row):
    reactants, _, product = row["rxn_smiles"].partition(">>")
    parsed = _parse_reaction(reactants, "", product)
    if parsed is None:
        return None
    try:
        rclass = int(float(row["class"]))
    except (TypeError, ValueError):
        rclass = None
    return parsed, (row["id"], rclass, SCHNEIDER_CLASSES.get(rclass, ""))


def parse_par2(row):
    parts = (row.get("rsmi_processed") or "").split(">")
    if len(parts) != 3:
        return None
    parsed = _parse_reaction(parts[0], parts[1], parts[2])
    if parsed is None:
        return None
    code, _, name = (row.get("classification") or "").partition(" ")
    try:
        rclass = int(code.split(".")[0]) or None
    except ValueError:
        rclass = None
    return parsed, (row["id"], rclass, name.strip() if rclass else "")


def load_reactions(path, parser, delimiter, columns, per_product, workers):
    """{canonical product: [reaction, ...]}, products list, fingerprints list."""
    by_product, fps = {}, {}
    with open(path, newline="", encoding="utf-8") as handle, Pool(workers) as pool:
        rows = (
            {key: row.get(key) for key in columns}
            for row in csv.DictReader(handle, delimiter=delimiter)
        )
        for result in pool.imap(parser, rows, chunksize=2000):
            if result is None:
                continue
            (product, fp, reactants, reagents, shown), (rid, rclass, name) = result
            kept = by_product.setdefault(product, [])
            if len(kept) < per_product:
                kept.append((rid, rclass, name, reactants, reagents, shown))
            if product not in fps and fp is not None:
                fps[product] = fp
    products = list(fps)
    return by_product, products, [DataStructs.ExplicitBitVect(fps[p]) for p in products]


def _init_search(fps):
    global _FPS
    _FPS = fps


def _search(args):
    """Top (index, similarity) hits >= threshold for one query fingerprint."""
    query, threshold, keep = args
    sims = np.asarray(DataStructs.BulkTanimotoSimilarity(DataStructs.ExplicitBitVect(query), _FPS))
    hits = np.flatnonzero(sims >= threshold)
    if hits.size > keep * 4:
        hits = hits[np.argpartition(sims[hits], -keep * 4)[-keep * 4 :]]
    return [(int(i), float(sims[i])) for i in hits[np.argsort(-sims[hits])]]


def match_dataset(db, ligands, reactions, threshold, workers, out):
    by_product, products, fps = reactions
    n_exact, n_similar = LIMITS[db][:2]
    rows = 0
    pending = []
    for smiles, canon, fp in ligands:
        exact = by_product.get(canon, [])
        for reaction in exact[:n_exact]:
            out.writerow([smiles, db, "exact", "", *_reaction_cells(reaction)])
            rows += 1
        if not exact and fp is not None:
            pending.append((smiles, canon, fp))
    print(f"{db}: {rows} exact rows; similarity search for {len(pending)} ligands", flush=True)

    with Pool(workers, initializer=_init_search, initargs=(fps,)) as pool:
        tasks = ((fp, threshold, n_similar) for _s, _c, fp in pending)
        for (smiles, canon, _fp), hits in zip(
            pending, pool.imap(_search, tasks, chunksize=64), strict=True
        ):
            kept = 0
            for index, similarity in hits:
                if products[index] == canon or kept >= n_similar:
                    continue
                reaction = by_product[products[index]][0]
                out.writerow(
                    [smiles, db, "similar", f"{similarity:.3f}", *_reaction_cells(reaction)]
                )
                kept += 1
                rows += 1
    return rows


def _reaction_cells(reaction):
    rid, rclass, name, reactants, reagents, product = reaction
    return [rid, "" if rclass is None else rclass, name, reactants, reagents, product]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ligands", required=True)
    parser.add_argument("--uspto50k", required=True)
    parser.add_argument("--paroutes", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-similarity", type=float, default=0.45)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    started = time.time()

    with open(args.ligands, encoding="utf-8") as handle:
        raw = [line.rstrip("\n") for line in handle if line.strip()]
    with Pool(args.workers) as pool:
        canons = pool.map(canonical, raw, chunksize=500)
        fps = pool.map(_fingerprint, [c or "" for c in canons], chunksize=500)
    ligands = [(s, c, f) for s, c, f in zip(raw, canons, fps, strict=True) if c]
    print(f"{len(ligands)} of {len(raw)} ligand SMILES parsed", flush=True)

    sources = [
        ("us50k", args.uspto50k, parse_us50k, ",", ("id", "class", "rxn_smiles")),
        ("par2", args.paroutes, parse_par2, "\t", ("id", "rsmi_processed", "classification")),
    ]
    total = 0
    with gzip.open(args.out, "wt", encoding="utf-8", newline="") as handle:
        out = csv.writer(handle, delimiter="\t", lineterminator="\n")
        out.writerow(
            [
                "ligand_smiles",
                "db",
                "match",
                "similarity",
                "reaction_id",
                "reaction_class",
                "reaction_name",
                "reactants",
                "reagents",
                "product",
            ]
        )
        for db, path, parse, delimiter, columns in sources:
            reactions = load_reactions(path, parse, delimiter, columns, LIMITS[db][2], args.workers)
            print(
                f"{db}: {len(reactions[1])} distinct products "
                f"({time.time() - started:.0f}s elapsed)",
                flush=True,
            )
            total += match_dataset(db, ligands, reactions, args.min_similarity, args.workers, out)
            del reactions
    print(f"done: {total} rows in {time.time() - started:.0f}s", flush=True)


if __name__ == "__main__":
    main()
