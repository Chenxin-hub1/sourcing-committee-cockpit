"""演示文件（v3 Phase-5）：提交时或案例页上传 PPT / PDF / Excel / Word，所有人可下载。

存放：Graph 核心凭据 + 站点地址配齐时存 SharePoint 文档库（SC_SP_FOLDER / <案例号> 文件夹）；
否则存服务器本地 SC_UPLOAD_DIR（演示环境与 IT 授权前）。每个文件记录自己的存放位置（store），
切换到 SharePoint 后，之前存在本地的文件照样能下载。

记录形如 {id, name, originalName, size, contentType, uploadedAt, uploadedBy, store: local|sharepoint,
driveId, itemId, webUrl}，挂在提交单或案例行的 files 列表上，确认登记时随提交单带进案例。

v3 Phase-15（领导要求）：演示文件在系统里统一改名 `YYYY.MM.DD 项目 零件描述 零件号, 供应商.ext`
（bundle_file_name），buyer 没好好命名也能一眼看出是哪个案例；原文件名留在 originalName。
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from . import graph, logic
from .config import get_settings

log = logging.getLogger("cockpit.files")

ALLOWED_EXTENSIONS = {".ppt", ".pptx", ".pdf", ".xls", ".xlsx", ".xlsm", ".doc", ".docx"}
MAX_BYTES = 100 * 1024 * 1024  # 反馈人答复：单个 ≤ 100 MB
MAX_FILES_PER_RECORD = 10
MAX_NAME_LENGTH = 120
CHUNK_BYTES = 10 * 1024 * 1024  # SharePoint 分块：10 MiB，是 320 KiB 的整数倍（微软建议 5–10 MiB）
TYPES_TEXT = "PowerPoint, PDF, Excel or Word"
# 待办反馈的凭证（v3 Phase-14）：另允许 Outlook 邮件
FEEDBACK_EXTENSIONS = ALLOWED_EXTENSIONS | {".msg", ".eml"}
FEEDBACK_TYPES_TEXT = "PowerPoint, PDF, Excel, Word or Outlook email (.msg / .eml)"
# SharePoint 文件名不允许的字符；控制字符一并替换
_BAD_CHARS = re.compile(r'[\x00-\x1f"*:<>?/\\|#%]')


def clean_name(raw: str, allowed: frozenset[str] | set[str] = ALLOWED_EXTENSIONS) -> str | None:
    """浏览器给的文件名 → 安全文件名；类型不允许、为空或过长返回 None。"""
    name = re.split(r"[\\/]", raw or "")[-1]  # 去掉任何目录部分（Windows 与 Unix 写法）
    name = _BAD_CHARS.sub("_", name).strip().strip(".").strip()
    stem, ext = os.path.splitext(name)
    if not stem.strip() or ext.lower() not in allowed or len(name) > MAX_NAME_LENGTH:
        return None
    return name


def _joined(values: list[str], sep: str = "+") -> str:
    seen: list[str] = []
    for v in values:
        v = (v or "").strip()
        if v and v not in seen:
            seen.append(v)
    return sep.join(seen)


def bundle_file_name(record: dict, original: str, when=None) -> str:
    """领导给的例子 `2026.09.30 MBEAL Spool PNxxx, XLX`：日期 项目 零件描述 零件号, 供应商 + 原扩展名。

    bundle（多零件）：项目与供应商去重后用 "+" 连接；零件描述与零件号取第一个零件，零件号后标 "+N"。
    超长时按 MAX_NAME_LENGTH 截断主干；任何一段为空就跳过，最差退回 `日期 原文件名`。"""
    rows = logic.part_number_lines(record)
    first = rows[0] if rows else {}
    day = (when or logic.na_now()).strftime("%Y.%m.%d")
    projects = _joined([r.get("project") or record.get("project") or "" for r in rows])
    suppliers = _joined([r.get("recommendedSupplier") or record.get("recommendedSupplier") or "" for r in rows])
    pn = (first.get("partNumber") or "").strip()
    if pn and len(rows) > 1:
        pn += f"+{len(rows) - 1}"
    original_stem, ext = os.path.splitext(original)
    ext = ext.lower()
    head = " ".join(part for part in (day, projects, (first.get("partDescription") or "").strip(), pn) if part)
    if head == day and not suppliers:  # 记录上什么都没有（不该发生）：至少带上日期
        head = f"{day} {original_stem}"
    stem = f"{head}, {suppliers}" if suppliers else head
    stem = _BAD_CHARS.sub("_", stem).strip().strip(".").strip()
    if len(stem) + len(ext) > MAX_NAME_LENGTH:
        stem = stem[: MAX_NAME_LENGTH - len(ext)].rstrip(" ,.")
    return f"{stem}{ext}"


def folder_name(raw: str) -> str:
    """案例号当文件夹名（Supplyon 号按原样录入，可能带斜杠等字符）。"""
    return _BAD_CHARS.sub("_", raw or "").strip().strip(".") or "Unassigned"


def upload_root() -> Path:
    return Path(get_settings().upload_dir)


def check_room(record: dict) -> None:
    if len(record.get("files") or []) >= MAX_FILES_PER_RECORD:
        raise HTTPException(422, f"A registration can carry at most {MAX_FILES_PER_RECORD} files. "
                                 "Remove one before adding another.")


def checked_name(raw: str, allowed: set[str] | None = None) -> str:
    allowed = allowed or ALLOWED_EXTENSIONS
    name = clean_name(raw, allowed)
    if name is None:
        types = FEEDBACK_TYPES_TEXT if allowed is FEEDBACK_EXTENSIONS else TYPES_TEXT
        raise HTTPException(422, f"Only {types} files can be uploaded "
                                 f"({', '.join(sorted(allowed))}), with a name up to {MAX_NAME_LENGTH} characters.")
    return name


async def receive(request: Request) -> tuple[Path, int]:
    """把请求体（文件原始字节）流式写进临时文件，边收边数；超过 100 MB 立即中止。"""
    too_big = HTTPException(413, "The file is larger than 100 MB. Please upload a smaller file "
                                 "(for example, save the PowerPoint as PDF or compress the pictures).")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BYTES:
        raise too_big
    incoming = upload_root() / ".incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    tmp = incoming / secrets.token_hex(16)
    size = 0
    try:
        with tmp.open("wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise too_big
                fh.write(chunk)
        if size == 0:
            raise HTTPException(422, "The file is empty.")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp, size


async def store(tmp: Path, name: str, size: int, content_type: str, folder: str, uploaded_by: str,
                original_name: str | None = None) -> dict:
    """临时文件 → 最终存放处，返回文件记录。SharePoint 失败抛 502（文案说明原因），临时文件总会清理。

    name 是系统里的文件名（演示文件已按案例改名）；original_name 是 buyer 上传时的文件名，留着可查。"""
    record = {
        "id": f"F-{secrets.token_hex(8)}", "name": name, "originalName": original_name or name,
        "size": size, "contentType": content_type[:100],
        "uploadedAt": logic.fmt_when(logic.na_now()), "uploadedBy": uploaded_by,
        "store": "local", "driveId": "", "itemId": "", "webUrl": "",
    }
    try:
        if graph.files_configured():
            try:
                item = await graph.upload_file(tmp, name, size, [get_settings().sp_folder, folder_name(folder)], CHUNK_BYTES)
            except Exception as exc:  # 任何上传失败都要变成可读的 502，而不是 500
                log.warning("sharepoint upload failed for %s: %s", name, exc)
                reason = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
                raise HTTPException(502, f"The file could not be saved to SharePoint ({reason}). "
                                         "Please try again later, or tell the Sourcing admin.") from exc
            record.update(store="sharepoint", driveId=item["driveId"], itemId=item["itemId"],
                          webUrl=item["webUrl"], name=item["name"] or name)
        else:
            tmp.replace(upload_root() / record["id"])
    finally:
        tmp.unlink(missing_ok=True)
    return record


async def download(record: dict):
    """本地文件直接回传；SharePoint 文件跳转到预认证下载地址（看的人不需要 SharePoint 权限）。"""
    if record.get("store") == "sharepoint":
        try:
            url = await graph.download_url(record["driveId"], record["itemId"])
        except Exception as exc:  # 取链接失败给可读的 502
            log.warning("sharepoint download link failed for %s: %s", record.get("id"), exc)
            raise HTTPException(502, "The file could not be fetched from SharePoint right now. Please try again later.") from exc
        return RedirectResponse(url, status_code=302)
    path = upload_root() / record["id"]
    if not path.is_file():
        raise HTTPException(404, "This file is no longer available on the server.")
    return FileResponse(path, media_type=record.get("contentType") or "application/octet-stream",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(record['name'])}"})


async def remove(record: dict) -> None:
    """删除存放的文件；SharePoint 删不掉只记日志（记录照样移除，文件留在文档库里由人工清理）。"""
    if record.get("store") == "sharepoint":
        try:
            await graph.delete_file(record["driveId"], record["itemId"])
        except Exception as exc:  # noqa: BLE001
            log.warning("sharepoint delete failed for %s: %s", record.get("id"), exc)
        return
    (upload_root() / record["id"]).unlink(missing_ok=True)
