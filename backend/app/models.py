from sqlalchemy import JSON, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CaseRow(Base):
    """案例的每周登场记录 —— 整文档 JSON 保真存储，索引列只服务查询。"""

    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(primary_key=True)  # 模板行号，如 C0001
    swat_id: Mapped[str] = mapped_column(index=True)
    week_num: Mapped[int] = mapped_column(Integer, index=True)
    case_number: Mapped[int] = mapped_column(Integer)
    doc: Mapped[dict] = mapped_column(JSON)


class SubmissionRow(Base):
    """在线登记提交。"""

    __tablename__ = "submissions"

    sub_id: Mapped[str] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(index=True)
    doc: Mapped[dict] = mapped_column(JSON)


class ReminderLogRow(Base):
    """提醒发送日志（自动 + 设置保存触发的强制检查），新记录 seq 更大。"""

    __tablename__ = "reminder_log"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc: Mapped[dict] = mapped_column(JSON)


class KvRow(Base):
    """提醒设置、管理员令牌、初始化标记与案例行号上限。"""

    __tablename__ = "kv"

    key: Mapped[str] = mapped_column(primary_key=True)
    doc: Mapped[dict] = mapped_column(JSON)


class UserRow(Base):
    """个人账号（v3 Phase-6）：邮箱（小写）为主键，整文档 JSON 存 name / role / 密码哈希等。"""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(primary_key=True)
    doc: Mapped[dict] = mapped_column(JSON)
