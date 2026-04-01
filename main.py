import sys

from divvydiary_app import AppConfig, DivvyDiaryClient, PortfolioService
from divvydiary_app.cache import FileCache
from divvydiary_app.cli import run_cli


def main() -> int:
    config = AppConfig.from_env()
    if not config.api_key:
        print(
            "Please set DIVVYDIARY_API_KEY in the .env file before running this script.",
            file=sys.stderr,
        )
        return 1

    cache = FileCache(config.cache_file, ttl_seconds=config.cache_ttl_seconds)
    client = DivvyDiaryClient(config, cache=cache, log_func=print)
    service = PortfolioService(client)

    try:
        return run_cli(service)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
