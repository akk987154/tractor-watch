from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="forbid" 让拼错的变量名直接报错而不是被静默忽略。
    # 这一点很重要：写错成 TELEGRAM_BOT_TOCKEN 时，原先只会得到一个空 token，
    # 通知发不出去却没有任何提示。
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    database_url: str = "sqlite:///tractor_watch.db"

    # 用 SecretStr 而不是 str：否则 token 会出现在 repr(settings)、model_dump()
    # 以及任何打印了局部变量的 traceback 里
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_chat_id: str = ""
    discord_webhook_url: SecretStr = SecretStr("")

    # 原先没有任何边界校验：设为 0 会让 watch() 的 asyncio.sleep(0) 变成忙循环，
    # 以最快速度反复抓取并写库
    check_interval_hours: int = Field(default=6, ge=1, le=168)

    # 通知失败后的最大重试次数，超过后不再重试并保留失败原因供排查
    max_notify_attempts: int = Field(default=5, ge=1, le=100)

    user_agent: str = "TractorWatch/1.0"

    # /docs 与 /openapi.json 会完整暴露接口与数据结构。
    # 该 API 目前没有任何鉴权，若不打算暴露给外部就把它关掉。
    enable_docs: bool = True

    @field_validator("database_url")
    @classmethod
    def _require_sqlite(cls, value: str) -> str:
        # 原先各处直接做 database_url.replace("sqlite:///", "")，
        # 若配成 postgresql://... 则 replace 是空操作，
        # sqlite3.connect("postgresql://...") 会创建一个以此为文件名的空库，
        # 而不是报错
        if not value.startswith("sqlite:///"):
            raise ValueError("目前仅支持 sqlite:/// 形式的 DATABASE_URL")
        return value

    @property
    def sqlite_path(self) -> str:
        """去掉 sqlite:/// 前缀后的数据库文件路径"""
        return self.database_url[len("sqlite:///"):]

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token.get_secret_value() and self.telegram_chat_id)

    @property
    def discord_enabled(self) -> bool:
        return bool(self.discord_webhook_url.get_secret_value())


settings = Settings()
