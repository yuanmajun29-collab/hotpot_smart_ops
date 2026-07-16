"""common package — 共享错误模型、工具函数等。"""

from hotpot_platform.cloud.event_hub.common.errors import (
    AppError,
    ConflictError,
    ErrorDetail,
    ErrorResponse,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
    register_error_handlers,
)

__all__ = [
    "AppError",
    "ConflictError",
    "ErrorDetail",
    "ErrorResponse",
    "ForbiddenError",
    "NotFoundError",
    "ServiceUnavailableError",
    "UnauthorizedError",
    "ValidationError",
    "register_error_handlers",
]
