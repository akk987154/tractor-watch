"""抓取 → 入库 → 派发通知的主循环。"""

import asyncio

from loguru import logger

from .config import settings
from .database import Database
from .models import PriceAlert, TractorListing, as_int
from .notifier import Notifier
from .scrapers import MachinioScraper, TractorHouseScraper

# 轮询循环出错后的重试退避
_INITIAL_BACKOFF_SECONDS = 60
_MAX_BACKOFF_SECONDS = 1800


class Tracker:
    def __init__(self, db=None, notifier=None, scrapers=None):
        # 允许注入依赖，便于测试；不传时使用默认实现
        self.db = db if db is not None else Database(settings.sqlite_path)
        self.notifier = notifier if notifier is not None else Notifier()
        self.scrapers = (
            scrapers
            if scrapers is not None
            else [TractorHouseScraper(), MachinioScraper()]
        )

    async def aclose(self) -> None:
        await self.notifier.aclose()

    async def run_once(self) -> dict:
        stats = {"new": 0, "updated": 0, "alerts": 0, "failed": 0, "scraper_errors": 0}

        for scraper in self.scrapers:
            try:
                listings = await scraper.fetch_listings()
            except Exception as exc:
                # 单个爬虫失败不应影响其它爬虫
                stats["scraper_errors"] += 1
                logger.error(f"爬虫 {scraper.source_name} 出错: {exc}")
                continue

            for listing in listings:
                try:
                    _listing_id, created = self.db.upsert_listing(listing)
                except Exception as exc:
                    logger.error(
                        f"写入挂牌失败 ({listing.source}/{listing.source_id}): {exc}"
                    )
                    continue
                # 原实现写的是 `if result_id: updated else new`，而 upsert_listing
                # 所有分支都返回真值，于是新增的挂牌全被算进"更新"，
                # 每日摘要里的"新增挂牌"永远是 0
                stats["new" if created else "updated"] += 1

        dispatched = await self._dispatch_alerts()
        stats["alerts"] = dispatched["sent"]
        stats["failed"] = dispatched["failed"]
        return stats

    async def _dispatch_alerts(self) -> dict:
        sent = 0
        failed = 0
        max_attempts = settings.max_notify_attempts

        for row in self.db.get_unnotified_alerts(max_attempts=max_attempts):
            alert_id = row["id"]

            # 先抢占再发送。原实现是"读未通知列表 → 发送 → 再标记"，
            # 两个 tracker 进程（compose 服务 + 手工 track --once）会同时选中
            # 同一批记录并重复发送。claim_alert 用 UPDATE 的原子性做抢占。
            if not self.db.claim_alert(alert_id):
                continue

            try:
                listing = TractorListing(
                    source="",
                    source_id="",
                    brand=row.get("brand") or "",
                    model=row.get("model") or "",
                    year=as_int(row.get("year")),
                    hours=as_int(row.get("hours")),
                    price=row.get("new_price"),
                    location=row.get("location") or "",
                    url=row.get("url") or "",
                )
                alert = PriceAlert(
                    listing_id=row["listing_id"],
                    old_price=row["old_price"],
                    new_price=row["new_price"],
                    change_percent=row["change_percent"],
                )

                if row["change_percent"] < 0:
                    await self.notifier.send_price_drop_alert(listing, alert)
                else:
                    await self.notifier.send_price_rise_alert(listing, alert)
                sent += 1

            except Exception as exc:
                # 发送失败必须释放抢占，否则这条告警会被永久标记为已通知。
                # 这正是原先最严重的缺陷：notifier 吞掉异常 + 无条件标记，
                # 导致失败的通知再也不会重试。
                self.db.release_alert(alert_id, f"{type(exc).__name__}: {exc}")
                failed += 1
                attempts = (row.get("notify_attempts") or 0) + 1
                logger.error(
                    f"发送提醒失败 (alert #{alert_id}，第 {attempts}/{max_attempts} 次): {exc}"
                )

        exhausted = self.db.count_exhausted_alerts(max_attempts=max_attempts)
        if exhausted:
            logger.warning(
                f"有 {exhausted} 条告警已重试 {max_attempts} 次仍未送达，已停止重试。"
                f"可通过 /api/alerts 查看 last_notify_error"
            )

        return {"sent": sent, "failed": failed}

    async def watch(self):
        logger.info(f"TractorWatch 启动，检查间隔: {settings.check_interval_hours} 小时")
        backoff = _INITIAL_BACKOFF_SECONDS

        while True:
            try:
                logger.info("开始新一轮检查...")
                stats = await self.run_once()
                logger.info(
                    f"检查完成: 新增 {stats['new']}, 更新 {stats['updated']}, "
                    f"异动 {stats['alerts']}, 发送失败 {stats['failed']}"
                )

                total = self.db.count_listings()
                await self.notifier.send_summary(stats["new"], total, stats["alerts"])
                backoff = _INITIAL_BACKOFF_SECONDS

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # 原实现没有这层保护。run_once 只护住了爬虫和告警两处，
                # count_listings() 与 send_summary() 都在保护之外，
                # 一次 sqlite3.OperationalError: database is locked
                # （双容器共用同一 WAL 文件时很容易触发）就会让协程直接结束；
                # 进程本身还活着，所以 restart: unless-stopped 不会重启它，
                # 监控就此永久停摆且没有任何提示。
                logger.exception(f"本轮检查异常，{backoff} 秒后重试: {exc}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)
                continue

            await asyncio.sleep(settings.check_interval_hours * 3600)
