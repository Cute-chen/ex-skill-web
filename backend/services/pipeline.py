"""
Creation pipeline: Intake info + parsed materials → LLM analysis → memories.md + persona.md
Streams progress events via async generator.
"""
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import AsyncGenerator
import httpx

# Add tools dir to path for skill_writer / version_manager
TOOLS_DIR = Path(__file__).parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))


_CHUNK_CHAR_SIZE = 6_000
_CHUNK_OVERLAP = 500
_MAX_RETRIES = 3
_RETRYABLE_HTTP_STATUS = {408, 409, 429, 500, 502, 503, 504}
_FAST_CHUNK_CHAR_SIZE = 10_000
_FAST_CHUNK_OVERLAP = 300


def _split_text_chunks(text: str, size: int = _CHUNK_CHAR_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _build_material_chunks(
    materials: list[str],
    *,
    chunk_size: int = _CHUNK_CHAR_SIZE,
    chunk_overlap: int = _CHUNK_OVERLAP,
) -> list[dict]:
    chunks: list[dict] = []
    for material_idx, material in enumerate(materials, start=1):
        text = (material or "").strip()
        if not text:
            continue
        split = _split_text_chunks(text, size=chunk_size, overlap=chunk_overlap)
        for chunk_idx, chunk_text in enumerate(split, start=1):
            chunks.append({
                "material_idx": material_idx,
                "chunk_idx": chunk_idx,
                "chunk_total": len(split),
                "text": chunk_text,
            })
    return chunks


def _is_retryable_error(err: Exception) -> bool:
    if isinstance(err, httpx.TimeoutException):
        return True
    if isinstance(err, httpx.HTTPStatusError):
        return err.response.status_code in _RETRYABLE_HTTP_STATUS
    msg = str(err).lower()
    return (
        "timeout" in msg
        or "timed out" in msg
        or "gateway timeout" in msg
        or "server disconnected" in msg
    )


async def _complete_with_retry(
    client,
    *,
    system: str,
    messages: list,
    max_tokens: int = 8096,
) -> str:
    delay = 1.0
    last_error: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return await client.complete(
                system=system,
                messages=messages,
                max_tokens=max_tokens,
            )
        except Exception as e:
            last_error = e
            if attempt >= _MAX_RETRIES or not _is_retryable_error(e):
                raise
            await asyncio.sleep(delay)
            delay = min(delay * 2, 8.0)

    if last_error:
        raise last_error
    raise RuntimeError("LLM 调用失败")


def _merge_prompt(analysis_type: str) -> str:
    label = "共同记忆分析" if analysis_type == "memories" else "人物性格分析"
    return f"""你是信息合并器。请把两个来自同一人的{label}合并成一份更完整的分析。

要求：
1. 两份分析中的有效信息都要保留，不要遗漏。
2. 对重复内容去重。
3. 对相互矛盾的信息同时保留，并标记为“冲突候选”。
4. 输出中文，结构清晰，可直接给后续文档生成器使用。
    5. 只输出合并后的分析结果，不要解释过程。"""


def _fast_dual_prompt() -> str:
    return """你是“双通道分析器”，请同时提炼：
1) 共同记忆（events / 细节 / 关系阶段）
2) 人物性格（沟通风格 / 依恋模式 / 情绪触发点）

输出要求：
1. 只能输出 JSON 对象，不要 markdown，不要解释。
2. JSON 必须包含两个键：memories, persona。
3. 两个字段都输出中文字符串，可分点、可换行。
4. 信息不足时写“（信息不足）”，不要编造。"""


def _parse_fast_dual_result(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if not raw:
        return "", ""

    candidates = [raw]
    l = raw.find("{")
    r = raw.rfind("}")
    if l != -1 and r != -1 and r > l:
        candidates.append(raw[l:r + 1])

    for cand in candidates:
        try:
            data = json.loads(cand)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        memories = data.get("memories")
        persona = data.get("persona")
        m_text = memories if isinstance(memories, str) else ""
        p_text = persona if isinstance(persona, str) else ""
        if m_text or p_text:
            return m_text.strip(), p_text.strip()

    # Fallback: avoid dropping information if provider emits non-JSON
    return raw, raw


def _merge_group_text(parts: list[str]) -> str:
    blocks = []
    for idx, text in enumerate(parts, start=1):
        blocks.append(f"分析{idx}：\n{text}")
    return "\n\n".join(blocks)


async def _merge_analyses_in_rounds(
    client,
    analyses: list[str],
    analysis_type: str,
    *,
    group_size: int = 2,
    max_tokens: int = 4096,
) -> str:
    items = [x.strip() for x in analyses if (x or "").strip()]
    if not items:
        return "（原材料不足，建议追加聊天记录）"
    if len(items) == 1:
        return items[0]

    system = _merge_prompt(analysis_type)
    group_size = max(2, int(group_size))
    current = items
    while len(current) > 1:
        merged_round: list[str] = []
        for i in range(0, len(current), group_size):
            batch = current[i:i + group_size]
            if len(batch) == 1:
                merged_round.append(batch[0])
                continue
            merged = await _complete_with_retry(
                client,
                system=system,
                messages=[{
                    "role": "user",
                    "content": _merge_group_text(batch),
                }],
                max_tokens=max_tokens,
            )
            merged_round.append(merged)
        current = merged_round
    return current[0]


def _slugify(name: str) -> str:
    try:
        from pypinyin import lazy_pinyin
        parts = lazy_pinyin(name)
        slug = "-".join(p for p in parts if p)
        slug = "".join(c if c.isalnum() or c == "-" else "-" for c in slug)
        slug = slug.strip("-")
        return slug or name
    except ImportError:
        import re
        slug = re.sub(r"[^\w\u4e00-\u9fff]", "-", name).strip("-")
        return slug or name


async def run_creation_pipeline(
    intake: dict,
    materials: list[str],
    client,
    base_dir: Path,
    analysis_mode: str = "fidelity",
) -> AsyncGenerator[dict, None]:
    """
    intake: {name, basic_info, personality}
    materials: list of parsed text strings
    yields: {"stage": str, "progress": 0-100, "done": bool, "data": dict}
    """
    from ..config import load_prompt

    name = intake.get("name", "她")
    basic_info = intake.get("basic_info", "")
    personality = intake.get("personality", "")
    slug = _slugify(name)
    mode = (analysis_mode or "fidelity").strip().lower()
    if mode not in {"fidelity", "fast"}:
        mode = "fidelity"

    base_input = f"昵称：{name}\n基本信息：{basic_info}\n性格画像：{personality}"
    memories_analyzer = load_prompt("memories_analyzer.md")
    persona_analyzer = load_prompt("persona_analyzer.md")
    chunk_size = _FAST_CHUNK_CHAR_SIZE if mode == "fast" else _CHUNK_CHAR_SIZE
    chunk_overlap = _FAST_CHUNK_OVERLAP if mode == "fast" else _CHUNK_OVERLAP
    material_chunks = _build_material_chunks(
        materials,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    chunk_memories: list[str] = []
    chunk_personas: list[str] = []

    if not material_chunks:
        # 没有原材料时，仍允许仅根据 intake 生成
        try:
            yield {"stage": "分析共同记忆...", "progress": 12}
            chunk_memories.append(await _complete_with_retry(
                client,
                system=memories_analyzer,
                messages=[{"role": "user", "content": base_input}],
                max_tokens=4096,
            ))
        except Exception as e:
            yield {"error": f"分析记忆失败：{e}"}
            return

        try:
            yield {"stage": "分析人物性格...", "progress": 28}
            chunk_personas.append(await _complete_with_retry(
                client,
                system=persona_analyzer,
                messages=[{"role": "user", "content": base_input}],
                max_tokens=4096,
            ))
        except Exception as e:
            yield {"error": f"分析性格失败：{e}"}
            return
    else:
        total_chunks = len(material_chunks)
        dual_fast_prompt = _fast_dual_prompt() if mode == "fast" else ""
        for idx, chunk in enumerate(material_chunks, start=1):
            progress = 8 + int((idx - 1) / max(total_chunks, 1) * 42)
            stage_prefix = "极速分块提炼中" if mode == "fast" else "分块提炼中"
            stage = f"{stage_prefix} ({idx}/{total_chunks})"
            yield {"stage": stage, "progress": progress}

            header = (
                f"原材料分块信息：材料 {chunk['material_idx']}，"
                f"分块 {chunk['chunk_idx']}/{chunk['chunk_total']}，"
                f"全局 {idx}/{total_chunks}"
            )
            chunk_input = f"{base_input}\n\n{header}\n\n原材料内容：\n{chunk['text']}"

            if mode == "fast":
                try:
                    combined_piece = await _complete_with_retry(
                        client,
                        system=dual_fast_prompt,
                        messages=[{"role": "user", "content": chunk_input}],
                        max_tokens=3200,
                    )
                    memories_piece, persona_piece = _parse_fast_dual_result(combined_piece)
                    if memories_piece:
                        chunk_memories.append(memories_piece)
                    if persona_piece:
                        chunk_personas.append(persona_piece)
                except Exception as e:
                    yield {"error": f"极速分块分析失败（分块 {idx}/{total_chunks}）：{e}"}
                    return
            else:
                try:
                    memories_piece, persona_piece = await asyncio.gather(
                        _complete_with_retry(
                            client,
                            system=memories_analyzer,
                            messages=[{"role": "user", "content": chunk_input}],
                            max_tokens=4096,
                        ),
                        _complete_with_retry(
                            client,
                            system=persona_analyzer,
                            messages=[{"role": "user", "content": chunk_input}],
                            max_tokens=4096,
                        ),
                    )
                    chunk_memories.append(memories_piece)
                    chunk_personas.append(persona_piece)
                except Exception as e:
                    yield {"error": f"分块分析失败（分块 {idx}/{total_chunks}）：{e}"}
                    return

    try:
        yield {"stage": "合并分析结果...", "progress": 60}
        merge_group = 4 if mode == "fast" else 2
        merge_tokens = 2800 if mode == "fast" else 4096
        memories_raw, persona_raw = await asyncio.gather(
            _merge_analyses_in_rounds(
                client,
                chunk_memories,
                "memories",
                group_size=merge_group,
                max_tokens=merge_tokens,
            ),
            _merge_analyses_in_rounds(
                client,
                chunk_personas,
                "persona",
                group_size=merge_group,
                max_tokens=merge_tokens,
            ),
        )
    except Exception as e:
        yield {"error": f"合并分析失败：{e}"}
        return

    yield {"stage": "生成共同记忆文档...", "progress": 76}

    # Step 3: Build memories.md (only analysis results, no raw materials)
    memories_builder = load_prompt("memories_builder.md")
    yield {"stage": "生成 Persona 文档...", "progress": 86}

    # Step 4: Build persona.md
    persona_builder = load_prompt("persona_builder.md")
    try:
        memories_content, persona_content = await asyncio.gather(
            _complete_with_retry(
                client,
                system=memories_builder,
                messages=[{"role": "user", "content": f"基础信息：\n{base_input}\n\n分析结果：\n{memories_raw}"}],
                max_tokens=8096,
            ),
            _complete_with_retry(
                client,
                system=persona_builder,
                messages=[{"role": "user", "content": f"基础信息：\n{base_input}\n\n分析结果：\n{persona_raw}"}],
                max_tokens=8096,
            ),
        )
    except Exception as e:
        yield {"error": f"生成文档失败：{e}"}
        return

    yield {"stage": "生成预览...", "progress": 94}

    # Build preview summaries (first ~300 chars of each)
    memories_preview = memories_content[:500].strip()
    persona_preview = persona_content[:500].strip()

    yield {
        "stage": "preview",
        "progress": 96,
        "data": {
            "slug": slug,
            "name": name,
            "memories_preview": memories_preview,
            "persona_preview": persona_preview,
            "memories_content": memories_content,
            "persona_content": persona_content,
            "intake": intake,
        }
    }


async def write_ex_files(
    slug: str,
    name: str,
    intake: dict,
    memories_content: str,
    persona_content: str,
    base_dir: Path,
    knowledge_sources: list[str] = None,
) -> Path:
    ex_dir = base_dir / slug
    ex_dir.mkdir(parents=True, exist_ok=True)
    (ex_dir / "versions").mkdir(exist_ok=True)
    (ex_dir / "knowledge" / "chats").mkdir(parents=True, exist_ok=True)
    (ex_dir / "knowledge" / "photos").mkdir(parents=True, exist_ok=True)
    (ex_dir / "knowledge" / "social").mkdir(parents=True, exist_ok=True)

    # Write memories.md
    (ex_dir / "memories.md").write_text(memories_content, encoding="utf-8")

    # Write persona.md
    (ex_dir / "persona.md").write_text(persona_content, encoding="utf-8")

    # Write meta.json
    now = datetime.now(timezone.utc).isoformat()
    profile = _parse_profile(intake.get("basic_info", ""))
    tags = _parse_tags(intake.get("personality", ""))

    meta = {
        "name": name,
        "slug": slug,
        "created_at": now,
        "updated_at": now,
        "version": "v1",
        "profile": profile,
        "tags": tags,
        "impression": intake.get("personality", ""),
        "knowledge_sources": knowledge_sources or [],
        "corrections_count": 0,
    }
    with open(ex_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # Build and write SKILL.md
    profile_desc = profile.get("duration", "")
    occupation = profile.get("occupation", "")
    identity = "，".join(p for p in [profile_desc, occupation] if p) or name

    skill_content = f"""---
name: ex_{slug}
description: {name}，{identity}
user-invocable: true
---

# {name}

{identity}

---

## PART A：共同记忆

{memories_content}

---

## PART B：人物性格

{persona_content}

---

## 运行规则

接收到任何消息时：

1. **先由 PART B 判断**：她会不会回这条消息？用什么心情和态度回？
2. **再由 PART A 提供记忆**：相关的共同记忆、日常细节、重要时刻
3. **输出时保持 PART B 的表达风格**：她说话的方式、用词习惯、emoji 偏好

**PART B 的 Layer 0 规则永远优先，任何情况下不得违背。**
"""
    (ex_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")

    return ex_dir


def _parse_profile(basic_info: str) -> dict:
    """Best-effort extract duration/how_met from free text."""
    return {
        "duration": "",
        "how_met": "",
        "time_since_breakup": "",
        "occupation": "",
        "gender": "女",
        "mbti": "",
        "raw": basic_info,
    }


def _parse_tags(personality: str) -> dict:
    """Best-effort extract MBTI and attachment from free text."""
    import re
    mbti_match = re.search(r"\b(INTJ|INTP|ENTJ|ENTP|INFJ|INFP|ENFJ|ENFP|ISTJ|ISFJ|ESTJ|ESFJ|ISTP|ISFP|ESTP|ESFP)\b", personality, re.I)
    attachment_map = {"焦虑型": "焦虑型", "回避型": "回避型", "安全型": "安全型", "混乱型": "混乱型"}
    attachment = next((v for k, v in attachment_map.items() if k in personality), "")
    return {
        "personality": [],
        "attachment": attachment,
        "mbti": mbti_match.group(0).upper() if mbti_match else "",
        "raw": personality,
    }
