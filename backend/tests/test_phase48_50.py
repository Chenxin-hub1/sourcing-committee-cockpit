"""v3 Phase-48 ~ 50（领导 2026-11-20 截图反馈）。

Phase-48：地区加 CLS（按案例 Region 筛选待办）。
Phase-49：Due 格子直接改截止日——只动截止日一个字段，按新日期重判 Open / Overdue。
Phase-50：关最后一条待办（结案）可上传文件代替 Final PPT 链接；被批准的反馈带了附件也算。
"""

from __future__ import annotations

import pytest

from app import excel_import, exports, feedback, files, logic
from app.config import get_settings
from app.schemas import _regions
from tests.test_api import _edit_payload, _get_case
from tests.test_feedback import ANON, MSG, TASK, TASK2, _attach, _decide, _decided_case, _post, _task


@pytest.fixture(autouse=True)
def _upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))


@pytest.fixture
def sent(monkeypatch):
    from app import delivery

    async def fake(to, subject, body, cc=""):
        return "sent"

    monkeypatch.setattr(delivery, "send_email", fake)


def _login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"X-Session-Token": r.json()["token"]}


@pytest.fixture
def admin(api_client):
    return _login(api_client, "admin@zf.com", "test-admin")


@pytest.fixture
def manager(api_client, admin):
    api_client.post("/api/auth/register", json={"email": "npi@zf.com", "name": "NPI Person", "password": "npi-pass-12345"}, headers=ANON)
    assert api_client.put("/api/users/npi@zf.com", json={"role": "npi_manager"}, headers=admin).status_code == 200
    return _login(api_client, "npi@zf.com", "npi-pass-12345")


def _final_upload(client, row_id, name="KW40 MM.xlsx", headers=None, body=b"x" * 10):
    return client.post(f"/api/cases/{row_id}/final-files", params={"name": name}, content=body,
                       headers={"Content-Type": MSG, **(headers or {})})


# ---------- Phase-48：CLS 地区 ----------


def test_cls_is_a_fourth_region_stored_after_the_others():
    assert _regions(["CLS", "EU"]) == "EU + CLS"
    assert _regions("CLS + AP + NA + EU") == "AP + EU + NA + CLS"
    assert _regions("EU + NA") == "EU + NA"  # 旧写法不变
    with pytest.raises(ValueError, match="Use AP, EU, NA or CLS"):
        _regions(["LATAM"])


def test_cls_case_saves_and_sorts_after_the_three_regions(api_client, admin):
    case = _decided_case(api_client, admin, [TASK], region="EU + CLS")
    assert _get_case(api_client, case["id"])["region"] == "EU + CLS"
    assert exports.REGION_ORDER[-1] == "CLS"
    assert excel_import.normalize_region("eu / cls") == "EU + CLS"
    assert excel_import.normalize_region("CLS8 Program") == "CLS8 Program"  # 项目名里的 CLS8 不算地区


# ---------- Phase-49：只改截止日 ----------


def test_due_date_endpoint_changes_only_the_date_and_recomputes_the_status(api_client, admin, manager):
    case = _decided_case(api_client, admin, [{**TASK, "dueDate": "", "notes": "keep me"}, TASK2],
                         finalDocLink="https://zf.sharepoint.com/f.pptx")
    r = api_client.put("/api/tasks/FU-FB1/due-date", json={"dueDate": "2026-09-01"}, headers=manager)
    assert r.status_code == 200, r.text
    c, t = _task(api_client, "FU-FB1")
    assert (t["dueDate"], t["status"], t["notes"], t["notifyEmail"]) == ("2026-09-01", "Overdue", "keep me", "sp.abc@zf.com")
    assert c["actionStatus"] == "Overdue"
    assert api_client.put("/api/tasks/FU-FB1/due-date", json={"dueDate": "2027-01-15"}, headers=manager).status_code == 200
    c, t = _task(api_client, "FU-FB1")
    assert (t["dueDate"], t["status"], c["actionStatus"]) == ("2027-01-15", "Open", "Open")
    # 清掉截止日：回到 Open
    api_client.put("/api/tasks/FU-FB1/due-date", json={"dueDate": "2026-09-01"}, headers=manager)
    assert api_client.put("/api/tasks/FU-FB1/due-date", json={"dueDate": ""}, headers=manager).status_code == 200
    _, t = _task(api_client, "FU-FB1")
    assert (t["dueDate"], t["status"]) == ("", "Open")
    assert case["id"] == c["id"]


def test_due_date_on_a_closed_task_keeps_it_closed():
    task = {**TASK, "status": "Closed"}
    case = {"followUps": [task]}
    logic.set_task_due_date(case, task, "2026-01-01")
    assert (task["status"], case["actionStatus"]) == ("Closed", "Closed")


def test_due_date_endpoint_permissions_and_validation(api_client, admin, manager):
    _decided_case(api_client, admin, [TASK])
    assert api_client.put("/api/tasks/FU-FB1/due-date", json={"dueDate": "2027-01-15"}, headers=ANON).status_code == 401
    assert api_client.put("/api/tasks/FU-NOPE/due-date", json={"dueDate": "2027-01-15"}, headers=manager).status_code == 404
    assert api_client.put("/api/tasks/FU-FB1/due-date", json={"dueDate": "15.01.2027"}, headers=manager).status_code == 422


# ---------- Phase-50：结案文件 ----------


def test_uploaded_file_lets_the_last_follow_up_close_by_approval(api_client, admin, manager, sent):
    case = _decided_case(api_client, admin, [TASK])
    fb = _post(api_client, "FU-FB1").json()["feedback"]
    r = _decide(api_client, "FU-FB1", fb["id"], "approved", manager)
    assert r.status_code == 422 and "or attach the file" in r.json()["detail"]
    r = _final_upload(api_client, case["id"], "Re_ closure confirmed.msg", headers=manager)
    assert r.status_code == 200, r.text
    rec = r.json()["file"]
    assert rec["name"] == "Re_ closure confirmed.msg"  # 结案文件保留原名，不按案例改名
    r = _decide(api_client, "FU-FB1", fb["id"], "approved", manager)
    assert r.status_code == 200, r.text
    case = r.json()["case"]
    assert case["actionStatus"] == "Closed" and case["finalDocLink"] == ""
    assert [f["id"] for f in case["finalDocFiles"]] == [rec["id"]]
    assert api_client.get(f"/api/files/{rec['id']}", headers=ANON).content == b"x" * 10


def test_feedback_with_an_attachment_is_enough_to_close_the_case(api_client, admin, manager, sent):
    _decided_case(api_client, admin, [TASK])
    fb = _post(api_client, "FU-FB1").json()["feedback"]
    assert _attach(api_client, "FU-FB1", fb["id"], "KW40 minutes.pdf").status_code == 200
    r = _decide(api_client, "FU-FB1", fb["id"], "approved", manager)
    assert r.status_code == 200, r.text
    case = r.json()["case"]
    assert case["actionStatus"] == "Closed"
    assert [f["name"] for f in logic.closing_evidence(case)] == ["KW40 minutes.pdf"]
    # 之后在编辑页保存这个已结案的案例，不会因为没有链接被规则 2 拦住
    r = api_client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, committeeDiscussion="noted"))
    assert r.status_code == 200, r.text


def test_case_editor_and_inline_edit_accept_an_uploaded_final_file(api_client, admin, manager):
    case = _decided_case(api_client, admin, [TASK, TASK2])
    closed = [{**TASK, "status": "Closed"}, {**TASK2, "status": "Closed"}]
    r = api_client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, followUps=closed))
    assert r.status_code == 422 and "or attach the file" in r.json()["detail"]
    # Follow-ups 页单条编辑关最后一条：提示去案例页补链接或文件
    api_client.put(f"/api/tasks/{TASK['id']}", headers=manager, json={**TASK, "status": "Closed"})
    r = api_client.put(f"/api/tasks/{TASK2['id']}", headers=manager, json={**TASK2, "status": "Closed"})
    assert r.status_code == 422 and "(link or file)" in r.json()["detail"]
    assert _final_upload(api_client, case["id"], "Final.pptx", headers=manager).status_code == 200
    r = api_client.put(f"/api/tasks/{TASK2['id']}", headers=manager, json={**TASK2, "status": "Closed"})
    assert r.status_code == 200, r.text
    saved = _get_case(api_client, case["id"])
    assert saved["actionStatus"] == "Closed"
    r = api_client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(saved, followUps=saved["followUps"]))
    assert r.status_code == 200, r.text
    assert [f["name"] for f in _get_case(api_client, case["id"])["finalDocFiles"]] == ["Final.pptx"]  # 编辑保存不擦文件


def test_final_file_upload_rules_and_removal(api_client, admin, manager):
    case = _decided_case(api_client, admin, [TASK])
    assert _final_upload(api_client, case["id"], headers=ANON).status_code == 401
    assert _final_upload(api_client, case["id"], "tool.exe", headers=manager).status_code == 422
    assert _final_upload(api_client, "C-NOPE", headers=manager).status_code == 404
    rec = _final_upload(api_client, case["id"], "mail.eml", headers=manager).json()["file"]
    assert api_client.delete(f"/api/cases/{case['id']}/final-files/{rec['id']}", headers=ANON).status_code == 401
    r = api_client.delete(f"/api/cases/{case['id']}/final-files/{rec['id']}", headers=manager)
    assert r.status_code == 200 and r.json()["case"]["finalDocFiles"] == []
    assert not list((files.upload_root()).rglob("mail.eml"))
    assert api_client.delete(f"/api/cases/{case['id']}/final-files/{rec['id']}", headers=manager).status_code == 404


def test_last_final_file_of_a_closed_case_cannot_be_removed(api_client, admin, manager, sent):
    case = _decided_case(api_client, admin, [TASK])
    rec = _final_upload(api_client, case["id"], "Final.pdf", headers=manager).json()["file"]
    fb = _post(api_client, "FU-FB1").json()["feedback"]
    assert _decide(api_client, "FU-FB1", fb["id"], "approved", manager).status_code == 200
    r = api_client.delete(f"/api/cases/{case['id']}/final-files/{rec['id']}", headers=manager)
    assert r.status_code == 422 and "only final document" in r.json()["detail"]
    other = _final_upload(api_client, case["id"], "Final v2.pdf", headers=manager).json()["file"]
    assert api_client.delete(f"/api/cases/{case['id']}/final-files/{rec['id']}", headers=manager).status_code == 200
    assert [f["id"] for f in _get_case(api_client, case["id"])["finalDocFiles"]] == [other["id"]]


def test_final_files_are_deleted_with_the_case(api_client, admin, manager):
    case = _decided_case(api_client, admin, [TASK])
    rec = _final_upload(api_client, case["id"], "Final.pdf", headers=manager).json()["file"]
    r = api_client.delete(f"/api/cases/{case['swatId']}", headers=admin)
    assert r.status_code == 200 and r.json()["filesRemoved"] >= 1
    assert api_client.get(f"/api/files/{rec['id']}", headers=ANON).status_code == 404


def test_decide_counts_feedback_files_and_case_files_but_not_others():
    user = {"name": "Q", "email": "q@zf.com"}
    for case_extra, fb_files, ok in (({}, [], False), ({}, [{"id": "F1"}], True),
                                     ({"finalDocFiles": [{"id": "F2"}]}, [], True)):
        task = dict(TASK)
        case = {"meetingDecision": "APPROVED", "followUps": [task], **case_extra}
        fb = {"id": "FB-1", "status": feedback.PENDING, "files": fb_files}
        assert (feedback.decide(case, task, fb, user, feedback.APPROVED, "", "") is None) is ok


def test_clearing_the_due_date_in_the_case_editor_turns_overdue_back_to_open(api_client, admin):
    """编辑页清空截止日：没有截止日就谈不上逾期，回到 Open（之前会停在 Overdue）。"""
    late = {**TASK, "dueDate": "2026-09-01"}
    case = _decided_case(api_client, admin, [late, TASK2])
    r = api_client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, followUps=[late, TASK2]))
    assert r.status_code == 200, r.text
    saved = _get_case(api_client, case["id"])
    assert saved["followUps"][0]["status"] == "Overdue"
    cleared = [{**saved["followUps"][0], "dueDate": ""}, saved["followUps"][1]]
    r = api_client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(saved, followUps=cleared))
    assert r.status_code == 200, r.text
    t = _get_case(api_client, case["id"])["followUps"][0]
    assert (t["dueDate"], t["status"]) == ("", "Open")


def test_daily_check_turns_an_overdue_task_without_due_date_back_to_open():
    """每日检查：旧数据里没有截止日却停在 Overdue 的待办改回 Open，案例状态跟着重算；不发提醒。"""
    stuck = {"id": "FU-1", "task": "no date", "status": "Overdue", "dueDate": "—", "notifyEmail": "a@zf.com"}
    blank = {"id": "FU-2", "task": "blank", "status": "Overdue", "dueDate": "", "notifyEmail": "a@zf.com"}
    done = {"id": "FU-3", "task": "done", "status": "Closed", "dueDate": ""}
    case = logic.mk_case({"id": "C1", "swatId": "SWAT-1", "followUps": [stuck, blank, done]}, [])
    case["actionStatus"] = "Overdue"
    log: list = []
    result = logic.run_daily_reminder_check([case], dict(logic.REMINDER_DEFAULTS, enabled=True), log)
    assert [t["status"] for t in case["followUps"]] == ["Open", "Open", "Closed"]
    assert case["actionStatus"] == "Open"
    assert result["changed"] == ["C1"] and result["sent"] == 0 and log == []
