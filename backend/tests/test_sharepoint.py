"""SharePoint 建单（Graph app-only）：提交触发、结果回填、失败不阻断 —— HTTP 全替身。"""

import pytest

from app import graph
from app.config import get_settings


def submission(number):
    return {
        "submitterName": "Test User", "submitterEmail": "tester@example.com",
        "caseNo": f"SWAT-{number}", "recommendedSupplier": "Test Supplier", "project": "Test Project",
        "region": "EU", "meetingDateISO": "2026-10-07",
        "partNumbers": [{"partNumber": "1", "partDescription": "Test Part", "pcPriceCQA": "1.25", "supplierPriceLanded": "1.1",
                         "toolingCQA": "120000", "supplierToolingCost": "118500"}],
        "peakYearSpend": 100, "lifetimeSpend": 200,
        "isFamilyCase": "No", "involvesECM": "No",
        "toolingPayment": "Lumpsum", "fraAvailable": "Yes",
    }


class FakeGraphHttp:
    """替身：按 URL 分发 token / 站点解析 / List 解析 / 建单 四类请求。"""

    def __init__(self, *, item_status=201, token_status=200, site_status=200, seen=None):
        self.item_status = item_status
        self.token_status = token_status
        self.site_status = site_status
        self.seen = seen if seen is not None else []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, **kwargs):
        self.seen.append(("POST", url, kwargs))
        if "login.microsoftonline.com" in url:
            if self.token_status != 200:
                return type("R", (), {"status_code": self.token_status, "text": "invalid_client"})()
            return type("R", (), {"status_code": 200, "json": lambda *a: {
                "access_token": "fake-token", "expires_in": 3600}})()
        return type("R", (), {"status_code": self.item_status, "json": lambda *a: {"id": "42"},
                              "text": "err"})()

    async def get(self, url, **kwargs):
        self.seen.append(("GET", url, kwargs))
        path = url.replace("https://graph.microsoft.com/v1.0", "", 1)
        if ":/" in path:  # 站点按 URL 寻址（host:/path 只出现在剥掉前缀后的站点路径里）
            if self.site_status != 200:
                return type("R", (), {"status_code": self.site_status, "text": "not found"})()
            return type("R", (), {"status_code": 200, "json": lambda *a: {"id": "site-1"}})()
        if path.endswith("/lists"):
            return type("R", (), {"status_code": 200, "json": lambda *a: {"value": [
                {"id": "list-1", "displayName": "Sourcing Cases"}]}})()
        raise AssertionError(f"unexpected GET {url}")


def enable_graph(monkeypatch, fake):
    monkeypatch.setattr(get_settings(), "graph_tenant_id", "tenant-1")
    monkeypatch.setattr(get_settings(), "graph_client_id", "client-1")
    monkeypatch.setattr(get_settings(), "graph_client_secret", "secret-1")
    monkeypatch.setattr(get_settings(), "sp_site_url", "https://contoso.sharepoint.com/sites/SC")
    monkeypatch.setattr(get_settings(), "sp_list_name", "Sourcing Cases")
    monkeypatch.setattr(graph.httpx, "AsyncClient", lambda **kwargs: fake)


async def test_unconfigured_submission_records_skipped(async_client):
    created = await async_client.post("/api/submissions", json=submission(30001))
    assert created.status_code == 200
    snap = (await async_client.get("/api/bootstrap")).json()
    sub = next(s for s in snap["submissions"] if s.get("caseId") == "SWAT-30001")
    assert sub["sharepoint"]["result"] == "skipped"
    assert sub["sharepoint"]["itemId"] == ""


async def test_configured_submission_creates_item_with_contract_fields(async_client, monkeypatch):
    seen = []
    enable_graph(monkeypatch, FakeGraphHttp(seen=seen))
    created = await async_client.post("/api/submissions", json=submission(30002))
    assert created.status_code == 200

    snap = (await async_client.get("/api/bootstrap")).json()
    sub = next(s for s in snap["submissions"] if s.get("caseId") == "SWAT-30002")
    assert sub["sharepoint"] == {"when": sub["sharepoint"]["when"], "result": "created", "itemId": "42"}

    posts = [(u, kw) for method, u, kw in seen if method == "POST" and "login.microsoftonline.com" not in u]
    assert len(posts) == 1  # 一次提交恰好一条建单
    url, kwargs = posts[0]
    assert url.endswith("/sites/site-1/lists/list-1/items")
    fields = kwargs["json"]["fields"]
    assert fields["SWATId"] == "SWAT-30002"
    assert fields["Status"] == "Waiting for Registration Confirmation"
    assert fields["SubmitterEmail"] == "test.user@zf.com"  # 提交人 = 登录账号（v3 Phase-6）
    assert fields["CaseLink"].endswith("/#case/SWAT-30002")
    assert kwargs["headers"]["Authorization"] == "Bearer fake-token"


@pytest.mark.parametrize("status,expect", [
    (403, "failed: 403"),
    (400, "failed: 400"),
    (500, "failed: HTTP 500"),
])
async def test_create_failure_does_not_block_submission(async_client, monkeypatch, status, expect):
    enable_graph(monkeypatch, FakeGraphHttp(item_status=status))
    created = await async_client.post("/api/submissions", json=submission(30003))
    assert created.status_code == 200
    snap = (await async_client.get("/api/bootstrap")).json()
    sub = next(s for s in snap["submissions"] if s.get("caseId") == "SWAT-30003")
    assert sub["sharepoint"]["result"].startswith(expect)
    assert sub["status"] == "Waiting for Registration Confirmation"


async def test_token_failure_falls_back_to_error_without_item(async_client, monkeypatch):
    enable_graph(monkeypatch, FakeGraphHttp(token_status=401))
    created = await async_client.post("/api/submissions", json=submission(30004))
    assert created.status_code == 200
    snap = (await async_client.get("/api/bootstrap")).json()
    sub = next(s for s in snap["submissions"] if s.get("caseId") == "SWAT-30004")
    assert sub["sharepoint"]["result"] == "failed: token HTTP 401"
    assert sub["sharepoint"]["itemId"] == ""


async def test_confirm_does_not_create_second_item(async_client, monkeypatch):
    seen = []
    enable_graph(monkeypatch, FakeGraphHttp(seen=seen))
    login = await async_client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    headers = {"X-Session-Token": login.json()["token"]}
    created = await async_client.post("/api/submissions", json=submission(30005))
    sid = created.json()["subId"]
    confirm = await async_client.post(f"/api/submissions/{sid}/confirm", headers=headers)
    assert confirm.status_code == 200

    item_posts = [(u, kw) for method, u, kw in seen
                  if method == "POST" and "login.microsoftonline.com" not in u]
    assert len(item_posts) == 1  # 确认登记不再重复建单
    snap = (await async_client.get("/api/bootstrap")).json()
    sub = next(s for s in snap["submissions"] if s["subId"] == sid)
    assert sub["sharepoint"]["result"] == "created"


async def test_list_resolution_404_reports_clear_error(async_client, monkeypatch):
    enable_graph(monkeypatch, FakeGraphHttp(site_status=404))
    created = await async_client.post("/api/submissions", json=submission(30006))
    assert created.status_code == 200
    snap = (await async_client.get("/api/bootstrap")).json()
    sub = next(s for s in snap["submissions"] if s.get("caseId") == "SWAT-30006")
    assert "404" in sub["sharepoint"]["result"]
