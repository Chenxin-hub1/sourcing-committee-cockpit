"""投递通道：Email（SMTP）+ Teams（webhook）—— 提醒与审批结果通知共用。

设计约束：
- 未配置的通道记 "skipped"，已配置但出错的通道记 "failed: …"，绝不让投递异常中断每日检查；
- 结果写进日志条目的 delivery 字段，与消息一起持久化，前端可见。
"""

from __future__ import annotations

import logging
import re
from email.message import EmailMessage
from typing import Any

import httpx

from . import graph
from .config import get_settings

log = logging.getLogger("cockpit.delivery")

_ADDR_SPLIT_RE = re.compile(r"[;,]")
_ADDR_UNSAFE_RE = re.compile(r"[\r\n]")


def clean_addresses(value: str) -> str:
    """标准化收件人串：兼容逗号/分号分隔（Outlook 习惯），修剪空白，
    丢弃空项、无 @ 的项和含换行的项（后者可构成邮件头注入）。"""
    kept = []
    for part in _ADDR_SPLIT_RE.split(value or ""):
        p = part.strip()
        if p and "@" in p and not _ADDR_UNSAFE_RE.search(p):
            kept.append(p)
    return ", ".join(kept)


async def send_email(to: str, subject: str, body: str, cc: str = "") -> str:
    """统一发信入口（提醒邮件与审批结果邮件共用）。返回 sent / skipped / failed: …。

    通道选择：配置了 SMTP 中继（SC_SMTP_HOST）优先走 SMTP；未配置而 Graph 凭据与
    发件邮箱（SC_GRAPH_SENDER）齐备时走 Graph sendMail；两者皆空记 skipped。
    """
    s = get_settings()
    if s.smtp_host:
        return await _send_via_smtp(to, subject, body, cc)
    if graph.credentials_ready() and s.graph_sender:
        return await graph.send_mail(to, subject, body, cc)
    return "skipped"


async def _send_via_smtp(to: str, subject: str, body: str, cc: str = "") -> str:
    s = get_settings()
    to = clean_addresses(to)
    if not to:
        return "failed: no valid recipient address"
    subject = _ADDR_UNSAFE_RE.sub(" ", subject)  # 防御：主题里的换行可构成邮件头注入
    try:
        import aiosmtplib

        m = EmailMessage()
        m["From"] = s.smtp_from
        m["To"] = to
        cc = clean_addresses(cc)
        if cc:
            m["Cc"] = cc
        m["Subject"] = subject
        m.set_content(body)
        refused, _ = await aiosmtplib.send(
            m,
            hostname=s.smtp_host, port=s.smtp_port,
            username=s.smtp_user or None, password=s.smtp_password or None,
            start_tls=s.smtp_starttls, timeout=15,
        )
        if refused:
            codes = ", ".join(str(response.code) for response in refused.values())
            return f"failed: {len(refused)} recipient(s) refused (SMTP {codes}); others may have received the message"
        return "sent"
    except Exception as e:  # noqa: BLE001 — 投递失败必须被记录而不是中断
        log.warning("email delivery failed (%s): %s", subject, e)
        return f"failed: {e}"


async def deliver_email(entry: dict) -> str:
    return await send_email(entry.get("to", ""), f"Follow-up Task for Sourcing Case {entry['swatId']}",
                            entry["message"], entry.get("cc") or "")


async def deliver_teams(entry: dict) -> str:
    s = get_settings()
    # 优先 Graph 直发频道消息（与邮件同一套凭据）；未配团队/频道 ID 时回落 webhook；
    # 两者皆未配置记 skipped。
    if graph.channel_message_ready():
        return await graph.send_channel_message(entry["message"])
    if not s.teams_webhook_url:
        return "skipped"
    if s.teams_webhook_format == "flow":
        payload: dict[str, Any] = {
            "to": entry.get("to", ""),
            "subject": f"Follow-up Task for Sourcing Case {entry['swatId']}",
            "text": entry["message"],
        }
    else:  # teams：频道 Incoming Webhook
        payload = {"text": entry["message"]}
    # Graph 凭据齐备时附带 Bearer：无认证的 "anyone with URL" 触发器会忽略它；
    # 要求租户认证的触发器可直接通过。令牌获取失败不阻断——照常发送，
    # 若触发器确要认证会以 401 记入 failed，结果可见。
    headers: dict[str, str] = {}
    if graph.credentials_ready():
        try:
            headers["Authorization"] = f"Bearer {await graph.access_token()}"
        except Exception as e:  # noqa: BLE001
            log.warning("graph token for teams webhook unavailable: %s", e)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(s.teams_webhook_url, json=payload, headers=headers)
        if not 200 <= resp.status_code < 300:
            return f"failed: HTTP {resp.status_code}"
        return "sent"
    except Exception as e:  # noqa: BLE001
        # httpx 异常文本可能包含 webhook URL 内的凭据，不写入共享日志或 API 快照。
        log.warning("teams delivery failed for %s (%s)", entry.get("swatId"), type(e).__name__)
        return f"failed: {type(e).__name__}"


async def deliver_entry(entry: dict) -> None:
    """按条目自身选择的通道投递，并把结果写进 entry["delivery"]。"""
    channel = entry.get("channel") or "Email + Teams"
    result: dict[str, str] = {}
    if channel in ("Email", "Email + Teams"):
        result["email"] = await deliver_email(entry)
    if channel in ("Teams", "Email + Teams"):
        result["teams"] = await deliver_teams(entry)
    entry["delivery"] = result
