"""v3 Phase-14：待办反馈与关闭审批（反馈 PPT 第 4、11 页）。

任何登录用户对开放待办提交反馈（文字 + 附件，另允许 .msg / .eml）；NPI 经理及以上 approve（待办 Closed，
最后一条开放待办须有最终文件链接）或 reject（必须写进一步要求）；提交通知全部 NPI 经理 / 管理员，结果邮件给待办收件人抄送反馈人。
"""

import pytest

from app import delivery, feedback, files, logic
from app.config import get_settings
from tests.test_api import VALID_SUBMISSION, _edit_payload, _get_case

MSG = "application/vnd.ms-outlook"
ANON = {"X-Session-Token": ""}


@pytest.fixture(autouse=True)
def _upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))


@pytest.fixture
def sent(monkeypatch):
    """截获外发邮件：记录 (to, subject, body, cc)，回 sent。"""
    calls = []

    async def fake(to, subject, body, cc=""):
        calls.append({"to": to, "subject": subject, "body": body, "cc": cc})
        return "sent"

    monkeypatch.setattr(delivery, "send_email", fake)
    return calls


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


TASK = {"id": "FU-FB1", "task": "Negotiate consignment", "responsible": "SP ABC", "dueDate": "2027-02-18",
        "status": "Open", "notes": "", "tags": ["Saving"], "notifyEmail": "sp.abc@zf.com"}
TASK2 = {**TASK, "id": "FU-FB2", "task": "Send BPG", "notifyEmail": "bp@zf.com"}


def _decided_case(client, admin, tasks, **over):
    assert client.post("/api/submissions", json=VALID_SUBMISSION).status_code == 200
    assert client.post("/api/submissions/SUB-0002/confirm", headers=admin).status_code == 200
    case = _get_case(client, "C0023")
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(
        case, meetingDecision="APPROVED", sourcingPresentationLink="https://zf.sharepoint.com/p.pptx", followUps=tasks, **over))
    assert r.status_code == 200, r.text
    return r.json()["case"]


def _task(client, task_id):
    for c in client.get("/api/bootstrap").json()["cases"]:
        for t in c.get("followUps") or []:
            if t["id"] == task_id:
                return c, t
    raise AssertionError(task_id)


def _post(client, task_id, text="BP 50K negotiated, committed for 2026", headers=None):
    return client.post(f"/api/tasks/{task_id}/feedback", json={"text": text}, headers=headers or {})


def _attach(client, task_id, fb_id, name, body=b"x" * 10, headers=None):
    return client.post(f"/api/tasks/{task_id}/feedback/{fb_id}/files", params={"name": name}, content=body,
                       headers={"Content-Type": MSG, **(headers or {})})


def _decide(client, task_id, fb_id, decision, headers, **extra):
    return client.post(f"/api/tasks/{task_id}/feedback/{fb_id}/decision", json={"decision": decision, **extra}, headers=headers)


# ---------- 提交反馈 ----------

def test_feedback_needs_login_text_and_an_open_task(api_client, admin, sent):
    _decided_case(api_client, admin, [TASK])
    assert _post(api_client, "FU-FB1", headers=ANON).status_code == 401
    assert _post(api_client, "FU-FB1", text="   ").status_code == 422
    assert _post(api_client, "FU-NOPE").status_code == 404
    r = _post(api_client, "FU-FB1")
    assert r.status_code == 200, r.text
    fb = r.json()["feedback"]
    assert fb["status"] == "pending" and fb["by"] == "Test User" and fb["byEmail"] == "test.user@zf.com"
    assert fb["text"] == "BP 50K negotiated, committed for 2026" and fb["files"] == [] and fb["decision"] is None
    # 通知全部 NPI 经理 / 管理员（这里只有 bootstrap 管理员），信里有案例链接与反馈原文
    assert fb["notify"]["to"] == "admin@zf.com" and fb["notify"]["result"] == "sent"
    assert sent[-1]["to"] == "admin@zf.com" and "BP 50K negotiated" in sent[-1]["body"]
    assert "/#case/SWAT-20999" in sent[-1]["body"] and "SWAT-20999" in sent[-1]["subject"]
    # 快照里待办带着这条反馈；待办本身仍 Open
    _, task = _task(api_client, "FU-FB1")
    assert task["status"] == "Open" and [f["id"] for f in task["feedback"]] == [fb["id"]]


def test_no_feedback_on_closed_task_and_notice_lists_every_approver(api_client, admin, manager, sent):
    _decided_case(api_client, admin, [TASK, {**TASK2, "status": "Closed"}])
    r = _post(api_client, "FU-FB2")
    assert r.status_code == 422 and "already Closed" in r.json()["detail"]
    fb = _post(api_client, "FU-FB1").json()["feedback"]
    assert fb["notify"]["to"] == "admin@zf.com, npi@zf.com"


def test_feedback_without_any_approver_account_is_skipped_not_failed(api_client, admin, sent, monkeypatch):
    _decided_case(api_client, admin, [TASK])
    from app import service

    async def no_users(session):
        return []

    monkeypatch.setattr(service, "list_users", no_users)
    before = len(sent)  # 确认登记的邮件已经发过一封
    fb = _post(api_client, "FU-FB1").json()["feedback"]
    assert fb["notify"]["result"].startswith("skipped") and len(sent) == before


# ---------- 附件 ----------

def test_attachments_allow_outlook_mail_only_while_pending_and_only_by_author_or_manager(api_client, admin, manager, sent):
    _decided_case(api_client, admin, [TASK])
    fb = _post(api_client, "FU-FB1").json()["feedback"]
    r = _attach(api_client, "FU-FB1", fb["id"], "closure.msg")
    assert r.status_code == 200, r.text
    rec = r.json()["file"]
    assert rec["name"] == "closure.msg" and rec["uploadedBy"] == "Test User" and rec["store"] == "local"
    r = _attach(api_client, "FU-FB1", fb["id"], "tool.exe")
    assert r.status_code == 422 and ".msg" in r.json()["detail"] and "Outlook" in r.json()["detail"]
    assert files.clean_name("mail.msg") is None  # 演示文件的白名单没有放宽
    # 别的普通用户不能给这条反馈加附件；NPI 经理可以
    api_client.post("/api/auth/register", json={"email": "other@zf.com", "name": "Other", "password": "other-pass-123"}, headers=ANON)
    other = _login(api_client, "other@zf.com", "other-pass-123")
    assert _attach(api_client, "FU-FB1", fb["id"], "x.eml", headers=other).status_code == 403
    assert _attach(api_client, "FU-FB1", fb["id"], "x.eml", headers=manager).status_code == 200
    # 所有人可下载
    _, task = _task(api_client, "FU-FB1")
    assert [f["name"] for f in task["feedback"][0]["files"]] == ["closure.msg", "x.eml"]
    r = api_client.get(f"/api/files/{rec['id']}", headers=ANON)
    assert r.status_code == 200 and r.content == b"x" * 10
    # 审批之后不能再加
    assert _decide(api_client, "FU-FB1", fb["id"], "rejected", manager, remark="Need the signed BP").status_code == 200
    r = _attach(api_client, "FU-FB1", fb["id"], "late.msg")
    assert r.status_code == 422 and "already rejected" in r.json()["detail"]
    assert _attach(api_client, "FU-FB1", "FB-nope", "x.msg").status_code == 404
    assert not list((files.upload_root() / ".incoming").glob("*"))


# ---------- 审批 ----------

def test_approve_closes_the_task_and_mails_the_owner_with_author_in_cc(api_client, admin, manager, sent):
    _decided_case(api_client, admin, [TASK, TASK2])
    fb = _post(api_client, "FU-FB1").json()["feedback"]
    assert _decide(api_client, "FU-FB1", fb["id"], "approved", {}).status_code == 403  # 普通用户不能审批
    r = _decide(api_client, "FU-FB1", fb["id"], "approved", manager, remark="Well done")
    assert r.status_code == 200, r.text
    case = r.json()["case"]
    task = next(t for t in case["followUps"] if t["id"] == "FU-FB1")
    assert task["status"] == "Closed" and task["closure"]["by"] == "NPI Person" and task["closure"]["feedbackId"] == fb["id"]
    assert case["actionStatus"] == "Open"  # 另一条待办还开着
    saved = task["feedback"][0]
    assert saved["status"] == "approved" and saved["decision"]["by"] == "NPI Person" and saved["decision"]["remark"] == "Well done"
    assert saved["decision"]["notify"] == {**saved["decision"]["notify"], "to": "sp.abc@zf.com", "cc": "test.user@zf.com", "result": "sent"}
    mail = sent[-1]
    assert mail["to"] == "sp.abc@zf.com" and mail["cc"] == "test.user@zf.com"
    assert "Follow-up closed" in mail["subject"] and "now Closed" in mail["body"] and "Remark: Well done" in mail["body"]
    # 已审批的不能再审
    r = _decide(api_client, "FU-FB1", fb["id"], "rejected", manager, remark="x")
    assert r.status_code == 422 and "already approved" in r.json()["detail"]


def test_reject_needs_a_remark_and_keeps_the_task_open(api_client, admin, manager, sent):
    _decided_case(api_client, admin, [TASK])
    fb = _post(api_client, "FU-FB1").json()["feedback"]
    r = _decide(api_client, "FU-FB1", fb["id"], "rejected", manager, remark="  ")
    assert r.status_code == 422 and "remark" in r.json()["detail"]
    r = _decide(api_client, "FU-FB1", fb["id"], "rejected", manager, remark="Negotiate another 0.02 EUR/pc")
    assert r.status_code == 200
    task = next(t for t in r.json()["case"]["followUps"] if t["id"] == "FU-FB1")
    assert task["status"] == "Open" and "closure" not in task
    assert task["feedback"][0]["status"] == "rejected"
    assert "not accepted" in sent[-1]["subject"] and "Further action: Negotiate another 0.02 EUR/pc" in sent[-1]["body"]
    # 被退回后还能再提交一条反馈；未知决议值 422
    assert _post(api_client, "FU-FB1", text="Done: 0.02 achieved").status_code == 200
    assert api_client.post(f"/api/tasks/FU-FB1/feedback/{fb['id']}/decision", json={"decision": "maybe"}, headers=manager).status_code == 422


def test_closing_the_last_open_task_needs_the_final_document_link(api_client, admin, manager, sent):
    _decided_case(api_client, admin, [TASK])
    fb = _post(api_client, "FU-FB1").json()["feedback"]
    r = _decide(api_client, "FU-FB1", fb["id"], "approved", manager)
    assert r.status_code == 422 and "Final PPT / Supporting Document Link" in r.json()["detail"]
    r = _decide(api_client, "FU-FB1", fb["id"], "approved", manager, finalDocLink="sharepoint/x.pptx")
    assert r.status_code == 422 and "full URL" in r.json()["detail"]
    _, task = _task(api_client, "FU-FB1")
    assert task["status"] == "Open" and task["feedback"][0]["status"] == "pending"  # 被拒的审批不落库
    r = _decide(api_client, "FU-FB1", fb["id"], "approved", manager, finalDocLink="https://zf.sharepoint.com/final.pptx")
    assert r.status_code == 200, r.text
    case = r.json()["case"]
    assert case["finalDocLink"] == "https://zf.sharepoint.com/final.pptx" and case["actionStatus"] == "Closed"
    assert case["followUps"][0]["status"] == "Closed"


def test_case_with_final_link_closes_without_asking_again(api_client, admin, manager, sent):
    _decided_case(api_client, admin, [TASK], finalDocLink="https://zf.sharepoint.com/f.pptx")
    fb = _post(api_client, "FU-FB1").json()["feedback"]
    r = _decide(api_client, "FU-FB1", fb["id"], "approved", manager)
    assert r.status_code == 200, r.text
    assert r.json()["case"]["actionStatus"] == "Closed" and r.json()["case"]["finalDocLink"] == "https://zf.sharepoint.com/f.pptx"
    assert sent[-1]["to"] == "sp.abc@zf.com" and sent[-1]["cc"] == "test.user@zf.com"


# ---------- 与编辑页、案例文件的配合 ----------

def test_case_editor_save_keeps_feedback_and_closure(api_client, admin, manager, sent):
    case = _decided_case(api_client, admin, [TASK, TASK2])
    fb = _post(api_client, "FU-FB1").json()["feedback"]
    assert _decide(api_client, "FU-FB1", fb["id"], "approved", manager).status_code == 200
    fb2 = _post(api_client, "FU-FB2").json()["feedback"]
    case = _get_case(api_client, case["id"])
    # 浏览器带着过期快照（没有 feedback / closure）保存编辑：服务端保留自己的记录
    stale = [{k: v for k, v in t.items() if k not in ("feedback", "closure")} for t in case["followUps"]]
    r = api_client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, followUps=stale))
    assert r.status_code == 200, r.text
    tasks = {t["id"]: t for t in r.json()["case"]["followUps"]}
    assert tasks["FU-FB1"]["closure"]["feedbackId"] == fb["id"] and tasks["FU-FB1"]["feedback"][0]["status"] == "approved"
    assert tasks["FU-FB2"]["feedback"][0]["id"] == fb2["id"] and tasks["FU-FB2"]["feedback"][0]["status"] == "pending"
    # 编辑页把待办删掉，反馈随之消失（只剩已关闭的待办 → 规则 2 要最终链接）
    r = api_client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(
        case, followUps=[stale[0]], finalDocLink="https://zf.sharepoint.com/f.pptx"))
    assert r.status_code == 200 and [t["id"] for t in r.json()["case"]["followUps"]] == ["FU-FB1"]


def test_decision_email_texts_and_recipients():
    case = {"swatId": "SWAT-1", "partDescription": "Part", "partNumber": "PN", "partNumbers": [{}, {}], "followUps": []}
    task = {"task": "Do it", "responsible": "R", "dueDate": "2027-01-01", "notifyEmail": "owner@zf.com"}
    fb = {"by": "Jane", "byEmail": "jane@zf.com", "when": "Sep 28, 9:00 AM", "text": "done", "status": "rejected",
          "decision": {"by": "Mgr", "when": "Sep 28, 10:00 AM", "remark": "more"}}
    subject, body = feedback.decision_email(case, task, fb, base_url="http://x/")
    assert subject == "Follow-up feedback not accepted — Sourcing Case SWAT-1"
    assert "Part Number: PN (+1 more)" in body and "Further action: more" in body and body.endswith("http://x/#case/SWAT-1")
    assert feedback.decision_recipients(task, fb) == ("owner@zf.com", "jane@zf.com")
    assert feedback.decision_recipients({"notifyEmail": "Jane@zf.com"}, fb) == ("Jane@zf.com", "")
    assert feedback.decision_recipients({"notifyEmail": ""}, fb) == ("jane@zf.com", "")  # 旧待办没邮箱：发给反馈人
    assert logic.case_link({"swatId": "SWAT 1/2"}, "http://x") == "http://x/#case/SWAT%201%2F2"
