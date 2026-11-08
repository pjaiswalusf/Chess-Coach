"""Safe application failures, independent of HTTP."""


class OperationError(ValueError):
    def __init__(self, code: str, message: str, status: int = 409):
        self.code, self.status = code, status
        super().__init__(message)
