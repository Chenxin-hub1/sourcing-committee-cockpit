"""反馈 PPT 第 2 页（v3 Phase-8）：登记截止时间由管理员配置、服务端强制；截止后可申请例外。

约定：会议固定周三；截止 = 会议前 daysBefore 天的 cutoffTime（timezone 为空时用服务器时区）。
过了截止仍提交该周会议日期 → 422；勾选 lateException 且给出理由 → 接受并带 lateRegistration 标记。
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app import logic
from tests.test_commercial import SUBMISSION

NY = ZoneInfo("America/New_York")


@pytest.fixture
def client(api_client):
    return api_client


@pytest.fixture
def admin(client):
    r = client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    return {"X-Session-Token": r.json()["token"]}


@pytest.fixture(autouse=True)
def _reset_throttles():
    yield
    from app import main
    main._login_failures.clear()
    main._submission_times.clear()


def _freeze(monkeypatch, when: datetime):
    monkeypatch.setattr(logic, "na_now", lambda: when.astimezone(ZoneInfo(logic.get_settings().timezone)))


# ---------- 规则本身 ----------

def test_default_cutoff_is_monday_end_of_day_in_server_timezone():
    s = dict(logic.REGISTRATION_DEFAULTS)
    cutoff = logic.registration_cutoff(date(2026, 9, 30), s)  # 周三
    assert cutoff == datetime(2026, 9, 28, 23, 59, tzinfo=NY)
    assert logic.cutoff_label(s) == "Monday 23:59 (America/New_York)"


def test_custom_cutoff_uses_its_own_timezone():
    s = {"daysBefore": 1, "cutoffTime": "18:00", "timezone": "Europe/Berlin"}
    assert logic.registration_cutoff(date(2026, 9, 30), s) == datetime(2026, 9, 29, 18, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    assert logic.cutoff_label(s) == "Tuesday 18:00 (Europe/Berlin)"


@pytest.mark.parametrize("now,open_", [
    (datetime(2026, 9, 28, 23, 58, tzinfo=NY), True),
    (datetime(2026, 9, 28, 23, 59, tzinfo=NY), True),   # 截止那一分钟仍可提交
    (datetime(2026, 9, 29, 0, 0, tzinfo=NY), False),
    (datetime(2026, 9, 29, 5, 59, tzinfo=ZoneInfo("Europe/Berlin")), True),  # 柏林 05:59 = 纽约 23:59
])
def test_registration_open_compares_in_cutoff_timezone(now, open_):
    assert logic.registration_open(date(2026, 9, 30), dict(logic.REGISTRATION_DEFAULTS), now) is open_


# ---------- 接口 ----------

def test_submission_blocked_after_cutoff_unless_exception(client, monkeypatch):
    _freeze(monkeypatch, datetime(2026, 9, 29, 9, 0, tzinfo=NY))  # 周二早上，周一截止已过
    r = client.post("/api/submissions", json=dict(SUBMISSION, meetingDateISO="2026-09-30"))
    assert r.status_code == 422
    assert "closed" in r.json()["detail"] and "Monday 23:59" in r.json()["detail"]
    # 下周三仍开放
    assert client.post("/api/submissions", json=dict(SUBMISSION, meetingDateISO="2026-10-07")).status_code == 200
    # 例外但没写理由 → 拦
    r = client.post("/api/submissions", json=dict(SUBMISSION, caseNo="SWAT-31020", meetingDateISO="2026-09-30", lateException=True))
    assert r.status_code == 422 and "reason" in r.json()["detail"].lower()
    r = client.post("/api/submissions", json=dict(SUBMISSION, caseNo="SWAT-31020", meetingDateISO="2026-09-30",
                                                   lateException=True, lateReason="Customer escalation, SOP at risk"))
    assert r.status_code == 200, r.text
    sub = next(s for s in r.json()["snapshot"]["submissions"] if s["subId"] == r.json()["subId"])
    assert sub["lateRegistration"] == {"reason": "Customer escalation, SOP at risk", "deadline": "Mon, Sep 28, 2026 23:59 (America/New_York)"}


def test_exception_flag_ignored_when_registration_is_open(client, monkeypatch):
    _freeze(monkeypatch, datetime(2026, 9, 24, 9, 0, tzinfo=NY))
    r = client.post("/api/submissions", json=dict(SUBMISSION, meetingDateISO="2026-09-30", lateException=True, lateReason="not needed"))
    assert r.status_code == 200
    sub = next(s for s in r.json()["snapshot"]["submissions"] if s["subId"] == r.json()["subId"])
    assert "lateRegistration" not in sub


def test_late_flag_carries_into_case_on_confirm(client, admin, monkeypatch):
    _freeze(monkeypatch, datetime(2026, 9, 29, 9, 0, tzinfo=NY))
    r = client.post("/api/submissions", json=dict(SUBMISSION, meetingDateISO="2026-09-30", lateException=True, lateReason="Escalation"))
    sid = r.json()["subId"]
    case = client.post(f"/api/submissions/{sid}/confirm", headers=admin).json()["case"]
    assert case["lateRegistration"]["reason"] == "Escalation"


def test_admin_sets_cutoff_and_it_is_enforced_and_published(client, admin, monkeypatch):
    body = {"daysBefore": 1, "cutoffTime": "18:00", "timezone": "Europe/Berlin"}
    assert client.put("/api/registration-settings", json=body).status_code == 403  # 普通用户不能改
    r = client.put("/api/registration-settings", json=body, headers=admin)
    assert r.status_code == 200
    reg = r.json()["snapshot"]["registrationSettings"]
    assert reg["daysBefore"] == 1 and reg["cutoffTime"] == "18:00" and reg["timezone"] == "Europe/Berlin" and reg["updatedAt"]
    assert client.get("/api/bootstrap").json()["registrationSettings"]["cutoffTime"] == "18:00"
    # 周二柏林 17:00 还开放，19:00 关闭
    _freeze(monkeypatch, datetime(2026, 9, 29, 17, 0, tzinfo=ZoneInfo("Europe/Berlin")))
    assert client.post("/api/submissions", json=dict(SUBMISSION, meetingDateISO="2026-09-30")).status_code == 200
    _freeze(monkeypatch, datetime(2026, 9, 29, 19, 0, tzinfo=ZoneInfo("Europe/Berlin")))
    r = client.post("/api/submissions", json=dict(SUBMISSION, caseNo="SWAT-31021", meetingDateISO="2026-09-30"))
    assert r.status_code == 422 and "Tuesday 18:00 (Europe/Berlin)" in r.json()["detail"]


@pytest.mark.parametrize("body", [
    {"daysBefore": 0}, {"daysBefore": 7}, {"cutoffTime": "25:00"}, {"cutoffTime": "6pm"}, {"timezone": "Mars/Olympus"},
])
def test_registration_settings_validated(client, admin, body):
    assert client.put("/api/registration-settings", json={"daysBefore": 2, "cutoffTime": "23:59", "timezone": "", **body},
                      headers=admin).status_code == 422


# ---------- 复测修复（Phase-11）：会议日期不能留空、必须是周三，否则截止门禁形同虚设 ----------

def test_submission_without_meeting_date_is_rejected(client):
    r = client.post("/api/submissions", json=dict(SUBMISSION, meetingDateISO=""))
    assert r.status_code == 422 and "meeting date" in r.json()["detail"]


def test_submission_on_a_non_wednesday_is_rejected(client):
    r = client.post("/api/submissions", json=dict(SUBMISSION, meetingDateISO="2026-10-05"))  # 周一
    assert r.status_code == 422 and "Wednesday" in r.json()["detail"]
    assert client.post("/api/submissions", json=dict(SUBMISSION, meetingDateISO="2026-10-07")).status_code == 200
