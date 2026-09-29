"""核验真实并发路径与外发结果，外部服务全部替身化。"""

import asyncio

import pytest

from app import delivery, main
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


def test_unicode_password_round_trips(api_client):
    account = {"email": "unicode.user@zf.com", "name": "Unicode", "password": "管理员口令🔑-long-enough"}
    assert api_client.post("/api/auth/register", json=account).status_code == 200
    response = api_client.post("/api/auth/login", json={**account, "password": "错误口令-long-enough"})
    assert response.status_code == 401
    response = api_client.post("/api/auth/login", json=account)
    assert response.status_code == 200


def test_bootstrap_revalidates_cached_session(api_client):
    assert api_client.get("/api/bootstrap", headers={"X-Session-Token": ""}).json()["currentUser"] is None
    login = api_client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    headers = {"X-Session-Token": login.json()["token"]}
    assert api_client.get("/api/bootstrap", headers=headers).json()["currentUser"]["role"] == "admin"
    assert api_client.post("/api/auth/logout", headers=headers).status_code == 200
    stale = api_client.get("/api/bootstrap", headers=headers)
    assert stale.status_code == 200
    assert stale.json()["currentUser"] is None
    assert stale.json()["cases"]


async def test_concurrent_submissions_respect_limit(async_client, monkeypatch):
    monkeypatch.setattr(main, "SUBMIT_MAX_PER_WINDOW", 2)
    responses = await asyncio.gather(*[
        async_client.post("/api/submissions", json=submission(81000 + i)) for i in range(8)
    ])
    assert sorted(r.status_code for r in responses) == [200, 200, 429, 429, 429, 429, 429, 429]


async def test_notification_does_not_restore_deleted_case(async_client, monkeypatch):
    login = await async_client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    headers = {"X-Session-Token": login.json()["token"]}
    created = await async_client.post("/api/submissions", json=submission(82000))
    sid = created.json()["subId"]
    sending, release = asyncio.Event(), asyncio.Event()

    async def delayed_email(*args, **kwargs):
        sending.set()
        await release.wait()
        return "sent"

    monkeypatch.setattr(delivery, "send_email", delayed_email)
    confirm = asyncio.create_task(async_client.post(f"/api/submissions/{sid}/confirm", headers=headers))
    try:
        await asyncio.wait_for(sending.wait(), timeout=3)
        deleted = await async_client.delete("/api/cases/SWAT-82000", headers=headers)
        assert deleted.status_code == 200
    finally:
        release.set()
    response = await confirm
    assert response.status_code == 200
    snap = (await async_client.get("/api/bootstrap")).json()
    stored = next(s for s in snap["submissions"] if s["subId"] == sid)
    assert stored["status"] == "Deleted"
    assert stored["notify"]["result"] == "sent"
    assert not any(c["swatId"] == "SWAT-82000" for c in response.json()["snapshot"]["cases"])


async def test_concurrent_admin_sessions_remain_valid(async_client):
    responses = await asyncio.gather(*[
        async_client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"}) for _ in range(4)
    ])
    tokens = [r.json()["token"] for r in responses]
    for token in tokens:
        response = await async_client.delete("/api/cases/NOT-FOUND", headers={"X-Session-Token": token})
        assert response.status_code == 404


def test_repeat_legacy_upload_keeps_case_and_task_ids_unique(api_client):
    login = api_client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    headers = {"X-Session-Token": login.json()["token"]}
    for _ in range(2):
        response = api_client.post("/api/legacy-upload", headers=headers)
        assert response.status_code == 200
    cases = response.json()["snapshot"]["cases"]
    ids = [t["id"] for c in cases for t in c.get("followUps") or []]
    assert len(ids) == len(set(ids))
    imported = cases[22:]
    assert len({c["swatId"] for c in imported}) == 36


@pytest.mark.parametrize("status", [301, 302, 400, 500])
async def test_teams_non_success_not_reported_sent(monkeypatch, status):
    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return type("Response", (), {"status_code": status})()

    monkeypatch.setattr(get_settings(), "teams_webhook_url", "https://example.com/webhook")
    monkeypatch.setattr(delivery.httpx, "AsyncClient", Client)
    result = await delivery.deliver_teams({"swatId": "SWAT-1", "message": "Test"})
    assert result == f"failed: HTTP {status}"


async def test_smtp_partial_failure_is_visible(monkeypatch):
    import aiosmtplib
    from aiosmtplib.response import SMTPResponse

    async def partial_send(*args, **kwargs):
        return {"cc@example.com": SMTPResponse(550, "Mailbox not found")}, "OK"

    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.example.com")
    monkeypatch.setattr(aiosmtplib, "send", partial_send)
    result = await delivery.send_email("to@example.com", "Test", "Body", "cc@example.com")
    assert result.startswith("failed:")
    assert "550" in result


def test_submission_rate_limit_prunes_inactive_ips(monkeypatch):
    monkeypatch.setattr(main.time, "time", lambda: 10000)
    main._submission_times["inactive"] = [1.0]
    assert main._submission_allowed("active") is True
    assert "inactive" not in main._submission_times
