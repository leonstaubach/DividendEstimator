import os
from dataclasses import dataclass
from pathlib import Path


class EnvLoader:
    def __init__(self, env_file: Path) -> None:
        self.env_file = env_file

    def load(self) -> None:
        if not self.env_file.exists():
            return

        for raw_line in self.env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key:
                os.environ.setdefault(key, value)


@dataclass(frozen=True)
class AppConfig:
    api_key: str
    user_id: str
    portfolio_id: str
    log_level: str = "DEBUG"
    base_url: str = "https://api.divvydiary.com"
    cache_file: Path = Path(".cache/divvydiary_cache.json")
    cache_ttl_seconds: int = 604800
    gcs_bucket: str | None = None
    gcs_blob_name: str = "divvydiary_cache.json"
    gcs_credentials_file: Path | None = None

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "AppConfig":
        env_path = env_file or Path(__file__).resolve().parent.parent / ".env"
        EnvLoader(env_path).load()
        cache_file = os.getenv("DIVVYDIARY_CACHE_FILE")
        creds_path = os.getenv("DIVVYDIARY_GCS_CREDENTIALS_FILE")
        gcs_credentials_file: Path | None = Path(creds_path) if creds_path else None
        return cls(
            api_key=os.getenv("DIVVYDIARY_API_KEY", ""),
            user_id=os.getenv("DIVVYDIARY_USER_ID", ""),
            portfolio_id=os.getenv("DIVVYDIARY_PORTFOLIO_ID", ""),
            log_level=os.getenv("DIVVYDIARY_LOG_LEVEL", "DEBUG"),
            cache_file=Path(cache_file) if cache_file else env_path.parent / ".cache" / "divvydiary_cache.json",
            cache_ttl_seconds=int(os.getenv("DIVVYDIARY_CACHE_TTL_SECONDS", "604800")),
            gcs_bucket=os.getenv("DIVVYDIARY_GCS_BUCKET") or None,
            gcs_blob_name=os.getenv("DIVVYDIARY_GCS_BLOB_NAME", "divvydiary_cache.json"),
            gcs_credentials_file=gcs_credentials_file,
        )
