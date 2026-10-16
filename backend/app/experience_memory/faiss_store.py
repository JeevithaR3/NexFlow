"""FAISS index management (similarity search only - the experiences themselves live in SQLite).

The index is ``IndexIDMap2(IndexFlatL2)`` keyed by the experience table's integer ``faiss_id``.
It is persisted atomically (temp file + rename) next to a small metadata file, and can always be
rebuilt from the database, which is the source of truth.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import faiss
import numpy as np


class FaissStore:
    def __init__(self, directory: Path, dim: int, schema: str) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.dim = dim
        self.schema = schema
        self.index_path = self.dir / "experience.faiss"
        self.meta_path = self.dir / "index_meta.json"
        self._lock = threading.RLock()
        self._index = self._new_index()

    def _new_index(self):
        return faiss.IndexIDMap2(faiss.IndexFlatL2(self.dim))

    @property
    def ntotal(self) -> int:
        return int(self._index.ntotal)

    def ids(self) -> set[int]:
        with self._lock:
            return set(int(i) for i in faiss.vector_to_array(self._index.id_map))

    def rebuild(self, ids: list[int], vectors: np.ndarray) -> None:
        with self._lock:
            idx = self._new_index()
            if len(ids):
                v = np.ascontiguousarray(vectors, dtype=np.float32).reshape(len(ids), self.dim)
                idx.add_with_ids(v, np.asarray(ids, dtype=np.int64))
            self._index = idx
            self.save()

    def add(self, faiss_id: int, vector: np.ndarray) -> None:
        v = np.ascontiguousarray(vector, dtype=np.float32).reshape(1, self.dim)
        with self._lock:
            self._index.add_with_ids(v, np.array([faiss_id], dtype=np.int64))
            self.save()

    def search(self, vector: np.ndarray, k: int) -> list[tuple[int, float]]:
        """Return [(faiss_id, squared_l2_distance)] ordered by increasing distance."""
        with self._lock:
            if self._index.ntotal == 0:
                return []
            k = min(k, self._index.ntotal)
            d, i = self._index.search(np.ascontiguousarray(vector, dtype=np.float32).reshape(1, self.dim), k)
        return [(int(a), float(b)) for a, b in zip(i[0], d[0]) if a >= 0]

    def save(self) -> None:
        with self._lock:
            tmp = self.index_path.with_suffix(".faiss.tmp")
            faiss.write_index(self._index, str(tmp))
            os.replace(tmp, self.index_path)
            meta = {
                "dim": self.dim,
                "schema": self.schema,
                "count": self.ntotal,
                "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "index_type": "IndexIDMap2(IndexFlatL2)",
            }
            tmp_m = self.meta_path.with_suffix(".tmp")
            tmp_m.write_text(json.dumps(meta), encoding="utf-8")
            os.replace(tmp_m, self.meta_path)

    def load(self) -> bool:
        """Load the persisted index if it exists and matches dimension and schema."""
        if not (self.index_path.exists() and self.meta_path.exists()):
            return False
        try:
            meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
            if meta.get("dim") != self.dim or meta.get("schema") != self.schema:
                return False
            idx = faiss.read_index(str(self.index_path))
            if idx.d != self.dim:
                return False
            with self._lock:
                self._index = idx
            return True
        except (OSError, ValueError, RuntimeError):
            return False
