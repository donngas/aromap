"""Preparation failures, independent of FastAPI and worker persistence."""


class PreparationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)
