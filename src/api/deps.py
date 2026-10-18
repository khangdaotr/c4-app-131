from datetime import timedelta
from typing import Annotated

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy.orm import Session

from src.api.errors import AppError
from src.config import get_settings
from src.db.database import get_db
from src.db.models import User, utcnow
from src.db.seed import DEMO_ADMIN_ID, DEMO_ADVISOR_ID, DEMO_STUDENT_ID
from src.services import auth

DbSession = Annotated[Session, Depends(get_db)]

# Bản demo: không có phiên đăng nhập thì frontend gửi vai trò qua header X-Demo-Role và backend ánh xạ sang
# người dùng demo cố định (tắt bằng DEMO_LOGIN_ENABLED=false). Phiên đăng nhập luôn được ưu tiên.
_DEMO_USER_BY_ROLE = {"student": DEMO_STUDENT_ID, "advisor": DEMO_ADVISOR_ID, "admin": DEMO_ADMIN_ID}

SessionToken = Annotated[str | None, Cookie(alias=get_settings().session_cookie_name)]

# "Hoạt động" ở trang Quản trị: chỉ ghi lại last_seen_at khi lần trước đã cách quá khoảng này, để không ghi DB mỗi request
_SEEN_EVERY = timedelta(minutes=5)
# Còn mật khẩu tạm thì chỉ gọi được các API tài khoản (đổi mật khẩu, đăng xuất) và /me
_ALLOWED_WITH_TEMP_PASSWORD = ("/api/v1/auth/", "/api/v1/me")


def _session_user(db: Session, session_token: str | None, x_demo_role: str | None) -> User:
    user = auth.user_from_session(db, session_token)
    if user is not None:
        return user
    if get_settings().demo_login_enabled:
        user_id = _DEMO_USER_BY_ROLE.get(x_demo_role or "")
        if user_id is not None:
            demo = db.get(User, user_id)
            if demo is None:
                raise AppError(401, "Không tìm thấy tài khoản demo. Hãy khởi động lại backend.", "unauthenticated")
            return demo
    raise AppError(401, "Phiên đăng nhập đã hết. Hãy đăng nhập lại.", "unauthenticated")


def get_current_user(
    request: Request,
    db: DbSession,
    session_token: SessionToken = None,
    x_demo_role: Annotated[str | None, Header()] = None,
) -> User:
    assistant_request = request.url.path.startswith("/api/v1/assistant/")
    # Reuse session verification and account restrictions, but never the demo
    # identity fallback or activity writes on the assistant boundary.
    user = _session_user(db, session_token, None if assistant_request else x_demo_role)
    if user.disabled_at is not None:
        raise AppError(401, "Tài khoản đã bị tạm khoá. Hãy liên hệ quản trị viên.", "account_disabled")
    if user.role == "advisor" and not get_settings().advisor_features:
        # Phiên cố vấn còn lưu từ trước khi tạm ẩn vai trò cố vấn
        raise AppError(401, auth.ADVISOR_PAUSED, "advisor_disabled")
    if user.must_change_password and not request.url.path.startswith(_ALLOWED_WITH_TEMP_PASSWORD):
        raise AppError(403, "Hãy đổi mật khẩu tạm trước khi tiếp tục.", "password_change_required")
    now = utcnow()
    if not assistant_request and (user.last_seen_at is None or now - user.last_seen_at >= _SEEN_EVERY):
        user.last_seen_at = now
        db.commit()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_student(user: CurrentUser) -> User:
    if user.role != "student":
        raise AppError(403, "Chức năng này chỉ dành cho sinh viên.", "forbidden")
    return user


CurrentStudent = Annotated[User, Depends(get_current_student)]


def get_current_advisor(user: CurrentUser) -> User:
    if user.role != "advisor":
        raise AppError(403, "Chức năng này chỉ dành cho cố vấn.", "forbidden")
    return user


CurrentAdvisor = Annotated[User, Depends(get_current_advisor)]


def get_current_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise AppError(403, "Chức năng này chỉ dành cho quản trị viên.", "forbidden")
    return user


CurrentAdmin = Annotated[User, Depends(get_current_admin)]
