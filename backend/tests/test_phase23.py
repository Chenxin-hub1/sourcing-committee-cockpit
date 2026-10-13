"""v3 Phase-23：从会议纪要（Excel 的 Notes/Task/Resp./Due Date 列 / Committee Discussion）列出 Action Item 草稿。

样本是领导 2026-10-12 截图里的两段真实纪要：一段按行分好（Excel 单元格），一段挤在一行里（编号接在上一条后面）。
"""

from __future__ import annotations

from datetime import date

import pytest

from app import action_items

MEETING = date(2026, 10, 7)

EXCEL_NOTES = """1. To share updated sourcing presentation -- SP Melisa by 09.10.2026

2. To share QAF, PDF Quotation, CAPA for each region, each Kimball location.-- SP Melisa by 09.10.2026

3. To inform Kimball globally with LOI. -- SP Melisa by 09.10.2026
Agreement on 08.10.2026: to inform Kimball that ZF LT will pay with Amo, e.g. for EU, 449K Euro into 896039pcs, 0,71 Euro/pc, interest rate around 8%.
In parallel, team to further check if we can cover or partially cover the investment via CEA.

4. To share MPC plan by each region -- SP Melisa by 09.10.2026
Carrie to approve.

5. To kickoff Kimball after LOI-- BUP Rafal or Zhi, SDE Daniel U. KW42

6. CQA gap closure plan worked out and aglined with the task oweners. --team BUP Rafal, SP Melisa, PM, VAVE, Sales
a. To revisit PCB and E-components cost level, and to renegotiate with MB for in case of market increase. -- Andreas Feb 2028
b. To move MRA2 + V530 from screwed design to laser welded design. --Michal W., Nyanick June 2028
c. To check cost improvement with Daimler 465 MBEAL incremental volume. -- Rafal Nov 2026
d. VA to be double checked. -- Melisa Feb 2028.
e. To check if investment can be partially paid through MBEAL CEA -- Chrisitan, Agustin, Eric 09.11.2026.
f. To close the CQA gap for ECU Housing and cover. --Jan 2027, tracking in parallel with Housing and Cover SP, SDE, engineering"""

ONE_LINE = ("1. To check with engineering and SDE about cleanliness requirement, benchmarking with Staamp current pratice: "
            "cleanliness tested once per year, combining the comment of CE, if high-end cleaning or cleaning process ever really "
            "needed. --BUP Rafal, Deke to seperate the cleanling cost in QAF to show reduction potential. --SP Sandra 2. To continue "
            "the packaging cost improvement 1) to check and access with Kimball if their process allow us to pack ECU housing and "
            "cover together --BUP Rafal, SP Melisa 2) to check with Engineering and SDE if bulk package for cover can be approved "
            "instead of blister 3. To kickoff tooling at Deke-- TEAM 4. To close the gap towards CQA, to list down all the gap "
            "closure activities and to follow up bi-weekly, to define task owner, list to be distributed KW40--BUP Rafal, SP Sandra "
            "with ECU team 5. To request BP lumpsum from Deke for 2026.--SP Sandra")


def _by_ref(items: list[dict]) -> dict:
    return {i["ref"]: i for i in items}


# ---------- 按行分好的纪要（Excel 单元格） ----------


def test_numbered_lines_and_lettered_sub_items_become_drafts_in_order():
    items = action_items.extract(EXCEL_NOTES, MEETING)
    assert [i["ref"] for i in items] == ["1", "2", "3", "4", "5", "6", "6a", "6b", "6c", "6d", "6e", "6f"]


def test_owner_and_exact_due_date_are_read_after_the_double_dash():
    items = _by_ref(action_items.extract(EXCEL_NOTES, MEETING))
    assert (items["1"]["task"], items["1"]["responsible"], items["1"]["dueDate"]) == (
        "To share updated sourcing presentation", "SP Melisa", "2026-10-09")
    assert items["1"]["dueEstimated"] is False and items["1"]["notes"] == ""
    assert items["2"]["task"] == "To share QAF, PDF Quotation, CAPA for each region, each Kimball location."
    assert items["6e"]["responsible"] == "Chrisitan, Agustin, Eric" and items["6e"]["dueDate"] == "2026-11-09"
    assert items["6"]["responsible"] == "team BUP Rafal, SP Melisa, PM, VAVE, Sales" and items["6"]["dueDate"] == ""


def test_lines_without_a_number_stay_with_the_task_above_as_notes():
    items = _by_ref(action_items.extract(EXCEL_NOTES, MEETING))
    assert items["3"]["task"] == "To inform Kimball globally with LOI."
    assert items["3"]["notes"].startswith("Agreement on 08.10.2026: to inform Kimball")
    assert "partially cover the investment via CEA." in items["3"]["notes"]
    assert items["3"]["dueDate"] == "2026-10-09"  # 备注里的 08.10.2026 不当截止日期
    assert items["4"]["notes"] == "Carrie to approve."


def test_week_and_month_deadlines_are_estimated_and_flagged():
    items = _by_ref(action_items.extract(EXCEL_NOTES, MEETING))
    # KW42 → 那周周五；负责人里的 "U." 是姓名缩写，保留
    assert (items["5"]["responsible"], items["5"]["dueDate"], items["5"]["dueText"]) == ("BUP Rafal or Zhi, SDE Daniel U.", "2026-10-16", "KW42")
    assert items["5"]["dueEstimated"] is True and 'Due date estimated from "KW42"' in items["5"]["notes"]
    # 月份 → 当月最后一天
    assert (items["6a"]["responsible"], items["6a"]["dueDate"]) == ("Andreas", "2028-02-29")
    assert (items["6b"]["responsible"], items["6b"]["dueDate"]) == ("Michal W., Nyanick", "2028-06-30")
    assert (items["6c"]["responsible"], items["6c"]["dueDate"]) == ("Rafal", "2026-11-30")
    assert (items["6d"]["task"], items["6d"]["responsible"], items["6d"]["dueDate"]) == ("VA to be double checked.", "Melisa", "2028-02-29")
    # 日期写在负责人前面
    assert items["6f"]["dueDate"] == "2027-01-31"
    assert items["6f"]["responsible"] == "tracking in parallel with Housing and Cover SP, SDE, engineering"


# ---------- 挤在一行里的纪要（Cockpit 里录入的 Committee Discussion） ----------


def test_inline_numbering_and_parenthesised_sub_items_are_split():
    items = _by_ref(action_items.extract(ONE_LINE, MEETING))
    assert list(items) == ["1", "2", "2.1", "2.2", "3", "4", "5"]
    assert items["1"]["responsible"] == "SP Sandra"
    assert items["1"]["task"].startswith("To check with engineering and SDE") and "Deke to seperate" in items["1"]["task"]
    assert (items["2"]["task"], items["2"]["responsible"]) == ("To continue the packaging cost improvement", "")
    assert (items["2.1"]["task"], items["2.1"]["responsible"]) == (
        "to check and access with Kimball if their process allow us to pack ECU housing and cover together", "BUP Rafal, SP Melisa")
    assert items["2.2"]["responsible"] == ""
    assert (items["3"]["task"], items["3"]["responsible"]) == ("To kickoff tooling at Deke", "TEAM")
    # 截止写在任务文字里（KW40）：日期取出来，任务文字不动
    assert items["4"]["dueDate"] == "2026-10-02" and items["4"]["task"].endswith("list to be distributed KW40")
    assert items["4"]["responsible"] == "BUP Rafal, SP Sandra with ECU team"
    # "for 2026" 只有年份，不是日期
    assert (items["5"]["task"], items["5"]["responsible"], items["5"]["dueDate"]) == ("To request BP lumpsum from Deke for 2026.", "SP Sandra", "")


# ---------- 历史纪要里的另一种写法：单个 " - " 分隔负责人 ----------


def test_single_spaced_dash_separates_the_owner_when_there_is_no_double_dash():
    text = ("1. To check if there is further potential to improve packaging concept - SCM Anna S. CW 40.\n"
            "2. Confirm CQA basis - Summer Chen. CW38. (Markus approves once complete)\n"
            "3. To calculate USMCA %, if USMCA% are to be improved, cost acceptance from customer to be requested - PP Mario\n"
            "4. Re-check E-components cost -- Andreas - Lukas\n"
            "5. Further potential to improve the price?")
    items = _by_ref(action_items.extract(text, date(2025, 9, 17)))
    assert (items["1"]["task"], items["1"]["responsible"], items["1"]["dueDate"]) == (
        "To check if there is further potential to improve packaging concept", "SCM Anna S.", "2025-10-03")
    assert (items["2"]["responsible"], items["2"]["dueDate"]) == ("Summer Chen", "2025-09-19")  # 句末的点去掉
    assert items["2"]["notes"].endswith("Markus approves once complete")  # 括号里的说明进备注
    assert items["3"]["responsible"] == "PP Mario"
    assert (items["4"]["task"], items["4"]["responsible"]) == ("Re-check E-components cost", "Andreas - Lukas")  # 有 "--" 时以它为准
    assert items["5"]["responsible"] == ""


# ---------- 边界 ----------


@pytest.mark.parametrize("text", ["", "Pending for Sourcing Committee Review", "Approved. No open points."])
def test_text_without_numbered_items_gives_no_drafts(text):
    assert action_items.extract(text, MEETING) == []


def test_numbers_inside_sentences_do_not_start_new_items():
    text = "1. To raise volume to Level 2. Then confirm -- Anna by 12.10.2026\n2. To ship 3. samples -- Ben"
    items = action_items.extract(text, MEETING)
    assert [i["ref"] for i in items] == ["1", "2"]
    assert items[0]["task"] == "To raise volume to Level 2. Then confirm" and items[1]["task"] == "To ship 3. samples"


@pytest.mark.parametrize("written,expected", [
    ("by 9.10.2026", "2026-10-09"), ("09/10/2026", "2026-10-09"), ("2026-10-09", "2026-10-09"), ("09.10.26", "2026-10-09"),
    ("KW 3", "2027-01-22"), ("CW05/2027", "2027-02-05"), ("end of Sept 2026", "2026-09-30"), ("31.02.2026", ""),
])
def test_due_date_spellings(written, expected):
    # 会议在 2026-12-16（KW51）：没写年份的 KW 3 已是明年
    items = action_items.extract(f"1. To do it -- Anna {written}", date(2026, 12, 16))
    assert items[0]["dueDate"] == expected


# ---------- 接口 ----------


@pytest.fixture
def admin(api_client):
    r = api_client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    return {"X-Session-Token": r.json()["token"]}


def test_extract_endpoint_is_for_managers_and_returns_drafts(api_client, admin):
    body = {"text": EXCEL_NOTES, "meetingDateISO": "2026-10-07"}
    assert api_client.post("/api/action-items/extract", json=body, headers={"X-Session-Token": ""}).status_code == 401
    assert api_client.post("/api/action-items/extract", json=body).status_code == 403
    r = api_client.post("/api/action-items/extract", json=body, headers=admin)
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 12 and r.json()["items"][0]["dueDate"] == "2026-10-09"
    assert api_client.post("/api/action-items/extract", json={"text": "x", "meetingDateISO": "07.10.2026"}, headers=admin).status_code == 422
