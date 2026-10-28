"""Build providers from settings and pick one for a task."""
from __future__ import annotations

from ..config import PROVIDERS, api_key_for, load_settings
from .base import Provider


class ProviderError(Exception):
    pass


def get_provider(name: str, settings: dict | None = None, model: str | None = None) -> Provider:
    s = settings or load_settings()
    if name not in PROVIDERS:
        raise ProviderError(f"알 수 없는 프로바이더: {name}")
    cfg = s["providers"][name]
    model = model or cfg.get("model") or PROVIDERS[name]["model"]
    if name == "chatgpt":
        from .. import chatgpt_auth
        st = chatgpt_auth.status()
        if not st.get("logged_in"):
            raise ProviderError("ChatGPT 계정으로 로그인하세요 (설정 → ChatGPT 계정).")
        if not st.get("sharing"):
            raise ProviderError("ChatGPT 플랜 사용 권한이 없습니다. 설정에서 다시 로그인하고 권한에 동의하세요.")
        if not model:
            raise ProviderError("ChatGPT 모델을 설정에서 선택하세요.")
        from .chatgpt_provider import ChatGPTProvider
        return ChatGPTProvider(model)
    key = api_key_for(name, s)
    base_url = cfg.get("base_url") or PROVIDERS[name]["base_url"]
    if name != "custom" and not key:
        raise ProviderError(f"{PROVIDERS[name]['label']} API 키가 설정되지 않았습니다. 설정에서 키를 입력하세요.")
    if not model:
        raise ProviderError(f"{PROVIDERS[name]['label']} 모델명이 비어 있습니다.")

    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(key, model, base_url)
    if name == "gemini":
        from .gemini_provider import GeminiProvider
        return GeminiProvider(key, model)
    from .openai_provider import OpenAIProvider
    return OpenAIProvider(key, model, base_url, vision=PROVIDERS[name]["vision"], name=name)


def resolve_provider(requested: str | None = None, need_vision: bool = False, model: str | None = None) -> Provider:
    """Pick the provider: explicit request > vision provider (if images) > default."""
    s = load_settings()
    name = requested or s.get("default_provider") or "anthropic"
    if need_vision:
        if not PROVIDERS[name]["vision"]:
            name = s.get("vision_provider") or ""
            if not name or not PROVIDERS.get(name, {}).get("vision"):
                name = next((n for n in ("anthropic", "openai", "gemini") if api_key_for(n, s)), "")
                if not name:
                    from .. import chatgpt_auth
                    if chatgpt_auth.status().get("sharing"):
                        name = "chatgpt"
            if not name:
                raise ProviderError("그림 설명에는 비전 모델(Claude·GPT·Gemini)이 필요합니다. 설정에서 키를 입력하세요.")
            if name != (requested or s.get("default_provider")):
                model = None            # a model chosen for another provider does not apply here
    return get_provider(name, s, model=model or None)
