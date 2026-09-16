"""通知层测试。

这里覆盖的是本项目最严重的现存缺陷：
notifier 不检查 HTTP 状态码、吞掉所有异常，而 tracker 发完就无条件标记
"已通知" —— 三者叠加的结果是通知失败时告警被永久静默丢弃。
因此"HTTP 400 必须抛出 NotificationError"是本文件最重要的一条断言。
"""

import json

import httpx
import pytest
from pydantic import SecretStr

from tractor_watch.config import settings
from tractor_watch.notifier import NotificationError, Notifier, redact


def _enable_telegram(monkeypatch, token="123456:AAbbCCddEEffGG", chat_id="42"):
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr(token))
    monkeypatch.setattr(settings, "telegram_chat_id", chat_id)
    monkeypatch.setattr(settings, "discord_webhook_url", SecretStr(""))


def _enable_discord(monkeypatch, url="https://discord.com/api/webhooks/123/abcXYZ"):
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr(""))
    monkeypatch.setattr(settings, "telegram_chat_id", "")
    monkeypatch.setattr(settings, "discord_webhook_url", SecretStr(url))


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_telegram_http_error_raises(monkeypatch, listing, alert):
    """回归：原先不调用 raise_for_status，Telegram 返回 400/401/429
    都会被当作发送成功，告警随即被标记为已通知且永不重试。"""
    _enable_telegram(monkeypatch)
    notifier = Notifier(client=_client(lambda request: httpx.Response(400, json={"ok": False})))

    with pytest.raises(NotificationError):
        await notifier.send_price_drop_alert(listing(), alert)


async def test_telegram_success_does_not_raise(monkeypatch, listing, alert):
    _enable_telegram(monkeypatch)
    notifier = Notifier(client=_client(lambda request: httpx.Response(200, json={"ok": True})))

    await notifier.send_price_drop_alert(listing(), alert)


async def test_discord_http_error_raises(monkeypatch, listing, alert):
    _enable_discord(monkeypatch)
    notifier = Notifier(client=_client(lambda request: httpx.Response(429)))

    with pytest.raises(NotificationError):
        await notifier.send_price_drop_alert(listing(), alert)


async def test_partial_channel_failure_still_raises(monkeypatch, listing, alert):
    """Telegram 成功但 Discord 失败时仍要报错，否则失败通道会被静默放弃"""
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("123456:AAbbCCddEEffGG"))
    monkeypatch.setattr(settings, "telegram_chat_id", "42")
    monkeypatch.setattr(
        settings, "discord_webhook_url", SecretStr("https://discord.com/api/webhooks/123/abcXYZ")
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if "telegram" in request.url.host:
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(500)

    notifier = Notifier(client=_client(handler))
    with pytest.raises(NotificationError) as excinfo:
        await notifier.send_price_drop_alert(listing(), alert)
    assert "Discord" in str(excinfo.value)


async def test_no_channel_configured_is_not_an_error(monkeypatch, listing, alert):
    """两个通道都没配置属于"功能未启用"，不应报错、不应占用重试次数"""
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr(""))
    monkeypatch.setattr(settings, "telegram_chat_id", "")
    monkeypatch.setattr(settings, "discord_webhook_url", SecretStr(""))

    notifier = Notifier(client=_client(lambda request: httpx.Response(500)))
    await notifier.send_price_drop_alert(listing(), alert)


async def test_telegram_payload_has_no_parse_mode(monkeypatch, listing, alert):
    """回归：原先带 parse_mode=HTML，而消息体里根本没有 HTML 标签。

    抓到含 < 的标题时 Telegram 会直接 400（整条通知丢失），
    构造 <a href=...> 还能把链接注入运维会话。
    """
    _enable_telegram(monkeypatch)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    await Notifier(client=_client(handler)).send_price_drop_alert(listing(), alert)

    assert "parse_mode" not in captured["payload"]
    assert captured["payload"]["chat_id"] == "42"
    assert "原价" in captured["payload"]["text"]


async def test_telegram_renders_missing_year_and_hours(monkeypatch, listing, alert):
    """回归：year/hours 为 NULL 时原先会打印出 "None年" """
    _enable_telegram(monkeypatch)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    await Notifier(client=_client(handler)).send_price_drop_alert(
        listing(year=None, hours=None), alert
    )

    text = captured["payload"]["text"]
    assert "None" not in text
    assert "未知年份" in text


async def test_discord_disables_mentions(monkeypatch, listing, alert):
    """回归：标题里的 @everyone 会触发 Discord 全服 @ """
    _enable_discord(monkeypatch)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(204)

    await Notifier(client=_client(handler)).send_price_drop_alert(listing(), alert)

    assert captured["payload"]["allowed_mentions"] == {"parse": []}


async def test_discord_rejects_non_discord_host(monkeypatch, listing, alert):
    """环境变量写错或被篡改时，不应把每条告警 POST 到任意地址"""
    _enable_discord(monkeypatch, url="https://evil.example.com/api/webhooks/1/x")

    with pytest.raises(NotificationError):
        await Notifier(client=_client(lambda r: httpx.Response(204))).send_price_drop_alert(
            listing(), alert
        )


async def test_summary_goes_to_all_channels(monkeypatch):
    """回归：send_summary 原先只发 Telegram，配置 Discord 的用户收不到摘要"""
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("123456:AAbbCCddEEffGG"))
    monkeypatch.setattr(settings, "telegram_chat_id", "42")
    monkeypatch.setattr(
        settings, "discord_webhook_url", SecretStr("https://discord.com/api/webhooks/123/abcXYZ")
    )

    hosts = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(200, json={"ok": True})

    await Notifier(client=_client(handler)).send_summary(1, 2, 3)

    assert "api.telegram.org" in hosts
    assert "discord.com" in hosts


async def test_aclose_only_closes_owned_client(monkeypatch):
    """外部注入的客户端不应被 notifier 关闭"""
    client = _client(lambda request: httpx.Response(200))
    notifier = Notifier(client=client)
    await notifier.aclose()
    assert client.is_closed is False
    await client.aclose()

    owned = Notifier()
    await owned._get_client()
    await owned.aclose()
    assert owned._client is None


def test_redact_hides_credentials():
    token = "123456789:AAbbCCddEEffGGhhIIjj"
    assert token not in redact(f"Client error for url https://api.telegram.org/bot{token}/sendMessage")
    assert "webhooks/<redacted>" in redact(
        "https://discord.com/api/webhooks/123456/abcDEFghiJKL"
    )
