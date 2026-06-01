import sqlite3
import json
from datetime import datetime
from typing import Optional
from .models import TractorListing, PriceAlert

class Database:
    def __init__(self, path: str = "tractor_watch.db"):
        self.path = path
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init(self):
        with self._connect() as conn:
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
                    FOREIGN KEY (listing_id) REFERENCES listings(id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_source ON listings(source, source_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_brand ON listings(brand, model)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_listing ON alerts(listing_id)")

    def upsert_listing(self, listing: TractorListing) -> Optional[int]:
        now = datetime.now().isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, price, price_history FROM listings WHERE source=? AND source_id=?",
                (listing.source, listing.source_id),
            ).fetchone()

            if existing:
                old_price = existing["price"]
                new_price = listing.price
                history = json.loads(existing["price_history"] or "[]")

                if old_price and old_price != new_price:
                    history.append({
                        "date": now,
                        "price": new_price,
                        "old_price": old_price,
                        "change": new_price - old_price,
                        "change_percent": round((new_price - old_price) / old_price * 100, 2),
                    })
                    self._create_alert(existing["id"], old_price, new_price, conn)

                conn.execute(
                    """UPDATE listings SET price=?, last_price=?, last_seen=?, hours=?, location=?,
                       price_history=?, year=? WHERE id=?""",
                    (new_price, old_price, now, listing.hours, listing.location,
                     json.dumps(history, ensure_ascii=False), listing.year, existing["id"]),
                )
                return existing["id"]
            else:
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
                return cursor.lastrowid

    def _create_alert(self, listing_id: int, old_price: float, new_price: float, conn: sqlite3.Connection):
        now = datetime.now().isoformat()
        change_percent = round((new_price - old_price) / old_price * 100, 2)
        conn.execute(
            "INSERT INTO alerts (listing_id, old_price, new_price, change_percent, notified_at) VALUES (?,?,?,?,?)",
            (listing_id, old_price, new_price, change_percent, now),
        )

    def get_all_listings(self, brand: str = "", source: str = "") -> list[dict]:
        with self._connect() as conn:
            query = "SELECT * FROM listings WHERE 1=1"
            params: list = []
            if brand:
                query += " AND brand LIKE ?"
                params.append(f"%{brand}%")
            if source:
                query += " AND source = ?"
                params.append(source)
            query += " ORDER BY last_seen DESC"
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def get_listing(self, listing_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
            return dict(row) if row else None

    def get_alerts(self, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT a.*, l.brand, l.model, l.year, l.url
                   FROM alerts a JOIN listings l ON a.listing_id = l.id
                   ORDER BY a.notified_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_price_history(self, listing_id: int) -> list[dict]:
        listing = self.get_listing(listing_id)
        if not listing:
            return []
        return json.loads(listing["price_history"] or "[]")
