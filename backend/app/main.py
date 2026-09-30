"""Seat Belt Sourcing Committee Cockpit —— API + 静态前端。

约定：所有写端点返回 {ok, snapshot[, ...]}，前端整体替换内存态后重渲染；
校验失败返回 422 {detail}，文案与模板一致，前端映射到模板既有错误展示位。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
import secrets
import time
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.staticfiles import StaticFiles

from . import accounts, delivery, excel_import, exports, feedback, files, graph, logic, service
from .config import get_settings
from .db import SessionLocal
from .schemas import (
    COMMERCIAL_INPUT_FIELDS,
    CaseEditIn,
    ExportSelectionIn,
    FeedbackDecisionIn,
    FeedbackIn,
    FxSettingsIn,
    LibraryImportIn,
    LoginIn,
    ManualReminderIn,
    PasswordChangeIn,
    RegisterIn,
    RegistrationSettingsIn,
    RejectIn,
    ReminderSettingsIn,
    SubmissionIn,
    UserUpdateIn,
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
STATIC_DIR = Path(__file__).parent / "static"

log = logging.getLogger("cockpit.main")

# 写路径进程内互斥：所有"读-改-写"端点串行执行，并发提交不再撞 SUB 编号或整行覆盖。
# 与 SQLite 单写者的天性匹配；网络外发一律在锁外（见 _run_check_if_due）。
_write_lock = asyncio.Lock()


# ============================= 生命周期：建表 / 种子 / 每小时每日检查 =============================


async def _run_check_if_due(session, *, force: bool = False) -> bool:
    """跑每日提醒检查（参考时区日期守卫），并对新产生的日志条目执行真实投递。

    顺序刻意为之：状态计算与落库在 _write_lock 内（与其他写端点互斥），网络 I/O
    （SMTP/webhook 单通道最长 15s，条目多时可达分钟级）在锁外，最后短事务回填投递
    结果 —— 长外发既不阻塞其他写入，失败也不会丢状态或导致下一小时整批重发。
    """
    fresh: list[dict] = []
    async with _write_lock:
        state = await service.load_state(session)
        if not force and state["settings"].get("lastRunDate") == logic.today_iso():
            return False
        result = logic.run_daily_reminder_check(state["cases"], state["settings"], state["log"],
                                                force=force, base_url=get_settings().public_url)
        fresh = [e for e in state["log"] if "_seq" not in e]  # 本次检查新产生的条目
        cases_by_id = {c["id"]: c for c in state["cases"]}
        for cid in result["changed"]:
            await service.upsert_case(session, cases_by_id[cid])
        await service.persist_log(session, state["log"])
        await service.persist_settings(session, state["settings"])
        await session.commit()
    if fresh:
        for entry in fresh:
            await delivery.deliver_entry(entry)
        async with _write_lock, SessionLocal() as s2:
            await service.update_log_delivery(s2, fresh)
            await s2.commit()
    return True


async def _hourly_loop() -> None:
    while True:
        await asyncio.sleep(3600)
        try:
            async with SessionLocal() as session:
                await _run_check_if_due(session)
        except Exception:
            log.exception("hourly reminder check failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with SessionLocal() as session:
        await service.init_db(session)
        await _run_check_if_due(session)
    task = asyncio.create_task(_hourly_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Seat Belt Sourcing Committee Cockpit", lifespan=lifespan)


# ============================= 管理员门禁 =============================


# 登录限流（进程内，按客户端 IP）：15 分钟滑动窗口内失败 5 次 → 锁 5 分钟 —— 内网防爆破的最低门槛。
# 存失败时间戳列表而非裸计数器：两周前的口误不该算进今天的窗口（办公室 NAT 下全组共享一个 IP，尤甚）。
LOGIN_FAIL_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILS = 5
LOGIN_LOCK_SECONDS = 300
_login_failures: dict[str, dict] = {}  # ip -> {"fails": [timestamps], "locked_until": float}


def _prune_login_failures() -> None:
    """清掉不在锁定期、且窗口内已无失败记录的条目 —— 长期运行字典不无界增长。"""
    now = time.time()
    stale = [ip for ip, v in _login_failures.items()
             if v.get("locked_until", 0) <= now
             and all(now - t >= LOGIN_FAIL_WINDOW_SECONDS for t in v.get("fails", []))]
    for ip in stale:
        _login_failures.pop(ip, None)


def _login_remaining_lock(ip: str) -> int:
    """该 IP 的剩余锁定秒数（0 = 未锁定）。"""
    _prune_login_failures()
    rec = _login_failures.get(ip)
    if rec and rec.get("locked_until", 0) > time.time():
        return max(1, math.ceil(rec["locked_until"] - time.time()))
    return 0


def _login_record_failure(ip: str) -> None:
    now = time.time()
    rec = _login_failures.setdefault(ip, {"fails": [], "locked_until": 0})
    rec["fails"] = [t for t in rec["fails"] if now - t < LOGIN_FAIL_WINDOW_SECONDS]  # 只统计窗口内
    rec["fails"].append(now)
    if len(rec["fails"]) >= LOGIN_MAX_FAILS:
        rec["locked_until"] = now + LOGIN_LOCK_SECONDS
        rec["fails"] = []


# 提交接口限流（进程内，按客户端 IP）：1 小时滑动窗口内最多 10 条成功提交 —— 防内网误灌与脚本误循环。
# 只计成功（校验失败的 422 不计数，打错字不该把人锁住）；与登录限流同款进程内实现。
SUBMIT_MAX_PER_WINDOW = 10
SUBMIT_WINDOW_SECONDS = 3600
_submission_times: dict[str, list[float]] = {}  # ip -> 成功提交时间戳列表


def _submission_allowed(ip: str) -> bool:
    now = time.time()
    for key, entries in list(_submission_times.items()):
        if not entries or now - entries[-1] >= SUBMIT_WINDOW_SECONDS:
            _submission_times.pop(key, None)
    times = [t for t in _submission_times.get(ip, []) if now - t < SUBMIT_WINDOW_SECONDS]
    if not times:
        _submission_times.pop(ip, None)  # 窗口外无记录 → 清键，字典不膨胀
    else:
        _submission_times[ip] = times
    return len(times) < SUBMIT_MAX_PER_WINDOW


def _submission_record(ip: str) -> None:
    _submission_times.setdefault(ip, []).append(time.time())


# 注册限流（进程内，按客户端 IP）：1 小时最多 10 个新账号 —— 防脚本批量注册
REGISTER_MAX_PER_WINDOW = 10
_register_times: dict[str, list[float]] = {}


def _register_allowed(ip: str) -> bool:
    now = time.time()
    times = [t for t in _register_times.get(ip, []) if now - t < SUBMIT_WINDOW_SECONDS]
    _register_times[ip] = times
    return len(times) < REGISTER_MAX_PER_WINDOW


async def current_user(x_session_token: str | None = Header(default=None)) -> dict | None:
    """请求头里的登录令牌 → 账号文档（未登录 / 过期 / 已停用为 None）。调用方不能持有 _write_lock。"""
    if not x_session_token:
        return None
    async with _write_lock, SessionLocal() as session:
        return await service.session_user(session, x_session_token)


CurrentUser = Annotated[dict | None, Depends(current_user)]


def require_role(role: str):
    """按角色把门（服务端强制，前端隐藏按钮只是附加层）：未登录 401，角色不够 403。"""
    async def dependency(user: CurrentUser) -> dict:
        if user is None:
            raise HTTPException(401, "Please log in.")
        if user.get("mustChangePassword"):
            raise HTTPException(403, "Please change your temporary password first.")
        if accounts.RANK.get(user.get("role", "user"), 0) < accounts.RANK[role]:
            raise HTTPException(403, f"This needs the {accounts.ROLE_LABELS[role]} role. Ask the Sourcing admin if you need it.")
        return user
    return dependency


require_login = require_role("user")
require_manager = require_role("npi_manager")  # NPI 经理与 Sourcing 管理员
require_admin = require_role("admin")          # 只有 Sourcing 管理员：系统设置与账号
LoggedIn = Annotated[dict, Depends(require_login)]
Manager = Annotated[dict, Depends(require_manager)]
Admin = Annotated[dict, Depends(require_admin)]


PASSWORD_REQUIRED = "Password required."  # 前端据此文案展开密码框（管理员账号）


def _session_response(token: str, user: dict) -> dict:
    return {"ok": True, "token": token, "user": accounts.public_user(user)}


@app.post("/api/auth/register")
async def register(b: RegisterIn, request: Request) -> dict:
    """公司邮箱自注册（v3 Phase-16 起不设密码）：新账号默认普通用户，注册即登录。"""
    ip = request.client.host if request.client else "unknown"
    email = accounts.normalize_email(b.email)
    problem = (accounts.email_problem(email, accounts.allowed_domains(get_settings().allowed_email_domains))
               or ("Please enter your name." if not b.name.strip() else None))
    if problem:
        raise HTTPException(422, problem)
    async with _write_lock, SessionLocal() as session:
        if not _register_allowed(ip):
            raise HTTPException(429, "Too many new accounts from this network in the last hour. Please try again later.")
        if await service.get_user(session, email) is not None:
            raise HTTPException(409, "An account with this email already exists — just log in with it.")
        now = logic.fmt_when(logic.na_now())
        user = {"email": email, "name": b.name.strip(), "role": "user", "disabled": False, "mustChangePassword": False,
                "createdAt": now, "lastLoginAt": now}
        await service.save_user(session, user)
        _register_times.setdefault(ip, []).append(time.time())
        token = await service.issue_session(session, email)  # 内含提交
    return _session_response(token, user)


@app.post("/api/auth/login")
async def login(b: LoginIn, request: Request) -> dict:
    ip = request.client.host if request.client else "unknown"
    remaining = _login_remaining_lock(ip)
    if remaining:
        raise HTTPException(429, f"Too many failed login attempts. Try again in {max(1, remaining // 60)} minute(s).")
    email = accounts.normalize_email(b.email)
    async with _write_lock, SessionLocal() as session:
        user = await service.get_user(session, email)
    if user is None:
        _login_record_failure(ip)
        raise HTTPException(401, "No account with this email yet — register first (Register tab), it only takes your name.")
    # v3 Phase-16：只有 Sourcing 管理员用密码；其他角色凭邮箱直接登录
    if user.get("role") == "admin":
        if not b.password:
            raise HTTPException(401, PASSWORD_REQUIRED)
        if not accounts.verify_or_dummy(b.password, user.get("passwordHash")):
            _login_record_failure(ip)
            raise HTTPException(401, "Wrong email or password.")
    if user.get("disabled"):
        raise HTTPException(403, "This account is disabled. Ask the Sourcing admin to re-enable it.")
    _login_failures.pop(ip, None)
    async with _write_lock, SessionLocal() as session:
        user["lastLoginAt"] = logic.fmt_when(logic.na_now())
        await service.save_user(session, user)
        token = await service.issue_session(session, email)
    return _session_response(token, user)


@app.post("/api/auth/logout")
async def logout(x_session_token: str | None = Header(default=None)) -> dict:
    async with _write_lock, SessionLocal() as session:
        await service.revoke_session(session, x_session_token or "")
    return {"ok": True}


@app.post("/api/auth/password")
async def change_password(b: PasswordChangeIn, x_session_token: str | None = Header(default=None),
                          user: CurrentUser = None) -> dict:
    """本人改密码（临时密码登录后必须先走这里）；别处登录的会话一并失效，当前这个保留。"""
    if user is None:
        raise HTTPException(401, "Please log in.")
    if user.get("role") != "admin":
        raise HTTPException(403, "Only Sourcing admins have a password — everyone else logs in with their email.")
    if not accounts.verify_password(b.currentPassword, user.get("passwordHash", "")):
        raise HTTPException(422, "The current password is not correct.")
    problem = accounts.password_problem(b.newPassword, user["email"])
    if problem or b.newPassword == b.currentPassword:
        raise HTTPException(422, problem or "Choose a new password that differs from the current one.")
    async with _write_lock, SessionLocal() as session:
        user.update(passwordHash=accounts.hash_password(b.newPassword), mustChangePassword=False)
        await service.save_user(session, user)
        await service.revoke_user_sessions(session, user["email"], keep_token=x_session_token or "")
        await session.commit()
    return {"ok": True, "user": accounts.public_user(user)}


# ---------- 账号管理（只有 Sourcing 管理员） ----------


async def _users_response(session) -> dict:
    return {"ok": True, "users": [accounts.public_user(u) for u in await service.list_users(session)]}


@app.get("/api/users", dependencies=[Depends(require_admin)])
async def list_accounts() -> dict:
    async with _write_lock, SessionLocal() as session:
        return await _users_response(session)


@app.put("/api/users/{email}", dependencies=[Depends(require_admin)])
async def update_account(email: str, b: UserUpdateIn) -> dict:
    """改角色 / 停用启用。至少留一个可用的 Sourcing 管理员，防止把自己锁在门外。"""
    async with _write_lock, SessionLocal() as session:
        user = await service.get_user(session, accounts.normalize_email(email))
        if user is None:
            raise HTTPException(404, "Account not found.")
        updated = {**user, **b.model_dump(exclude_unset=True)}
        users = [updated if u["email"] == user["email"] else u for u in await service.list_users(session)]
        if not any(u.get("role") == "admin" and not u.get("disabled") for u in users):
            raise HTTPException(422, "Keep at least one active Sourcing admin — promote someone else first.")
        temporary = None
        if updated.get("role") == "admin" and user.get("role") != "admin":
            # v3 Phase-16：管理员必须有密码 —— 提升时发一个临时密码（只显示这一次），本人首次登录后必须改
            temporary = accounts.temporary_password()
            updated.update(passwordHash=accounts.hash_password(temporary), mustChangePassword=True)
        elif updated.get("role") != "admin":
            updated["mustChangePassword"] = False  # 非管理员不用密码，也就不会被"先改密码"拦住
        await service.save_user(session, updated)
        if updated.get("disabled"):
            await service.revoke_user_sessions(session, updated["email"])
        await session.commit()
        response = await _users_response(session)
        return {**response, "temporaryPassword": temporary} if temporary else response


@app.post("/api/users/{email}/reset-password", dependencies=[Depends(require_admin)])
async def reset_account_password(email: str) -> dict:
    """管理员忘记密码（还没有邮件通道）：生成临时密码只显示一次，本人登录后必须先改。只有管理员账号有密码。"""
    async with _write_lock, SessionLocal() as session:
        user = await service.get_user(session, accounts.normalize_email(email))
        if user is None:
            raise HTTPException(404, "Account not found.")
        if user.get("role") != "admin":
            raise HTTPException(422, "Only Sourcing admins have a password — this account logs in with its email.")
        temporary = accounts.temporary_password()
        user.update(passwordHash=accounts.hash_password(temporary), mustChangePassword=True)
        await service.save_user(session, user)
        await service.revoke_user_sessions(session, user["email"])
        await session.commit()
        return {**(await _users_response(session)), "temporaryPassword": temporary}


# ============================= 读路径 =============================


@app.get("/api/health")
async def health() -> dict:
    """容器健康检查专用 —— 轻量：不碰数据库，也不触发每日检查。"""
    return {"ok": True}


@app.get("/api/bootstrap")
async def bootstrap(x_session_token: str | None = Header(default=None)) -> dict:
    async with SessionLocal() as session:
        await _run_check_if_due(session)
        async with _write_lock:
            state = await service.load_state(session)
            snap = service.snapshot(state)
            user = await service.session_user(session, x_session_token or "")
            snap["currentUser"] = accounts.public_user(user) if user else None
            snap["allowedEmailDomains"] = accounts.allowed_domains(get_settings().allowed_email_domains)
            return snap


# ============================= 提交与登记 =============================


def _validate_submission(cases: list[dict], submissions: list[dict], b: SubmissionIn) -> dict:
    """提交门禁 —— 文案与模板 showError 完全一致。"""
    if not (b.submitterName.strip() and b.submitterEmail.strip()):
        raise HTTPException(422, "⚠ Please fill in Name and Email before submitting.")
    if not b.partNumbers or any(not p.partNumber.strip() or not p.partDescription.strip() for p in b.partNumbers):
        raise HTTPException(422, "⚠ Please fill in Part Number and Part Description for every part number row before submitting.")
    # v3 Phase-15：项目 / 寻源类型 / 推荐供应商按零件行（行上留空沿用案例级值）
    rows_error = logic.bundle_rows_error(logic.bundle_rows([p.model_dump() for p in b.partNumbers], b.model_dump()))
    if rows_error:
        raise HTTPException(422, rows_error)
    # v3 Phase-15：金额按整个 bundle 填一个，必填
    if b.peakYearSpend <= 0 or b.lifetimeSpend <= 0:
        raise HTTPException(422, "⚠ Please enter the bundle Peak Year Spend and Lifetime Spend (the total for all part numbers) before submitting.")
    if not b.region:
        raise HTTPException(422, "⚠ Please select at least one Region before submitting.")
    # 会议日期是登记截止门禁的依据：留空或非周三都不能绕过（提交页只会给周三）
    if not b.meetingDateISO:
        raise HTTPException(422, "⚠ Please choose the committee meeting date before submitting.")
    if date.fromisoformat(b.meetingDateISO).weekday() != logic.MEETING_WEEKDAY:
        raise HTTPException(422, "⚠ The Sourcing Committee meets on Wednesdays — choose a Wednesday as the meeting date.")
    st = logic.case_no_status(cases, b.caseNo)
    if st is None:
        raise HTTPException(422, "⚠ Please enter the SWAT Case # or Supplyon Case #. Every case has one — it is required.")
    if any(x.get("caseId") == st["id"] and x.get("status") == "Waiting for Registration Confirmation" for x in submissions):
        raise HTTPException(422, f"⚠ {st['id']} already has a registration waiting for confirmation. "
                                 "Please wait for that one to be processed.")
    if not b.isFamilyCase:
        raise HTTPException(422, '⚠ Please answer "Is this a Family Case?" before submitting.')
    if not b.involvesECM:
        raise HTTPException(422, '⚠ Please answer "Does this case involve an Engineering Change (ECM)?" before submitting.')
    if b.isFamilyCase == "Yes":
        if not b.familyAligned:
            raise HTTPException(422, "⚠ Please answer whether Family Alignment has been completed.")
        if b.familyAligned == "No":
            raise HTTPException(422, "⚠ This case cannot be registered until Family Alignment is completed.")
    if b.involvesECM == "Yes":
        if not b.ccbApproved:
            raise HTTPException(422, "⚠ Please answer whether this case has passed CCB2.")
        if b.ccbApproved == "No":
            raise HTTPException(422, "⚠ This case cannot be registered until it has passed CCB2 (Change Control Board 2).")
    return st


def _late_registration(registration: dict, b: SubmissionIn) -> dict | None:
    """登记截止门禁：截止后提交该周会议日期 → 422；申请例外且有理由 → 返回标记，随登记单进审批队列。"""
    if not b.meetingDateISO:
        return None
    meeting = date.fromisoformat(b.meetingDateISO)
    if logic.registration_open(meeting, registration):
        return None
    deadline = logic.cutoff_moment_label(meeting, registration)
    if not b.lateException:
        raise HTTPException(422, f"⚠ Registration for the {b.meetingDateLabel or b.meetingDateISO} meeting closed on {deadline} "
                                 f"(registrations close {logic.cutoff_label(registration)}). Choose a later meeting date, "
                                 "or tick \"Request an exception\" and give the reason for the Sourcing admin.")
    if not b.lateReason.strip():
        raise HTTPException(422, "⚠ Please give the reason for the late registration, so the Sourcing admin can approve the exception.")
    return {"reason": b.lateReason.strip(), "deadline": deadline}


@app.post("/api/submissions")
async def create_submission(b: SubmissionIn, request: Request, user: LoggedIn) -> dict:
    ip = request.client.host if request.client else "unknown"
    # v3 Phase-6：提交人就是登录的账号（请求里的姓名 / 邮箱不作数，防止冒名）
    b.submitterName, b.submitterEmail = user["name"], user["email"]
    async with SessionLocal() as session, _write_lock:
        if not _submission_allowed(ip):
            raise HTTPException(429, "Too many submissions from this network in the last hour. Please try again later.")
        state = await service.load_state(session)
        st = _validate_submission(state["cases"], state["submissions"], b)
        fx = logic.fx_rate(state["fx"], b.currency)
        if fx is None:
            raise HTTPException(422, f"⚠ No exchange rate is set for {b.currency} yet. Enter the amounts in EUR, "
                                     f"or ask the Sourcing admin to set the {b.currency} rate.")
        rows = logic.bundle_rows([p.model_dump() for p in b.partNumbers], b.model_dump())
        spend = logic.convert_spend(rows, fx, b.peakYearSpend, b.lifetimeSpend)
        commercial_error = logic.validate_commercial(b.model_dump(), spend["lifetimeSpend"])
        if commercial_error:
            raise HTTPException(422, commercial_error)
        late = _late_registration(state["registration"], b)
        pns = spend["partNumbers"]
        summary = logic.bundle_summary(pns)
        sub = {
            "subId": logic.next_sub_id(state["submissions"]),
            "submittedAt": logic.fmt_submitted_at(logic.na_now()),
            "submitterName": b.submitterName.strip(), "submitterEmail": b.submitterEmail.strip(),
            "status": "Waiting for Registration Confirmation", "rejectReason": "",
            "caseId": st["id"], "existingSwatId": st["id"] if st["existing"] else "",
            "priorEntries": st["priorEntries"],
            "partNumbers": pns,
            "partNumber": pns[0]["partNumber"] if pns else "",
            "partDescription": pns[0]["partDescription"] if pns else "",
            "region": b.region, "project": summary["project"], "family": b.family, "cluster": b.cluster,
            "parentPF": b.parentPF, "partFamilyCode": b.partFamilyCode,
            "sourcingType": summary["sourcingType"], "recommendedSupplier": summary["recommendedSupplier"],
            "presenter": b.submitterName.strip(), "decisionLevel": b.decisionLevel,
            # 金额存欧元；原币合计与所用汇率一并保存，之后改汇率不影响这条记录
            "peakYearSpend": spend["peakYearSpend"], "lifetimeSpend": spend["lifetimeSpend"], "leadTime": "",
            "peakYearSpendEntered": spend["peakYearSpendEntered"],
            "lifetimeSpendEntered": spend["lifetimeSpendEntered"],
            "spendCurrency": "EUR",
            "fx": {"currency": b.currency, "perEur": logic.rate_text(fx.per_eur),
                   "basis": state["fx"].get("basis", "") if b.currency != "EUR" else ""},
            "committeeDiscussion": b.comments,
            "meetingDateLabel": b.meetingDateLabel or None,
            "meetingDateISO": b.meetingDateISO,
            "meetingWeekNum": b.meetingWeekNum,
            "isFamilyCase": b.isFamilyCase, "familyAligned": b.familyAligned or "—",
            "involvesECM": b.involvesECM, "ccbApproved": b.ccbApproved or "—",
            **logic.commercial_fields(b.model_dump(), fx),
        }
        logic.sync_row_commercial(sub, pns)
        # 提交人给这条登记上传演示文件的一次性密钥：只存哈希，明文只在本次响应里给提交人
        upload_key = secrets.token_urlsafe(24)
        sub["uploadKeyHash"] = hashlib.sha256(upload_key.encode()).hexdigest()
        if late:
            sub["lateRegistration"] = late
        state["submissions"].append(sub)
        await service.upsert_submission(session, sub)
        await session.commit()
        _submission_record(ip)
        snap = service.snapshot(state)
    # SharePoint 建单：网络在写锁外（提交高峰不被拖住），结果短事务回填
    sub, snap = await _create_sharepoint_record(sub)
    return {"ok": True, "subId": sub["subId"], "uploadKey": upload_key, "snapshot": snap}


def _find_sub(state: dict, sub_id: str) -> dict:
    sub = next((s for s in state["submissions"] if s["subId"] == sub_id), None)
    if sub is None:
        raise HTTPException(404, f"Submission {sub_id} not found.")
    return sub


async def _notify_submitter(sub: dict, approved: bool) -> tuple[dict, dict]:
    """审批结果邮件 —— 兑现提交页 "You'll be notified by email once it's approved or returned"。

    事务纪律与每日提醒一致：调用前主事务已提交，网络外发在写锁外（不阻塞其他写入），
    结果回填 sub["notify"] 用独立短事务持久化。通道未配置 → result 记 "skipped"，不是错误。
    """
    subject, body = logic.decision_email(sub, approved, base_url=get_settings().public_url)
    result = await delivery.send_email(sub.get("submitterEmail", ""), subject, body)
    notification = {"when": logic.fmt_when(logic.na_now()), "approved": approved, "result": result}
    async with _write_lock, SessionLocal() as s2:
        current = await service.update_submission_notification(s2, sub["subId"], notification)
        await s2.commit()
        state = await service.load_state(s2)
        return current or {**sub, "notify": notification}, service.snapshot(state)


async def _create_sharepoint_record(sub: dict) -> tuple[dict, dict]:
    """提交登记 → SharePoint List 建单（Graph app-only）。

    用户提交时即建单（不等审批确认）；审批/决议结果不回写（一期边界）。
    事务纪律同审批邮件：主事务已提交，网络在写锁外，短事务回填 sub["sharepoint"]。
    未配置凭据 → result 记 "skipped"；失败记 "failed: …"，均不阻断提交。
    """
    result, item_id = await graph.create_submission_item(sub, base_url=get_settings().public_url)
    record = {"when": logic.fmt_when(logic.na_now()), "result": result, "itemId": item_id or ""}
    async with _write_lock, SessionLocal() as s2:
        current = await service.update_submission_sharepoint(s2, sub["subId"], record)
        await s2.commit()
        state = await service.load_state(s2)
        return current or {**sub, "sharepoint": record}, service.snapshot(state)


@app.post("/api/submissions/{sub_id}/confirm", dependencies=[Depends(require_manager)])
async def confirm_registration(sub_id: str) -> dict:
    async with SessionLocal() as session, _write_lock:
        state = await service.load_state(session)
        sub = _find_sub(state, sub_id)
        if sub["status"] != "Waiting for Registration Confirmation":
            raise HTTPException(422, f"{sub_id} is already processed ({sub['status']}).")
        new_case = logic.confirm_submission(sub, state["cases"])
        state["cases"].append(new_case)
        await service.upsert_submission(session, sub)
        await service.insert_cases(session, [new_case])
        await session.commit()
    # 网络等待期间其他用户可能删除案例；只回填通知字段，并返回最新快照。
    sub, snap = await _notify_submitter(sub, approved=True)
    return {"ok": True, "submission": service.public_submission(sub), "case": new_case, "snapshot": snap}


@app.post("/api/submissions/{sub_id}/reject", dependencies=[Depends(require_manager)])
async def reject_registration(sub_id: str, b: RejectIn) -> dict:
    async with SessionLocal() as session, _write_lock:
        state = await service.load_state(session)
        sub = _find_sub(state, sub_id)
        if sub["status"] != "Waiting for Registration Confirmation":
            raise HTTPException(422, f"{sub_id} is already processed ({sub['status']}).")
        if not b.reason.strip():
            raise HTTPException(422, "A reason is required before returning this to the submitter.")
        sub["status"] = "Rejected"
        sub["rejectReason"] = b.reason.strip()
        await service.upsert_submission(session, sub)
        await session.commit()
    sub, snap = await _notify_submitter(sub, approved=False)
    return {"ok": True, "submission": service.public_submission(sub), "snapshot": snap}


# ============================= 案例：编辑 / 删除 =============================


@app.put("/api/cases/{row_id}", dependencies=[Depends(require_manager)])
async def save_case(row_id: str, b: CaseEditIn) -> dict:
    async with SessionLocal() as session, _write_lock:
        state = await service.load_state(session)
        case = next((c for c in state["cases"] if c["id"] == row_id), None)
        if case is None:
            raise HTTPException(404, f"Case row {row_id} not found.")
        edit = b.model_dump()
        other_task_ids = {
            task.get("id") for other in state["cases"] if other["id"] != row_id
            for task in other.get("followUps") or []
        }
        if any(task.get("id") in other_task_ids for task in edit["followUps"]):
            raise HTTPException(422, "Follow-up task IDs must be unique across cases.")
        error = logic.validate_case_edit(edit, imported=excel_import.is_imported(case))
        if error:
            raise HTTPException(422, error)
        # 只有请求真的带了商务字段才覆盖（model_fields_set），旧客户端 / 只改决议的保存不动它们
        commercial = (b.model_dump(include=set(COMMERCIAL_INPUT_FIELDS))
                      if b.model_fields_set & set(COMMERCIAL_INPUT_FIELDS) else None)
        # 先在副本上合并，再过商务门槛（明确答 No 的拒绝，留空放行），通过才落到内存态与库
        candidate = deepcopy(case)
        logic.apply_case_edit(candidate, edit, commercial)
        gate = logic.validate_commercial_state(candidate)
        if gate:
            raise HTTPException(422, gate)
        case.clear()
        case.update(candidate)
        await service.upsert_case(session, case)
        await session.commit()
        return {"ok": True, "case": case, "snapshot": service.snapshot(state)}


@app.delete("/api/cases/{swat_id}", dependencies=[Depends(require_manager)])
async def delete_case(swat_id: str) -> dict:
    async with SessionLocal() as session, _write_lock:
        state = await service.load_state(session)
        if not logic.delete_case_by_swat(state["cases"], state["submissions"], swat_id):
            raise HTTPException(404, f"No case rows for {swat_id}.")
        await service.delete_cases_by_swat(session, swat_id)
        for s in state["submissions"]:
            if s.get("approvedSwatId") == swat_id:
                await service.upsert_submission(session, s)
        await session.commit()
        return {"ok": True, "snapshot": service.snapshot(state)}


# ============================= 提醒 =============================


@app.post("/api/reminders/manual", dependencies=[Depends(require_manager)])
async def send_reminder(b: ManualReminderIn) -> dict:
    """手动提醒同样真实投递（管理员操作：真实外发的接口不能匿名调用）。与每日检查一致：先落库（lastReminder 不含投递结果），
    事务外投递，最后回填 delivery —— 网络慢不拖住数据库会话。"""
    email = b.email.strip()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "Enter a valid recipient email before sending.")
    async with SessionLocal() as session, _write_lock:
        state = await service.load_state(session)
        if not logic.send_manual_reminder(state["cases"], task_id=b.taskId, name=b.name.strip(), email=email,
                                          cc=b.cc.strip(), channel=b.channel,
                                          base_url=get_settings().public_url):
            raise HTTPException(404, f"Follow-up task {b.taskId} not found.")
        case = next(c for c in state["cases"] if any(t.get("id") == b.taskId for t in c.get("followUps") or []))
        task = next(t for t in case["followUps"] if t.get("id") == b.taskId)
        reminder_id = secrets.token_urlsafe(16)
        task["lastReminder"]["id"] = reminder_id
        await service.upsert_case(session, case)
        await session.commit()
        last = task["lastReminder"]
        pseudo = {"when": last["when"], "trigger": "Manual reminder",
                  "swatId": case["swatId"], "task": task.get("task", ""), "to": email, "cc": b.cc.strip(),
                  "channel": last["channel"], "message": last["message"]}
    await delivery.deliver_entry(pseudo)  # 网络外发在锁外，不阻塞其他写入
    async with _write_lock, SessionLocal() as session:
        await service.set_task_last_delivery(
            session, case["id"], b.taskId, pseudo.get("delivery") or {}, expected_reminder_id=reminder_id,
        )
        await session.commit()
        state = await service.load_state(session)
    return {"ok": True, "snapshot": service.snapshot(state)}


@app.put("/api/reminder-settings", dependencies=[Depends(require_admin)])
async def save_reminder_settings(b: ReminderSettingsIn) -> dict:
    async with SessionLocal() as session:
        async with _write_lock:
            state = await service.load_state(session)
            s = state["settings"]
            s["enabled"] = b.enabled
            s["onDueDate"] = True
            s["overdueEveryDays"] = max(1, b.overdueEveryDays or 1)
            s["channel"] = b.channel or "Email + Teams"
            s["alwaysCc"] = b.alwaysCc.strip()
            await service.persist_settings(session, s)
            await session.commit()
        # 保存后立即用新规则强制重跑一次（对应模板 rsSave 的 runDailyReminderCheck(true)）；
        # _run_check_if_due 内部自带 _write_lock —— 必须在上方锁释放后再调，否则死锁
        await _run_check_if_due(session, force=True)
        async with _write_lock:
            state = await service.load_state(session)
            return {"ok": True, "message": "Saved — reminders re-checked with the new rules.",
                    "snapshot": service.snapshot(state)}


# ============================= 议程 / 纪要导出 =============================


@app.get("/api/exports/{kind}")
async def export_week(kind: str, week: int = Query(ge=1, le=53), year: int = Query(default=0, ge=0, le=2100)) -> Response:
    """某周的议程（会前）或会议纪要（会后）.xlsx；周号与页面一致（ISO 周，KW）。

    year 默认当年（v3 Phase-17 导入了往年历史后，同一个 KW 会同时有 2025 与 2026 的案例）；
    没有 meetingYear 的旧记录（模板演示数据）不按年份过滤。"""
    if kind not in ("agenda", "minutes"):
        raise HTTPException(404, "Unknown export. Use agenda or minutes.")
    year = year or logic.na_now().isocalendar().year
    async with SessionLocal() as session, _write_lock:
        state = await service.load_state(session)
    cases = [c for c in state["cases"] if int(c.get("weekNum") or 0) == week
             and (not c.get("meetingYear") or int(c["meetingYear"]) == year)]
    label = logic.wk(week)
    return _xlsx_response(kind, exports.build(kind, cases, label), exports.filename(kind, label))


@app.post("/api/exports/{kind}")
async def export_selection(kind: str, b: ExportSelectionIn) -> Response:
    """Database 页按当前筛选结果导出：前端传可见案例的行 id，同一版式（跨周时按周、案例号排序）。"""
    if kind not in ("agenda", "minutes"):
        raise HTTPException(404, "Unknown export. Use agenda or minutes.")
    async with SessionLocal() as session, _write_lock:
        state = await service.load_state(session)
    wanted = set(b.ids)
    cases = [c for c in state["cases"] if c["id"] in wanted]
    now = logic.na_now()
    title = f"Database export, {len(cases)} case{'s' if len(cases) != 1 else ''} ({logic.fmt_when(now)})"
    return _xlsx_response(kind, exports.build(kind, cases, title), exports.filename(kind, f"Database_{now:%Y-%m-%d}"))


def _xlsx_response(kind: str, data: bytes, name: str) -> Response:
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ============================= 登记截止 =============================


@app.put("/api/registration-settings", dependencies=[Depends(require_admin)])
async def save_registration_settings(b: RegistrationSettingsIn) -> dict:
    """登记截止规则：会前几天、几点、时区。立即生效，只影响之后的提交。"""
    registration = {**b.model_dump(), "updatedAt": logic.fmt_when(logic.na_now())}
    async with SessionLocal() as session, _write_lock:
        await service.persist_registration(session, registration)
        await session.commit()
        state = await service.load_state(session)
        return {"ok": True, "snapshot": service.snapshot(state)}


# ============================= 汇率 =============================


@app.put("/api/fx-settings", dependencies=[Depends(require_admin)])
async def save_fx_settings(b: FxSettingsIn) -> dict:
    """汇率表（财务 OP 记法：1 EUR = X 外币）。只影响之后的提交；已有记录保存了当时的汇率。"""
    per_eur = {code: logic.rate_text(rate) for code, rate in b.perEur.model_dump().items() if rate is not None}
    fx = {"basis": b.basis, "perEur": per_eur, "updatedAt": logic.fmt_when(logic.na_now())}
    async with SessionLocal() as session, _write_lock:
        await service.persist_fx(session, fx)
        await session.commit()
        state = await service.load_state(session)
        return {"ok": True, "snapshot": service.snapshot(state)}


# ============================= 演示文件（v3 Phase-5） =============================
# 事务纪律同 SharePoint 建单：先在写锁内检查，收文件与上传（可能很久）在锁外，最后短事务记下文件；
# 期间记录被删或被处理了，就把刚存的文件删掉。

WAITING = "Waiting for Registration Confirmation"


def _upload_key_ok(sub: dict, key: str | None) -> bool:
    stored = sub.get("uploadKeyHash") or ""
    return bool(key and stored) and secrets.compare_digest(hashlib.sha256(key.encode()).hexdigest(), stored)


def _find_file(state: dict, file_id: str) -> dict | None:
    for record in (*state["cases"], *state["submissions"]):
        for f in record.get("files") or []:
            if f.get("id") == file_id:
                return f
    # 待办反馈的附件（v3 Phase-14）
    for case in state["cases"]:
        for task in case.get("followUps") or []:
            for fb in task.get("feedback") or []:
                for f in fb.get("files") or []:
                    if f.get("id") == file_id:
                        return f
    return None


@app.post("/api/submissions/{sub_id}/files")
async def upload_submission_file(sub_id: str, request: Request, name: str = Query(max_length=300),
                                 x_upload_key: str | None = Header(default=None),
                                 user: CurrentUser = None) -> dict:
    """提交人（提交时拿到的 uploadKey，或本人账号）或 NPI 经理及以上，给待确认的登记加文件。"""
    clean = files.checked_name(name)
    is_manager = bool(user) and accounts.RANK.get(user.get("role", "user"), 0) >= accounts.RANK["npi_manager"]
    async with SessionLocal() as session, _write_lock:
        sub = _find_sub(await service.load_state(session), sub_id)
        by_submitter = _upload_key_ok(sub, x_upload_key) or (
            bool(user) and user["email"] == sub.get("submitterEmail", "").lower())
        if not (by_submitter or is_manager):
            raise HTTPException(401, "This upload link is not valid for that registration.")
        if sub["status"] != WAITING:
            raise HTTPException(422, f"{sub_id} is already processed — ask the Sourcing admin to add the file on the case page.")
        files.check_room(sub)
    tmp, size = await files.receive(request)
    # v3 Phase-15：按案例改名（日期 项目 零件描述 零件号, 供应商），原文件名留在记录里
    record = await files.store(tmp, files.bundle_file_name(sub, clean), size, request.headers.get("content-type", ""),
                               sub.get("caseId", ""), sub.get("submitterName", "") if by_submitter else user["name"],
                               original_name=clean)
    async with SessionLocal() as session, _write_lock:
        state = await service.load_state(session)
        sub = next((s for s in state["submissions"] if s["subId"] == sub_id), None)
        if sub is None or sub["status"] != WAITING or len(sub.get("files") or []) >= files.MAX_FILES_PER_RECORD:
            await files.remove(record)
            raise HTTPException(409, f"{sub_id} changed while the file was uploading. Please reload and try again.")
        sub.setdefault("files", []).append(record)
        await service.upsert_submission(session, sub)
        await session.commit()
        return {"ok": True, "file": record, "snapshot": service.snapshot(state)}


@app.post("/api/cases/{row_id}/files")
async def upload_case_file(row_id: str, request: Request, user: Manager, name: str = Query(max_length=300)) -> dict:
    """管理员在案例页加文件（如会后的最终版演示）。"""
    clean = files.checked_name(name)
    async with SessionLocal() as session, _write_lock:
        case = next((c for c in (await service.load_state(session))["cases"] if c["id"] == row_id), None)
        if case is None:
            raise HTTPException(404, f"Case row {row_id} not found.")
        files.check_room(case)
    tmp, size = await files.receive(request)
    record = await files.store(tmp, files.bundle_file_name(case, clean), size, request.headers.get("content-type", ""),
                               case.get("swatId", ""), user["name"], original_name=clean)
    async with SessionLocal() as session, _write_lock:
        state = await service.load_state(session)
        case = next((c for c in state["cases"] if c["id"] == row_id), None)
        if case is None or len(case.get("files") or []) >= files.MAX_FILES_PER_RECORD:
            await files.remove(record)
            raise HTTPException(409, f"Case row {row_id} changed while the file was uploading. Please reload and try again.")
        case.setdefault("files", []).append(record)
        await service.upsert_case(session, case)
        await session.commit()
        return {"ok": True, "file": record, "case": case, "snapshot": service.snapshot(state)}


@app.delete("/api/cases/{row_id}/files/{file_id}", dependencies=[Depends(require_manager)])
async def delete_case_file(row_id: str, file_id: str) -> dict:
    async with SessionLocal() as session, _write_lock:
        state = await service.load_state(session)
        case = next((c for c in state["cases"] if c["id"] == row_id), None)
        record = next((f for f in (case or {}).get("files") or [] if f.get("id") == file_id), None)
        if case is None or record is None:
            raise HTTPException(404, "File not found on this case.")
        case["files"] = [f for f in case["files"] if f.get("id") != file_id]
        await service.upsert_case(session, case)
        # 确认登记时文件记录从提交单复制到案例：原提交单上的同一条一起去掉，删了就是真删了
        for sub in state["submissions"]:
            if any(f.get("id") == file_id for f in sub.get("files") or []):
                sub["files"] = [f for f in sub["files"] if f.get("id") != file_id]
                await service.upsert_submission(session, sub)
        await session.commit()
        snap = service.snapshot(state)
    await files.remove(record)
    return {"ok": True, "case": case, "snapshot": snap}


@app.get("/api/files/{file_id}")
async def download_file(file_id: str):
    """所有人可下载（反馈人答复）：本地文件直接回传，SharePoint 文件跳转到临时下载地址。"""
    async with SessionLocal() as session, _write_lock:
        record = _find_file(await service.load_state(session), file_id)
    if record is None:
        raise HTTPException(404, "File not found.")
    return await files.download(record)


# ============================= 待办反馈与关闭审批（v3 Phase-14） =============================


def _find_task(state: dict, task_id: str) -> tuple[dict, dict]:
    case, task = feedback.find_task(state["cases"], task_id)
    if task is None:
        raise HTTPException(404, f"Follow-up task {task_id} not found.")
    return case, task


async def _record_feedback_notice(task_id: str, fb_id: str, key: str, notice: dict) -> tuple[dict | None, dict]:
    """通知发完后回填投递结果（独立短事务，与审批邮件同一纪律）。key = notify | decision."""
    async with _write_lock, SessionLocal() as session:
        state = await service.load_state(session)
        case, task = feedback.find_task(state["cases"], task_id)
        fb = feedback.find_feedback(task, fb_id)
        if fb is not None:
            if key == "notify":
                fb["notify"] = notice
            elif fb.get("decision") is not None:
                fb["decision"]["notify"] = notice
            await service.upsert_case(session, case)
            await session.commit()
        return fb, service.snapshot(state)


@app.post("/api/tasks/{task_id}/feedback")
async def post_feedback(task_id: str, b: FeedbackIn, user: LoggedIn) -> dict:
    """任何登录用户对开放待办汇报进展；先落库，再在锁外通知全部 NPI 经理与管理员。"""
    text = b.text.strip()
    if not text:
        raise HTTPException(422, "Describe what was done before submitting the feedback.")
    async with SessionLocal() as session, _write_lock:
        state = await service.load_state(session)
        case, task = _find_task(state, task_id)
        if task.get("status") == "Closed":
            raise HTTPException(422, "This follow-up is already Closed — no further feedback is needed.")
        if len(task.get("feedback") or []) >= feedback.MAX_FEEDBACK_PER_TASK:
            raise HTTPException(422, f"A follow-up can carry at most {feedback.MAX_FEEDBACK_PER_TASK} feedback entries.")
        fb = feedback.new_feedback(user, text)
        task.setdefault("feedback", []).append(fb)
        await service.upsert_case(session, case)
        await session.commit()
        approvers = sorted(u["email"] for u in await service.list_users(session)
                           if u.get("role") in ("npi_manager", "admin") and not u.get("disabled"))
        subject, body = feedback.feedback_email(case, task, fb, base_url=get_settings().public_url)
    to = ", ".join(approvers)
    result = await delivery.send_email(to, subject, body) if to else "skipped: no Manager or admin account"
    notice = {"when": logic.fmt_when(logic.na_now()), "to": to, "result": result}
    saved, snap = await _record_feedback_notice(task_id, fb["id"], "notify", notice)
    return {"ok": True, "feedback": saved or {**fb, "notify": notice}, "snapshot": snap}


@app.post("/api/tasks/{task_id}/feedback/{fb_id}/files")
async def upload_feedback_file(task_id: str, fb_id: str, request: Request, user: LoggedIn,
                               name: str = Query(max_length=300)) -> dict:
    """反馈的凭证附件（如邮件 .msg）：反馈人本人或 NPI 经理及以上，只在待审时能加。"""
    clean = files.checked_name(name, files.FEEDBACK_EXTENSIONS)
    is_manager = accounts.RANK.get(user.get("role", "user"), 0) >= accounts.RANK["npi_manager"]
    async with SessionLocal() as session, _write_lock:
        case, task = _find_task(await service.load_state(session), task_id)
        fb = feedback.find_feedback(task, fb_id)
        if fb is None:
            raise HTTPException(404, "Feedback not found on this follow-up.")
        if not (feedback.is_author(fb, user) or is_manager):
            raise HTTPException(403, "Only the person who gave this feedback (or a Manager) can attach files to it.")
        if fb.get("status") != feedback.PENDING:
            raise HTTPException(422, f"This feedback was already {fb.get('status')} — files can no longer be added.")
        files.check_room(fb)
    tmp, size = await files.receive(request)
    # 凭证附件（邮件等）保留原文件名；只有演示文件按案例改名（v3 Phase-15）
    record = await files.store(tmp, clean, size, request.headers.get("content-type", ""), case.get("swatId", ""), user["name"])
    async with SessionLocal() as session, _write_lock:
        state = await service.load_state(session)
        case, task = feedback.find_task(state["cases"], task_id)
        fb = feedback.find_feedback(task, fb_id)
        if fb is None or fb.get("status") != feedback.PENDING or len(fb.get("files") or []) >= files.MAX_FILES_PER_RECORD:
            await files.remove(record)
            raise HTTPException(409, "The feedback changed while the file was uploading. Please reload and try again.")
        fb.setdefault("files", []).append(record)
        await service.upsert_case(session, case)
        await session.commit()
        return {"ok": True, "file": record, "feedback": fb, "snapshot": service.snapshot(state)}


@app.post("/api/tasks/{task_id}/feedback/{fb_id}/decision")
async def decide_feedback(task_id: str, fb_id: str, b: FeedbackDecisionIn, user: Manager) -> dict:
    """NPI 经理及以上 approve（待办关闭）或 reject（须写进一步要求）；结果邮件在锁外发给待办收件人，抄送反馈人。"""
    async with SessionLocal() as session, _write_lock:
        state = await service.load_state(session)
        case, task = _find_task(state, task_id)
        fb = feedback.find_feedback(task, fb_id)
        if fb is None:
            raise HTTPException(404, "Feedback not found on this follow-up.")
        error = feedback.decide(case, task, fb, user, b.decision, b.remark, b.finalDocLink)
        if error:
            raise HTTPException(422, error)
        await service.upsert_case(session, case)
        await session.commit()
        subject, body = feedback.decision_email(case, task, fb, base_url=get_settings().public_url)
        to, cc = feedback.decision_recipients(task, fb)
    result = await delivery.send_email(to, subject, body, cc) if to else "skipped: no recipient email"
    notice = {"when": logic.fmt_when(logic.na_now()), "to": to, "cc": cc, "result": result}
    saved, snap = await _record_feedback_notice(task_id, fb_id, "decision", notice)
    case = next((c for c in snap["cases"] if any(t.get("id") == task_id for t in c.get("followUps") or [])), case)
    return {"ok": True, "feedback": saved or fb, "case": case, "snapshot": snap}


# ============================= 遗留 Excel 上传模拟 =============================


@app.post("/api/import/excel")
async def import_excel(request: Request, user: Admin, name: str = Query(max_length=300),
                       commit: bool = Query(default=False), meetingDate: str = Query(default="", max_length=10),
                       sourceUrl: str = Query(default="", max_length=500)) -> dict:
    """v3 Phase-17：周会 Excel（委员会模板的 Agenda / MM）→ 那一周的案例。管理员专属。

    commit=false 只解析并返回预览（案例数、零件行数、警告、会替换掉的旧导入）；commit=true 写库：
    同一年同一周之前导入的案例先删再插。请求体是文件原始字节（与演示文件上传同一方式）。"""
    if not name.lower().endswith(".xlsx"):
        raise HTTPException(422, "Upload the weekly committee file as .xlsx (Excel workbook).")
    day = None
    if meetingDate:
        try:
            day = date.fromisoformat(meetingDate)
        except ValueError as exc:
            raise HTTPException(422, "Meeting date must be YYYY-MM-DD.") from exc
    if sourceUrl and not logic.valid_http_url(sourceUrl):
        raise HTTPException(422, "The SharePoint folder link must be a full URL (starting with http:// or https://).")
    tmp, size = await files.receive(request)
    try:
        if size > excel_import.MAX_FILE_BYTES:
            raise HTTPException(413, "The workbook is larger than 20 MB — that is not a weekly committee file.")
        data = tmp.read_bytes()
    finally:
        tmp.unlink(missing_ok=True)
    async with SessionLocal() as session, _write_lock:
        state = await service.load_state(session)
        return await _import_workbook(session, state, data, name, day=day, source_url=sourceUrl, commit=commit, user=user)


async def _import_workbook(session, state: dict, data: bytes, name: str, *, day: date | None, source_url: str,
                           commit: bool, user: dict) -> dict:
    """上传的文件与库里的文件共用：解析 → 预览摘要；commit 时替换同一年同一周之前导入的案例。调用方持有写锁。"""
    try:
        report = excel_import.parse_workbook(data, name, state["fx"], meeting_date=day, source_url=source_url,
                                             imported_by=user["email"], when=logic.fmt_when(logic.na_now()))
    except excel_import.TemplateError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:  # openpyxl 打不开等：给可读的 422，不是 500
        log.warning("excel import failed for %s: %s", name, exc)
        raise HTTPException(422, f"The file could not be read as an Excel workbook ({type(exc).__name__}).") from exc
    replaced = excel_import.previously_imported(state["cases"], report["meetingYear"], report["weekNum"])
    summary = {
        "ok": True, "file": name, "sheet": report["sheet"], "weekNum": report["weekNum"], "meetingYear": report["meetingYear"],
        "meetingDateISO": report["meetingDateISO"], "meetingDateLabel": report["meetingDateLabel"],
        "cases": len(report["cases"]), "rows": report["rows"], "warnings": report["warnings"],
        "replaces": len(replaced), "committed": False,
        "preview": [{"caseNumber": c["caseNumber"], "swatId": c["swatId"], "partDescription": c["partDescription"],
                     "parts": len(c["partNumbers"] or [1]), "region": c["region"], "decision": c["meetingDecision"],
                     "lifetimeSpend": c["lifetimeSpend"]} for c in report["cases"]],
    }
    if not commit:
        return summary
    if not report["cases"]:
        raise HTTPException(422, "No cases found in this file — nothing to import.")
    replaced_ids = {c["id"] for c in replaced}
    state["cases"] = [c for c in state["cases"] if c["id"] not in replaced_ids]
    new_cases = []
    for c in report["cases"]:
        c["id"] = logic.next_case_row_id(state["cases"] + new_cases)
        new_cases.append(c)
    await service.delete_cases_by_ids(session, sorted(replaced_ids))
    await service.insert_cases(session, new_cases)
    state["cases"].extend(new_cases)
    await session.commit()
    summary.update(committed=True, added=len(new_cases), snapshot=service.snapshot(state))
    return summary


@app.get("/api/import/library")
async def import_library(user: Admin) -> dict:
    """随程序发布的历史周文件（app/history）：列表 + 那一周是否已从 Excel 导入过。管理员专属。"""
    async with SessionLocal() as session, _write_lock:
        state = await service.load_state(session)
    listed = excel_import.library_files()
    for f in listed:
        f["imported"] = bool(f["meetingYear"] and excel_import.previously_imported(state["cases"], f["meetingYear"], f["weekNum"]))
    return {"ok": True, "files": listed}


@app.post("/api/import/library")
async def import_library_file(b: LibraryImportIn, user: Admin) -> dict:
    """导入库里的一份周文件（相对路径）；会议日期取文件名，取不到用文件夹名。commit 语义同 /api/import/excel。"""
    if b.sourceUrl and not logic.valid_http_url(b.sourceUrl):
        raise HTTPException(422, "The SharePoint folder link must be a full URL (starting with http:// or https://).")
    try:
        path = excel_import.library_path(b.path)
    except excel_import.TemplateError as exc:
        raise HTTPException(404, str(exc)) from exc
    _, day = excel_import.meeting_from_name(path.name)
    if day is None:
        _, day = excel_import.meeting_from_name(path.parent.name)
    data = path.read_bytes()
    async with SessionLocal() as session, _write_lock:
        state = await service.load_state(session)
        return await _import_workbook(session, state, data, path.name, day=day, source_url=b.sourceUrl, commit=b.commit, user=user)


# ============================= 静态前端（挂载在最后，/api 优先匹配） =============================


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
