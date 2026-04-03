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
_MIN_RETRY_CHUNK_CHAR_SIZE = 1_800
_MAX_AUTO_SPLIT_DEPTH = 2
_MIN_ALLOWED_FAILED_CHUNKS = 2
_MAX_ALLOWED_FAILED_CHUNKS = 12
_LARGE_TEXT_THRESHOLD = 600_000
_XL_TEXT_THRESHOLD = 1_200_000
_DIRECT_TOTAL_CHAR_BUDGET = 180_000
_DIRECT_MAX_PER_MATERIAL_CHAR_BUDGET = 60_000
_DIRECT_MIN_PER_MATERIAL_CHAR_BUDGET = 14_000


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


def _format_error(err: Exception) -> str:
    if isinstance(err, httpx.HTTPStatusError):
        status = err.response.status_code if err.response is not None else "unknown"
        text = ""
        try:
            body = (err.response.text or "").strip() if err.response is not None else ""
            if body:
                text = f" - {body[:120]}"
        except Exception:
            text = ""
        return f"HTTPStatusError({status}){text}"

    msg = str(err).strip()
    if msg:
        return f"{type(err).__name__}: {msg}"
    return type(err).__name__


def _allowed_failed_chunks(total_chunks: int) -> int:
    if total_chunks <= 0:
        return 0
    # 允许极少量分块失败，避免大任务在随机抖动下整体失败
    rough = max(_MIN_ALLOWED_FAILED_CHUNKS, total_chunks // 40)
    return min(_MAX_ALLOWED_FAILED_CHUNKS, rough)


def _split_for_retry(text: str) -> list[str]:
    clean = (text or "").strip()
    if not clean or len(clean) < _MIN_RETRY_CHUNK_CHAR_SIZE * 2:
        return []
    retry_size = max(_MIN_RETRY_CHUNK_CHAR_SIZE, len(clean) // 2)
    retry_overlap = min(max(80, retry_size // 10), retry_size - 1)
    return _split_text_chunks(clean, size=retry_size, overlap=retry_overlap)


def _select_chunking_params(mode: str, total_chars: int) -> tuple[int, int]:
    if mode == "fast":
        if total_chars >= _XL_TEXT_THRESHOLD:
            return 20_000, 500
        if total_chars >= _LARGE_TEXT_THRESHOLD:
            return 15_000, 400
        return _FAST_CHUNK_CHAR_SIZE, _FAST_CHUNK_OVERLAP

    if total_chars >= _XL_TEXT_THRESHOLD:
        return 12_000, 600
    if total_chars >= _LARGE_TEXT_THRESHOLD:
        return 9_000, 500
    return _CHUNK_CHAR_SIZE, _CHUNK_OVERLAP


def _select_merge_group(mode: str, total_chunks: int) -> int:
    if mode == "fast":
        if total_chunks >= 180:
            return 6
        return 4

    if total_chunks >= 120:
        return 4
    return 2


def _compress_text_for_direct(text: str, max_chars: int) -> str:
    clean = (text or "").strip()
    if not clean or max_chars <= 0:
        return ""
    if len(clean) <= max_chars:
        return clean

    # 保留头尾 + 中段抽样，尽量覆盖不同时间段的内容
    head = min(24_000, max_chars // 3)
    tail = min(24_000, max_chars // 3)
    middle_budget = max_chars - head - tail
    if middle_budget <= 0:
        return clean[:max_chars]

    core_start = head
    core_end = max(core_start, len(clean) - tail)
    core_len = core_end - core_start
    if core_len <= 0:
        return (clean[:head] + "\n\n...\n\n" + clean[-tail:])[:max_chars]

    samples = max(1, min(6, middle_budget // 6_000))
    window = max(2_000, middle_budget // samples)
    mids: list[str] = []
    step = core_len / (samples + 1)
    for i in range(samples):
        center = core_start + int((i + 1) * step)
        s = max(core_start, center - window // 2)
        e = min(core_end, s + window)
        if e > s:
            mids.append(clean[s:e])

    marker = "\n\n...[中段抽样]...\n\n"
    merged = clean[:head]
    if mids:
        merged += marker + marker.join(mids)
    merged += marker + clean[-tail:]
    return merged[:max_chars]


def _build_direct_input(base_input: str, materials: list[str]) -> tuple[str, dict]:
    non_empty = [(m or "").strip() for m in materials if (m or "").strip()]
    if not non_empty:
        return base_input, {
            "raw_chars": 0,
            "used_chars": len(base_input),
            "truncated_materials": 0,
            "material_count": 0,
            "per_material_budget": 0,
        }

    per_budget = max(
        _DIRECT_MIN_PER_MATERIAL_CHAR_BUDGET,
        min(
            _DIRECT_MAX_PER_MATERIAL_CHAR_BUDGET,
            _DIRECT_TOTAL_CHAR_BUDGET // max(1, len(non_empty)),
        ),
    )
    blocks: list[str] = []
    raw_chars = 0
    used_chars = 0
    truncated_materials = 0

    for idx, text in enumerate(non_empty, start=1):
        raw = len(text)
        raw_chars += raw
        compact = _compress_text_for_direct(text, per_budget)
        used_chars += len(compact)
        if len(compact) < raw:
            truncated_materials += 1
        blocks.append(
            f"原材料{idx}（原始 {raw} 字，送审 {len(compact)} 字）：\n{compact}"
        )

    body = (
        f"{base_input}\n\n"
        "以下是原材料汇总（已自动压缩采样以提升速度）：\n\n"
        + "\n\n----\n\n".join(blocks)
    )
    final_input = _compress_text_for_direct(body, _DIRECT_TOTAL_CHAR_BUDGET)
    return final_input, {
        "raw_chars": raw_chars,
        "used_chars": len(final_input),
        "truncated_materials": truncated_materials,
        "material_count": len(non_empty),
        "per_material_budget": per_budget,
    }


async def _analyze_chunk_once(
    client,
    *,
    mode: str,
    chunk_input: str,
    memories_analyzer: str,
    persona_analyzer: str,
    dual_fast_prompt: str,
    fallback_depth: int = 0,
) -> tuple[list[str], list[str]]:
    if mode in {"fast", "direct"}:
        combined_piece = await _complete_with_retry(
            client,
            system=dual_fast_prompt,
            messages=[{"role": "user", "content": chunk_input}],
            max_tokens=3200,
        )
        memories_piece, persona_piece = _parse_fast_dual_result(combined_piece)
        return (
            [memories_piece] if memories_piece else [],
            [persona_piece] if persona_piece else [],
        )

    # 回退重试时改为串行，减少并发下的上游抖动
    if fallback_depth > 0:
        memories_piece = await _complete_with_retry(
            client,
            system=memories_analyzer,
            messages=[{"role": "user", "content": chunk_input}],
            max_tokens=4096,
        )
        persona_piece = await _complete_with_retry(
            client,
            system=persona_analyzer,
            messages=[{"role": "user", "content": chunk_input}],
            max_tokens=4096,
        )
    else:
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

    return [memories_piece], [persona_piece]


async def _analyze_chunk_with_auto_split(
    client,
    *,
    mode: str,
    base_input: str,
    chunk: dict,
    idx: int,
    total_chunks: int,
    memories_analyzer: str,
    persona_analyzer: str,
    dual_fast_prompt: str,
) -> dict:
    pending: list[tuple[str, int, int, int]] = [(chunk["text"], 0, 1, 1)]
    memories_parts: list[str] = []
    persona_parts: list[str] = []
    split_rounds = 0

    while pending:
        text, depth, part_idx, part_total = pending.pop(0)
        split_note = ""
        if depth > 0:
            split_note = f"（自动细分 {part_idx}/{part_total}，层级 {depth}）"
        header = (
            f"原材料分块信息：材料 {chunk['material_idx']}，"
            f"分块 {chunk['chunk_idx']}/{chunk['chunk_total']}，"
            f"全局 {idx}/{total_chunks}"
            f"{split_note}"
        )
        chunk_input = f"{base_input}\n\n{header}\n\n原材料内容：\n{text}"

        try:
            mem_list, per_list = await _analyze_chunk_once(
                client,
                mode=mode,
                chunk_input=chunk_input,
                memories_analyzer=memories_analyzer,
                persona_analyzer=persona_analyzer,
                dual_fast_prompt=dual_fast_prompt,
                fallback_depth=depth,
            )
            memories_parts.extend(mem_list)
            persona_parts.extend(per_list)
        except Exception as err:
            sub_chunks = _split_for_retry(text)
            if depth >= _MAX_AUTO_SPLIT_DEPTH or len(sub_chunks) <= 1:
                return {
                    "ok": False,
                    "error": err,
                    "split_rounds": split_rounds,
                }
            split_rounds += 1
            next_batch = [(sub, depth + 1, i + 1, len(sub_chunks)) for i, sub in enumerate(sub_chunks)]
            pending = next_batch + pending

    return {
        "ok": True,
        "memories": memories_parts,
        "personas": persona_parts,
        "split_rounds": split_rounds,
    }


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
    analysis_mode: str = "direct",
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
    mode = (analysis_mode or "direct").strip().lower()
    if mode not in {"fidelity", "fast", "direct"}:
        mode = "direct"

    base_input = f"昵称：{name}\n基本信息：{basic_info}\n性格画像：{personality}"
    memories_analyzer = load_prompt("memories_analyzer.md")
    persona_analyzer = load_prompt("persona_analyzer.md")
    non_empty_materials = [(m or "").strip() for m in materials if (m or "").strip()]
    total_chars = sum(len(m) for m in non_empty_materials)
    chunk_size = 0
    chunk_overlap = 0
    material_chunks: list[dict] = []
    if mode != "direct":
        chunk_size, chunk_overlap = _select_chunking_params(mode, total_chars)
        material_chunks = _build_material_chunks(
            materials,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    chunk_memories: list[str] = []
    chunk_personas: list[str] = []
    failed_chunks: list[str] = []
    auto_split_rounds = 0
    max_failed_chunks = 0
    direct_stats = {
        "raw_chars": total_chars,
        "used_chars": 0,
        "truncated_materials": 0,
        "material_count": len(non_empty_materials),
        "per_material_budget": 0,
    }

    if not non_empty_materials:
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
            yield {"error": f"分析记忆失败：{_format_error(e)}"}
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
            yield {"error": f"分析性格失败：{_format_error(e)}"}
            return
    elif mode == "direct":
        dual_fast_prompt = _fast_dual_prompt()
        direct_input, direct_stats = _build_direct_input(base_input, non_empty_materials)
        yield {
            "stage": (
                f"Claude 同款直连模式：原始 {direct_stats['raw_chars']} 字，"
                f"送审 {direct_stats['used_chars']} 字"
            ),
            "progress": 8,
        }
        try:
            combined_piece = await _complete_with_retry(
                client,
                system=dual_fast_prompt,
                messages=[{"role": "user", "content": direct_input}],
                max_tokens=3800,
            )
            memories_piece, persona_piece = _parse_fast_dual_result(combined_piece)
            if not memories_piece or not persona_piece:
                raise ValueError("双通道输出不完整")
            chunk_memories.append(memories_piece)
            chunk_personas.append(persona_piece)
        except Exception as e:
            # 回退补偿：若单次双通道失败，退回双分析器并行
            yield {"stage": "直连主通道抖动，切换补偿分析...", "progress": 20}
            try:
                memories_piece, persona_piece = await asyncio.gather(
                    _complete_with_retry(
                        client,
                        system=memories_analyzer,
                        messages=[{"role": "user", "content": direct_input}],
                        max_tokens=4096,
                    ),
                    _complete_with_retry(
                        client,
                        system=persona_analyzer,
                        messages=[{"role": "user", "content": direct_input}],
                        max_tokens=4096,
                    ),
                )
                chunk_memories.append(memories_piece)
                chunk_personas.append(persona_piece)
                failed_chunks.append(f"直连主通道失败已补偿：{_format_error(e)}")
            except Exception as final_err:
                yield {"error": f"直连分析失败：{_format_error(final_err)}"}
                return
    else:
        total_chunks = len(material_chunks)
        dual_fast_prompt = _fast_dual_prompt() if mode == "fast" else ""
        yield {
            "stage": (
                f"已加载 {total_chars} 字，分块 {total_chunks} 块 "
                f"(size={chunk_size}, overlap={chunk_overlap})"
            ),
            "progress": 6,
        }
        max_failed_chunks = _allowed_failed_chunks(total_chunks)
        for idx, chunk in enumerate(material_chunks, start=1):
            progress = 8 + int((idx - 1) / max(total_chunks, 1) * 42)
            stage_prefix = "极速分块提炼中" if mode == "fast" else "分块提炼中"
            stage = f"{stage_prefix} ({idx}/{total_chunks})"
            yield {"stage": stage, "progress": progress}

            result = await _analyze_chunk_with_auto_split(
                client,
                mode=mode,
                base_input=base_input,
                chunk=chunk,
                idx=idx,
                total_chunks=total_chunks,
                memories_analyzer=memories_analyzer,
                persona_analyzer=persona_analyzer,
                dual_fast_prompt=dual_fast_prompt,
            )
            auto_split_rounds += result.get("split_rounds", 0)

            if result.get("ok"):
                chunk_memories.extend(result.get("memories", []))
                chunk_personas.extend(result.get("personas", []))
                continue

            err = result.get("error")
            detail = _format_error(err if isinstance(err, Exception) else Exception("未知错误"))
            failed_chunks.append(f"分块 {idx}/{total_chunks}：{detail}")
            if len(failed_chunks) > max_failed_chunks:
                prefix = "极速分块分析失败过多" if mode == "fast" else "分块分析失败过多"
                yield {
                    "error": (
                        f"{prefix}（失败 {len(failed_chunks)} 块，允许 {max_failed_chunks} 块）："
                        f"{failed_chunks[-1]}"
                    )
                }
                return

            yield {
                "stage": (
                    f"{stage_prefix} ({idx}/{total_chunks}) "
                    f"该块失败已跳过（{len(failed_chunks)}/{max_failed_chunks}）"
                ),
                "progress": progress,
            }

    if not chunk_memories or not chunk_personas:
        seed = failed_chunks[0] if failed_chunks else "无可用分块结果"
        yield {"error": f"分析结果不足：{seed}"}
        return

    try:
        yield {"stage": "合并分析结果...", "progress": 60}
        merge_group = _select_merge_group(mode, len(chunk_memories))
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
        yield {"error": f"合并分析失败：{_format_error(e)}"}
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
        yield {"error": f"生成文档失败：{_format_error(e)}"}
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
            "analysis_warnings": {
                "mode": mode,
                "failed_chunks": len(failed_chunks),
                "failed_chunks_limit": max_failed_chunks,
                "auto_split_rounds": auto_split_rounds,
                "total_chars": total_chars,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "chunk_count": len(material_chunks),
                "direct_stats": direct_stats,
                "sample_errors": failed_chunks[:3],
            },
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
