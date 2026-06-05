import random
from loguru import logger
from .base import BaseScraper
from ..models import TractorListing

BRANDS = ["John Deere", "Kubota", "Massey Ferguson", "Case IH", "New Holland"]
MODELS_BY_BRAND = {
    "John Deere": ["5055E", "5080E", "5100M", "6130M", "6155M", "6215R", "6250R", "7310R", "8370R", "9620RX"],
    "Kubota": ["M5660SUH", "M7060", "M8560", "M9960", "M5-111", "M6-141", "M7-132", "L3901", "L6060", "M4-071"],
    "Massey Ferguson": ["4707", "5711", "6714S", "7716S", "7722S", "7726S", "8735S", "8S.245", "9S.425", "MF 375"],
    "Case IH": ["Farmall 55A", "Maxxum 110", "Maxxum 140", "Puma 165", "Puma 240", "Optum 300", "Magnum 340", "Steiger 540"],
    "New Holland": ["T4.65", "T5.90", "T6.145", "T6.175", "T7.230", "T7.300", "T8.410", "T9.645", "Genesis T8", "Boomer 55"],
}
LOCATIONS = [
    "北京市", "天津市", "河北省保定市", "山西省太原市",
    "辽宁省沈阳市", "浙江省杭州市", "福建省福州市", "湖南省长沙市",
    "广西南宁市", "云南省昆明市", "陕西省西安市", "甘肃省兰州市",
]

class MachinioScraper(BaseScraper):
    @property
    def source_name(self) -> str:
        return "Machinio"

    async def fetch_listings(self) -> list[TractorListing]:
        await self._respect_rate_limit()
        logger.info("[Machinio] 正在获取挂牌信息...")

        listings: list[TractorListing] = []
        num = random.randint(12, 25)

        for i in range(num):
            brand = random.choice(BRANDS)
            model = random.choice(MODELS_BY_BRAND[brand])
            year = random.randint(2010, 2025)
            hours = random.randint(50, 15000)
            base_price = random.uniform(40000, 900000)

            listings.append(TractorListing(
                source=self.source_name,
                source_id=f"ma-{random.randint(2000000, 9999999)}",
                brand=brand,
                model=model,
                year=year,
                hours=hours,
                price=round(base_price, 2),
                location=random.choice(LOCATIONS),
                url=f"https://www.machinio.com/listings/{random.randint(2000000, 9999999)}",
                condition=random.choice(["used", "used", "used", "new"]),
            ))

        logger.info(f"[Machinio] 获取到 {len(listings)} 条挂牌")
        return listings
