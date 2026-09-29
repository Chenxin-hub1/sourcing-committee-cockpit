from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from .config import get_settings


def _engine_kwargs(url: str) -> dict[str, object]:
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        # 确保数据目录存在（相对路径基于进程工作目录）
        path = parsed.database
        if not path or path == ":memory:" or parsed.query.get("mode") == "memory":
            # 内存库需要单连接 + StaticPool，否则每次连接各拿一份空库
            return {"url": url, "connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
        if parsed.query.get("uri") == "true" and path.startswith("file:"):
            path = path[5:]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # timeout：SQLite 驱动的 busy 等待（默认仅 5s）——并发写冲突时多等一会而不是立刻报 database is locked
        return {"url": url, "connect_args": {"timeout": 30}}
    return {"url": url}


def make_engine():
    return create_async_engine(**_engine_kwargs(get_settings().database_url))


def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def register_pragmas(engine):
    if engine.url.get_backend_name() == "sqlite":
        event.listen(engine.sync_engine, "connect", _set_sqlite_pragma)


Engine = make_engine()
register_pragmas(Engine)
SessionLocal = async_sessionmaker(Engine, expire_on_commit=False)
