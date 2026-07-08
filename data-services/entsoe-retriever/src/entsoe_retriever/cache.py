from __future__ import annotations

import time
from pathlib import Path

import duckdb
import polars as pl


class ParquetCache:
    """A tiny local cache: writes query results to Parquet files and serves
    them back through DuckDB while still fresh. No server, no docker — just
    files on disk, queried in-process.
    """

    def __init__(self, cache_dir: str | Path, ttl_seconds: int = 3600) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds

    def _path_for(self, key: str) -> Path:
        return self.cache_dir / f"{key}.parquet"

    def get(self, key: str) -> pl.DataFrame | None:
        path = self._path_for(key)
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > self.ttl_seconds:
            return None
        with duckdb.connect() as con:
            return con.execute("SELECT * FROM read_parquet(?)", [str(path)]).pl()

    def set(self, key: str, frame: pl.DataFrame) -> None:
        frame.write_parquet(self._path_for(key))

    def invalidate(self, key: str) -> None:
        path = self._path_for(key)
        if path.exists():
            path.unlink()
