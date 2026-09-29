"""反馈 PPT 第 2、3 页（v3 Phase-7）：商务字段、BPG / FRA 门槛与可选字段。

约定：价格与摊销金额和 Phase-2 的支出一样，按提交币种填写，服务端按当时汇率折算成欧元
（保留 4 位小数，ROUND_HALF_UP），原币另存为 *Entered；确认登记时原样带进案例。
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app import logic
from app.schemas import CaseEditIn, PartNumberIn, SubmissionIn

# 件价 / 模具费按零件行（反馈人 MM 模板）；案例级只剩 Tooling Payment 与 BPG / FRA 等
PRICES = {"pcPriceCQA": "1.25", "supplierPriceLanded": "1.1", "toolingCQA": "120000", "supplierToolingCost": "118500.5"}
COMMERCIAL = {"toolingPayment": "Lumpsum", "fraAvailable": "Yes"}
ROW = {"partNumber": "R003H147A", "partDescription": "ECU Housing", **PRICES}


def _row(**over):
    return {**ROW, **over}


SUBMISSION = {
    "submitterName": "T. Ester", "submitterEmail": "t.ester@zf.com", "caseNo": "SWAT-31010",
    "partNumbers": [ROW],
    "peakYearSpend": 139000, "lifetimeSpend": 873000,  # v3 Phase-15：bundle 金额在案例级
    "region": "EU", "project": "MBEAL", "cluster": "Metal", "recommendedSupplier": "Test Supplier",
    "decisionLevel": "Level 2", "meetingDateISO": "2026-09-30",
    "isFamilyCase": "No", "involvesECM": "No", **COMMERCIAL,
}
RATES = {"basis": "OP 2026", "perEur": {"USD": "1.25", "CNY": "8.3"}}


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


def _post(client, **over):
    return client.post("/api/submissions", json={**SUBMISSION, **over})


def _submit(client, **over):
    r = _post(client, **over)
    assert r.status_code == 200, r.text
    return next(s for s in r.json()["snapshot"]["submissions"] if s["subId"] == r.json()["subId"])


# ---------- 请求边界 ----------

@pytest.mark.parametrize("raw,expected", [("0.02", "0.02"), (0.02, "0.02"), (1500, "1500"), ("1500.00", "1500"), ("", None), (None, None)])
def test_money_fields_accept_decimals_and_blank(raw, expected):
    row = PartNumberIn.model_validate(_row(pcPriceCQA=raw))
    assert (logic.money_text(row.pcPriceCQA) if row.pcPriceCQA is not None else None) == expected


@pytest.mark.parametrize("field,value", [
    ("toolingPayment", "Cash"), ("bpgAvailable", "maybe"), ("fraAvailable", 1), ("fotLeadTimeWeeks", -2),
    ("fotLeadTimeWeeks", "twelve"), ("amortizationPcs", 0), ("annualCapacity", 1.5), ("usmcaEligible", "Y"),
])
def test_invalid_commercial_values_rejected(field, value):
    with pytest.raises(ValidationError):
        SubmissionIn.model_validate(dict(SUBMISSION, **{field: value}))


@pytest.mark.parametrize("field,value", [
    ("pcPriceCQA", "-1"), ("pcPriceCQA", "abc"), ("pcPriceCQA", "1.23456"), ("averageVolume", -1), ("lifetimeVolume", 1.5),
])
def test_invalid_row_values_rejected(field, value):
    with pytest.raises(ValidationError):
        SubmissionIn.model_validate(dict(SUBMISSION, partNumbers=[_row(**{field: value})]))


# ---------- 折算 ----------

@pytest.mark.parametrize("amount,per_eur,expected", [
    ("1.25", "1.25", "1"), ("0.02", "1.25", "0.016"), ("118500.5", "1.17", "101282.4786"),
    ("7", "1", "7"), ("1000", "8.3", "120.4819"), ("0.00005", "1.25", "0"),
])
def test_money_conversion_keeps_four_decimals(amount, per_eur, expected):
    assert logic.money_text(logic.convert_money(Decimal(amount), logic.Fx(per_eur=Decimal(per_eur)))) == expected


# ---------- 门槛 ----------

@pytest.mark.parametrize("missing", ["pcPriceCQA", "supplierPriceLanded", "toolingCQA", "supplierToolingCost"])
def test_commercial_prices_are_mandatory_on_every_row(client, missing):
    r = _post(client, partNumbers=[_row(), _row(partNumber="B", **{missing: None})])
    assert r.status_code == 422 and "Pc Price CQA" in r.json()["detail"] and "every part number row" in r.json()["detail"]


def test_tooling_payment_is_mandatory(client):
    r = _post(client, toolingPayment="")
    assert r.status_code == 422 and "Tooling Payment" in r.json()["detail"]


def test_bpg_required_above_three_million_eur_lifetime(client, admin):
    # v3 Phase-15：门槛看 bundle 的 Lifetime Spend（案例级）
    r = _post(client, lifetimeSpend=3_000_001)
    assert r.status_code == 422 and "BPG" in r.json()["detail"]
    r = _post(client, lifetimeSpend=3_000_001, bpgAvailable="No")
    assert r.status_code == 422 and "BPG" in r.json()["detail"]
    assert _post(client, lifetimeSpend=3_000_001, bpgAvailable="Yes").status_code == 200
    # 门槛看的是折算后的欧元：4 Mio USD / 1.25 = 3.2 Mio EUR，仍超线
    assert client.put("/api/fx-settings", json=RATES, headers=admin).status_code == 200
    r = _post(client, caseNo="SWAT-31011", lifetimeSpend=4_000_000, currency="USD")
    assert r.status_code == 422 and "BPG" in r.json()["detail"]
    # 3.7 Mio USD / 1.25 = 2.96 Mio EUR，低于线，不需要回答
    assert _post(client, caseNo="SWAT-31011", lifetimeSpend=3_700_000, currency="USD").status_code == 200


def test_exactly_three_million_does_not_need_bpg(client):
    assert _post(client, lifetimeSpend=3_000_000).status_code == 200


def test_bundle_spend_is_mandatory_and_rows_carry_no_spend(client):
    # 领导 2026-09-29：Peak Year / Lifetime Spend 按整个 bundle 填一个，必填；零件行不再填
    for over in ({"peakYearSpend": 0}, {"lifetimeSpend": 0}):
        r = _post(client, **over)
        assert r.status_code == 422 and "bundle Peak Year Spend and Lifetime Spend" in r.json()["detail"], over
    sub = _submit(client, partNumbers=[_row(), _row(partNumber="R003B136A", partDescription="ECU Housing, WMS")],
                  peakYearSpend=578000, lifetimeSpend=3_373_000, bpgAvailable="Yes")
    assert (sub["peakYearSpend"], sub["lifetimeSpend"]) == (578000, 3_373_000)
    assert all("peakYearSpend" not in p for p in sub["partNumbers"])


def test_project_type_and_supplier_follow_the_part_number_rows(client, admin):
    # 领导 2026-09-29：一个 bundle 可混不同项目、GCS / New、不同供应商 → 三个字段按零件行；案例级去重汇总
    rows = [_row(project="MBEAL", sourcingType="New", recommendedSupplier="Supplier A"),
            _row(partNumber="R003B136A", project="ACR8", sourcingType="GCS", recommendedSupplier="Supplier B"),
            _row(partNumber="R003C001A", project="ACR8", sourcingType="GCS", recommendedSupplier="Supplier A")]
    sub = _submit(client, partNumbers=rows, project="", recommendedSupplier="")
    assert [(p["project"], p["sourcingType"], p["recommendedSupplier"]) for p in sub["partNumbers"]] == [
        ("MBEAL", "New", "Supplier A"), ("ACR8", "GCS", "Supplier B"), ("ACR8", "GCS", "Supplier A")]
    assert (sub["project"], sub["sourcingType"], sub["recommendedSupplier"]) == ("MBEAL, ACR8", "New, GCS", "Supplier A, Supplier B")
    # 行上留空沿用案例级值（旧客户端只填案例级）；两边都空 → 422
    partial = _submit(client, caseNo="SWAT-31012", partNumbers=[_row(project="", recommendedSupplier="X")], project="P0", sourcingType="C/O")
    assert (partial["partNumbers"][0]["project"], partial["partNumbers"][0]["sourcingType"]) == ("P0", "C/O")
    assert (partial["project"], partial["recommendedSupplier"]) == ("P0", "X")
    r = _post(client, caseNo="SWAT-31013", partNumbers=[_row(recommendedSupplier="")], recommendedSupplier="")
    assert r.status_code == 422 and "every part number row" in r.json()["detail"]
    # 确认成案例后：多零件案例的行带三个字段，案例级是汇总；编辑改行上的供应商，汇总跟着变
    case = client.post(f"/api/submissions/{sub['subId']}/confirm", headers=admin).json()["case"]
    assert case["recommendedSupplier"] == "Supplier A, Supplier B" and case["partNumbers"][1]["sourcingType"] == "GCS"
    edited = _edit_rows(case)
    edited[1]["recommendedSupplier"] = "Supplier A"
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, partNumbers=edited))
    assert r.status_code == 200, r.text
    assert r.json()["case"]["recommendedSupplier"] == "Supplier A" and r.json()["case"]["project"] == "MBEAL, ACR8"
    # 单零件案例：三个字段在案例顶层，零件行由顶层拼出
    single = client.post(f"/api/submissions/{partial['subId']}/confirm", headers=admin).json()["case"]
    assert single["partNumbers"] is None and single["project"] == "P0"
    assert logic.part_number_lines(single)[0]["recommendedSupplier"] == "X"


def test_fra_required_for_level_2_only(client):
    r = _post(client, fraAvailable="")
    assert r.status_code == 422 and "FRA" in r.json()["detail"]
    r = _post(client, fraAvailable="No")
    assert r.status_code == 422 and "FRA" in r.json()["detail"]
    assert _post(client, decisionLevel="Level 3", fraAvailable="").status_code == 200


def test_below_cqa_no_needs_justification(client):
    r = _post(client, belowCQA="No")
    assert r.status_code == 422 and "justification" in r.json()["detail"].lower()
    assert _post(client, belowCQA="No", cqaJustification="Raw material index above CQA assumption").status_code == 200
    assert _post(client, caseNo="SWAT-31012", belowCQA="Yes").status_code == 200


# ---------- 保存与流转 ----------

def test_prices_convert_with_submission_rate_and_keep_entered(client, admin):
    assert client.put("/api/fx-settings", json=RATES, headers=admin).status_code == 200
    sub = _submit(client, currency="USD", amortizationTotal="30000", amortizationPcs=120000,
                  partNumbers=[_row(pcPriceCQA="10.50", supplierPriceLanded="10", toolingCQA="100000",
                                    supplierToolingCost="99999.99", averageVolume=378979, lifetimeVolume=3410814)])
    line = sub["partNumbers"][0]
    assert line["pcPriceCQA"] == "8.4" and line["pcPriceCQAEntered"] == "10.5" and line["averageVolume"] == 378979
    # 单零件：行上的值同时放在顶层
    assert sub["pcPriceCQA"] == "8.4" and sub["pcPriceCQAEntered"] == "10.5" and sub["lifetimeVolume"] == 3410814
    assert sub["supplierPriceLanded"] == "8" and sub["supplierPriceLandedEntered"] == "10"
    assert sub["toolingCQA"] == "80000" and sub["supplierToolingCost"] == "79999.992"
    assert sub["amortizationTotal"] == "24000" and sub["amortizationTotalEntered"] == "30000"
    assert sub["amortizationPcs"] == 120000 and sub["amortizationPerPc"] == "0.2"  # 24000 / 120000
    assert sub["toolingPayment"] == "Lumpsum" and sub["fraAvailable"] == "Yes"
    assert sub["fx"]["currency"] == "USD"


def test_optional_fields_saved_and_blank_when_omitted(client):
    sub = _submit(client, strategicSupplier="Yes", ltaAvailable="No", fotLeadTimeWeeks=12, ppapLeadTimeWeeks=20,
                  usmcaEligible="No", annualCapacity=500000, lifetimeCapacity=2500000, belowCQA="Yes")
    assert sub["strategicSupplier"] == "Yes" and sub["ltaAvailable"] == "No"
    assert sub["fotLeadTimeWeeks"] == 12 and sub["ppapLeadTimeWeeks"] == 20
    assert sub["usmcaEligible"] == "No" and sub["annualCapacity"] == 500000 and sub["lifetimeCapacity"] == 2500000
    assert sub["amortizationTotal"] is None and sub["amortizationPcs"] is None and sub["amortizationPerPc"] == ""
    assert sub["bpgAvailable"] == ""  # 未超线，不要求回答


def test_confirm_carries_commercial_fields_into_case(client, admin):
    sub = _submit(client, amortizationTotal="30000", amortizationPcs=100000)
    r = client.post(f"/api/submissions/{sub['subId']}/confirm", headers=admin)
    assert r.status_code == 200
    case = r.json()["case"]
    for key in logic.COMMERCIAL_KEYS:
        assert case[key] == sub[key], key
    assert case["amortizationPerPc"] == "0.3"


def _edit_rows(case):
    """编辑页发回的零件行：外币折算来的按原币（*Entered）填写，与前端 editBuffer 一致。"""
    rows = []
    for line in logic.part_number_lines(case):
        row = {k: line.get(k) for k in ("partNumber", "partDescription", *logic.ROW_BUNDLE_KEYS, *logic.ROW_MONEY_KEYS, *logic.ROW_INT_KEYS)}
        if case.get("fx"):
            for k in logic.ROW_MONEY_KEYS:
                if line.get(f"{k}Entered") is not None:
                    row[k] = line[f"{k}Entered"]
        rows.append(row)
    return rows


def _edit_payload(case, **over):
    p = {"partNumbers": _edit_rows(case), "region": case["region"], "project": case["project"], "meetingDecision": "PENDING"}
    p.update(over)
    return p


def test_edit_reconverts_prices_with_case_rate_and_untouched_when_absent(client, admin):
    assert client.put("/api/fx-settings", json=RATES, headers=admin).status_code == 200
    sub = _submit(client, currency="USD", partNumbers=[_row(pcPriceCQA="10")])
    case = client.post(f"/api/submissions/{sub['subId']}/confirm", headers=admin).json()["case"]
    assert case["pcPriceCQA"] == "8"
    # 改汇率后编辑：仍按案例上记录的 1.25 折算，按原币填写
    client.put("/api/fx-settings", json={"basis": "OP 2027", "perEur": {"USD": "1.1"}}, headers=admin)
    rows = _edit_rows(case)
    rows[0].update(pcPriceCQA="20", supplierPriceLanded="19.5", toolingCQA="1000", supplierToolingCost="900")
    r = client.put(f"/api/cases/{case['id']}", headers=admin,
                   json=_edit_payload(case, partNumbers=rows, toolingPayment="MPC", fraAvailable="Yes"))
    assert r.status_code == 200, r.text
    edited = r.json()["case"]
    assert edited["pcPriceCQA"] == "16" and edited["pcPriceCQAEntered"] == "20"
    assert edited["toolingPayment"] == "MPC"
    # 不带商务字段的编辑（旧客户端 / 只改决议）不动这些值
    # 项目按零件行（v3 Phase-15）：改行上的值
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(edited, partNumbers=[dict(r, project="MBEAL-2") for r in _edit_rows(edited)]))
    assert r.status_code == 200
    again = r.json()["case"]
    assert again["pcPriceCQA"] == "16" and again["toolingPayment"] == "MPC" and again["project"] == "MBEAL-2"


def test_edit_schema_accepts_partial_commercial_block():
    edit = CaseEditIn.model_validate({"partNumbers": [{"partNumber": "1", "partDescription": "x"}],
                                      "meetingDecision": "PENDING", "toolingPayment": "MPC"})
    assert edit.toolingPayment == "MPC" and edit.amortizationTotal is None
    assert "toolingPayment" in edit.model_fields_set and "amortizationTotal" not in edit.model_fields_set


# ---------- 复测修复（Phase-11）：案例编辑的商务门槛 ----------

def _confirmed_case(client, admin, **over):
    sub = _submit(client, **over)
    return client.post(f"/api/submissions/{sub['subId']}/confirm", headers=admin).json()["case"]


def test_edit_rejects_explicit_no_on_bpg_above_three_million(client, admin):
    case = _confirmed_case(client, admin, caseNo="SWAT-31090", lifetimeSpend=5_000_000, bpgAvailable="Yes")
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, **COMMERCIAL, bpgAvailable="No"))
    assert r.status_code == 422 and "BPG" in r.json()["detail"]
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, **COMMERCIAL, bpgAvailable=""))
    assert r.status_code == 200 and r.json()["case"]["bpgAvailable"] == ""  # 留空放行


def test_edit_rejects_explicit_no_on_fra_for_level_2(client, admin):
    case = _confirmed_case(client, admin, caseNo="SWAT-31091")
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, decisionLevel="Level 2", **{**COMMERCIAL, "fraAvailable": "No"}))
    assert r.status_code == 422 and "FRA" in r.json()["detail"]
    # Level 3 不要求 FRA
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, decisionLevel="Level 3", **{**COMMERCIAL, "fraAvailable": "No"}))
    assert r.status_code == 200


def test_edit_rejects_below_cqa_no_without_justification(client, admin):
    case = _confirmed_case(client, admin, caseNo="SWAT-31092")
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, **COMMERCIAL, belowCQA="No"))
    assert r.status_code == 422 and "justification" in r.json()["detail"]
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, **COMMERCIAL, belowCQA="No", cqaJustification="Index"))
    assert r.status_code == 200


def test_rejected_edit_leaves_case_untouched(client, admin):
    case = _confirmed_case(client, admin, caseNo="SWAT-31093")
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, project="Changed", decisionLevel="Level 2", **{**COMMERCIAL, "fraAvailable": "No"}))
    assert r.status_code == 422
    snap = client.get("/api/bootstrap").json()
    assert next(c for c in snap["cases"] if c["id"] == case["id"])["project"] == case["project"]


def test_legacy_case_without_commercial_fields_is_still_editable(client, admin):
    legacy = next(c for c in client.get("/api/bootstrap").json()["cases"] if "pcPriceCQA" not in c and c["meetingDecision"] == "PENDING")
    r = client.put(f"/api/cases/{legacy['id']}", headers=admin, json=_edit_payload(legacy, partNumbers=[dict(r, project="Still editable") for r in _edit_rows(legacy)]))
    assert r.status_code == 200 and r.json()["case"]["project"] == "Still editable"


# ---------- 反馈人 MM 模板（2026-09-24）：多零件案例的件价按行 ----------

def test_multi_part_case_keeps_prices_per_row_and_blank_at_top_level(client, admin):
    rows = [_row(pcPriceCQA="1", supplierPriceLanded="0.9", averageVolume=1000),
            _row(partNumber="B", partDescription="Second", pcPriceCQA="2", supplierPriceLanded="2.2", lifetimeVolume=5)]
    sub = _submit(client, partNumbers=rows)
    assert [p["pcPriceCQA"] for p in sub["partNumbers"]] == ["1", "2"] and sub["pcPriceCQA"] is None
    case = client.post(f"/api/submissions/{sub['subId']}/confirm", headers=admin).json()["case"]
    assert [p["supplierPriceLanded"] for p in case["partNumbers"]] == ["0.9", "2.2"] and case["pcPriceCQA"] is None
    assert case["partNumbers"][0]["averageVolume"] == 1000 and case["partNumbers"][1]["lifetimeVolume"] == 5
    # 编辑：去掉一行后剩单零件，行上的值提升到顶层
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, partNumbers=_edit_rows(case)[1:]))
    assert r.status_code == 200 and r.json()["case"]["pcPriceCQA"] == "2" and r.json()["case"]["partNumbers"] is None
