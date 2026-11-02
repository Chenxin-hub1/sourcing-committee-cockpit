"""v3 Phase-43：Follow-ups 页不再显示 "Reminders sent automatically" 日志表。

Teams 评论（2026-11-02 收到）："We don't need the list showing reminders sent automatically."
页面不显示了，日志（含收件邮箱）也就不再随快照下发给每个浏览器；服务器照样记，留在库里。
"""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy

import pytest

from app import db, logic, service


@pytest.fixture
def admin(api_client):
    r = api_client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    assert r.status_code == 200
    return {"X-Session-Token": r.json()["token"]}


def test_snapshot_leaves_out_the_reminder_log():
    state = {"cases": [], "submissions": [], "settings": deepcopy(logic.REMINDER_DEFAULTS),
             "log": [{"_seq": 1, "when": "Oct 15, 12:42 AM", "trigger": "Overdue by 6 days", "taskId": "T1",
                      "to": "melisa.bouzo@zf-lifetec.com", "cc": "rafal.matuszek@zf-lifetec.com"}]}
    snap = service.snapshot(state)
    assert "autoLog" not in snap
    text = json.dumps(snap)
    assert "melisa.bouzo@zf-lifetec.com" not in text and "rafal.matuszek@zf-lifetec.com" not in text


def test_reminder_check_still_logs_on_the_server_but_the_page_never_gets_the_log(api_client, admin):
    r = api_client.put("/api/reminder-settings", headers=admin,
                       json={"enabled": True, "overdueEveryDays": 1, "channel": "Email", "alwaysCc": ""})
    assert r.status_code == 200
    assert "autoLog" not in r.json()["snapshot"]
    assert "autoLog" not in api_client.get("/api/bootstrap").json()

    async def _log():
        async with db.SessionLocal() as session:
            return (await service.load_state(session))["log"]

    assert asyncio.run(_log()), "the forced re-run reminds the seed's overdue tasks and keeps the log on the server"
