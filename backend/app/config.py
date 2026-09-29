import zoneinfo
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration — all overridable via SC_* environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="SC_",
        env_file=(Path(__file__).resolve().parents[2] / ".env", Path(__file__).resolve().parents[1] / ".env"),
        extra="ignore",
    )

    # 连接串接缝：换 PostgreSQL 只需改这一个值（届时再引 Alembic 做 schema 迁移）
    database_url: str = "sqlite+aiosqlite:///./data/cockpit.db"
    # 提醒消息里「Open Action Case」链接的前缀（部署时设为对外访问地址）
    public_url: str = "http://localhost:8062/"
    # 首次启动且库为空时，是否装载与模板一致的演示数据
    seed_on_empty: bool = True
    # 提醒引擎的参考时区（IANA 名）——"今天/到期"的判断基准；模板原设定为北美东部
    timezone: str = "America/New_York"

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, v: str) -> str:
        try:
            zoneinfo.ZoneInfo(v)
        except (ValueError, zoneinfo.ZoneInfoNotFoundError) as exc:
            raise ValueError("Use a valid IANA timezone, such as America/New_York.") from exc
        return v

    @field_validator("public_url", "teams_webhook_url", "sp_site_url")
    @classmethod
    def _valid_url(cls, value: str, info) -> str:
        value = value.strip()
        if not value and info.field_name != "public_url":
            return value
        try:
            parsed = urlsplit(value)
            valid = parsed.scheme in {"http", "https"} and parsed.hostname and not any(c.isspace() for c in value)
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                valid = False
        except ValueError as exc:
            raise ValueError("Use a complete HTTP or HTTPS URL.") from exc
        if not valid or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Use a complete HTTP or HTTPS URL without credentials or a fragment.")
        if info.field_name == "public_url" and parsed.query:
            raise ValueError("SC_PUBLIC_URL must not contain a query string.")
        return value

    # ---- 个人账号（v3 Phase-6，取代共享管理员口令） ----
    # 允许自注册的公司邮箱域名（逗号分隔）
    allowed_email_domains: str = "zf.com,zf-lifetec.com"
    # 启动时若还没有任何 Sourcing 管理员，就用这两项建一个（首个管理员 / 管理员全丢时的恢复口）；
    # 已有管理员时忽略。建好后建议在账号页把真人提升为管理员、停用这个账号
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""

    # ---- 提醒真实外发：Email（公司 SMTP 中继；host 为空 = 该通道仅记日志） ----
    smtp_host: str = ""
    smtp_port: int = Field(default=25, ge=1, le=65535)
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False
    smtp_from: str = "sourcing-cockpit@zf.com"

    # ---- 提醒真实外发：Teams（webhook；url 为空 = 该通道仅记日志） ----
    teams_webhook_url: str = ""
    teams_webhook_format: Literal["teams", "flow"] = "teams"
    # Teams Graph 直发（优先于 webhook）：团队/频道 ID 配齐 + Graph 凭据齐备即启用。
    # 注意：微软将应用权限直发频道消息定位为迁移场景（见 DEPLOY.md 限制注记）。
    # 环境变量名按 .env.example / DEPLOY.md 的 SC_TEAMS_TEAM_ID / SC_TEAMS_CHANNEL_ID（之前代码只认带 GRAPH 的名字，
    # 按文档填写不生效）；带 GRAPH 的旧名也接受
    teams_graph_team_id: str = Field(default="", validation_alias=AliasChoices("SC_TEAMS_TEAM_ID", "SC_TEAMS_GRAPH_TEAM_ID"))
    teams_graph_channel_id: str = Field(default="", validation_alias=AliasChoices("SC_TEAMS_CHANNEL_ID", "SC_TEAMS_GRAPH_CHANNEL_ID"))

    # ---- SharePoint 自动建单（Graph app-only；五项任一为空 = 功能停用，确认登记不建单） ----
    graph_tenant_id: str = ""
    graph_client_id: str = ""
    graph_client_secret: str = ""
    # 团队站点地址，如 https://xxx.sharepoint.com/sites/SourcingCommittee
    sp_site_url: str = ""
    # 目标 List 显示名（建议建列时用无空格名称，内部名 = 显示名）
    sp_list_name: str = ""
    # 演示文件（v3 Phase-5）：核心凭据 + 站点地址齐备即存 SharePoint 文档库（不需要 List 名）；
    # 文档库显示名，空 = 站点默认库（"Documents"）；库内文件夹，每个案例号再建一层子文件夹
    sp_library_name: str = ""
    sp_folder: str = "Sourcing Cockpit"
    # SharePoint 未配置时的本地存放目录（相对路径基于进程工作目录，Docker 里落在 ./data 卷）
    upload_dir: str = "./data/uploads"

    # Graph 发件的发件邮箱（需 Mail.Send 权限 + 应用有权以其发送）；SMTP 未配置时生效，
    # 两者皆空 = 邮件通道停用（提醒/审批通知记 skipped）
    graph_sender: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
