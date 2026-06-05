import asyncio
import random
import time
from abc import ABC, abstractmethod
from loguru import logger

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 Safari/17.5",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125.0.0.0",
]

class BaseScraper(ABC):
    def __init__(self, rate_limit: float = 2.0):
        self.rate_limit = rate_limit
        self.last_request = 0.0

    async def _respect_rate_limit(self):
        elapsed = time.monotonic() - self.last_request
        if elapsed < self.rate_limit:
            await asyncio.sleep(self.rate_limit - elapsed + random.uniform(0, 1))
        self.last_request = time.monotonic()

    def _random_ua(self) -> str:
        return random.choice(USER_AGENTS)

    @abstractmethod
    async def fetch_listings(self) -> list[dict]:
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        ...
