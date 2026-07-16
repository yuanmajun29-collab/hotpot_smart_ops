"""统一错误模型 — FastAPI 全局 exception handler。

目标格式:
{
  "error": {
    "code": "DEVICE_NOT_FOUND",
    "message": "设备不存在: jetson-yuhuan-01",
    "details": {"device_id": "jetson-yuhuan-01"}
  }
}
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


# ── 业务异常基类 ────────────────────────────────────────────────


class AppError(Exception):
    """应用层异常基类。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class NotFoundError(AppError):
    """资源不存在 (404)."""

    def __init__(
        self,
        message: str,
        code: str = "NOT_FOUND",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(code=code, message=message, status_code=404, details=details)


class ValidationError(AppError):
    """请求参数校验失败 (422)."""

    def __init__(
        self,
        message: str,
        code: str = "VALIDATION_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(code=code, message=message, status_code=422, details=details)


class UnauthorizedError(AppError):
    """认证失败 (401)."""

    def __init__(
        self,
        message: str = "未授权访问",
        code: str = "UNAUTHORIZED",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(code=code, message=message, status_code=401, details=details)


class ForbiddenError(AppError):
    """权限不足 (403)."""

    def __init__(
        self,
        message: str = "权限不足",
        code: str = "FORBIDDEN",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(code=code, message=message, status_code=403, details=details)


class ConflictError(AppError):
    """资源冲突 (409)."""

    def __init__(
        self,
        message: str,
        code: str = "CONFLICT",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(code=code, message=message, status_code=409, details=details)


class ServiceUnavailableError(AppError):
    """服务不可用 (503)."""

    def __init__(
        self,
        message: str = "服务暂不可用",
        code: str = "SERVICE_UNAVAILABLE",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(code=code, message=message, status_code=503, details=details)


# ── 全局 exception handler ──────────────────────────────────────


async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """AppError → 统一错误响应。"""
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=ErrorDetail(
                code=exc.code,
                message=exc.message,
                details=exc.details,
            )
        ).model_dump(),
    )


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底：非 AppError 异常。"""
    from fastapi.exceptions import HTTPException as _HTTPException

    if isinstance(exc, _HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="HTTP_ERROR",
                    message=str(exc.detail),
                )
            ).model_dump(),
        )

    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error=ErrorDetail(
                code="INTERNAL_ERROR",
                message="服务器内部错误",
            )
        ).model_dump(),
    )


def register_error_handlers(app: FastAPI) -> None:
    """向 FastAPI app 注册统一错误处理器。"""
    app.add_exception_handler(AppError, _app_error_handler)  # type: ignore[arg-type]
    from fastapi.exceptions import HTTPException as _FastAPIHTTPException
    app.add_exception_handler(_FastAPIHTTPException, _http_exception_handler)  # type: ignore[arg-type]
