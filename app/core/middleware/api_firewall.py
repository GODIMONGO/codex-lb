from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from app.core.config.settings import get_settings
from app.core.errors import openai_error
from app.db.session import SessionLocal
from app.modules.firewall.repository import FirewallRepository
from app.modules.firewall.service import FirewallService


def add_api_firewall_middleware(app: FastAPI) -> None:
    settings = get_settings()

    @app.middleware("http")
    async def api_firewall_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if not _is_protected_api_path(path):
            return await call_next(request)

        client_ip = _resolve_client_ip(request, trust_proxy_headers=settings.firewall_trust_proxy_headers)
        async with SessionLocal() as session:
            service = FirewallService(FirewallRepository(session))
            is_allowed = await service.is_ip_allowed(client_ip)

        if is_allowed:
            return await call_next(request)

        return JSONResponse(
            status_code=403,
            content=openai_error("ip_forbidden", "Access denied for client IP", error_type="access_error"),
        )


def _is_protected_api_path(path: str) -> bool:
    if path == "/backend-api/codex" or path.startswith("/backend-api/codex/"):
        return True
    return path == "/v1" or path.startswith("/v1/")


def _resolve_client_ip(request: Request, *, trust_proxy_headers: bool) -> str | None:
    if trust_proxy_headers:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            first = forwarded_for.split(",", 1)[0].strip()
            if first:
                return first
    if request.client is None:
        return None
    return request.client.host
