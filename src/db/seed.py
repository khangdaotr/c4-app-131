import json
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.config import get_settings
from src.db.models import AdvisorAssignment, GapAnalysis, JobDescription, User, utcnow
from src.services.auth import hash_password

# Individual development accounts. IDs are retained for existing records; these
# accounts now require their own credentials and are never selected by role.
DEMO_STUDENT_ID = "sv-0142"
SECOND_STUDENT_ID = "sv-0143"
DEMO_ADVISOR_ID = "cv-007"
DEMO_ADMIN_ID = "qt-001"

# Public development-only passwords, never used to provision production accounts.
DEV_PASSWORDS = {
    DEMO_STUDENT_ID: "Student-A-dev-only!",
    SECOND_STUDENT_ID: "Student-B-dev-only!",
    DEMO_ADVISOR_ID: "Advisor-dev-only!",
    DEMO_ADMIN_ID: "careerx123",
}

DEMO_USERS = [
    {
        "id": DEMO_STUDENT_ID,
        "role": "student",
        "full_name": "Nguyễn Minh Anh",
        "subtitle": "KDQT - K2021",
        "email": "minhanh.k21@student.university.edu.vn",
    },
    {
        "id": SECOND_STUDENT_ID,
        "role": "student",
        "full_name": "Lê Thu Hà",
        "subtitle": "HTTT - K2022",
        "email": "thuha.k22@student.university.edu.vn",
    },
    {
        "id": DEMO_ADVISOR_ID,
        "role": "advisor",
        "full_name": "ThS. Trần Hoàng Nam",
        "subtitle": "Cố vấn hướng nghiệp",
        "email": "nam.tran@careerv.vn",
        "title": "Cố vấn hướng nghiệp",
        "office": "Trực tuyến qua Google Meet",
        "office_hours": "Thứ 3 & Thứ 5 (14:00 – 16:30)",
    },
    {
        "id": DEMO_ADMIN_ID,
        "role": "admin",
        "full_name": "Quản trị CareerV",
        "subtitle": "Quản trị hệ thống",
        "email": "admin@careerv.vn",
    },
]


def seed_demo_users(db: Session) -> None:
    """Seed individual development accounts; preserve existing passwords and assignments."""
    settings = get_settings()
    if settings.app_env == "production":
        return
    passwords = {
        DEMO_STUDENT_ID: settings.seed_student_a_password.get_secret_value() or DEV_PASSWORDS[DEMO_STUDENT_ID],
        SECOND_STUDENT_ID: settings.seed_student_b_password.get_secret_value() or DEV_PASSWORDS[SECOND_STUDENT_ID],
        DEMO_ADVISOR_ID: settings.seed_advisor_password.get_secret_value() or DEV_PASSWORDS[DEMO_ADVISOR_ID],
        DEMO_ADMIN_ID: DEV_PASSWORDS[DEMO_ADMIN_ID],
    }
    for data in DEMO_USERS:
        user = db.get(User, data["id"])
        if user is None:
            user = User(**data)
            db.add(user)
        else:
            for key, value in data.items():
                if getattr(user, key) is None:
                    setattr(user, key, value)
        if not user.password_hash:
            user.password_hash = hash_password(passwords[data["id"]])
    db.flush()
    migrate_brand_domain(db)
    _set_demo_passwords(db)
    assign(db, DEMO_ADVISOR_ID, DEMO_STUDENT_ID)
    assign(db, DEMO_ADVISOR_ID, SECOND_STUDENT_ID)
    db.commit()


# Đổi tên CareerX → CareerV: email tài khoản demo và mật khẩu demo cũ
LEGACY_EMAIL_DOMAIN = "@careerx.vn"
BRAND_EMAIL_DOMAIN = "@careerv.vn"
LEGACY_DEMO_PASSWORD = "careerx123"


def migrate_brand_domain(db: Session) -> None:
    """Email "@careerx.vn" (cố vấn, quản trị demo tạo trước khi đổi tên) đổi sang "@careerv.vn" nếu chưa ai dùng."""
    from sqlalchemy import select

    for user in db.scalars(select(User).where(User.email.like(f"%{LEGACY_EMAIL_DOMAIN}"))):
        old, new = user.email, user.email[: -len(LEGACY_EMAIL_DOMAIN)] + BRAND_EMAIL_DOMAIN
        if db.scalars(select(User.id).where(User.email == new)).first() is None:
            user.email = new
            if user.subtitle == old:
                user.subtitle = new
    db.flush()


def _set_demo_passwords(db: Session) -> None:
    """Đặt mật khẩu DEMO_ACCOUNT_PASSWORD cho tài khoản demo chưa có mật khẩu (để thử trang Đăng nhập)."""
    from src.config import get_settings
    from src.services.auth import hash_password, verify_password

    password = get_settings().demo_account_password
    if not password:
        return
    for user_id in (DEMO_STUDENT_ID, DEMO_ADVISOR_ID, DEMO_ADMIN_ID):
        user = db.get(User, user_id)
        # Chưa có mật khẩu, hoặc vẫn là mật khẩu demo cũ "careerx123" (người dùng chưa tự đổi) → mật khẩu demo hiện tại
        legacy = (
            password != LEGACY_DEMO_PASSWORD and verify_password(LEGACY_DEMO_PASSWORD, user.password_hash)
            if user
            else False
        )
        if user is not None and (user.password_hash is None or legacy):
            user.password_hash = hash_password(password)
            if user.role == "student" and user.consent_accepted_at is None:
                user.consent_accepted_at = utcnow()


LEGACY_FIELDS = ("subtitle", "email", "title", "office")


def migrate_school_profile(user: User, data: dict) -> None:
    """
    Hồ sơ demo tạo trước khi bỏ email trường / mã SV: đổi sang thông tin cá nhân trong `data`.
    Chỉ áp dụng cho bản ghi còn email đuôi "university.edu.vn" nên chạy lại không ghi đè thay đổi của người dùng.
    """
    if not user.email.endswith("university.edu.vn"):
        return
    for key in LEGACY_FIELDS:
        if key in data:
            setattr(user, key, data[key])


def assign(db: Session, advisor_id: str, student_id: str) -> None:
    """Phân công cố vấn cho SV nếu SV chưa có cố vấn."""
    if db.scalar(select(AdvisorAssignment).where(AdvisorAssignment.student_id == student_id)) is None:
        db.add(AdvisorAssignment(id=f"as_{student_id}", advisor_id=advisor_id, student_id=student_id))


JD_LIBRARY_FILE = Path(__file__).parent / "fixtures" / "jd_library.json"


def seed_jd_library(db: Session) -> None:
    """
    Nạp thư viện JD từ fixtures/jd_library.json: thêm JD còn thiếu; JD quản trị viên chưa sửa (updated_at = None)
    thì vẫn đồng bộ theo file. Các trường cấu trúc chung được tách lại từ toàn văn khi nội dung đổi.
    """
    from src.services.jds import backfill_structure

    items = json.loads(JD_LIBRARY_FILE.read_text(encoding="utf-8"))
    for item in items:
        jd = db.get(JobDescription, item["id"])
        if jd is not None and jd.updated_at is not None:
            continue
        if jd is None:
            jd = JobDescription(id=item["id"], source="library")
            db.add(jd)
        if jd.content != item["content"]:
            jd.description = None  # tách lại các mục ở backfill_structure
        jd.title = item["title"]
        jd.company = item.get("company")
        jd.industry = item.get("industry")
        jd.level = item.get("level")
        jd.content = item["content"]
        jd.skills = item["skills"]
        jd.skills_source = "admin"
    db.commit()
    backfill_structure(db)


def ensure_admin_account(db: Session) -> None:
    """
    Tạo tài khoản quản trị từ ADMIN_EMAIL / ADMIN_PASSWORD (chạy cả khi APP_ENV=production, nơi không có tài khoản
    demo). Đã có tài khoản với email này thì giữ nguyên, không đổi mật khẩu (admin tự đổi trên web không bị ghi đè).
    Không bao giờ ghi mật khẩu ra log.
    """
    import logging
    import uuid

    from src.api.errors import AppError
    from src.services.auth import check_password_rules, find_by_email, normalize_email

    settings = get_settings()
    email = normalize_email(settings.admin_email)
    password = settings.admin_password.get_secret_value()
    if not email or not password:
        return
    if find_by_email(db, email) is not None:
        return
    try:
        check_password_rules(password)
    except AppError:
        logging.getLogger(__name__).warning("ADMIN_PASSWORD quá yếu (cần ≥ 8 ký tự, có chữ và số): chưa tạo admin")
        return
    db.add(
        User(
            id=f"qt-{uuid.uuid4().hex[:10]}",
            role="admin",
            full_name="Quản trị CareerV",
            subtitle="Quản trị hệ thống",
            email=email,
            password_hash=hash_password(password),
        )
    )
    db.commit()


def fail_interrupted_analyses(db: Session) -> None:
    """Lượt phân tích đang chạy dở khi máy chủ tắt sẽ không bao giờ xong; đánh dấu lỗi để SV chạy lại."""
    db.execute(
        update(GapAnalysis)
        .where(GapAnalysis.status == "processing")
        .values(
            status="failed",
            current_step=None,
            error_message="Máy chủ đã khởi động lại trong lúc phân tích. Hãy bấm Thử lại.",
        )
    )
    db.commit()


def seed_vector_store() -> int:
    """Nạp JD thư viện đang hiển thị (từ DB) vào Vector Store (ChromaDB); JD đã ẩn bị bỏ khỏi kho."""
    try:
        from src.db.database import SessionLocal
        from src.services.jd_library import jd_item
        from src.services.jd_store import get_jd_store

        store = get_jd_store()
        with SessionLocal() as db:
            library = list(db.scalars(select(JobDescription).where(JobDescription.source == "library")))
        if not library:
            return store.index_from_fixtures(str(JD_LIBRARY_FILE))
        hidden = [jd.id for jd in library if jd.status == "hidden"]
        store.remove(hidden)
        return store.index_items([jd_item(jd) for jd in library if jd.status != "hidden"])
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("Không thể nạp JD Vector Store: %s", e)
        return 0


if __name__ == "__main__":
    # Run from the repository root: python -m src.db.seed.
    from src.db.database import init_db

    init_db()
