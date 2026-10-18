import os
import secrets
from functools import lru_cache
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv
from pydantic import Field, PrivateAttr, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env file explicitly so os.environ is populated early
load_dotenv(override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "Trợ lý nghề nghiệp X (EDU-17)"
    app_env: Literal["development", "production", "test"] = "development"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_host: str = "0.0.0.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    # Mẫu (regex) tên miền frontend được tin thêm, chỉ dùng cho bản preview Vercel của chính dự án. Phải khớp TOÀN BỘ
    # origin và neo vào đuôi tên nhóm (team slug) của tài khoản Vercel, ví dụ
    # ^https://c4-app-131-(git-[a-z0-9-]+|[a-z0-9]+)-ten-nhom\.vercel\.app$. Không dùng ".*\.vercel\.app" hay
    # "c4-app-131.*": ai cũng tạo được trang *.vercel.app. Để trống = chỉ tin CORS_ORIGINS và FRONTEND_URL.
    cors_origin_regex: str = ""
    auth_secret_key: SecretStr = SecretStr("")
    auth_session_ttl_seconds: int = Field(default=28800, ge=300, le=86400)
    session_cookie_name: str = "careerv_session"
    _session_cookie_secure: bool | None = PrivateAttr(default=None)
    session_days: int = 30
    # "lax" cho cùng domain/localhost, "none" cho cross-site (Frontend Vercel + Backend Render)
    session_cookie_samesite: str = "lax"
    password_reset_minutes: int = 30
    login_max_attempts: int = 5
    login_lock_minutes: int = 15
    frontend_url: str = "http://localhost:3000"
    assistant_tz: str = "Asia/Ho_Chi_Minh"
    result_facts_max_field_chars: int = Field(default=80, ge=1, le=500)
    demo_login_enabled: bool = False
    demo_account_password: str = "careerx123"
    # Tài khoản quản trị khi deploy (APP_ENV=production không tạo tài khoản demo): khởi động mà chưa có tài khoản với
    # email này thì tạo admin; đã có thì giữ nguyên (không đổi mật khẩu). Để trống = không tạo.
    admin_email: str = ""
    admin_password: SecretStr = SecretStr("")

    @property
    def session_cookie_secure(self) -> bool:
        if self._session_cookie_secure is not None:
            return self._session_cookie_secure
        return self.app_env == "production"

    @session_cookie_secure.setter
    def session_cookie_secure(self, value: bool | None) -> None:
        self._session_cookie_secure = value

    @model_validator(mode="after")
    def valid_assistant_timezone(self) -> "Settings":
        try:
            ZoneInfo(self.assistant_tz)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            # Windows Python may not ship the system IANA database. The default
            # zone is fixed UTC+07:00 and does not observe daylight saving time.
            if self.assistant_tz == "Asia/Ho_Chi_Minh":
                return self
            raise ValueError("ASSISTANT_TZ must be a valid IANA timezone") from exc
        return self

    # SMTP Mailer
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "CareerX <no-reply@careerx.vn>"
    smtp_starttls: bool = True

    # Soniox Speech-to-Text
    soniox_api_key: str = ""
    soniox_model: str = "vi_v2"
    soniox_ws_url: str = "wss://api.soniox.com/transcribe-websocket"

    # Local privacy extraction (no cloud OCR).
    pii_ocr_command: str = "tesseract"
    pii_ocr_dpi: int = Field(default=200, ge=100, le=400)
    pii_ocr_timeout_seconds: int = Field(default=30, ge=1, le=120)
    pii_document_max_bytes: int = Field(default=20_000_000, ge=1)
    pii_document_max_pages: int = Field(default=30, ge=1, le=100)

    pii_vault_key: SecretStr = SecretStr("")
    pii_vault_ttl_hours: float = Field(default=24, gt=0, le=8760)
    pii_masking_enabled: bool = True
    pii_mask_entity_types: tuple[str, ...] = ("PERSON", "EMAIL", "PHONE", "ID", "URL", "HANDLE", "DOB", "ADDRESS")
    pii_keep_entity_types: tuple[str, ...] = (
        "EMPLOYER",
        "SCHOOL",
        "JOB_TITLE",
        "SKILL",
        "PROJECT",
        "EMPLOYMENT_DATE",
        "CITY",
        "COUNTRY",
    )
    pii_ner_backend: Literal["underthesea", "phobert", "spacy"] = "underthesea"
    pii_spacy_model: str = "xx_ent_wiki_sm"
    pii_phobert_model_dir: str = ""
    pii_ner_cpu_threads: int = Field(default=2, ge=1, le=16)

    @model_validator(mode="after")
    def validate_privacy(self) -> "Settings":
        from src.services.privacy.types import KINDS

        if set(self.pii_mask_entity_types) != KINDS or set(self.pii_keep_entity_types) & KINDS:
            raise ValueError("PII entity configuration must retain all required direct identifiers")
        if self.app_env == "production":
            if not self.pii_masking_enabled:
                raise ValueError("Production requires PII_MASKING_ENABLED=true")
        return self

    @model_validator(mode="after")
    def configure_session_key(self) -> "Settings":
        key = self.auth_secret_key.get_secret_value()
        if not key and self.app_env != "production":
            self.auth_secret_key = SecretStr(secrets.token_urlsafe(48))
        elif len(key.encode()) < 32:
            raise ValueError("AUTH_SECRET_KEY must contain at least 32 bytes; production requires an explicit key")
        return self

    # LLM Provider Configuration (Groq / OpenRouter / OpenAI / DeepSeek)
    llm_provider: Literal["groq", "openrouter", "openai", "deepseek"] = Field(
        default="groq",
        description="LLM provider: deepseek, groq, openrouter, hoặc openai",
    )

    @field_validator("llm_provider", mode="before")
    @classmethod
    def _normalize_llm_provider(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    deepseek_api_key: str = Field(default="", description="API key cho DeepSeek")
    groq_api_key: str = Field(default="", description="API key cho Groq")
    openrouter_api_key: str = Field(default="", description="API key cho OpenRouter")
    openai_api_key: str = Field(default="", description="API key cho OpenAI")

    model_name: str = Field(
        default="openai/gpt-oss-120b",
        description="Tên model LLM mặc định",
    )
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    llm_base_url: str | None = Field(default=None, description="Tùy chỉnh base URL nếu có proxy hoặc endpoint riêng")
    # Assistant v2 raw-provider path (independent of legacy credential fallback).
    llm_api_key: SecretStr = SecretStr("")
    llm_model_agent: str = "deepseek-flash"
    llm_model_router: str = "deepseek-flash"
    llm_thinking_agent: Literal["enabled", "disabled"] = "disabled"
    # Model suy luận (gpt-oss, o-series, gpt-5): mức "medium" mặc định tiêu hết giới hạn đầu ra cho phần suy luận,
    # JSON bị cắt giữa chừng. "low" đủ cho các bước chấm / trích của dự án. Mặc định section 14 là "high".
    llm_reasoning_effort: Literal["low", "medium", "high", "max", ""] = "high"
    llm_timeout_s: float = Field(default=60, gt=0, le=600)
    llm_max_retries: int = Field(default=2, ge=0, le=8)
    router_backend: Literal["deepseek", "shadow"] = "deepseek"
    agent_max_steps: int = Field(default=8, ge=1)
    agent_max_tool_calls: int = Field(default=12, ge=1)
    agent_confirm_ttl_min: int = Field(default=30, ge=1)
    ui_ack_timeout_s: float = Field(default=5, gt=0)
    user_daily_token_cap: int = Field(default=100_000, ge=1)
    trace_backend: Literal["langfuse", "langsmith", "none"] = "none"
    workers: int = Field(default=1, ge=1, le=1)

    # LangSmith Tracing (AI Logs - Deliverable #4)
    langchain_tracing_v2: bool = Field(default=False, description="Automatic tracing is disabled by privacy policy")
    langchain_api_key: str = Field(default="", description="LangSmith API Key")
    langchain_project: str = Field(default="ai20k-p131", description="Tên project trên LangSmith")
    langchain_endpoint: str = Field(
        default="https://api.smith.langchain.com",
        description="LangSmith API Endpoint",
    )

    # Database
    database_url: str = "sqlite:///./data/app.db"

    # Thư mục lưu file CV gốc do sinh viên tải lên
    upload_dir: str = "./data/uploads"

    # Tạo nhóm SV giả định do cố vấn demo phụ trách (dữ liệu minh hoạ cho các trang Cố vấn). Mặc định tắt: trang Quản
    # trị chỉ hiện dữ liệu thật; bật lại bằng SEED_DEMO_COHORT=true (code giữ ở src/db/demo_cohort.py)
    seed_demo_cohort: bool = False

    # Vai trò cố vấn (chia sẻ, nhắn tin, nhận xét, phân công) đang tạm ẩn: tài khoản cố vấn không đăng nhập được.
    # Đặt ADVISOR_FEATURES=true (kèm NEXT_PUBLIC_FEATURE_ADVISOR=true ở frontend) để bật lại.
    advisor_features: bool = False
    seed_student_a_password: SecretStr = SecretStr("")
    seed_student_b_password: SecretStr = SecretStr("")
    seed_advisor_password: SecretStr = SecretStr("")

    # Dung lượng lưu CV cho mỗi sinh viên
    storage_limit_mb: int = 50

    # Vector Store
    chroma_persist_dir: str = "./data/chroma"

    # Assistant & Knowledge Base RAG
    assistant_chroma_collection: str = "assistant_knowledge"
    assistant_chroma_persist_dir: str = "./data/chroma_assistant"
    assistant_embedding_model: str = "intfloat/multilingual-e5-small"
    assistant_embedding_device: str = "cpu"
    # "openrouter": embed via OpenRouter's API (no torch model in server RAM); key = OPENROUTER_API_KEY
    assistant_embedding_provider: Literal["local", "openrouter"] = "local"
    assistant_embedding_api_model: str = "baai/bge-m3"
    assistant_embedding_api_base_url: str = "https://openrouter.ai/api/v1"
    assistant_embedding_api_batch_size: int = Field(default=32, ge=1, le=256)
    assistant_docs_dir: str = "./docs/user-guide"
    assistant_locate_threshold: float = Field(default=0.78, ge=0.0, le=1.0)
    assistant_locate_margin: float = Field(default=0.10, ge=0.0, le=1.0)
    assistant_top_k: int = 5
    rag_abstain_threshold: float = Field(default=0.42, ge=0.0, le=1.0)
    rag_semantic_abstain_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    rag_ui_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    rag_answer_cache_ttl_s: float = Field(default=300.0, gt=0.0)
    rag_answer_cache_maxsize: int = Field(default=256, ge=1)
    assistant_similarity_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    assistant_llm_timeout_seconds: float = Field(default=30.0, gt=0.0, le=120.0)
    assistant_history_turns: int = Field(default=6, ge=0, le=20)
    assistant_stream_checkpoint_seconds: float = Field(default=0.5, gt=0, le=60)

    # Local assistant router. Cache values are decisions, never resolved records.
    router_cache_ttl_s: float = Field(default=300, gt=0)
    router_cache_max: int = Field(default=1024, ge=1)
    router_cache_threshold: float = Field(default=0.9, ge=0, le=1)
    router_max_input_chars: int = Field(default=8000, ge=1)
    router_clf_threshold: float = Field(default=0.20, ge=0, le=1)
    router_clf_margin: float = Field(default=0.0, ge=0, le=1)
    router_classifier_artifact: str = "eval/router/artifacts/router-v2-25dfa7a47266.joblib"

    # Deployment-specific tariff overrides. None means price unknown, not free.
    provider_input_usd_per_million: float | None = Field(default=None, ge=0)
    provider_output_usd_per_million: float | None = Field(default=None, ge=0)
    provider_embedding_usd_per_million: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def configure_llm_credentials(self) -> "Settings":
        if not self.llm_api_key.get_secret_value():
            fallback = self.deepseek_api_key or os.getenv("DEEPSEEK_API_KEY", "")
            if not fallback:
                fallback, _ = self.get_llm_credentials()
            if fallback:
                self.llm_api_key = SecretStr(fallback)
        return self

    def get_llm_credentials(self) -> tuple[str, str]:
        """
        Lấy (api_key, base_url) dựa theo provider đang được kích hoạt.
        Hỗ trợ fallback tự động nếu key của provider ưu tiên chưa được set.
        """
        provider = self.llm_provider.lower()
        if provider == "deepseek":
            api_key = (
                self.deepseek_api_key
                or self.llm_api_key.get_secret_value()
                or os.getenv("DEEPSEEK_API_KEY", "")
                or os.getenv("LLM_API_KEY", "")
            )
            base_url = self.llm_base_url or "https://api.deepseek.com"
            return api_key, base_url

        if provider == "groq":
            api_key = self.groq_api_key or os.getenv("GROQ_API_KEY", "")
            base_url = self.llm_base_url or "https://api.groq.com/openai/v1"
            if not api_key and (self.deepseek_api_key or os.getenv("DEEPSEEK_API_KEY")):
                api_key = self.deepseek_api_key or os.getenv("DEEPSEEK_API_KEY", "")
                base_url = self.llm_base_url or "https://api.deepseek.com"
            elif not api_key and (self.openrouter_api_key or os.getenv("OPENROUTER_API_KEY")):
                api_key = self.openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")
                base_url = self.llm_base_url or "https://openrouter.ai/api/v1"
            elif not api_key and (self.openai_api_key or os.getenv("OPENAI_API_KEY")):
                api_key = self.openai_api_key or os.getenv("OPENAI_API_KEY", "")
                base_url = self.llm_base_url or "https://api.openai.com/v1"
            return api_key, base_url

        if provider == "openrouter":
            api_key = self.openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")
            base_url = self.llm_base_url or "https://openrouter.ai/api/v1"
            if not api_key and (self.deepseek_api_key or os.getenv("DEEPSEEK_API_KEY")):
                api_key = self.deepseek_api_key or os.getenv("DEEPSEEK_API_KEY", "")
                base_url = self.llm_base_url or "https://api.deepseek.com"
            elif not api_key and (self.groq_api_key or os.getenv("GROQ_API_KEY")):
                api_key = self.groq_api_key or os.getenv("GROQ_API_KEY", "")
                base_url = self.llm_base_url or "https://api.groq.com/openai/v1"
            return api_key, base_url

        # Mặc định OpenAI
        api_key = self.openai_api_key or os.getenv("OPENAI_API_KEY", "")
        base_url = self.llm_base_url or "https://api.openai.com/v1"
        return api_key, base_url

    def get_chat_model(self, **kwargs: Any):
        """Chat model tương thích OpenAI API (DeepSeek, Groq, OpenRouter, OpenAI), luôn đi qua cổng gateway."""
        from src.services.providers.gateway import GatewayChat

        temperature = kwargs.pop("temperature", self.llm_temperature)
        if self.llm_provider.lower() == "deepseek":
            default_model = self.model_name if ("deepseek" in self.model_name.lower()) else "deepseek-chat"
        else:
            default_model = self.model_name
        model = kwargs.pop("model", default_model)
        if self.llm_reasoning_effort and is_reasoning_model(model):
            kwargs.setdefault("reasoning_effort", self.llm_reasoning_effort)
        if self.llm_provider.lower() == "deepseek":
            # DeepSeek mặc định bật chế độ suy nghĩ: một lần sinh câu hỏi mất ~22 giây (tắt: ~3 giây). Dùng chung
            # LLM_THINKING_AGENT với trợ lý (src/services/providers/llm_client.py) để bật / tắt ở một chỗ
            thinking = "enabled" if self.llm_thinking_agent == "enabled" else "disabled"
            kwargs.setdefault("extra_body", {"thinking": {"type": thinking}})
        return GatewayChat(settings=self, model=model, temperature=temperature, **kwargs)


def is_reasoning_model(model: str) -> bool:
    """Model nhan tham so reasoning_effort; model khac khong gui de tranh loi 400."""
    name = model.lower().rsplit("/", 1)[-1]
    return name.startswith(("gpt-oss", "o1", "o3", "o4", "gpt-5"))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # Never enable automatic tracing of business state, even via inherited env.
    settings.langchain_tracing_v2 = False
    for name in ("LANGCHAIN_TRACING", "LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING"):
        os.environ[name] = "false"
    os.environ.pop("LANGCHAIN_HANDLER", None)
    return settings
