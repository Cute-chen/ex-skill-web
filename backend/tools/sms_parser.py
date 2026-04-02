#!/usr/bin/env python3
"""
短信解析器

支持格式：
1. Android SMS Backup & Restore 导出的 XML
2. CSV 格式导出
3. 纯文本格式

用法：
    python sms_parser.py --file sms_backup.xml --target "+8613800138000" --output output.txt
    python sms_parser.py --file sms.csv --target "小美" --output output.txt
"""

import re
import csv
import sys
import argparse
from pathlib import Path
from xml.etree import ElementTree
from datetime import datetime, timezone


def parse_sms_xml(file_path: str, target: str) -> list[dict]:
    """解析 Android SMS Backup & Restore 导出的 XML"""
    messages = []

    try:
        tree = ElementTree.parse(file_path)
        root = tree.getroot()
    except ElementTree.ParseError as e:
        print(f"错误：XML 解析失败: {e}", file=sys.stderr)
        return []

    for sms in root.iter("sms"):
        address = sms.get("address", "")
        body = sms.get("body", "")
        date_ms = sms.get("date", "")
        msg_type = sms.get("type", "")  # 1=received, 2=sent

        # Only keep received messages (from target)
        if msg_type != "1":
            continue

        if target and target not in address:
            # Also check contact_name attribute
            contact = sms.get("contact_name", "")
            if target not in contact:
                continue

        if not body.strip():
            continue

        timestamp = ""
        if date_ms:
            try:
                ts = int(date_ms) / 1000
                timestamp = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            except (ValueError, OSError):
                pass

        messages.append({
            "sender": sms.get("contact_name", address),
            "content": body.strip(),
            "timestamp": timestamp,
        })

    return messages


def parse_sms_csv(file_path: str, target: str) -> list[dict]:
    """解析 CSV 格式的短信导出"""
    messages = []

    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sender = (
                row.get("sender") or row.get("from") or
                row.get("address") or row.get("number") or ""
            )
            content = (
                row.get("content") or row.get("body") or
                row.get("text") or row.get("message") or ""
            )
            timestamp = (
                row.get("timestamp") or row.get("date") or
                row.get("time") or ""
            )

            if target and target not in str(sender):
                continue
            if not content.strip():
                continue

            messages.append({
                "sender": str(sender),
                "content": str(content).strip(),
                "timestamp": str(timestamp),
            })

    return messages


def parse_sms_txt(file_path: str, target: str) -> list[dict]:
    """解析纯文本格式的短信记录"""
    messages = []

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    pattern = re.compile(
        r"^(?P<time>\d{4}[-/]\d{1,2}[-/]\d{1,2}[\s\d:]*)\s+(?P<sender>.+?)[:：]\s*(?P<content>.+)$"
    )

    for line in lines:
        line = line.strip()
        if not line:
            continue

        m = pattern.match(line)
        if m:
            sender = m.group("sender").strip()
            content = m.group("content").strip()
            timestamp = m.group("time").strip()

            if target and target not in sender:
                continue
            if not content:
                continue

            messages.append({
                "sender": sender,
                "content": content,
                "timestamp": timestamp,
            })

    return messages


def extract_key_content(messages: list[dict]) -> dict:
    """分类提取消息"""
    long_messages = []
    emotional_messages = []
    daily_messages = []

    emotional_keywords = [
        "想你", "爱你", "喜欢", "讨厌", "生气", "难过", "开心",
        "不开心", "对不起", "分手", "在一起", "想见你",
    ]

    for msg in messages:
        content = msg["content"]
        if len(content) > 50:
            long_messages.append(msg)
        elif any(kw in content for kw in emotional_keywords):
            emotional_messages.append(msg)
        else:
            daily_messages.append(msg)

    return {
        "long_messages": long_messages,
        "emotional_messages": emotional_messages,
        "daily_messages": daily_messages,
        "total_count": len(messages),
    }


def format_output(target: str, extracted: dict) -> str:
    """格式化输出"""
    lines = [
        f"# 短信记录提取结果",
        f"目标人物：{target}",
        f"总消息数：{extracted['total_count']}",
        "",
        "---",
        "",
        "## 长消息（权重最高）",
        "",
    ]

    for msg in extracted["long_messages"]:
        ts = f"[{msg['timestamp']}] " if msg["timestamp"] else ""
        lines.append(f"{ts}{msg['content']}")
        lines.append("")

    lines += ["---", "", "## 情感类消息", ""]

    for msg in extracted["emotional_messages"]:
        ts = f"[{msg['timestamp']}] " if msg["timestamp"] else ""
        lines.append(f"{ts}{msg['content']}")
        lines.append("")

    lines += ["---", "", "## 日常沟通（风格参考）", ""]

    for msg in extracted["daily_messages"]:
        ts = f"[{msg['timestamp']}] " if msg["timestamp"] else ""
        lines.append(f"{ts}{msg['content']}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="解析短信导出文件")
    parser.add_argument("--file", required=True, help="输入文件路径（.xml / .csv / .txt）")
    parser.add_argument("--target", default="", help="目标人物（手机号或姓名，留空提取所有人）")
    parser.add_argument("--output", default=None, help="输出文件路径")

    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"错误：文件不存在 {file_path}", file=sys.stderr)
        sys.exit(1)

    suffix = file_path.suffix.lower()

    if suffix == ".xml":
        messages = parse_sms_xml(str(file_path), args.target)
    elif suffix == ".csv":
        messages = parse_sms_csv(str(file_path), args.target)
    else:
        messages = parse_sms_txt(str(file_path), args.target)

    if not messages:
        print(f"警告：未找到 '{args.target}' 的短信", file=sys.stderr)

    extracted = extract_key_content(messages)
    output = format_output(args.target, extracted)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"已输出到 {args.output}，共 {len(messages)} 条短信")
    else:
        print(output)


if __name__ == "__main__":
    main()
