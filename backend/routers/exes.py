import json
import shutil
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..config import EXES_DIR, get_ex_dir

router = APIRouter(prefix="/api/exes", tags=["exes"])


def _read_meta(slug: str) -> dict:
    meta_path = get_ex_dir(slug) / "meta.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail=f"找不到 {slug}")
    with open(meta_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_file(slug: str, filename: str) -> str:
    path = get_ex_dir(slug) / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _resolve_build_meta(ex_dir: Path, meta: dict) -> dict:
    status = meta.get("build_status")
    preview_exists = (ex_dir / "preview_result.json").exists()
    skill_exists = (ex_dir / "SKILL.md").exists()

    if status not in {"processing", "preview_ready", "ready", "failed", "cancelled"}:
        if skill_exists:
            status = "ready"
        elif preview_exists:
            status = "preview_ready"
        else:
            status = "processing"

    default_stage = {
        "processing": "处理中",
        "preview_ready": "待确认",
        "ready": "创建完成",
        "failed": "处理失败",
        "cancelled": "任务已取消",
    }.get(status, "处理中")

    if status == "ready":
        default_progress = 100
    elif status == "preview_ready":
        default_progress = 96
    else:
        default_progress = 0

    progress = meta.get("build_progress", default_progress)
    try:
        progress = max(0, min(100, int(progress)))
    except Exception:
        progress = default_progress

    meta["build_status"] = status
    meta["build_progress"] = progress
    meta["build_stage"] = meta.get("build_stage") or default_stage
    meta["build_error"] = meta.get("build_error", "")
    return meta


@router.get("")
def list_exes():
    if not EXES_DIR.exists():
        return []
    result = []
    for d in sorted(EXES_DIR.iterdir()):
        meta_path = d / "meta.json"
        if d.is_dir() and meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta = _resolve_build_meta(d, meta)
                result.append({
                    "slug": meta.get("slug", d.name),
                    "name": meta.get("name", d.name),
                    "version": meta.get("version", "v1"),
                    "created_at": meta.get("created_at", ""),
                    "updated_at": meta.get("updated_at", ""),
                    "profile": meta.get("profile", {}),
                    "tags": meta.get("tags", {}),
                    "impression": meta.get("impression", ""),
                    "corrections_count": meta.get("corrections_count", 0),
                    "analysis_mode": meta.get("analysis_mode", "direct"),
                    "build_status": meta.get("build_status", "ready"),
                    "build_progress": meta.get("build_progress", 100),
                    "build_stage": meta.get("build_stage", ""),
                    "build_error": meta.get("build_error", ""),
                })
            except Exception:
                pass
    return result


@router.get("/{slug}")
def get_ex(slug: str):
    ex_dir = get_ex_dir(slug)
    meta = _read_meta(slug)
    meta = _resolve_build_meta(ex_dir, meta)
    memories = _read_file(slug, "memories.md")
    persona = _read_file(slug, "persona.md")
    preview = None
    preview_path = ex_dir / "preview_result.json"
    if preview_path.exists():
        try:
            preview = json.loads(preview_path.read_text(encoding="utf-8"))
        except Exception:
            preview = None
    return {
        "meta": meta,
        "memories": memories,
        "persona": persona,
        "preview": preview,
    }


class CorrectBody(BaseModel):
    text: str  # 用户的纠正内容（自由文本）


@router.post("/{slug}/correct")
async def add_correction(slug: str, body: CorrectBody):
    from ..llm_client import get_client
    from ..config import load_prompt
    import re
    from datetime import datetime

    meta = _read_meta(slug)
    prompt = load_prompt("correction_handler.md")
    persona_content = _read_file(slug, "persona.md")
    memories_content = _read_file(slug, "memories.md")

    system = f"{prompt}\n\n---\n当前 persona.md:\n{persona_content}\n\n当前 memories.md:\n{memories_content}"
    messages = [{"role": "user", "content": body.text}]
    client = get_client()
    result = await client.complete(system=system, messages=messages)

    # Append correction to persona.md under ## Correction 记录
    ex_dir = get_ex_dir(slug)
    persona_path = ex_dir / "persona.md"
    ts = datetime.now().strftime("%Y-%m-%d")
    correction_line = f"\n- [{ts}] {result.strip()}"

    persona_text = persona_path.read_text(encoding="utf-8") if persona_path.exists() else ""
    if "## Correction 记录" in persona_text:
        persona_text = persona_text + correction_line
    else:
        persona_text = persona_text + f"\n\n## Correction 记录\n{correction_line}"
    persona_path.write_text(persona_text, encoding="utf-8")

    # Rebuild SKILL.md
    _rebuild_skill(slug)

    # Update meta
    meta["corrections_count"] = meta.get("corrections_count", 0) + 1
    meta["updated_at"] = datetime.utcnow().isoformat() + "Z"
    meta_path = ex_dir / "meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return {"ok": True, "correction": result.strip()}


@router.delete("/{slug}")
def delete_ex(slug: str):
    ex_dir = get_ex_dir(slug)
    if not ex_dir.exists():
        raise HTTPException(status_code=404, detail=f"找不到 {slug}")
    shutil.rmtree(ex_dir)
    return {"ok": True}


@router.get("/{slug}/versions")
def list_versions(slug: str):
    versions_dir = get_ex_dir(slug) / "versions"
    if not versions_dir.exists():
        return []
    result = []
    for v in sorted(versions_dir.iterdir(), reverse=True):
        if v.is_dir():
            meta_path = v / "meta.json"
            ts = ""
            if meta_path.exists():
                try:
                    m = json.loads(meta_path.read_text(encoding="utf-8"))
                    ts = m.get("updated_at", "")
                except Exception:
                    pass
            result.append({"version": v.name, "ts": ts})
    return result


@router.post("/{slug}/rollback/{version}")
def rollback_version(slug: str, version: str):
    import subprocess, sys
    from pathlib import Path
    tools_dir = Path(__file__).parent.parent / "tools"
    result = subprocess.run(
        [sys.executable, str(tools_dir / "version_manager.py"),
         "--action", "rollback", "--slug", slug, "--version", version,
         "--base-dir", str(EXES_DIR)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr)
    return {"ok": True}


def _rebuild_skill(slug: str):
    ex_dir = get_ex_dir(slug)
    meta_path = ex_dir / "meta.json"
    if not meta_path.exists():
        return
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    name = meta.get("name", slug)
    profile = meta.get("profile", {})
    duration = profile.get("duration", "")
    occupation = profile.get("occupation", "")
    identity_parts = [p for p in [duration, occupation] if p]
    identity = "，".join(identity_parts) if identity_parts else name

    memories = (ex_dir / "memories.md").read_text(encoding="utf-8") if (ex_dir / "memories.md").exists() else ""
    persona = (ex_dir / "persona.md").read_text(encoding="utf-8") if (ex_dir / "persona.md").exists() else ""

    skill_content = f"""---
name: ex_{slug}
description: {name}，{identity}
user-invocable: true
---

# {name}

{identity}

---

## PART A：共同记忆

{memories}

---

## PART B：人物性格

{persona}

---

## 运行规则

接收到任何消息时：

1. **先由 PART B 判断**：她会不会回这条消息？用什么心情和态度回？
2. **再由 PART A 提供记忆**：相关的共同记忆、日常细节、重要时刻
3. **输出时保持 PART B 的表达风格**：她说话的方式、用词习惯、emoji 偏好

**PART B 的 Layer 0 规则永远优先，任何情况下不得违背。**
"""
    (ex_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")
