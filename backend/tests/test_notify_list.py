"""通知列表（SC_NOTIFY_LIST_NAME）：应用没有 Mail.Send、公司数据策略又禁用 Teams webhook 触发器时，
系统把邮件 / Teams 通知写成 SharePoint 列表里的一行，由 Power Automate 流用所有者的连接发出 —— HTTP 全替身。"""

import pytest

from app import delivery, graph, migrations
from app.config import get_settings
from tests.test_delivery_graph import enable_graph

SITE = "https://contoso.sharepoint.com/sites/SCC"
TOKEN = {"access_token": "fake-token", "expires_in": 3600}
LISTS = {"value": [{"id": "list-docs", "displayName": "Documents"}, {"id": "list-notify", "displayName": "Cockpit Notifications"}]}


class FakeGraph:
    """按 (方法, URL 子串) 路由返回固定响应（最长的子串优先），记录全部请求。"""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def _reply(self, method, url, kwargs):
        self.requests.append((method, url, kwargs))
        hits = sorted(((key, reply) for (m, key), reply in self.routes.items() if m == method and key in url),
                      key=lambda hit: -len(hit[0]))
        if not hits:
            raise AssertionError(f"unexpected {method} {url}")
        status, payload = hits[0][1]
        return type("R", (), {"status_code": status, "json": lambda *a, _p=payload: _p, "text": "err"})()

    async def get(self, url, **kwargs):
        return self._reply("GET", url, kwargs)

    async def post(self, url, **kwargs):
        return self._reply("POST", url, kwargs)

    async def request(self, method, url, **kwargs):
        return self._reply(method, url, kwargs)


def routes(extra=None):
    base = {("POST", "login.microsoftonline.com"): (200, TOKEN),
            ("GET", "/sites/contoso.sharepoint.com:/sites/SCC"): (200, {"id": "site-1"}),
            ("GET", "/sites/site-1/lists"): (200, LISTS),
            ("POST", "/lists/list-notify/items"): (201, {"id": "7"})}
    base.update(extra or {})
    return base


@pytest.fixture
def notify(monkeypatch):
    graph._reset_cache()  # 令牌与列表 id 缓存不跨用例
    enable_graph(monkeypatch, sender="")  # 有 Graph 凭据，但没有发件邮箱（应用没有 Mail.Send）
    for key, value in {"sp_site_url": SITE, "notify_list_name": "Cockpit Notifications", "smtp_host": "",
                       "teams_webhook_url": "", "teams_graph_team_id": "", "teams_graph_channel_id": ""}.items():
        monkeypatch.setattr(get_settings(), key, value)


def fake(monkeypatch, table):
    f = FakeGraph(table)
    monkeypatch.setattr(graph.httpx, "AsyncClient", lambda **kwargs: f)
    return f


def _item(f):
    return next(r[2]["json"]["fields"] for r in f.requests if r[1].endswith("/lists/list-notify/items"))


async def test_email_is_written_to_the_notification_list(monkeypatch, notify):
    f = fake(monkeypatch, routes())
    body = "Follow-up Task: <check> cost & capa\nOpen Action Case: http://cockpit/#case/SWAT-1"
    result = await delivery.send_email("a@zf.com, b@zf.com", "Follow-up Task for Sourcing Case SWAT-1", body, cc="c@zf.com,bad")
    assert result == "sent"
    fields = _item(f)
    assert fields == {
        "Title": "Follow-up Task for Sourcing Case SWAT-1", "channel": "email",
        "to": "a@zf.com; b@zf.com", "cc": "c@zf.com",  # Outlook 连接器用分号分隔
        "subject": "Follow-up Task for Sourcing Case SWAT-1",
        "html": 'Follow-up Task: &lt;check&gt; cost &amp; capa<br>Open Action Case: <a href="http://cockpit/#case/SWAT-1">http://cockpit/#case/SWAT-1</a>',
    }


async def test_teams_reminder_is_written_for_the_recipient(monkeypatch, notify):
    monkeypatch.setattr(get_settings(), "teams_webhook_url", "https://old.example.com/hook")  # 旧 webhook 让位
    f = fake(monkeypatch, routes())
    entry = {"swatId": "SWAT-7", "message": "Due Date: 2026-10-16\nOwner: SP Melisa", "to": "melisa@zf.com", "cc": "lead@zf.com"}
    assert await delivery.deliver_teams(entry) == "sent"
    fields = _item(f)
    assert (fields["channel"], fields["to"], fields["cc"], fields["subject"]) == ("teams", "melisa@zf.com", "", "Follow-up Task for Sourcing Case SWAT-7")
    assert fields["html"] == "Due Date: 2026-10-16<br>Owner: SP Melisa"
    assert not any("old.example.com" in r[1] for r in f.requests)


async def test_list_id_is_resolved_once_and_cached(monkeypatch, notify):
    f = fake(monkeypatch, routes())
    await delivery.send_email("a@zf.com", "S", "B")
    await delivery.send_email("a@zf.com", "S", "B")
    assert sum(1 for r in f.requests if r[0] == "GET" and r[1].endswith("/lists")) == 1


async def test_smtp_graph_mail_and_graph_channel_still_take_priority(monkeypatch, notify):
    calls = []

    async def smtp_path(*args):
        calls.append("smtp")
        return "sent"

    async def mail_path(*args):
        calls.append("graph mail")
        return "sent"

    async def channel_path(text):
        calls.append("graph channel")
        return "sent"

    monkeypatch.setattr(delivery, "_send_via_smtp", smtp_path)
    monkeypatch.setattr(graph, "send_mail", mail_path)
    monkeypatch.setattr(graph, "send_channel_message", channel_path)
    f = fake(monkeypatch, routes())
    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.example.com")
    await delivery.send_email("a@zf.com", "S", "B")
    monkeypatch.setattr(get_settings(), "smtp_host", "")
    monkeypatch.setattr(get_settings(), "graph_sender", "cockpit@zf.com")
    await delivery.send_email("a@zf.com", "S", "B")
    monkeypatch.setattr(get_settings(), "teams_graph_team_id", "team-1")
    monkeypatch.setattr(get_settings(), "teams_graph_channel_id", "19:channel-1")
    await delivery.deliver_teams({"swatId": "SWAT-1", "message": "Hi", "to": "a@zf.com"})
    assert calls == ["smtp", "graph mail", "graph channel"] and f.requests == []


async def test_unconfigured_list_is_skipped(monkeypatch, notify):
    monkeypatch.setattr(get_settings(), "notify_list_name", "")
    f = fake(monkeypatch, routes())
    assert await delivery.send_email("a@zf.com", "S", "B") == "skipped"
    assert await delivery.deliver_teams({"swatId": "SWAT-1", "message": "Hi", "to": "a@zf.com"}) == "skipped"
    assert f.requests == []


async def test_failures_are_recorded_readably(monkeypatch, notify):
    fake(monkeypatch, routes({("POST", "/lists/list-notify/items"): (400, {})}))
    assert await delivery.send_email("a@zf.com", "S", "B") == "failed: 400 (notification list columns missing — run notify-list-setup)"
    graph._reset_cache()
    fake(monkeypatch, routes({("POST", "/lists/list-notify/items"): (403, {})}))
    assert await delivery.send_email("a@zf.com", "S", "B") == "failed: 403 (site write permission missing?)"
    graph._reset_cache()
    fake(monkeypatch, routes({("GET", "/sites/site-1/lists"): (200, {"value": [{"id": "x", "displayName": "Documents"}]})}))
    result = await delivery.send_email("a@zf.com", "S", "B")
    assert result.startswith("failed: notification list 'Cockpit Notifications' not found") and "notify-list-setup" in result


async def test_no_valid_recipient_makes_no_graph_call(monkeypatch, notify):
    f = fake(monkeypatch, routes())
    assert await delivery.send_email("not-an-address", "S", "B") == "failed: no valid recipient address"
    assert await delivery.deliver_teams({"swatId": "SWAT-1", "message": "Hi", "to": ""}) == "failed: no valid recipient address"
    assert f.requests == []


# ---------- 部署时建列表：notify-list-setup ----------


async def test_setup_creates_the_list_with_every_column(monkeypatch, notify, capsys):
    f = fake(monkeypatch, routes({("GET", "/sites/site-1/lists"): (200, {"value": [{"id": "list-docs", "displayName": "Documents"}]}),
                                    ("POST", "/sites/site-1/lists"): (201, {"id": "list-new"})}))
    assert await migrations.run(["notify-list-setup"], None) == 0
    created = next(r[2]["json"] for r in f.requests if r[0] == "POST" and r[1].endswith("/sites/site-1/lists"))
    assert created["displayName"] == "Cockpit Notifications" and created["list"] == {"template": "genericList"}
    columns = {c["name"]: c["text"] for c in created["columns"]}
    assert set(columns) == {"channel", "to", "cc", "subject", "html"}
    assert columns["html"] == {"allowMultipleLines": True, "textType": "plain"}  # 正文可能超过 255 字
    assert "created list 'Cockpit Notifications'" in capsys.readouterr().out


async def test_setup_adds_only_missing_columns_to_an_existing_list(monkeypatch, notify, capsys):
    f = fake(monkeypatch, routes({("GET", "/lists/list-notify/columns"): (200, {"value": [{"name": n} for n in ("Title", "channel", "to", "cc")]}),
                                    ("POST", "/lists/list-notify/columns"): (201, {})}))
    assert await migrations.run(["notify-list-setup"], None) == 0
    added = [r[2]["json"]["name"] for r in f.requests if r[0] == "POST" and r[1].endswith("/columns")]
    assert added == ["subject", "html"]
    assert capsys.readouterr().out.splitlines() == ["added column subject", "added column html"]
    graph._reset_cache()
    fake(monkeypatch, routes({("GET", "/lists/list-notify/columns"): (200, {"value": [{"name": n} for n in graph.NOTIFY_COLUMNS]})}))
    assert await migrations.run(["notify-list-setup"], None) == 0
    assert "already has every column" in capsys.readouterr().out


async def test_setup_explains_missing_settings_and_permission(monkeypatch, notify, capsys):
    monkeypatch.setattr(get_settings(), "notify_list_name", "")
    assert await migrations.run(["notify-list-setup"], None) == 1
    assert "SC_NOTIFY_LIST_NAME" in capsys.readouterr().err
    monkeypatch.setattr(get_settings(), "notify_list_name", "Cockpit Notifications")
    fake(monkeypatch, routes({("GET", "/sites/site-1/lists"): (200, {"value": []}), ("POST", "/sites/site-1/lists"): (403, {})}))
    assert await migrations.run(["notify-list-setup"], None) == 1
    assert "403" in capsys.readouterr().err
