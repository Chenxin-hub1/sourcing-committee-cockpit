"""v3 Phase-12：旧美元案例一次性换算成欧元（反馈人答复问题 1）。

旧数据没有 spendCurrency（当初按美元录入）。换算按财务 OP 汇率（1 EUR = X USD）做除法，
原美元金额留在 *Entered，记录带上汇率快照与换算时间；之后编辑仍按美元填写、按同一汇率折算。
换算由管理员在服务器上手动跑一次：python -m app.migrations usd-to-eur（默认只预览，--apply 才写库）。
"""

from copy import deepcopy
from decimal import Decimal

from app import logic, main, migrations

FX = {"currency": "USD", "perEur": "1.17", "basis": "OP 2025 plan rates 2026"}
WHEN = "Sep 24, 6:30 PM"


# ---------- 单条记录 ----------

def test_single_part_case_converts_top_level_amounts_and_keeps_usd():
    case = {"id": "C1", "partNumbers": None, "partNumber": "P1", "partDescription": "Housing",
            "peakYearSpend": 1_170_000, "lifetimeSpend": 2_340_001}
    assert logic.convert_legacy_record(case, FX, WHEN) is True
    assert case["spendCurrency"] == "EUR"
    # 2,340,001 / 1.17 = 2,000,000.85 → 整欧元四舍五入
    assert (case["peakYearSpend"], case["lifetimeSpend"]) == (1_000_000, 2_000_001)
    assert (case["peakYearSpendEntered"], case["lifetimeSpendEntered"]) == (1_170_000, 2_340_001)
    assert case["fx"] == {**FX, "convertedAt": WHEN}
    assert case["partNumbers"] is None and case["partNumber"] == "P1"


def test_multi_part_case_converts_each_row_and_totals_are_row_sums():
    case = {"id": "C2", "partNumber": "P1", "peakYearSpend": 118, "lifetimeSpend": 236, "partNumbers": [
        {"partNumber": "P1", "partDescription": "A", "peakYearSpend": 117, "lifetimeSpend": 234},
        {"partNumber": "P2", "partDescription": "B", "peakYearSpend": 1, "lifetimeSpend": 2},
    ]}
    assert logic.convert_legacy_record(case, FX, WHEN)
    rows = case["partNumbers"]
    assert [(r["peakYearSpend"], r["lifetimeSpend"]) for r in rows] == [(100, 200), (1, 2)]
    assert [(r["peakYearSpendEntered"], r["lifetimeSpendEntered"]) for r in rows] == [(117, 234), (1, 2)]
    assert (case["peakYearSpend"], case["lifetimeSpend"]) == (101, 202)
    assert (case["peakYearSpendEntered"], case["lifetimeSpendEntered"]) == (118, 236)


def test_prices_and_amortization_convert_to_four_decimals():
    case = {"id": "C3", "partNumbers": None, "partNumber": "P1", "partDescription": "Housing",
            "peakYearSpend": 0, "lifetimeSpend": 0, "pcPriceCQA": "11.7", "supplierPriceLanded": "1",
            "toolingCQA": "117000", "supplierToolingCost": None, "averageVolume": 5,
            "toolingPayment": "Lumpsum", "amortizationTotal": "1170", "amortizationPcs": 100}
    logic.convert_legacy_record(case, FX, WHEN)
    assert case["pcPriceCQA"] == "10" and case["pcPriceCQAEntered"] == "11.7"
    assert case["supplierPriceLanded"] == "0.8547"  # 1 / 1.17 = 0.854700…
    assert case["toolingCQA"] == "100000" and case["supplierToolingCost"] is None
    assert case["averageVolume"] == 5 and case["toolingPayment"] == "Lumpsum"
    assert case["amortizationTotal"] == "1000" and case["amortizationTotalEntered"] == "1170"
    assert case["amortizationPerPc"] == "10"


def test_submission_without_part_rows_keeps_its_shape():
    # 模板演示数据里的提交单只有顶层零件字段，没有 partNumbers 键
    sub = {"subId": "SUB-1", "partNumber": "P1", "partDescription": "x", "peakYearSpend": 117, "lifetimeSpend": 234}
    logic.convert_legacy_record(sub, FX, WHEN)
    assert "partNumbers" not in sub
    assert (sub["peakYearSpend"], sub["peakYearSpendEntered"]) == (100, 117)


def test_records_already_in_eur_are_left_alone():
    case = {"id": "C4", "spendCurrency": "EUR", "fx": {"currency": "USD", "perEur": "1.25", "basis": ""},
            "partNumbers": None, "peakYearSpend": 80, "lifetimeSpend": 160, "peakYearSpendEntered": 100}
    before = deepcopy(case)
    assert logic.convert_legacy_record(case, FX, WHEN) is False
    assert case == before


# ---------- 整库换算（管理员在服务器上跑） ----------

async def _bootstrap(client):
    return (await client.get("/api/bootstrap")).json()


async def _admin(client):
    r = await client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    return {"X-Session-Token": r.json()["token"]}


async def test_dry_run_reports_counts_and_changes_nothing(async_client, capsys):
    before = await _bootstrap(async_client)
    legacy = [c for c in before["cases"] if "spendCurrency" not in c]
    assert legacy
    assert await migrations.run(["usd-to-eur", "--per-eur", "1.17"], main.SessionLocal) == 0
    out = capsys.readouterr().out
    assert f"{len(legacy)} case rows" in out and "dry run" in out.lower()
    assert (await _bootstrap(async_client))["cases"] == before["cases"]


async def test_conversion_needs_a_usd_rate(async_client, capsys):
    assert await migrations.run(["usd-to-eur", "--apply"], main.SessionLocal) == 2
    assert "USD rate" in capsys.readouterr().err
    assert all("spendCurrency" not in c for c in (await _bootstrap(async_client))["cases"])


async def test_apply_uses_dashboard_rate_converts_once_and_edits_stay_in_usd(async_client):
    admin = await _admin(async_client)
    r = await async_client.put("/api/fx-settings", headers=admin,
                               json={"basis": "OP 2025 plan rates 2026", "perEur": {"USD": "1.17", "CNY": "8.3"}})
    assert r.status_code == 200
    before = {c["id"]: c for c in (await _bootstrap(async_client))["cases"]}

    assert await migrations.run(["usd-to-eur", "--apply"], main.SessionLocal) == 0
    after = await _bootstrap(async_client)
    assert all(c["spendCurrency"] == "EUR" for c in after["cases"] + after["submissions"])
    case = next(c for c in after["cases"] if c["partNumbers"] is None and c["meetingDecision"] == "PENDING")
    old = before[case["id"]]
    assert case["peakYearSpendEntered"] == old["peakYearSpend"]
    assert case["peakYearSpend"] == logic.to_eur(old["peakYearSpend"], logic.Fx(per_eur=Decimal("1.17")))
    assert case["fx"]["perEur"] == "1.17" and case["fx"]["basis"] == "OP 2025 plan rates 2026"
    assert case["fx"]["currency"] == "USD" and case["fx"]["convertedAt"]

    # 再跑一次：没有旧记录可换算
    assert await migrations.run(["usd-to-eur", "--apply"], main.SessionLocal) == 0
    assert (await _bootstrap(async_client))["cases"] == after["cases"]

    # 换算后的案例编辑时仍按美元填写，按 1.17 折算
    body = {"partNumbers": [{"partNumber": case["partNumber"], "partDescription": case["partDescription"]}],
            "peakYearSpend": 117, "lifetimeSpend": 234,
            "region": case["region"], "project": case["project"], "meetingDecision": "PENDING", "followUps": []}
    r = await async_client.put(f"/api/cases/{case['id']}", json=body, headers=admin)
    assert r.status_code == 200, r.text
    saved = r.json()["case"]
    assert (saved["peakYearSpend"], saved["peakYearSpendEntered"]) == (100, 117)
