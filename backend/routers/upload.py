import subprocess
import sys
import tempfile
import os
from pathlib import Path
from fastapi import APIRouter, File, Form, UploadFile, HTTPException, Query
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/upload", tags=["upload"])

TOOLS_DIR = Path(__file__).parent.parent / "tools"


def _run_parser(script: str, extra_args: list, input_path: str) -> str:
    out_file = tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8")
    out_file.close()
    try:
        result = subprocess.run(
            [sys.executable, str(TOOLS_DIR / script), "--file", input_path,
             "--output", out_file.name] + extra_args,
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=result.stderr or "解析失败")
        content = Path(out_file.name).read_text(encoding="utf-8")
        return content
    finally:
        try:
            os.unlink(out_file.name)
        except Exception:
            pass


def _save_upload(file: UploadFile) -> str:
    suffix = Path(file.filename).suffix if file.filename else ".tmp"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(file.file.read())
        tmp.flush()
        return tmp.name
    finally:
        tmp.close()


@router.post("/wechat")
async def parse_wechat(
    file: UploadFile = File(...),
    target: str = Form(""),
):
    tmp_path = _save_upload(file)
    try:
        content = _run_parser("wechat_parser.py", ["--target", target], tmp_path)
        return {"content": content}
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.post("/imessage")
async def parse_imessage(
    file: UploadFile = File(...),
    target: str = Form(""),
):
    tmp_path = _save_upload(file)
    try:
        content = _run_parser("imessage_parser.py", ["--target", target], tmp_path)
        return {"content": content}
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.post("/sms")
async def parse_sms(
    file: UploadFile = File(...),
    target: str = Form(""),
):
    tmp_path = _save_upload(file)
    try:
        content = _run_parser("sms_parser.py", ["--target", target], tmp_path)
        return {"content": content}
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.post("/social")
async def parse_social(
    file: UploadFile = File(...),
    target: str = Form(""),
    platform: str = Form("text"),
):
    tmp_path = _save_upload(file)
    try:
        content = _run_parser("social_media_parser.py", ["--platform", platform, "--target", target], tmp_path)
        return {"content": content}
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.post("/photo")
async def parse_photo(
    files: list[UploadFile] = File(...),
):
    import tempfile as tmpmod
    # Save all photos to a temp directory
    tmp_dir = tempfile.mkdtemp()
    try:
        for f in files:
            dest = os.path.join(tmp_dir, f.filename or "photo.jpg")
            with open(dest, "wb") as out:
                out.write(f.file.read())

        out_file = tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8")
        out_file.close()
        try:
            result = subprocess.run(
                [sys.executable, str(TOOLS_DIR / "photo_analyzer.py"),
                 "--dir", tmp_dir, "--output", out_file.name],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode != 0:
                raise HTTPException(status_code=500, detail=result.stderr or "照片分析失败")
            content = Path(out_file.name).read_text(encoding="utf-8")
            return {"content": content}
        finally:
            try:
                os.unlink(out_file.name)
            except Exception:
                pass
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
