import asyncio
from datetime import datetime
from loguru import logger
from .database import Database
from .notifier import Notifier
from .scrapers import TractorHouseScraper, MachinioScraper
from .config import settings

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

        recent_alerts = self.db.get_alerts(limit=100)
        now = datetime.now().isoformat()
        new_alerts = [a for a in recent_alerts if a["notified_at"] > now[:10]]
        stats["alerts"] = len(new_alerts)

        return stats

    async def watch(self):
        logger.info(f"TractorWatch 启动，检查间隔: {settings.check_interval_hours} 小时")
        while True:
            logger.info("开始新一轮检查...")
            stats = await self.run_once()
            logger.info(f"检查完成: 新增 {stats['new']}, 更新 {stats['updated']}, 异动 {stats['alerts']}")

            total = len(self.db.get_all_listings())
            await self.notifier.send_summary(stats["new"], total, stats["alerts"])

            await asyncio.sleep(settings.check_interval_hours * 3600)
