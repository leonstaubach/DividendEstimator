from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class UserProfile:
    id: int | str | None
    forename: str

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "UserProfile":
        return cls(
            id=payload.get("id"),
            forename=payload.get("forename", "unknown"),
        )


@dataclass
class Security:
    isin: str
    wkn: str | None
    symbol: str | None
    name: str
    nickname: str | None
    quantity: float
    price: float | None
    prev_price: float | None
    value: float | None
    allocation: float | None
    dividend_yield: float | None
    dividend_frequency: str | None
    currency: str | None
    original_dividend_currency: str | None
    tax_rate: float | None
    sector: str | None
    cash_account: str | None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "Security":
        return cls(
            isin=payload["isin"],
            wkn=payload.get("wkn"),
            symbol=payload.get("symbol"),
            name=payload.get("name", ""),
            nickname=payload.get("nickname"),
            quantity=float(payload.get("quantity", 0.0)),
            price=payload.get("price"),
            prev_price=payload.get("prevPrice"),
            value=payload.get("value"),
            allocation=payload.get("allocation"),
            dividend_yield=payload.get("dividendYield"),
            dividend_frequency=payload.get("dividendFrequency"),
            currency=payload.get("currency"),
            original_dividend_currency=payload.get("originalDividendCurrency"),
            tax_rate=payload.get("taxRate"),
            sector=payload.get("sector"),
            cash_account=payload.get("cashAccount"),
        )


@dataclass
class Portfolio:
    id: int | str | None
    name: str
    currency: str | None
    acronym: str | None
    securities: list[Security]

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "Portfolio":
        raw_securities = payload.get("securities", [])
        return cls(
            id=payload.get("id"),
            name=payload.get("name", "unknown"),
            currency=payload.get("currency"),
            acronym=payload.get("acronym"),
            securities=[Security.from_api(raw_security) for raw_security in raw_securities],
        )


@dataclass
class ResolvedPortfolio:
    user: UserProfile
    portfolio: Portfolio


@dataclass
class DividendEvent:
    id: int
    ex_date: str | None
    pay_date: str | None
    amount: float | None
    currency: str | None
    forecast: bool

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "DividendEvent":
        return cls(
            id=int(payload["id"]),
            ex_date=payload.get("exDate"),
            pay_date=payload.get("payDate"),
            amount=payload.get("amount"),
            currency=payload.get("currency"),
            forecast=bool(payload.get("forecast", False)),
        )


@dataclass
class SecurityDividendHistory:
    security: Security
    dividends: list[DividendEvent]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DividendEstimate:
    next_payment_date: str | None
    next_payment_amount: float | None
    confidence: str
    basis: str


@dataclass
class EstimatedSecurityDividendHistory:
    security: Security
    dividends: list[DividendEvent]
    estimate: DividendEstimate

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
