"""v3 Phase-5：演示文件上传（PPT / PDF / Excel / Word，单个 ≤ 100 MB），所有人可下载。

存放：Graph 凭据与站点配齐 → SharePoint 文档库（分块上传会话）；否则 → 服务器本地 SC_UPLOAD_DIR。
上传权限：提交人凭提交时拿到的一次性 uploadKey（只在待确认期间有效），或管理员；案例页只有管理员。
"""

import hashlib
import json

import httpx
import pytest

from app import files, graph
from app.config import get_settings
from tests.test_sharepoint import submission

PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


@pytest.fixture(autouse=True)
def _upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))


async def _admin(client):
    r = await client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    return {"X-Session-Token": r.json()["token"]}


async def _submit(client, number=40001):
    r = await client.post("/api/submissions", json=submission(number))
    assert r.status_code == 200, r.text
    return r.json()["subId"], r.json()["uploadKey"]


async def _upload(client, url, name, body, headers):
    return await client.post(url, params={"name": name}, content=body, headers={"Content-Type": PPTX, **headers})


def _sub(snapshot, sub_id):
    return next(s for s in snapshot["submissions"] if s["subId"] == sub_id)


# ---------- 文件名与类型 ----------

@pytest.mark.parametrize("raw,clean", [
    ("Sourcing deck.pptx", "Sourcing deck.pptx"),
    ("C:\\Users\\me\\KW40 deck.PPTX", "KW40 deck.PPTX"),
    ("../../etc/review.pdf", "review.pdf"),
    ('a:b*c?"d<e>|f.xlsx', "a_b_c__d_e__f.xlsx"),
    ("  report .docx ", "report .docx"),
])
def test_file_names_are_cleaned(raw, clean):
    assert files.clean_name(raw) == clean


@pytest.mark.parametrize("raw", ["", "   ", "virus.exe", "deck", "notes.txt", ".pptx", "x" * 300 + ".pdf"])
def test_disallowed_names_are_refused(raw):
    assert files.clean_name(raw) is None


# ---------- 本地存放（SharePoint 未配置） ----------

async def test_submitter_uploads_with_key_and_anyone_downloads(async_client):
    sub_id, key = await _submit(async_client)
    r = await _upload(async_client, f"/api/submissions/{sub_id}/files", "KW40 deck.pptx", b"deck-bytes", {"X-Upload-Key": key})
    assert r.status_code == 200, r.text
    record = r.json()["file"]
    # v3 Phase-15（领导要求）：系统里按案例改名 "日期 项目 零件描述 零件号, 供应商"，原文件名留在 originalName
    assert record["name"] == "2026.09.24 Test Project Test Part 1, Test Supplier.pptx" and record["originalName"] == "KW40 deck.pptx"
    assert record["size"] == 10 and record["store"] == "local"
    assert record["uploadedBy"] == "Test User" and record["uploadedAt"]
    snap = r.json()["snapshot"]
    assert _sub(snap, sub_id)["files"] == [record]
    assert "uploadKeyHash" not in json.dumps(snap) and key not in json.dumps(snap)  # 密钥不下发给其他人

    got = await async_client.get(f"/api/files/{record['id']}")
    assert got.status_code == 200 and got.content == b"deck-bytes"
    assert "2026.09.24%20Test%20Project%20Test%20Part%201%2C%20Test%20Supplier.pptx" in got.headers["content-disposition"]
    assert (await async_client.get("/api/files/F-missing")).status_code == 404


async def test_upload_key_is_required_and_stored_hashed(async_client):
    sub_id, key = await _submit(async_client, 40002)
    url = f"/api/submissions/{sub_id}/files"
    anonymous = {"X-Session-Token": ""}
    assert (await _upload(async_client, url, "a.pdf", b"x", anonymous)).status_code == 401
    assert (await _upload(async_client, url, "a.pdf", b"x", {**anonymous, "X-Upload-Key": "wrong"})).status_code == 401
    assert (await _upload(async_client, url, "a.pdf", b"x", {**anonymous, "X-Upload-Key": key})).status_code == 200
    # 提交人本人的账号（默认登录的用户）不带 key 也行；别的普通用户不行
    assert (await _upload(async_client, url, "b.pdf", b"x", {})).status_code == 200
    other = (await async_client.post("/api/auth/register", json={"email": "other@zf.com", "name": "Other", "password": "other-pass-1"})).json()["token"]
    assert (await _upload(async_client, url, "c.pdf", b"x", {"X-Session-Token": other})).status_code == 401
    assert (await _upload(async_client, url, "a.pdf", b"x", await _admin(async_client))).status_code == 200
    from app import main, service
    async with main.SessionLocal() as session:
        stored = next(s for s in (await service.load_state(session))["submissions"] if s["subId"] == sub_id)
    assert stored["uploadKeyHash"] == hashlib.sha256(key.encode()).hexdigest()


async def test_type_size_empty_and_count_limits(async_client, monkeypatch):
    sub_id, key = await _submit(async_client, 40003)
    url, auth = f"/api/submissions/{sub_id}/files", {"X-Upload-Key": key}
    r = await _upload(async_client, url, "tool.exe", b"x", auth)
    assert r.status_code == 422 and "PowerPoint" in r.json()["detail"]
    assert (await _upload(async_client, url, "empty.pdf", b"", auth)).status_code == 422
    monkeypatch.setattr(files, "MAX_BYTES", 5)
    r = await _upload(async_client, url, "big.pdf", b"123456", auth)
    assert r.status_code == 413 and "100 MB" in r.json()["detail"]
    monkeypatch.setattr(files, "MAX_BYTES", 100)
    monkeypatch.setattr(files, "MAX_FILES_PER_RECORD", 2)
    for i in range(2):
        assert (await _upload(async_client, url, f"d{i}.pdf", b"x", auth)).status_code == 200
    r = await _upload(async_client, url, "d3.pdf", b"x", auth)
    assert r.status_code == 422 and "2 files" in r.json()["detail"]
    # 被拒的上传不留临时文件
    incoming = files.upload_root() / ".incoming"
    assert not any(incoming.iterdir())


async def test_files_follow_the_registration_into_the_case(async_client):
    admin = await _admin(async_client)
    sub_id, key = await _submit(async_client, 40004)
    rec = (await _upload(async_client, f"/api/submissions/{sub_id}/files", "deck.pptx", b"d", {"X-Upload-Key": key})).json()["file"]
    case = (await async_client.post(f"/api/submissions/{sub_id}/confirm", headers=admin)).json()["case"]
    assert case["files"] == [rec]
    # 确认后提交人的 key 失效；管理员在案例页继续加、删
    r = await _upload(async_client, f"/api/submissions/{sub_id}/files", "late.pdf", b"x", {"X-Upload-Key": key})
    assert r.status_code == 422
    assert (await _upload(async_client, f"/api/cases/{case['id']}/files", "final.pdf", b"x", {})).status_code == 403
    r = await _upload(async_client, f"/api/cases/{case['id']}/files", "final.pdf", b"final", admin)
    assert r.status_code == 200
    extra = r.json()["file"]
    assert [f["name"] for f in r.json()["case"]["files"]] == ["2026.09.24 Test Project Test Part 1, Test Supplier.pptx", "2026.09.24 Test Project Test Part 1, Test Supplier.pdf"]
    assert [f["originalName"] for f in r.json()["case"]["files"]] == ["deck.pptx", "final.pdf"]
    assert extra["uploadedBy"] == "Sourcing admin"  # 上传人 = 账号姓名（demo 管理员叫 Sourcing admin）
    assert (await async_client.delete(f"/api/cases/{case['id']}/files/{extra['id']}")).status_code == 403
    r = await async_client.delete(f"/api/cases/{case['id']}/files/{extra['id']}", headers=admin)
    assert r.status_code == 200 and [f["name"] for f in r.json()["case"]["files"]] == ["2026.09.24 Test Project Test Part 1, Test Supplier.pptx"]
    assert (await async_client.get(f"/api/files/{extra['id']}")).status_code == 404
    # 删除提交时带来的文件：提交单上的同一条一起去掉，存放的文件也删掉
    r = await async_client.delete(f"/api/cases/{case['id']}/files/{rec['id']}", headers=admin)
    assert r.status_code == 200 and r.json()["case"]["files"] == []
    assert _sub(r.json()["snapshot"], sub_id)["files"] == []
    assert (await async_client.get(f"/api/files/{rec['id']}")).status_code == 404
    assert not (files.upload_root() / rec["id"]).exists()
    r = await _upload(async_client, f"/api/cases/{case['id']}/files", "deck.pptx", b"d2", admin)
    # 案例编辑不会把文件清掉
    body = {"partNumbers": [{"partNumber": "1", "partDescription": "Test Part"}], "region": "EU",
            "project": "P", "meetingDecision": "PENDING", "followUps": []}
    r = await async_client.put(f"/api/cases/{case['id']}", json=body, headers=admin)
    assert r.status_code == 200 and [f["originalName"] for f in r.json()["case"]["files"]] == ["deck.pptx"]


# ---------- SharePoint 文档库 ----------

class FakeSharePoint:
    """Graph + 上传会话替身（httpx.MockTransport），记录每个请求。"""

    def __init__(self, *, session_status=200):
        self.requests: list[httpx.Request] = []
        self.session_status = session_status
        self.received = b""

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url, method = str(request.url), request.method
        if "login.microsoftonline.com" in url:
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if url.startswith("https://upload.example/"):
            if method == "DELETE":
                return httpx.Response(204)
            _start, end_total = request.headers["Content-Range"].removeprefix("bytes ").split("-")
            end, total = (int(x) for x in end_total.split("/"))
            self.received += request.content
            if end + 1 < total:
                return httpx.Response(202, json={"nextExpectedRanges": [f"{end + 1}-"]})
            return httpx.Response(201, json={"id": "item-9", "name": "deck.pptx", "webUrl": "https://contoso.sharepoint.com/deck.pptx"})
        path = url.removeprefix("https://graph.microsoft.com/v1.0")
        if method == "GET" and path.startswith("/sites/contoso.sharepoint.com:/sites/SC"):
            return httpx.Response(200, json={"id": "site-1"})
        if method == "GET" and path.startswith("/sites/site-1/drive"):
            return httpx.Response(200, json={"id": "drive-1"})
        if method == "GET" and path.startswith("/drives/drive-1/root?"):
            return httpx.Response(200, json={"id": "root-1"})
        if method == "POST" and path == "/drives/drive-1/items/root-1/children":
            return httpx.Response(409, json={"error": {"code": "nameAlreadyExists"}})  # 顶层文件夹已存在
        if method == "GET" and path.startswith("/drives/drive-1/root:/Sourcing%20Cockpit"):
            return httpx.Response(200, json={"id": "folder-top"})
        if method == "POST" and path == "/drives/drive-1/items/folder-top/children":
            return httpx.Response(201, json={"id": "folder-case"})
        if method == "POST" and path.startswith("/drives/drive-1/items/folder-case:/") and path.endswith(":/createUploadSession"):
            if self.session_status != 200:
                return httpx.Response(self.session_status, json={"error": {"code": "accessDenied"}})
            return httpx.Response(200, json={"uploadUrl": "https://upload.example/session-1"})
        if method == "GET" and path.startswith("/drives/drive-1/items/item-9"):
            return httpx.Response(200, json={"id": "item-9", "@microsoft.graph.downloadUrl": "https://download.example/item-9"})
        if method == "DELETE" and path == "/drives/drive-1/items/item-9":
            return httpx.Response(204)
        raise AssertionError(f"unexpected {method} {url}")


def enable_sharepoint(monkeypatch, fake):
    s = get_settings()
    for key, value in {"graph_tenant_id": "tenant-1", "graph_client_id": "client-1", "graph_client_secret": "secret-1",
                       "sp_site_url": "https://contoso.sharepoint.com/sites/SC", "sp_list_name": ""}.items():
        monkeypatch.setattr(s, key, value)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(graph.httpx, "AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(fake.handler), **kwargs))


async def test_sharepoint_upload_uses_chunked_session_without_auth_on_chunks(async_client, monkeypatch):
    fake = FakeSharePoint()
    enable_sharepoint(monkeypatch, fake)
    monkeypatch.setattr(files, "CHUNK_BYTES", 327_680)  # 320 KiB：微软要求分块是它的整数倍
    body = bytes(range(256)) * 2800  # 716,800 字节 → 3 块
    sub_id, key = await _submit(async_client, 40005)
    r = await _upload(async_client, f"/api/submissions/{sub_id}/files", "deck.pptx", body, {"X-Upload-Key": key})
    assert r.status_code == 200, r.text
    record = r.json()["file"]
    assert record["store"] == "sharepoint" and record["driveId"] == "drive-1" and record["itemId"] == "item-9"
    assert record["webUrl"] == "https://contoso.sharepoint.com/deck.pptx" and record["size"] == len(body)
    chunks = [q for q in fake.requests if str(q.url).startswith("https://upload.example/")]
    assert [q.headers["Content-Range"] for q in chunks] == [
        "bytes 0-327679/716800", "bytes 327680-655359/716800", "bytes 655360-716799/716800"]
    assert all("Authorization" not in q.headers for q in chunks)
    assert fake.received == body
    session = next(q for q in fake.requests if str(q.url).endswith(":/createUploadSession"))
    assert "/items/folder-case:/2026.09.24%20Test%20Project%20Test%20Part%201%2C%20Test%20Supplier.pptx:/" in str(session.url)
    assert json.loads(session.content)["item"]["@microsoft.graph.conflictBehavior"] == "rename"
    folder = next(q for q in fake.requests if str(q.url).endswith("/items/folder-top/children"))
    assert json.loads(folder.content)["name"] == "SWAT-40005"
    assert not any((files.upload_root() / ".incoming").iterdir())  # 临时文件已清理

    # 下载：服务器换取临时下载地址，浏览器跳过去（看的人不需要 SharePoint 权限）
    got = await async_client.get(f"/api/files/{record['id']}", follow_redirects=False)
    assert got.status_code == 302 and got.headers["location"] == "https://download.example/item-9"


async def test_sharepoint_failure_is_reported_and_nothing_is_recorded(async_client, monkeypatch):
    enable_sharepoint(monkeypatch, FakeSharePoint(session_status=403))
    sub_id, key = await _submit(async_client, 40006)
    r = await _upload(async_client, f"/api/submissions/{sub_id}/files", "deck.pptx", b"abc", {"X-Upload-Key": key})
    assert r.status_code == 502 and "SharePoint" in r.json()["detail"]
    snap = (await async_client.get("/api/bootstrap")).json()
    assert _sub(snap, sub_id).get("files", []) == []
