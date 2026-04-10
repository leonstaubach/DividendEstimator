from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .logging_config import get_logger

_log = get_logger("cache")


class _CacheBase:
    def __init__(self, ttl_seconds: int = 604800) -> None:
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
        raise NotImplementedError

    def _load_payload(self) -> dict[str, Any]:
        raise NotImplementedError

    def _write_payload(self, payload: dict[str, Any]) -> None:
        raise NotImplementedError

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


class FileCache(_CacheBase):
    def __init__(self, cache_file: Path, ttl_seconds: int = 86400) -> None:
        super().__init__(ttl_seconds)
        self.cache_file = cache_file

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


class GCSCache(_CacheBase):
    def __init__(self, bucket_name: str, blob_name: str = "divvydiary_cache.json", ttl_seconds: int = 604800, credentials_file: Path | None = None) -> None:
        super().__init__(ttl_seconds)
        from google.cloud import storage  # noqa: PLC0415
        from google.oauth2 import service_account  # noqa: PLC0415
        self._blob_name = blob_name
        if credentials_file is not None:
            credentials = service_account.Credentials.from_service_account_file(
                str(credentials_file),
                scopes=["https://www.googleapis.com/auth/devstorage.read_write"],
            )
            client = storage.Client(credentials=credentials)
        else:
            client = storage.Client()
        self._bucket = client.bucket(bucket_name)
        self._memory_payload: dict[str, Any] | None = None

    def probe(self) -> None:
        """Verify bucket connectivity. Raises RuntimeError on failure."""
        try:
            self._bucket.reload()
            _log.debug("GCS probe: successfully connected to bucket '%s'", self._bucket.name)
        except Exception as exc:
            raise RuntimeError(
                f"GCS probe failed for bucket '{self._bucket.name}': {exc}"
            ) from exc

    def clear(self) -> None:
        self._memory_payload = None
        blob = self._bucket.blob(self._blob_name)
        if blob.exists():
            blob.delete()

    def _load_payload(self) -> dict[str, Any]:
        if self._memory_payload is not None:
            return self._memory_payload

        _log.debug("GCS read: downloading %s", self._blob_name)
        blob = self._bucket.blob(self._blob_name)
        if not blob.exists():
            _log.debug("GCS read: blob not found, starting with empty cache")
            return {"entries": {}}

        try:
            raw_payload = json.loads(blob.download_as_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            _log.debug("GCS read: failed to parse blob, starting with empty cache")
            return {"entries": {}}

        if not isinstance(raw_payload, dict):
            return {"entries": {}}

        entries = raw_payload.get("entries", {})
        if not isinstance(entries, dict):
            return {"entries": {}}

        self._memory_payload = {"entries": entries}
        return self._memory_payload

    def _write_payload(self, payload: dict[str, Any]) -> None:
        self._memory_payload = payload
        _log.debug("GCS write: uploading %s", self._blob_name)
        blob = self._bucket.blob(self._blob_name)
        blob.upload_from_string(
            json.dumps(payload, indent=2, sort_keys=True),
            content_type="application/json",
        )
