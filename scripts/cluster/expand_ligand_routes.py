#!/usr/bin/env python
"""Expand each ligand into a multi-step synthesis tree over literature reactions.

Runs on a SLURM CPU node with RDKit (the LigQ_2 conda env), submitted by
`manage.py predict_ligand_routes`; never on nodo0. Shares the SMILES handling
with match_ligand_reactions.py, which is copied next to it.

Inputs:
  --ligands   one SMILES per line, exactly as stored in Binders.smiles
  --uspto50k  USPTO-50K with Schneider reaction classes (data_processed.csv)
  --paroutes  PaRoutes v2 selected_reactions_all.csv
Output (gzipped JSONL, one plan per ligand that got one):
  {"ligand_smiles", "solved", "depth", "steps", "leaves", "available_leaves", "tree"}

A branch ends at a building block: a compound used as a reactant in at least
--min-uses distinct reactions of the corpus, or small enough (--simple-atoms
heavy atoms) to be a commodity chemical. There is no supplier catalogue here
-- pricing APIs are paid -- so "available" means "routinely used as a starting
material in the patent literature", which is weaker than "in stock" and is
labelled that way in the web page.

The index drops the fingerprints match_ligand_reactions.py needs: this script
only ever looks a product up by its canonical SMILES.
"""

import argparse
import csv
import gzip
import json
import sys
import time
from collections import Counter
import multiprocessing

from rdkit import Chem, RDLogger

import match_ligand_reactions as matcher

RDLogger.DisableLog("rdApp.*")
csv.field_size_limit(2**31 - 1)

# Python 3.14 starts workers with forkserver on Linux, which hands each one a
# fresh interpreter and no copy of the index built here. fork keeps sharing it
# copy-on-write, which is the whole reason the index is a module global.
try:
    MP = multiprocessing.get_context("fork")
except ValueError:  # Windows, where this script never runs
    MP = multiprocessing.get_context()

# Reactions kept per product in the index, and candidates tried per expansion.
PER_PRODUCT = 4
CANDIDATES = 3


def _parse(reactants, reagents, product):
    """(canonical product, display reactants, reagents) -- no fingerprint."""
    product = matcher.canonical(matcher.strip_maps(product))
    if not product or "." in product:
        return None
    shown = [
        matcher.canonical(matcher.strip_maps(s)) or matcher.strip_maps(s)
        for s in reactants.split(".")
        if s
    ]
    return product, ".".join(shown), matcher.strip_maps(reagents)


def parse_us50k(row):
    reactants, _, product = row["rxn_smiles"].partition(">>")
    parsed = _parse(reactants, "", product)
    if parsed is None:
        return None
    try:
        rclass = int(float(row["class"]))
    except (TypeError, ValueError):
        rclass = None
    product, shown, reagents = parsed
    return product, (row["id"], rclass, matcher.SCHNEIDER_CLASSES.get(rclass, ""), shown, reagents)


def parse_par2(row):
    parts = (row.get("rsmi_processed") or "").split(">")
    if len(parts) != 3:
        return None
    parsed = _parse(parts[0], parts[1], parts[2])
    if parsed is None:
        return None
    code, _, name = (row.get("classification") or "").partition(" ")
    try:
        rclass = int(code.split(".")[0]) or None
    except ValueError:
        rclass = None
    product, shown, reagents = parsed
    return product, (row["id"], rclass, name.strip() if rclass else "", shown, reagents)


def heavy_atoms(smiles):
    mol = Chem.MolFromSmiles(smiles)
    return mol.GetNumHeavyAtoms() if mol is not None else 0


class Corpus:
    """The retro index: what makes a compound, and what ends a branch."""

    def __init__(self, by_product, reactant_uses, min_uses, simple_atoms):
        self.by_product = by_product
        self.reactant_uses = reactant_uses
        self.min_uses = min_uses
        self.simple_atoms = simple_atoms
        self._available = {}

    def available(self, smiles):
        """A building block: common in the corpus, or a small commodity."""
        known = self._available.get(smiles)
        if known is None:
            known = self.reactant_uses.get(smiles, 0) >= self.min_uses or (
                0 < heavy_atoms(smiles) <= self.simple_atoms
            )
            self._available[smiles] = known
        return known

    def reactions(self, smiles):
        return self.by_product.get(smiles, ())


def _leaf(smiles, corpus):
    return {
        "smiles": smiles,
        "available": corpus.available(smiles),
        "reaction": None,
        "precursors": [],
    }


def walk(node):
    """(leaves, available leaves, steps) under a node, the node included."""
    if node["reaction"] is None:
        return 1, int(node["available"]), 0
    leaves = available = 0
    steps = 1
    for child in node["precursors"]:
        child_leaves, child_available, child_steps = walk(child)
        leaves += child_leaves
        available += child_available
        steps += child_steps
    return leaves, available, steps


def score(node):
    """(solved, available leaves, -steps): bigger is better."""
    leaves, available, steps = walk(node)
    return (leaves == available, available, -steps)


def depth_of(node):
    if node["reaction"] is None:
        return 0
    return 1 + max(depth_of(child) for child in node["precursors"])


def expand(smiles, corpus, depth, seen):
    """The best plan for one compound, as a tree node. Depth-bounded, acyclic."""
    if depth <= 0 or corpus.available(smiles) or smiles in seen:
        return _leaf(smiles, corpus)

    best = best_score = None
    seen = seen | {smiles}
    for rid, rclass, name, reactants, reagents in corpus.reactions(smiles)[:CANDIDATES]:
        precursors = [p for p in reactants.split(".") if p]
        if not precursors or smiles in precursors:
            continue
        node = {
            "smiles": smiles,
            "available": False,
            "reaction": {
                "id": rid,
                "class": rclass,
                "name": name,
                "reagents": reagents,
                "reactants": reactants,
            },
            "precursors": [expand(p, corpus, depth - 1, seen) for p in precursors],
        }
        node_score = score(node)
        if best_score is None or node_score > best_score:
            best, best_score = node, node_score
        if node_score[0]:
            # Every branch ends in a building block; no need to try the rest.
            break
    return best if best is not None else _leaf(smiles, corpus)


_CORPUS = None
_MAX_DEPTH = 3


def plan(ligand):
    """One (smiles, canonical) ligand -> its plan dict, or None when nothing makes it."""
    smiles, canon = ligand
    if _CORPUS is None:
        raise RuntimeError("the index did not reach this worker: expected a fork start method")
    node = expand(canon, _CORPUS, _MAX_DEPTH, frozenset())
    if node["reaction"] is None:
        return None
    leaves, available, steps = walk(node)
    return {
        "ligand_smiles": smiles,
        "solved": leaves == available,
        "depth": depth_of(node),
        "steps": steps,
        "leaves": leaves,
        "available_leaves": available,
        "tree": node,
    }


def load_corpus(sources, min_uses, simple_atoms, workers, started):
    """Merge the datasets into one retro index plus reactant-use counts."""
    by_product = {}
    reactant_uses = Counter()
    for db, path, parser, delimiter, columns in sources:
        rows = 0
        with open(path, newline="", encoding="utf-8") as handle, MP.Pool(workers) as pool:
            records = (
                {key: row.get(key) for key in columns}
                for row in csv.DictReader(handle, delimiter=delimiter)
            )
            for result in pool.imap(parser, records, chunksize=2000):
                if result is None:
                    continue
                product, reaction = result
                kept = by_product.setdefault(product, [])
                if len(kept) < PER_PRODUCT:
                    kept.append(reaction)
                # Counted over every reaction, not only the ones kept: this is
                # how often the corpus starts from that compound.
                for reactant in reaction[3].split("."):
                    if reactant:
                        reactant_uses[reactant] += 1
                rows += 1
        print(
            f"{db}: {rows} reactions, {len(by_product)} products so far "
            f"({time.time() - started:.0f}s elapsed)",
            flush=True,
        )
    return Corpus(by_product, reactant_uses, min_uses, simple_atoms)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ligands", required=True)
    parser.add_argument("--uspto50k", required=True)
    parser.add_argument("--paroutes", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--min-uses", type=int, default=25)
    parser.add_argument("--simple-atoms", type=int, default=12)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    started = time.time()

    with open(args.ligands, encoding="utf-8") as handle:
        raw = [line.rstrip("\n") for line in handle if line.strip()]
    with MP.Pool(args.workers) as pool:
        canons = pool.map(matcher.canonical, raw, chunksize=500)
    ligands = [(s, c) for s, c in zip(raw, canons, strict=True) if c]
    print(f"{len(ligands)} of {len(raw)} ligand SMILES parsed", flush=True)

    sources = [
        ("us50k", args.uspto50k, parse_us50k, ",", ("id", "class", "rxn_smiles")),
        ("par2", args.paroutes, parse_par2, "\t", ("id", "rsmi_processed", "classification")),
    ]
    global _CORPUS, _MAX_DEPTH
    _CORPUS = load_corpus(sources, args.min_uses, args.simple_atoms, args.workers, started)
    _MAX_DEPTH = args.max_depth
    print(
        f"index: {len(_CORPUS.by_product)} products, "
        f"{len(_CORPUS.reactant_uses)} distinct reactants",
        flush=True,
    )

    written = solved = 0
    # The workers fork after the index is built, so they share it copy-on-write
    # instead of each receiving a pickled copy.
    with (
        gzip.open(args.out, "wt", encoding="utf-8", newline="") as handle,
        MP.Pool(args.workers) as pool,
    ):
        for result in pool.imap(plan, ligands, chunksize=16):
            if result is None:
                continue
            handle.write(json.dumps(result, separators=(",", ":")) + "\n")
            written += 1
            solved += int(result["solved"])
    print(
        f"done: {written} plans ({solved} fully resolved) in {time.time() - started:.0f}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
