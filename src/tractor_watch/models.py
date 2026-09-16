from dataclasses import dataclass


def as_int(value) -> int | None:
    """把数据库读回的值安全地转成 int。

    数据库里 year / hours 都是可空的，读出来可能是 None 或字符串。
    原实现直接把 None 塞进声明为 int 的字段，通知里就会打印出 "None年"。
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class TractorListing:
    id: int | None = None
    source: str = ""
    source_id: str = ""
    brand: str = ""
    model: str = ""
    year: int | None = None
    hours: int | None = None
    price: float = 0.0
    location: str = ""
    url: str = ""
    condition: str = "used"
    first_seen: str = ""
    last_seen: str = ""
    last_price: float = 0.0
    price_history: str = "[]"


@dataclass
class PriceAlert:
    id: int | None = None
    listing_id: int = 0
    old_price: float = 0.0
    new_price: float = 0.0
    change_percent: float = 0.0
    notified_at: str = ""
    notify_attempts: int = 0
    last_notify_error: str = ""
