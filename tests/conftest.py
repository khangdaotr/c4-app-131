import os
import tempfile
from pathlib import Path

# Test dùng file SQLite và thư mục upload tạm, không đụng data/.
# Phải đặt trước khi import app vì engine được tạo lúc import src.db.database.
_TMP = Path(tempfile.mkdtemp())
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
# Test tự tạo dữ liệu cần dùng; không nạp nhóm SV giả định của bản demo.
os.environ["SEED_DEMO_COHORT"] = "false"
# Test gọi API bằng header X-Demo-Role thay cho đăng nhập.
os.environ["DEMO_LOGIN_ENABLED"] = "true"
# Test vẫn kiểm các tính năng cố vấn (đang tạm ẩn ở bản chạy thật)
os.environ["ADVISOR_FEATURES"] = "true"

# Không gọi LLM thật khi chạy test (chậm, tốn credit): key rỗng → agent dùng quy tắc dự phòng.
# Biến môi trường được ưu tiên hơn file .env nên ghi đè được key thật trong .env.
for _key in (
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "LLM_API_KEY",
    "LANGCHAIN_API_KEY",
):
    os.environ[_key] = ""
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from unittest.mock import AsyncMock  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from src.config import get_settings  # noqa: E402
from src.db.database import SessionLocal, init_db  # noqa: E402
from src.db.models import User  # noqa: E402
from src.main import app  # noqa: E402
from src.services.auth import hash_password  # noqa: E402
from tests.helpers import ADMIN, ADVISOR, STUDENT  # noqa: E402

_AUTH_READY = False

# Fail before any fixture can seed/delete records if configuration precedence ever
# regresses. Local .env files must never redirect tests into the development DB.
assert get_settings().database_url == f"sqlite:///{(_TMP / 'test.db').as_posix()}"
assert Path(get_settings().upload_dir).resolve() == (_TMP / "uploads").resolve()


@pytest.fixture(scope="session", autouse=True)
def initialized_database():
    """Bootstrap once; individual fixtures may then control their own assignments."""
    init_db()
    # ASGITransport skips startup. Unit tests use a deterministic local NER
    # double; adapter/failure and golden integration tests explicitly replace it.
    from src.services.privacy import ner
    from src.services.privacy.detectors import Detector
    from tests.test_privacy_detectors import EmptyNer

    previous = ner._detector
    ner._detector = Detector(EmptyNer())
    yield
    ner._detector = previous


@pytest_asyncio.fixture
async def client():
    """Async HTTP client for testing API endpoints."""
    # ASGITransport does not run lifespan; initialized_database bootstraps it once.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        accounts = [
            ("sv-0142", "Student-A-dev-only!", STUDENT),
            ("cv-007", "Advisor-dev-only!", ADVISOR),
            ("qt-001", "careerx123", ADMIN),
        ]
        with SessionLocal() as db:
            for user_id, password, _ in accounts:
                user = db.get(User, user_id)
                if user is not None:
                    user.password_hash = hash_password(password)
            db.commit()
        for user_id, password, headers in accounts:
            with SessionLocal() as db:
                user = db.get(User, user_id)
                email = user.email if user else None
            if email:
                response = await ac.post("/api/v1/auth/login", json={"email": email, "password": password})
                if response.status_code == 200:
                    headers.clear()
                    headers["Cookie"] = response.headers["set-cookie"].split(";", 1)[0]
        ac.cookies.clear()
        yield ac


@pytest.fixture
def mock_llm():
    """Mock LLM to avoid calling OpenAI during tests.

    Usage in test:
        def test_something(mock_llm):
            # LLM calls will return mock response instead of hitting OpenAI
            ...
    """
    mock = AsyncMock()
    mock.ainvoke.return_value = AsyncMock(content="Mocked LLM response")
    return mock
