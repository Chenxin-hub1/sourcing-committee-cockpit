"""v3 Phase-37：编辑页改 Commodity；Phase-39：Level 4 案例记录决议不强制演示文稿。

领导 2026-10-28：旧案例 Commodity 有错（"SO02"、Excel 里写成人名 "Yajun Zhao"），编辑页没地方改；
L4 案例很多没有演示文稿，点不成 Approved。
"""

from __future__ import annotations

import pytest

from app import commodities, logic, service
from tests.test_api import _edit_payload
from tests.test_phase19 import _confirmed_case


@pytest.fixture
def client(api_client):
    return api_client


@pytest.fixture
def admin(client):
    r = client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    assert r.status_code == 200
    return {"X-Session-Token": r.json()["token"]}


# ---------- Phase-37：Commodity ----------


def test_options_list_every_known_commodity_once_grouped_by_cluster():
    options = commodities.options()
    assert [o["commodity"] for o in options] == [
        "CH Chemical", "CH01 Functional Plastics", "Textiles",
        "SC Stamping & Mechanical Metals", "FF Forging, Forming & Tubes", "CA Casting", "Powder Metal",
        "EL Electronics", "EA Electromechanical", "Pyro",
    ]
    assert {o["cluster"] for o in options} == set(commodities.CLUSTERS)
    # 每个规范名再过一遍词表还是它自己（手改后词表重算也不会变样）
    assert all(commodities.classify(o["commodity"]) == {**o, "known": True} for o in options)


def test_bootstrap_sends_the_commodity_options(client):
    assert client.get("/api/bootstrap").json()["commodityOptions"] == commodities.options()


def test_picking_a_commodity_sets_its_cluster_and_marks_the_case_as_edited(client, admin):
    case = _confirmed_case(client, admin)
    assert (case["cluster"], case.get("commodity", "")) == ("Metal", "")
    r = client.put(f"/api/cases/{case['id']}", headers=admin,
                   json=_edit_payload(case, commodity="Pyro", cluster="Metal"))
    assert r.status_code == 200, r.text
    saved = r.json()["case"]
    assert (saved["cluster"], saved["commodity"], saved["commodityEdited"]) == ("Electronics, EA and Pyro", "Pyro", True)
    # 清空 = Not specified，Cluster 按请求
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(saved, commodity="", cluster="Chemical"))
    assert r.status_code == 200, r.text
    assert (r.json()["case"]["cluster"], r.json()["case"]["commodity"]) == ("Chemical", "")


def test_commodity_outside_the_list_is_refused_but_an_existing_one_is_kept(client, admin):
    case = _confirmed_case(client, admin)
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, commodity="Yajun Zhao"))
    assert r.status_code == 422 and "Commodity" in r.json()["detail"]
    # 导入时认不出的原值（"SO02"）：没改就照存，Cluster 照请求
    legacy = {**case, "cluster": "SO02", "commodity": "SO02"}
    logic.apply_commodity_edit(legacy, {"commodity": "SO02", "cluster": "Metal"})
    assert (legacy["cluster"], legacy["commodity"], legacy.get("commodityEdited")) == ("Metal", "SO02", True)


def test_old_clients_without_commodity_leave_it_untouched(client, admin):
    case = _confirmed_case(client, admin)
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, commodity="Pyro"))
    saved = r.json()["case"]
    payload = _edit_payload(saved)
    payload.pop("commodity", None)
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=payload)
    assert r.status_code == 200, r.text
    assert (r.json()["case"]["commodity"], r.json()["case"]["cluster"]) == ("Pyro", "Electronics, EA and Pyro")


def test_vocabulary_recompute_skips_hand_edited_cases():
    imported = {"source": {"kind": "excel"}, "commodityRaw": "Yajun Zhao", "cluster": "Metal",
                "commodity": "FF Forging, Forming & Tubes", "commodityEdited": True}
    untouched = {"source": {"kind": "excel"}, "commodityRaw": "SC03", "cluster": "", "commodity": ""}
    changed = service.normalize_commodities([imported, untouched])
    assert changed == [untouched] and imported["commodity"] == "FF Forging, Forming & Tubes"


def test_earlier_hand_edits_are_marked_once_while_the_vocabulary_is_unchanged():
    # Phase-37 之前在编辑页改过 Cluster 的导入案例：与当前词表的结果不一致 → 标成手改，以后词表重算不覆盖
    edited = {"source": {"kind": "excel"}, "commodityRaw": "Yajun Zhao", "cluster": "Metal", "commodity": "Yajun Zhao"}
    as_imported = {"source": {"kind": "excel"}, "commodityRaw": "SO02", "cluster": "SO02", "commodity": "SO02"}
    online = {"cluster": "Metal", "commodity": ""}
    assert service.mark_hand_edited_commodities([edited, as_imported, online]) == [edited]
    assert edited["commodityEdited"] is True and "commodityEdited" not in as_imported


# ---------- Phase-39：Level 4 不强制演示文稿 ----------


def test_level_4_case_can_record_a_decision_without_a_presentation(client, admin):
    case = _confirmed_case(client, admin)
    r = client.put(f"/api/cases/{case['id']}", headers=admin, json=_edit_payload(case, meetingDecision="APPROVED"))
    assert r.status_code == 422 and "Sourcing Presentation" in r.json()["detail"]
    r = client.put(f"/api/cases/{case['id']}", headers=admin,
                   json=_edit_payload(case, meetingDecision="APPROVED", decisionLevel="Level 4"))
    assert r.status_code == 200, r.text
    assert (r.json()["case"]["meetingDecision"], r.json()["case"]["decisionLevel"]) == ("APPROVED", "Level 4")
    # 链接写了就要是完整网址（Level 4 也一样）
    problems = logic.case_edit_problems({"meetingDecision": "APPROVED", "region": "EU", "decisionLevel": "Level 4",
                                         "sourcingPresentationLink": "deck.pptx"})
    assert problems == ["The Sourcing Presentation Link must be a full URL (starting with http:// or https://)."]
