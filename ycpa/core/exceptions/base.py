from typing import Any, Optional


class AppException(Exception):
    status_code: int = 500
    error_code:  str = "INTERNAL_SERVER_ERROR"
    message:     str = "An unexpected error occurred"

    def __init__(
        self,
        message:     str            = None,
        details:     Optional[Any]  = None,
        error_code:  Optional[str]  = None,
        status_code: Optional[int]  = None,
    ):
        self.message     = message     or self.__class__.message
        self.details     = details     or {}
        self.error_code  = error_code  or self.__class__.error_code
        self.status_code = status_code or self.__class__.status_code
        super().__init__(self.message)

    def __str__(self):  return f"[{self.error_code}] {self.message}"
    def __repr__(self): return f"{self.__class__.__name__}(status={self.status_code}, code={self.error_code!r})"