import json
import sys

from divvydiary_app import AppConfig, DivvyDiaryClient, PortfolioService


def main() -> int:
    config = AppConfig.from_env()
    if not config.api_key:
        print(
            "Please set DIVVYDIARY_API_KEY in the .env file before running this script.",
            file=sys.stderr,
        )
        return 1

    client = DivvyDiaryClient(config)
    service = PortfolioService(client)

    try:
        resolved_portfolio = service.get_resolved_portfolio()
        estimated_histories = service.build_estimated_security_dividend_histories(resolved_portfolio)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("Connected to DivvyDiary")
    print(
        f"User: {resolved_portfolio.user.forename} "
        f"(id={resolved_portfolio.user.id if resolved_portfolio.user.id is not None else 'unknown'})"
    )
    print(
        f"Portfolio: {resolved_portfolio.portfolio.name} "
        f"(id={resolved_portfolio.portfolio.id if resolved_portfolio.portfolio.id is not None else 'unknown'})"
    )
    print("Structured security dividend histories:")
    print(json.dumps(service.serialize_histories(estimated_histories), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
