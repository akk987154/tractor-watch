"""主循环测试。

覆盖两个关键回归：
1. 新增/更新计数：原实现用 upsert_listing 的返回值做真值判断，
   而该返回值在所有分支上都是真值，导致"新增挂牌"永远是 0。
2. 通知失败必须释放告警：原先失败也会被标记为已通知，告警永久丢失。
以及一条容错不变式：单轮异常不得终止整个 watch 循环。
"""

import asyncio
import sqlite3

import pytest

from tractor_watch import tracker as tracker_module
from tractor_watch.config import settings
from tractor_watch.tracker import Tracker


class StubScraper:
    def __init__(self, listings=None, error=None, name="Stub"):
        self._listings = listings or []
        self._error = error
        self._name = name

    @property
    def source_name(self):
        return self._name

    async def fetch_listings(self):
        if self._error is not None:
            raise self._error
        return self._listings


class StubNotifier:
    def __init__(self, error=None):
        self.sent = []
        self.error = error
        self.summaries = []

    async def _maybe_fail(self):
        if self.error is not None:
            raise self.error

    async def send_price_drop_alert(self, listing, alert):
        await self._maybe_fail()
        self.sent.append(("drop", alert.new_price))

    async def send_price_rise_alert(self, listing, alert):
        await self._maybe_fail()
        self.sent.append(("rise", alert.new_price))

    async def send_summary(self, new_count, total, alerts):
        await self._maybe_fail()
        self.summaries.append((new_count, total, alerts))

    async def aclose(self):
        pass


def make_tracker(db, listings, notifier=None, error=None):
    return Tracker(
        db=db,
        notifier=notifier or StubNotifier(),
        scrapers=[StubScraper(listings=listings, error=error)],
    )


async def test_run_once_counts_new_then_updated(db, listing):
    tracker = make_tracker(db, [listing(source_id="a"), listing(source_id="b")])

    first = await tracker.run_once()
    assert first["new"] == 2
    assert first["updated"] == 0

    second = await tracker.run_once()
    assert second["new"] == 0
    assert second["updated"] == 2


async def test_scraper_error_is_isolated(db, listing):
    tracker = Tracker(
        db=db,
        notifier=StubNotifier(),
        scrapers=[
            StubScraper(error=RuntimeError("反爬拦截"), name="Broken"),
            StubScraper(listings=[listing(source_id="ok")], name="Healthy"),
        ],
    )

    stats = await tracker.run_once()
    assert stats["scraper_errors"] == 1
    assert stats["new"] == 1


async def test_notification_failure_keeps_alert_retryable(db, listing):
    """回归：原先通知失败也会标记已通知，告警被永久静默丢弃"""
    db.upsert_listing(listing(price=300000.0))
    db.upsert_listing(listing(price=270000.0))

    failing = StubNotifier(error=RuntimeError("telegram down"))
    tracker = make_tracker(db, [], notifier=failing)

    stats = await tracker.run_once()
    assert stats["failed"] == 1
    assert stats["alerts"] == 0

    # 必须仍然待发送，并累计了失败次数
    pending = db.get_unnotified_alerts()
    assert len(pending) == 1
    assert pending[0]["notify_attempts"] == 1
    assert "telegram down" in pending[0]["last_notify_error"]

    # 通道恢复后应当能成功发出
    recovering = StubNotifier()
    stats2 = await make_tracker(db, [], notifier=recovering).run_once()
    assert stats2["alerts"] == 1
    assert recovering.sent == [("drop", 270000.0)]
    assert db.get_unnotified_alerts() == []


async def test_price_rise_uses_rise_alert(db, listing):
    db.upsert_listing(listing(price=300000.0))
    db.upsert_listing(listing(price=330000.0))

    notifier = StubNotifier()
    stats = await make_tracker(db, [], notifier=notifier).run_once()

    assert stats["alerts"] == 1
    assert notifier.sent == [("rise", 330000.0)]


async def test_alert_is_not_sent_twice(db, listing):
    db.upsert_listing(listing(price=300000.0))
    db.upsert_listing(listing(price=270000.0))

    notifier = StubNotifier()
    tracker = make_tracker(db, [], notifier=notifier)

    await tracker.run_once()
    await tracker.run_once()
    await tracker.run_once()

    assert len(notifier.sent) == 1


async def test_alert_with_exhausted_attempts_is_skipped(db, listing, monkeypatch):
    monkeypatch.setattr(settings, "max_notify_attempts", 2)
    db.upsert_listing(listing(price=300000.0))
    db.upsert_listing(listing(price=270000.0))

    failing = StubNotifier(error=RuntimeError("down"))
    tracker = make_tracker(db, [], notifier=failing)

    await tracker.run_once()
    await tracker.run_once()
    third = await tracker.run_once()

    assert third["failed"] == 0
    assert db.count_exhausted_alerts(max_attempts=2) == 1


async def test_watch_survives_iteration_errors(db, monkeypatch):
    """回归：watch 循环体没有任何保护。

    原先 run_once 只护住了爬虫与告警两处，count_listings() 与 send_summary()
    都在保护之外。一次 sqlite3.OperationalError: database is locked
    就会让协程直接结束，而进程仍然存活，容器不会重启它。
    """
    monkeypatch.setattr(tracker_module, "_INITIAL_BACKOFF_SECONDS", 0.01)
    monkeypatch.setattr(tracker_module, "_MAX_BACKOFF_SECONDS", 0.02)

    calls = {"run": 0}

    async def failing_run_once():
        calls["run"] += 1
        raise sqlite3.OperationalError("database is locked")

    tracker = Tracker(db=db, notifier=StubNotifier(), scrapers=[])
    monkeypatch.setattr(tracker, "run_once", failing_run_once)

    task = asyncio.create_task(tracker.watch())
    try:
        for _ in range(300):
            if calls["run"] >= 3:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert calls["run"] >= 3, "第一次异常之后循环就终止了"


async def test_watch_sends_summary_after_successful_run(db, listing, monkeypatch):
    monkeypatch.setattr(tracker_module, "_INITIAL_BACKOFF_SECONDS", 0.01)

    notifier = StubNotifier()
    tracker = Tracker(
        db=db,
        notifier=notifier,
        scrapers=[StubScraper(listings=[listing(source_id="a")])],
    )

    task = asyncio.create_task(tracker.watch())
    try:
        for _ in range(300):
            if notifier.summaries:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert notifier.summaries[0][0] == 1  # 新增 1 条
    assert notifier.summaries[0][1] == 1  # 总数 1
