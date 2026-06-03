"""
Convert Gates-Targets fpocket output to TPW fpocket.json.gz format.

Reads ATCC43816-001.tar.gz in streaming mode (no full extraction),
produces a new tar: fpocket_converted.tar.gz
  {locus_tag}/fpocket.json.gz   (one file per protein)

Usage:
    python scripts/gates_fpocket_to_tpw.py \
        /Users/ani/Desktop/Exactas/Klebsiella/ATCC43816-001.tar.gz \
        /tmp/fpocket_converted.tar.gz
"""

import gzip
import io
import json
import re
import sys
import tarfile
from collections import defaultdict

# Map from _info.txt property name → TPW long name
# (TPW long names must match fpocket_properties_map values in FPocket2SQL.py)
INFO_TO_TPW = {
    "Score":                               "Score",
    "Druggability Score":                  "Druggability Score",
    "Number of Alpha Spheres":             "Number of Alpha Spheres",
    "Total SASA":                          "Total SASA",
    "Polar SASA":                          "Polar SASA",
    "Apolar SASA":                         "Apolar SASA",
    "Volume":                              "Volume",
    "Mean local hydrophobic density":      "Mean local hydrophobic density",
    "Mean alpha sphere radius":            "Mean alpha sphere radius",
    "Mean alp. sph. solvent access":       "Mean alp sph solvent access",
    "Mean alp sph solvent access":         "Mean alp sph solvent access",
    "Apolar alpha sphere proportion":      "Apolar alpha sphere proportion",
    "Hydrophobicity score":                "Hydrophobicity score",
    "Volume score":                        "Volume score",
    "Polarity score":                      "Polarity score",
    "Charge score":                        "Charge score",
    "Proportion of polar atoms":           "Proportion of polar atoms",
    "Alpha sphere density":                "Alpha sphere density",
    "Cent. of mass - Alpha Sphere max dist": "Cent of mass - Alpha Sphere max dist",
    "Cent of mass - Alpha Sphere max dist":  "Cent of mass - Alpha Sphere max dist",
    "Flexibility":                         "Flexibility",
}


def parse_out_pdb(text):
    """Return dict: pocket_number → [STP HETATM lines]"""
    pockets = defaultdict(list)
    for line in text.splitlines():
        if line.startswith("HETATM") and "STP" in line:
            try:
                pocket_num = int(line[22:26])
                pockets[pocket_num].append(line)
            except ValueError:
                pass
    return pockets


def parse_info_txt(text):
    """Return dict: pocket_number → {tpw_prop_name: float}"""
    pockets = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"Pocket\s+(\d+)\s*:", line)
        if m:
            current = int(m.group(1))
            pockets[current] = {}
            continue
        if current is None:
            continue
        if ":" in line:
            left, _, right = line.partition(":")
            raw_name = left.strip().rstrip(".")
            # try exact match then stripped-period match
            tpw_name = INFO_TO_TPW.get(raw_name) or INFO_TO_TPW.get(raw_name + ".")
            if tpw_name:
                try:
                    pockets[current][tpw_name] = float(right.strip())
                except ValueError:
                    pass
    return pockets


def build_pocket_list(as_lines_by_pocket, props_by_pocket):
    pockets = []
    all_nums = sorted(set(as_lines_by_pocket) | set(props_by_pocket))
    for num in all_nums:
        pockets.append({
            "number": num,
            "as_lines": as_lines_by_pocket.get(num, []),
            "atoms": [],
            "properties": props_by_pocket.get(num, {}),
        })
    return pockets


def make_fpocket_gz(pocket_list):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(json.dumps(pocket_list).encode("utf-8"))
    return buf.getvalue()


def main(src_tar, dst_tar):
    # Collect: locus_tag → {out_pdb: str, info_txt: str}
    data = defaultdict(dict)

    print(f"Reading {src_tar} …", flush=True)
    with tarfile.open(src_tar, "r:gz") as tf:
        for member in tf:
            name = member.name
            # Match: KpATCC43816/structures/{locus_tag}/pockets/CB_{locus_tag}_relaxed1_fpocket/CB_{locus_tag}_relaxed1_out.pdb
            m = re.search(
                r"structures/(VK055_\d+)/pockets/CB_VK055_\d+_relaxed1_fpocket/"
                r"CB_(VK055_\d+)_relaxed1_(out\.pdb|info\.txt)$",
                name,
            )
            if not m:
                continue
            locus_tag = m.group(1)
            file_type = m.group(3)  # "out.pdb" or "info.txt"
            key = "out_pdb" if file_type == "out.pdb" else "info_txt"
            f = tf.extractfile(member)
            if f:
                data[locus_tag][key] = f.read().decode("utf-8", errors="replace")

    print(f"Found {len(data)} proteins with fpocket data.", flush=True)

    converted = ok = skip = 0
    with tarfile.open(dst_tar, "w:gz") as out_tf:
        for locus_tag, files in sorted(data.items()):
            if "out_pdb" not in files or "info_txt" not in files:
                skip += 1
                continue
            try:
                as_lines = parse_out_pdb(files["out_pdb"])
                props    = parse_info_txt(files["info_txt"])
                if not as_lines and not props:
                    skip += 1
                    continue
                pocket_list = build_pocket_list(as_lines, props)
                gz_bytes    = make_fpocket_gz(pocket_list)

                tarname = f"{locus_tag}/fpocket.json.gz"
                info = tarfile.TarInfo(name=tarname)
                info.size = len(gz_bytes)
                out_tf.addfile(info, io.BytesIO(gz_bytes))
                ok += 1
            except Exception as e:
                print(f"  FAIL {locus_tag}: {e}", flush=True)
                skip += 1

            if ok % 500 == 0 and ok:
                print(f"  {ok} converted …", flush=True)

    print(f"Done. {ok} converted, {skip} skipped → {dst_tar}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python gates_fpocket_to_tpw.py <src.tar.gz> <dst.tar.gz>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
