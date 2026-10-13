"""v3 Phase-21：案例编号按"年份 + 周"排；删除或改走案例后原周补成连续号；启动时一次性整理已编错的号。"""

from __future__ import annotations

from collections import defaultdict

import pytest

from app import logic, service
from tests.test_api import VALID_SUBMISSION, _edit_payload, _get_case


@pytest.fixture
def client(api_client):
    return api_client


@pytest.fixture
def admin(client):
    r = client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    assert r.status_code == 200
    return {"X-Session-Token": r.json()["token"]}


def _confirmed_case(client, admin, number: str) -> dict:
    r = client.post("/api/submissions", json={**VALID_SUBMISSION, "caseNo": number})
    assert r.status_code == 200, r.text
    case = client.post(f"/api/submissions/{r.json()['subId']}/confirm", headers=admin).json()["case"]
    return _get_case(client, case["id"])


def _week_numbers(cases: list[dict]) -> dict:
    weeks: dict = defaultdict(list)
    for c in cases:
        weeks[(logic.case_year(c), int(c["weekNum"]))].append(int(c["caseNumber"]))
    return weeks


def _assert_contiguous(cases: list[dict]) -> None:
    for key, numbers in _week_numbers(cases).items():
        assert sorted(set(numbers)) == list(range(1, len(set(numbers)) + 1)), (key, sorted(numbers))


def _history(year: int, week: int, count: int) -> list[dict]:
    cases: list[dict] = []
    for n in range(1, count + 1):
        cases.append(logic.mk_case({"swatId": f"H{year}-{week}-{n}", "weekNum": week, "caseNumber": n, "meetingYear": year}, cases))
    return cases


# ---------- 确认登记按年份编号 ----------


def test_confirmed_case_is_numbered_within_its_own_year():
    # 2025-KW42 历史有 1~3 号；2026-KW42 的第一条登记应是 1 号（之前错成 4 号）
    cases = _history(2025, 42, 3)
    sub = dict(VALID_SUBMISSION, meetingDateISO="2026-10-14", meetingWeekNum=42)
    case = logic.confirm_submission(sub, cases)
    assert (case["meetingYear"], case["weekNum"], case["caseNumber"]) == (2026, 42, 1)
    cases.append(case)
    second = logic.confirm_submission(dict(sub, caseNo="swat 20998"), cases)
    assert second["caseNumber"] == 2


# ---------- 重排辅助函数 ----------


def test_renumber_closes_gaps_in_order_and_leaves_other_weeks_alone():
    cases = _history(2025, 42, 3) + _history(2026, 41, 1)
    week = [logic.mk_case({"swatId": s, "weekNum": 42, "caseNumber": n, "meetingYear": 2026}, cases) for s, n in
            (("A", 4), ("B", 7), ("C", 5))]
    cases += week
    changed = logic.renumber_weeks(cases, {(2026, 42)})
    assert {c["swatId"]: c["caseNumber"] for c in week} == {"A": 1, "C": 2, "B": 3}
    assert {c["swatId"] for c in changed} == {"A", "B", "C"}
    assert logic.renumber_weeks(cases, {(2026, 42)}) == []  # 已连续：不再改动
    _assert_contiguous(cases)


def test_renumber_keeps_rows_that_share_a_number_together():
    # 同一周两行同号（Excel 里合并的 '#'）：仍然同号，按名次重排
    cases = [logic.mk_case({"swatId": s, "weekNum": 10, "caseNumber": n, "meetingYear": 2026}, []) for s, n in
             (("A", 3), ("B", 3), ("C", 6))]
    logic.renumber_weeks(cases, {(2026, 10)})
    assert [c["caseNumber"] for c in cases] == [1, 1, 2]


# ---------- 接口：删除 / 改周后原周补号 ----------


def test_deleting_a_case_renumbers_the_rest_of_its_week(client, admin):
    first = _confirmed_case(client, admin, "swat 20991")
    second = _confirmed_case(client, admin, "swat 20992")
    third = _confirmed_case(client, admin, "swat 20993")
    assert (second["caseNumber"], third["caseNumber"]) == (first["caseNumber"] + 1, first["caseNumber"] + 2)
    r = client.delete("/api/cases/SWAT-20992", headers=admin)
    assert r.status_code == 200, r.text
    cases = r.json()["snapshot"]["cases"]
    assert next(c for c in cases if c["id"] == third["id"])["caseNumber"] == second["caseNumber"]
    _assert_contiguous(cases)
    # 落库了：重新加载仍是补过的号
    assert _get_case(client, third["id"])["caseNumber"] == second["caseNumber"]


def test_moving_a_case_away_renumbers_the_week_it_left(client, admin):
    first = _confirmed_case(client, admin, "swat 20991")
    _confirmed_case(client, admin, "swat 20992")
    third = _confirmed_case(client, admin, "swat 20993")
    r = client.put(f"/api/cases/{first['id']}", headers=admin, json=_edit_payload(first, meetingDate="2026-10-07"))
    assert r.status_code == 200, r.text
    cases = r.json()["snapshot"]["cases"]
    _assert_contiguous(cases)
    assert _get_case(client, third["id"])["caseNumber"] == third["caseNumber"] - 1


# ---------- 启动迁移：一次性整理已编错的号 ----------


async def test_startup_renumbers_existing_weeks_once(isolated_app):
    from app import db

    async with db.SessionLocal() as session:
        await service.init_db(session)
        history = _history(2025, 42, 3)
        wrong = [logic.mk_case({"swatId": s, "weekNum": 42, "caseNumber": n, "meetingYear": 2026}, history) for s, n in
                 (("R1", 4), ("R2", 5))]
        # 全部从 Excel 导入的周保持原件编号（2026-KW39 的周会 Excel 本身就跳过了 6 号）
        excel = {"kind": "excel", "file": "KW39 23.09.2026_MM.xlsx"}
        imported = [logic.mk_case({"swatId": s, "weekNum": 39, "caseNumber": n, "meetingYear": 2026, "source": excel}, []) for s, n in
                    (("E5", 5), ("E7", 7))]
        await service.insert_cases(session, history + wrong + imported)
        await service._set_kv(session, service.CASE_NUMBERING_KEY, None)
        await session.commit()
        await service._migrate_case_numbers(session)
        await session.commit()
        cases = (await service.load_state(session))["cases"]
        numbers = {c["swatId"]: c["caseNumber"] for c in cases}
        assert (numbers["R1"], numbers["R2"]) == (1, 2)
        assert [numbers[f"H2025-42-{n}"] for n in (1, 2, 3)] == [1, 2, 3]
        assert (numbers["E5"], numbers["E7"]) == (5, 7)
        _assert_contiguous([c for c in cases if c["swatId"] not in ("E5", "E7")])
        assert (await service._kv_doc(session, service.CASE_NUMBERING_KEY)) == {"scheme": "per-year-week"}
        # 只跑一次：之后手工出现的空号不会被启动迁移改动（删除 / 改周时各自补号）
        r1 = next(c for c in cases if c["swatId"] == "R1")
        r1["caseNumber"] = 9
        await service.upsert_case(session, r1)
        await session.commit()
        await service._migrate_case_numbers(session)
        await session.commit()
        assert next(c for c in (await service.load_state(session))["cases"] if c["swatId"] == "R1")["caseNumber"] == 9
