"""Origin checks for cookie-authenticated browser mutations, including uploads."""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.config import get_settings


class OriginProtectionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            trusted = {value.strip().rstrip("/") for value in get_settings().cors_origins.split(",") if value.strip()}
            trusted.add(f"{request.url.scheme}://{request.url.netloc}")
            if (origin is not None and origin not in trusted) or (
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
