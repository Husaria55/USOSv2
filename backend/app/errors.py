from app.domain.enrollment_rules import Refusal


class AppError(Exception):
    """Błąd zwracany klientowi jako {"code", "message", "details"}."""

    status = 400

    def __init__(self, code: str, message: str, details: tuple[str, ...] | list = ()):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = list(details)


class NotFound(AppError):
    status = 404


class Forbidden(AppError):
    status = 403


class Conflict(AppError):
    """Operacja niedozwolona w obecnym stanie (odmowa zapisu, kolizja, cykl)."""
    status = 409

    @classmethod
    def from_refusal(cls, r: Refusal) -> "Conflict":
        return cls(r.code, r.message, r.details)
