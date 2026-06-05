import asyncio
from datetime import datetime
from loguru import logger
from .database import Database
from .notifier import Notifier
from .scrapers import TractorHouseScraper, MachinioScraper
from .config import settings
from .models import TractorListing, PriceAlert


class Tracker:
    def __init__(self):
        self.db = Database(settings.database_url.replace("sqlite:///", ""))
        self.notifier = Notifier()
        self.scrapers = [TractorHouseScraper(), MachinioScraper()]

    async def run_once(self) -> dict:
        stats = {"new": 0, "updated": 0, "alerts": 0}

        for scraper in self.scrapers:
            try:
                listings = await scraper.fetch_listings()
                for listing in listings:
                    result_id = self.db.upsert_listing(listing)
                    if result_id:
                        stats["updated"] += 1
                    else:
                        stats["new"] += 1
            except Exception as e:
                logger.error(f"爬虫 {scraper.source_name} 出错: {e}")

        # Dispatch notifications for newly created (unnotified) alerts
        unnotified = self.db.get_unnotified_alerts()
        for a in unnotified:
            try:
                listing = TractorListing(
                    source="",
                    source_id="",
                    brand=a.get("brand", ""),
                    model=a.get("model", ""),
                    year=a.get("year"),
                    hours=a.get("hours"),
                    price=a.get("new_price"),
                    location=a.get("location", ""),
                    url=a.get("url", ""),
                )
                alert = PriceAlert(
                    listing_id=a["listing_id"],
                    old_price=a["old_price"],
                    new_price=a["new_price"],
                    change_percent=a["change_percent"],
                )
                if a["change_percent"] < 0:
                    await self.notifier.send_price_drop_alert(listing, alert)
                else:
                    await self.notifier.send_price_rise_alert(listing, alert)
                self.db.mark_alert_notified(a["id"])
                stats["alerts"] += 1
            except Exception as e:
                logger.error(f"发送提醒失败 (alert #{a['id']}): {e}")

        return stats

    async def watch(self):
        logger.info(f"TractorWatch 启动，检查间隔: {settings.check_interval_hours} 小时")
        while True:
            logger.info("开始新一轮检查...")
            stats = await self.run_once()
            logger.info(
                f"检查完成: 新增 {stats['new']}, 更新 {stats['updated']}, "
                f"异动 {stats['alerts']}"
            )

            total = self.db.count_listings()
            await self.notifier.send_summary(stats["new"], total, stats["alerts"])

            await asyncio.sleep(settings.check_interval_hours * 3600)
