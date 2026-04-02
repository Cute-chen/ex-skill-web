import json
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from ..config import get_ex_dir
from ..llm_client import get_client

router = APIRouter(prefix="/api/exes", tags=["chat"])

HISTORY_LIMIT = 30  # 最多加载最近 30 条作为 context


def _load_history(slug: str) -> list:
    path = get_ex_dir(slug) / "chat_history.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_history(slug: str, history: list):
    path = get_ex_dir(slug) / "chat_history.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


class ChatBody(BaseModel):
    message: str


@router.get("/{slug}/history")
def get_history(slug: str):
    history = _load_history(slug)
    return history


@router.delete("/{slug}/history")
def clear_history(slug: str):
    path = get_ex_dir(slug) / "chat_history.json"
    if path.exists():
        path.unlink()
    return {"ok": True}


@router.post("/{slug}/chat")
async def chat(slug: str, body: ChatBody):
    ex_dir = get_ex_dir(slug)
    skill_path = ex_dir / "SKILL.md"
    if not skill_path.exists():
        raise HTTPException(status_code=404, detail="Skill 文件不存在，请先创建")

    system_prompt = skill_path.read_text(encoding="utf-8")

    history = _load_history(slug)
    # Build messages for API (last HISTORY_LIMIT entries)
    context = history[-HISTORY_LIMIT:] if len(history) > HISTORY_LIMIT else history
    api_messages = [
        {"role": h["role"], "content": h["content"]} for h in context
    ]
    api_messages.append({"role": "user", "content": body.message})

    client = get_client()

    async def generate():
        full_response = ""
        from datetime import datetime
        try:
            async for token in client.stream(system=system_prompt, messages=api_messages):
                full_response += token
                yield f"data: {json.dumps({'token': token})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return

        # Persist to history
        from datetime import datetime
        ts = datetime.utcnow().isoformat() + "Z"
        history.append({"role": "user", "content": body.message, "ts": ts})
        history.append({"role": "assistant", "content": full_response, "ts": ts})
        _save_history(slug, history)
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
