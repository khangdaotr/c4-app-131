import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.errors import register_error_handlers
from src.api.routes import router
from src.api.security import OriginProtectionMiddleware, trusted_origins
from src.config import get_settings
from src.db.database import init_db
from src.models.schemas import HealthResponse
from src.services.providers.gateway import install_telemetry_policy

install_telemetry_policy()

# Console Windows mặc định cp1252 không in được tiếng Việt/emoji khi output bị chuyển hướng
# (ghi file, chạy nền) và làm app crash lúc khởi động.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Load the selected local CPU NER once, before startup can reach providers.
    # Failure propagates as a sanitized PrivacyError; no regex-only fallback.
    if settings.pii_masking_enabled:
        from src.services.privacy.ner import initialize_privacy

        initialize_privacy(settings)

    tracing_status = "Disabled (privacy policy)"

    init_db()

    # Tự động nạp thư viện JD vào ChromaDB document store (bỏ qua ở production để tiết kiệm RAM dưới 512MB)
    if settings.app_env != "production":
        try:
            from src.db.seed import seed_vector_store

            indexed_count = seed_vector_store()
            print(f"✅ Đã index {indexed_count} JD vào ChromaDB document store.")
        except Exception:
            print("⚠️ Indexing ChromaDB unavailable")

    import gc

    gc.collect()

    print("=" * 60)
    print(f"🚀 {settings.app_name} starting in [{settings.app_env}] mode")
    print(f"🤖 LLM Provider: {settings.llm_provider.upper()} (Model: {settings.model_name})")
    print(f"🔍 LangSmith Tracing: {tracing_status}")
    print(f"📖 Swagger Docs: http://localhost:{settings.app_port}/docs")
    print("=" * 60)

    yield

    print(f"🛑 Shutting down {settings.app_name}...")


app = FastAPI(
    title="Trợ lý nghề nghiệp X (EDU-17) - API",
    description=(
        "API Backend cung cấp dịch vụ phân tích khoảng cách CV-JD (Gap Analysis), "
        "phỏng vấn thử theo Rubric STAR (Mock Interview), và Dashboard cố vấn (Advisor HITL)."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

settings = get_settings()

# CORS: chỉ tin CORS_ORIGINS, FRONTEND_URL và (nếu đặt) mẫu CORS_ORIGIN_REGEX cho bản preview của dự án.
# Không mở cho mọi *.vercel.app: kèm allow_credentials, trang lạ sẽ đọc được dữ liệu của SV đang đăng nhập.
cors_list = sorted(trusted_origins())
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_list or ["*"],
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(OriginProtectionMiddleware)

# Chuẩn hoá lỗi về {"detail": str, "code": str}
register_error_handlers(app)

# Đăng ký routes với tiền tố /api/v1
app.include_router(router, prefix="/api/v1")


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health() -> HealthResponse:
    """Kiểm tra sức khỏe dịch vụ."""
    return HealthResponse(
        status="ok",
        env=settings.app_env,
        version="1.0.0",
    )


@app.get("/", tags=["System"])
async def root():
    """Trang chủ API - Chuyển tiếp tới Swagger UI."""
    return {
        "app": settings.app_name,
        "status": "running",
        "docs_url": "/docs",
        "api_v1": "/api/v1",
    }
