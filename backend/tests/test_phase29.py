"""v3 Phase-29（领导 2026-10-16）：待办负责人统一显示全名、职能跟着人走、Follow-ups 页直接编辑。

- 负责人填的是邮箱：有注册账号用账号名字，没有就从邮箱推出名字；本来写的是人名照旧。算好的全名存在 ownerName，
  页面、导出、提醒文字都用它；提醒收件邮箱不变。改账号名 / 注册后重算。
- 职能按人归并：改了一条待办的职能，这个人所有待办一起改；一个人只有一种职能时，空着的待办自动补上。
- PUT /api/tasks/{id}：Manager 及以上改一条待办，门槛与案例编辑页的待办规则一致。
"""

from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app import exports, logic, owners
from tests.test_api import VALID_SUBMISSION, _edit_payload, _get_case
from tests.test_exports import WHEN, _case, _rows, _sheet

ANON = {"X-Session-Token": ""}


def _login(client, email, password=""):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"X-Session-Token": r.json()["token"]}


@pytest.fixture
def admin(api_client):
    return _login(api_client, "admin@zf.com", "test-admin")


@pytest.fixture
def manager(api_client, admin):
    api_client.post("/api/auth/register", json={"email": "npi@zf.com", "name": "NPI Person"}, headers=ANON)
    assert api_client.put("/api/users/npi@zf.com", json={"role": "npi_manager"}, headers=admin).status_code == 200
    return _login(api_client, "npi@zf.com")


TASK = {"id": "FU-P29a", "task": "Track cost recovery with MB", "responsible": "andreas.huber1@zf-lifetec.com",
        "dueDate": "2027-02-18", "status": "Open", "notes": "", "tags": [], "notifyEmail": "andreas.huber1@zf-lifetec.com"}


def _decided_case(client, admin, tasks, **over):
    assert client.post("/api/submissions", json=VALID_SUBMISSION).status_code == 200
    assert client.post("/api/submissions/SUB-0002/confirm", headers=admin).status_code == 200
    case = _get_case(client, "C0023")
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(
        case, meetingDecision="APPROVED", sourcingPresentationLink="https://zf.sharepoint.com/p.pptx", followUps=tasks, **over))
    assert r.status_code == 200, r.text
    return r.json()["case"]


def _tasks(client):
    return {t["id"]: t for c in client.get("/api/bootstrap").json()["cases"] for t in c.get("followUps") or []}


# ---------- 全名 ----------

@pytest.mark.parametrize("email,name", [
    ("andreas.huber1@zf-lifetec.com", "Andreas Huber"),
    ("xin.chen.external@zf-lifetec.com", "Xin Chen"),
    ("MARIO.GONZALEZ1@zf-lifetec.com", "Mario Gonzalez"),
    ("anne-marie_weber@zf.com", "Anne Marie Weber"),
    ("12345@zf.com", "12345@zf.com"),
])
def test_name_is_derived_from_the_email(email, name):
    assert owners.name_from_email(email) == name


def test_display_name_prefers_the_account_name_and_keeps_written_names():
    names = owners.account_names([{"email": "a.huber@zf.com", "name": "Andreas  Huber"},
                                  {"email": "admin@zf.com", "name": "Sourcing admin"}])
    assert names == {"a.huber@zf.com": "Andreas Huber"}  # 启动建的占位管理员名字不拿来显示
    assert owners.display_name("A.Huber@zf.com", names) == "Andreas Huber"
    assert owners.display_name("admin@zf.com", names) == "Admin"
    assert owners.display_name("  Robert   Nieczyporuk ", names) == "Robert Nieczyporuk"
    assert owners.display_name("a.huber@zf.com; mario.rossi@zf.com", names) == "Andreas Huber, Mario Rossi"
    assert owners.display_name("Robert / mario.rossi@zf.com", names) == "Robert / mario.rossi@zf.com"
    assert owners.display_name("", names) == ""


def test_saved_tasks_carry_the_full_name_and_keep_the_reminder_email(api_client, admin):
    _decided_case(api_client, admin, [TASK])
    t = _tasks(api_client)["FU-P29a"]
    assert t["ownerName"] == "Andreas Huber"
    assert t["responsible"] == t["notifyEmail"] == "andreas.huber1@zf-lifetec.com"
    # 种子数据里写的是人名：照旧
    assert _tasks(api_client)["FU-0005"]["ownerName"] == "L. Novak"


def test_registering_and_renaming_an_account_updates_the_owner_name(api_client, admin):
    _decided_case(api_client, admin, [TASK])
    r = api_client.post("/api/auth/register", json={"email": "andreas.huber1@zf-lifetec.com", "name": "Andi Huber"}, headers=ANON)
    assert r.status_code == 200, r.text
    assert _tasks(api_client)["FU-P29a"]["ownerName"] == "Andi Huber"
    r = api_client.put("/api/users/andreas.huber1@zf-lifetec.com", json={"name": "Andreas Huber"}, headers=admin)
    assert r.status_code == 200, r.text
    assert _tasks(api_client)["FU-P29a"]["ownerName"] == "Andreas Huber"


def test_exports_and_messages_show_the_full_name():
    task = {**TASK, "ownerName": "Andreas Huber", "ownerFunction": "Sales"}
    case = _case(swatId="S1", weekNum=42, caseNumber=1, meetingDecision="APPROVED", followUps=[task])
    _, rows = _rows(_sheet(exports.build("minutes", [case], "x", WHEN), "Actions"))
    assert rows[0]["Owner"] == "Andreas Huber" and rows[0]["Function"] == "Sales"
    assert "Owner: Andreas Huber" in logic.reminder_message(case, task)


# ---------- 职能跟着人走 ----------

def _owner_cases():
    return [
        {"id": "C1", "followUps": [{"id": "a", "responsible": "andreas.huber1@zf.com", "ownerFunction": "Sales"},
                                   {"id": "b", "responsible": "Andreas Huber", "ownerFunction": ""}]},
        {"id": "C2", "followUps": [{"id": "c", "responsible": "andreas.huber1@zf.com", "ownerFunction": ""},
                                   {"id": "d", "responsible": "R. Fischer", "ownerFunction": "Quality"},
                                   {"id": "e", "responsible": "R. Fischer", "ownerFunction": "Purchasing"},
                                   {"id": "f", "responsible": "R. Fischer", "ownerFunction": ""}]},
    ]


def test_refresh_fills_empty_functions_only_when_the_person_has_one_function():
    cases = _owner_cases()
    changed = owners.refresh(cases, {})
    t = {x["id"]: x for c in cases for x in c["followUps"]}
    assert t["b"]["ownerFunction"] == t["c"]["ownerFunction"] == "Sales"  # 邮箱与人名是同一个人
    assert t["f"]["ownerFunction"] == ""  # R. Fischer 有两种职能（旧数据）：不猜
    assert [c["id"] for c in changed] == ["C1", "C2"]
    assert owners.refresh(cases, {}) == []  # 幂等


def test_changing_a_function_updates_all_tasks_of_that_owner():
    cases = _owner_cases()
    owners.refresh(cases, {})
    t = {x["id"]: x for c in cases for x in c["followUps"]}
    before = {"a": ("Andreas Huber", "Sales")}
    t["a"]["ownerFunction"] = "Purchasing"
    owners.apply_edits(cases, [t["a"]], before, {})
    assert {t[k]["ownerFunction"] for k in "abc"} == {"Purchasing"}
    # 冲突的旧数据：改一处后统一
    owners.apply_edits(cases, [{**t["d"], "ownerFunction": "Quality"}], {"d": ("R. Fischer", "Purchasing")}, {})
    assert {t[k]["ownerFunction"] for k in "def"} == {"Quality"}


def test_switching_the_owner_takes_the_new_owners_function():
    cases = _owner_cases()
    owners.refresh(cases, {})
    t = {x["id"]: x for c in cases for x in c["followUps"]}
    t["d"]["ownerFunction"] = "Quality"
    t["e"]["ownerFunction"] = "Quality"
    owners.refresh(cases, {})
    # 把 Andreas 的任务改给 R. Fischer，职能框还留着 Sales：换成 R. Fischer 的职能，Andreas 其他任务不受影响
    t["a"]["responsible"] = "R. Fischer"
    owners.apply_edits(cases, [t["a"]], {"a": ("Andreas Huber", "Sales")}, {})
    assert t["a"]["ownerFunction"] == "Quality"
    assert t["b"]["ownerFunction"] == t["c"]["ownerFunction"] == "Sales"


def test_case_save_spreads_the_function_to_the_owners_other_cases(api_client, admin):
    # 种子里 W. Chen 有三条待办（两个案例），都没写职能
    _decided_case(api_client, admin, [{**TASK, "id": "FU-P29w", "responsible": "W. Chen", "ownerFunction": "Purchasing"}])
    tasks = _tasks(api_client)
    assert {tasks[k]["ownerFunction"] for k in ("FU-P29w", "FU-0002", "FU-0002b", "FU-0003")} == {"Purchasing"}


# ---------- Follow-ups 页单条编辑 ----------

def test_manager_edits_one_task_in_place(api_client, admin, manager):
    case = _decided_case(api_client, admin, [TASK, {**TASK, "id": "FU-P29b", "task": "Second"}])
    api_client.post("/api/reminders/manual", headers=admin, json={"taskId": "FU-P29a", "email": TASK["notifyEmail"]})
    r = api_client.put("/api/tasks/FU-P29a", headers=manager, json={
        "task": "Track cost recovery with MB (65K EUR)", "tags": ["Saving"], "responsible": "andreas.huber1@zf-lifetec.com",
        "ownerFunction": "Sales", "dueDate": "2026-09-01", "status": "Open", "notes": "Call on Friday",
        "notifyEmail": "andreas.huber1@zf-lifetec.com", "cc": "boss@zf.com", "channel": "Email"})
    assert r.status_code == 200, r.text
    t = r.json()["task"]
    assert t["task"].endswith("(65K EUR)") and t["cc"] == "boss@zf.com" and t["channel"] == "Email"
    assert t["status"] == "Overdue"  # 截止日已过：与编辑页一样按日期重判
    assert "Saving" in t["categories"] and t["lastReminder"]  # 分类重算、已发提醒记录保留
    after = _get_case(api_client, case["id"])
    assert after["actionStatus"] == "Overdue"
    assert [x["task"] for x in after["followUps"]][1] == "Second"  # 别的待办不动
    assert _tasks(api_client)["FU-P29b"]["ownerFunction"] == "Sales"  # 同一个人：职能跟着走


def test_task_edit_follows_the_case_editor_rules(api_client, admin, manager):
    _decided_case(api_client, admin, [TASK])
    body = {**{k: TASK[k] for k in ("task", "responsible", "dueDate", "notifyEmail")}, "status": "Open"}
    assert api_client.put("/api/tasks/FU-P29a", json=body).status_code == 403  # 普通用户
    assert api_client.put("/api/tasks/FU-nope", headers=manager, json=body).status_code == 404
    r = api_client.put("/api/tasks/FU-P29a", headers=manager, json={**body, "notifyEmail": ""})
    assert r.status_code == 422 and "Send reminder to" in r.json()["detail"]
    # 关掉最后一条开放待办 = 案例闭环：要先在案例页填最终文件链接
    r = api_client.put("/api/tasks/FU-P29a", headers=manager, json={**body, "status": "Closed"})
    assert r.status_code == 422 and "Final PPT" in r.json()["detail"]


def test_closing_a_task_with_the_final_link_closes_the_case(api_client, admin, manager):
    case = _decided_case(api_client, admin, [TASK], finalDocLink="https://zf.sharepoint.com/final.pptx")
    r = api_client.put("/api/tasks/FU-P29a", headers=manager, json={"task": TASK["task"], "status": "Closed", "notifyEmail": ""})
    assert r.status_code == 200, r.text
    assert _get_case(api_client, case["id"])["actionStatus"] == "Closed"


def test_reminder_log_entries_point_at_their_task(monkeypatch):
    monkeypatch.setattr(logic, "na_now", lambda: datetime(2026, 9, 22, 12, tzinfo=ZoneInfo("America/New_York")))
    task = {"id": "FU-log", "task": "due today", "status": "Open", "dueDate": "2026-09-22", "notifyEmail": "a@zf.com"}
    log: list[dict] = []
    logic.run_daily_reminder_check([logic.mk_case({"id": "C1", "swatId": "SWAT-1", "followUps": [task]}, [])],
                                   deepcopy(logic.REMINDER_DEFAULTS), log)
    assert log[0]["taskId"] == "FU-log"
