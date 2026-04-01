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
    base_url: str = "https://api.divvydiary.com"

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "AppConfig":
        env_path = env_file or Path(__file__).resolve().parent.parent / ".env"
        EnvLoader(env_path).load()
        return cls(
            api_key=os.getenv("DIVVYDIARY_API_KEY", ""),
            user_id=os.getenv("DIVVYDIARY_USER_ID", ""),
            portfolio_id=os.getenv("DIVVYDIARY_PORTFOLIO_ID", ""),
        )
