from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..config import load_settings, save_settings
from ..llm_client import create_client
import httpx

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsIn(BaseModel):
    provider: str = "claude"
    base_url: str
    api_key: str
    model: str


def _extract_connect_error(err: Exception) -> str:
    if isinstance(err, httpx.HTTPStatusError):
        status = err.response.status_code
        try:
            data = err.response.json()
            if isinstance(data, dict):
                if isinstance(data.get("detail"), str):
                    return f"HTTP {status}: {data['detail']}"
                error = data.get("error")
                if isinstance(error, dict):
                    msg = error.get("message")
                    if isinstance(msg, str) and msg.strip():
                        return f"HTTP {status}: {msg}"
                if isinstance(error, str) and error.strip():
                    return f"HTTP {status}: {error}"
        except Exception:
            pass
        text = (err.response.text or "").strip().replace("\n", " ")
        if text:
            return f"HTTP {status}: {text[:240]}"
        return f"HTTP {status}"
    return str(err) or err.__class__.__name__


@router.get("")
def get_settings():
    cfg = load_settings()
    key = cfg.get("api_key", "")
    masked = key[:8] + "..." + key[-4:] if len(key) > 12 else ("*" * len(key) if key else "")
    return {
        "provider": cfg.get("provider", "claude"),
        "base_url": cfg.get("base_url", ""),
        "api_key_masked": masked,
        "api_key": key,  # return full key for form pre-fill (local only)
        "model": cfg.get("model", ""),
    }


@router.post("")
def update_settings(body: SettingsIn):
    provider = (body.provider or "claude").strip().lower()
    if provider not in {"claude", "openai"}:
        raise HTTPException(status_code=400, detail="provider 仅支持 claude 或 openai")
    save_settings({
        "provider": provider,
        "base_url": body.base_url,
        "api_key": body.api_key,
        "model": body.model,
    })
    return {"ok": True}


@router.post("/test")
async def test_connection(body: SettingsIn):
    provider = (body.provider or "claude").strip().lower()
    if provider not in {"claude", "openai"}:
        raise HTTPException(status_code=400, detail="provider 仅支持 claude 或 openai")

    client = create_client(
        provider=provider,
        base_url=body.base_url,
        api_key=body.api_key,
        model=body.model,
    )
    try:
        result = await client.complete(
            system="You are a helpful assistant.",
            messages=[{"role": "user", "content": "Reply with just: ok"}],
            max_tokens=10,
        )
    except Exception as e:
        detail = _extract_connect_error(e)
        raise HTTPException(status_code=400, detail=f"连接失败：{detail}")

    if not result:
        raise HTTPException(status_code=400, detail="连接失败：接口返回为空，请检查模型名或权限")
    return {"ok": True}
