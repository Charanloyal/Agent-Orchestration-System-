"""Budget meter and metered provider wrappers (FR-09, threat model T9).

Protocol for every billable provider call:
1. estimate the worst-case cost (prompt size + maximum output tokens, or search credits);
2. reserve it transactionally: the run row is locked, committed spend is summed, and the
   reservation is inserted only if it fits the brief's budget. Concurrent tasks therefore
   cannot over-commit (no read-then-write race);
3. make the call; reconcile the reservation with the provider-reported usage.

This is estimated accounting. It stops *scheduling* work when funds run out; it is not a
provider-side billing cap, and in-flight calls may finish.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import case, func, select, update

from app.billing.prices import PriceSchedule, schedule_from
from app.db.models import BudgetReservation, Run
from app.observability.tracing import annotate, span
from app.providers.llm import LlmProvider, LlmResult
from app.providers.search import SearchProvider, SearchResponse
from app.services.events import append_event

if TYPE_CHECKING:
    from app.workflow.context import RunContext

CHARS_PER_TOKEN = 4


class BudgetExhausted(Exception):
    def __init__(self, step: str, needed: Decimal, remaining: Decimal) -> None:
        super().__init__(
            f"budget exhausted at {step}: needs ~${needed:.4f}, ${max(remaining, Decimal(0)):.4f} left"
        )
        self.step = step


@dataclass(frozen=True)
class Spend:
    budget: Decimal
    committed: Decimal  # reconciled actuals + outstanding reservations
    reconciled: Decimal
    outstanding: Decimal
    uncertain: Decimal


class BudgetMeter:
    def __init__(self, ctx: RunContext) -> None:
        self.ctx = ctx
        self.budget = Decimal(str(ctx.brief.budget.max_estimated_cost))
        self.schedule: PriceSchedule = schedule_from(ctx.settings)

    @staticmethod
    def committed_expression() -> Any:
        return func.coalesce(
            func.sum(
                case(
                    (BudgetReservation.status == "reserved", BudgetReservation.estimated_cost),
                    else_=func.coalesce(BudgetReservation.actual_cost, BudgetReservation.estimated_cost),
                )
            ),
            0,
        )

    def reserve(self, *, step: str, kind: str, estimate: Decimal, detail: dict[str, Any]) -> uuid.UUID:
        reservation_id = uuid.uuid4()
        rejected: tuple[Decimal, Decimal] | None = None
        with self.ctx.fenced() as session:
            session.execute(select(Run.id).where(Run.id == self.ctx.run_id).with_for_update())
            self.ctx.check_continue(session)
            committed = Decimal(
                session.scalar(
                    select(self.committed_expression()).where(BudgetReservation.run_id == self.ctx.run_id)
                )
                or 0
            )
            if committed + estimate > self.budget:
                rejected = (estimate, self.budget - committed)
                append_event(
                    session,
                    self.ctx.run_id,
                    self.ctx.workspace_id,
                    "budget_exhausted",
                    {
                        "step": step,
                        "kind": kind,
                        "needed": f"{estimate:.6f}",
                        "committed": f"{committed:.6f}",
                        "budget": f"{self.budget:.2f}",
                    },
                )
            else:
                session.add(
                    BudgetReservation(
                        id=reservation_id,
                        run_id=self.ctx.run_id,
                        workspace_id=self.ctx.workspace_id,
                        step=step,
                        kind=kind,
                        status="reserved",
                        estimated_cost=estimate,
                        usage=detail,
                        price_snapshot=self.schedule.snapshot(),
                        fencing_token=self.ctx.lease.token,
                    )
                )
        if rejected:
            raise BudgetExhausted(step, *rejected)
        self.ctx.crash_if("after_budget_reserve")
        return reservation_id

    def reconcile(
        self, reservation_id: uuid.UUID, *, actual: Decimal, usage: dict[str, Any], uncertain: bool = False
    ) -> None:
        with self.ctx.fenced() as session:
            session.execute(
                update(BudgetReservation)
                .where(BudgetReservation.id == reservation_id)
                .values(
                    status="reconciled",
                    actual_cost=actual,
                    usage=usage,
                    uncertain=uncertain,
                    reconciled_at=datetime.now(UTC),
                )
            )


def spend_for(session: Any, run_id: uuid.UUID, budget: Decimal) -> Spend:
    row = session.execute(
        select(
            BudgetMeter.committed_expression(),
            func.coalesce(
                func.sum(BudgetReservation.actual_cost).filter(BudgetReservation.status == "reconciled"), 0
            ),
            func.coalesce(
                func.sum(BudgetReservation.estimated_cost).filter(BudgetReservation.status == "reserved"), 0
            ),
            func.coalesce(
                func.sum(BudgetReservation.actual_cost).filter(BudgetReservation.uncertain.is_(True)), 0
            ),
        ).where(BudgetReservation.run_id == run_id)
    ).one()
    return Spend(budget, Decimal(row[0]), Decimal(row[1]), Decimal(row[2]), Decimal(row[3]))


class MeteredLlm:
    """Wraps an LLM provider so every call is reserved before and reconciled after."""

    def __init__(self, inner: LlmProvider, meter: BudgetMeter, step: str) -> None:
        self.inner, self.meter, self.step = inner, meter, step
        self.name, self.model = inner.name, inner.model

    def complete(self, *, system: str, user: str, json_output: bool, max_output_tokens: int) -> LlmResult:
        input_estimate = (len(system) + len(user)) // CHARS_PER_TOKEN + 16
        estimate = self.meter.schedule.llm_cost(input_estimate, max_output_tokens)
        reservation = self.meter.reserve(
            step=self.step,
            kind="llm",
            estimate=estimate,
            detail={
                "model": self.model,
                "estimated_input_tokens": input_estimate,
                "max_output_tokens": max_output_tokens,
            },
        )
        with span("llm.call", step=self.step, provider=self.name, model=self.model) as current:
            try:
                result = self.inner.complete(
                    system=system, user=user, json_output=json_output, max_output_tokens=max_output_tokens
                )
            except Exception:
                # The request may have reached the provider; keep the estimate, flagged uncertain.
                self.meter.reconcile(
                    reservation, actual=estimate, usage={"model": self.model, "error": True}, uncertain=True
                )
                raise
            usage = result.usage
            actual = self.meter.schedule.llm_cost(usage.input_tokens, usage.output_tokens)
            annotate(
                current,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                estimated_cost=float(actual),
            )
        self.meter.reconcile(
            reservation,
            actual=actual,
            usage={
                "model": usage.model,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
            },
        )
        return result


class MeteredSearch:
    """Wraps a search provider; one basic search is estimated at one credit."""

    def __init__(self, inner: SearchProvider, meter: BudgetMeter, *, credits_per_call: float = 1.0) -> None:
        self.inner, self.meter, self.credits_per_call = inner, meter, credits_per_call
        self.name = inner.name

    def search(
        self, query: str, *, max_results: int, allowed_domains: list[str], blocked_domains: list[str]
    ) -> SearchResponse:
        priced = (
            self.meter.schedule.search_cost(self.credits_per_call)
            if self.inner.name != "fake"
            else Decimal(0)
        )
        reservation = self.meter.reserve(
            step="research", kind="search", estimate=priced, detail={"provider": self.inner.name}
        )
        with span("search.call", step="research", provider=self.inner.name) as current:
            try:
                response = self.inner.search(
                    query,
                    max_results=max_results,
                    allowed_domains=allowed_domains,
                    blocked_domains=blocked_domains,
                )
            except Exception:
                self.meter.reconcile(
                    reservation,
                    actual=priced,
                    usage={"provider": self.inner.name, "error": True},
                    uncertain=True,
                )
                raise
            annotate(current, results=len(response.hits))
        actual = (
            self.meter.schedule.search_cost(response.credits) if self.inner.name != "fake" else Decimal(0)
        )
        self.meter.reconcile(
            reservation, actual=actual, usage={"provider": self.inner.name, "credits": response.credits}
        )
        return response
