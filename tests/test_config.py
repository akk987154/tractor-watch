"""配置校验测试。

原实现没有任何校验：
- DATABASE_URL 配成 postgresql://... 时，replace("sqlite:///", "") 是空操作，
  sqlite3.connect() 会创建一个以该字符串为文件名的空库，而不是报错
- CHECK_INTERVAL_HOURS=0 会让 watch() 的 asyncio.sleep(0) 变成忙循环
- 变量名拼错只会得到空值，例如 TELEGRAM_BOT_TOCKEN 让通知静默失效
"""

import pytest
from pydantic import ValidationError

from tractor_watch.config import Settings

_MANAGED_KEYS = (
    "DATABASE_URL",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "DISCORD_WEBHOOK_URL",
    "CHECK_INTERVAL_HOURS",
    "MAX_NOTIFY_ATTEMPTS",
    "ENABLE_DOCS",
    "USER_AGENT",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """conftest 会设置 DATABASE_URL 等变量，这里清掉以便测试默认值"""
    for key in _MANAGED_KEYS:
        monkeypatch.delenv(key, raising=False)


def make(**env):
    """构造一个只看传入参数、不读 .env 文件的 Settings"""
    return Settings(_env_file=None, **env)


def test_defaults_are_sane():
    settings = make()
    assert settings.sqlite_path == "tractor_watch.db"
    assert settings.check_interval_hours == 6
    assert settings.max_notify_attempts == 5
    assert settings.telegram_enabled is False
    assert settings.discord_enabled is False


def test_rejects_non_sqlite_database_url():
    with pytest.raises(ValidationError):
        make(database_url="postgresql://localhost/tractor")


def test_accepts_sqlite_url_and_strips_prefix():
    settings = make(database_url="sqlite:///data/tractor_watch.db")
    assert settings.sqlite_path == "data/tractor_watch.db"


@pytest.mark.parametrize("value", [0, -1, 169, 1000])
def test_rejects_out_of_range_check_interval(value):
    with pytest.raises(ValidationError):
        make(check_interval_hours=value)


def test_rejects_out_of_range_max_notify_attempts():
    with pytest.raises(ValidationError):
        make(max_notify_attempts=0)


def test_secrets_are_not_exposed_in_repr():
    settings = make(
        telegram_bot_token="123456:SUPERSECRETTOKEN",
        telegram_chat_id="42",
        discord_webhook_url="https://discord.com/api/webhooks/1/SUPERSECRET",
    )
    text = repr(settings)
    assert "SUPERSECRETTOKEN" not in text
    assert "SUPERSECRET" not in text

    # 但业务代码仍能取到真实值
    assert settings.telegram_enabled is True
    assert settings.telegram_bot_token.get_secret_value() == "123456:SUPERSECRETTOKEN"


def test_enabled_flags_require_both_telegram_fields():
    assert make(telegram_bot_token="1:abc").telegram_enabled is False
    assert make(telegram_chat_id="42").telegram_enabled is False
    assert make(telegram_bot_token="1:abc", telegram_chat_id="42").telegram_enabled is True


def test_rejects_typo_in_env_file(tmp_path):
    """extra="forbid" 的价值所在：拼错的键必须报错而不是被静默忽略"""
    env_file = tmp_path / ".env"
    env_file.write_text("TELEGRAM_BOT_TOCKEN=123456:abc\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        Settings(_env_file=str(env_file))


def test_unrelated_environment_variables_are_ignored(monkeypatch):
    """必须确认 extra="forbid" 不会把无关的环境变量也当成错误。

    容器里会有 PATH / HOSTNAME / PYTHONUNBUFFERED 等大量变量，
    如果这些触发校验失败，服务在 docker 里根本起不来。
    """
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")
    monkeypatch.setenv("HOSTNAME", "container-1")
    monkeypatch.setenv("PYTHONUNBUFFERED", "1")
    monkeypatch.setenv("SOME_COMPLETELY_UNRELATED_VAR", "value")

    settings = Settings(_env_file=None)
    assert settings.check_interval_hours == 6


def test_reads_managed_values_from_environment(monkeypatch):
    monkeypatch.setenv("CHECK_INTERVAL_HOURS", "12")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///tmp/x.db")

    settings = Settings(_env_file=None)
    assert settings.check_interval_hours == 12
    assert settings.sqlite_path == "tmp/x.db"
