"""反馈 #1：采购员按本币填写金额，系统按管理员维护的汇率折算成欧元。

约定：提交与编辑请求里的金额都是"用户输入的币种"；记录里 peakYearSpend / lifetimeSpend
存欧元，原币金额与当时的汇率一并保存，之后改汇率不影响已有记录。
汇率按财务 OP 表的记法录入与保存（v3 Phase-12）：1 EUR = X 外币，折算用除法。
"""

from decimal import Decimal

import pytest

from app import logic

SUBMISSION = {
    "submitterName": "T. Ester", "submitterEmail": "t.ester@zf-lifetec.com", "caseNo": "SWAT-31001",
    "partNumbers": [
        {"partNumber": "R003H147A", "partDescription": "ECU Housing, w/o WMS",
         "pcPriceCQA": "1.25", "supplierPriceLanded": "1.1", "toolingCQA": "120000", "supplierToolingCost": "118500"},
        {"partNumber": "R004D369A", "partDescription": "ECU Cover",
         "pcPriceCQA": "0.5", "supplierPriceLanded": "0.4", "toolingCQA": "0", "supplierToolingCost": "0"},
    ],
    # v3 Phase-15：金额按整个 bundle 填一个
    "peakYearSpend": 278000, "lifetimeSpend": 1725000,
    "region": "EU", "project": "MBEAL", "cluster": "Metal", "recommendedSupplier": "Test Supplier",
    "meetingDateISO": "2026-10-07", "isFamilyCase": "No", "involvesECM": "No",
    "toolingPayment": "Lumpsum", "fraAvailable": "Yes",
}
RATES = {"basis": "OP 2025 plan rates 2026", "perEur": {"USD": 1.25, "CNY": 8.3}}


@pytest.fixture
def client(api_client):
    return api_client


@pytest.fixture
def admin(client):
    r = client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    return {"X-Session-Token": r.json()["token"]}


@pytest.fixture(autouse=True)
def _reset_throttles():
    yield
    from app import main
    main._login_failures.clear()
    main._submission_times.clear()


def _submit(client, **over):
    r = client.post("/api/submissions", json={**SUBMISSION, **over})
    assert r.status_code == 200, r.text
    return next(s for s in r.json()["snapshot"]["submissions"] if s["subId"] == r.json()["subId"])


@pytest.mark.parametrize("amount,per_eur,expected", [
    (139000, "1.17", 118803), (1000, "8.3", 120), (5, "2", 3), (0, "1.17", 0), (7, "1", 7), (117, "1.17", 100),
])
def test_conversion_divides_by_op_rate_and_rounds_half_up_to_whole_euro(amount, per_eur, expected):
    assert logic.to_eur(amount, logic.Fx(per_eur=Decimal(per_eur))) == expected


def test_record_rate_snapshot_reads_op_notation_and_early_multiplier_notation():
    assert logic.to_eur(117, logic.fx_of({"currency": "USD", "perEur": "1.17"})) == 100
    # v3 Phase-2 早期的快照是 "1 外币 = r EUR"，仍按乘法读
    assert logic.to_eur(100, logic.fx_of({"currency": "USD", "rate": "0.92"})) == 92
    assert logic.to_eur(100, logic.fx_of(None)) == 100


def test_stored_early_rate_table_is_read_in_op_notation():
    # 早期汇率表存 "1 外币 = r EUR"（倒数，6 位小数）；读出来换成 OP 记法，取 4 位小数
    early = {"basis": "OP", "rates": {"USD": "0.854701", "CNY": "0.120482"}, "updatedAt": "x"}
    assert logic.normalize_fx_settings(early) == {"basis": "OP", "perEur": {"USD": "1.17", "CNY": "8.3"}, "updatedAt": "x"}
    current = {"basis": "OP", "perEur": {"USD": "1.17"}, "updatedAt": "x"}
    assert logic.normalize_fx_settings(current) == current


def test_fx_settings_are_admin_only_and_validated(client, admin):
    assert client.put("/api/fx-settings", json=RATES).status_code == 403  # 普通用户（默认登录）不能改
    r = client.put("/api/fx-settings", json=RATES, headers=admin)
    assert r.status_code == 200
    fx = r.json()["snapshot"]["fxSettings"]
    assert fx["basis"] == "OP 2025 plan rates 2026" and fx["perEur"] == {"USD": "1.25", "CNY": "8.3"}
    assert fx["updatedAt"] and "rates" not in fx
    for bad in (0, -1, 0.1234567, True, "abc", 100001):
        r = client.put("/api/fx-settings", json={"basis": "OP", "perEur": {"USD": bad}}, headers=admin)
        assert r.status_code == 422, bad
    # 清空某个币种的汇率
    r = client.put("/api/fx-settings", json={"basis": "OP 2026", "perEur": {"USD": 1.17, "CNY": None}}, headers=admin)
    assert r.json()["snapshot"]["fxSettings"]["perEur"] == {"USD": "1.17"}


def test_fx_settings_in_early_notation_are_refused_not_silently_cleared(client, admin):
    # 没刷新的旧页面仍发 "rates"（1 外币 = r EUR）：拒绝，而不是当作空表把汇率清掉
    client.put("/api/fx-settings", json=RATES, headers=admin)
    r = client.put("/api/fx-settings", json={"basis": "OP", "rates": {"USD": 0.92}}, headers=admin)
    assert r.status_code == 422 and "reload" in r.text.lower()
    assert client.get("/api/bootstrap").json()["fxSettings"]["perEur"] == {"USD": "1.25", "CNY": "8.3"}


def test_eur_is_default_and_needs_no_rate(client):
    sub = _submit(client)
    assert sub["spendCurrency"] == "EUR"
    assert sub["fx"] == {"currency": "EUR", "perEur": "1", "basis": ""}
    assert (sub["peakYearSpend"], sub["lifetimeSpend"]) == (278000, 1725000)
    assert (sub["peakYearSpendEntered"], sub["lifetimeSpendEntered"]) == (278000, 1725000)


def test_currency_without_rate_is_rejected(client):
    r = client.post("/api/submissions", json={**SUBMISSION, "currency": "CNY"})
    assert r.status_code == 422
    assert "exchange rate" in r.json()["detail"] and "CNY" in r.json()["detail"]
    r = client.post("/api/submissions", json={**SUBMISSION, "currency": "GBP"})
    assert r.status_code == 422


def test_usd_submission_is_stored_in_eur_with_rate_snapshot(client, admin):
    client.put("/api/fx-settings", json=RATES, headers=admin)
    sub = _submit(client, currency="USD")
    assert sub["spendCurrency"] == "EUR"
    assert sub["fx"] == {"currency": "USD", "perEur": "1.25", "basis": "OP 2025 plan rates 2026"}
    parts = sub["partNumbers"]
    # v3 Phase-15：零件行不再带金额；bundle 金额在案例级折算。1 EUR = 1.25 USD：278,000 USD / 1.25 = 222,400 EUR
    assert all("peakYearSpend" not in p and "lifetimeSpend" not in p for p in parts)
    assert (sub["peakYearSpend"], sub["lifetimeSpend"]) == (222400, 1380000)
    assert (sub["peakYearSpendEntered"], sub["lifetimeSpendEntered"]) == (278000, 1725000)

    # 确认入库：案例沿用同一套金额与汇率
    r = client.post(f"/api/submissions/{sub['subId']}/confirm", headers=admin)
    case = next(c for c in r.json()["snapshot"]["cases"] if c["swatId"] == "SWAT-31001")
    for key in ("spendCurrency", "fx", "peakYearSpend", "lifetimeSpend", "peakYearSpendEntered", "lifetimeSpendEntered"):
        assert case[key] == sub[key], key
    assert case["partNumbers"] == parts

    # 之后改汇率：已有记录不变
    client.put("/api/fx-settings", json={"basis": "OP 2027", "perEur": {"USD": 1.1}}, headers=admin)
    snap = client.get("/api/bootstrap").json()
    assert next(c for c in snap["cases"] if c["id"] == case["id"])["peakYearSpend"] == 222400


def test_case_edit_reconverts_with_the_rate_recorded_at_submission(client, admin):
    client.put("/api/fx-settings", json=RATES, headers=admin)
    sub = _submit(client, currency="USD", partNumbers=[SUBMISSION["partNumbers"][0]], peakYearSpend=139000, lifetimeSpend=873000)
    r = client.post(f"/api/submissions/{sub['subId']}/confirm", headers=admin)
    case = next(c for c in r.json()["snapshot"]["cases"] if c["swatId"] == "SWAT-31001")
    assert case["partNumbers"] is None  # 单零件案例：金额在案例本身
    assert (case["peakYearSpendEntered"], case["peakYearSpend"]) == (139000, 111200)
    client.put("/api/fx-settings", json={"basis": "OP 2027", "perEur": {"USD": 1.1}}, headers=admin)
    body = {
        "partNumbers": [{"partNumber": "R003H147A", "partDescription": "ECU Housing"}],
        "peakYearSpend": 100000, "lifetimeSpend": 500000,
        "region": "EU", "project": "MBEAL", "meetingDecision": "PENDING", "followUps": [],
    }
    r = client.put(f"/api/cases/{case['id']}", json=body, headers=admin)
    assert r.status_code == 200, r.text
    saved = r.json()["case"]
    # 编辑时金额按原币填写，仍用提交时记录的 1.25 折算，而不是新的 1.1
    assert (saved["peakYearSpendEntered"], saved["lifetimeSpendEntered"]) == (100000, 500000)
    assert (saved["peakYearSpend"], saved["lifetimeSpend"]) == (80000, 400000)
    assert saved["fx"]["perEur"] == "1.25"
    # 不带金额的保存（只改决议）：原值不动
    r = client.put(f"/api/cases/{case['id']}", json={k: v for k, v in body.items() if k not in ("peakYearSpend", "lifetimeSpend")}, headers=admin)
    assert r.status_code == 200, r.text
    assert (r.json()["case"]["peakYearSpendEntered"], r.json()["case"]["peakYearSpend"]) == (100000, 80000)


async def test_legacy_case_without_currency_keeps_its_amounts(async_client):
    # 没有币种信息的旧数据（当初按美元录入，未跑换算）：编辑时原样保存，不做折算。
    # 演示种子已是欧元，这里自己放一条旧记录进库
    from app import main, service
    async with main.SessionLocal() as session:
        state = await service.load_state(session)
        case = logic.mk_case({"weekNum": 30, "caseNumber": 9, "swatId": "SWAT-LEGACY-9", "partNumber": "P-LEG", "partDescription": "Legacy",
                              "region": "EU", "project": "Legacy", "meetingDecision": "PENDING", "peakYearSpend": 10, "lifetimeSpend": 20}, state["cases"])
        await service.insert_cases(session, [case])
        await session.commit()
    r = await async_client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    admin = {"X-Session-Token": r.json()["token"]}
    assert "spendCurrency" not in case and "fx" not in case
    body = {
        "partNumbers": [{"partNumber": case["partNumber"], "partDescription": case["partDescription"]}],
        "peakYearSpend": 1234, "lifetimeSpend": 5678,
        "region": case["region"], "project": case["project"], "meetingDecision": "PENDING", "followUps": [],
    }
    r = await async_client.put(f"/api/cases/{case['id']}", json=body, headers=admin)
    assert r.status_code == 200, r.text
    saved = r.json()["case"]
    assert (saved["peakYearSpend"], saved["lifetimeSpend"]) == (1234, 5678)
    assert "spendCurrency" not in saved and "fx" not in saved
