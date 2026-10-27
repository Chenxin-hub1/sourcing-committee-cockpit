"""v3 Phase-19：同事试用反馈 —— 缺项一次列全、管理员改周、无模具选项、演示文件即满足演示文稿规则。"""

from __future__ import annotations

from datetime import date

import pytest

from app import logic
from app.config import get_settings
from tests.test_api import VALID_SUBMISSION, _edit_payload, _get_case


@pytest.fixture
def client(api_client):
    return api_client


@pytest.fixture
def admin(client):
    r = client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    assert r.status_code == 200
    return {"X-Session-Token": r.json()["token"]}


@pytest.fixture
def manager(client, admin):
    """Manager 账号：注册后由管理员提升角色（免密登录，邮箱即登录）。"""
    email = "carrie.wang@zf.com"
    client.post("/api/auth/register", json={"name": "Carrie Wang", "email": email})
    assert client.put(f"/api/users/{email}", headers=admin, json={"role": "npi_manager"}).status_code == 200
    r = client.post("/api/auth/login", json={"email": email})
    assert r.status_code == 200, r.text
    return {"X-Session-Token": r.json()["token"]}


def _confirmed_case(client, admin, number="swat 20999"):
    r = client.post("/api/submissions", json={**VALID_SUBMISSION, "caseNo": number})
    assert r.status_code == 200, r.text
    case = client.post(f"/api/submissions/{r.json()['subId']}/confirm", headers=admin).json()["case"]
    return _get_case(client, case["id"])


# ---------- (1) 缺项一次列全 ----------


def test_submission_lists_every_missing_field_at_once(client):
    bad = {**VALID_SUBMISSION, "region": [], "peakYearSpend": 0, "isFamilyCase": "", "involvesECM": "",
           "toolingPayment": "", "partNumbers": [{"partNumber": "99112233", "partDescription": ""}]}
    r = client.post("/api/submissions", json=bad)
    assert r.status_code == 422
    lines = r.json()["detail"].split("\n")
    assert len(lines) >= 6, lines
    for needle in ("Part Number and Part Description", "at least one Region", "bundle Peak Year Spend",
                   '"Is this a Family Case?"', "change management (CCB)", "Pc Price CQA",
                   "Tooling Payment (Lumpsum, MPC or No tooling involved)"):
        assert any(needle in line for line in lines), (needle, lines)


def test_single_problem_still_reads_as_one_message(client):
    r = client.post("/api/submissions", json={**VALID_SUBMISSION, "region": []})
    assert r.status_code == 422 and r.json()["detail"] == "⚠ Please select at least one Region before submitting."


def test_case_edit_lists_every_problem_at_once(client, admin):
    case = _confirmed_case(client, admin)
    task = {"id": "FU-X1", "task": "t", "responsible": "A", "dueDate": "2027-01-01", "status": "Open", "notes": "", "tags": []}
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(
        case, meetingDecision="APPROVED", region="", finalDocLink="not-a-url", followUps=[task]))
    assert r.status_code == 422
    lines = r.json()["detail"].split("\n")
    assert [any(n in line for line in lines) for n in ("Sourcing Presentation", "at least one Region", "Follow-up task 1", "Final PPT")] == [True] * 4


def test_commercial_problems_collects_all():
    out = logic.commercial_problems({"partNumbers": [{}], "decisionLevel": "Level 2", "belowCQA": "No"}, 4_000_000)
    assert len(out) == 5
    assert logic.commercial_problems({"partNumbers": [{}], "toolingPayment": "MPC"}, None) == [out[0]]  # 汇率缺失时不判 BPG


# ---------- (2) 管理员改周 ----------


def test_admin_moves_a_case_to_another_week_and_case_number_follows(client, admin):
    first = _confirmed_case(client, admin, "swat 20991")
    second = _confirmed_case(client, admin, "swat 20992")
    assert (second["weekNum"], second["meetingYear"]) == (40, 2026)
    # 改到 KW41（给的是周五，按那周的周三存）
    r = client.put(f"/api/cases/{second['id']}", headers=admin, json=_edit_payload(second, meetingDate="2026-10-09"))
    assert r.status_code == 200, r.text
    moved = r.json()["case"]
    assert (moved["weekNum"], moved["meetingYear"], moved["meetingDateISO"], moved["meetingDateLabel"]) == (
        41, 2026, "2026-10-07", "Wed, Oct 7, 2026")
    kw41 = [c["caseNumber"] for c in r.json()["snapshot"]["cases"] if c["weekNum"] == 41 and c.get("meetingYear") == 2026 and c["id"] != moved["id"]]
    assert moved["caseNumber"] == (max(kw41) + 1 if kw41 else 1)
    # 改到 2025 年的周：年份跟着变，周标签带 2025
    r = client.put(f"/api/cases/{first['id']}", headers=admin, json=_edit_payload(first, meetingDate="2025-12-17"))
    assert r.status_code == 200
    old = r.json()["case"]
    assert (old["weekNum"], old["meetingYear"], logic.week_label(old)) == (51, 2025, "2025-KW51")
    # 同一周内换一天：不动案例号
    number = old["caseNumber"]
    r = client.put(f"/api/cases/{first['id']}", headers=admin, json=_edit_payload(_get_case(client, first["id"]), meetingDate="2025-12-15"))
    assert r.json()["case"]["caseNumber"] == number and r.json()["case"]["meetingDateISO"] == "2025-12-17"


def test_only_the_sourcing_admin_can_move_a_case(client, admin, manager):
    case = _confirmed_case(client, admin)
    r = client.put(f"/api/cases/{case['id']}", headers=manager, json=_edit_payload(case, meetingDate="2026-10-07"))
    assert r.status_code == 403 and "Sourcing admin" in r.json()["detail"]
    # Manager 带着同一周的日期（编辑页原样回传）照常保存
    r = client.put(f"/api/cases/{case['id']}", headers=manager, json=_edit_payload(case, meetingDate=case["meetingDateISO"]))
    assert r.status_code == 200
    assert client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, meetingDate="2026-13-01")).status_code == 422


def test_move_case_to_week_helper():
    cases = [logic.mk_case({"id": "A", "weekNum": 40, "caseNumber": 3, "meetingYear": 2026}, []),
             logic.mk_case({"id": "B", "weekNum": 40, "caseNumber": 7, "meetingYear": 2025}, []),
             logic.mk_case({"id": "C", "weekNum": 12, "caseNumber": 1, "meetingYear": 2026}, [])]
    assert logic.move_case_to_week(cases[2], date(2026, 10, 1), cases) is True
    assert (cases[2]["weekNum"], cases[2]["caseNumber"], cases[2]["meetingDateISO"]) == (40, 4, "2026-09-30")  # 2025 的 KW40 不算
    assert logic.move_case_to_week(cases[2], date(2026, 9, 28), cases) is False and cases[2]["caseNumber"] == 4


# ---------- (3) No tooling involved ----------


def test_no_tooling_involved_is_a_valid_tooling_payment(client, admin):
    r = client.post("/api/submissions", json={**VALID_SUBMISSION, "toolingPayment": "No tooling involved"})
    assert r.status_code == 200, r.text
    sub = next(s for s in r.json()["snapshot"]["submissions"] if s["subId"] == r.json()["subId"])
    assert sub["toolingPayment"] == "No tooling involved"
    assert client.post("/api/submissions", json={**VALID_SUBMISSION, "caseNo": "swat 20998", "toolingPayment": "None"}).status_code == 422


# ---------- (4) 演示文件即满足演示文稿规则 ----------


def test_uploaded_presentation_file_satisfies_the_presentation_rule(client, admin, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))
    case = _confirmed_case(client, admin)
    approve = _edit_payload(case, meetingDecision="APPROVED")
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=approve)
    assert r.status_code == 422 and "Sourcing Presentation" in r.json()["detail"]
    r = client.post(f"/api/cases/{case['id']}/files", params={"name": "deck.pptx"}, content=b"deck",
                    headers={**admin, "Content-Type": "application/octet-stream"})
    assert r.status_code == 200, r.text
    task = {"id": "FU-P1", "task": "Send samples", "responsible": "A", "dueDate": "2027-01-01", "status": "Open",
            "notes": "", "tags": [], "notifyEmail": "a@zf.com"}
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json={**approve, "followUps": [task]})
    assert r.status_code == 200, r.text
    saved = r.json()["case"]
    assert saved["meetingDecision"] == "APPROVED" and saved["sourcingPresentationLink"] == "" and len(saved["files"]) == 1
    assert logic.validate_case_edit({"meetingDecision": "APPROVED", "region": "EU"}, has_files=True) is None
