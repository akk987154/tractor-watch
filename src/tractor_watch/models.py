from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class TractorListing:
    id: Optional[int] = None
    source: str = ""
    source_id: str = ""
    brand: str = ""
    model: str = ""
    year: int = 0
    hours: int = 0
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
    id: Optional[int] = None
    listing_id: int = 0
    old_price: float = 0.0
    new_price: float = 0.0
    change_percent: float = 0.0
    notified_at: str = ""
    brand: str = ""
    model: str = ""
    year: int = 0
    url: str = ""
