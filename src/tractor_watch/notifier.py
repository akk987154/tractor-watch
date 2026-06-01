import httpx
from datetime import datetime
from loguru import logger
from .config import settings
from .models import TractorListing, PriceAlert

class Notifier:
    async def send_price_drop_alert(self, listing: TractorListing, alert: PriceAlert):
        message = self._format_message(listing, alert, "降价")
        await self._send_telegram(message)
        await self._send_discord(message)

    async def send_price_rise_alert(self, listing: TractorListing, alert: PriceAlert):
        message = self._format_message(listing, alert, "涨价")
        await self._send_telegram(message)
        await self._send_discord(message)

    async def send_summary(self, new_count: int, total: int, alerts: int):
        message = (
            f"📊 TractorWatch 每日摘要\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🆕 新增挂牌: {new_count}\n"
            f"📋 总追踪数: {total}\n"
            f"🚨 价格异动: {alerts}\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        await self._send_telegram(message)

    def _format_message(self, listing: TractorListing, alert: PriceAlert, direction: str) -> str:
        emoji = "📉" if direction == "降价" else "📈"
        return (
            f"{emoji} 价格异动 - {direction}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🚜 {listing.brand} {listing.model} ({listing.year}年)\n"
            f"📍 {listing.location}\n"
            f"⏱️ {listing.hours} 小时\n"
            f"💰 原价: ¥{alert.old_price:,.0f} → 现价: ¥{alert.new_price:,.0f}\n"
            f"📊 变化: {alert.change_percent:+.1f}%\n"
            f"🔗 {listing.url}"
        )

    async def _send_telegram(self, message: str):
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            return
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                    json={"chat_id": settings.telegram_chat_id, "text": message, "parse_mode": "HTML"},
                    timeout=10,
                )
            logger.debug("Telegram 通知已发送")
        except Exception as e:
            logger.error(f"Telegram 通知失败: {e}")

    async def _send_discord(self, message: str):
        if not settings.discord_webhook_url:
            return
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    settings.discord_webhook_url,
                    json={"content": message},
                    timeout=10,
                )
            logger.debug("Discord 通知已发送")
        except Exception as e:
            logger.error(f"Discord 通知失败: {e}")
