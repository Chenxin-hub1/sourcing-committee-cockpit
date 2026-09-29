"""持久层回归：每条用例独占临时 SQLite 文件，不读取或修改运行环境的数据。"""

import os
from types import SimpleNamespace

os.environ.setdefault("SC_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import service
from app.models import Base, CaseRow, SubmissionRow


@pytest.fixture
async def database(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = SimpleNamespace(seed_on_empty=True, timezone="America/New_York",
                               bootstrap_admin_email="", bootstrap_admin_password="")
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False), settings
    finally:
        await engine.dispose()


def case_doc(row_id="C0001", swat_id="SWAT-1"):
    return {
        "id": row_id, "swatId": swat_id, "weekNum": 1, "caseNumber": 1,
        "followUps": [{"id": "FU-1", "lastReminder": {"id": "reminder-new", "to": "a@example.test"}}],
    }


async def test_deleted_cases_stay_deleted_after_restart(database):
    sessions, _ = database
    async with sessions() as session:
        await service.init_db(session)
        assert len((await service.load_state(session))["cases"]) == 22
        await session.execute(delete(CaseRow))
        await session.commit()
    async with sessions() as session:
        await service.init_db(session)
        state = await service.load_state(session)
        assert state["cases"] == []
        assert len(state["submissions"]) == 1


async def test_existing_submissions_prevent_demo_seed(database):
    sessions, _ = database
    async with sessions() as session:
        await service.upsert_submission(session, {"subId": "SUB-0001", "status": "Waiting"})
        await session.commit()
        await service.init_db(session)
        state = await service.load_state(session)
        assert state["cases"] == []
        assert state["submissions"] == [{"subId": "SUB-0001", "status": "Waiting"}]


async def test_enabling_seed_later_does_not_populate_initialized_database(database):
    sessions, settings = database
    settings.seed_on_empty = False
    async with sessions() as session:
        await service.init_db(session)
    settings.seed_on_empty = True
    async with sessions() as session:
        await service.init_db(session)
        assert (await service.load_state(session))["cases"] == []


async def test_case_row_ids_survive_deletion_and_restart(database):
    sessions, _ = database
    async with sessions() as session:
        await service.insert_cases(session, [case_doc("C0009")])
        await session.commit()
        await service.delete_cases_by_swat(session, "SWAT-1")
        await session.commit()
    async with sessions() as session:
        replacement = case_doc()
        await service.insert_cases(session, [replacement])
        await session.commit()
        assert replacement["id"] == "C0010"
        assert (await session.get(CaseRow, "C0009")) is None


async def test_first_delete_on_existing_database_preserves_case_id_ceiling(database):
    sessions, _ = database
    async with sessions() as session:
        await service.upsert_case(session, case_doc("C0099"))
        await session.commit()
        await service.delete_cases_by_swat(session, "SWAT-1")
        replacement = case_doc()
        await service.insert_cases(session, [replacement])
        await session.commit()
        assert replacement["id"] == "C0100"


async def test_loaded_documents_do_not_mutate_session_records(database):
    sessions, _ = database
    async with sessions() as session:
        await service.insert_cases(session, [case_doc()])
        await session.commit()
        row = await session.get(CaseRow, "C0001")
        state = await service.load_state(session)
        state["cases"][0]["followUps"][0]["lastReminder"]["to"] = "changed@example.test"
        assert row.doc["followUps"][0]["lastReminder"]["to"] == "a@example.test"


async def test_loading_reused_session_refreshes_existing_records(database):
    sessions, _ = database
    async with sessions() as session:
        await service.insert_cases(session, [case_doc()])
        await session.commit()
        row = await session.get(CaseRow, "C0001")
        async with sessions() as writer:
            changed = case_doc()
            changed["project"] = "Latest edit"
            await service.upsert_case(writer, changed)
            await writer.commit()
        state = await service.load_state(session)
        assert state["cases"][0]["project"] == "Latest edit"
        assert row.doc["project"] == "Latest edit"


async def test_task_delivery_is_persisted_as_nested_json(database):
    sessions, _ = database
    async with sessions() as session:
        await service.insert_cases(session, [case_doc()])
        await session.commit()
        await service.set_task_last_delivery(session, "C0001", "FU-1", {"email": "sent"})
        await session.commit()
    async with sessions() as session:
        state = await service.load_state(session)
        assert state["cases"][0]["followUps"][0]["lastReminder"]["delivery"] == {"email": "sent"}


async def test_old_delivery_result_does_not_overwrite_new_reminder(database):
    sessions, _ = database
    async with sessions() as session:
        await service.insert_cases(session, [case_doc()])
        await session.commit()
        await service.set_task_last_delivery(
            session, "C0001", "FU-1", {"email": "failed"}, expected_reminder_id="reminder-old",
        )
        await session.commit()
        state = await service.load_state(session)
        assert "delivery" not in state["cases"][0]["followUps"][0]["lastReminder"]
        await service.set_task_last_delivery(
            session, "C0001", "FU-1", {"email": "sent"}, expected_reminder_id="reminder-new",
        )
        await session.commit()
    async with sessions() as session:
        state = await service.load_state(session)
        assert state["cases"][0]["followUps"][0]["lastReminder"]["delivery"] == {"email": "sent"}


async def test_submission_notification_preserves_newer_status(database):
    sessions, _ = database
    async with sessions() as session:
        sub = {"subId": "SUB-0001", "status": "Deleted", "rejectReason": "Case removed"}
        await service.upsert_submission(session, sub)
        await session.commit()
        notification = {"approved": True, "result": "sent"}
        updated = await service.update_submission_notification(session, "SUB-0001", notification)
        await session.commit()
        assert updated == {**sub, "notify": notification}
    async with sessions() as session:
        row = await session.get(SubmissionRow, "SUB-0001")
        assert row.status == "Deleted"
        assert row.doc == updated
        assert await service.update_submission_notification(session, "missing", notification) is None
        await session.commit()
        assert len((await session.execute(select(SubmissionRow))).scalars().all()) == 1


# ---------- 登录会话（v3 Phase-6） ----------

USER = {"email": "a.buyer@zf.com", "name": "A. Buyer", "role": "user", "passwordHash": "x"}


@pytest.mark.parametrize("bad_entry", [
    "legacy-token", {}, {"tokenHash": "h", "email": "a.buyer@zf.com", "issued_at": "yesterday"},
    {"tokenHash": "h", "email": "a.buyer@zf.com", "issued_at": None}, {"issued_at": 1000},
    {"tokenHash": "h", "email": "a.buyer@zf.com", "issued_at": float("inf")},
    {"tokenHash": "h", "email": "a.buyer@zf.com", "issued_at": 10**20},
    {"token": "old-shared-password-token", "issued_at": 1e9, "credential": "c"},  # 共享口令时代的令牌
])
async def test_malformed_sessions_are_rejected(database, bad_entry):
    sessions, _ = database
    async with sessions() as session:
        await service.save_user(session, USER)
        await service._set_kv(session, service.SESSIONS_KEY, [bad_entry])
        await session.commit()
        assert await service.session_user(session, "invalid") is None
        assert await service._kv_doc(session, service.SESSIONS_KEY) == []


async def test_session_lifecycle_and_token_is_stored_hashed(database):
    sessions, _ = database
    async with sessions() as session:
        await service.save_user(session, USER)
        first = await service.issue_session(session, USER["email"])
        second = await service.issue_session(session, USER["email"])
        assert (await service.session_user(session, first))["name"] == "A. Buyer"
        assert first not in str(await service._kv_doc(session, service.SESSIONS_KEY))  # 库里只有哈希
        await service.revoke_session(session, first)
        assert await service.session_user(session, first) is None
        assert await service.session_user(session, second) is not None
        # 改密码：别处的会话全部失效，保留当前这个
        third = await service.issue_session(session, USER["email"])
        await service.revoke_user_sessions(session, USER["email"], keep_token=third)
        await session.commit()
        assert await service.session_user(session, second) is None
        assert await service.session_user(session, third) is not None
        # 停用的账号：令牌立即无效
        await service.save_user(session, {**USER, "disabled": True})
        await session.commit()
        assert await service.session_user(session, third) is None


async def test_expired_sessions_are_removed_without_losing_current_one(database, monkeypatch):
    sessions, _ = database
    async with sessions() as session:
        await service.save_user(session, USER)
        old_token = await service.issue_session(session, USER["email"])
        later = service.time.time() + service.SESSION_TTL_SECONDS + 1
        monkeypatch.setattr(service.time, "time", lambda: later)
        current = await service.issue_session(session, USER["email"])
        assert await service.session_user(session, old_token) is None
        assert await service.session_user(session, current) is not None
        assert len(await service._kv_doc(session, service.SESSIONS_KEY)) == 1


@pytest.mark.parametrize("url", [
    "sqlite+aiosqlite://", "sqlite+aiosqlite:///:memory:",
    "sqlite+aiosqlite:///file:temporary?mode=memory&uri=true",
])
def test_memory_database_urls_do_not_create_directories(tmp_path, monkeypatch, url):
    from sqlalchemy.pool import StaticPool

    from app.db import _engine_kwargs

    monkeypatch.chdir(tmp_path)
    assert _engine_kwargs(url)["poolclass"] is StaticPool
    assert list(tmp_path.iterdir()) == []


def test_database_uri_creates_real_parent_directory(tmp_path, monkeypatch):
    from app.db import _engine_kwargs

    monkeypatch.chdir(tmp_path)
    _engine_kwargs("sqlite+aiosqlite:///file:data/cockpit.db?uri=true")
    assert (tmp_path / "data").is_dir()
    assert not (tmp_path / "file:data").exists()
