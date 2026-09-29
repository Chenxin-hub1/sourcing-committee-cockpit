"""请求边界与提醒日期回归；只使用内存对象或隔离测试数据库。"""

from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app import logic
from app.schemas import CaseEditIn, FollowUpIn, PartNumberIn, ReminderSettingsIn, SubmissionIn

VALID_PART = {"partNumber": "1001", "partDescription": "Test part",
              "pcPriceCQA": "1.25", "supplierPriceLanded": "1.1", "toolingCQA": "120000", "supplierToolingCost": "118500"}
VALID_EDIT = {"partNumbers": [VALID_PART], "region": "EU", "meetingDecision": "PENDING"}
VALID_SUBMISSION = {
    "submitterName": "Test User", "submitterEmail": "test@example.com", "caseNo": "SWAT-90123",
    "recommendedSupplier": "Test supplier", "project": "Test project", "partNumbers": [VALID_PART],
    "peakYearSpend": 100, "lifetimeSpend": 200,  # v3 Phase-15：bundle 金额在案例级
    "meetingDateISO": "2026-10-07", "isFamilyCase": "No", "involvesECM": "No",
    "toolingPayment": "Lumpsum", "fraAvailable": "Yes",
}


@pytest.mark.parametrize("field,value", [
    ("isFamilyCase", "not applicable"), ("familyAligned", "Approved"),
    ("involvesECM", "false"), ("ccbApproved", "Passed"),
    ("region", "invalid"), ("decisionLevel", "Level 99"),
    ("submitterEmail", "not-an-email"), ("submitterEmail", "a@example.com,b@example.com"),
    ("meetingDateISO", "2026-02-30"), ("meetingDateISO", "2026-9-22"),
    ("meetingWeekNum", 0), ("meetingWeekNum", 54), ("meetingWeekNum", True),
])
def test_invalid_submission_fields_rejected(field, value):
    with pytest.raises(ValidationError):
        SubmissionIn.model_validate(dict(VALID_SUBMISSION, **{field: value}))


@pytest.mark.parametrize("raw,expected", [
    ("EU", "EU"), (["NA", "EU"], "EU + NA"), ("NA + AP", "AP + NA"), (["EU", "EU", " AP "], "AP + EU"),
    ("EU+NA+AP", "AP + EU + NA"), ([], ""), ("", ""),
])
def test_regions_normalize_to_fixed_order(raw, expected):
    # 反馈 #2：多区域统一存成固定顺序的 "AP + EU + NA" 文本，旧的单区域数据原样有效
    assert SubmissionIn.model_validate(dict(VALID_SUBMISSION, region=raw)).region == expected


@pytest.mark.parametrize("raw", [["EU", "LATAM"], "EU + Mars", 3, [1], {"EU": True}])
def test_regions_reject_unknown_values(raw):
    with pytest.raises(ValidationError):
        SubmissionIn.model_validate(dict(VALID_SUBMISSION, region=raw))


@pytest.mark.parametrize("value", [-1, True, 1.5, "10", 2**53, float("inf"), float("nan")])
def test_spend_rejects_invalid_or_inexact_values(value):
    # v3 Phase-15：金额按 bundle 在案例级（提交与编辑都是）
    with pytest.raises(ValidationError):
        SubmissionIn.model_validate(dict(VALID_SUBMISSION, peakYearSpend=value))
    with pytest.raises(ValidationError):
        CaseEditIn.model_validate(dict(VALID_EDIT, lifetimeSpend=value))


def test_row_spend_from_old_clients_is_ignored_not_rejected():
    # 旧页面还按零件行发金额：忽略（案例级为准），不 422
    part = PartNumberIn.model_validate(dict(VALID_PART, peakYearSpend=5, lifetimeSpend="x"))
    assert "peakYearSpend" not in part.model_dump()


@pytest.mark.parametrize("updates", [
    {"meetingDecision": "APPROVED WITHOUT REVIEW"}, {"partNumbers": []},
    {"followUps": [{"id": "FU-1", "status": "Done"}]},
    {"followUps": [{"id": "FU-1", "tags": "Cost"}]},
    {"followUps": [{"id": "FU-1", "dueDate": "2026-02-30"}]},
    {"followUps": [{"id": "FU-1", "task": {"text": "bad"}}]},
    {"followUps": [{"task": "missing ID"}]},
    {"followUps": [{"id": "FU-1"}, {"id": "FU-1"}]},
])
def test_case_edit_rejects_malformed_nested_data(updates):
    with pytest.raises(ValidationError):
        CaseEditIn.model_validate(dict(VALID_EDIT, **updates))


def test_valid_legacy_tasks_and_dates_remain_compatible():
    task = FollowUpIn(id="FU-1", dueDate="—", tags=["Custom tag"], cc="K. Reyes", lastAutoReminderDate="yesterday")
    assert task.dueDate == "—" and task.tags == ["Custom tag"]
    assert "lastAutoReminderDate" not in task.model_dump()
    sub = SubmissionIn.model_validate(dict(VALID_SUBMISSION, meetingDateISO="2028-02-29", meetingWeekNum=9))
    assert sub.meetingDateISO == "2028-02-29"
    assert SubmissionIn.model_validate(dict(VALID_SUBMISSION, submitterName="  Test User  ")).submitterName == "Test User"


def test_meeting_calendar_fields_follow_iso_week_numbering():
    sub = SubmissionIn.model_validate(dict(
        VALID_SUBMISSION, meetingDateISO="2026-09-30", meetingWeekNum=12, meetingDateLabel="Wrong date"))
    assert sub.meetingWeekNum == 40  # v3 Phase-13：ISO 周（KW），不再是模板的"1 月 1 日起每 7 天"
    assert sub.meetingDateLabel == "Wed, Sep 30, 2026"


def test_confirm_preserves_next_year_meeting_date(reminder_clock):
    sub = dict(VALID_SUBMISSION, meetingDateISO="2027-01-06", meetingWeekNum=1)
    case = logic.confirm_submission(sub, [])
    assert case["meetingDateISO"] == "2027-01-06"
    assert case["meetingYear"] == 2027 and case["weekNum"] == 1


@pytest.mark.parametrize("updates", [
    {"enabled": "false"}, {"overdueEveryDays": 0}, {"overdueEveryDays": -1},
    {"overdueEveryDays": True}, {"channel": "SMS"}, {"alwaysCc": "a@example.com\r\nBcc: b@example.com"},
])
def test_invalid_reminder_settings_rejected(updates):
    with pytest.raises(ValidationError):
        ReminderSettingsIn.model_validate(updates)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https:///file", "https://host:bad/file", "https://host\\path"])
@pytest.mark.parametrize("field", ["sourcingPresentationLink", "finalDocLink"])
def test_optional_links_are_validated_even_for_pending_cases(field, url):
    error = logic.validate_case_edit(dict(VALID_EDIT, **{field: url}))
    assert error and "full URL" in error


def test_signed_document_url_preserved():
    url = "https://intranet/docs/report.pptx?token=abc&download=1#slide=2"
    assert logic.validate_case_edit(dict(VALID_EDIT, sourcingPresentationLink=url, finalDocLink=url)) is None


@pytest.fixture
def reminder_clock(monkeypatch):
    now = datetime(2026, 9, 22, 12, tzinfo=ZoneInfo("America/New_York"))
    monkeypatch.setattr(logic, "na_now", lambda: now)
    return now


def _reminder_case(tasks):
    return logic.mk_case({"id": "C0001", "swatId": "SWAT-1", "followUps": tasks}, [])


def test_invalid_legacy_date_does_not_stop_other_reminders(reminder_clock):
    invalid = {"id": "FU-bad", "task": "bad", "status": "Open", "dueDate": "2026-02-30"}
    valid = {"id": "FU-good", "task": "good", "status": "Open", "dueDate": "2026-09-22", "responsible": "W. Chen"}
    settings, log = deepcopy(logic.REMINDER_DEFAULTS), []
    cases = [_reminder_case([invalid, valid])]
    result = logic.run_daily_reminder_check(cases, settings, log)
    assert result["sent"] == 1 and log[0]["task"] == "good"
    assert "lastAutoReminderDate" not in invalid
    assert valid["lastAutoReminderDate"] == "2026-09-22"
    assert logic.run_daily_reminder_check(cases, settings, log, force=True)["sent"] == 0


def test_postponed_task_stops_being_overdue_when_reminders_disabled(reminder_clock):
    task = {"id": "FU-1", "task": "postponed", "status": "Overdue", "dueDate": "2026-09-30"}
    case = _reminder_case([task])
    case["actionStatus"] = "Overdue"
    result = logic.run_daily_reminder_check([case], dict(logic.REMINDER_DEFAULTS, enabled=False), [])
    assert task["status"] == "Open" and case["actionStatus"] == "Open"
    assert result["sent"] == 0 and result["changed"] == [case["id"]]


def test_edit_preserves_current_reminder_record_and_deduplication(reminder_clock):
    task = {"id": "FU-1", "task": "current", "status": "Open", "dueDate": "2026-09-22",
            "lastAutoReminderDate": "2026-09-22", "lastReminder": {"to": "current@example.com", "delivery": {"email": "sent"}}}
    case = _reminder_case([deepcopy(task)])
    stale_task = dict(task, task="edited", lastAutoReminderDate="2026-09-21", lastReminder={"to": "stale@example.com"})
    edit = dict(VALID_EDIT, meetingDecision="APPROVED", sourcingPresentationLink="https://intranet/p.pptx", followUps=[stale_task])
    logic.apply_case_edit(case, edit)
    saved = case["followUps"][0]
    assert saved["task"] == "edited"
    assert saved["lastReminder"] == task["lastReminder"]
    assert saved["lastAutoReminderDate"] == "2026-09-22"
    assert logic.run_daily_reminder_check([case], deepcopy(logic.REMINDER_DEFAULTS), [])["sent"] == 0


def test_edit_recalculates_overdue_status_immediately(reminder_clock):
    task = {"id": "FU-1", "task": "postponed", "status": "Overdue", "dueDate": "2026-09-21"}
    case = _reminder_case([task])
    edit = dict(VALID_EDIT, meetingDecision="APPROVED", followUps=[dict(task, dueDate="2026-09-30")])
    logic.apply_case_edit(case, edit)
    assert case["followUps"][0]["status"] == "Open" and case["actionStatus"] == "Open"


def test_api_rejects_invalid_registration_without_mutation(api_client):
    before = api_client.get("/api/bootstrap").json()
    response = api_client.post("/api/submissions", json=dict(VALID_SUBMISSION, isFamilyCase="bypass"))
    assert response.status_code == 422
    assert api_client.get("/api/bootstrap").json()["submissions"] == before["submissions"]


def test_api_rejects_invalid_case_edit_without_mutation(api_client):
    login = api_client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    headers = {"X-Session-Token": login.json()["token"]}
    before = api_client.get("/api/bootstrap").json()
    response = api_client.put("/api/cases/C0001", headers=headers, json=dict(VALID_EDIT, partNumbers=[]))
    assert response.status_code == 422
    assert api_client.get("/api/bootstrap").json()["cases"] == before["cases"]
