from divvydiary_app import AppConfig, DivvyDiaryClient, PortfolioService
from divvydiary_app.cache import FileCache
from divvydiary_app.cli import run_cli
from divvydiary_app.logging_config import configure_logging, get_logger


def main() -> int:
    config = AppConfig.from_env()
    logger = configure_logging(config.log_level)
    if not config.api_key:
        logger.error("Please set DIVVYDIARY_API_KEY in the .env file before running this script.")
        return 1

    cache = FileCache(config.cache_file, ttl_seconds=config.cache_ttl_seconds)
    client = DivvyDiaryClient(config, cache=cache)
    service = PortfolioService(client)

    try:
        return run_cli(service)
    except Exception as exc:
        get_logger("main").error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
