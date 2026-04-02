#!/usr/bin/env python3
"""
微信聊天记录解析器

支持的导出格式：
1. WechatExporter 导出的 txt 文件（格式：时间 发送人: 内容）
2. WechatExporter 导出的 html 文件
3. 其他微信备份工具导出的 txt/csv

用法：
    python wechat_parser.py --file chat.txt --target "小美" --output output.txt
    python wechat_parser.py --file chat.html --target "小美" --output output.txt
"""

import re
import sys
import csv
import argparse
from pathlib import Path
from html.parser import HTMLParser


class WechatHTMLParser(HTMLParser):
    """解析 WechatExporter 导出的 HTML 格式"""

    def __init__(self, target_name: str):
        super().__init__()
        self.target_name = target_name
        self.messages = []
        self._current_sender = ""
        self._current_time = ""
        self._current_content = []
        self._in_sender = False
        self._in_content = False
        self._in_time = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")

        if "sender" in cls:
            self._in_sender = True
        elif "content" in cls or "message-text" in cls:
            self._in_content = True
        elif "time" in cls or "timestamp" in cls:
            self._in_time = True

    def handle_endtag(self, tag):
        if self._in_sender:
            self._in_sender = False
        elif self._in_content:
            self._in_content = False
            content = "".join(self._current_content).strip()
            if content and self.target_name in self._current_sender:
                self.messages.append({
                    "sender": self._current_sender,
                    "content": content,
                    "timestamp": self._current_time,
                })
            self._current_content = []
        elif self._in_time:
            self._in_time = False

    def handle_data(self, data):
        if self._in_sender:
            self._current_sender = data.strip()
        elif self._in_content:
            self._current_content.append(data)
        elif self._in_time:
            self._current_time = data.strip()


def parse_wechat_txt(file_path: str, target_name: str) -> list[dict]:
    """解析微信导出的 TXT 格式消息"""
    messages = []

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 匹配常见格式：
    # 2024-01-01 10:00:00 小美: 消息内容
    # 2024/01/01 10:00 小美：消息内容
    pattern = re.compile(
        r"^(?P<time>\d{4}[-/]\d{1,2}[-/]\d{1,2}[\s\d:]*)\s+(?P<sender>.+?)[:：]\s*(?P<content>.+)$"
    )

    current_msg = None

    for line in lines:
        line = line.rstrip("\n")
        if not line.strip():
            continue

        m = pattern.match(line)
        if m:
            # 保存上一条多行消息
            if current_msg and target_name in current_msg["sender"]:
                messages.append(current_msg)

            current_msg = {
                "sender": m.group("sender").strip(),
                "content": m.group("content").strip(),
                "timestamp": m.group("time").strip(),
            }
        elif current_msg:
            # 多行消息，追加到当前消息
            current_msg["content"] += "\n" + line

    # 最后一条
    if current_msg and target_name in current_msg["sender"]:
        messages.append(current_msg)

    # 过滤系统消息和媒体占位符
    filtered = []
    skip_patterns = [
        "[图片]", "[文件]", "[撤回了一条消息]", "[语音]", "[视频]",
        "[表情]", "[位置]", "[名片]", "[链接]", "[红包]", "[转账]",
        "<img", "<video", "<audio",
    ]
    for msg in messages:
        content = msg["content"].strip()
        if not content:
            continue
        if any(p in content for p in skip_patterns):
            continue
        filtered.append(msg)

    return filtered


def parse_wechat_csv(file_path: str, target_name: str) -> list[dict]:
    """解析 CSV 格式的微信聊天记录"""
    messages = []

    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sender = (
                row.get("sender") or row.get("发送人") or
                row.get("from") or row.get("NickName") or ""
            )
            content = (
                row.get("content") or row.get("内容") or
                row.get("message") or row.get("Message") or ""
            )
            timestamp = (
                row.get("timestamp") or row.get("时间") or
                row.get("time") or row.get("StrTime") or ""
            )

            if target_name and target_name not in str(sender):
                continue
            if not content.strip():
                continue

            messages.append({
                "sender": str(sender),
                "content": str(content).strip(),
                "timestamp": str(timestamp),
            })

    return messages


def parse_wechat_html(file_path: str, target_name: str) -> list[dict]:
    """解析 HTML 格式的微信聊天记录"""
    with open(file_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    parser = WechatHTMLParser(target_name)
    parser.feed(html_content)
    return parser.messages


def extract_key_content(messages: list[dict]) -> dict:
    """
    对消息进行分类提取：
    - 长消息（>50字）：可能包含心情、想法、重要表达
    - 情感类回复：包含情感关键词
    - 日常沟通：其他消息
    """
    long_messages = []
    emotional_messages = []
    daily_messages = []

    emotional_keywords = [
        "想你", "爱你", "喜欢", "讨厌", "生气", "难过", "开心", "高兴",
        "不开心", "委屈", "对不起", "分手", "在一起", "想见你", "好想",
        "心疼", "舍不得", "感动", "幸福", "孤独", "害怕", "担心",
        "吵架", "冷战", "和好", "原谅", "道歉", "伤心", "哭",
        "miss", "love", "sorry", "happy", "sad",
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


def format_output(target_name: str, extracted: dict) -> str:
    """格式化输出，供 AI 分析使用"""
    lines = [
        f"# 微信聊天记录提取结果",
        f"目标人物：{target_name}",
        f"总消息数：{extracted['total_count']}",
        "",
        "---",
        "",
        "## 长消息（心情/想法类，权重最高）",
        "",
    ]

    for msg in extracted["long_messages"]:
        ts = f"[{msg['timestamp']}] " if msg["timestamp"] else ""
        lines.append(f"{ts}{msg['content']}")
        lines.append("")

    lines += [
        "---",
        "",
        "## 情感类消息",
        "",
    ]

    for msg in extracted["emotional_messages"]:
        ts = f"[{msg['timestamp']}] " if msg["timestamp"] else ""
        lines.append(f"{ts}{msg['content']}")
        lines.append("")

    lines += [
        "---",
        "",
        "## 日常沟通（风格参考）",
        "",
    ]

    for msg in extracted["daily_messages"]:
        ts = f"[{msg['timestamp']}] " if msg["timestamp"] else ""
        lines.append(f"{ts}{msg['content']}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="解析微信聊天记录导出文件")
    parser.add_argument("--file", required=True, help="输入文件路径（.txt / .html / .csv）")
    parser.add_argument("--target", default="", help="目标人物姓名（只提取此人发出的消息，留空提取所有人）")
    parser.add_argument("--output", default=None, help="输出文件路径（默认打印到 stdout）")

    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"错误：文件不存在 {file_path}", file=sys.stderr)
        sys.exit(1)

    suffix = file_path.suffix.lower()

    if suffix == ".html" or suffix == ".htm":
        messages = parse_wechat_html(str(file_path), args.target)
    elif suffix == ".csv":
        messages = parse_wechat_csv(str(file_path), args.target)
    else:
        messages = parse_wechat_txt(str(file_path), args.target)

    if not messages:
        print(f"警告：未找到 '{args.target}' 发出的消息", file=sys.stderr)
        print("提示：请检查目标姓名是否与文件中的发送人名称一致", file=sys.stderr)

    extracted = extract_key_content(messages)
    output = format_output(args.target, extracted)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"已输出到 {args.output}，共 {len(messages)} 条消息")
    else:
        print(output)


if __name__ == "__main__":
    main()
