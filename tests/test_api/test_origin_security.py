"""Kiểm tra nguồn yêu cầu (chống CSRF) và CORS: chỉ tin đúng tên miền của dự án, không tin mọi *.vercel.app."""

import pytest

from src.api.security import is_trusted_origin
from src.config import get_settings
from tests.helpers import STUDENT

API = "/api/v1"
PROD = "https://c4-app-131.vercel.app"
PREVIEW_REGEX = r"^https://c4-app-131-(git-[a-z0-9-]+|[a-z0-9]+)-nhom-c4\.vercel\.app$"


@pytest.fixture
def deployed(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "frontend_url", PROD + "/")
    monkeypatch.setattr(settings, "cors_origin_regex", "")
    return settings


def test_only_project_domains_are_trusted(deployed, monkeypatch):
    assert is_trusted_origin(PROD)
    assert is_trusted_origin("http://localhost:3000")
    for origin in (
        "https://evil.vercel.app",
        "https://c4-app-131-evil.vercel.app",
        "https://c4-app-131.vercel.app.evil.com",
    ):
        assert not is_trusted_origin(origin)
    # Bản preview chỉ được tin khi đặt mẫu, và mẫu phải neo vào tên nhóm
    preview = "https://c4-app-131-git-feat-interview-nhom-c4.vercel.app"
    assert not is_trusted_origin(preview)
    monkeypatch.setattr(deployed, "cors_origin_regex", PREVIEW_REGEX)
    assert is_trusted_origin(preview)
    assert is_trusted_origin("https://c4-app-131-a1b2c3-nhom-c4.vercel.app")
    assert not is_trusted_origin("https://c4-app-131-git-x-nhom-khac.vercel.app")
    assert not is_trusted_origin(preview + ".evil.com")


@pytest.mark.asyncio
async def test_mutation_from_foreign_vercel_site_is_rejected(client, deployed):
    body = {"rating": 5}
    foreign = await client.post(f"{API}/feedback", json=body, headers={**STUDENT, "Origin": "https://evil.vercel.app"})
    assert (foreign.status_code, foreign.json()["code"]) == (403, "untrusted_origin")
    own = await client.post(f"{API}/feedback", json=body, headers={**STUDENT, "Origin": PROD})
    assert own.status_code != 403 or own.json().get("code") != "untrusted_origin"


@pytest.mark.asyncio
async def test_cors_does_not_allow_foreign_vercel_sites(client):
    preflight = await client.options(
        f"{API}/me",
        headers={"Origin": "https://evil.vercel.app", "Access-Control-Request-Method": "GET"},
    )
    assert preflight.headers.get("access-control-allow-origin") != "https://evil.vercel.app"
    simple = await client.get(f"{API}/me", headers={**STUDENT, "Origin": "https://evil.vercel.app"})
    assert simple.headers.get("access-control-allow-origin") != "https://evil.vercel.app"
