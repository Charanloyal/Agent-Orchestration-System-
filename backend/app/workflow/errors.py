"""Error classes that drive retry decisions. Only TransientError is ever retried."""


class TransientError(Exception):
    """Network failure, rate limit, or provider 5xx: safe to retry with backoff."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class StepFailed(Exception):
    """Deterministic failure of a workflow step (invalid output after repair, policy violation).
    Retrying would not help; the run fails visibly with this reason."""

    def __init__(self, step: str, reason: str) -> None:
        super().__init__(f"{step}: {reason}")
        self.step = step
        self.reason = reason


class RunStopped(Exception):
    """Cancellation or deadline observed at a step boundary."""

    def __init__(self, target_state: str, reason: str) -> None:
        super().__init__(reason)
        self.target_state = target_state
        self.reason = reason
