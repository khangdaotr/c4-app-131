"""Origin checks for cookie-authenticated browser mutations, including uploads."""

import re

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.config import get_settings


def trusted_origins() -> set[str]:
    """CORS_ORIGINS và FRONTEND_URL (trang frontend đã deploy), bỏ dấu / ở cuối."""
    settings = get_settings()
    trusted = {value.strip().rstrip("/") for value in settings.cors_origins.split(",") if value.strip()}
    if settings.frontend_url:
        trusted.add(settings.frontend_url.strip().rstrip("/"))
    return trusted


def is_trusted_origin(origin: str) -> bool:
    """Origin nằm trong danh sách tin cậy, hoặc khớp toàn bộ mẫu CORS_ORIGIN_REGEX (bản preview của dự án)."""
    origin = origin.rstrip("/")
    pattern = get_settings().cors_origin_regex
    return origin in trusted_origins() or bool(pattern and re.fullmatch(pattern, origin))


class OriginProtectionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            same_site = f"{request.url.scheme}://{request.url.netloc}"
            if (origin is not None and origin != same_site and not is_trusted_origin(origin)) or (
                origin is None and request.headers.get("sec-fetch-site") == "cross-site"
            ):
                return JSONResponse(
                    {"detail": "Nguồn yêu cầu không được phép.", "code": "untrusted_origin"}, status_code=403
                )
        response = await call_next(request)
        if request.url.path.startswith("/api/v1/"):
            if response.headers.get("content-type", "").startswith("text/event-stream"):
                response.headers["Cache-Control"] = "no-cache"
            else:
                response.headers.setdefault("Cache-Control", "no-store")
        return response
