"""v3 Phase-31：Case Comments（背景说明）单独保存；登记这个案例的本人，或经理 / 管理员可改。

是不是本人由服务端现查已确认的登记单；案例上不另存提交人邮箱，页面也只拿到"能不能改"（公司不允许多一份个人信息）。
"""

import json

from app import logic
from tests.test_files import _admin, _submit

ANON = {"X-Session-Token": ""}


async def _confirmed_case(client, admin, number=40311):
    sub_id, _ = await _submit(client, number)
    r = await client.post(f"/api/submissions/{sub_id}/confirm", headers=admin)
    assert r.status_code == 200, r.text
    return r.json()["case"]


async def test_the_submitter_can_edit_case_comments_after_confirmation(async_client):
    admin = await _admin(async_client)
    case = await _confirmed_case(async_client, admin)
    assert "test.user@zf.com" not in json.dumps(case)  # 案例上没有提交人邮箱
    assert (await async_client.get(f"/api/cases/{case['id']}/comments/access")).json() == {"canEdit": True}

    # 默认登录的就是提交人
    r = await async_client.put(f"/api/cases/{case['id']}/comments",
                               json={"comments": "  No tooling budget available. CO current supplier Getac.  "})
    assert r.status_code == 200, r.text
    saved = r.json()["case"]
    assert saved["submitterComments"] == "No tooling budget available. CO current supplier Getac."
    assert set(saved["submitterCommentsEdited"]) == {"when", "by"}  # 只记名字和时间，不记邮箱
    assert saved["submitterCommentsEdited"]["by"] == "Test User"
    assert "test.user@zf.com" not in json.dumps(saved)
    assert saved["committeeDiscussion"] == "Pending for Sourcing Committee Review"  # 不碰会议讨论
    stored = next(c for c in r.json()["snapshot"]["cases"] if c["id"] == case["id"])
    assert stored["submitterComments"] == saved["submitterComments"]


async def test_managers_can_edit_and_other_users_cannot(async_client):
    admin = await _admin(async_client)
    case = await _confirmed_case(async_client, admin, 40312)
    url = f"/api/cases/{case['id']}/comments"

    other = (await async_client.post("/api/auth/register",
                                     json={"email": "other@zf.com", "name": "Other", "password": "other-pass-1"})).json()["token"]
    assert (await async_client.put(url, json={"comments": "x"}, headers={"X-Session-Token": other})).status_code == 403
    assert (await async_client.put(url, json={"comments": "x"}, headers=ANON)).status_code == 401
    access = f"/api/cases/{case['id']}/comments/access"
    assert (await async_client.get(access, headers={"X-Session-Token": other})).json() == {"canEdit": False}
    assert (await async_client.get(access, headers=ANON)).json() == {"canEdit": False}
    assert (await async_client.get(access, headers=admin)).json() == {"canEdit": True}
    assert (await async_client.get("/api/cases/NOPE/comments/access", headers=admin)).status_code == 404

    r = await async_client.put(url, json={"comments": "Set by the admin"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["case"]["submitterCommentsEdited"]["by"] == "Sourcing admin"

    assert (await async_client.put("/api/cases/NOPE/comments", json={"comments": "x"}, headers=admin)).status_code == 404
    assert (await async_client.put(url, json={"comments": "x" * 5001}, headers=admin)).status_code == 422


async def test_saving_the_case_editor_keeps_the_comments(async_client):
    admin = await _admin(async_client)
    case = await _confirmed_case(async_client, admin, 40313)
    await async_client.put(f"/api/cases/{case['id']}/comments", json={"comments": "Background"})

    body = {"partNumbers": [{"partNumber": "1", "partDescription": "Test Part"}], "region": "EU", "project": "P",
            "meetingDecision": "PENDING", "committeeDiscussion": "Discussed"}
    r = await async_client.put(f"/api/cases/{case['id']}", json=body, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["case"]["submitterComments"] == "Background"
    assert r.json()["case"]["committeeDiscussion"] == "Discussed"


def test_submitter_is_found_from_the_confirmed_registration_only():
    subs = [
        {"status": "Registration Confirmed", "approvedSwatId": "SWAT-1", "submittedAt": "Sep 1, 2026, 9:00 AM", "submitterEmail": " Ann@ZF.com "},
        {"status": "Rejected", "approvedSwatId": "SWAT-2", "submittedAt": "Sep 2, 2026, 9:00 AM", "submitterEmail": "bob@zf.com"},
    ]
    first = {"swatId": "SWAT-1", "createdDate": "Sep 1, 2026, 9:00 AM"}
    assert logic.is_case_submitter(first, subs, "ann@zf.com")
    assert not logic.is_case_submitter(first, subs, "bob@zf.com")
    assert not logic.is_case_submitter(first, subs, "")
    # 同号的另一次登场（别的登记单），不算
    assert not logic.is_case_submitter({"swatId": "SWAT-1", "createdDate": "Aug 1, 2026, 9:00 AM"}, subs, "ann@zf.com")
    # 登记单没确认，不算
    assert not logic.is_case_submitter({"swatId": "SWAT-2", "createdDate": "Sep 2, 2026, 9:00 AM"}, subs, "bob@zf.com")
