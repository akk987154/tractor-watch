"""测试公共配置。

重要：必须在任何 tractor_watch 模块被导入之前设置 DATABASE_URL。
settings 是模块级单例，而 web.py 在导入时就会创建 Database，
否则会在仓库根目录留下一个 tractor_watch.db。
"""

import os
import tempfile
from pathlib import Path

import pytest

_TMP_ROOT = Path(tempfile.mkdtemp(prefix="tractor-watch-tests-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP_ROOT / 'default.db'}")
# 测试环境不应触发真实通知
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")
os.environ.setdefault("TELEGRAM_CHAT_ID", "")
os.environ.setdefault("DISCORD_WEBHOOK_URL", "")

from tractor_watch.database import Database  # noqa: E402
from tractor_watch.models import PriceAlert, TractorListing  # noqa: E402


@pytest.fixture
def db(tmp_path) -> Database:
    return Database(str(tmp_path / "test.db"))


@pytest.fixture
def listing():
    def _make(**overrides) -> TractorListing:
        values = {
            "source": "TractorHouse",
            "source_id": "th-0001",
            "brand": "John Deere",
            "model": "5075E",
            "year": 2020,
            "hours": 1200,
            "price": 300000.0,
            "location": "黑龙江省哈尔滨市",
            "url": "https://www.tractorhouse.com/listings/1",
        }
        values.update(overrides)
        return TractorListing(**values)

    return _make


@pytest.fixture
def alert():
    return PriceAlert(
        listing_id=1,
        old_price=300000.0,
        new_price=270000.0,
        change_percent=-10.0,
    )
