"""Preparation failures, independent of FastAPI and worker persistence."""


class PreparationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class SimulationError(RuntimeError):
    """Numerical engine failure, independent of HTTP/job error mapping."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)
