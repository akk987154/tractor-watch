"""SQLite 持久化层。

两个关键约定：

1. 连接必须在退出时关闭。`with sqlite3.connect(...)` 是**事务**上下文管理器，
   它只负责提交/回滚，并不会关闭连接。原实现每个方法都用 `with self._connect()`
   并依赖 GC 回收，长驻进程里会持续泄漏文件描述符与 WAL 句柄。
   这里统一用 _connect() 上下文管理器，finally 中显式 close()。

2. 通知状态机。原实现是"发完就无条件标记已通知"，配合 notifier 里吞掉所有异常，
   导致通知失败时告警被永久标记为已发送、再也不会重试。
   现在改为：claim（原子抢占）→ 发送成功则保持 notified_at；
   发送失败则 release（清空 notified_at、累计失败次数、记录原因）。
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from .models import TractorListing

# 超过这个失败次数的告警不再重试，改为在 /api/alerts 中可见地保留失败原因
DEFAULT_MAX_ATTEMPTS = 5


def load_history(raw) -> list[dict]:
    """安全解析 price_history。损坏的 JSON 不应让整条链路崩掉。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return data if isinstance(data, list) else []


class Database:
    def __init__(self, path: str = "tractor_watch.db"):
        self.path = path
        with self._connect() as conn:
            self._init(conn)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        # SQLite 默认不启用外键约束，schema 里声明的 FOREIGN KEY 形同虚设
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init(self, conn: sqlite3.Connection):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS listings (
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
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id INTEGER NOT NULL,
                old_price REAL,
                new_price REAL,
                change_percent REAL,
                notified_at TEXT,
                notify_attempts INTEGER NOT NULL DEFAULT 0,
                last_notify_error TEXT,
                FOREIGN KEY (listing_id) REFERENCES listings(id)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_listings_source ON listings(source, source_id)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_brand ON listings(brand, model)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_listing ON alerts(listing_id)")
        self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection):
        """为既有数据库补齐新增列（CREATE TABLE IF NOT EXISTS 不会修改已存在的表）"""
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(alerts)")}
        if "notify_attempts" not in columns:
            conn.execute(
                "ALTER TABLE alerts ADD COLUMN notify_attempts INTEGER NOT NULL DEFAULT 0"
            )
        if "last_notify_error" not in columns:
            conn.execute("ALTER TABLE alerts ADD COLUMN last_notify_error TEXT")

    # ---------- listings ----------

    def upsert_listing(self, listing: TractorListing) -> tuple[int, bool]:
        """写入或更新一条挂牌。

        返回 (listing_id, created)。原实现返回 Optional[int] 但所有分支都返回真值，
        调用方用 `if result_id:` 区分新增/更新，导致 else 分支成为死代码、
        stats["new"] 恒为 0。这里显式返回布尔值，让语义不再依赖真值判断。
        """
        now = datetime.now().isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, price, price_history FROM listings WHERE source=? AND source_id=?",
                (listing.source, listing.source_id),
            ).fetchone()

            if existing:
                old_price = existing["price"]
                new_price = listing.price
                history = load_history(existing["price_history"])

                if old_price and new_price is not None and old_price != new_price:
                    change_percent = round((new_price - old_price) / old_price * 100, 2)
                    history.append({
                        "date": now,
                        "price": new_price,
                        "old_price": old_price,
                        "change": new_price - old_price,
                        "change_percent": change_percent,
                    })
                    self._create_alert(existing["id"], old_price, new_price, change_percent, conn)

                conn.execute(
                    """UPDATE listings SET price=?, last_price=?, last_seen=?, hours=?, location=?,
                       price_history=?, year=?, brand=?, model=?, url=? WHERE id=?""",
                    (new_price, old_price, now, listing.hours, listing.location,
                     json.dumps(history, ensure_ascii=False), listing.year,
                     listing.brand, listing.model, listing.url, existing["id"]),
                )
                return existing["id"], False

            listing.first_seen = now
            listing.last_seen = now
            listing.last_price = 0
            listing.price_history = json.dumps([], ensure_ascii=False)
            cursor = conn.execute(
                """INSERT INTO listings (source, source_id, brand, model, year, hours, price,
                   location, url, condition, first_seen, last_seen, last_price, price_history)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (listing.source, listing.source_id, listing.brand, listing.model,
                 listing.year, listing.hours, listing.price, listing.location,
                 listing.url, listing.condition, listing.first_seen, listing.last_seen,
                 listing.last_price, listing.price_history),
            )
            return cursor.lastrowid, True

    def _create_alert(
        self,
        listing_id: int,
        old_price: float,
        new_price: float,
        change_percent: float,
        conn: sqlite3.Connection,
    ):
        conn.execute(
            "INSERT INTO alerts (listing_id, old_price, new_price, change_percent) "
            "VALUES (?,?,?,?)",
            (listing_id, old_price, new_price, change_percent),
        )

    def get_all_listings(
        self, brand: str = "", source: str = "", limit: int | None = None
    ) -> list[dict]:
        """按条件查询挂牌。limit 在 SQL 层生效，避免把整表读进内存后再切片。"""
        with self._connect() as conn:
            query = "SELECT * FROM listings WHERE 1=1"
            params: list = []
            if brand:
                # 转义 LIKE 元字符，否则调用方传入的 % / _ 会被当成通配符
                escaped = brand.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                query += " AND brand LIKE ? ESCAPE '\\'"
                params.append(f"%{escaped}%")
            if source:
                query += " AND source = ?"
                params.append(source)
            query += " ORDER BY last_seen DESC"
            if limit is not None:
                query += " LIMIT ?"
                params.append(limit)
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def get_listing(self, listing_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
            return dict(row) if row else None

    def count_listings(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM listings").fetchone()
            return row[0] if row else 0

    def get_price_history(self, listing_id: int) -> list[dict]:
        listing = self.get_listing(listing_id)
        if not listing:
            return []
        return load_history(listing["price_history"])

    # ---------- alerts ----------

    def get_alerts(self, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT a.*, l.brand, l.model, l.year, l.url
                   FROM alerts a JOIN listings l ON a.listing_id = l.id
                   ORDER BY a.id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_unnotified_alerts(self, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> list[dict]:
        """尚未成功通知、且失败次数未超上限的告警"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT a.*, l.brand, l.model, l.year, l.url, l.location, l.hours
                   FROM alerts a JOIN listings l ON a.listing_id = l.id
                   WHERE a.notified_at IS NULL AND a.notify_attempts < ?
                   ORDER BY a.id ASC""",
                (max_attempts,),
            ).fetchall()
            return [dict(row) for row in rows]

    def claim_alert(self, alert_id: int) -> bool:
        """原子抢占一条告警的发送权。

        返回 True 表示本次调用获得了发送权；False 表示已被其它进程抢占或已通知。
        原实现是"先读未通知列表、发送、再标记"，两个 tracker 进程会同时选中同一批
        记录并重复发送。这里把标记提前到发送之前，用 UPDATE 的原子性做抢占。
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE alerts SET notified_at = ? WHERE id = ? AND notified_at IS NULL",
                (datetime.now().isoformat(), alert_id),
            )
            return cursor.rowcount == 1

    def release_alert(self, alert_id: int, error: str) -> None:
        """发送失败时释放抢占并累计失败次数与原因，使其可在下一轮重试"""
        with self._connect() as conn:
            conn.execute(
                """UPDATE alerts
                   SET notified_at = NULL,
                       notify_attempts = notify_attempts + 1,
                       last_notify_error = ?
                   WHERE id = ?""",
                (error[:500], alert_id),
            )

    def count_pending_alerts(self, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE notified_at IS NULL AND notify_attempts < ?",
                (max_attempts,),
            ).fetchone()
            return row[0] if row else 0

    def count_exhausted_alerts(self, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> int:
        """重试次数已耗尽、放弃发送的告警数量（用于暴露问题而不是静默丢弃）"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE notified_at IS NULL AND notify_attempts >= ?",
                (max_attempts,),
            ).fetchone()
            return row[0] if row else 0
