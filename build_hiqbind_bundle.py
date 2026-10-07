#!/usr/bin/env python3
"""Build the HiQBind PocketEval resource bundle consumed by server.py.

Produces, under --out:

    dataset_index.json          per-pocket records
    cluster_assignments.json    pocket_id / cluster_label / projection_2d
    benchmark_pocket_split.csv  released split + the affinity annotations
    summary.json                dataset-level counts
    embeddings/<pid>.npy        80-dim mean-pooled MaSIF descriptor
    pockets/<pid>/{pocket_protein.pdb, ligand.sdf, ligand.pdb, metadata.json}

Notes
-----
* cluster_label is the MaSIF pocket-similarity connected component
  (`mutual_similarity_group`), not a k-means label.
* projection_2d is PCA (SVD) of the 80-dim mean-pooled descriptors.
* The ligand is parsed straight from the SDF atom block (text only) so the build does
  not need RDKit and stays cheap on a single core.

Run:
  python build_hiqbind_bundle.py --split-csv <released split csv> \
      --pocket-root <dir with <pocket_id>/pocket_protein.pdb and ligand.sdf> \
      --patch-root  <dir with <pocket_id>_patch.npy> \
      --out <resource root>
"""

import argparse
import csv
import json
import os
import shutil
import time
from pathlib import Path

import numpy as np

DESCRIPTOR = "MaSIF-search PPI-search patch descriptor"

# Columns dropped from the released table: internal absolute paths that mean nothing to
# an external user, plus columns that are byte-identical to another column.
DROP_COLUMNS = [
    "protein_path", "ligand_path", "patch_path", "pool_path",
    "clean_protein_path", "clean_ligand_path", "clean_patch_path", "clean_pool_path",
    "canonical_smiles",          # identical to "Ligand SMILES"
]

# Fields kept in each pocket's metadata.json. The full annotation lives in the
# benchmark table, so the per-pocket copy stays minimal.
METADATA_FIELDS = ("pocket_id", "pdb_id")


def ligand_from_sdf(sdf_path, resname, chain, resseq):
    """Return (heavy_atom_count, centroid, pdb_text) parsed from the SDF text."""
    with open(sdf_path, "r", errors="replace") as fh:
        lines = fh.read().splitlines()
    if len(lines) < 4:
        return 0, None, ""
    try:
        natoms = int(lines[3][0:3])
    except ValueError:
        return 0, None, ""
    coords, elements = [], []
    for line in lines[4:4 + natoms]:
        if len(line) < 34:
            continue
        el = line[31:34].strip().upper() or line[31:34].strip()
        if not el:
            continue
        coords.append([float(line[0:10]), float(line[10:20]), float(line[20:30])])
        elements.append(el)
    heavy = [(c, e) for c, e in zip(coords, elements) if e != "H"]
    if not heavy:
        return 0, None, ""
    xyz = np.asarray([c for c, _ in heavy], dtype=np.float64)
    centroid = xyz.mean(axis=0)
    out = []
    for i, (c, e) in enumerate(heavy, start=1):
        out.append("HETATM{:>5d} {:<4s}{:>3s} {:1s}{:>4d}    "
                   "{:8.3f}{:8.3f}{:8.3f}  1.00  0.00          {:>2s}".format(
                       i, str(e) + str(i), resname[:3], chain[:1], resseq,
                       c[0], c[1], c[2], e))
    out.append("END")
    return len(heavy), centroid.tolist(), "\n".join(out) + "\n"


def protein_residue_count(pdb_path):
    seen = set()
    with open(pdb_path, "r", errors="replace") as fh:
        for line in fh:
            if line.startswith(("ATOM", "HETATM")):
                seen.add((line[21], line[22:27]))
    return len(seen)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split-csv", required=True)
    ap.add_argument("--pocket-root", required=True)
    ap.add_argument("--patch-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-copy-structures", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    (out / "embeddings").mkdir(parents=True, exist_ok=True)
    (out / "pockets").mkdir(parents=True, exist_ok=True)
    pocket_root = Path(args.pocket_root)
    patch_root = Path(args.patch_root)

    with open(args.split_csv, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if args.limit:
        rows = rows[: args.limit]
    print("rows:", len(rows), flush=True)

    fieldnames = [c for c in rows[0] if c not in DROP_COLUMNS]
    index_records, cluster_records, embeddings, ids = [], [], [], []
    group_label = {}
    started = time.time()
    missing = 0

    with open(out / "benchmark_pocket_split.csv", "w", newline="", encoding="utf-8") as bench:
        writer = csv.DictWriter(bench, fieldnames=fieldnames)
        writer.writeheader()
        for n, row in enumerate(rows, 1):
            pid = row["pocket_id"].strip()
            pdir = pocket_root / pid
            protein_pdb = pdir / "pocket_protein.pdb"
            ligand_sdf = pdir / "ligand.sdf"
            if not protein_pdb.exists() or not ligand_sdf.exists():
                missing += 1
                continue

            writer.writerow({k: row.get(k, "") for k in fieldnames})

            patch_file = patch_root / (pid + "_patch.npy")
            try:
                patches = np.load(str(patch_file))
                patch_count, dim = int(patches.shape[0]), int(patches.shape[1])
                pooled = patches.astype(np.float32).mean(axis=0)
            except Exception:
                patch_count, dim, pooled = 0, 80, np.zeros(80, dtype=np.float32)
            np.save(str(out / "embeddings" / (pid + ".npy")), pooled)
            embeddings.append(pooled)

            resname = (row.get("Ligand Name") or "LIG").strip() or "LIG"
            chain = (row.get("Ligand Chain") or "A").strip() or "A"
            try:
                resseq = int(float(row.get("Ligand Residue Number") or 1))
            except ValueError:
                resseq = 1
            heavy, centroid, lig_pdb = ligand_from_sdf(str(ligand_sdf), resname, chain, resseq)

            label = row.get("mutual_similarity_group", "")
            if label not in group_label:
                group_label[label] = len(group_label)
            cluster_records.append({
                "cluster_label": group_label[label],
                "embedding_npy": "embeddings/{}.npy".format(pid),
                "pdb_id": row.get("PDBID", ""),
                "pocket_id": pid,
                "projection_2d": [0.0, 0.0],
            })

            index_records.append({
                "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "distance_cutoff": 12.0,
                "embedding": {
                    "cached": True,
                    "descriptor_dim": dim,
                    "embedding_dim": int(pooled.shape[0]),
                    "embedding_path": "embeddings/{}.npy".format(pid),
                    "patch_count": patch_count,
                    "representation": DESCRIPTOR,
                    "dtype": "float32",
                },
                "ligand": {
                    "centroid": centroid,
                    "chain_id": chain,
                    "heavy_atom_count": heavy,
                    "icode": "",
                    "resname": resname,
                    "resseq": resseq,
                },
                "paths": {
                    "embedding_npy": "embeddings/{}.npy".format(pid),
                    "pocket_dir": "pockets/{}".format(pid),
                    "pocket_protein_pdb": "pockets/{}/pocket_protein.pdb".format(pid),
                    "ligand_pdb": "pockets/{}/ligand.pdb".format(pid),
                    "ligand_sdf": "pockets/{}/ligand.sdf".format(pid),
                    "metadata_json": "pockets/{}/metadata.json".format(pid),
                },
                "pdb_id": row.get("PDBID", ""),
                "pocket_id": pid,
                "protein_residue_count": protein_residue_count(str(protein_pdb)),
                "status": "success",
                "split": row.get("split", ""),
            })
            ids.append(pid)

            if not args.no_copy_structures:
                dst = out / "pockets" / pid
                dst.mkdir(parents=True, exist_ok=True)
                for src, name in ((protein_pdb, "pocket_protein.pdb"), (ligand_sdf, "ligand.sdf")):
                    target = dst / name
                    if not target.exists():
                        # realpath: the source pocket_protein.pdb is itself a symlink, and
                        # linking the link would ship a dangling path in the release archive.
                        real = os.path.realpath(str(src))
                        try:
                            os.link(real, str(target))
                        except OSError:
                            shutil.copyfile(real, str(target))
                (dst / "ligand.pdb").write_text(lig_pdb, encoding="utf-8")
                metadata = {
                    "pocket_id": pid,
                    "pdb_id": row.get("PDBID", ""),
                    "ligand": {"resname": resname, "chain_id": chain, "resseq": resseq},
                }
                (dst / "metadata.json").write_text(
                    json.dumps(metadata, indent=2), encoding="utf-8")

            if n % 2000 == 0:
                print("  {}/{}  {:.0f}s".format(n, len(rows), time.time() - started), flush=True)

    matrix = np.asarray(embeddings, dtype=np.float64)
    matrix -= matrix.mean(axis=0, keepdims=True)
    u, s, vt = np.linalg.svd(matrix, full_matrices=False)
    proj = u[:, :2] * s[:2]
    for rec, xy in zip(cluster_records, proj):
        rec["projection_2d"] = [float(xy[0]), float(xy[1])]

    (out / "dataset_index.json").write_text(json.dumps(index_records), encoding="utf-8")
    (out / "cluster_assignments.json").write_text(json.dumps(cluster_records), encoding="utf-8")

    counts = {}
    for rec in index_records:
        counts[rec["split"]] = counts.get(rec["split"], 0) + 1
    summary = {
        "canonical_pockets": len(index_records),
        "split_counts": counts,
        "descriptor": DESCRIPTOR,
        "descriptor_dim": 80,
        "dtype": "float32",
        "embedding_files": len(ids),
        "pocket_directories": len(ids),
        "patch_total": int(sum(r["embedding"]["patch_count"] for r in index_records)),
        "alignment_key": "pocket_id",
        "cluster_label_source": "MaSIF pocket-similarity connected component (mutual_similarity_group)",
        "projection": "PCA (SVD) of the 80-dim mean-pooled MaSIF descriptor",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("missing input pockets:", missing)
    print("clusters:", len(group_label), " wall: {:.0f}s".format(time.time() - started))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
