# PocketEval Pocket Web

PocketEval Pocket Web is an interactive browser for the PocketEval pocket-level benchmark
built on HiQBind (32,230 pockets). It provides pocket-centric inspection of protein-ligand
structures, MaSIF-derived surface descriptors, the released Pocket split, cluster
projections and linked affinity records.

This repository contains the web application only. The per-pocket records, structures,
affinity annotations, descriptors and split files are intentionally excluded and are
distributed separately (see [DATA.md](DATA.md)).

## Contents

```text
.
|-- server.py                     pocket browser (stdlib + optional rdkit)
|-- static/
|   |-- index.html                dataset browser
|   |-- detail.html               per-pocket page
|   |-- app.js  detail.js  styles.css
|   `-- vendor/3Dmol-min.js       bundled 3D viewer (+ its LICENSE.txt)
|-- build_hiqbind_bundle.py       rebuilds the resource bundle from MaSIF outputs
|-- package-pocket-web.sh         code-only deployment archive
|-- run-pocket-web.sh             Linux launcher
|-- run-pocket-web.bat            Windows launcher
|-- requirements.txt
|-- DATA.md                       how to obtain and place the data
|-- DATASET_CARD.md               HuggingFace dataset card
|-- LICENSE-CODE  LICENSE-DATA
`-- resource_bundle/              (not included; provide the released data)
```

## Deployment

### Requirements

- Python 3.10 or later
- `rdkit` — only needed for the ligand-property panel; everything else runs without it

```bash
python -m pip install -r requirements.txt
```

`numpy` is needed only by `build_hiqbind_bundle.py`, not by the web application.

### Windows

```powershell
# from this directory
.\run-pocket-web.bat              # listens on 127.0.0.1:8766
```

Or start the server directly:

```powershell
python server.py --host 127.0.0.1 --port 8766
```

`run-pocket-web.bat` sets `PYTHON_BIN` to `python` by default; set the environment
variable before running it to use a specific interpreter.

### Linux / macOS

```bash
bash run-pocket-web.sh            # listens on 0.0.0.0:8766
```

The port and interpreter can be configured with environment variables:

```bash
PORT=8790 PYTHON_BIN=python3 bash run-pocket-web.sh
```

### Data location

By default the server reads `resource_bundle/` next to `server.py`. The extracted
structures are ~9 GB across ~190,000 files, so the bundle can also be kept anywhere
else and pointed at explicitly:

```bash
python server.py --resource-root /path/to/pocketeval --port 8766
```

The resource root must contain the four metadata files plus `pockets/` and `embeddings/`.
See [DATA.md](DATA.md) for the full layout and download instructions.

## Data Repository

The complete PocketEval data package is hosted separately on Hugging Face:

<https://huggingface.co/datasets/xyx-2523/PocketEval>

Step-by-step download and layout instructions, including how to place the extracted
structures so the visualisation works immediately, are in [DATA.md](DATA.md).

## Licensing

Original software in this repository is available under the MIT License in
`LICENSE-CODE`. The bundled data and derived representations are not covered by that
software license; their use is described in `LICENSE-DATA` and remains subject to the
HiQBind distribution (MIT, <https://github.com/THGLab/HiQBind>), the MaSIF software and
other applicable third-party licenses.

`static/vendor/3Dmol-min.js` is redistributed under its own BSD-3-Clause license; the
full text ships alongside it in `static/vendor/3Dmol-min.js.LICENSE.txt`.

## Resource bundle

`server.py` reads four files from the resource root:

| File | Content |
|---|---|
| `dataset_index.json` | one record per pocket (structure/ligand/embedding metadata + split) |
| `cluster_assignments.json` | `cluster_label` (MaSIF pocket-similarity connected component) and `projection_2d` (PCA of the 80-dim descriptor) |
| `benchmark_pocket_split.csv` | released partition + affinity annotations |
| `summary.json` | dataset-level counts |

The released benchmark table carries the source column names; the server maps the fields it
needs internally, so no duplicate alias columns are shipped.

The per-pocket structures (`pockets/<pocket_id>/`) and descriptors
(`embeddings/<pocket_id>.npy`) are distributed separately. The complex structure served at
`/api/structure/<pocket_id>/complex.pdb` is composed from `pocket_protein.pdb` +
`ligand.pdb` at request time, so no per-pocket complex file is stored.

Rebuild the whole bundle with `build_hiqbind_bundle.py` (see its module docstring).
