"""Paths and user settings (providers, API keys, target language)."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # paper_reader/
DATA_DIR = Path(os.environ.get("PAPER_READER_DATA", ROOT / "data"))
PAPERS_DIR = DATA_DIR / "papers"
SETTINGS_FILE = DATA_DIR / "settings.json"
DB_FILE = DATA_DIR / "paper_reader.sqlite"
FRONTEND_DIST = ROOT / "frontend" / "dist"

PAPERS_DIR.mkdir(parents=True, exist_ok=True)

# Provider catalogue. "env" = environment variable fallback for the key.
PROVIDERS: dict[str, dict] = {
    "chatgpt": {
        "label": "ChatGPT 계정 (구독 사용)",
        "model": "",
        "models": [],
        "env": "",
        "vision": True,
        "base_url": "https://api.openai.com/v1",
        "oauth": True,
    },
    "anthropic": {
        "label": "Claude (Anthropic)",
        "model": "claude-opus-5-5",
        "models": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"],
        "env": "ANTHROPIC_API_KEY",
        "vision": True,
        "base_url": "",
    },
    "openai": {
        "label": "OpenAI (GPT)",
        "model": "gpt-5",
        "models": ["gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4o"],
        "env": "OPENAI_API_KEY",
        "vision": True,
        "base_url": "https://api.openai.com/v1",
    },
    "gemini": {
        "label": "Google Gemini",
        "model": "gemini-2.5-flash",
        "models": ["gemini-2.5-pro", "gemini-2.5-flash"],
        "env": "GEMINI_API_KEY",
        "vision": True,
        "base_url": "",
    },
    "deepseek": {
        "label": "DeepSeek",
        "model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "env": "DEEPSEEK_API_KEY",
        "vision": False,
        "base_url": "https://api.deepseek.com",
    },
    "custom": {
        "label": "OpenAI 호환 (Ollama, OpenRouter 등)",
        "model": "",
        "models": [],
        "env": "",
        "vision": False,
        "base_url": "http://localhost:11434/v1",
    },
}

LANG_NAMES = {
    "ko": "Korean (한국어)",
    "en": "English",
    "ja": "Japanese (日本語)",
    "zh": "Simplified Chinese (简体中文)",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
}

_lock = threading.Lock()


def _defaults() -> dict:
    return {
        "target_lang": "ko",
        "default_provider": "anthropic",
        "vision_provider": "",          # "" = same as default (or first vision-capable)
        "usage_budget_5h": 0,           # optional personal token budgets for the usage panel (0 = none)
        "usage_budget_7d": 0,
        "providers": {
            name: {"api_key": "", "model": p["model"], "base_url": p["base_url"]}
            for name, p in PROVIDERS.items()
        },
    }


def load_settings() -> dict:
    with _lock:
        s = _defaults()
        if SETTINGS_FILE.exists():
            try:
                saved = json.loads(SETTINGS_FILE.read_text("utf-8"))
            except Exception:
                saved = {}
            for k in ("target_lang", "default_provider", "vision_provider", "usage_budget_5h", "usage_budget_7d"):
                if k in saved:
                    s[k] = saved[k]
            for name, cfg in (saved.get("providers") or {}).items():
                if name in s["providers"]:
                    s["providers"][name].update({k: v for k, v in cfg.items() if v is not None})
        return s


def save_settings(s: dict) -> None:
    with _lock:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), "utf-8")


def api_key_for(name: str, settings: dict | None = None) -> str:
    s = settings or load_settings()
    key = (s["providers"].get(name) or {}).get("api_key") or ""
    if not key:
        env = PROVIDERS[name]["env"]
        key = os.environ.get(env, "") if env else ""
    return key


def public_settings() -> dict:
    """Settings with API keys masked (for the UI)."""
    s = load_settings()
    out = {
        "target_lang": s["target_lang"],
        "default_provider": s["default_provider"],
        "vision_provider": s["vision_provider"],
        "usage_budget_5h": int(s.get("usage_budget_5h") or 0),
        "usage_budget_7d": int(s.get("usage_budget_7d") or 0),
        "languages": LANG_NAMES,
        "providers": {},
    }
    for name, meta in PROVIDERS.items():
        cfg = s["providers"][name]
        if meta.get("oauth"):
            from .chatgpt_auth import status as chatgpt_status
            st = chatgpt_status()
            out["providers"][name] = {
                "label": meta["label"],
                "model": cfg.get("model") or "",
                "models": meta["models"],
                "base_url": meta["base_url"],
                "vision": meta["vision"],
                "oauth": True,
                "key_set": bool(st.get("logged_in") and st.get("sharing")),
                "key_hint": st.get("email", ""),
                "key_from_env": False,
                "auth": st,
            }
            continue
        key = api_key_for(name, s)
        out["providers"][name] = {
            "label": meta["label"],
            "model": cfg.get("model") or meta["model"],
            "models": meta["models"],
            "base_url": cfg.get("base_url", meta["base_url"]),
            "vision": meta["vision"],
            "oauth": False,
            "key_set": bool(key) or name == "custom",
            "key_hint": (key[:6] + "…" + key[-4:]) if len(key) > 12 else ("설정됨" if key else ""),
            "key_from_env": bool(key) and not cfg.get("api_key") and bool(meta["env"]),
        }
    return out
