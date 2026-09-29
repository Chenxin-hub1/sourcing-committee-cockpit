"""Graph 外发：邮件 sendMail 兜底与通道优先级、Teams webhook Bearer —— HTTP 全替身。"""

from app import delivery, graph
from app.config import get_settings


class FakeGraphHttp:
    """替身：按 URL 子串路由返回固定响应，记录全部请求。"""

    def __init__(self, *, routes):
        self.routes = routes  # URL 子串 -> (status, json payload)
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, **kwargs):
        self.requests.append(("POST", url, kwargs))
        for key, (status, payload) in self.routes.items():
            if key in url:
                return type("R", (), {"status_code": status, "json": lambda *a, _p=payload: _p,
                                      "text": "err"})()
        raise AssertionError(f"unexpected POST {url}")


def enable_graph(monkeypatch, sender="cockpit@contoso.com"):
    monkeypatch.setattr(get_settings(), "graph_tenant_id", "tenant-1")
    monkeypatch.setattr(get_settings(), "graph_client_id", "client-1")
    monkeypatch.setattr(get_settings(), "graph_client_secret", "secret-1")
    monkeypatch.setattr(get_settings(), "graph_sender", sender)


def fake_http(monkeypatch, routes):
    fake = FakeGraphHttp(routes=routes)
    monkeypatch.setattr(delivery.httpx, "AsyncClient", lambda **kwargs: fake)
    return fake


TOKEN_ROUTE = ("login.microsoftonline.com", (200, {"access_token": "fake-token", "expires_in": 3600}))


async def test_send_email_prefers_smtp_over_graph(monkeypatch):
    calls = []

    async def smtp_path(*args, **kwargs):
        calls.append(("smtp", args))
        return "sent"

    async def graph_path(*args, **kwargs):
        calls.append(("graph", args))
        return "sent"

    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.example.com")
    enable_graph(monkeypatch)
    monkeypatch.setattr(delivery, "_send_via_smtp", smtp_path)
    monkeypatch.setattr(graph, "send_mail", graph_path)
    result = await delivery.send_email("to@example.com", "S", "B")
    assert result == "sent"
    assert [c[0] for c in calls] == ["smtp"]


async def test_send_email_falls_back_to_graph_when_no_smtp(monkeypatch):
    monkeypatch.setattr(get_settings(), "smtp_host", "")
    enable_graph(monkeypatch)
    seen = []

    async def graph_path(to, subject, body, cc=""):
        seen.append((to, subject, body, cc))
        return "sent"

    monkeypatch.setattr(graph, "send_mail", graph_path)
    result = await delivery.send_email("to@example.com", "Subject", "Body", "cc@example.com")
    assert result == "sent"
    assert seen == [("to@example.com", "Subject", "Body", "cc@example.com")]


async def test_send_email_unconfigured_returns_skipped(monkeypatch):
    monkeypatch.setattr(get_settings(), "smtp_host", "")
    assert await delivery.send_email("to@example.com", "S", "B") == "skipped"


async def test_graph_send_mail_payload_and_recipient_cleanup(monkeypatch):
    enable_graph(monkeypatch)
    fake = fake_http(monkeypatch, dict([TOKEN_ROUTE, ("/sendMail", (202, {}))]))
    result = await graph.send_mail("a@zf.com; bad-address; b@zf.com", "Subject", "Body", "c@zf.com")
    assert result == "sent"
    url, kwargs = next((u, kw) for _, u, kw in fake.requests if "/sendMail" in u)
    assert url.endswith("/users/cockpit%40contoso.com/sendMail")
    msg = kwargs["json"]["message"]
    assert [r["emailAddress"]["address"] for r in msg["toRecipients"]] == ["a@zf.com", "b@zf.com"]
    assert [r["emailAddress"]["address"] for r in msg["ccRecipients"]] == ["c@zf.com"]
    assert msg["body"] == {"contentType": "Text", "content": "Body"}
    assert kwargs["json"]["saveToSentItems"] is False
    assert kwargs["headers"]["Authorization"] == "Bearer fake-token"


async def test_graph_send_mail_403_carries_actionable_hint(monkeypatch):
    enable_graph(monkeypatch)
    fake_http(monkeypatch, dict([TOKEN_ROUTE, ("/sendMail", (403, {}))]))
    result = await graph.send_mail("a@zf.com", "S", "B")
    assert result.startswith("failed: 403")
    assert "Mail.Send" in result or "mailbox" in result


async def test_graph_send_mail_without_valid_recipient_makes_no_http_call(monkeypatch):
    enable_graph(monkeypatch)
    fake = fake_http(monkeypatch, dict([TOKEN_ROUTE]))
    assert await graph.send_mail("not-an-email", "S", "B") == "failed: no valid recipient address"
    assert fake.requests == []


async def test_graph_sender_unset_records_skipped(monkeypatch):
    enable_graph(monkeypatch, sender="")
    assert await graph.send_mail("a@zf.com", "S", "B") == "skipped"


async def test_teams_webhook_carries_graph_bearer(monkeypatch):
    monkeypatch.setattr(get_settings(), "teams_webhook_url", "https://flow.example.com/hook")
    enable_graph(monkeypatch, sender="unused@contoso.com")
    fake = fake_http(monkeypatch, dict([TOKEN_ROUTE, ("flow.example.com", (200, {}))]))
    result = await delivery.deliver_teams({"swatId": "SWAT-1", "message": "Test"})
    assert result == "sent"
    hook = next(r for r in fake.requests if "flow.example.com" in r[1])
    assert hook[2]["headers"]["Authorization"] == "Bearer fake-token"


async def test_teams_prefers_graph_channel_over_webhook(monkeypatch):
    monkeypatch.setattr(get_settings(), "teams_webhook_url", "https://flow.example.com/hook")
    enable_graph(monkeypatch)
    monkeypatch.setattr(get_settings(), "teams_graph_team_id", "team-1")
    monkeypatch.setattr(get_settings(), "teams_graph_channel_id", "19:channel-1")
    seen = []

    async def channel_message(text):
        seen.append(text)
        return "sent"

    monkeypatch.setattr(graph, "send_channel_message", channel_message)
    result = await delivery.deliver_teams({"swatId": "SWAT-1", "message": "Line1\nLine2"})
    assert result == "sent"
    assert seen == ["Line1\nLine2"]  # Graph 直发生效，webhook 未被触碰（fake_http 未装，触碰即报错）


async def test_graph_channel_message_payload_and_escape(monkeypatch):
    enable_graph(monkeypatch)
    monkeypatch.setattr(get_settings(), "teams_graph_team_id", "team-1")
    monkeypatch.setattr(get_settings(), "teams_graph_channel_id", "19:abc&def")
    fake = fake_http(monkeypatch, dict([TOKEN_ROUTE, ("/messages", (201, {"id": "m1"}))]))
    result = await graph.send_channel_message("Follow-up <Case>\nLine2")
    assert result == "sent"
    _, url, kwargs = next(r for r in fake.requests if "/messages" in r[1])
    assert "/teams/team-1/channels/19%3Aabc%26def/messages" in url
    assert kwargs["json"]["body"]["contentType"] == "html"
    assert kwargs["json"]["body"]["content"] == "Follow-up &lt;Case&gt;<br>Line2"
    assert kwargs["headers"]["Authorization"] == "Bearer fake-token"


async def test_graph_channel_message_errors_carry_hints(monkeypatch):
    enable_graph(monkeypatch)
    monkeypatch.setattr(get_settings(), "teams_graph_team_id", "team-1")
    monkeypatch.setattr(get_settings(), "teams_graph_channel_id", "19:x")
    fake_http(monkeypatch, dict([TOKEN_ROUTE, ("/messages", (403, {}))]))
    result = await graph.send_channel_message("Hi")
    assert result.startswith("failed: 403")

    fake_http(monkeypatch, dict([TOKEN_ROUTE, ("/messages", (404, {}))]))
    result = await graph.send_channel_message("Hi")
    assert "SC_TEAMS_TEAM_ID" in result


async def test_teams_all_unconfigured_returns_skipped(monkeypatch):
    assert await delivery.deliver_teams({"swatId": "SWAT-1", "message": "x"}) == "skipped"
