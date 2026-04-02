import json
import os
from pathlib import Path

SETTINGS_FILE = Path(__file__).parent.parent / "settings.json"
EXES_DIR = Path(__file__).parent.parent / "exes"
PROMPTS_DIR = Path(__file__).parent / "prompts"

DEFAULT_SETTINGS = {
    "provider": "claude",
    "base_url": "https://api.anthropic.com",
    "api_key": "",
    "model": "claude-opus-4-6",
}


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg = {**DEFAULT_SETTINGS, **data}
                provider = str(cfg.get("provider", "claude")).strip().lower()
                if provider not in {"claude", "openai"}:
                    provider = "claude"
                cfg["provider"] = provider
                return cfg
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def get_ex_dir(slug: str) -> Path:
    return EXES_DIR / slug
