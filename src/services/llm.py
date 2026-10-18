import asyncio
import hashlib
import json
import re
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

from langchain_core.messages import HumanMessage
from openai import RateLimitError

from src.config import get_settings
from src.services.providers.gateway import GatewayChat, GatewayError, provider_scope, wrap_chat
from src.services.providers.llm_client import LlmClient

# Tiền tố của key mẫu trong .env.example; key như vậy coi như chưa cấu hình LLM.
_PLACEHOLDER_PREFIXES = (
    "your-",
    "your_",
    "sk-dummy",
    "gsk_your",
    "sk-or-v1-your",
    "sk-your",
    "sk-placeholder",
    "gsk_placeholder",
)
LLM_HEALTH_TTL_SECONDS = 30.0
LLM_HEALTH_TIMEOUT_SECONDS = 3.0
_llm_health_cache: tuple[str, float, dict[str, Any]] | None = None
_llm_health_lock = asyncio.Lock()


def get_llm() -> GatewayChat:
    return get_settings().get_chat_model()


def get_assistant_llm() -> LlmClient:
    """The assistant uses the raw SDK through the shared outbound gateway."""
    return LlmClient(settings=get_settings())


def assistant_llm_configured() -> bool:
    key = get_settings().llm_api_key.get_secret_value().strip().casefold()
    return (
        bool(key)
        and not key.startswith(_PLACEHOLDER_PREFIXES)
        and key not in {"changeme", "placeholder", "none", "dummy"}
    )


def llm_configured() -> bool:
    """Có API key thật cho provider đang chọn hay không (key rỗng hoặc key mẫu → False)."""
    api_key, _ = get_settings().get_llm_credentials()
    api_key = api_key.strip().casefold()
    return (
        bool(api_key)
        and not api_key.startswith(_PLACEHOLDER_PREFIXES)
        and api_key
        not in {
            "changeme",
            "placeholder",
            "none",
            "dummy",
        }
    )


async def check_llm_health(*, assistant: bool = False) -> dict[str, Any]:
    """Probe the configured model once per TTL, sharing concurrent health checks."""
    global _llm_health_cache
    settings = get_settings()
    model_name = settings.llm_model_agent if assistant else settings.model_name
    if not (assistant_llm_configured() if assistant else llm_configured()):
        return {
            "status": "offline",
            "provider": "none",
            "model": model_name,
            "is_live": False,
            "message": "Chưa cấu hình API Key hoặc dùng key mẫu",
        }

    api_key, base_url = (
        (settings.llm_api_key.get_secret_value(), settings.llm_base_url or "https://api.deepseek.com")
        if assistant
        else settings.get_llm_credentials()
    )
    hostname = urlsplit(base_url).hostname
    provider = {
        "api.groq.com": "groq",
        "openrouter.ai": "openrouter",
        "api.openai.com": "openai",
        "api.deepseek.com": "deepseek",
    }.get(hostname, settings.llm_provider)
    # Invalidate immediately when credentials, endpoint or model change.
    signature = hashlib.sha256(
        json.dumps([api_key, base_url, model_name, provider, assistant]).encode("utf-8")
    ).hexdigest()
    async with _llm_health_lock:
        if (
            _llm_health_cache is not None
            and _llm_health_cache[0] == signature
            and monotonic() - _llm_health_cache[1] < LLM_HEALTH_TTL_SECONDS
        ):
            return dict(_llm_health_cache[2])
        result: dict[str, Any] = {
            "status": "offline",
            "provider": provider,
            "model": model_name,
            "is_live": False,
            "message": "",
        }
        try:
            if assistant:
                with provider_scope(mask_only=True):
                    client = LlmClient(
                        settings=settings.model_copy(
                            update={"llm_timeout_s": LLM_HEALTH_TIMEOUT_SECONDS, "llm_max_retries": 0}
                        )
                    )
                    try:
                        await client.chat([{"role": "user", "content": "ping"}], thinking=False, max_tokens=8)
                    finally:
                        await client.aclose()
            else:
                llm = settings.get_chat_model(timeout=LLM_HEALTH_TIMEOUT_SECONDS, max_retries=0, max_tokens=8)
                await asyncio.wait_for(
                    wrap_chat(llm, timeout=LLM_HEALTH_TIMEOUT_SECONDS).ainvoke([HumanMessage(content="ping")]),
                    timeout=LLM_HEALTH_TIMEOUT_SECONDS,
                )
            result.update(status="live", is_live=True)
        except TimeoutError:
            result["message"] = "LLM không phản hồi trong 3 giây. Đang dùng chế độ dự phòng."
        except Exception:
            # Provider error bodies can echo credentials; expose only the error class.
            result["message"] = "Không kết nối được LLM. Đang dùng chế độ dự phòng."
        _llm_health_cache = (signature, monotonic(), result)
        return dict(result)


# Hết hạn mức token theo phút (Groq gói miễn phí 8.000 token/phút): chờ đúng số giây nhà cung cấp báo rồi thử lại,
# nhưng không chờ quá mức này (hạn mức theo ngày thì chờ cũng vô ích)
RATE_LIMIT_MAX_WAIT_SECONDS = 30.0
_RETRY_AFTER = re.compile(r"try again in (?:(\d+)m)?([\d.]+)s", re.IGNORECASE)


def retry_after_seconds(error: RateLimitError) -> float | None:
    """Số giây cần chờ theo lỗi 429 ("Please try again in 26.69s" hoặc header retry-after); None nếu không rõ."""
    header = error.response.headers.get("retry-after") if error.response is not None else None
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    match = _RETRY_AFTER.search(str(error))
    if not match:
        return None
    return int(match.group(1) or 0) * 60 + float(match.group(2))


class InvalidJsonError(GatewayError, ValueError):
    """LLM không trả về object JSON hợp lệ. Không kèm nội dung câu trả lời (có thể chứa thông tin cá nhân)."""


async def _invoke_json_once(prompt: str, temperature: float, timeout: float) -> dict[str, Any]:
    llm = get_settings().get_chat_model(temperature=temperature)
    response = await asyncio.wait_for(llm.ainvoke(prompt), timeout=timeout)
    data = None
    try:
        content = response.content if isinstance(response.content, str) else str(response.content)
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match is not None:
            parsed = json.loads(match.group(0))
            data = parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    if data is None:
        # Báo lỗi ngoài khối except: không giữ chuỗi ngoại lệ / nội dung câu trả lời của LLM
        raise InvalidJsonError("LLM không trả về JSON object hợp lệ")
    return data


async def invoke_json(prompt: str, *, temperature: float = 0.1, timeout: float = 60.0) -> dict[str, Any]:
    """
    Gọi LLM và trả về object JSON trong câu trả lời. Thử lại một lần khi JSON hỏng / bị cắt, hoặc khi hết hạn mức
    theo phút mà chỉ cần chờ ngắn; vẫn lỗi thì báo lỗi để nơi gọi dùng phương án dự phòng.

    Cổng gateway che thông tin cá nhân ở cả câu trả lời của LLM ("[[PERSON_..]]"): đổi mã ẩn về chữ thật trong cùng
    phạm vi che (dùng lại phạm vi của nơi gọi nếu có) để mọi chữ LLM viết hiển thị cho SV không còn mã ẩn.
    """
    with provider_scope() as scope:
        data = await _invoke_json_with_retry(prompt, temperature, timeout)
        return data if scope.mask_only else scope.restore_business(data)


async def _invoke_json_with_retry(prompt: str, temperature: float, timeout: float) -> dict[str, Any]:
    try:
        return await _invoke_json_once(prompt, temperature, timeout)
    except RateLimitError as e:
        wait = retry_after_seconds(e)
        if wait is None or wait > RATE_LIMIT_MAX_WAIT_SECONDS:
            raise
        await asyncio.sleep(wait + 0.5)
    except InvalidJsonError:  # JSON hỏng / bị cắt: thử lại một lần
        pass
    return await _invoke_json_once(prompt, temperature, timeout)
