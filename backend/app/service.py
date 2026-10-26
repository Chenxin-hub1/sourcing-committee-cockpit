"""状态装载 / 持久化 / 快照 —— 服务端是唯一事实源。

持久化按行增量写（upsert / 定点删除），并发粒度 = 单个案例行：两个管理员同时编辑
不同案例互不覆盖；同一案例同时编辑仍是后写者胜（小团队下的合理取舍）。
提醒日志只追加新条目并裁剪到上限。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from . import accounts, commodities, logic, owners
from .config import get_settings
from .models import Base, CaseRow, KvRow, ReminderLogRow, SubmissionRow, UserRow

log = logging.getLogger("cockpit.service")

SEED_PATH = Path(__file__).parent / "seed.json"
LOG_CAP = 200
SETTINGS_KEY = "reminder_settings"
FX_KEY = "fx_settings"
REGISTRATION_KEY = "registration_settings"
SESSIONS_KEY = "sessions"
INITIALIZED_KEY = "database_initialized"
CASE_SEQUENCE_KEY = "case_row_sequence"
COMMODITY_KEY = "commodity_vocabulary"  # {"version": N}：已按 commodities.VERSION 归一过术语（v3 Phase-18）
WEEK_NUMBERING_KEY = "week_numbering"  # {"scheme": "iso"}：已换成 ISO 周（v3 Phase-13）
CASE_NUMBERING_KEY = "case_numbering"  # {"scheme": "per-year-week"}：已按年份 + 周整理过案例号（v3 Phase-21）
SESSION_TTL_SECONDS = 7 * 24 * 3600  # 登录 7 天过期：泄露窗口有界，列表不无限增长


async def _kv_doc(session, key: str) -> Any:
    kv = (await session.execute(
        select(KvRow).where(KvRow.key == key).execution_options(populate_existing=True)
    )).scalar_one_or_none()
    return deepcopy(kv.doc) if kv is not None else None


# ---------- 登录会话（v3 Phase-6：个人账号；取代共享口令令牌） ----------
# kv 里存 {tokenHash, email, issued_at} 列表：只存令牌的 SHA-256，库泄露也拿不到可用令牌。
# 7 天过期；登出删一条；改密码 / 重置 / 停用删掉该账号的全部会话。


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _load_sessions(raw) -> list[dict]:
    """过滤出仍在有效期内、结构完整的会话；早期共享口令令牌等旧格式一律丢弃。"""
    now = time.time()
    valid = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("tokenHash"), str) or not isinstance(entry.get("email"), str):
            continue
        try:
            issued_at = float(entry.get("issued_at", 0))
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(issued_at) and 0 <= now - issued_at < SESSION_TTL_SECONDS:
            valid.append(entry)
    return valid


async def issue_session(session, email: str) -> str:
    """签发登录令牌（持久化在 kv，重启不失）；调用方持有写锁。"""
    import secrets

    token = secrets.token_urlsafe(32)
    sessions = _load_sessions(await _kv_doc(session, SESSIONS_KEY))
    sessions.append({"tokenHash": _token_hash(token), "email": email, "issued_at": time.time()})
    await _set_kv(session, SESSIONS_KEY, sessions)
    await session.commit()
    return token


async def revoke_session(session, token: str) -> None:
    sessions = _load_sessions(await _kv_doc(session, SESSIONS_KEY))
    await _set_kv(session, SESSIONS_KEY, [e for e in sessions if e["tokenHash"] != _token_hash(token or "")])
    await session.commit()


async def revoke_user_sessions(session, email: str, keep_token: str = "") -> None:
    """删掉某账号的全部会话（keep_token 除外，如改密码时保留当前这一个）；由调用方提交。"""
    keep = _token_hash(keep_token) if keep_token else ""
    sessions = _load_sessions(await _kv_doc(session, SESSIONS_KEY))
    await _set_kv(session, SESSIONS_KEY, [e for e in sessions if e["email"] != email or e["tokenHash"] == keep])


async def session_user(session, token: str) -> dict | None:
    """令牌对应的账号文档；过期、账号不存在或已停用返回 None。顺手清掉过期会话。"""
    if not token:
        return None
    raw = await _kv_doc(session, SESSIONS_KEY)
    sessions = _load_sessions(raw)
    if raw is not None and sessions != raw:  # 写操作由调用方共享写锁串行化，避免清理覆盖新登录
        await _set_kv(session, SESSIONS_KEY, sessions)
        await session.commit()
    wanted = _token_hash(token)
    entry = next((e for e in sessions if hmac.compare_digest(e["tokenHash"], wanted)), None)
    if entry is None:
        return None
    user = await get_user(session, entry["email"])
    return user if user is not None and not user.get("disabled") else None


# ---------- 账号 ----------


async def get_user(session, email: str) -> dict | None:
    row = (await session.execute(
        select(UserRow).where(UserRow.email == email).execution_options(populate_existing=True)
    )).scalar_one_or_none()
    return deepcopy(row.doc) if row is not None else None


async def save_user(session, doc: dict) -> None:
    row = (await session.execute(select(UserRow).where(UserRow.email == doc["email"]))).scalar_one_or_none()
    if row is None:
        session.add(UserRow(email=doc["email"], doc=deepcopy(doc)))
    else:
        row.doc = deepcopy(doc)


async def list_users(session) -> list[dict]:
    rows = (await session.execute(select(UserRow).order_by(UserRow.email).execution_options(populate_existing=True))).scalars()
    return [deepcopy(r.doc) for r in rows]


async def _ensure_bootstrap_admin(session) -> None:
    """还没有可用的 Sourcing 管理员时，按 SC_BOOTSTRAP_ADMIN_* 建一个（或把同名账号恢复成管理员并重设密码）。"""
    s = get_settings()
    email = accounts.normalize_email(s.bootstrap_admin_email)
    if not email or not s.bootstrap_admin_password:
        return
    if any(u.get("role") == "admin" and not u.get("disabled") for u in await list_users(session)):
        return
    doc = await get_user(session, email) or {"email": email, "name": "Sourcing admin",
                                             "createdAt": logic.fmt_when(logic.na_now()), "lastLoginAt": ""}
    doc.update(role="admin", disabled=False, mustChangePassword=False,
               passwordHash=accounts.hash_password(s.bootstrap_admin_password))
    await save_user(session, doc)
    # 恢复管理员会重置密码；恢复前签发的令牌也应失效，不能随账号恢复重新获得管理员权限。
    await revoke_user_sessions(session, email)


async def _set_kv(session, key: str, doc) -> None:
    kv = (await session.execute(select(KvRow).where(KvRow.key == key))).scalar_one_or_none()
    if kv is None:
        session.add(KvRow(key=key, doc=deepcopy(doc)))
    else:
        kv.doc = deepcopy(doc)


async def load_state(session) -> dict[str, Any]:
    """从库装载全部状态；log 携带内部 _seq 标记（快照时剥离）。"""
    cases = [deepcopy(row.doc) for row in (await session.execute(
        select(CaseRow).order_by(CaseRow.id).execution_options(populate_existing=True)
    )).scalars()]
    submissions = [deepcopy(row.doc) for row in (await session.execute(
        select(SubmissionRow).order_by(SubmissionRow.sub_id).execution_options(populate_existing=True)
    )).scalars()]
    log_rows = (await session.execute(
        select(ReminderLogRow).order_by(ReminderLogRow.seq.desc()).execution_options(populate_existing=True)
    )).scalars().all()
    log = [{**deepcopy(row.doc), "_seq": row.seq} for row in log_rows]
    settings_doc = await _kv_doc(session, SETTINGS_KEY)
    settings: dict[str, Any] = dict(logic.REMINDER_DEFAULTS)
    if settings_doc is not None:
        settings.update(settings_doc or {})
    fx = {**logic.FX_DEFAULTS, **logic.normalize_fx_settings(await _kv_doc(session, FX_KEY) or {})}
    registration = {**logic.REGISTRATION_DEFAULTS, **(await _kv_doc(session, REGISTRATION_KEY) or {})}
    return {"cases": cases, "submissions": submissions, "log": log, "settings": settings, "fx": fx,
            "registration": registration}


def public_submission(sub: dict) -> dict:
    """下发给浏览器的提交单：去掉上传密钥的哈希（快照所有人都能拿到）。"""
    return {k: v for k, v in sub.items() if k != "uploadKeyHash"}


def snapshot(state: dict[str, Any]) -> dict[str, Any]:
    """给前端的完整快照：整体替换 ALL_CASES / SUBMISSIONS / AUTO_LOG / REMINDER_SETTINGS。

    serverTimezone：前端 getNATime 跟随服务器 SC_TIMEZONE，保证"今天"的判断两端一致。
    """
    return {
        "cases": state["cases"],
        "submissions": [public_submission(sub) for sub in state["submissions"]],
        "reminderSettings": state["settings"],
        "fxSettings": state.get("fx", logic.FX_DEFAULTS),
        "registrationSettings": state.get("registration", logic.REGISTRATION_DEFAULTS),
        "autoLog": [{k: v for k, v in e.items() if k != "_seq"} for e in state["log"]],
        "serverTimezone": get_settings().timezone,
        # v3 Phase-18：待办分类关键词与职能建议，编辑页实时预览用同一套规则
        "taskRules": logic.task_rules(),
    }


def _case_values(c: dict) -> dict:
    return {"swat_id": c.get("swatId", ""), "week_num": int(c.get("weekNum") or 0),
            "case_number": int(c.get("caseNumber") or 0), "doc": deepcopy(c)}


async def upsert_case(session, case: dict) -> None:
    """按行写单个案例：存在即更新，不存在即插入。"""
    row = (await session.execute(select(CaseRow).where(CaseRow.id == case["id"]))).scalar_one_or_none()
    values = _case_values(case)
    if row is None:
        session.add(CaseRow(id=case["id"], **values))
    else:
        for k, v in values.items():
            setattr(row, k, v)


async def insert_cases(session, cases: list[dict]) -> None:
    """保留持久化的最大行号，避免删除后复用旧案例链接所指向的记录。"""
    if not cases:
        return
    ceiling = await _case_id_ceiling(session)
    for c in cases:
        number = int(c["id"][1:])
        if number <= ceiling:
            number = ceiling + 1
            c["id"] = f"C{number:04d}"
        ceiling = number
        session.add(CaseRow(id=c["id"], **_case_values(c)))
    await _set_kv(session, CASE_SEQUENCE_KEY, {"last": ceiling})


async def _case_id_ceiling(session) -> int:
    stored = await _kv_doc(session, CASE_SEQUENCE_KEY)
    ids = (await session.execute(select(CaseRow.id))).scalars().all()
    numbers = [int(row_id[1:]) for row_id in ids if row_id.startswith("C") and row_id[1:].isdigit()]
    return max([int((stored or {}).get("last", 0)), *numbers])


async def delete_cases_by_ids(session, ids: list[str]) -> None:
    """按行 id 删（Excel 重新导入同一周时替换上次导入的案例）；序号上限先保存，行号不复用。"""
    if not ids:
        return
    await _set_kv(session, CASE_SEQUENCE_KEY, {"last": await _case_id_ceiling(session)})
    await session.execute(delete(CaseRow).where(CaseRow.id.in_(ids)))


async def delete_cases_by_swat(session, swat_id: str) -> None:
    # 升级前的数据库没有序号记录；首次删除前先保存当前上限。
    await _set_kv(session, CASE_SEQUENCE_KEY, {"last": await _case_id_ceiling(session)})
    await session.execute(delete(CaseRow).where(CaseRow.swat_id == swat_id))


async def upsert_submission(session, sub: dict) -> None:
    row = (await session.execute(select(SubmissionRow).where(SubmissionRow.sub_id == sub["subId"]))).scalar_one_or_none()
    if row is None:
        session.add(SubmissionRow(sub_id=sub["subId"], status=sub.get("status", ""), doc=deepcopy(sub)))
    else:
        row.status = sub.get("status", "")
        row.doc = deepcopy(sub)


async def update_submission_notification(session, sub_id: str, notify: dict) -> dict | None:
    """只回填通知结果，保留邮件发送期间发生的审批状态与删除变更。"""
    row = (await session.execute(
        select(SubmissionRow).where(SubmissionRow.sub_id == sub_id).execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if row is None:
        return None
    row.doc = {**deepcopy(row.doc), "notify": deepcopy(notify)}
    return deepcopy(row.doc)


async def update_submission_sharepoint(session, sub_id: str, record: dict) -> dict | None:
    """只回填 SharePoint 建单结果，保留建单网络等待期间发生的其他变更。"""
    row = (await session.execute(
        select(SubmissionRow).where(SubmissionRow.sub_id == sub_id).execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if row is None:
        return None
    row.doc = {**deepcopy(row.doc), "sharepoint": deepcopy(record)}
    return deepcopy(row.doc)


async def set_task_last_delivery(
    session, case_row_id: str, task_id: str, delivery: dict, *, expected_reminder_id: str | None = None,
) -> None:
    """外发完成后回填某个任务的 lastReminder.delivery（外发本身不占用数据库会话）。"""
    row = (await session.execute(
        select(CaseRow).where(CaseRow.id == case_row_id).execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if row is None:
        return
    doc = deepcopy(row.doc or {})  # 嵌套对象也必须复制，否则新旧 JSON 相等，ORM 不会写入
    for t in doc.get("followUps") or []:
        if t.get("id") == task_id and t.get("lastReminder"):
            if expected_reminder_id is not None and t["lastReminder"].get("id") != expected_reminder_id:
                continue
            t["lastReminder"]["delivery"] = deepcopy(delivery)
    row.doc = doc


async def persist_log(session, log: list[dict]) -> None:
    """只插入没有 _seq 的新条目，再裁剪到 LOG_CAP（最旧先删）。"""
    for e in log:
        if "_seq" not in e:
            session.add(ReminderLogRow(doc=e))
    seqs = (await session.execute(select(ReminderLogRow.seq).order_by(ReminderLogRow.seq.desc()))).scalars().all()
    for seq in seqs[LOG_CAP:]:
        await session.execute(delete(ReminderLogRow).where(ReminderLogRow.seq == seq))


async def update_log_delivery(session, entries: list[dict]) -> None:
    """按条目自身的 id 把投递结果回填进日志行（没有 id 的历史条目跳过）。"""
    by_id = {e["id"]: e for e in entries if e.get("id") and e.get("delivery")}
    if not by_id:
        return
    rows = (await session.execute(select(ReminderLogRow))).scalars().all()
    for row in rows:
        entry = by_id.get((row.doc or {}).get("id"))
        if entry is not None:
            row.doc = {**row.doc, "delivery": entry["delivery"]}


async def persist_fx(session, fx: dict) -> None:
    await _set_kv(session, FX_KEY, fx)


async def convert_legacy_usd(session, fx_snapshot: dict, *, apply: bool) -> dict[str, int]:
    """v3 Phase-12：没有 spendCurrency 的案例行与提交单（旧美元数据）换算成欧元。

    apply=False 只统计不改；apply=True 改在会话里，由调用方提交。"""
    when = logic.fmt_when(logic.na_now())
    counts = {"cases": 0, "submissions": 0}
    for model, key in ((CaseRow, "cases"), (SubmissionRow, "submissions")):
        for row in (await session.execute(select(model))).scalars():
            doc = deepcopy(row.doc)
            if logic.convert_legacy_record(doc, fx_snapshot, when):
                counts[key] += 1
                if apply:
                    row.doc = doc
    return counts


async def persist_registration(session, registration: dict) -> None:
    await _set_kv(session, REGISTRATION_KEY, registration)


async def persist_settings(session, settings: dict) -> None:
    kv = (await session.execute(select(KvRow).where(KvRow.key == SETTINGS_KEY))).scalar_one_or_none()
    if kv is None:
        session.add(KvRow(key=SETTINGS_KEY, doc=settings))
    else:
        kv.doc = dict(settings)


async def init_db(session) -> None:
    """建表；仅首次初始化且所有业务表为空时装载演示数据；再做尚未做过的一次性数据换算。"""
    async with session.bind.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    if await _kv_doc(session, INITIALIZED_KEY) is None:
        has_data = False
        for model in (CaseRow, SubmissionRow, ReminderLogRow, KvRow):
            if (await session.execute(select(model).limit(1))).first() is not None:
                has_data = True
                break
        seeded = get_settings().seed_on_empty and not has_data
        if seeded:
            data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
            await insert_cases(session, data["cases"])
            for sub in data["submissions"]:
                await upsert_submission(session, sub)
        await _set_kv(session, INITIALIZED_KEY, {"seeded": seeded})
    await _migrate_iso_weeks(session)
    await _migrate_commodities(session)
    await _migrate_case_numbers(session)
    await _ensure_bootstrap_admin(session)
    await _refresh_owners(session)
    await session.commit()


async def _migrate_iso_weeks(session) -> None:
    """v3 Phase-13：案例周号从模板周换成 ISO 周（KW），只做一次（演示数据刚装载时也在这里换）。

    案例按 logic.iso_week_of_record 重算（索引列 week_num 一起改）；提交单有会议日期的重算 meetingWeekNum。"""
    if (await _kv_doc(session, WEEK_NUMBERING_KEY) or {}).get("scheme") == "iso":
        return
    for row in (await session.execute(select(CaseRow))).scalars():
        doc = deepcopy(row.doc)
        doc["weekNum"] = logic.iso_week_of_record(doc)
        row.doc, row.week_num = doc, doc["weekNum"]
    for row in (await session.execute(select(SubmissionRow))).scalars():
        if logic.ISO_DATE_RE.match(row.doc.get("meetingDateISO") or ""):
            row.doc = {**row.doc, "meetingWeekNum": logic.iso_week_of_record({"meetingDateISO": row.doc["meetingDateISO"]})}
    await _set_kv(session, WEEK_NUMBERING_KEY, {"scheme": "iso"})


async def _migrate_case_numbers(session) -> None:
    """v3 Phase-21：一次性把每个"年份 + 周"的案例号整理成从 1 开始的连续号。

    之前确认登记只看周号，2026-KW42 接着 2025-KW42 的历史从 4 号排起；之后删除 / 改周时各自补号，不再需要重跑。
    只整理含有系统内登记案例的周：全部从 Excel 导入的周保持原件编号（周会 Excel 本身可能跳号，如 2026-KW39 没有 6 号）。"""
    if (await _kv_doc(session, CASE_NUMBERING_KEY) or {}).get("scheme") == "per-year-week":
        return
    rows = {row.id: row for row in (await session.execute(select(CaseRow))).scalars()}
    cases = [deepcopy(row.doc) for row in rows.values()]
    before = {c["id"]: c.get("caseNumber") for c in cases}
    registered = {logic.year_week(c) for c in cases if (c.get("source") or {}).get("kind") != "excel"}
    for c in logic.renumber_weeks(cases, registered):
        row = rows[c["id"]]
        row.doc, row.case_number = c, int(c["caseNumber"])
        # warning 级：uvicorn 只输出 warning 及以上，一次性改数据要在 docker logs 里留痕
        log.warning("case number %s %s: #%s -> #%s", logic.week_label(c), c.get("swatId"), before[c["id"]], c["caseNumber"])
    await _set_kv(session, CASE_NUMBERING_KEY, {"scheme": "per-year-week"})


async def _refresh_owners(session) -> None:
    """v3 Phase-29：每次启动重算待办负责人的全名，并给职能空着、但这个人职能已知的待办补上（幂等，只写改了的案例）。"""
    rows = {row.id: row for row in (await session.execute(select(CaseRow))).scalars()}
    cases = [deepcopy(row.doc) for row in rows.values()]
    for c in owners.refresh(cases, owners.account_names(await list_users(session))):
        rows[c["id"]].doc = c


def normalize_commodities(cases: list[dict]) -> list[dict]:
    """v3 Phase-18：按 commodities 词表重算从 Excel 导入的案例（以及 Cluster 不在固定三项里的案例）的
    cluster / commodity / commodityRaw。返回改动了的案例（原文 commodityRaw 一直保留，词表改了可以再算）。"""
    changed: list[dict] = []
    for c in cases:
        imported = (c.get("source") or {}).get("kind") == "excel"
        if not imported and c.get("cluster") in commodities.CLUSTERS and not c.get("commodityRaw"):
            continue  # 在线登记的案例：Cluster 本来就是固定项
        before = (c.get("cluster"), c.get("commodity"), c.get("commodityRaw"))
        commodities.apply(c)
        if before != (c.get("cluster"), c.get("commodity"), c.get("commodityRaw")):
            changed.append(c)
    return changed


async def _migrate_commodities(session) -> None:
    """词表版本变了（或从未归一过）就重算一遍，写回改动的案例。"""
    if (await _kv_doc(session, COMMODITY_KEY) or {}).get("version") == commodities.VERSION:
        return
    for row in (await session.execute(select(CaseRow))).scalars():
        doc = deepcopy(row.doc)
        if normalize_commodities([doc]):
            row.doc = doc
    await _set_kv(session, COMMODITY_KEY, {"version": commodities.VERSION})
