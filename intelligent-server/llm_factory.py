import os
from typing import Optional

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI


def _read_config(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _provider(prefix: str, default_provider: str) -> str:
    return (_read_config(f"{prefix}_PROVIDER") or _read_config("LLM_PROVIDER", default_provider) or default_provider).strip().lower()


def _model(prefix: str, default_model: str) -> str:
    return _read_config(f"{prefix}_MODEL", default_model) or default_model


def _api_key(prefix: str, provider: str) -> Optional[str]:
    specific = _read_config(f"{prefix}_API_KEY")
    if specific:
        return specific
    if provider == "google":
        return _read_config("GOOGLE_API_KEY")
    return _read_config("OPENAI_COMPAT_API_KEY") or _read_config("AIHUBMIX_API_KEY")


def _base_url(prefix: str) -> Optional[str]:
    return (
        _read_config(f"{prefix}_BASE_URL")
        or _read_config("OPENAI_COMPAT_BASE_URL")
        or _read_config("AIHUBMIX_BASE_URL")
    )


def create_chat_model(
    prefix: str,
    *,
    default_model: str,
    default_provider: str,
    temperature: float,
    max_retries: int,
    streaming: bool,
):
    provider = _provider(prefix, default_provider)
    model = _model(prefix, default_model)
    api_key = _api_key(prefix, provider)

    if provider == "google":
        if not api_key:
            raise RuntimeError(f"{prefix}_API_KEY or GOOGLE_API_KEY must be configured for google provider")
        return ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
            max_retries=max_retries,
            streaming=streaming,
            google_api_key=api_key,
        )

    base_url = _base_url(prefix)
    if not api_key or not base_url:
        raise RuntimeError(
            f"{prefix}_API_KEY/{prefix}_BASE_URL or OPENAI_COMPAT_API_KEY/OPENAI_COMPAT_BASE_URL must be configured"
        )

    return ChatOpenAI(
        model=model,
        temperature=temperature,
        max_retries=max_retries,
        streaming=streaming,
        openai_api_key=api_key,
        openai_api_base=base_url,
    )
