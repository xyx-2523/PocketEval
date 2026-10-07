#!/usr/bin/env python3
import argparse
import csv
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from rdkit import Chem
    from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors
except Exception:
    Chem = None
    Descriptors = None
    Crippen = None
    Lipinski = None
    rdMolDescriptors = None


RESOURCE_ROOT = Path(__file__).resolve().parent / "resource_bundle"
DEFAULT_PSQL_BIN = "psql"
DEFAULT_DB_NAME = "activitydb_test"
DEFAULT_DB_PORT = 55432
MAX_PAGE_SIZE = 200
HIGH_QUALITY_TYPES = {"IC50", "KI", "KD", "EC50", "POTENCY"}
RELEASED_SPLIT_NAME = "Pocket split"

# Logical field -> benchmark-table column. The released table uses the source column
# names, so no duplicate alias columns are shipped. The second entry of each tuple is
# accepted as a fallback for older bundles.
BENCHMARK_COLUMNS = {
    "pX": ("pX",),
    "pdb_id": ("PDBID", "pdb_id"),
    "ligand_id": ("Ligand Name", "ligand_id"),
    "ligand_smiles": ("Ligand SMILES", "ligand_smiles"),
    "standard_type": ("Binding Affinity Measurement", "standard_type"),
    "standard_units": ("Binding Affinity Unit", "standard_units"),
    "standard_value": ("Binding Affinity Value", "standard_value"),
    "relation": ("Binding Affinity Sign", "relation"),
    "inchi_key": ("inchi_key",),
}


def benchmark_field(row, field):
    """Read a logical field from a benchmark row, tolerating either column spelling."""
    for column in BENCHMARK_COLUMNS[field]:
        value = row.get(column)
        if value not in (None, ""):
            return value
    return ""


def _json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        original_error = exc

    stripped = text.lstrip()
    if not stripped.startswith("["):
        raise original_error

    decoder = json.JSONDecoder()
    items = []
    idx = text.find("[") + 1
    length = len(text)

    while idx < length:
        while idx < length and text[idx] in " \r\n\t":
            idx += 1
        if idx >= length or text[idx] == "]":
            break
        try:
            item, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            break
        items.append(item)
        idx = end
        while idx < length and text[idx] in " \r\n\t":
            idx += 1
        if idx < length and text[idx] == ",":
            idx += 1
            continue
        if idx < length and text[idx] == "]":
            break
    if items:
        return items
    raise original_error


def _to_number(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_literal(value):
    return str(value).replace("'", "''")

def _copy_to_ascii_temp(source_path):
    suffix = Path(source_path).suffix or ""
    fd, temp_path = tempfile.mkstemp(prefix="pocketeval_", suffix=suffix)
    os.close(fd)
    shutil.copyfile(source_path, temp_path)
    return temp_path


class PocketStore:
    def __init__(self, index_file, cluster_file, benchmark_file=None, resource_root=None):
        self.index_file = index_file
        self.cluster_file = cluster_file
        self.benchmark_file = benchmark_file
        self.resource_root = Path(resource_root) if resource_root else RESOURCE_ROOT
        self.records_by_id = {}
        self.list_records = []
        self.points = []
        self.cluster_counts = {}
        self.split_counts = {}
        self.summary = {}
        self.activity_by_pocket = {}
        self.activity_summary = {
            "matched_pocket_count": 0,
            "matched_unique_pdb_count": 0,
            "activity_record_links": 0,
            "standardized_pocket_count": 0,
            "high_quality_pocket_count": 0,
        }
        self.status_items = [
            {
                "title": "Pocket Decomposition",
                "state": "implemented",
                "detail": "Pocket-level structural records are organized and exposed as downloadable resource entries.",
            },
            {
                "title": "Embedding Space Analysis",
                "state": "implemented",
                "detail": "Released projection and clustering annotations are available for embedding-space browsing.",
            },
            {
                "title": "Geometry-Aware Split",
                "state": "implemented",
                "detail": "PocketEval distributes the released MaSIF 80D Pocket split with train/validation/test labels.",
            },
            {
                "title": "Pocket-Level Bioactivity Mapping",
                "state": "implemented",
                "detail": "Pocket-linked bioactivity summaries are available for interactive browsing when activity mappings are present.",
            },
        ]
        self.load()

    def _build_local_download_paths(self, pocket_id):
        pocket_dir = self.resource_root / "pockets" / pocket_id
        return {
            "embedding_npy": str(self.resource_root / "embeddings" / f"{pocket_id}.npy"),
            "pocket_protein_pdb": str(pocket_dir / "pocket_protein.pdb"),
            "ligand_pdb": str(pocket_dir / "ligand.pdb"),
            "ligand_sdf": str(pocket_dir / "ligand.sdf"),
            "metadata_json": str(pocket_dir / "metadata.json"),
        }

    def _load_split_map(self):
        split_map = {}
        if not self.benchmark_file or not os.path.isfile(self.benchmark_file):
            return split_map
        with open(self.benchmark_file, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                pocket_id = row.get("pocket_id") or ""
                split = row.get("split") or ""
                if pocket_id and split:
                    split_map[pocket_id] = split
        return split_map

    def _load_benchmark_rows(self):
        benchmark_rows = {}
        if not self.benchmark_file or not os.path.isfile(self.benchmark_file):
            return benchmark_rows
        with open(self.benchmark_file, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                pocket_id = row.get("pocket_id") or ""
                if pocket_id:
                    benchmark_rows[pocket_id] = row
        return benchmark_rows

    def _load_activity_export(self):
        self.activity_by_pocket = {}
        self.activity_summary = {
            "matched_pocket_count": 0,
            "matched_unique_pdb_count": 0,
            "activity_record_links": 0,
            "standardized_pocket_count": 0,
            "high_quality_pocket_count": 0,
        }
        if not self.benchmark_file or not os.path.isfile(self.benchmark_file):
            return

        matched_pdbs = set()
        standardized_pockets = set()
        high_quality_pockets = set()

        with open(self.benchmark_file, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                pocket_id = row.get("pocket_id") or ""
                if not pocket_id:
                    continue
                px = _to_number(benchmark_field(row, "pX"))
                standard_type = (benchmark_field(row, "standard_type") or "").upper()
                standard_value = benchmark_field(row, "standard_value")
                standard_units = benchmark_field(row, "standard_units")
                relation = benchmark_field(row, "relation")
                inchi_key = benchmark_field(row, "inchi_key")
                ligand_smiles = benchmark_field(row, "ligand_smiles")
                summary = self.activity_by_pocket.setdefault(
                    pocket_id,
                    {
                        "pocket_id": pocket_id,
                        "pdb_id": benchmark_field(row, "pdb_id"),
                        "ligand_id": benchmark_field(row, "ligand_id"),
                        "activity_group_count": 0,
                        "activity_total_count": 0,
                        "standardized_group_count": 0,
                        "high_quality_group_count": 0,
                        "min_px": None,
                        "max_px": None,
                        "records": [],
                    },
                )
                summary["activity_group_count"] += 1
                summary["activity_total_count"] += 1
                summary["records"].append(
                    {
                        "standard_type": standard_type or None,
                        "standard_relation": relation or None,
                        "standard_value": standard_value or None,
                        "standard_units": standard_units or None,
                        "px_value": f"{px:.6f}" if px is not None else None,
                        "inchi_key": inchi_key or None,
                        "ligand_smiles": ligand_smiles or None,
                        "source": "benchmark_file",
                    }
                )
                if px is not None:
                    summary["standardized_group_count"] += 1
                    standardized_pockets.add(pocket_id)
                    summary["min_px"] = px if summary["min_px"] is None else min(summary["min_px"], px)
                    summary["max_px"] = px if summary["max_px"] is None else max(summary["max_px"], px)
                if px is not None and standard_type in HIGH_QUALITY_TYPES and relation == "=":
                    summary["high_quality_group_count"] += 1
                    high_quality_pockets.add(pocket_id)
                matched_pdbs.add(summary["pdb_id"])

        for summary in self.activity_by_pocket.values():
            summary["has_activity"] = summary["activity_group_count"] > 0
            summary["has_standardized_activity"] = summary["standardized_group_count"] > 0
            summary["has_high_quality_activity"] = summary["high_quality_group_count"] > 0
            self.activity_summary["activity_record_links"] += summary["activity_total_count"]

        self.activity_summary["matched_pocket_count"] = len(self.activity_by_pocket)
        self.activity_summary["matched_unique_pdb_count"] = len(matched_pdbs)
        self.activity_summary["standardized_pocket_count"] = len(standardized_pockets)
        self.activity_summary["high_quality_pocket_count"] = len(high_quality_pockets)

    def load(self):
        index_records = _read_json(self.index_file)
        cluster_records = _read_json(self.cluster_file)
        split_map = self._load_split_map()
        benchmark_rows = self._load_benchmark_rows()
        self._load_activity_export()
        cluster_by_id = {item["pocket_id"]: item for item in cluster_records}
        pdb_ids = set()
        ligand_ids = set()
        cluster_counter = Counter()
        split_counter = Counter()

        for record in index_records:
            pocket_id = record["pocket_id"]
            if benchmark_rows and pocket_id not in benchmark_rows:
                continue
            cluster_info = cluster_by_id.get(pocket_id, {})
            split_label = split_map.get(pocket_id)
            benchmark_row = benchmark_rows.get(pocket_id, {})
            ligand = record.get("ligand", {})
            activity = self.activity_by_pocket.get(
                pocket_id,
                {
                    "activity_group_count": 0,
                    "activity_total_count": 0,
                    "standardized_group_count": 0,
                    "high_quality_group_count": 0,
                    "min_px": None,
                    "max_px": None,
                    "has_activity": False,
                    "has_standardized_activity": False,
                    "has_high_quality_activity": False,
                },
            )
            merged = dict(record)
            merged["cluster"] = {
                "cluster_label": cluster_info.get("cluster_label"),
                "projection_2d": cluster_info.get("projection_2d", [0.0, 0.0]),
            }
            merged["split"] = split_label
            merged["benchmark"] = benchmark_row
            merged["local_paths"] = self._build_local_download_paths(pocket_id)
            merged["activity_summary"] = activity
            self.records_by_id[pocket_id] = merged
            pdb_ids.add(record["pdb_id"])
            ligand_ids.add(ligand.get("resname", ""))
            label = cluster_info.get("cluster_label")
            if label is not None:
                cluster_counter[label] += 1
            if split_label:
                split_counter[split_label] += 1
            point = {
                "pocket_id": pocket_id,
                "pdb_id": record["pdb_id"],
                "ligand_resname": ligand.get("resname"),
                "ligand_chain": ligand.get("chain_id"),
                "cluster_label": label,
                "split": split_label,
                "projection_2d": cluster_info.get("projection_2d", [0.0, 0.0]),
                "protein_residue_count": record.get("protein_residue_count"),
                "status": record.get("status"),
                "has_activity": activity["has_activity"],
                "has_standardized_activity": activity["has_standardized_activity"],
                "has_high_quality_activity": activity["has_high_quality_activity"],
                "activity_total_count": activity["activity_total_count"],
                "max_px": activity["max_px"],
            }
            self.points.append(point)
            self.list_records.append(
                {
                    "pocket_id": pocket_id,
                    "pdb_id": record["pdb_id"],
                    "ligand_resname": ligand.get("resname"),
                    "ligand_chain": ligand.get("chain_id"),
                    "ligand_resseq": ligand.get("resseq"),
                    "cluster_label": label,
                    "split": split_label,
                    "projection_2d": cluster_info.get("projection_2d", [0.0, 0.0]),
                    "protein_residue_count": record.get("protein_residue_count"),
                    "pX": benchmark_field(benchmark_row, "pX") or None,
                    "patch_count": record.get("embedding", {}).get("patch_count"),
                    "embedding_dim": record.get("embedding", {}).get("embedding_dim"),
                    "status": record.get("status"),
                    "created_at_utc": record.get("created_at_utc"),
                    "activity_total_count": activity["activity_total_count"],
                    "max_px": activity["max_px"],
                    "min_px": activity["min_px"],
                    "has_activity": activity["has_activity"],
                    "has_standardized_activity": activity["has_standardized_activity"],
                    "has_high_quality_activity": activity["has_high_quality_activity"],
                }
            )

        self.list_records.sort(key=lambda item: item["pocket_id"])
        self.cluster_counts = dict(sorted(cluster_counter.items(), key=lambda item: item[0]))
        self.split_counts = dict(split_counter)
        embedding_dims = {
            record.get("embedding", {}).get("embedding_dim")
            for record in index_records
            if record.get("embedding", {}).get("embedding_dim")
        }
        self.summary = {
            "total_pockets": len(self.list_records),
            "total_pdb_entries": len(pdb_ids),
            "unique_ligand_codes": len([item for item in ligand_ids if item]),
            "cluster_count": len(self.cluster_counts),
            "embedding_dim": sorted(embedding_dims)[-1] if embedding_dims else None,
            "released_split_name": RELEASED_SPLIT_NAME,
            "released_split_counts": self.split_counts,
            "matched_pocket_count": self.activity_summary["matched_pocket_count"],
            "matched_unique_pdb_count": self.activity_summary["matched_unique_pdb_count"],
            "standardized_pocket_count": self.activity_summary["standardized_pocket_count"],
            "high_quality_pocket_count": self.activity_summary["high_quality_pocket_count"],
            "activity_record_links": self.activity_summary["activity_record_links"],
            "index_file": self.index_file,
            "cluster_file": self.cluster_file,
            "benchmark_file": self.benchmark_file,
            "resource_root": str(self.resource_root),
        }

    def search(self, query="", cluster=None, split=None, activity_mode="all", affinity_mode="with_affinity", page=1, page_size=40):
        query = (query or "").strip().lower()
        page_size = max(1, min(page_size, MAX_PAGE_SIZE))
        page = max(1, page)
        rows = self.list_records

        if query:
            rows = [
                row
                for row in rows
                if query in row["pocket_id"].lower()
                or query in row["pdb_id"].lower()
                or query in (row.get("ligand_resname") or "").lower()
            ]

        if cluster is not None:
            rows = [row for row in rows if row.get("cluster_label") == cluster]

        if split not in (None, "", "all"):
            rows = [row for row in rows if row.get("split") == split]

        if activity_mode == "active":
            rows = [row for row in rows if row.get("has_activity")]
        elif activity_mode == "standardized":
            rows = [row for row in rows if row.get("has_standardized_activity")]
        elif activity_mode == "high_quality":
            rows = [row for row in rows if row.get("has_high_quality_activity")]

        if affinity_mode == "with_affinity":
            rows = [row for row in rows if row.get("has_standardized_activity")]
        elif affinity_mode == "without_affinity":
            rows = [row for row in rows if not row.get("has_standardized_activity")]

        total = len(rows)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "items": rows[start:end],
        }

    def get_record(self, pocket_id):
        return self.records_by_id.get(pocket_id)


class PocketRequestHandler(BaseHTTPRequestHandler):
    server_version = "PocketWeb/0.1"

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/":
            return self._serve_static("index.html")
        if path.startswith("/pocket/"):
            return self._serve_static("detail.html")
        if path.startswith("/static/"):
            return self._serve_static(path[len("/static/"):])
        if path == "/api/summary":
            return self._send_json(self.server.store.summary)
        if path == "/api/quality-info":
            return self._send_json(
                {
                    "items": [
                        {
                            "field": "standard_type",
                            "meaning": "The biological readout type, such as IC50, Ki, Kd, EC50, or Potency.",
                        },
                        {
                            "field": "standard_units",
                            "meaning": "The standardized unit for the reported measurement, typically nM or uM.",
                        },
                        {
                            "field": "px_value",
                            "meaning": "The recorded binding affinity on a log10 molar scale, as shipped in the released benchmark table. Lower values correspond to tighter binding.",
                        },
                        {
                            "field": "released_split",
                            "meaning": "PocketEval distributes the released MaSIF 80D Pocket split with train, validation, and test labels for benchmark reuse.",
                        },
                    ]
                }
            )
        if path == "/api/status":
            return self._send_json({"items": self.server.store.status_items})
        if path == "/api/benchmark-file":
            return self._serve_file(self.server.store.benchmark_file, "text/csv; charset=utf-8")
        if path == "/api/exports/active-pockets.csv":
            # The benchmark table already is the canonical export; no separate copy is
            # shipped.
            return self._serve_file(self.server.store.benchmark_file, "text/csv; charset=utf-8")
        if path == "/api/cluster-stats":
            items = [
                {"cluster_label": label, "count": count}
                for label, count in self.server.store.cluster_counts.items()
            ]
            return self._send_json({"items": items})
        if path == "/api/points":
            return self._send_json({"items": self.server.store.points})
        if path == "/api/pockets":
            cluster = query.get("cluster", [None])[0]
            cluster = int(cluster) if cluster not in (None, "", "all") else None
            split = query.get("split", ["all"])[0]
            page = int(query.get("page", ["1"])[0])
            page_size = int(query.get("page_size", ["40"])[0])
            search_query = query.get("q", [""])[0]
            activity_mode = query.get("activity", ["all"])[0]
            affinity_mode = query.get("affinity", ["with_affinity"])[0]
            return self._send_json(
                self.server.store.search(
                    query=search_query,
                    cluster=cluster,
                    split=split,
                    activity_mode=activity_mode,
                    affinity_mode=affinity_mode,
                    page=page,
                    page_size=page_size,
                )
            )
        if path.startswith("/api/pocket/"):
            pocket_id = urllib.parse.unquote(path.split("/api/pocket/", 1)[1])
            record = self.server.store.get_record(pocket_id)
            if not record:
                return self._send_json({"error": "Pocket not found"}, status=HTTPStatus.NOT_FOUND)
            payload = dict(record)
            payload["project_status"] = {
                "split": "implemented",
                "bioactivity_mapping": "implemented",
            }
            payload["ligand_properties"] = self.server.get_ligand_properties(record)
            payload["local_benchmark_activity"] = {
                "pX": benchmark_field(record.get("benchmark") or {}, "pX") or None,
                "split": record.get("split"),
                "source": "benchmark_file",
            }
            payload["downloads"] = {
                "embedding_npy": f"/api/embedding/{urllib.parse.quote(pocket_id)}.npy",
                "complex_pdb": f"/api/structure/{urllib.parse.quote(pocket_id)}/complex.pdb",
                "protein_pdb": f"/api/structure/{urllib.parse.quote(pocket_id)}/protein.pdb",
                "ligand_pdb": f"/api/structure/{urllib.parse.quote(pocket_id)}/ligand.pdb",
            }
            return self._send_json(payload)
        if path.startswith("/api/activity/"):
            pocket_id = urllib.parse.unquote(path.split("/api/activity/", 1)[1])
            record = self.server.store.get_record(pocket_id)
            if not record:
                return self._send_json({"error": "Pocket not found"}, status=HTTPStatus.NOT_FOUND)
            return self._send_json(self.server.lookup_activity(record))
        if path.startswith("/api/embedding/"):
            pocket_id = urllib.parse.unquote(path.split("/api/embedding/", 1)[1]).rsplit(".npy", 1)[0]
            record = self.server.store.get_record(pocket_id)
            if not record:
                return self._send_json({"error": "Pocket not found"}, status=HTTPStatus.NOT_FOUND)
            embedding_path = record.get("local_paths", {}).get("embedding_npy")
            if not embedding_path or not os.path.isfile(embedding_path):
                return self._send_json(self._missing_structure(record), status=HTTPStatus.NOT_FOUND)
            return self._serve_file(embedding_path, "application/octet-stream")
        if path.startswith("/api/structure/"):
            return self._serve_structure(path)

        return self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stdout.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))

    def _send_json(self, payload, status=HTTPStatus.OK):
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, relative_path):
        if not relative_path:
            relative_path = "index.html"
        safe_path = os.path.normpath(relative_path).lstrip("/\\")
        full_path = os.path.join(self.server.static_dir, safe_path)
        return self._serve_file(full_path)

    def _serve_file(self, file_path, content_type=None):
        if not file_path or not os.path.isfile(file_path):
            return self._send_json({"error": "File not found"}, status=HTTPStatus.NOT_FOUND)
        with open(file_path, "rb") as handle:
            body = handle.read()
        mime, _ = mimetypes.guess_type(file_path)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _missing_structure(self, record):
        """Actionable 404: the metadata bundle can be present without the structures."""
        root = self.server.store.resource_root
        return {
            "error": "Structure file missing",
            "pocket_id": record.get("pocket_id"),
            "resource_root": str(root),
            "hint": ("The per-pocket structures are a separate download. Unpack "
                     "pocket_structures.tar.gz into the resource root, i.e. "
                     f"tar -xzf pocket_structures.tar.gz -C \"{root}\", so that "
                     "pockets/ and embeddings/ sit next to dataset_index.json."),
        }

    def _serve_structure(self, path):
        suffix = path.split("/api/structure/", 1)[1]
        parts = suffix.split("/")
        if len(parts) != 2:
            return self._send_json({"error": "Invalid structure path"}, status=HTTPStatus.BAD_REQUEST)
        pocket_id = urllib.parse.unquote(parts[0])
        filename = parts[1]
        kind = filename.rsplit(".", 1)[0]
        record = self.server.store.get_record(pocket_id)
        if not record:
            return self._send_json({"error": "Pocket not found"}, status=HTTPStatus.NOT_FOUND)

        key_by_kind = {
            "complex": None,
            "protein": "pocket_protein_pdb",
            "ligand": "ligand_pdb",
        }
        path_key = key_by_kind.get(kind)
        if kind not in key_by_kind:
            return self._send_json({"error": "Unsupported structure kind"}, status=HTTPStatus.BAD_REQUEST)
        local_paths = record.get("local_paths", {})
        if kind == "complex":
            # Composed on the fly: storing a separate complex PDB per pocket would
            # roughly double the bundle size for no information gain.
            parts = []
            for key in ("pocket_protein_pdb", "ligand_pdb"):
                part = local_paths.get(key)
                if part and os.path.isfile(part):
                    with open(part, "rb") as handle:
                        parts.append(handle.read())
            if not parts:
                return self._send_json(self._missing_structure(record), status=HTTPStatus.NOT_FOUND)
            body = b"".join(parts)
        else:
            file_path = local_paths.get(path_key)
            if not file_path or not os.path.isfile(file_path):
                return self._send_json(self._missing_structure(record), status=HTTPStatus.NOT_FOUND)
            with open(file_path, "rb") as handle:
                body = handle.read()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "chemical/x-pdb; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class PocketWebServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, store, static_dir, psql_bin, db_name, db_port):
        super().__init__(server_address, handler_class)
        self.store = store
        self.static_dir = static_dir
        self.psql_bin = psql_bin
        self.db_name = db_name
        self.db_port = db_port
        self.ligand_property_cache = {}

    def _run_sql(self, query):
        command = [
            "runuser",
            "-u",
            "pgsvc",
            "--",
            self.psql_bin,
            "-p",
            str(self.db_port),
            "-d",
            self.db_name,
            "-F",
            "\t",
            "-At",
            "-c",
            query,
        ]
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        return [line for line in completed.stdout.splitlines() if line.strip()]

    def get_ligand_properties(self, record):
        pocket_id = record["pocket_id"]
        if pocket_id in self.ligand_property_cache:
            return self.ligand_property_cache[pocket_id]

        local_paths = record.get("local_paths", {})
        ligand_pdb_path = local_paths.get("ligand_pdb") or record.get("paths", {}).get("ligand_pdb")
        ligand_sdf_path = local_paths.get("ligand_sdf")
        fallback = {
            "status": "unavailable",
            "source": "resource_bundle/pockets/{}/ligand.sdf".format(pocket_id) if ligand_sdf_path else "resource_bundle/pockets/{}/ligand.pdb".format(pocket_id),
            "reason": "Ligand properties are unavailable in the current local environment.",
        }
        if not Chem:
            self.ligand_property_cache[pocket_id] = fallback
            return fallback

        mol = None
        source_label = None
        temp_paths = []
        try:
            if ligand_sdf_path and os.path.isfile(ligand_sdf_path):
                temp_sdf_path = _copy_to_ascii_temp(ligand_sdf_path)
                temp_paths.append(temp_sdf_path)
                supplier = Chem.SDMolSupplier(temp_sdf_path, removeHs=False)
                if supplier and len(supplier) > 0:
                    mol = supplier[0]
                if mol is not None:
                    source_label = "resource_bundle/pockets/{}/ligand.sdf".format(pocket_id)
            if mol is None and ligand_pdb_path and os.path.isfile(ligand_pdb_path):
                temp_pdb_path = _copy_to_ascii_temp(ligand_pdb_path)
                temp_paths.append(temp_pdb_path)
                mol = Chem.MolFromPDBFile(temp_pdb_path, sanitize=True, removeHs=False)
                if mol is None:
                    mol = Chem.MolFromPDBFile(temp_pdb_path, sanitize=False, removeHs=False)
                if mol is not None:
                    source_label = "resource_bundle/pockets/{}/ligand.pdb".format(pocket_id)
            if mol is None:
                self.ligand_property_cache[pocket_id] = fallback
                return fallback

            props = {
                "status": "computed",
                "source": source_label or fallback["source"],
                "formula": rdMolDescriptors.CalcMolFormula(mol),
                "molecular_weight": round(float(Descriptors.MolWt(mol)), 3),
                "logp": round(float(Crippen.MolLogP(mol)), 3),
                "tpsa": round(float(rdMolDescriptors.CalcTPSA(mol)), 3),
                "h_donors": int(Lipinski.NumHDonors(mol)),
                "h_acceptors": int(Lipinski.NumHAcceptors(mol)),
                "rotatable_bonds": int(Lipinski.NumRotatableBonds(mol)),
                "ring_count": int(rdMolDescriptors.CalcNumRings(mol)),
                "heavy_atom_count": int(mol.GetNumHeavyAtoms()),
                "atom_count": int(mol.GetNumAtoms()),
            }
            self.ligand_property_cache[pocket_id] = props
            return props
        except Exception:
            failed = dict(fallback)
            failed["reason"] = "Ligand file is present, but RDKit could not parse it in the current local environment."
            self.ligand_property_cache[pocket_id] = failed
            return failed
        finally:
            for temp_path in temp_paths:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def lookup_activity(self, record):
        activity = record.get("activity_summary") or {}
        strict_records = list(activity.get("records") or [])
        type_counter = Counter()
        standardized_count = 0
        high_quality_count = 0
        for item in strict_records:
            standard_type = item.get("standard_type") or ""
            relation = item.get("standard_relation") or ""
            px_value = item.get("px_value")
            if standard_type:
                type_counter[standard_type] += 1
            if px_value not in (None, ""):
                standardized_count += 1
            if standard_type.upper() in HIGH_QUALITY_TYPES and relation == "=" and px_value not in (None, ""):
                high_quality_count += 1

        benchmark = record.get("benchmark") or {}
        fallback_px = benchmark.get("pX")

        return {
            "status": "implemented",
            "source": "benchmark_file",
            "pocket_id": record["pocket_id"],
            "pdb_id": record["pdb_id"],
            "ligand_id": record.get("ligand", {}).get("resname"),
            "strict_record_count": len(strict_records),
            "standardized_record_count": standardized_count,
            "high_quality_record_count": high_quality_count,
            "standard_type_breakdown": dict(type_counter),
            "strict_records": strict_records,
            "local_pX": fallback_px,
            "local_split": record.get("split"),
            "note": "Local activity table is assembled from the bundled benchmark CSV and does not depend on ActivityDB.",
            "error": None,
        }


def build_parser():
    parser = argparse.ArgumentParser(description="Pocket-centric benchmark web platform")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8766,
                        help="TCP port to listen on (default: 8766)")
    parser.add_argument("--resource-root", default=str(RESOURCE_ROOT),
                        help="directory holding the bundle: the metadata files plus "
                             "pockets/ and embeddings/")
    parser.add_argument("--index-file", default=None,
                        help="default: <resource-root>/dataset_index.json")
    parser.add_argument("--cluster-file", default=None,
                        help="default: <resource-root>/cluster_assignments.json")
    parser.add_argument("--benchmark-file", default=None,
                        help="default: <resource-root>/benchmark_pocket_split.csv")
    parser.add_argument("--static-dir", default=os.path.join(os.path.dirname(__file__), "static"))
    parser.add_argument("--psql-bin", default=DEFAULT_PSQL_BIN)
    parser.add_argument("--db-name", default=DEFAULT_DB_NAME)
    parser.add_argument("--db-port", type=int, default=DEFAULT_DB_PORT)
    return parser


def main():
    args = build_parser().parse_args()
    resource_root = Path(args.resource_root).expanduser().resolve()
    index_file = args.index_file or str(resource_root / "dataset_index.json")
    cluster_file = args.cluster_file or str(resource_root / "cluster_assignments.json")
    benchmark_file = args.benchmark_file or str(resource_root / "benchmark_pocket_split.csv")
    store = PocketStore(
        index_file,
        cluster_file,
        benchmark_file=benchmark_file,
        resource_root=resource_root,
    )
    server = PocketWebServer(
        (args.host, args.port),
        PocketRequestHandler,
        store=store,
        static_dir=args.static_dir,
        psql_bin=args.psql_bin,
        db_name=args.db_name,
        db_port=args.db_port,
    )
    print(
        "Pocket web platform ready on http://{host}:{port} with {count} pockets".format(
            host=args.host,
            port=args.port,
            count=store.summary["total_pockets"],
        ),
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()







