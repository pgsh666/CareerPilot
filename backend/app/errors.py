import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger("careerpilot")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, *, retryable: bool = False, diagnostic=None):
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable
        self.diagnostic = diagnostic


def error_response(request: Request, status: int, code: str, message: str, retryable=False):
    return JSONResponse(
        status_code=status,
        content={"error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "request_id": getattr(request.state, "request_id", None),
        }},
    )


def install_error_handlers(app: FastAPI):
    @app.exception_handler(ApiError)
    async def business_error(request: Request, exc: ApiError):
        return error_response(request, exc.status, exc.code, exc.message, exc.retryable)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _: RequestValidationError):
        # ValidationError.input may contain passwords/codes. Never return it.
        return error_response(request, 422, "INVALID_INPUT", "输入格式或字段内容不符合要求")

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, _: SQLAlchemyError):
        logger.error("database_error request_id=%s", request.state.request_id)
        return error_response(request, 503, "DATABASE_UNAVAILABLE", "数据库暂不可用", True)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, _: Exception):
        logger.error("internal_error request_id=%s", request.state.request_id)
        return error_response(request, 500, "INTERNAL_ERROR", "服务暂时无法完成操作", True)

