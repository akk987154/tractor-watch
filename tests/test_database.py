"""数据库层测试。

重点覆盖两类回归：
1. upsert_listing 必须能区分"新增"与"更新"—— 原实现所有分支都返回真值，
   调用方用真值判断，导致 stats["new"] 恒为 0。
2. 通知状态机必须允许失败重试 —— 原先"发送失败也标记已通知"，
   配合 notifier 吞异常，告警会被永久静默丢弃。
"""

import sqlite3

import pytest

from tractor_watch.database import Database, load_history


def test_upsert_reports_created_then_updated(db, listing):
    listing_id, created = db.upsert_listing(listing())
    assert created is True
    assert isinstance(listing_id, int)

    same_id, created_again = db.upsert_listing(listing())
    assert created_again is False
    assert same_id == listing_id


def test_price_drop_creates_alert_and_history(db, listing):
    listing_id, _ = db.upsert_listing(listing(price=300000.0))
    db.upsert_listing(listing(price=270000.0))

    alerts = db.get_alerts()
    assert len(alerts) == 1
    assert alerts[0]["listing_id"] == listing_id
    assert alerts[0]["change_percent"] == -10.0

    history = db.get_price_history(listing_id)
    assert len(history) == 1
    assert history[0]["price"] == 270000.0
    assert history[0]["old_price"] == 300000.0


def test_unchanged_price_creates_no_alert(db, listing):
    db.upsert_listing(listing(price=300000.0))
    db.upsert_listing(listing(price=300000.0))
    assert db.get_alerts() == []


def test_get_alerts_returns_newest_first(db, listing):
    """回归：原先按 notified_at DESC 排序，而新建告警该列为 NULL。

    SQLite 中 NULL 在 DESC 里排在最后，于是最新、最需要处理的告警
    反而被挤到列表底部，正好落在 LIMIT 之外。
    """
    listing_id, _ = db.upsert_listing(listing(price=300000.0))
    for price in (290000.0, 280000.0, 260000.0):
        db.upsert_listing(listing(price=price))

    alerts = db.get_alerts(limit=10)
    assert [a["id"] for a in alerts] == sorted((a["id"] for a in alerts), reverse=True)
    assert alerts[0]["new_price"] == 260000.0
    assert alerts[-1]["listing_id"] == listing_id


def test_claim_is_exclusive(db, listing):
    db.upsert_listing(listing(price=300000.0))
    db.upsert_listing(listing(price=270000.0))
    alert_id = db.get_alerts()[0]["id"]

    assert db.claim_alert(alert_id) is True
    # 第二个进程不应该抢到同一条告警，否则会重复发送
    assert db.claim_alert(alert_id) is False


def test_release_makes_alert_retryable_and_records_error(db, listing):
    db.upsert_listing(listing(price=300000.0))
    db.upsert_listing(listing(price=270000.0))
    alert_id = db.get_alerts()[0]["id"]

    assert db.claim_alert(alert_id) is True
    db.release_alert(alert_id, "Telegram(HTTPStatusError)")

    # 释放后必须重新出现在待发送列表里
    pending = db.get_unnotified_alerts()
    assert [a["id"] for a in pending] == [alert_id]
    assert pending[0]["notify_attempts"] == 1
    assert pending[0]["last_notify_error"] == "Telegram(HTTPStatusError)"

    assert db.claim_alert(alert_id) is True


def test_unnotified_alerts_respect_max_attempts(db, listing):
    db.upsert_listing(listing(price=300000.0))
    db.upsert_listing(listing(price=270000.0))
    alert_id = db.get_alerts()[0]["id"]

    for _ in range(3):
        db.claim_alert(alert_id)
        db.release_alert(alert_id, "boom")

    assert db.get_unnotified_alerts(max_attempts=5) != []
    assert db.get_unnotified_alerts(max_attempts=3) == []
    assert db.count_exhausted_alerts(max_attempts=3) == 1
    assert db.count_pending_alerts(max_attempts=5) == 1


def test_notified_alert_is_not_retried(db, listing):
    db.upsert_listing(listing(price=300000.0))
    db.upsert_listing(listing(price=270000.0))
    alert_id = db.get_alerts()[0]["id"]

    assert db.claim_alert(alert_id) is True  # 抢占即视为已通知
    assert db.get_unnotified_alerts() == []


def test_migration_adds_columns_to_legacy_database(tmp_path):
    """遗留数据库里的 alerts 表没有新列，打开时应当自动补齐"""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            source_id TEXT NOT NULL,
            brand TEXT NOT NULL,
            model TEXT NOT NULL,
            year INTEGER,
            hours INTEGER,
            price REAL,
            location TEXT,
            url TEXT,
            condition TEXT DEFAULT 'used',
            first_seen TEXT,
            last_seen TEXT,
            last_price REAL,
            price_history TEXT DEFAULT '[]',
            UNIQUE(source, source_id)
        )
    """)
    conn.execute("""
        CREATE TABLE alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER NOT NULL,
            old_price REAL,
            new_price REAL,
            change_percent REAL,
            notified_at TEXT
        )
    """)
    conn.execute(
        "INSERT INTO listings (source, source_id, brand, model, price) "
        "VALUES ('TractorHouse', 'legacy-1', 'John Deere', '5075E', 300000)"
    )
    conn.execute(
        "INSERT INTO alerts (listing_id, old_price, new_price, change_percent) "
        "VALUES (1, 10, 9, -10)"
    )
    conn.commit()
    conn.close()

    db = Database(str(path))
    alerts = db.get_alerts()
    assert len(alerts) == 1
    assert alerts[0]["notify_attempts"] == 0
    assert alerts[0]["last_notify_error"] is None
    # 补齐的新列必须真的可用
    assert db.claim_alert(alerts[0]["id"]) is True


def test_orphaned_alerts_are_invisible_and_foreign_keys_are_enforced(db, listing):
    """get_alerts 是 INNER JOIN，因此孤儿告警不会出现在接口里。

    现在 Database 的连接启用了 PRAGMA foreign_keys=ON，新建孤儿告警会被拒绝。
    注意该 PRAGMA 是**按连接**生效的，所以这里必须在测试自己的连接上显式打开，
    否则测的就不是 schema 约束而是默认关闭的状态。
    """
    listing_id, _ = db.upsert_listing(listing(price=300000.0))
    db.upsert_listing(listing(price=270000.0))
    assert len(db.get_alerts()) == 1

    conn = sqlite3.connect(db.path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO alerts (listing_id, old_price, new_price, change_percent) "
                "VALUES (999999, 1, 2, 3)"
            )
    finally:
        conn.close()


def test_database_connections_enable_foreign_keys(db):
    """确认 Database 自己的连接确实打开了外键约束"""
    with db._connect() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1



def test_like_metacharacters_are_escaped(db, listing):
    """brand 传入 % 时不应退化成"匹配所有记录"的通配查询"""
    db.upsert_listing(listing(source_id="a", brand="John Deere"))
    db.upsert_listing(listing(source_id="b", brand="Kubota"))

    assert len(db.get_all_listings(brand="%")) == 0
    assert len(db.get_all_listings(brand="John")) == 1
    assert len(db.get_all_listings()) == 2


def test_limit_is_applied_in_sql(db, listing):
    for i in range(5):
        db.upsert_listing(listing(source_id=f"th-{i}"))
    assert len(db.get_all_listings(limit=2)) == 2
    assert len(db.get_all_listings()) == 5


def test_corrupt_history_does_not_crash(db, listing):
    listing_id, _ = db.upsert_listing(listing())
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db.path)
    conn.execute("UPDATE listings SET price_history=? WHERE id=?", ("{ 不是合法 JSON", listing_id))
    conn.commit()
    conn.close()

    assert db.get_price_history(listing_id) == []
    # 损坏的历史不应让后续写入失败
    db.upsert_listing(listing(price=250000.0))
    assert db.get_alerts() != []


def test_load_history_handles_bad_input():
    assert load_history(None) == []
    assert load_history("") == []
    assert load_history("not json") == []
    assert load_history('{"a": 1}') == []  # 不是数组
    assert load_history('[{"price": 1}]') == [{"price": 1}]


def test_connections_are_closed(db, listing):
    """反复操作后不应耗尽文件描述符。原实现依赖 GC 回收连接。"""
    for i in range(200):
        db.upsert_listing(listing(source_id=f"th-{i}"))
        db.count_listings()
    assert db.count_listings() == 200
