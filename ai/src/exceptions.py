"""Shared error contracts for execution limits and tool failures."""


class LimitReached(Exception):
    pass


class ToolFailure(Exception):
    """Explicit operational error; only retryable, safe reads may be repeated."""

    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.retryable = retryable
