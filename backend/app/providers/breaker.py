"""Provider circuit breaker: degraded mode during an outage (ADR 0016).

After `threshold` consecutive transient failures from a provider, calls fail fast for
`cooldown` seconds with a TransientError carrying `retry_after`. The worker then re-queues the
run with backoff instead of hammering a provider that is down (and paying for timeouts).
After the cooldown, one trial call is let through (half-open); success closes the circuit.

The breaker sits *outside* the budget meter, so an open circuit reserves no money. State is
per worker process and per provider/model, shared by every run that process executes.
"""

import logging
import threading
import time
from collections.abc import Callable

from app.config import Settings
from app.providers.llm import LlmProvider, LlmResult
from app.providers.search import SearchProvider, SearchResponse
from app.workflow.errors import TransientError

log = logging.getLogger("aos.breaker")


class CircuitBreaker:
    def __init__(
        self, name: str, threshold: int, cooldown: float, clock: Callable[[], float] = time.monotonic
    ):
        self.name, self.threshold, self.cooldown, self.clock = name, threshold, cooldown, clock
        self._lock = threading.Lock()
        self.failures = 0
        self.opened_at: float | None = None
        self._trial_in_flight = False

    @property
    def state(self) -> str:
        with self._lock:
            if self.opened_at is None:
                return "closed"
            return "half_open" if self.clock() - self.opened_at >= self.cooldown else "open"

    def before_call(self) -> None:
        with self._lock:
            if self.opened_at is None:
                return
            remaining = self.cooldown - (self.clock() - self.opened_at)
            if remaining > 0 or self._trial_in_flight:
                raise TransientError(
                    f"{self.name} unavailable (circuit open after {self.failures} failures)",
                    retry_after=max(remaining, 1.0),
                )
            self._trial_in_flight = True

    def record_success(self) -> None:
        with self._lock:
            if self.opened_at is not None:
                log.info("provider circuit closed", extra={"provider": self.name})
            self.failures, self.opened_at, self._trial_in_flight = 0, None, False

    def record_failure(self) -> None:
        with self._lock:
            self.failures += 1
            reopen = self._trial_in_flight
            self._trial_in_flight = False
            if reopen or (self.opened_at is None and self.failures >= self.threshold):
                self.opened_at = self.clock()
                log.warning(
                    "provider circuit opened", extra={"provider": self.name, "failures": self.failures}
                )


_registry: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def breaker_for(name: str, settings: Settings) -> CircuitBreaker:
    with _registry_lock:
        if name not in _registry:
            _registry[name] = CircuitBreaker(
                name, settings.breaker_failure_threshold, settings.breaker_cooldown_seconds
            )
        return _registry[name]


def reset_breakers() -> None:
    with _registry_lock:
        _registry.clear()


class BreakerLlm:
    def __init__(self, inner: LlmProvider, settings: Settings) -> None:
        self.inner = inner
        self.name, self.model = inner.name, inner.model
        self.breaker = breaker_for(f"llm:{inner.name}:{inner.model}", settings)

    def complete(self, *, system: str, user: str, json_output: bool, max_output_tokens: int) -> LlmResult:
        self.breaker.before_call()
        try:
            result = self.inner.complete(
                system=system, user=user, json_output=json_output, max_output_tokens=max_output_tokens
            )
        except TransientError:
            self.breaker.record_failure()
            raise
        self.breaker.record_success()
        return result


class BreakerSearch:
    def __init__(self, inner: SearchProvider, settings: Settings) -> None:
        self.inner = inner
        self.name = inner.name
        self.breaker = breaker_for(f"search:{inner.name}", settings)

    def search(
        self, query: str, *, max_results: int, allowed_domains: list[str], blocked_domains: list[str]
    ) -> SearchResponse:
        self.breaker.before_call()
        try:
            response = self.inner.search(
                query,
                max_results=max_results,
                allowed_domains=allowed_domains,
                blocked_domains=blocked_domains,
            )
        except TransientError:
            self.breaker.record_failure()
            raise
        self.breaker.record_success()
        return response
