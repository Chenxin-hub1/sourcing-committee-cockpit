"""v3 Phase-41：Pending 案例也能加待办。

领导 2026-10-29："有的case presented了但是暂时还是pending一些action，before we can approve"；
"但是case改回pending，我就无法save follow up actions"。Pending 案例的待办与其他待办一样提醒、统计、导出；
唯一例外：Pending 案例待办全关不算结案，不要求 Final PPT。
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app import exports, feedback, logic
from tests.test_api import _edit_payload, _get_case
from tests.test_exports import WHEN, _case, _rows, _sheet
from tests.test_phase19 import _confirmed_case

TASK = {"id": "FU-P41", "task": "Share updated quotation", "responsible": "M. Bouzo", "dueDate": "2026-11-09",
        "status": "Open", "notes": "", "tags": [], "notifyEmail": "m.bouzo@example.com"}


@pytest.fixture
def admin(api_client):
    r = api_client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    assert r.status_code == 200
    return {"X-Session-Token": r.json()["token"]}


def _pending_case(tasks):
    return logic.mk_case({"id": "C1", "swatId": "SWAT-1", "meetingDecision": "PENDING", "followUps": tasks}, [])


def test_pending_case_saves_follow_up_tasks_and_closing_them_all_does_not_close_the_case(api_client, admin):
    case = _confirmed_case(api_client, admin)
    assert case["meetingDecision"] == "PENDING" and not case["finalDocLink"]
    r = api_client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, followUps=[TASK]))
    assert r.status_code == 200, r.text
    saved = _get_case(api_client, case["id"])
    assert saved["meetingDecision"] == "PENDING" and [t["task"] for t in saved["followUps"]] == [TASK["task"]]
    assert saved["actionStatus"] == "Open"
    # 待办全关：案例还是 Pending，不算结案，不要求 Final PPT
    r = api_client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(saved, followUps=[{**TASK, "status": "Closed"}]))
    assert r.status_code == 200, r.text
    saved = _get_case(api_client, case["id"])
    assert (saved["meetingDecision"], saved["actionStatus"], saved["finalDocLink"]) == ("PENDING", "Closed", "")
    # 记录决议时规则 2 照旧：待办全关又没有 Final PPT 不能保存
    r = api_client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(
        saved, meetingDecision="APPROVED", sourcingPresentationLink="https://zf.sharepoint.com/x.pptx",
        followUps=[{**TASK, "status": "Closed"}]))
    assert r.status_code == 422 and "Final PPT / Supporting Document Link" in r.json()["detail"]


def test_closing_the_last_task_of_a_pending_case_inline_or_by_approval_needs_no_final_ppt():
    closed = {**TASK, "status": "Closed"}
    assert logic.task_edit_problems(_pending_case([dict(TASK)]), TASK["id"], closed) == []
    decided = {**_pending_case([dict(TASK)]), "meetingDecision": "APPROVED"}
    assert "Final PPT" in logic.task_edit_problems(decided, TASK["id"], closed)[0]

    user = {"name": "Q. Lee", "email": "q.lee@example.com"}
    task = dict(TASK)
    case = _pending_case([task])
    assert feedback.decide(case, task, {"id": "FB-1", "status": feedback.PENDING}, user, feedback.APPROVED, "", "") is None
    assert (task["status"], case["actionStatus"], case["meetingDecision"]) == ("Closed", "Closed", "PENDING")
    task = dict(TASK)
    case = {**_pending_case([task]), "meetingDecision": "APPROVED"}
    error = feedback.decide(case, task, {"id": "FB-1", "status": feedback.PENDING}, user, feedback.APPROVED, "", "")
    assert error and "Final PPT" in error


def test_pending_case_tasks_are_reminded_and_counted(monkeypatch):
    monkeypatch.setattr(logic, "na_now", lambda: datetime(2026, 9, 22, 12, tzinfo=ZoneInfo("America/New_York")))
    due_today = {**TASK, "id": "FU-today", "dueDate": "2026-09-22"}
    late = {**TASK, "id": "FU-late", "dueDate": "2026-09-01"}
    case = _pending_case([due_today, late])
    log: list[dict] = []
    result = logic.run_daily_reminder_check([case], deepcopy(logic.REMINDER_DEFAULTS), log)
    assert "FU-today" in [e["taskId"] for e in log]
    assert late["status"] == "Overdue" and case["actionStatus"] == "Overdue"
    assert (result["openTotal"], result["overdueTotal"]) == (1, 1)


def test_minutes_list_the_tasks_of_a_pending_case():
    with_tasks = _case(caseNumber=3, swatId="SWAT-3", meetingDecision="PENDING", committeeDiscussion="Presented; capacity to confirm.")
    no_tasks = _case(caseNumber=4, swatId="SWAT-4", meetingDecision="PENDING", actionStatus=None, followUps=[],
                     committeeDiscussion="Pending for Sourcing Committee Review")
    data = exports.build("minutes", [with_tasks, no_tasks], "2026-KW39", WHEN)
    _, rows = _rows(_sheet(data, "Minutes"))
    by_no = {r["#"]: r for r in rows if r["#"]}
    assert by_no[3]["Sourcing Decision"] == "Pending" and by_no[3]["Action Status"] == "Open"
    assert by_no[3]["Notes / Task / Resp. / Due Date"] == ("Presented; capacity to confirm.\n"
                                                         "1. Negotiate consignment — SP ABC, due 2027-02-18 [Open]\n"
                                                         "2. Send BP — SP ABC, due 2026-10-01 [Closed]")
    # 没有待办的 Pending 案例还没决议：行动状态留空
    assert by_no[4]["Action Status"] == "" and by_no[4]["Notes / Task / Resp. / Due Date"] == ""
    _, actions = _rows(_sheet(data, "Actions"))
    assert [(a["Task"], a["Sourcing Decision"]) for a in actions] == [("Negotiate consignment", "Pending"), ("Send BP", "Pending")]
