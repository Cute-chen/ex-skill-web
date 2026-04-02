#!/usr/bin/env python3
"""
社交媒体解析器

支持平台：
1. 微博（Weibo）— JSON 数据导出
2. 豆瓣（Douban）— JSON/HTML 导出
3. 小红书（Xiaohongshu/RED）— JSON 导出
4. Instagram — JSON 数据导出
5. 通用文本（text）— 纯文本帖子

用法：
    python social_media_parser.py --file weibo_export.json --platform weibo --target "小美" --output output.txt
    python social_media_parser.py --file posts.txt --platform text --target "小美" --output output.txt
"""

import json
import re
import sys
import argparse
from pathlib import Path
from datetime import datetime


def parse_weibo(file_path: str, target: str) -> list[dict]:
    """解析微博 JSON 数据导出"""
    posts = []

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 微博数据导出格式可能是 list 或 dict
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("statuses") or data.get("data") or data.get("weibos") or []
    else:
        return []

    for item in items:
        user = item.get("user", {})
        username = user.get("screen_name") or user.get("name") or ""

        if target and target not in username:
            continue

        text = item.get("text") or item.get("content") or ""
        # Remove HTML tags from Weibo text
        text = re.sub(r"<[^>]+>", "", text).strip()

        created_at = item.get("created_at") or item.get("time") or ""
        likes = item.get("attitudes_count") or item.get("likes") or 0
        comments = item.get("comments_count") or 0

        if not text:
            continue

        posts.append({
            "text": text,
            "date": str(created_at),
            "likes": likes,
            "comments": comments,
            "platform": "微博",
        })

    return posts


def parse_douban(file_path: str, target: str) -> list[dict]:
    """解析豆瓣导出"""
    posts = []

    with open(file_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            # Try as text
            f.seek(0)
            return parse_text(file_path, target)

    items = data if isinstance(data, list) else data.get("data", [])

    for item in items:
        author = item.get("author") or item.get("user", {}).get("name", "")
        if target and target not in str(author):
            continue

        text = item.get("text") or item.get("content") or item.get("abstract") or ""
        date = item.get("date") or item.get("created") or ""

        if not text.strip():
            continue

        posts.append({
            "text": text.strip(),
            "date": str(date),
            "likes": item.get("likes", 0),
            "comments": item.get("comments", 0),
            "platform": "豆瓣",
        })

    return posts


def parse_xiaohongshu(file_path: str, target: str) -> list[dict]:
    """解析小红书 JSON 导出"""
    posts = []

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data if isinstance(data, list) else data.get("data", [])

    for item in items:
        author = (
            item.get("user", {}).get("nickname") or
            item.get("author") or ""
        )
        if target and target not in str(author):
            continue

        title = item.get("title") or ""
        desc = item.get("desc") or item.get("content") or ""
        text = f"{title}\n{desc}".strip() if title else desc.strip()
        date = item.get("time") or item.get("date") or ""

        if not text:
            continue

        posts.append({
            "text": text,
            "date": str(date),
            "likes": item.get("liked_count", 0),
            "comments": item.get("comment_count", 0),
            "platform": "小红书",
        })

    return posts


def parse_instagram(file_path: str, target: str) -> list[dict]:
    """解析 Instagram JSON 数据导出"""
    posts = []

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Instagram data export structure
    items = data if isinstance(data, list) else data.get("posts", data.get("data", []))

    for item in items:
        # Instagram export usually doesn't have sender info (it's your own data)
        text = ""
        if isinstance(item, dict):
            media = item.get("media", [{}])
            if isinstance(media, list) and media:
                text = media[0].get("title", "") or media[0].get("caption", "")
            text = text or item.get("title", "") or item.get("caption", "")
            date = item.get("creation_timestamp", "")
            if isinstance(date, (int, float)):
                date = datetime.fromtimestamp(date).strftime("%Y-%m-%d %H:%M")
        else:
            continue

        if not text.strip():
            continue

        posts.append({
            "text": text.strip(),
            "date": str(date),
            "likes": 0,
            "comments": 0,
            "platform": "Instagram",
        })

    return posts


def parse_text(file_path: str, target: str) -> list[dict]:
    """解析纯文本帖子"""
    posts = []

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Split by common delimiters
    entries = re.split(r"\n={3,}\n|\n-{3,}\n|\n\n\n+", content)

    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue

        # Try to extract date
        date_match = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", entry)
        date = date_match.group(1) if date_match else ""

        posts.append({
            "text": entry,
            "date": date,
            "likes": 0,
            "comments": 0,
            "platform": "文本",
        })

    return posts


def format_output(target: str, posts: list[dict]) -> str:
    """格式化输出"""
    lines = [
        f"# 社交媒体内容提取结果",
        f"目标人物：{target}",
        f"总帖子数：{len(posts)}",
        "",
        "---",
        "",
    ]

    # 按长度分类
    long_posts = [p for p in posts if len(p["text"]) > 100]
    short_posts = [p for p in posts if len(p["text"]) <= 100]

    lines += ["## 长帖子（观点/情感类，权重最高）", ""]

    for p in long_posts:
        date_str = f"[{p['date']}] " if p["date"] else ""
        platform = f"({p['platform']}) " if p.get("platform") else ""
        lines.append(f"{date_str}{platform}{p['text']}")
        lines.append("")

    lines += ["---", "", "## 短帖子（日常/风格参考）", ""]

    for p in short_posts:
        date_str = f"[{p['date']}] " if p["date"] else ""
        platform = f"({p['platform']}) " if p.get("platform") else ""
        lines.append(f"{date_str}{platform}{p['text']}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="解析社交媒体导出文件")
    parser.add_argument("--file", required=True, help="输入文件路径")
    parser.add_argument(
        "--platform",
        required=True,
        choices=["weibo", "douban", "xiaohongshu", "instagram", "text"],
        help="平台类型",
    )
    parser.add_argument("--target", default="", help="目标人物（可选，用于过滤）")
    parser.add_argument("--output", default=None, help="输出文件路径")

    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"错误：文件不存在 {file_path}", file=sys.stderr)
        sys.exit(1)

    parsers = {
        "weibo": parse_weibo,
        "douban": parse_douban,
        "xiaohongshu": parse_xiaohongshu,
        "instagram": parse_instagram,
        "text": parse_text,
    }

    posts = parsers[args.platform](str(file_path), args.target)

    if not posts:
        print(f"警告：未提取到帖子内容", file=sys.stderr)

    output = format_output(args.target or "未指定", posts)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"已输出到 {args.output}，共 {len(posts)} 条帖子")
    else:
        print(output)


if __name__ == "__main__":
    main()
