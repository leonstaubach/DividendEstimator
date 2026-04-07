from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class FileCache:
    def __init__(self, cache_file: Path, ttl_seconds: int = 86400) -> None:
        self.cache_file = cache_file
        self.ttl = timedelta(seconds=ttl_seconds)

    def get(self, key: str) -> Any | None:
        payload = self._load_payload()
        entries = payload.get("entries", {})
        cached_entry = entries.get(key)
        if cached_entry is None:
            return None

        stored_at = self._parse_timestamp(cached_entry.get("stored_at"))
        if stored_at is None or self._is_expired(stored_at):
            entries.pop(key, None)
            self._write_payload(payload)
            return None

        return cached_entry.get("value")

    def set(self, key: str, value: Any) -> None:
        payload = self._load_payload()
        payload.setdefault("entries", {})[key] = {
            "stored_at": self._timestamp_now(),
            "value": value,
        }
        self._write_payload(payload)

    def is_fresh(self, key: str) -> bool:
        payload = self._load_payload()
        cached_entry = payload.get("entries", {}).get(key)
        if cached_entry is None:
            return False
        stored_at = self._parse_timestamp(cached_entry.get("stored_at"))
        if stored_at is None or self._is_expired(stored_at):
            return False
        return True

    def clear(self) -> None:
        if self.cache_file.exists():
            self.cache_file.unlink()

    def _load_payload(self) -> dict[str, Any]:
        if not self.cache_file.exists():
            return {"entries": {}}

        try:
            raw_payload = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"entries": {}}

        if not isinstance(raw_payload, dict):
            return {"entries": {}}

        entries = raw_payload.get("entries", {})
        if not isinstance(entries, dict):
            return {"entries": {}}

        return {"entries": entries}

    def _write_payload(self, payload: dict[str, Any]) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _is_expired(self, stored_at: datetime) -> bool:
        return datetime.now(UTC) - stored_at >= self.ttl

    def _parse_timestamp(self, value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None

        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _timestamp_now(self) -> str:
        return datetime.now(UTC).isoformat()
