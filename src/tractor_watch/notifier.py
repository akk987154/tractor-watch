"""通知投递。

原实现有三个连在一起的问题：

1. 不检查 HTTP 状态码。`client.post(...)` 的返回值被丢弃，也没有
   `raise_for_status()`，因此 Telegram 返回 400/401/429（token 失效、
   chat_id 错误、限流）都会被当成发送成功。
2. 吞掉所有异常。每个通道都 `except Exception` 后只打一行日志就正常返回，
   于是 tracker 那边 `except` 分支成为死代码。
3. tracker 发完就无条件标记"已通知"。综合 1 与 2 的结果是：
   通知失败 → 告警被标记为已发送 → 永远不会重试 → 静默丢失。

现在的约定：投递失败必须抛出 NotificationError，由调用方决定是否重试。

另外两点安全处理：
- Telegram 去掉了 parse_mode="HTML"。原消息体里本来就没有任何 HTML 标签，
  开启 HTML 解析只有坏处：抓取到的标题/型号里的 `<` 会让 Telegram 直接
  返回 400（整条通知丢失），构造 `<a href=...>` 还能往运维的会话里注入链接。
- Discord 增加 allowed_mentions.parse=[]，避免标题里的 @everyone 触发全服 @。
"""

import re

import httpx
from loguru import logger

from .config import settings

# Telegram 的 bot token 直接嵌在 URL 里，Discord 的 secret 也在 URL 里。
# 异常对象经常携带完整 URL，直接记录会把凭据写进日志。
_BOT_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")
_DISCORD_WEBHOOK_RE = re.compile(r"webhooks/\d+/[A-Za-z0-9_-]+")

_ALLOWED_DISCORD_HOSTS = (
    "https://discord.com/api/webhooks/",
    "https://discordapp.com/api/webhooks/",
    "https://ptb.discord.com/api/webhooks/",
    "https://canary.discord.com/api/webhooks/",
)


class NotificationError(RuntimeError):
    """通知投递失败，调用方应据此重试而不是标记为已发送"""


def redact(text: str) -> str:
    """抹掉日志中的凭据"""
    text = _BOT_TOKEN_RE.sub("bot<redacted>", text)
    return _DISCORD_WEBHOOK_RE.sub("webhooks/<redacted>", text)


class Notifier:
    def __init__(self, client: httpx.AsyncClient | None = None):
        # 复用一个客户端：原实现每发一条消息就新建并销毁一个 AsyncClient，
        # 连接池无法复用，也没有重试
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None

    # ---------- 对外接口 ----------

    async def send_price_drop_alert(self, listing, alert) -> None:
        await self.deliver(self._format_message(listing, alert, "降价"))

    async def send_price_rise_alert(self, listing, alert) -> None:
        await self.deliver(self._format_message(listing, alert, "涨价"))

    async def send_summary(self, new_count: int, total: int, alerts: int) -> None:
        from datetime import datetime

        message = (
            f"📊 TractorWatch 每日摘要\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🆕 新增挂牌: {new_count}\n"
            f"📋 总追踪数: {total}\n"
            f"🚨 价格异动: {alerts}\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        # 原实现只发 Telegram，配置了 Discord 的用户永远收不到摘要
        await self.deliver(message)

    # ---------- 内部实现 ----------

    def _format_message(self, listing, alert, direction: str) -> str:
        emoji = "📉" if direction == "降价" else "📈"
        year = listing.year if listing.year is not None else "未知年份"
        hours = listing.hours if listing.hours is not None else "未知"
        return (
            f"{emoji} 价格异动 - {direction}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🚜 {listing.brand} {listing.model} ({year}年)\n"
            f"📍 {listing.location}\n"
            f"⏱️ {hours} 小时\n"
            f"💰 原价: ¥{alert.old_price:,.0f} → 现价: ¥{alert.new_price:,.0f}\n"
            f"📊 变化: {alert.change_percent:+.1f}%\n"
            f"🔗 {listing.url}"
        )

    async def deliver(self, message: str) -> None:
        """投递到所有已配置的通道；任一通道失败即抛出 NotificationError"""
        if not settings.telegram_enabled and not settings.discord_enabled:
            # 两个通道都没配置属于"功能未启用"，不是失败。
            # 保持与原先一致的语义：不报错、不重试，只提示一次。
            logger.warning(
                "未配置任何通知通道（TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 或 "
                "DISCORD_WEBHOOK_URL），消息未发送"
            )
            return

        failures: list[str] = []

        if settings.telegram_enabled:
            try:
                await self._send_telegram(message)
            except Exception as exc:
                failures.append(f"Telegram({type(exc).__name__})")
                logger.error(f"Telegram 通知失败: {redact(str(exc))}")

        if settings.discord_enabled:
            try:
                await self._send_discord(message)
            except Exception as exc:
                failures.append(f"Discord({type(exc).__name__})")
                logger.error(f"Discord 通知失败: {redact(str(exc))}")

        if failures:
            raise NotificationError("; ".join(failures))

    async def _send_telegram(self, message: str) -> None:
        client = await self._get_client()
        token = settings.telegram_bot_token.get_secret_value()
        response = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": settings.telegram_chat_id,
                "text": message,
                # 刻意不使用 parse_mode：消息体里没有 HTML 标签，
                # 开启解析只会让抓取内容中的 < 触发 400 或注入链接
                "disable_web_page_preview": True,
            },
        )
        # 关键：不检查状态码就无法区分"发出去了"和"被拒绝了"
        response.raise_for_status()
        logger.debug("Telegram 通知已发送")

    async def _send_discord(self, message: str) -> None:
        url = settings.discord_webhook_url.get_secret_value()
        if not url.startswith(_ALLOWED_DISCORD_HOSTS):
            # 环境变量写错或被篡改时，不至于把每条告警都 POST 到任意地址
            raise NotificationError("DISCORD_WEBHOOK_URL 不是合法的 Discord webhook 地址")

        client = await self._get_client()
        response = await client.post(
            url,
            json={
                "content": message,
                # 不加这个限制，标题里的 @everyone / @here 会造成全服打扰
                "allowed_mentions": {"parse": []},
            },
        )
        response.raise_for_status()
        logger.debug("Discord 通知已发送")
