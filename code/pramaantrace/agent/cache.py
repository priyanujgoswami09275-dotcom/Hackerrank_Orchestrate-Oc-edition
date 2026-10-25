"""Local SQLite cache for successful model responses."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Mapping


def cache_key(
    endpoint: str,
    model: str,
    prompt_version: str,
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    *,
    response_format: Mapping[str, Any] | None = None,
) -> str:
    """Hash all request semantics without ever including an API credential."""
    canonical = json.dumps(
        {
            "endpoint": endpoint,
            "model": model,
            "prompt_version": prompt_version,
            "tools": tools,
            "messages": messages,
            "response_format": response_format,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ResponseCache:
    """A response cache whose default location is outside the repository."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS model_responses ("
                "cache_key TEXT PRIMARY KEY, response_json TEXT NOT NULL)"
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def get(self, key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response_json FROM model_responses WHERE cache_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        decoded = json.loads(row[0])
        if not isinstance(decoded, dict):
            raise ValueError("cached model response must be a JSON object")
        return decoded

    def put(self, key: str, response: dict[str, Any]) -> None:
        serialized = json.dumps(
            response,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO model_responses(cache_key, response_json) "
                "VALUES (?, ?)",
                (key, serialized),
            )
