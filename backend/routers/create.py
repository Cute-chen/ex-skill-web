"""
POST /api/create  — SSE streaming creation pipeline
POST /api/create/jobs — create background processing job
GET /api/create/jobs/{job_id} — query progress/result
POST /api/create/confirm — Write files after user preview confirmation
POST /api/exes/{slug}/update — Append new materials (SSE)
"""
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from ..config import EXES_DIR, get_ex_dir
from ..llm_client import get_client
from ..services import create_jobs
from ..services.pipeline import run_creation_pipeline, write_ex_files

router = APIRouter(tags=["create"])


class CreateBody(BaseModel):
    name: str
    basic_info: str = ""
    personality: str = ""
    materials: list[str] = []  # list of pre-parsed text blobs
    materials_labels: list[str] = []
    analysis_mode: str = "direct"  # direct | fast | fidelity


class ConfirmBody(BaseModel):
    slug: str
    name: Optional[str] = None
    intake: Optional[dict] = None
    memories_content: Optional[str] = None
    persona_content: Optional[str] = None
    materials_labels: list[str] = []


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(name: str) -> str:
    text = (name or "").strip() or "ta"
    try:
        from pypinyin import lazy_pinyin
        parts = lazy_pinyin(text)
        slug = "-".join(p for p in parts if p)
    except Exception:
        slug = text
    slug = re.sub(r"[^a-zA-Z0-9\-_\u4e00-\u9fff]+", "-", slug).strip("-")
    return slug or "ta"


def _ensure_unique_slug(base_slug: str) -> str:
    slug = base_slug
    idx = 2
    while (EXES_DIR / slug).exists():
        slug = f"{base_slug}-{idx}"
        idx += 1
    return slug


def _meta_path(slug: str) -> Path:
    return get_ex_dir(slug) / "meta.json"


def _read_meta(slug: str) -> dict:
    path = _meta_path(slug)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _write_meta(slug: str, meta: dict):
    path = _meta_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _init_processing_ex(slug: str, body: CreateBody, job_id: str):
    now = _utc_now()
    meta = {
        "name": body.name,
        "slug": slug,
        "created_at": now,
        "updated_at": now,
        "version": "v0",
        "profile": {
            "duration": "",
            "how_met": "",
            "time_since_breakup": "",
            "occupation": "",
            "gender": "女",
            "mbti": "",
            "raw": body.basic_info,
        },
        "tags": {
            "personality": [],
            "attachment": "",
            "mbti": "",
            "raw": body.personality,
        },
        "impression": body.personality or "",
        "knowledge_sources": body.materials_labels or [],
        "corrections_count": 0,
        "build_status": "processing",
        "build_progress": 1,
        "build_stage": "任务已创建",
        "build_error": "",
        "job_id": job_id,
        "analysis_mode": (body.analysis_mode or "direct").strip().lower(),
    }
    _write_meta(slug, meta)


def _update_build_meta(
    slug: str,
    *,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    stage: Optional[str] = None,
    error: Optional[str] = None,
):
    meta = _read_meta(slug)
    if not meta:
        return
    if status is not None:
        meta["build_status"] = status
    if progress is not None:
        meta["build_progress"] = max(0, min(100, int(progress)))
    if stage is not None:
        meta["build_stage"] = stage
    if error is not None:
        meta["build_error"] = error
    meta["updated_at"] = _utc_now()
    _write_meta(slug, meta)


def _preview_path(slug: str) -> Path:
    return get_ex_dir(slug) / "preview_result.json"


@router.post("/api/create")
async def create_ex_stream(body: CreateBody):
    client = get_client()
    analysis_mode = (body.analysis_mode or "direct").strip().lower()
    if analysis_mode not in {"direct", "fast", "fidelity"}:
        analysis_mode = "direct"
    intake = {
        "name": body.name,
        "basic_info": body.basic_info,
        "personality": body.personality,
    }

    async def generate():
        async for event in run_creation_pipeline(
            intake=intake,
            materials=body.materials,
            client=client,
            base_dir=EXES_DIR,
            analysis_mode=analysis_mode,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'stage': 'done', 'progress': 100})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


async def _run_create_job(job_id: str, slug: str, body: CreateBody):
    client = get_client()
    intake = {
        "name": body.name,
        "basic_info": body.basic_info,
        "personality": body.personality,
    }
    labels = body.materials_labels or []
    analysis_mode = (body.analysis_mode or "direct").strip().lower()
    if analysis_mode not in {"direct", "fast", "fidelity"}:
        analysis_mode = "direct"

    await create_jobs.update_job(
        job_id,
        status="running",
        stage="后台任务启动中...",
        progress=1,
        error="",
    )
    _update_build_meta(
        slug,
        status="processing",
        stage="后台任务启动中...",
        progress=1,
        error="",
    )

    try:
        got_preview = False
        async for event in run_creation_pipeline(
            intake=intake,
            materials=body.materials,
            client=client,
            base_dir=EXES_DIR,
            analysis_mode=analysis_mode,
        ):
            if event.get("error"):
                await create_jobs.update_job(
                    job_id,
                    status="failed",
                    stage="任务失败",
                    error=event["error"],
                    progress=100,
                )
                _update_build_meta(
                    slug,
                    status="failed",
                    stage="任务失败",
                    progress=100,
                    error=event["error"],
                )
                return

            stage = event.get("stage", "")
            progress = event.get("progress", 0)
            if stage == "preview":
                data = event.get("data", {}) or {}
                data["slug"] = slug
                data["name"] = body.name
                data["materials_labels"] = labels
                data["analysis_mode"] = analysis_mode
                _preview_path(slug).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                await create_jobs.update_job(
                    job_id,
                    status="preview_ready",
                    stage="预览已生成，等待确认",
                    progress=96,
                    data=data,
                    error="",
                )
                _update_build_meta(
                    slug,
                    status="preview_ready",
                    stage="预览已生成，等待确认",
                    progress=96,
                    error="",
                )
                got_preview = True
                continue

            await create_jobs.update_job(
                job_id,
                stage=stage,
                progress=progress,
                status="running",
                error="",
            )
            _update_build_meta(
                slug,
                status="processing",
                stage=stage,
                progress=progress,
                error="",
            )

        if not got_preview:
            await create_jobs.update_job(
                job_id,
                status="failed",
                stage="任务失败",
                error="任务未生成预览结果",
                progress=100,
            )
            _update_build_meta(
                slug,
                status="failed",
                stage="任务失败",
                progress=100,
                error="任务未生成预览结果",
            )
    except asyncio.CancelledError:
        await create_jobs.update_job(
            job_id,
            status="cancelled",
            stage="任务已取消",
            progress=100,
            error="用户取消了任务",
        )
        _update_build_meta(
            slug,
            status="cancelled",
            stage="任务已取消",
            progress=100,
            error="用户取消了任务",
        )
        raise
    except Exception as e:
        await create_jobs.update_job(
            job_id,
            status="failed",
            stage="任务异常",
            error=str(e),
            progress=100,
        )
        _update_build_meta(
            slug,
            status="failed",
            stage="任务异常",
            progress=100,
            error=str(e),
        )
    finally:
        await create_jobs.finish_task(job_id)


@router.post("/api/create/jobs")
async def create_job(body: CreateBody):
    analysis_mode = (body.analysis_mode or "direct").strip().lower()
    if analysis_mode not in {"direct", "fast", "fidelity"}:
        analysis_mode = "direct"
    body.analysis_mode = analysis_mode

    slug = _ensure_unique_slug(_slugify(body.name))
    non_empty_materials = [m for m in body.materials if (m or "").strip()]
    total_chars = sum(len(m) for m in non_empty_materials)
    meta = {
        "name": body.name,
        "slug": slug,
        "materials_count": len(non_empty_materials),
        "total_chars": total_chars,
        "analysis_mode": analysis_mode,
    }
    job = await create_jobs.create_job(meta=meta)
    _init_processing_ex(slug, body, job["id"])
    task = asyncio.create_task(_run_create_job(job["id"], slug, body))
    await create_jobs.attach_task(job["id"], task)
    return {"job_id": job["id"], "slug": slug}


@router.get("/api/create/jobs")
async def list_create_jobs():
    jobs = await create_jobs.list_jobs()
    return jobs


@router.get("/api/create/jobs/{job_id}")
async def get_create_job(job_id: str):
    job = await create_jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@router.delete("/api/create/jobs/{job_id}")
async def cancel_create_job(job_id: str):
    job = await create_jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    cancelled = await create_jobs.cancel_task(job_id)
    slug = (job.get("meta") or {}).get("slug")
    if cancelled:
        await create_jobs.update_job(
            job_id,
            status="cancelled",
            stage="任务已取消",
            progress=100,
            error="用户取消了任务",
        )
        if slug:
            _update_build_meta(
                slug,
                status="cancelled",
                stage="任务已取消",
                progress=100,
                error="用户取消了任务",
            )
    return {"ok": True, "cancelled": cancelled}


@router.post("/api/create/confirm")
async def confirm_creation(body: ConfirmBody):
    preview_data = {}
    if not (body.memories_content and body.persona_content and body.intake and body.name):
        preview_path = _preview_path(body.slug)
        if preview_path.exists():
            try:
                preview_data = json.loads(preview_path.read_text(encoding="utf-8"))
            except Exception:
                preview_data = {}

    name = body.name or preview_data.get("name")
    intake = body.intake or preview_data.get("intake")
    memories_content = body.memories_content or preview_data.get("memories_content")
    persona_content = body.persona_content or preview_data.get("persona_content")
    materials_labels = body.materials_labels or preview_data.get("materials_labels") or []

    if not (name and intake and memories_content and persona_content):
        raise HTTPException(status_code=400, detail="缺少确认创建所需数据，请重新生成预览")

    previous_meta = _read_meta(body.slug)
    ex_dir = await write_ex_files(
        slug=body.slug,
        name=name,
        intake=intake,
        memories_content=memories_content,
        persona_content=persona_content,
        base_dir=EXES_DIR,
        knowledge_sources=materials_labels,
    )

    meta_path = ex_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    if previous_meta.get("created_at"):
        meta["created_at"] = previous_meta["created_at"]
    if previous_meta.get("job_id"):
        meta["job_id"] = previous_meta["job_id"]
    analysis_mode = previous_meta.get("analysis_mode") or preview_data.get("analysis_mode")
    if analysis_mode:
        meta["analysis_mode"] = analysis_mode
    meta["build_status"] = "ready"
    meta["build_progress"] = 100
    meta["build_stage"] = "创建完成"
    meta["build_error"] = ""
    meta["updated_at"] = _utc_now()
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    preview_path = _preview_path(body.slug)
    if preview_path.exists():
        preview_path.unlink()

    return {"ok": True, "slug": body.slug, "path": str(ex_dir)}


class UpdateBody(BaseModel):
    materials: list[str] = []


@router.post("/api/exes/{slug}/update")
async def update_ex_stream(slug: str, body: UpdateBody):
    from ..config import get_ex_dir, load_prompt
    import datetime

    ex_dir = get_ex_dir(slug)
    client = get_client()

    async def generate():
        yield f"data: {json.dumps({'stage': '读取现有数据...', 'progress': 5})}\n\n"

        existing_memories = (ex_dir / "memories.md").read_text(encoding="utf-8") if (ex_dir / "memories.md").exists() else ""
        existing_persona = (ex_dir / "persona.md").read_text(encoding="utf-8") if (ex_dir / "persona.md").exists() else ""

        yield f"data: {json.dumps({'stage': '分析增量内容...', 'progress': 20})}\n\n"

        combined_new = "\n\n---\n\n".join(m for m in body.materials if m.strip())
        merger_prompt = load_prompt("merger.md")
        merge_input = f"现有 memories.md:\n{existing_memories}\n\n现有 persona.md:\n{existing_persona}\n\n新增内容:\n{combined_new}"

        try:
            merge_result = await client.complete(
                system=merger_prompt,
                messages=[{"role": "user", "content": merge_input}],
            )
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return

        yield f"data: {json.dumps({'stage': '更新文件...', 'progress': 80})}\n\n"

        # Backup current version first
        import subprocess, sys
        from pathlib import Path
        tools_dir = Path(__file__).parent.parent / "tools"
        subprocess.run(
            [sys.executable, str(tools_dir / "version_manager.py"),
             "--action", "backup", "--slug", slug, "--base-dir", str(EXES_DIR)],
            capture_output=True
        )

        # Append merge result to memories.md
        memories_path = ex_dir / "memories.md"
        memories_path.write_text(existing_memories + f"\n\n## 增量更新 ({datetime.date.today()})\n\n{merge_result}", encoding="utf-8")

        # Rebuild SKILL.md
        from ..routers.exes import _rebuild_skill
        _rebuild_skill(slug)

        # Update meta version
        import json
        meta_path = ex_dir / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            ver = meta.get("version", "v1")
            try:
                num = int(ver.lstrip("v")) + 1
                meta["version"] = f"v{num}"
            except Exception:
                meta["version"] = "v2"
            meta["updated_at"] = datetime.datetime.utcnow().isoformat() + "Z"
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        yield f"data: {json.dumps({'stage': 'done', 'progress': 100})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
