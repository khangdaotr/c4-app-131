"""Tạo tài khoản quản trị từ ADMIN_EMAIL / ADMIN_PASSWORD khi deploy (production không có tài khoản demo)."""

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from src.config import get_settings
from src.db.database import SessionLocal, init_db
from src.db.models import User
from src.db.seed import ensure_admin_account
from src.services.auth import verify_password

EMAIL = "quantri.deploy@careerv.vn"


@pytest.fixture
def admin_env(monkeypatch):
    init_db()
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_email", " QuanTri.Deploy@careerv.vn ")
    monkeypatch.setattr(settings, "admin_password", SecretStr("Matkhau-Manh-2026"))
    yield settings
    with SessionLocal() as db:
        db.execute(delete(User).where(User.email == EMAIL))
        db.commit()


def admins(db) -> list[User]:
    return list(db.scalars(select(User).where(User.email == EMAIL)))


@pytest.mark.asyncio
async def test_admin_is_created_once_and_can_log_in(client, admin_env):
    with SessionLocal() as db:
        ensure_admin_account(db)
        ensure_admin_account(db)  # khởi động lại không tạo trùng
        [admin] = admins(db)
        assert admin.role == "admin" and admin.id.startswith("qt-")
    res = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": "Matkhau-Manh-2026"})
    assert res.status_code == 200 and res.json()["role"] == "admin"


def test_existing_admin_password_is_never_overwritten(admin_env, monkeypatch):
    with SessionLocal() as db:
        ensure_admin_account(db)
    monkeypatch.setattr(admin_env, "admin_password", SecretStr("Matkhau-Khac-2027"))
    with SessionLocal() as db:
        ensure_admin_account(db)
        [admin] = admins(db)
        assert verify_password("Matkhau-Manh-2026", admin.password_hash)


@pytest.mark.parametrize(("email", "password"), [("", "Matkhau-Manh-2026"), (EMAIL, ""), (EMAIL, "yeu")])
def test_missing_or_weak_settings_create_nothing(admin_env, monkeypatch, email, password):
    monkeypatch.setattr(admin_env, "admin_email", email)
    monkeypatch.setattr(admin_env, "admin_password", SecretStr(password))
    with SessionLocal() as db:
        ensure_admin_account(db)
        assert admins(db) == []
