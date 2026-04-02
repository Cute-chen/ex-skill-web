#!/usr/bin/env python3
"""
前女友.skill Web — 启动脚本
用法: python run.py [--port 8765] [--no-browser] [--dev]
"""
import argparse
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).parent
FRONTEND = ROOT / "frontend"
STATIC = ROOT / "backend" / "static"


def run(cmd, cwd=None, check=True):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, cwd=cwd, check=check)


def npm_cmd():
    """Return npm executable (handles Windows)."""
    if sys.platform == "win32":
        return "npm.cmd"
    return "npm"


def check_node():
    try:
        result = subprocess.run(["node", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            return True
    except FileNotFoundError:
        pass
    return False


def install_frontend():
    node_modules = FRONTEND / "node_modules"
    if not node_modules.exists():
        print("\n[1/3] 安装前端依赖 (npm install)...")
        run([npm_cmd(), "install"], cwd=FRONTEND)
    else:
        print("[1/3] 前端依赖已安装 ✓")


def build_frontend(force=False):
    index_html = STATIC / "index.html"
    if not force and index_html.exists():
        print("[2/3] 前端已构建 ✓")
        return
    print("\n[2/3] 构建前端 (npm run build)...")
    run([npm_cmd(), "run", "build"], cwd=FRONTEND)
    print("前端构建完成 ✓")


def start_server(port, open_browser):
    print(f"\n[3/3] 启动服务器 http://localhost:{port}")
    print("      按 Ctrl+C 停止\n")

    if open_browser:
        def _open():
            time.sleep(1.2)
            webbrowser.open(f"http://localhost:{port}")
        import threading
        threading.Thread(target=_open, daemon=True).start()

    os.chdir(ROOT)
    subprocess.run([
        sys.executable, "-m", "uvicorn",
        "backend.main:app",
        "--host", "0.0.0.0",
        "--port", str(port),
    ])


def start_dev(port):
    """Dev mode: run uvicorn with reload + vite dev server concurrently."""
    print("\n开发模式：启动 uvicorn (reload) + Vite dev server")
    print("  后端: http://localhost:8765")
    print("  前端: http://localhost:5173  (带热更新)\n")

    backend_proc = subprocess.Popen([
        sys.executable, "-m", "uvicorn",
        "backend.main:app",
        "--host", "0.0.0.0",
        "--port", str(port),
        "--reload",
    ], cwd=ROOT)

    frontend_proc = subprocess.Popen(
        [npm_cmd(), "run", "dev"],
        cwd=FRONTEND
    )

    try:
        backend_proc.wait()
    except KeyboardInterrupt:
        print("\n停止中...")
        backend_proc.terminate()
        frontend_proc.terminate()


def main():
    parser = argparse.ArgumentParser(description="前女友.skill Web 启动脚本")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--dev", action="store_true", help="开发模式（前端热更新）")
    parser.add_argument("--rebuild", action="store_true", help="强制重新构建前端")
    args = parser.parse_args()

    print("=" * 48)
    print("   前女友.skill Web")
    print("=" * 48)

    # Check Node.js
    if not check_node():
        print("\n错误：未找到 Node.js，请先安装：https://nodejs.org")
        sys.exit(1)

    if args.dev:
        install_frontend()
        start_dev(args.port)
    else:
        install_frontend()
        build_frontend(force=args.rebuild)
        start_server(args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
