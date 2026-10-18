"""
Tài khoản: băm mật khẩu, phiên đăng nhập, đăng ký sinh viên, quên / đổi mật khẩu.
Chỉ sinh viên tự đăng ký (chờ quản trị viên phân công cố vấn); tài khoản cố vấn do quản trị viên tạo bằng mật khẩu tạm.
Email là email cá nhân, không gắn với trường.
"""

import hashlib
import hmac
import re
import secrets
import unicodedata
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src.api.errors import AppError
from src.config import get_settings
from src.db.models import AuthSession, PasswordResetToken, User, utcnow
from src.services import email_templates, notifications
from src.services.mailer import send_email

PBKDF2_ITERATIONS = 390_000
PASSWORD_MIN_LENGTH = 8
MIN_AGE_YEARS = 15

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


# ---------- Mật khẩu ----------


SCRYPT_N = 32_768
SCRYPT_R = 8
SCRYPT_P = 3


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=67108864).hex()
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    parts = stored.split("$")
    if len(parts) == 6 and parts[0] == "scrypt":
        _, n_str, r_str, p_str, salt_hex, digest = parts
        try:
            n, r, p = int(n_str), int(r_str), int(p_str)
            if n <= 1 or (n & (n - 1)) != 0:
                return False
            salt = bytes.fromhex(salt_hex)
            candidate = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=67108864).hex()
            return hmac.compare_digest(candidate, digest)
        except Exception:
            return False
    elif len(parts) == 4 and parts[0] == "pbkdf2_sha256":
        _, iterations_str, salt_hex, digest = parts
        try:
            iterations = int(iterations_str)
            salt = bytes.fromhex(salt_hex)
            candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations).hex()
            return hmac.compare_digest(candidate, digest)
        except Exception:
            return False
    return False


def check_password_rules(password: str) -> None:
    """Cùng quy tắc với frontend (lib/password.ts): ≥ 8 ký tự, có cả chữ và số, không khoảng trắng."""
    if (
        len(password) < PASSWORD_MIN_LENGTH
        or not any(c.isalpha() for c in password)
        or not any(c.isdigit() for c in password)
        or any(c.isspace() for c in password)
    ):
        raise AppError(422, "Mật khẩu cần ít nhất 8 ký tự, có cả chữ và số, không có khoảng trắng.", "weak_password")


# ---------- Kiểm tra dữ liệu hồ sơ ----------


def normalize_email(email: str) -> str:
    return unicodedata.normalize("NFC", email).strip().lower()


def check_email(email: str) -> str:
    value = normalize_email(email)
    if not _EMAIL_RE.match(value) or len(value) > 255:
        raise AppError(422, "Email chưa đúng định dạng.", "invalid_email")
    return value


def normalize_phone(phone: str) -> str:
    """Số điện thoại Việt Nam: 10 chữ số bắt đầu bằng 0; chấp nhận "+84" và dấu cách / chấm / gạch."""
    digits = re.sub(r"[\s.\-]", "", phone)
    if digits.startswith("+84"):
        digits = "0" + digits[3:]
    if not re.fullmatch(r"0\d{9}", digits):
        raise AppError(422, "Số điện thoại cần đủ 10 chữ số, bắt đầu bằng 0.", "invalid_phone")
    return f"{digits[:4]} {digits[4:7]} {digits[7:]}"


def check_date_of_birth(value: date, today: date | None = None) -> date:
    today = today or utcnow().date()
    if value > today:
        raise AppError(422, "Ngày sinh không thể ở tương lai.", "invalid_date_of_birth")
    try:
        min_age = today.replace(year=today.year - MIN_AGE_YEARS)
    except ValueError:  # 29/02
        min_age = today.replace(year=today.year - MIN_AGE_YEARS, day=28)
    if value > min_age:
        raise AppError(422, "Bạn cần từ 15 tuổi trở lên để tạo tài khoản.", "too_young")
    if value.year < 1940:
        raise AppError(422, "Ngày sinh chưa đúng.", "invalid_date_of_birth")
    return value


def check_full_name(name: str) -> str:
    value = " ".join(name.split())
    if len(value) < 2 or len(value) > 120:
        raise AppError(422, "Hãy nhập họ và tên (2–120 ký tự).", "invalid_full_name")
    return value


def find_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == normalize_email(email)))


# ---------- Phiên đăng nhập ----------


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User) -> tuple[str, datetime]:
    """Tạo phiên mới; trả về (token đặt vào cookie, thời điểm hết hạn)."""
    token = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(days=get_settings().session_days)
    db.add(AuthSession(id=_token_hash(token), user_id=user.id, expires_at=expires))
    db.commit()
    return token, expires


def user_from_session(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    session = db.get(AuthSession, _token_hash(token))
    if session is None or session.expires_at <= utcnow():
        return None
    return db.get(User, session.user_id)


def end_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(AuthSession).where(AuthSession.id == _token_hash(token)))
        db.commit()


def end_all_sessions(db: Session, user: User) -> None:
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))


# ---------- Đăng nhập / đăng ký ----------


# Vai trò cố vấn đang tạm ẩn (settings.advisor_features)
ADVISOR_PAUSED = "Tính năng dành cho cố vấn đang tạm ngưng. Hãy liên hệ quản trị viên."


def login(db: Session, email: str, password: str) -> User:
    settings = get_settings()
    now = utcnow()
    user = find_by_email(db, email)
    if user is not None and user.locked_until and user.locked_until > now:
        minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise AppError(429, f"Bạn đã nhập sai quá nhiều lần. Hãy thử lại sau {minutes} phút.", "too_many_attempts")
    if user is None or not verify_password(password, user.password_hash):
        if user is not None:
            user.failed_logins = (user.failed_logins or 0) + 1
            left = settings.login_max_attempts - user.failed_logins
            if left <= 0:
                user.failed_logins = 0
                user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
                db.commit()
                raise AppError(
                    429,
                    f"Bạn đã nhập sai quá nhiều lần. Hãy thử lại sau {settings.login_lock_minutes} phút.",
                    "too_many_attempts",
                )
            db.commit()
            raise AppError(
                401,
                f"Email hoặc mật khẩu chưa đúng. Còn {left} lần thử trước khi tạm khoá {settings.login_lock_minutes} phút.",
                "invalid_credentials",
            )
        raise AppError(401, "Email hoặc mật khẩu chưa đúng.", "invalid_credentials")
    user.failed_logins = 0
    user.locked_until = None
    db.commit()
    if user.disabled_at is not None:
        raise AppError(403, "Tài khoản đã bị tạm khoá. Hãy liên hệ quản trị viên.", "account_disabled")
    if user.role == "advisor" and not settings.advisor_features:
        raise AppError(403, ADVISOR_PAUSED, "advisor_disabled")
    return user


def register(
    db: Session,
    *,
    full_name: str,
    date_of_birth: date,
    phone: str,
    email: str,
    password: str,
    consent: bool,
    integrity_pledge: bool,
) -> User:
    if not (consent and integrity_pledge):
        raise AppError(422, "Hãy đồng ý xử lý dữ liệu và cam kết liêm chính để tạo tài khoản.", "consent_required")
    name = check_full_name(full_name)
    dob = check_date_of_birth(date_of_birth)
    phone_value = normalize_phone(phone)
    email_value = check_email(email)
    check_password_rules(password)
    if find_by_email(db, email_value) is not None:
        raise AppError(409, "Email này đã có tài khoản.", "email_taken")
    now = utcnow()
    user = User(
        id=f"sv-{uuid.uuid4().hex[:10]}",
        role="student",
        full_name=name,
        subtitle=email_value,
        email=email_value,
        phone=phone_value,
        date_of_birth=dob,
        password_hash=hash_password(password),
        consent_accepted_at=now,
        integrity_pledge_at=now,
    )
    db.add(user)
    for admin in db.scalars(select(User).where(User.role == "admin", User.disabled_at.is_(None))):
        notifications.notify(
            db,
            admin,
            "student_registered",
            f"{name} vừa tạo tài khoản",
            "Sinh viên mới đang chờ phân công cố vấn.",
            action_label="Phân công",
            action_href="/admin/students?filter=unassigned",
        )
    db.commit()
    return user


# ---------- Quên / đổi mật khẩu ----------


def request_password_reset(db: Session, email: str) -> None:
    """Luôn coi là thành công (không lộ email nào có tài khoản); chỉ gửi link khi tài khoản tồn tại."""
    settings = get_settings()
    user = find_by_email(db, email)
    if user is None:
        return
    token = secrets.token_urlsafe(32)
    db.add(
        PasswordResetToken(
            id=_token_hash(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(minutes=settings.password_reset_minutes),
        )
    )
    db.commit()
    link = f"{settings.frontend_url.rstrip('/')}/reset-password?token={token}"
    text, html = email_templates.password_reset(
        user.full_name,
        user.email,
        link,
        settings.password_reset_minutes,
        email_templates.logo_url(settings.frontend_url),
    )
    send_email(user.email, "Đặt lại mật khẩu CareerV", text, html=html)


def confirm_password_reset(db: Session, token: str, new_password: str) -> User:
    record = db.get(PasswordResetToken, _token_hash(token)) if token else None
    now = utcnow()
    if record is None or record.used_at is not None or record.expires_at <= now:
        raise AppError(400, "Link đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.", "invalid_token")
    check_password_rules(new_password)
    user = db.get(User, record.user_id)
    if user is None:
        raise AppError(400, "Link đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.", "invalid_token")
    record.used_at = now
    _set_password(db, user, new_password)
    user.failed_logins = 0
    user.locked_until = None
    db.commit()
    return user


def change_password(db: Session, user: User, current: str, new: str) -> datetime:
    if not verify_password(current, user.password_hash):
        raise AppError(400, "Mật khẩu hiện tại không đúng.", "wrong_password")
    if current == new:
        raise AppError(422, "Mật khẩu mới phải khác mật khẩu hiện tại.", "same_password")
    check_password_rules(new)
    _set_password(db, user, new)
    db.commit()
    return user.password_updated_at


def _set_password(db: Session, user: User, password: str) -> None:
    """Đặt mật khẩu mới (thay cả mật khẩu tạm) và đăng xuất mọi phiên cũ (route tạo phiên mới cho thiết bị hiện tại)."""
    user.password_hash = hash_password(password)
    user.password_updated_at = utcnow()
    user.must_change_password = None
    end_all_sessions(db, user)
