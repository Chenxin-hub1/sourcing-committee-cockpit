"""v3 Phase-13：周号从模板周（1 月 1 日起每 7 天）改为 ISO 周（德国 KW），反馈人答复问题 3。

会议固定周三；ISO 周从周一开始，跨年周归属周四所在的年份。已存数据在服务启动时一次性换算（kv 标记，只做一次）：
有会议日期的按日期重算；没有日期的模板演示数据（2026 年，1 月 1 日是周四）一律 +1。
"""

import json
from datetime import date

import pytest
from sqlalchemy import select

from app import logic, main, service
from app.models import CaseRow, KvRow, SubmissionRow
from app.schemas import SubmissionIn
from tests.test_api import VALID_SUBMISSION as API_SUBMISSION
from tests.test_validation import VALID_SUBMISSION


@pytest.mark.parametrize("meeting,week", [
    ("2026-09-30", 40), ("2026-01-07", 2), ("2026-12-30", 53), ("2025-12-31", 1), ("2027-01-06", 1),
])
def test_submission_meeting_week_is_the_iso_week(meeting, week):
    sub = SubmissionIn.model_validate(dict(VALID_SUBMISSION, meetingDateISO=meeting, meetingWeekNum=12))
    assert sub.meetingWeekNum == week


def test_week_label_is_kw():
    assert logic.wk(40) == "2026-KW40" and logic.wk(3) == "2026-KW03"


@pytest.mark.parametrize("record,week", [
    ({"weekNum": 39, "meetingDateISO": "2026-09-30"}, 40),
    ({"weekNum": 40, "meetingDateISO": "", "meetingDateLabel": "Wed, Oct 7, 2026"}, 41),
    ({"weekNum": 23, "meetingDateLabel": None}, 24),  # 模板演示数据：没有日期，+1
    ({"weekNum": 53}, 53),  # 模板第 53 周（12 月 31 日，周四）没有下一周可去
    ({"weekNum": 5, "meetingDateLabel": "not a date"}, 6),
])
def test_record_iso_week_prefers_the_meeting_date(record, week):
    assert logic.iso_week_of_record(record) == week


def _seed_weeks():
    return [c["weekNum"] for c in json.loads(service.SEED_PATH.read_text(encoding="utf-8"))["cases"]]


async def test_fresh_database_seeds_demo_cases_in_iso_weeks_once(async_client):
    cases = (await async_client.get("/api/bootstrap")).json()["cases"]
    assert sorted(c["weekNum"] for c in cases) == sorted(w + 1 for w in _seed_weeks())
    # 重启（再次初始化）不会再加一次
    async with main.SessionLocal() as session:
        await service.init_db(session)
    again = (await async_client.get("/api/bootstrap")).json()["cases"]
    assert [c["weekNum"] for c in again] == [c["weekNum"] for c in cases]


async def test_existing_database_is_converted_on_startup(async_client):
    # 模拟 Phase-13 之前的库：去掉标记，放一条有日期的案例和一条待确认的提交单（模板周号）
    async with main.SessionLocal() as session:
        await session.delete(await session.get(KvRow, service.WEEK_NUMBERING_KEY))
        await service.insert_cases(session, [logic.mk_case({"swatId": "SWAT-DATED", "weekNum": 40, "caseNumber": 1,
                                                             "meetingDateISO": "2026-10-07"}, [])])
        await service.upsert_submission(session, {"subId": "SUB-9001", "status": "Waiting for Registration Confirmation",
                                                  "meetingDateISO": "2026-09-30", "meetingWeekNum": 39})
        await service.upsert_submission(session, {"subId": "SUB-9002", "status": "Waiting for Registration Confirmation"})
        await session.commit()
    before = {c["id"]: c["weekNum"] for c in (await async_client.get("/api/bootstrap")).json()["cases"]}

    async with main.SessionLocal() as session:
        await service.init_db(session)
        rows = (await session.execute(select(CaseRow))).scalars().all()
        assert all(r.week_num == r.doc["weekNum"] for r in rows)  # 索引列随文档一起改
        subs = {r.sub_id: r.doc for r in (await session.execute(select(SubmissionRow))).scalars()}
    snap = (await async_client.get("/api/bootstrap")).json()
    after = {c["id"]: c for c in snap["cases"]}
    dated = next(c for c in after.values() if c["swatId"] == "SWAT-DATED")
    assert dated["weekNum"] == date(2026, 10, 7).isocalendar().week == 41
    assert all(after[i]["weekNum"] == w + 1 for i, w in before.items() if i != dated["id"])
    assert subs["SUB-9001"]["meetingWeekNum"] == 40 and "meetingWeekNum" not in subs["SUB-9002"]


async def test_confirmed_registration_lands_in_the_iso_week(async_client):
    admin = {"X-Session-Token": (await async_client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})).json()["token"]}
    r = await async_client.post("/api/submissions", json=API_SUBMISSION)  # 会议 2026-09-30
    assert r.status_code == 200, r.text
    case = (await async_client.post(f"/api/submissions/{r.json()['subId']}/confirm", headers=admin)).json()["case"]
    assert case["weekNum"] == 40
    r = await async_client.get("/api/exports/agenda", params={"week": 40})
    assert 'filename="Sourcing_Committee_Agenda_2026-KW40.xlsx"' in r.headers["content-disposition"]
