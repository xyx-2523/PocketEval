# Getting the data

The release is split across two hosts.

| Where | What |
|---|---|
| **GitHub** (this repository) | the web application only: `server.py`, `static/`, `build_hiqbind_bundle.py`, packaging scripts |
| **HuggingFace** [`xyx-2523/PocketEval`](https://huggingface.co/datasets/xyx-2523/PocketEval) | the data: four metadata files plus `pocket_structures.tar.gz` |

## Layout that `server.py` expects

```text
resource_bundle/
|-- dataset_index.json          one record per pocket
|-- cluster_assignments.json    cluster_label + 2D projection
|-- benchmark_pocket_split.csv  released partition + affinity annotations
|-- summary.json                dataset-level counts
|-- pockets/
|   `-- <pocket_id>/
|       |-- pocket_protein.pdb
|       |-- ligand.sdf
|       |-- ligand.pdb
|       `-- metadata.json
`-- embeddings/
    `-- <pocket_id>.npy         80-dim mean-pooled MaSIF descriptor
```

## Setup

1. Clone this repository.

2. Download the four metadata files **and** `pocket_structures.tar.gz` from HuggingFace
   into the `resource_bundle/` directory.

3. Extract the archive **into `resource_bundle/`** so that `pockets/` and `embeddings/`
   land in the right place:

   ```bash
   tar -xzf pocket_structures.tar.gz -C resource_bundle/
   ```

   The archive's top-level entries are `pockets/` and `embeddings/`, so no extra
   `--strip-components` is needed.

4. Start the server:

   ```bash
   python server.py --host 127.0.0.1 --port 8766
   ```

   The console prints `Pocket web platform ready on http://0.0.0.0:8766 with 32230 pockets`.

5. Open <http://127.0.0.1:8766>. Pocket search, split filtering, cluster filtering,
   the 2D embedding projection and the 3D structure viewer are all available once the
   archive has been extracted.

### Keeping the data outside the application directory

The extracted structures are ~9 GB across ~190,000 files. The whole resource bundle can
live anywhere; point the server at it:

```bash
python server.py --resource-root /path/to/pocketeval --port 8766
```

`<resource-root>` must contain the four metadata files plus `pockets/` and `embeddings/`;
the individual paths are then `<resource-root>/dataset_index.json` and so on. Passing the
four metadata files with the extracted structures is the only requirement — the directory
does not have to be the one next to `server.py`.

If a structure request fails, the API returns a JSON body naming the resolved resource
root and the `tar` command needed to populate it, so a partially set-up installation is
easy to diagnose.

## Verifying the download

```bash
sha256sum -c SHA256SUMS.txt
```

## Notes

* `/api/structure/<pocket_id>/complex.pdb` (used by the 3D viewer for the pocket complex)
  is composed at request time from `pocket_protein.pdb` + `ligand.pdb`; no separate
  complex file is distributed.
* Ligand property panels (molecular weight, logP, TPSA, ...) are computed by RDKit from
  `ligand.sdf`; install `rdkit` (see `requirements.txt`) to enable them.

## Rebuilding the bundle from MaSIF outputs

If you have the raw per-pocket MaSIF patch outputs, `build_hiqbind_bundle.py` regenerates the
four metadata files and the `pockets/` + `embeddings/` payload. See its module docstring
for the exact inputs.
