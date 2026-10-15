"""v3 Phase-27：删除案例时一并删除附件文件。

范围：该 SWAT 全部登场行的附件、待办反馈的证据、被级联置 Deleted 的登记单上同一批文件记录。
仍被其他记录引用的文件不删（例如同号的新登记还在等审批）；SharePoint 上案例文件夹删空后一并删除。
"""

import httpx
import pytest

from app import files, graph
from app.config import get_settings
from tests.test_files import _admin, _submit, _upload


@pytest.fixture(autouse=True)
def _upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))


async def _case_with_three_files(client, admin, number):
    """登记附件 + 案例页附件 + 待办反馈证据，各一个。"""
    sub_id, key = await _submit(client, number)
    deck = (await _upload(client, f"/api/submissions/{sub_id}/files", "deck.pptx", b"deck", {"X-Upload-Key": key})).json()["file"]
    case = (await client.post(f"/api/submissions/{sub_id}/confirm", headers=admin)).json()["case"]
    extra = (await _upload(client, f"/api/cases/{case['id']}/files", "final.pdf", b"final", admin)).json()["file"]
    body = {"partNumbers": [{"partNumber": "1", "partDescription": "Test Part"}], "region": "EU", "project": "P",
            "meetingDecision": "APPROVED",
            "followUps": [{"id": "FU-27", "task": "Send PPAP", "responsible": "Owner", "notifyEmail": "owner@zf.com",
                           "dueDate": "2026-12-31", "status": "Open"}]}
    r = await client.put(f"/api/cases/{case['id']}", json=body, headers=admin)
    assert r.status_code == 200, r.text
    fb = (await client.post("/api/tasks/FU-27/feedback", json={"text": "PPAP sent"}, headers=admin)).json()["feedback"]
    r = await client.post(f"/api/tasks/FU-27/feedback/{fb['id']}/files", params={"name": "evidence.pdf"}, content=b"ev",
                          headers={"Content-Type": "application/pdf", **admin})
    assert r.status_code == 200, r.text
    return sub_id, case, [deck, extra, r.json()["file"]]


async def test_deleting_a_case_removes_every_attachment_and_clears_the_registration(async_client):
    admin = await _admin(async_client)
    sub_id, case, recs = await _case_with_three_files(async_client, admin, 40271)
    assert all((files.upload_root() / f["id"]).exists() for f in recs)

    r = await async_client.delete(f"/api/cases/{case['swatId']}", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["filesRemoved"] == 3
    for f in recs:
        assert not (files.upload_root() / f["id"]).exists()
        assert (await async_client.get(f"/api/files/{f['id']}")).status_code == 404
    sub = next(s for s in r.json()["snapshot"]["submissions"] if s["subId"] == sub_id)
    assert sub["status"] == "Deleted" and sub["files"] == []  # 登记单不再指向已删的文件


async def test_files_of_a_pending_registration_with_the_same_number_are_kept(async_client):
    admin = await _admin(async_client)
    _, case, recs = await _case_with_three_files(async_client, admin, 40272)
    # 同号回来的新登记还在等审批：它的文件放在同一个文件夹里，删除旧案例时不能动
    sub2, key2 = await _submit(async_client, 40272)
    pending = (await _upload(async_client, f"/api/submissions/{sub2}/files", "again.pptx", b"again", {"X-Upload-Key": key2})).json()["file"]

    r = await async_client.delete(f"/api/cases/{case['swatId']}", headers=admin)
    assert r.status_code == 200 and r.json()["filesRemoved"] == 3
    assert (files.upload_root() / pending["id"]).exists()
    assert (await async_client.get(f"/api/files/{pending['id']}")).status_code == 200
    assert not any((files.upload_root() / f["id"]).exists() for f in recs)


async def test_sharepoint_files_are_deleted_and_the_case_folder_goes_when_empty(monkeypatch):
    calls = []

    async def delete_file(drive_id, item_id):
        calls.append(("file", drive_id, item_id))

    async def delete_folder_if_empty(path):
        calls.append(("folder", path))
        return True

    monkeypatch.setattr(graph, "delete_file", delete_file)
    monkeypatch.setattr(graph, "delete_folder_if_empty", delete_folder_if_empty)
    monkeypatch.setattr(graph, "files_configured", lambda: True)
    records = [{"id": "F-1", "store": "sharepoint", "driveId": "d", "itemId": "i1"},
               {"id": "F-2", "store": "sharepoint", "driveId": "d", "itemId": "i2"}]
    assert await files.remove_case_files(records, "SWAT/2026:1") == 2
    assert calls == [("file", "d", "i1"), ("file", "d", "i2"),
                     ("folder", f"{get_settings().sp_folder}/{files.folder_name('SWAT/2026:1')}")]


async def test_nothing_to_delete_does_not_touch_sharepoint(monkeypatch):
    async def boom(*_a, **_k):
        raise AssertionError("SharePoint must not be called")

    monkeypatch.setattr(graph, "delete_folder_if_empty", boom)
    monkeypatch.setattr(graph, "files_configured", lambda: True)
    assert await files.remove_case_files([], "SWAT-1") == 0


def _fake_graph(monkeypatch, children, seen):
    s = get_settings()
    for key, value in {"graph_tenant_id": "t", "graph_client_id": "c", "graph_client_secret": "x",
                       "sp_site_url": "https://contoso.sharepoint.com/sites/SC"}.items():
        monkeypatch.setattr(s, key, value)

    def handler(request: httpx.Request) -> httpx.Response:
        url, method = str(request.url), request.method
        seen.append((method, url.removeprefix("https://graph.microsoft.com/v1.0")))
        if "login.microsoftonline.com" in url:
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        path = url.removeprefix("https://graph.microsoft.com/v1.0")
        if path.startswith("/sites/contoso.sharepoint.com:/sites/SC"):
            return httpx.Response(200, json={"id": "site-1"})
        if path.startswith("/sites/site-1/drive"):
            return httpx.Response(200, json={"id": "drive-1"})
        if path.startswith("/drives/drive-1/root?"):
            return httpx.Response(200, json={"id": "root-1"})
        if method == "GET" and path.startswith("/drives/drive-1/root:/Sourcing%20Cockpit/SWAT-1:/children"):
            return children
        if method == "DELETE" and path == "/drives/drive-1/root:/Sourcing%20Cockpit/SWAT-1":
            return httpx.Response(204)
        raise AssertionError(f"unexpected {method} {url}")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(graph.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    graph._reset_cache()


@pytest.mark.parametrize("children,deleted", [
    (httpx.Response(200, json={"value": []}), True),                       # 空了 → 删文件夹
    (httpx.Response(200, json={"value": [{"name": "keep.pdf"}]}), False),  # 还有文件 → 保留
    (httpx.Response(404, json={"error": {"code": "itemNotFound"}}), False),  # 没有这个文件夹 → 什么都不做
])
async def test_delete_folder_if_empty(monkeypatch, children, deleted):
    seen = []
    _fake_graph(monkeypatch, children, seen)
    assert await graph.delete_folder_if_empty(f"{get_settings().sp_folder}/SWAT-1") is deleted
    assert (("DELETE", "/drives/drive-1/root:/Sourcing%20Cockpit/SWAT-1") in seen) is deleted
