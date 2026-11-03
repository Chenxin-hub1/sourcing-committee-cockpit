"""v3 Phase-45：Decision Level 按 bundle Lifetime Spend（欧元）门槛自动算。

门槛来自 BU Sourcing Meeting 幻灯片（2025-10，Sourcing Thresholds (€)）：
≥ 1.500k PV lifecycle → BU Sourcing Meeting（系统里的 Level 2）；≥ 750k – < 1.500k → Level 3；< 750k → Level 4。
用户 2026-11-03 定：登记页不让 buyer 选；只有 Sourcing admin 能在编辑页手改；编辑页改了金额级别自动跟着变。
"""

from __future__ import annotations

import pytest

from app import logic
from tests.test_commercial import RATES, SUBMISSION, _edit_payload


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
    email = "carrie.wang@zf.com"
    client.post("/api/auth/register", json={"name": "Carrie Wang", "email": email})
    assert client.put(f"/api/users/{email}", headers=admin, json={"role": "npi_manager"}).status_code == 200
    r = client.post("/api/auth/login", json={"email": email})
    assert r.status_code == 200, r.text
    return {"X-Session-Token": r.json()["token"]}


@pytest.fixture(autouse=True)
def _reset_throttles():
    yield
    from app import main
    main._submission_times.clear()


def _submit(client, **over):
    r = client.post("/api/submissions", json={**SUBMISSION, **over})
    assert r.status_code == 200, r.text
    return next(s for s in r.json()["snapshot"]["submissions"] if s["subId"] == r.json()["subId"])


def _case(client, admin, **over):
    sub = _submit(client, **over)
    r = client.post(f"/api/submissions/{sub['subId']}/confirm", headers=admin)
    assert r.status_code == 200, r.text
    return r.json()["case"]


def _put(client, headers, case, **over):
    return client.put(f"/api/cases/{case['id']}", headers=headers, json=_edit_payload(case, **over))


# ---------- 门槛 ----------


@pytest.mark.parametrize("eur,level", [
    (50_000_000, "Level 2"), (1_500_000, "Level 2"), (1_499_999, "Level 3"),
    (750_000, "Level 3"), (749_999, "Level 4"), (1, "Level 4"),
])
def test_thresholds_follow_the_bu_sourcing_meeting_slide(eur, level):
    assert logic.decision_level_for(eur) == level


# ---------- 登记 ----------


def test_submission_level_comes_from_the_lifetime_spend_not_the_request(client):
    sub = _submit(client, caseNo="SWAT-45001", lifetimeSpend=2_000_000, decisionLevel="Level 4")
    assert sub["decisionLevel"] == "Level 2"
    sub = _submit(client, caseNo="SWAT-45002", lifetimeSpend=749_999, decisionLevel="Level 2")
    assert sub["decisionLevel"] == "Level 4"
    # 旧页面不带 decisionLevel 也照样算
    body = {k: v for k, v in SUBMISSION.items() if k != "decisionLevel"}
    r = client.post("/api/submissions", json={**body, "caseNo": "SWAT-45003", "lifetimeSpend": 900_000})
    assert r.status_code == 200, r.text
    assert next(s for s in r.json()["snapshot"]["submissions"] if s["subId"] == r.json()["subId"])["decisionLevel"] == "Level 3"


def test_submission_level_uses_the_converted_euro_amount(client, admin):
    assert client.put("/api/fx-settings", json=RATES, headers=admin).status_code == 200
    # 1 EUR = 1.25 USD：1,800,000 USD = €1,440,000 → Level 3（按美元数字看会以为够 1.5 Mio）
    sub = _submit(client, caseNo="SWAT-45010", currency="USD", lifetimeSpend=1_800_000)
    assert (sub["lifetimeSpend"], sub["decisionLevel"]) == (1_440_000, "Level 3")
    sub = _submit(client, caseNo="SWAT-45011", currency="USD", lifetimeSpend=1_875_000)
    assert (sub["lifetimeSpend"], sub["decisionLevel"]) == (1_500_000, "Level 2")


def test_fra_rule_follows_the_computed_level(client):
    # 金额够 Level 2：FRA 必答且不能是 No，请求里写 Level 3 也绕不过去
    r = client.post("/api/submissions", json={**SUBMISSION, "caseNo": "SWAT-45020", "lifetimeSpend": 1_600_000,
                                              "decisionLevel": "Level 3", "fraAvailable": ""})
    assert r.status_code == 422 and "FRA" in r.json()["detail"]
    r = client.post("/api/submissions", json={**SUBMISSION, "caseNo": "SWAT-45020", "lifetimeSpend": 1_600_000,
                                              "fraAvailable": "No"})
    assert r.status_code == 422 and "FRA" in r.json()["detail"]
    # 金额只够 Level 3：不要求 FRA，请求里写 Level 2 也不要求
    assert _submit(client, caseNo="SWAT-45021", lifetimeSpend=800_000, decisionLevel="Level 2", fraAvailable="")


def test_confirmed_case_keeps_the_computed_level(client, admin):
    assert _case(client, admin, caseNo="SWAT-45030", lifetimeSpend=1_200_000)["decisionLevel"] == "Level 3"


# ---------- 案例编辑：Manager 不能选，金额变了才重算 ----------


def test_manager_cannot_pick_the_level(client, admin, manager):
    case = _case(client, admin, caseNo="SWAT-45040", lifetimeSpend=1_200_000)
    r = _put(client, manager, case, decisionLevel="Level 4")
    assert r.status_code == 200, r.text
    assert r.json()["case"]["decisionLevel"] == "Level 3"


def test_manager_changing_the_amount_recomputes_the_level(client, admin, manager):
    case = _case(client, admin, caseNo="SWAT-45041", lifetimeSpend=1_200_000)
    r = _put(client, manager, case, lifetimeSpend=2_000_000)
    assert r.status_code == 200, r.text
    assert r.json()["case"]["decisionLevel"] == "Level 2"
    r = _put(client, manager, r.json()["case"], lifetimeSpend=300_000)
    assert r.json()["case"]["decisionLevel"] == "Level 4"


def test_saving_without_an_amount_change_keeps_an_admin_override(client, admin, manager):
    case = _case(client, admin, caseNo="SWAT-45042", lifetimeSpend=1_800_000)
    assert case["decisionLevel"] == "Level 2"
    # 例外（如历史上 €2,760,000 记成 L3）：admin 手改
    r = _put(client, admin, case, decisionLevel="Level 3")
    assert r.json()["case"]["decisionLevel"] == "Level 3"
    # 之后 Manager 只记录决议、不动金额：例外保留；带着同样的金额也不算改
    r = _put(client, manager, r.json()["case"], lifetimeSpend=1_800_000, committeeDiscussion="Discussed")
    assert r.status_code == 200, r.text
    assert r.json()["case"]["decisionLevel"] == "Level 3"


def test_unchanged_amount_on_a_row_by_row_converted_case_keeps_the_level():
    # Phase-15 之前逐行换算的外币案例：欧元合计是各行之和，可能和"合计一次换算"差 1 欧元；
    # 原币金额没动就不算改了金额，例外级别不能因为这 1 欧元被重算
    case = {"fx": {"currency": "USD", "perEur": "1.17"}, "lifetimeSpend": 1_000_001,
            "lifetimeSpendEntered": 1_170_000, "decisionLevel": "Level 2"}
    assert logic.to_eur(1_170_000, logic.fx_of(case["fx"])) == 1_000_000
    assert logic.edit_decision_level(case, {"lifetimeSpend": 1_170_000}, admin_choice=False) == "Level 2"
    assert logic.edit_decision_level(case, {"lifetimeSpend": 1_170_001}, admin_choice=False) == "Level 3"


def test_clearing_the_amount_does_not_guess_a_level(client, admin, manager):
    case = _case(client, admin, caseNo="SWAT-45043", lifetimeSpend=1_800_000)
    r = _put(client, manager, case, lifetimeSpend=0)
    assert r.status_code == 200, r.text
    assert r.json()["case"]["decisionLevel"] == "Level 2"


def test_edit_recomputes_with_the_case_exchange_rate(client, admin, manager):
    assert client.put("/api/fx-settings", json=RATES, headers=admin).status_code == 200
    case = _case(client, admin, caseNo="SWAT-45044", currency="USD", lifetimeSpend=1_000_000)  # €800,000
    assert case["decisionLevel"] == "Level 3"
    # 之后汇率改了，编辑仍按案例上记录的 1.25：1,900,000 USD = €1,520,000 → Level 2
    client.put("/api/fx-settings", json={"basis": "OP 2027", "perEur": {"USD": "1.3"}}, headers=admin)
    r = _put(client, manager, case, lifetimeSpend=1_900_000)
    assert r.status_code == 200, r.text
    assert (r.json()["case"]["lifetimeSpend"], r.json()["case"]["decisionLevel"]) == (1_520_000, "Level 2")


def test_presentation_rule_uses_the_final_level(client, admin, manager):
    # Manager 不能靠在请求里写 Level 4 绕开"记录决议要有演示文稿"
    case = _case(client, admin, caseNo="SWAT-45045", lifetimeSpend=1_800_000)
    r = _put(client, manager, case, meetingDecision="APPROVED", decisionLevel="Level 4")
    assert r.status_code == 422 and "Sourcing Presentation" in r.json()["detail"]
    # 金额改小到 Level 4：同一次保存里就按 Level 4 免演示文稿
    r = _put(client, manager, case, meetingDecision="APPROVED", lifetimeSpend=500_000)
    assert r.status_code == 200, r.text
    assert r.json()["case"]["decisionLevel"] == "Level 4"


# ---------- 案例编辑：Sourcing admin 可以手改 ----------


def test_admin_choice_wins_even_when_the_amount_changes(client, admin):
    case = _case(client, admin, caseNo="SWAT-45050", lifetimeSpend=1_200_000)
    r = _put(client, admin, case, lifetimeSpend=2_000_000, decisionLevel="Level 3")
    assert r.status_code == 200, r.text
    assert r.json()["case"]["decisionLevel"] == "Level 3"


def test_admin_without_a_level_in_the_request_gets_the_computed_one(client, admin):
    case = _case(client, admin, caseNo="SWAT-45051", lifetimeSpend=1_200_000)
    r = _put(client, admin, case, lifetimeSpend=2_000_000)  # 旧页面：请求里没有 decisionLevel
    assert r.json()["case"]["decisionLevel"] == "Level 2"
    r = _put(client, admin, r.json()["case"], decisionLevel="")  # 空值不算手选
    assert r.json()["case"]["decisionLevel"] == "Level 2"
