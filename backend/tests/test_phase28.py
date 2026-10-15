"""v3 Phase-28（领导 2026-10-15）：Presenter 可填可改、Agenda / MM 按级别与地区排序、导出按会议命名。

- 提交页 Presenter 默认是提交人，可以改成实际上会讲的人；留空回退到提交账号的名字。管理员能在 Accounts 页改账号名。
- Agenda、MM（含 Actions 表）每周内按 级别 L2 → L3 → L4 → 未填、地区 AP → EU → NA、案例号 排；
  多区域案例按勾选里最靠前的地区归组。
- 文件名与委员会历史文件一致：`KW42 14.10.2026_SBS Sourcing Alignment Committee_Agenda.xlsx`（纪要结尾 `_MM`），
  跨多周 `KW42-KW43 2026_…`，系统的周会 Excel 导入能从这个名字认回 KW 与会议日期。
"""

from datetime import date

import pytest

from app import excel_import, exports
from tests.test_accounts import _login_by_email, _register
from tests.test_api import VALID_SUBMISSION
from tests.test_exports import WHEN, _case, _rows, _sheet


@pytest.fixture
def admin(api_client):
    r = api_client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    return {"X-Session-Token": r.json()["token"]}


# ---------- 排序 ----------

def _c(swat, week, num, level, region="EU", year=2026, **over):
    return _case(swatId=swat, weekNum=week, caseNumber=num, decisionLevel=f"Level {level}" if level else "",
                 region=region, meetingYear=year, **over)


CASES = [
    _c("43-L4", 43, 1, 4), _c("43-L2", 43, 2, 2),
    _c("42-L4-EU", 42, 1, 4), _c("42-L4-AP", 42, 9, 4, region="AP"),
    _c("42-L2-NA", 42, 2, 2, region="NA"), _c("42-L2-EU+NA", 42, 3, 2, region="EU + NA"),
    _c("42-L2-AP+EU", 42, 8, 2, region="AP + EU"), _c("42-L2-EU", 42, 4, 2),
    _c("42-L3-NA", 42, 5, 3, region="NA"), _c("42-none", 42, 6, None), _c("42-noregion", 42, 7, 3, region=""),
    _c("2025-42-L4", 42, 1, 4, year=2025),
]
EXPECTED = ["2025-42-L4",
            "42-L2-AP+EU", "42-L2-EU+NA", "42-L2-EU", "42-L2-NA", "42-L3-NA", "42-noregion", "42-L4-AP", "42-L4-EU", "42-none",
            "43-L2", "43-L4"]


@pytest.mark.parametrize("kind,sheet", [("agenda", "Agenda"), ("minutes", "Minutes")])
def test_agenda_and_minutes_order_each_week_by_level_then_region(kind, sheet):
    data = exports.build(kind, CASES, "Database export", WHEN)
    ws = _sheet(data, sheet)
    _, rows = _rows(ws)
    assert [r["SWAT ID / Bundle ID"] for r in rows] == EXPECTED
    assert "L2, L3, then L4" in ws["A2"].value and "AP, EU, NA" in ws["A2"].value


def test_minutes_actions_follow_the_same_case_order():
    cases = [_c("L4", 42, 1, 4, followUps=[{"id": "FU-a", "task": "Task of L4", "status": "Open"}]),
             _c("L2", 42, 2, 2, followUps=[{"id": "FU-b", "task": "Task of L2", "status": "Open"}])]
    _, rows = _rows(_sheet(exports.build("minutes", cases, "x", WHEN), "Actions"))
    assert [r["Task"] for r in rows] == ["Task of L2", "Task of L4"]


# ---------- 文件名 ----------

def test_single_week_file_is_named_like_the_committee_files():
    cases = [_c("A", 42, 1, 2, meetingDateISO="2026-10-14"), _c("B", 42, 2, 4, meetingDateISO="2026-10-14")]
    assert exports.filename("agenda", cases) == "KW42 14.10.2026_SBS Sourcing Alignment Committee_Agenda.xlsx"
    assert exports.filename("minutes", cases) == "KW42 14.10.2026_SBS Sourcing Alignment Committee_MM.xlsx"


def test_single_week_without_a_meeting_date_uses_the_wednesday_of_that_week():
    cases = [_c("A", 42, 1, 2, meetingDateISO="", meetingDateLabel="")]
    assert exports.filename("agenda", cases) == "KW42 14.10.2026_SBS Sourcing Alignment Committee_Agenda.xlsx"
    # 同一周里会议日期不一致（导入的旧文件有时写准备日）：取不准就用那周的周三
    mixed = [_c("A", 42, 1, 2, meetingDateISO="2026-10-13"), _c("B", 42, 2, 2, meetingDateISO="2026-10-14")]
    assert exports.filename("agenda", mixed) == "KW42 14.10.2026_SBS Sourcing Alignment Committee_Agenda.xlsx"


def test_several_weeks_name_the_first_and_last_week():
    two = [_c("A", 43, 1, 2), _c("B", 42, 1, 2), _c("C", 45, 1, 2)]
    assert exports.filename("agenda", two) == "KW42-KW45 2026_SBS Sourcing Alignment Committee_Agenda.xlsx"
    across = [_c("A", 52, 1, 2, year=2025), _c("B", 1, 1, 2, year=2026)]
    assert exports.filename("minutes", across) == "KW52 2025-KW01 2026_SBS Sourcing Alignment Committee_MM.xlsx"
    assert exports.filename("agenda", [_c("A", 5, 1, 2, meetingDateISO="2026-01-28")]).startswith("KW05 28.01.2026_")


def test_empty_selection_falls_back_to_the_requested_week_or_today():
    assert exports.filename("agenda", [], week=(2026, 42)) == "KW42 14.10.2026_SBS Sourcing Alignment Committee_Agenda.xlsx"
    assert exports.filename("minutes", [], today=date(2026, 10, 15)) == "15.10.2026_SBS Sourcing Alignment Committee_MM.xlsx"


def test_the_weekly_excel_import_reads_the_week_and_date_back_from_the_name():
    name = exports.filename("minutes", [_c("A", 42, 1, 2, meetingDateISO="2026-10-14")])
    assert excel_import.meeting_from_name(name) == (42, date(2026, 10, 14))


def test_endpoints_send_the_committee_file_name(api_client):
    r = api_client.get("/api/exports/agenda", params={"week": 42, "year": 2026})
    assert r.status_code == 200
    assert 'filename="KW42 14.10.2026_SBS Sourcing Alignment Committee_Agenda.xlsx"' in r.headers["content-disposition"]
    cases = api_client.get("/api/bootstrap").json()["cases"]
    week = max(c["weekNum"] for c in cases)
    picked = [c for c in cases if c["weekNum"] == week]
    r = api_client.post("/api/exports/minutes", json={"ids": [c["id"] for c in picked]})
    assert r.status_code == 200
    assert r.headers["content-disposition"].endswith('_SBS Sourcing Alignment Committee_MM.xlsx"')
    assert f'filename="KW{week:02d} ' in r.headers["content-disposition"]


# ---------- Presenter ----------

def test_presenter_defaults_to_the_submitter_and_can_name_someone_else(api_client, admin):
    r = api_client.post("/api/submissions", json={**VALID_SUBMISSION, "caseNo": "SWAT-28001", "presenter": "  Lingqing Hu  "})
    assert r.status_code == 200, r.text
    sub_id = r.json()["subId"]
    r = api_client.post(f"/api/submissions/{sub_id}/confirm", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["case"]["presenter"] == "Lingqing Hu"
    sub = next(s for s in r.json()["snapshot"]["submissions"] if s["subId"] == sub_id)
    assert sub["presenter"] == "Lingqing Hu" and sub["submitterName"] == "Test User"

    r = api_client.post("/api/submissions", json={**VALID_SUBMISSION, "caseNo": "SWAT-28002", "presenter": "   "})
    assert r.status_code == 200, r.text
    sub = next(s for s in r.json()["snapshot"]["submissions"] if s["subId"] == r.json()["subId"])
    assert sub["presenter"] == "Test User"  # 留空：回退到提交账号的名字


def test_admin_renames_an_account_and_new_submissions_use_the_new_name(api_client, admin):
    _register(api_client, "lingqing.hu@zf.com", name="EXTERNAL_HU")
    r = api_client.put("/api/users/lingqing.hu@zf.com", json={"name": "  Lingqing Hu (Tracy) "}, headers=admin)
    assert r.status_code == 200, r.text
    assert next(u for u in r.json()["users"] if u["email"] == "lingqing.hu@zf.com")["name"] == "Lingqing Hu (Tracy)"
    assert api_client.put("/api/users/lingqing.hu@zf.com", json={"name": "   "}, headers=admin).status_code == 422
    user = _login_by_email(api_client, "lingqing.hu@zf.com")
    r = api_client.post("/api/submissions", json={**VALID_SUBMISSION, "caseNo": "SWAT-28003"}, headers=user)
    assert r.status_code == 200, r.text
    sub = next(s for s in r.json()["snapshot"]["submissions"] if s["subId"] == r.json()["subId"])
    assert sub["submitterName"] == sub["presenter"] == "Lingqing Hu (Tracy)"
    # 普通用户不能改别人的名字
    assert api_client.put("/api/users/admin@zf.com", json={"name": "X"}, headers=user).status_code == 403
