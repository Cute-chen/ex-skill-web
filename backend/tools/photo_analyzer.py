#!/usr/bin/env python3
"""
照片元数据分析器

提取照片的 EXIF 元数据（日期、位置、相机），按时间线分组。
不分析照片内容（内容分析由 Claude 的 Read 工具完成）。

用法：
    python photo_analyzer.py --dir ~/Photos/with_her --output timeline.txt
"""

import os
import sys
import struct
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict


def extract_exif_date(file_path: str) -> str | None:
    """从 JPEG 文件中提取 EXIF 拍摄日期（不依赖 PIL）"""
    try:
        with open(file_path, "rb") as f:
            # Check JPEG header
            if f.read(2) != b"\xff\xd8":
                return None

            while True:
                marker = f.read(2)
                if len(marker) < 2:
                    break

                if marker[0] != 0xFF:
                    break

                if marker[1] == 0xE1:  # APP1 (EXIF)
                    length = struct.unpack(">H", f.read(2))[0]
                    exif_data = f.read(length - 2)

                    # Search for DateTimeOriginal tag in raw bytes
                    # DateTimeOriginal format: "YYYY:MM:DD HH:MM:SS"
                    date_pattern = rb"\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}"
                    import re
                    matches = re.findall(date_pattern, exif_data)
                    if matches:
                        return matches[0].decode("ascii")

                    return None
                elif marker[1] in (0xD9, 0xDA):  # EOI or SOS
                    break
                else:
                    length = struct.unpack(">H", f.read(2))[0]
                    f.seek(length - 2, 1)

    except Exception:
        pass

    return None


def get_photo_date(file_path: Path) -> str:
    """获取照片日期：优先 EXIF，fallback 到文件修改时间"""
    exif_date = extract_exif_date(str(file_path))
    if exif_date:
        try:
            dt = datetime.strptime(exif_date, "%Y:%m:%d %H:%M:%S")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Fallback to file modification time
    mtime = file_path.stat().st_mtime
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")


def scan_photos(directory: str) -> list[dict]:
    """扫描目录中的照片文件"""
    photo_extensions = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tiff", ".bmp"}
    photos = []

    dir_path = Path(directory)
    if not dir_path.exists():
        print(f"错误：目录不存在 {directory}", file=sys.stderr)
        return []

    for file_path in sorted(dir_path.rglob("*")):
        if file_path.suffix.lower() in photo_extensions and file_path.is_file():
            date = get_photo_date(file_path)
            photos.append({
                "path": str(file_path),
                "filename": file_path.name,
                "date": date,
                "size_kb": file_path.stat().st_size // 1024,
            })

    return photos


def group_by_date(photos: list[dict]) -> dict[str, list]:
    """按日期分组照片"""
    groups = defaultdict(list)
    for photo in photos:
        groups[photo["date"]].append(photo)
    return dict(sorted(groups.items()))


def format_output(photo_dir: str, groups: dict, total: int) -> str:
    """格式化时间线输出"""
    lines = [
        f"# 照片时间线",
        f"目录：{photo_dir}",
        f"总照片数：{total}",
        f"跨度：{min(groups.keys()) if groups else 'N/A'} ~ {max(groups.keys()) if groups else 'N/A'}",
        "",
        "---",
        "",
    ]

    for date, photos in groups.items():
        lines.append(f"## {date}（{len(photos)} 张）")
        for p in photos:
            lines.append(f"  - {p['filename']}（{p['size_kb']} KB）")
        lines.append("")

    lines += [
        "---",
        "",
        "## 使用说明",
        "",
        "以上是照片的时间线摘要。如需查看具体照片的内容，",
        "请告诉我日期或文件名，我会用 Read 工具直接查看照片。",
    ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="分析照片元数据，生成时间线")
    parser.add_argument("--dir", required=True, help="照片目录路径")
    parser.add_argument("--output", default=None, help="输出文件路径")

    args = parser.parse_args()

    photos = scan_photos(args.dir)
    if not photos:
        print("警告：未找到照片文件", file=sys.stderr)

    groups = group_by_date(photos)
    output = format_output(args.dir, groups, len(photos))

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"已输出到 {args.output}，共 {len(photos)} 张照片，{len(groups)} 个日期")
    else:
        print(output)


if __name__ == "__main__":
    main()
