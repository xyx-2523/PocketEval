---
license: mit
task_categories:
  - other
language:
  - en
pretty_name: PocketEval — HiQBind pocket-level benchmark
tags:
  - protein-ligand
  - binding-affinity
  - benchmark
  - MaSIF
  - binding-pocket
---

# PocketEval — HiQBind pocket-level benchmark

PocketEval organises **HiQBind** at the level of the binding pocket and releases a
geometry-aware partition that constrains both pocket-surface similarity and protein-level
relatedness.

* **32,230** pocket-level complexes from **18,149** PDB entries
* Released split: **25,784 / 3,223 / 3,223** (train / validation / test)
* Pocket representation: **MaSIF-search 80-dimensional** surface patch descriptor,
  mean-pooled to an 80-dimensional pocket vector

## Files

| File | Size | Content |
|---|---|---|
| `dataset_index.json` | 29 MB | one record per pocket: ligand identity, embedding metadata, protein residue count, split |
| `cluster_assignments.json` | 5.7 MB | `cluster_label` (MaSIF pocket-similarity connected component) and `projection_2d` (PCA of the 80-dim descriptor) |
| `benchmark_pocket_split.csv` | 16 MB | released partition with affinity annotations and grouping columns |
| `summary.json` | 0.5 kB | dataset-level counts |
| `pocket_structures.tar.gz` | **1.9 GB** | per-pocket `pocket_protein.pdb`, `ligand.sdf`, `ligand.pdb`, `metadata.json` and the 80-dim `embeddings/<pocket_id>.npy` |
| `SHA256SUMS.txt` | 0.5 kB | checksums for the files above |

## Getting started

```bash
# 1. clone the web application (code only)
git clone https://github.com/xyx-2523/PocketEval.git
cd PocketEval

# 2. download the data files from this dataset page into resource_bundle/

# 3. extract the structures into resource_bundle/ (top-level entries are
#    pockets/ and embeddings/, so no --strip-components is needed)
tar -xzf pocket_structures.tar.gz -C resource_bundle/

# 4. verify
sha256sum -c SHA256SUMS.txt

# 5. run the browser
python server.py --host 127.0.0.1 --port 8766
# -> "Pocket web platform ready on http://0.0.0.0:8766 with 32230 pockets"
```

Once the archive is extracted, pocket search, split and cluster filtering, the 2D embedding
projection and the 3D structure viewer all work. `/api/structure/<pocket_id>/complex.pdb`
is composed from `pocket_protein.pdb` + `ligand.pdb` at request time, so no separate complex
file is distributed.

## Layout

```text
resource_bundle/
|-- dataset_index.json
|-- cluster_assignments.json
|-- benchmark_pocket_split.csv
|-- summary.json
|-- pockets/<pocket_id>/{pocket_protein.pdb, ligand.sdf, ligand.pdb, metadata.json}
`-- embeddings/<pocket_id>.npy
```

## Construction

The Pocket partition groups pockets that are similar in MaSIF 80-dimensional surface geometry
(mutual patch matching: cosine 0.95, symmetric coverage 0.90, mutual Q25 0.98, support 5)
together with pockets sharing a UniProt accession connected component, and assigns each
integrated group wholly to one subset. No affinity or ligand information is used to build the
graph or the grouping.

## Source data

Derived from **HiQBind** (32,230 complexes; Wang, Y. *et al.*, *Digital Discovery* **2025**,
*4*, 1209–1220, DOI [10.1039/d4dd00357h](https://doi.org/10.1039/d4dd00357h)), which is
distributed under the MIT licence.

## Citation

If you use this resource, please cite the PocketEval paper and the HiQBind dataset above.
