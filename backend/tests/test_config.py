"""无效运行配置在启动前给出校验错误。"""

import re
from pathlib import Path

import pytest
from pydantic import AliasChoices, ValidationError

from app.config import Settings


@pytest.mark.parametrize("values", [
    {"timezone": "Unknown/Nowhere"},
    {"smtp_port": 0},
    {"smtp_port": 65536},
    {"teams_webhook_format": "typo"},
    {"public_url": "javascript:alert(1)"},
    {"public_url": "http://"},
    {"public_url": "https://example.com/#case/1"},
    {"public_url": "https://example.com/?redirect=/"},
    {"teams_webhook_url": "not-a-url"},
])
def test_invalid_configuration_is_rejected(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_webhook_keeps_query_credentials_and_public_base_path():
    settings = Settings(
        _env_file=None, public_url="https://example.com/cockpit/",
        teams_webhook_url="https://example.com/webhook?sig=test-placeholder", timezone="Asia/Taipei",
    )
    assert settings.teams_webhook_url.endswith("?sig=test-placeholder")
    assert settings.public_url == "https://example.com/cockpit/"


# ---------- 部署配置一致性：.env.example 里写的每一项，容器都拿得到、程序都读得到 ----------

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_ONLY = {"SC_UID", "SC_GID", "SC_PORT"}  # 只给 docker-compose（user: / ports:）与 start.bat 用，不进程序


def _documented_keys() -> set[str]:
    return set(re.findall(r"(?m)^(SC_[A-Z0-9_]+)=", (ROOT / ".env.example").read_text(encoding="utf-8")))


def test_every_documented_setting_is_passed_into_the_container():
    # 容器里没有宿主机的 .env 文件：没列在 docker-compose.yml environment 里的配置，填了也不生效
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    passed = set(re.findall(r"(?m)^\s+(SC_[A-Z0-9_]+):", compose))
    assert _documented_keys() - COMPOSE_ONLY - passed == set()
    assert "${SC_PORT:-8062}:8000" in compose  # 对外端口与 start.bat 共用 SC_PORT


def test_every_documented_setting_is_read_by_the_app():
    names = set()
    for name, field in Settings.model_fields.items():
        alias = field.validation_alias
        names |= set(alias.choices) if isinstance(alias, AliasChoices) else {f"SC_{name.upper()}"}
    assert _documented_keys() - COMPOSE_ONLY - names == set()


def test_teams_channel_ids_use_the_documented_names(monkeypatch):
    monkeypatch.setenv("SC_TEAMS_TEAM_ID", "team-9")
    monkeypatch.setenv("SC_TEAMS_CHANNEL_ID", "19:channel-9")
    s = Settings(_env_file=None)
    assert (s.teams_graph_team_id, s.teams_graph_channel_id) == ("team-9", "19:channel-9")
