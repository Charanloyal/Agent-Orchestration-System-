"""Price schedules for *estimated* cost accounting (FR-09, ADR 0005).

These are configured estimates, not quotes: verify against the providers' current price
pages before relying on them, and override via settings. Every reservation stores the
schedule id and unit prices it used, so estimates stay auditable after prices change.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.config import Settings

MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class PriceSchedule:
    schedule_id: str
    llm_input_per_million: Decimal
    llm_output_per_million: Decimal
    search_per_credit: Decimal
    currency: str = "USD"

    def llm_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        return (
            Decimal(input_tokens) * self.llm_input_per_million
            + Decimal(output_tokens) * self.llm_output_per_million
        ) / MILLION

    def search_cost(self, credits: float) -> Decimal:
        return Decimal(str(credits)) * self.search_per_credit

    def snapshot(self) -> dict[str, str]:
        return {
            "schedule_id": self.schedule_id,
            "llm_input_per_million": str(self.llm_input_per_million),
            "llm_output_per_million": str(self.llm_output_per_million),
            "search_per_credit": str(self.search_per_credit),
            "currency": self.currency,
        }


def schedule_from(settings: Settings) -> PriceSchedule:
    return PriceSchedule(
        schedule_id=settings.price_schedule_id,
        llm_input_per_million=Decimal(str(settings.price_llm_input_per_million)),
        llm_output_per_million=Decimal(str(settings.price_llm_output_per_million)),
        search_per_credit=Decimal(str(settings.price_search_per_credit)),
    )
