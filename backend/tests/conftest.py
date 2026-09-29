"""测试独占临时数据库；所有外发通道强制关闭，避免读取开发环境的真实配置。"""

import asyncio
import os

for key, value in {
    "SC_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    "SC_SEED_ON_EMPTY": "true",
    # v3 Phase-6：个人账号。启动时建 demo 管理员；测试用 example.com 邮箱，也放进允许的域名
    "SC_BOOTSTRAP_ADMIN_EMAIL": "admin@zf.com",
    "SC_BOOTSTRAP_ADMIN_PASSWORD": "test-admin",
    "SC_ALLOWED_EMAIL_DOMAINS": "zf.com,zf-lifetec.com,example.com",
    "SC_TIMEZONE": "America/New_York",
    "SC_PUBLIC_URL": "http://localhost:8000/",
    "SC_SMTP_HOST": "",
    "SC_SMTP_PORT": "25",
    "SC_SMTP_STARTTLS": "false",
    "SC_SMTP_USER": "",
    "SC_SMTP_PASSWORD": "",
    "SC_SMTP_FROM": "sourcing-cockpit@test.invalid",
    "SC_TEAMS_WEBHOOK_URL": "",
    "SC_TEAMS_WEBHOOK_FORMAT": "teams",
    "SC_TEAMS_TEAM_ID": "",
    "SC_TEAMS_CHANNEL_ID": "",
    "SC_GRAPH_TENANT_ID": "",
    "SC_GRAPH_CLIENT_ID": "",
    "SC_GRAPH_CLIENT_SECRET": "",
    "SC_SP_SITE_URL": "",
    "SC_SP_LIST_NAME": "",
    "SC_GRAPH_SENDER": "",
}.items():
    os.environ[key] = value

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import db, graph, main

FROZEN_NOW = "2026-09-24T09:00:00"  # 登记截止（Phase-8）按"现在"判断；冻结后用例不随日历失效


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app import logic

    monkeypatch.setattr(logic, "na_now", lambda: datetime.fromisoformat(FROZEN_NOW).replace(tzinfo=ZoneInfo(logic.get_settings().timezone)))


@pytest.fixture
def isolated_app(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    db.register_pragmas(engine)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, "Engine", engine)
    monkeypatch.setattr(db, "SessionLocal", sessions)
    monkeypatch.setattr(main, "SessionLocal", sessions)
    monkeypatch.setattr(main, "_write_lock", asyncio.Lock())
    main._login_failures.clear()
    main._submission_times.clear()
    main._register_times.clear()
    graph._reset_cache()  # 令牌/站点缓存按配置键隔离，测试间不串台
    yield main.app
    main._login_failures.clear()
    main._submission_times.clear()
    graph._reset_cache()
    asyncio.run(engine.dispose())


# 提交登记要登录（v3 Phase-6）：两个客户端默认以普通用户登录；管理员请求显式带自己的令牌头覆盖它
DEFAULT_USER = {"email": "test.user@zf.com", "name": "Test User", "password": "user-pass-123"}


@pytest.fixture
def api_client(isolated_app):
    with TestClient(isolated_app) as client:
        client.headers["X-Session-Token"] = client.post("/api/auth/register", json=DEFAULT_USER).json()["token"]
        main._register_times.clear()
        yield client


@pytest.fixture
async def async_client(isolated_app):
    async with (
        main.lifespan(isolated_app),
        AsyncClient(transport=ASGITransport(app=isolated_app), base_url="http://test") as client,
    ):
        client.headers["X-Session-Token"] = (await client.post("/api/auth/register", json=DEFAULT_USER)).json()["token"]
        main._register_times.clear()
        yield client
