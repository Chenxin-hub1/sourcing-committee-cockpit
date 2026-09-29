"""输入加固（v3 Phase-10）：字段长度上限与手动提醒的管理员门禁。"""

import pytest
from pydantic import ValidationError

from app.schemas import CaseEditIn, FollowUpIn, ManualReminderIn, ReminderSettingsIn, SubmissionIn
from tests.test_commercial import SUBMISSION


@pytest.mark.parametrize("field,length,ok", [
    ("recommendedSupplier", 500, True), ("recommendedSupplier", 501, False),
    ("comments", 5000, True), ("comments", 5001, False),
    ("lateReason", 5001, False), ("cqaJustification", 5001, False), ("project", 501, False),
])
def test_submission_text_limits(field, length, ok):
    body = dict(SUBMISSION, **{field: "x" * length})
    if ok:
        assert len(getattr(SubmissionIn.model_validate(body), field)) == length
    else:
        with pytest.raises(ValidationError):
            SubmissionIn.model_validate(body)


def test_part_number_rows_capped_at_fifty():
    part = {"partNumber": "1", "partDescription": "p"}
    assert len(SubmissionIn.model_validate(dict(SUBMISSION, partNumbers=[part] * 50)).partNumbers) == 50
    with pytest.raises(ValidationError):
        SubmissionIn.model_validate(dict(SUBMISSION, partNumbers=[part] * 51))


def test_follow_up_limits():
    assert len(FollowUpIn(id="FU-1", task="t" * 5000, notes="n" * 5000).task) == 5000
    with pytest.raises(ValidationError):
        FollowUpIn(id="FU-1", task="t" * 5001)
    with pytest.raises(ValidationError):
        FollowUpIn(id="FU-1", tags=["a"] * 21)
    edit = {"partNumbers": [{"partNumber": "1", "partDescription": "p"}], "meetingDecision": "PENDING"}
    assert len(CaseEditIn.model_validate(dict(edit, committeeDiscussion="d" * 5000)).committeeDiscussion) == 5000
    with pytest.raises(ValidationError):
        CaseEditIn.model_validate(dict(edit, followUps=[{"id": f"FU-{i}"} for i in range(101)]))


def test_oversized_request_is_a_readable_422(api_client):
    r = api_client.post("/api/submissions", json=dict(SUBMISSION, recommendedSupplier="s" * 501))
    assert r.status_code == 422
    assert "recommendedSupplier" in str(r.json()["detail"]) and "500" in str(r.json()["detail"])


def test_cc_fields_are_capped_at_500():
    # 2026-09-24 复测：三处抄送字段漏了上限，10 万字符曾原样进库并进纪要 Actions 表
    assert len(FollowUpIn(id="FU-1", cc="c" * 500).cc) == 500
    with pytest.raises(ValidationError):
        FollowUpIn(id="FU-1", cc="c" * 501)
    with pytest.raises(ValidationError):
        ManualReminderIn(taskId="FU-1", cc="c" * 501)
    with pytest.raises(ValidationError):
        ReminderSettingsIn(alwaysCc="c" * 501)
