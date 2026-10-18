from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.config import get_settings


class Base(DeclarativeBase):
    """Lớp cơ sở cho mọi bảng ORM."""


def _create_engine(database_url: str):
    # Dịch vụ Cloud (Neon, Render) thường trả URL bắt đầu bằng postgres:// hoặc postgresql://
    # SQLAlchemy 2.0 ưu tiên tìm psycopg (v3). Ta ép dùng driver postgresql+psycopg2:// để tương thích psycopg2-binary
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    url = make_url(database_url)
    connect_args = {}
    if url.get_backend_name() == "sqlite":
        # FastAPI chạy dependency đồng bộ trong threadpool nên cần cho phép dùng kết nối khác thread.
        connect_args["check_same_thread"] = False
        if url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(database_url, connect_args=connect_args)


engine = _create_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: mở một session cho mỗi request và đóng khi xong."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _add_missing_columns() -> None:
    """Thêm cột mới vào bảng đã có (create_all chỉ tạo bảng mới). Chỉ dùng cho cột cho phép NULL."""
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name not in existing:
                    column_type = column.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column_type}'))


def _relax_interview_cv_columns() -> None:
    """Phỏng vấn không cần CV (interview_mode = "jd_only"): cv_version_id / cv_file_name được để trống.

    SQLite không đổi được NOT NULL tại chỗ nên dựng lại bảng interview_sessions và chép toàn bộ buổi phỏng vấn cũ sang
    (không xoá dữ liệu). legacy_alter_table giữ khoá ngoại của interview_turns trỏ đúng bảng mới.
    """
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='interview_sessions'")
        ).fetchone()
        if not row or not row[0] or "cv_version_id VARCHAR(64) NOT NULL" not in row[0]:
            return
        table = Base.metadata.tables["interview_sessions"]
        old_columns = {r[1] for r in conn.execute(text("PRAGMA table_info(interview_sessions)"))}
        # Buổi phỏng vấn cũ đều có CV nên chế độ là "with_cv"
        targets = [c.name for c in table.columns if c.name in old_columns]
        sources = [f'"{c}"' for c in targets]
        if "interview_mode" not in old_columns:
            targets.append("interview_mode")
            sources.append("'with_cv'")
        columns = ", ".join(f'"{c}"' for c in targets)
        values = ", ".join(sources)
        indexes = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='interview_sessions' AND sql IS NOT NULL"
            )
        ).fetchall()
        for (name,) in indexes:
            conn.execute(text(f'DROP INDEX "{name}"'))
        conn.execute(text("PRAGMA legacy_alter_table=ON"))
        conn.execute(text("ALTER TABLE interview_sessions RENAME TO interview_sessions_old"))
        table.create(conn)
        conn.execute(text(f"INSERT INTO interview_sessions ({columns}) SELECT {values} FROM interview_sessions_old"))
        conn.execute(text("DROP TABLE interview_sessions_old"))
        conn.execute(text("PRAGMA legacy_alter_table=OFF"))


def init_db() -> None:
    """Tạo bảng / cột còn thiếu và nạp dữ liệu demo (idempotent, gọi khi khởi động app).

    Chưa dùng migration: cột mới được thêm tự động; đổi kiểu hoặc xoá cột thì xoá file data/app.db để tạo lại.
    """
    from src.db import models  # noqa: F401  (đăng ký các bảng vào Base.metadata)
    from src.db.demo_cohort import seed_demo_cohort
    from src.db.migrations.assistant_runs import upgrade as upgrade_assistant_runs
    from src.db.migrations.auth import upgrade as upgrade_auth
    from src.db.migrations.pii_vault import upgrade as upgrade_pii_vault
    from src.db.seed import ensure_admin_account, fail_interrupted_analyses, seed_demo_users, seed_jd_library
    from src.services.cv_versions import backfill as backfill_cv_versions
    from src.services.cv_versions import backfill_ocr_flags

    _relax_interview_cv_columns()
    Base.metadata.create_all(bind=engine)
    upgrade_auth(engine)
    upgrade_pii_vault(engine)
    upgrade_assistant_runs(engine)
    _add_missing_columns()
    with SessionLocal() as db:
        seed_demo_users(db)
        ensure_admin_account(db)
        seed_jd_library(db)
        if get_settings().app_env != "production" and get_settings().seed_demo_cohort:
            seed_demo_cohort(db)
        fail_interrupted_analyses(db)
        # Phiên bản CV tạo trước khi có lịch sử phiên bản theo từng CV
        backfill_cv_versions(db)
        # CV tải lên trước khi lưu cờ "đọc bằng OCR"
        backfill_ocr_flags(db)
        from src.services.assistant.runs import sweep_running

        sweep_running(db)
