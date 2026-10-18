"""Tài khoản (đăng ký / đăng nhập / quên mật khẩu), Cài đặt, thông báo, JD đã lưu và JD tự dán."""

from unittest.mock import patch

import pytest
from sqlalchemy import delete

from src.db.database import SessionLocal, init_db
from src.db.models import (
    AuthSession,
    JobDescription,
    Notification,
    PasswordResetToken,
    SavedJd,
    User,
)
from src.db.seed import DEMO_STUDENT_ID
from src.services import notifications
from tests.helpers import ADVISOR, STUDENT

API = "/api/v1"
NEW_EMAIL = "nguyenvana@gmail.com"
PASSWORD = "matkhau12"
REGISTER = {
    "full_name": "  Nguyễn  Văn A ",
    "date_of_birth": "2003-05-14",
    "phone": "+84 912.345.678",
    "email": "NguyenVanA@Gmail.com",
    "password": PASSWORD,
    "consent": True,
    "integrity_pledge": True,
}
PASTED = (
    "Công ty Y tuyển thực tập sinh phân tích dữ liệu làm việc cùng đội kinh doanh. Mô tả công việc: tổng hợp số liệu "
    "bán hàng hằng tuần, viết truy vấn SQL, dựng báo cáo Power BI và trình bày kết quả cho quản lý. Yêu cầu ứng viên: "
    "thành thạo Excel và SQL, biết Python là lợi thế, có kỹ năng giao tiếp tốt và chủ động học hỏi trong công việc."
)


@pytest.fixture(autouse=True)
def clean_accounts():
    init_db()
    with SessionLocal() as db:
        for model in (AuthSession, PasswordResetToken, Notification, SavedJd):
            db.execute(delete(model))
        db.execute(delete(JobDescription).where(JobDescription.source == "pasted"))
        db.execute(delete(User).where(User.email == NEW_EMAIL))
        demo = db.get(User, DEMO_STUDENT_ID)
        demo.failed_logins, demo.locked_until, demo.preferences = None, None, None
        db.commit()


async def register(client, **overrides):
    return await client.post(f"{API}/auth/register", json={**REGISTER, **overrides})


# ---------- Đăng ký / đăng nhập ----------


@pytest.mark.asyncio
async def test_register_signs_in_with_normalized_profile(client):
    res = await register(client)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["role"] == "student"
    assert (body["profile"]["full_name"], body["profile"]["subtitle"]) == ("Nguyễn Văn A", NEW_EMAIL)
    assert "careerv_session" in res.cookies

    # Cookie phiên đăng nhập được ưu tiên hơn header demo
    me = await client.get(f"{API}/me", headers=STUDENT)
    assert me.json()["full_name"] == "Nguyễn Văn A"
    settings = (await client.get(f"{API}/students/me/settings")).json()
    assert (settings["email"], settings["phone"], settings["date_of_birth"]) == (
        NEW_EMAIL,
        "0912 345 678",
        "2003-05-14",
    )
    assert settings["consent_accepted_at"] is not None

    dup = await register(client, email=NEW_EMAIL.upper())
    assert (dup.status_code, dup.json()["code"]) == (409, "email_taken")

    assert (await client.post(f"{API}/auth/logout")).status_code == 204
    client.cookies.clear()
    assert (await client.get(f"{API}/me")).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("phone", "0912 345", "invalid_phone"),
        ("password", "abcdefgh", "weak_password"),
        ("password", "abc 12345", "weak_password"),
        ("email", "khong-phai-email", "invalid_email"),
        ("date_of_birth", "2020-01-01", "too_young"),
        ("consent", False, "consent_required"),
        ("full_name", " ", "invalid_full_name"),
    ],
)
async def test_register_validates_fields(client, field, value, code):
    res = await register(client, **{field: value})
    assert (res.status_code, res.json()["code"]) == (422, code)


@pytest.mark.asyncio
async def test_login_counts_failures_then_locks(client):
    ok = await client.post(f"{API}/auth/login", json={"email": "MinhAnh.Nguyen@gmail.com", "password": "careerv123"})
    assert ok.status_code == 200 and ok.json()["profile"]["id"] == DEMO_STUDENT_ID
    client.cookies.clear()

    wrong = {"email": "minhanh.nguyen@gmail.com", "password": "sai123456"}
    first = await client.post(f"{API}/auth/login", json=wrong)
    assert (first.status_code, first.json()["code"]) == (401, "invalid_credentials")
    assert "Còn 4 lần thử" in first.json()["detail"]
    for _ in range(3):
        await client.post(f"{API}/auth/login", json=wrong)
    locked = await client.post(f"{API}/auth/login", json=wrong)
    assert (locked.status_code, locked.json()["code"]) == (429, "too_many_attempts")
    # Đang khoá thì mật khẩu đúng cũng không vào được
    still = await client.post(f"{API}/auth/login", json={**wrong, "password": "careerv123"})
    assert still.status_code == 429

    unknown = await client.post(f"{API}/auth/login", json={"email": "ai@gmail.com", "password": "x1234567"})
    assert (unknown.status_code, unknown.json()["code"]) == (401, "invalid_credentials")


@pytest.mark.asyncio
async def test_password_reset_flow(client):
    assert (await register(client)).status_code == 201
    client.cookies.clear()
    sent: list[str] = []
    htmls: list[str] = []

    def capture(to: str, subject: str, body: str, html: str | None = None) -> None:
        sent.append(body)
        htmls.append(html or "")

    with patch("src.services.auth.send_email", side_effect=capture):
        # Email không có tài khoản: vẫn 204, không gửi gì
        assert (await client.post(f"{API}/auth/password-reset", json={"email": "ai@gmail.com"})).status_code == 204
        assert (await client.post(f"{API}/auth/password-reset", json={"email": NEW_EMAIL})).status_code == 204
    [body] = sent
    token = body.split("token=")[1].split()[0]
    # Bản HTML: nút "Đặt lại mật khẩu" trỏ cùng link; chạy localhost thì không chèn ảnh logo
    assert f"token={token}" in htmls[0] and "Đặt lại mật khẩu</a>" in htmls[0] and "<img" not in htmls[0]

    bad = await client.post(f"{API}/auth/password-reset/confirm", json={"token": "x", "new_password": "moi123456"})
    assert (bad.status_code, bad.json()["code"]) == (400, "invalid_token")
    ok = await client.post(f"{API}/auth/password-reset/confirm", json={"token": token, "new_password": "moi123456"})
    assert ok.status_code == 200 and ok.json()["role"] == "student"
    again = await client.post(f"{API}/auth/password-reset/confirm", json={"token": token, "new_password": "khac12345"})
    assert again.status_code == 400

    client.cookies.clear()
    login = await client.post(f"{API}/auth/login", json={"email": NEW_EMAIL, "password": "moi123456"})
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_change_password_keeps_current_device_signed_in(client):
    assert (await register(client)).status_code == 201
    wrong = await client.post(
        f"{API}/auth/change-password", json={"current_password": "sai12345", "new_password": "moi123456"}
    )
    assert wrong.json()["code"] == "wrong_password"
    res = await client.post(
        f"{API}/auth/change-password", json={"current_password": PASSWORD, "new_password": "moi123456"}
    )
    assert res.status_code == 200 and res.json()["password_updated_at"]
    assert (await client.get(f"{API}/me")).json()["full_name"] == "Nguyễn Văn A"


# ---------- Cài đặt & dữ liệu ----------


@pytest.mark.asyncio
async def test_settings_profile_and_data(client):
    assert (await register(client)).status_code == 201
    res = await client.patch(f"{API}/students/me/settings", json={"notifications": {"weekly_reminder": True}})
    assert res.json()["notifications"]["weekly_reminder"] is True
    bad = await client.patch(f"{API}/students/me/settings", json={"privacy": {"khong_co": True}})
    assert bad.json()["code"] == "unknown_setting"

    profile = await client.patch(
        f"{API}/students/me/profile", json={"full_name": "Nguyễn Văn B", "phone": "0987654321"}
    )
    assert (profile.json()["full_name"], profile.json()["phone"]) == ("Nguyễn Văn B", "0987 654 321")
    assert (await client.patch(f"{API}/students/me/profile", json={"phone": "123"})).json()["code"] == "invalid_phone"

    withdrawn = await client.post(f"{API}/students/me/consent/withdraw")
    assert withdrawn.json()["consent_accepted_at"] is None

    link = (await client.post(f"{API}/students/me/data-export")).json()["download_url"]
    export = await client.get(link)
    assert export.status_code == 200 and "attachment" in export.headers["content-disposition"]
    data = export.json()
    assert data["account"]["email"] == NEW_EMAIL and "password_hash" not in data["account"]

    assert (await client.delete(f"{API}/students/me/data")).status_code == 204
    assert (await client.get(f"{API}/cv")).json() == []


# ---------- Thông báo ----------


@pytest.mark.asyncio
async def test_notifications_list_and_read(client):
    with SessionLocal() as db:
        student = db.get(User, DEMO_STUDENT_ID)
        notifications.notify(db, student, "interview_report", "Báo cáo đã sẵn sàng", action_href="/student")
        notifications.notify(db, student, "gap_analysis", "Phân tích xong")
        # SV tắt "Khi báo cáo sẵn sàng" thì không tạo thông báo loại này
        student.preferences = {"notifications": {"report_ready": False}}
        notifications.notify(db, student, "interview_report", "Không được tạo")
        db.commit()

    items = (await client.get(f"{API}/notifications", headers=STUDENT)).json()
    assert sorted(n["title"] for n in items) == ["Báo cáo đã sẵn sàng", "Phân tích xong"]
    assert all(not n["read"] for n in items)
    assert (await client.post(f"{API}/notifications/{items[0]['id']}/read", headers=STUDENT)).status_code == 204
    assert (await client.post(f"{API}/notifications/nt_khong_co/read", headers=STUDENT)).status_code == 404
    assert (await client.post(f"{API}/notifications/read-all", headers=STUDENT)).status_code == 204
    assert all(n["read"] for n in (await client.get(f"{API}/notifications", headers=STUDENT)).json())


# ---------- JD đã lưu, JD tự dán ----------


@pytest.mark.asyncio
async def test_saved_jds(client):
    assert (await client.put(f"{API}/jd/jd-ba-intern/saved", headers=STUDENT)).status_code == 200
    again = await client.put(f"{API}/jd/jd-ba-intern/saved", headers=STUDENT)
    assert again.json()["jd_id"] == "jd-ba-intern"
    assert [s["jd_id"] for s in (await client.get(f"{API}/jd/saved", headers=STUDENT)).json()] == ["jd-ba-intern"]
    assert (await client.put(f"{API}/jd/jd-khong-co/saved", headers=STUDENT)).status_code == 404
    assert (await client.delete(f"{API}/jd/jd-ba-intern/saved", headers=STUDENT)).status_code == 204
    assert (await client.get(f"{API}/jd/saved", headers=STUDENT)).json() == []


@pytest.mark.asyncio
async def test_create_pasted_jd_detects_skills(client):
    short = await client.post(f"{API}/jd", json={"title": "DA", "text": "Quá ngắn"}, headers=STUDENT)
    assert short.json()["code"] == "jd_too_short"
    res = await client.post(
        f"{API}/jd", json={"title": "Data Analyst Intern", "company": "Công ty Y", "text": PASTED}, headers=STUDENT
    )
    assert res.status_code == 201, res.text
    jd = res.json()
    assert jd["source"] == "pasted" and jd["company"] == "Công ty Y"
    assert {"SQL", "Excel"} <= {s["name"] for s in jd["skills"]}
    assert jd["id"] in {j["id"] for j in (await client.get(f"{API}/jd", headers=STUDENT)).json()}


def test_reset_email_template_logo_and_escaping():
    """Logo chỉ chèn khi frontend là tên miền công khai; tên người dùng được escape trong HTML."""
    from src.services import email_templates

    assert email_templates.logo_url("http://localhost:3000") is None
    assert email_templates.logo_url("http://127.0.0.1:3000") is None
    assert email_templates.logo_url("https://careerv.vn/") == "https://careerv.vn/brand/careerv/email-logo.png"

    text, html = email_templates.password_reset(
        "An <b>", "an@example.com", "https://careerv.vn/reset-password?token=abc&x=1", 30, "https://careerv.vn/logo.png"
    )
    assert "An &lt;b&gt;" in html and "<b>," not in html
    assert 'src="https://careerv.vn/logo.png"' in html and "token=abc&amp;x=1" in html
    assert "https://careerv.vn/reset-password?token=abc&x=1" in text and "30 phút" in text


@pytest.mark.asyncio
async def test_advisor_role_is_paused_when_feature_off(client, monkeypatch):
    """Vai trò cố vấn tạm ẩn (ADVISOR_FEATURES=false): cố vấn không đăng nhập / gọi API được; SV và admin vẫn dùng."""
    from src.config import get_settings
    from src.db.models import User
    from src.db.seed import DEMO_ADMIN_ID, DEMO_ADVISOR_ID, DEV_PASSWORDS

    monkeypatch.setattr(get_settings(), "advisor_features", False)

    async def login(user_id: str):
        with SessionLocal() as db:
            email = db.get(User, user_id).email
        return await client.post(f"{API}/auth/login", json={"email": email, "password": DEV_PASSWORDS[user_id]})

    advisor = await login(DEMO_ADVISOR_ID)
    assert (advisor.status_code, advisor.json()["code"]) == (403, "advisor_disabled")
    assert (await client.get(f"{API}/me", headers=ADVISOR)).status_code == 401
    client.cookies.clear()
    assert (await login(DEMO_STUDENT_ID)).status_code == 200
    client.cookies.clear()
    assert (await login(DEMO_ADMIN_ID)).status_code == 200
