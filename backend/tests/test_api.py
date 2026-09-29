"""API 回归测试 —— 与 Playwright 人工验收互补，固化已验证的核心行为。

每个用例独占临时数据库，可单独运行，不依赖其他用例的执行顺序。
"""

import pytest


@pytest.fixture(autouse=True)
def _reset_throttles():
    """每条用例后清空进程内限流表（登录 + 提交）—— 限流用例不再要求"必须排在最后"。"""
    yield
    from app import main
    main._login_failures.clear()
    main._submission_times.clear()


@pytest.fixture
def client(api_client):
    return api_client


@pytest.fixture
def admin(client):
    r = client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    assert r.status_code == 200
    return {"X-Session-Token": r.json()["token"]}


VALID_SUBMISSION = {
    "submitterName": "T. Ester",
    "submitterEmail": "t.ester@zf.com",
    "caseNo": "swat 20999",
    "partNumbers": [{"partNumber": "99112233", "partDescription": "Test Part",
                     "pcPriceCQA": "1.25", "supplierPriceLanded": "1.1", "toolingCQA": "120000", "supplierToolingCost": "118500"}],
    # v3 Phase-15：金额按整个 bundle 在案例级；项目 / 类型 / 供应商在案例级时作为每个零件行的默认值
    "peakYearSpend": 100, "lifetimeSpend": 200,
    "region": "EU", "project": "ACR9 Program", "family": "N/A", "cluster": "Metal",
    "sourcingType": "New", "recommendedSupplier": "Baltic Stamping Works", "decisionLevel": "Level 2",
    "meetingDateISO": "2026-09-30", "meetingDateLabel": "Wed, Sep 30, 2026", "meetingWeekNum": 39,
    "comments": "pytest", "isFamilyCase": "No", "involvesECM": "No",
    "toolingPayment": "Lumpsum", "fraAvailable": "Yes",
}


def test_admin_gate(client, admin):
    # 未登录 → 401；普通用户 → 403；错误密码 → 401；登出后旧令牌失效
    r = client.post("/api/submissions/SUB-0001/confirm", headers={"X-Session-Token": ""})
    assert r.status_code == 401 and "log in" in r.json()["detail"]
    r = client.post("/api/submissions/SUB-0001/confirm")
    assert r.status_code == 403 and "Manager" in r.json()["detail"]
    r = client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "wrong"})
    assert r.status_code == 401
    r = client.post("/api/auth/logout", headers=admin)
    assert r.status_code == 200
    r = client.post("/api/submissions/SUB-0001/confirm", headers=admin)  # 已登出的令牌
    assert r.status_code == 401
    # 重新登录，供后续用例使用
    r = client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    assert r.status_code == 200
    admin["X-Session-Token"] = r.json()["token"]


def test_bootstrap_seeded(client):
    r = client.get("/api/bootstrap")
    assert r.status_code == 200
    snap = r.json()
    assert len(snap["cases"]) == 22          # 模板演示数据：22 条登场记录
    assert len(snap["submissions"]) == 1     # 种子 SUB-0001
    assert snap["reminderSettings"]["enabled"] is True
    assert snap["reminderSettings"]["lastRunDate"]  # 启动时已跑每日检查
    assert snap["serverTimezone"] == "America/New_York"  # 前端"今天"跟随服务器时区


def test_submission_gates(client):
    # 缺必填 → 模板原文文案
    missing = dict(VALID_SUBMISSION, recommendedSupplier=" ")
    r = client.post("/api/submissions", json=missing)
    assert r.status_code == 422
    assert "Recommended Supplier for every part number row" in r.json()["detail"]  # v3 Phase-15：供应商按零件行
    # Family Alignment 未完成 → 门禁拦截
    blocked = dict(VALID_SUBMISSION, isFamilyCase="Yes", familyAligned="No")
    r = client.post("/api/submissions", json=blocked)
    assert r.status_code == 422
    assert "Family Alignment" in r.json()["detail"]
    # ECM 未过 CCB2 → 门禁拦截
    blocked = dict(VALID_SUBMISSION, involvesECM="Yes", ccbApproved="No")
    r = client.post("/api/submissions", json=blocked)
    assert "CCB2" in r.json()["detail"]
    # 项目名改为自由输入后仍是必填
    r = client.post("/api/submissions", json=dict(VALID_SUBMISSION, project="  "))
    assert r.status_code == 422
    assert "Project" in r.json()["detail"]


def test_family_alignment_done_is_enough(client):
    # 反馈 #4：Family Alignment 已完成即可登记，不再要求证据链接
    body = dict(VALID_SUBMISSION, isFamilyCase="Yes", familyAligned="Yes", project="MBEAL")
    r = client.post("/api/submissions", json=body)
    assert r.status_code == 200
    sub = next(s for s in r.json()["snapshot"]["submissions"] if s["subId"] == r.json()["subId"])
    assert sub["familyAligned"] == "Yes" and "familyEvidence" not in sub
    assert sub["project"] == "MBEAL"  # 自由输入的项目名原样保存


def test_multi_region_submission_flows_into_case(client, admin):
    # 反馈 #2：一个案例可以同时属于多个区域，确认后案例沿用同一区域文本
    r = client.post("/api/submissions", json=dict(VALID_SUBMISSION, region=["NA", "EU"]))
    assert r.status_code == 200
    sid = r.json()["subId"]
    sub = next(s for s in r.json()["snapshot"]["submissions"] if s["subId"] == sid)
    assert sub["region"] == "EU + NA"
    r = client.post(f"/api/submissions/{sid}/confirm", headers=admin)
    case = next(c for c in r.json()["snapshot"]["cases"] if c["swatId"] == "SWAT-20999")
    assert case["region"] == "EU + NA"
    # 没选区域 → 拦截
    r = client.post("/api/submissions", json=dict(VALID_SUBMISSION, caseNo="SWAT-20998", region=[]))
    assert r.status_code == 422 and "Region" in r.json()["detail"]


def test_reminder_email_is_never_guessed_from_name():
    # 反馈 #8：未知姓名不再拼出 xxx@zf.com；通讯录与直接填写的邮箱照常使用
    from app import logic
    assert logic.email_for("Sandra Novegil") == ""
    assert logic.email_for("W. Chen") == "w.chen@zf.com"
    assert logic.email_for(" s.novegil@zf-lifetec.com ") == "s.novegil@zf-lifetec.com"
    assert logic.task_recipient({"responsible": "Sandra Novegil"})["email"] == ""


def test_submit_ok_and_duplicate_guard(client):
    r = client.post("/api/submissions", json=VALID_SUBMISSION)
    assert r.status_code == 200
    j = r.json()
    assert j["subId"] == "SUB-0002"
    sub = next(s for s in j["snapshot"]["submissions"] if s["subId"] == "SUB-0002")
    assert sub["caseId"] == "SWAT-20999"  # "swat 20999" 已归一化
    r = client.post("/api/submissions", json=VALID_SUBMISSION)
    assert r.status_code == 422
    assert "already has a registration" in r.json()["detail"]


def test_confirm_creates_pending_case(client, admin):
    assert client.post("/api/submissions", json=VALID_SUBMISSION).status_code == 200
    r = client.post("/api/submissions/SUB-0002/confirm", headers=admin)
    assert r.status_code == 200
    j = r.json()
    case = j["case"]
    assert case["meetingDecision"] == "PENDING"
    assert case["swatId"] == "SWAT-20999"
    assert case["weekNum"] == 40  # 2026-09-30 是 ISO 第 40 周（KW40）
    assert case["submitterComments"] == "pytest"
    assert case["followUps"] == []
    # 重复确认 → 拒绝
    r = client.post("/api/submissions/SUB-0002/confirm", headers=admin)
    assert r.status_code == 422


def _edit_payload(case, **over):
    p = {
        "partNumbers": [{"partNumber": case["partNumber"], "partDescription": case["partDescription"]}],
        "peakYearSpend": case["peakYearSpend"], "lifetimeSpend": case["lifetimeSpend"],
        "region": case["region"], "project": case["project"], "family": case["family"],
        "cluster": case["cluster"], "parentPF": case["parentPF"], "partFamilyCode": case["partFamilyCode"],
        "sourcingType": case["sourcingType"], "recommendedSupplier": case["recommendedSupplier"],
        "presenter": case["presenter"], "decisionLevel": case["decisionLevel"], "leadTime": case.get("leadTime", ""),
        "committeeDiscussion": case["committeeDiscussion"], "meetingDecision": case["meetingDecision"],
        "sourcingPresentationLink": case.get("sourcingPresentationLink", ""),
        "finalDocLink": case.get("finalDocLink", ""), "followUps": case.get("followUps") or [],
    }
    p.update(over)
    return p


def _get_case(client, row_id):
    snap = client.get("/api/bootstrap").json()
    return next(c for c in snap["cases"] if c["id"] == row_id)


def test_edit_three_rules(client, admin):
    assert client.post("/api/submissions", json=VALID_SUBMISSION).status_code == 200
    assert client.post("/api/submissions/SUB-0002/confirm", headers=admin).status_code == 200
    case = _get_case(client, "C0023")  # confirm 新建的那条
    # 规则 1：非 Pending 决议缺演示链接
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, meetingDecision="APPROVED"))
    assert r.status_code == 422
    assert "Sourcing Presentation Link" in r.json()["detail"]
    # 规则 1：链接不是完整 URL
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, meetingDecision="APPROVED", sourcingPresentationLink="sharepoint/x.pptx"))
    assert "full URL" in r.json()["detail"]
    # 规则 0：Pending 案例不能带待办
    task = {"id": "FU-T1", "task": "t", "responsible": "T. Ester", "dueDate": "2026-10-01",
            "status": "Open", "notes": "", "tags": ["Cost"]}
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, meetingDecision="PENDING", followUps=[task]))
    assert "cannot have follow-up tasks" in r.json()["detail"]
    # 规则 3：全部待办 Closed 必须有最终文件链接
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(
        case, meetingDecision="APPROVED", sourcingPresentationLink="https://zf.sharepoint.com/x.pptx",
        followUps=[dict(task, status="Closed")]))
    assert "Final PPT / Supporting Document Link" in r.json()["detail"]
    # 合法保存：补齐两个链接 → 成功且金额汇总正确
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(
        case, meetingDecision="APPROVED",
        sourcingPresentationLink="https://zf.sharepoint.com/p.pptx",
        finalDocLink="https://zf.sharepoint.com/f.pptx",
        partNumbers=[{"partNumber": "1", "partDescription": "d"}, {"partNumber": "2", "partDescription": "d2"}],
        peakYearSpend=15, lifetimeSpend=26,  # v3 Phase-15：bundle 金额在案例级
        followUps=[dict(task, status="Closed")]))
    assert r.status_code == 200
    saved = r.json()["case"]
    assert saved["peakYearSpend"] == 15 and saved["lifetimeSpend"] == 26
    assert saved["actionStatus"] == "Closed"
    assert len(saved["partNumbers"]) == 2


def test_edit_requires_region_and_reminder_email_server_side(client, admin):
    # 2026-09-24 复测：这两条之前只有前端拦，直接调 API 可以存空区域、存没邮箱的未关闭待办
    assert client.post("/api/submissions", json=VALID_SUBMISSION).status_code == 200
    assert client.post("/api/submissions/SUB-0002/confirm", headers=admin).status_code == 200
    case = _get_case(client, "C0023")
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, region=""))
    assert r.status_code == 422 and "at least one Region" in r.json()["detail"]
    task = {"id": "FU-T2", "task": "t", "responsible": "Nobody Known", "dueDate": "2026-10-01", "status": "Open", "tags": ["CQA"]}
    approved = {"meetingDecision": "APPROVED", "sourcingPresentationLink": "https://zf.sharepoint.com/p.pptx"}
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, **approved, followUps=[task]))
    assert r.status_code == 422 and "Follow-up task 1" in r.json()["detail"] and "email" in r.json()["detail"]
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, **approved, followUps=[dict(task, notifyEmail="n.known@zf.com")]))
    assert r.status_code == 200
    # 已关闭的待办不需要邮箱（历史任务可以直接关闭）
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(
        case, **approved, finalDocLink="https://zf.sharepoint.com/f.pptx", followUps=[dict(task, status="Closed")]))
    assert r.status_code == 200


def test_manual_reminder(client, admin):
    snap = client.get("/api/bootstrap").json()
    open_task = next(t for c in snap["cases"] for t in c["followUps"] if t["status"] in ("Open", "Overdue"))
    body = {"taskId": open_task["id"], "name": "W. Chen", "email": "w.chen@zf.com", "cc": "", "channel": "Email"}
    assert client.post("/api/reminders/manual", json=body, headers={"X-Session-Token": ""}).status_code == 401  # 真实外发：匿名不能调
    assert client.post("/api/reminders/manual", json=body).status_code == 403  # 普通用户也不能
    bad = client.post("/api/reminders/manual", json=dict(body, name="x", email="not-an-email"), headers=admin)
    assert bad.status_code == 422
    r = client.post("/api/reminders/manual", json=body, headers=admin)
    assert r.status_code == 200
    updated = next(t for c in r.json()["snapshot"]["cases"] for t in c["followUps"] if t["id"] == open_task["id"])
    assert updated["lastReminder"]["to"] == "w.chen@zf.com"
    assert "Follow-up Task for Sourcing Case" in updated["lastReminder"]["message"]


def test_delete_cascades_to_submission(client, admin):
    assert client.post("/api/submissions", json=VALID_SUBMISSION).status_code == 200
    assert client.post("/api/submissions/SUB-0002/confirm", headers=admin).status_code == 200
    r = client.delete("/api/cases/SWAT-20999", headers=admin)
    assert r.status_code == 200
    snap = r.json()["snapshot"]
    assert not any(c["swatId"] == "SWAT-20999" for c in snap["cases"])
    sub = next(s for s in snap["submissions"] if s["subId"] == "SUB-0002")
    assert sub["status"] == "Deleted"
    assert "SWAT-20999" in sub["rejectReason"]


def test_reminder_settings_force_rerun(client, admin):
    r = client.put("/api/reminder-settings", headers=admin, json={"enabled": True, "overdueEveryDays": 2, "channel": "Email", "alwaysCc": "lead@zf.com"})
    assert r.status_code == 200
    assert r.json()["message"] == "Saved — reminders re-checked with the new rules."
    settings = client.get("/api/bootstrap").json()["reminderSettings"]
    assert settings["overdueEveryDays"] == 2 and settings["alwaysCc"] == "lead@zf.com"
    assert settings["lastRun"]["auto"] is False  # 强制重跑


def test_legacy_upload_adds_18(client, admin):
    # Sourcing 管理员专属：未登录 401、普通用户 403（此前任何人可注入 18 条演示案例）
    assert client.post("/api/legacy-upload", headers={"X-Session-Token": ""}).status_code == 401
    r = client.post("/api/legacy-upload")
    assert r.status_code == 403
    before = len(client.get("/api/bootstrap").json()["cases"])
    r = client.post("/api/legacy-upload", headers=admin)
    assert r.status_code == 200 and r.json()["added"] == 18
    assert len(r.json()["snapshot"]["cases"]) == before + 18
    weeks = {c["weekNum"] for c in r.json()["snapshot"]["cases"] if c["swatId"].startswith("SWAT-205")}
    assert weeks == {34}


# ============================= v2 Phase-8：提交限流 =============================


def test_submission_rate_limit_unit():
    import time as time_mod

    from app import main

    assert main._submission_allowed("ip-a") is True
    for _ in range(main.SUBMIT_MAX_PER_WINDOW):
        main._submission_record("ip-a")
    assert main._submission_allowed("ip-a") is False
    # 窗口外的时间戳不计入，且无记录的键被清理（字典不膨胀）
    main._submission_times["ip-b"] = [time_mod.time() - 9999]
    assert main._submission_allowed("ip-b") is True
    assert "ip-b" not in main._submission_times


def test_submission_rate_limit_endpoint(client, monkeypatch):
    from app import main

    monkeypatch.setattr(main, "SUBMIT_MAX_PER_WINDOW", 2)
    r1 = client.post("/api/submissions", json=dict(VALID_SUBMISSION, caseNo="swat 71001"))
    r2 = client.post("/api/submissions", json=dict(VALID_SUBMISSION, caseNo="swat 71002"))
    assert r1.status_code == 200 and r2.status_code == 200
    r3 = client.post("/api/submissions", json=dict(VALID_SUBMISSION, caseNo="swat 71003"))
    assert r3.status_code == 429 and "Too many submissions" in r3.json()["detail"]


# ============================= v2：投递 =============================


def test_delivery_skips_when_unconfigured():
    import asyncio

    from app import delivery

    entry = {"when": "x", "trigger": "Due today", "swatId": "SWAT-1", "task": "t",
             "to": "a@zf.com", "cc": "", "channel": "Email + Teams", "message": "m"}
    asyncio.run(delivery.deliver_entry(entry))
    assert entry["delivery"] == {"email": "skipped", "teams": "skipped"}
    entry2 = dict(entry, channel="Email")
    asyncio.run(delivery.deliver_entry(entry2))
    assert entry2["delivery"] == {"email": "skipped"}  # 只走 Email，不会多出 teams


def test_email_invalid_recipient(monkeypatch):
    import asyncio

    from app import delivery
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.test")  # 通道视为已配置；校验发生在连接之前
    entry = {"when": "x", "trigger": "Due today", "swatId": "SWAT-1", "task": "t",
             "to": "(no email on file)", "cc": "", "channel": "Email", "message": "m"}
    assert asyncio.run(delivery.deliver_email(entry)).startswith("failed: no valid recipient")


def test_teams_flow_payload(monkeypatch):
    import asyncio

    from app import delivery
    from app.config import get_settings

    captured = {}

    class FakeResp:
        status_code = 200

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, **kwargs):  # kwargs: Graph 凭据配置时附带 headers
            captured["url"] = url
            captured["payload"] = json
            return FakeResp()

    s = get_settings()
    monkeypatch.setattr(s, "teams_webhook_url", "https://flow.test/abc")
    monkeypatch.setattr(s, "teams_webhook_format", "flow")
    monkeypatch.setattr(delivery.httpx, "AsyncClient", FakeClient)
    entry = {"when": "x", "trigger": "Due today", "swatId": "SWAT-10555", "task": "t",
             "to": "l.novak@zf.com", "cc": "", "channel": "Teams", "message": "hello"}
    assert asyncio.run(delivery.deliver_teams(entry)) == "sent"
    assert captured["url"] == "https://flow.test/abc"
    assert captured["payload"]["to"] == "l.novak@zf.com"
    assert "SWAT-10555" in captured["payload"]["subject"]
    assert captured["payload"]["text"] == "hello"


# ============================= v2 Phase-4：审查加固 =============================


def test_health_endpoint(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_clean_addresses():
    from app.delivery import clean_addresses

    # 分号（Outlook 习惯）/逗号混用、多余空白、空项、无 @ 项
    assert clean_addresses("a@zf.com; b@zf.com") == "a@zf.com, b@zf.com"
    assert clean_addresses(" a@zf.com ,, x@y.com ") == "a@zf.com, x@y.com"
    assert clean_addresses("not-an-email; c@zf.com") == "c@zf.com"
    assert clean_addresses("") == ""
    # 含换行的项（邮件头注入）整体丢弃
    assert clean_addresses("a@zf.com\r\nBcc: evil@x.com") == ""


def test_login_throttle_sliding_window():
    import time as time_mod

    from app import main

    # 窗口外的旧失败不计入今天的窗口：4 次新失败（不足 5）不触发锁定
    main._login_failures["ip-x"] = {"fails": [time_mod.time() - 9999], "locked_until": 0}
    assert main._login_remaining_lock("ip-x") == 0
    for _ in range(4):
        main._login_record_failure("ip-x")
    assert main._login_remaining_lock("ip-x") == 0
    # 窗口内第 5 次失败 → 锁定
    main._login_record_failure("ip-x")
    assert main._login_remaining_lock("ip-x") > 0
    # 窗口外无失败且不在锁定期的条目被清理，字典不无界增长
    main._login_failures["ip-y"] = {"fails": [time_mod.time() - 9999], "locked_until": 0}
    main._login_remaining_lock("ip-y")
    assert "ip-y" not in main._login_failures


def test_login_rate_limit(client):
    # 连续 5 次错误口令 → 锁定；锁定期内连正确口令也返回 429。
    # （autouse fixture 会在用例后清空限流表，不必排在最后。）
    for i in range(5):
        r = client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "wrong"})
        assert r.status_code == 401, f"attempt {i + 1}"
    r = client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "wrong"})
    assert r.status_code == 429
    r = client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    assert r.status_code == 429 and "Too many failed" in r.json()["detail"]


# ============================= v2 Phase-9：审批结果邮件 =============================


def _capture_send(monkeypatch):
    from app import delivery

    captured = {}

    async def fake_send(to, subject, body, cc=""):
        captured.update(to=to, subject=subject, body=body)
        return "sent"

    monkeypatch.setattr(delivery, "send_email", fake_send)
    return captured


def test_confirm_notifies_submitter(client, admin, monkeypatch):
    captured = _capture_send(monkeypatch)
    r = client.post("/api/submissions", json=dict(VALID_SUBMISSION, caseNo="swat 71011"))
    sid = r.json()["subId"]
    r = client.post(f"/api/submissions/{sid}/confirm", headers=admin)
    assert r.status_code == 200
    sub = r.json()["submission"]
    assert sub["status"] == "Registration Confirmed"
    assert sub["notify"]["result"] == "sent" and sub["notify"]["approved"] is True
    assert captured["to"] == "test.user@zf.com"  # 提交人 = 登录账号（v3 Phase-6）
    assert captured["subject"] == "Registration Confirmed — Sourcing Case SWAT-71011"
    assert "Baltic Stamping Works" in captured["body"]
    assert "/#case/SWAT-71011" in captured["body"]  # SC_PUBLIC_URL 深链
    # 投递结果随提交单持久化（刷新/重启后仍在）
    snap = client.get("/api/bootstrap").json()
    assert next(s for s in snap["submissions"] if s["subId"] == sid)["notify"]["result"] == "sent"


def test_reject_notifies_with_reason(client, admin, monkeypatch):
    captured = _capture_send(monkeypatch)
    r = client.post("/api/submissions", json=dict(VALID_SUBMISSION, caseNo="swat 71012"))
    sid = r.json()["subId"]
    r = client.post(f"/api/submissions/{sid}/reject", headers=admin, json={"reason": "Supplier not on AVL."})
    assert r.status_code == 200
    sub = r.json()["submission"]
    assert sub["status"] == "Rejected"
    assert sub["notify"]["approved"] is False
    assert captured["subject"] == "Registration Returned — Sourcing Case SWAT-71012"
    assert "Supplier not on AVL." in captured["body"]  # 退回原因必须随邮件送达
    assert "Submit page" in captured["body"]


def test_decision_email_skipped_when_unconfigured(client, admin):
    # 测试环境未配置 SMTP —— 通道缺失不是错误，结果记 skipped
    r = client.post("/api/submissions", json=dict(VALID_SUBMISSION, caseNo="swat 71013"))
    sid = r.json()["subId"]
    r = client.post(f"/api/submissions/{sid}/confirm", headers=admin)
    assert r.status_code == 200
    assert r.json()["submission"]["notify"]["result"] == "skipped"
