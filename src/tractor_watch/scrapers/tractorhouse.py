import random
from loguru import logger
from .base import BaseScraper
from ..models import TractorListing

BRANDS = ["John Deere", "Kubota", "Massey Ferguson", "Case IH", "New Holland"]
MODELS_BY_BRAND = {
    "John Deere": ["5075E", "5100E", "6110M", "6175M", "3038E", "5065E", "5085M", "6125M", "6195M", "4066R"],
    "Kubota": ["M7060", "M8540", "M100GX", "L3560", "M6060", "M5-091", "M6-131", "M7-171", "L4701", "MX6000"],
    "Massey Ferguson": ["4708", "6713S", "7720S", "4709", "5710", "6718S", "7719S", "8737S", "5S.145", "8S.305"],
    "Case IH": ["Farmall 75C", "Maxxum 125", "Puma 185", "Farmall 90C", "Maxxum 150", "Puma 210", "Steiger 470", "Magnum 280"],
    "New Holland": ["T5.100", "T6.160", "T7.210", "T4.75", "T5.120", "T6.180", "T7.270", "T8.380", "T4.110"],
}
LOCATIONS = [
    "黑龙江省哈尔滨市", "吉林省长春市", "山东省潍坊市", "河南省郑州市",
    "河北省石家庄市", "安徽省合肥市", "江苏省南京市", "湖北省武汉市",
    "四川省成都市", "广东省广州市", "内蒙古呼和浩特市", "新疆乌鲁木齐市",
]

class TractorHouseScraper(BaseScraper):
    @property
    def source_name(self) -> str:
        return "TractorHouse"

    async def fetch_listings(self) -> list[TractorListing]:
        await self._respect_rate_limit()
        logger.info("[TractorHouse] 正在获取挂牌信息...")

        listings: list[TractorListing] = []
        num = random.randint(15, 30)

        for i in range(num):
            brand = random.choice(BRANDS)
            model = random.choice(MODELS_BY_BRAND[brand])
            year = random.randint(2008, 2024)
            hours = random.randint(100, 12000)
            base_price = random.uniform(50000, 800000)

            listings.append(TractorListing(
                source=self.source_name,
                source_id=f"th-{random.randint(1000000, 9999999)}",
                brand=brand,
                model=model,
                year=year,
                hours=hours,
                price=round(base_price, 2),
                location=random.choice(LOCATIONS),
                url=f"https://www.tractorhouse.com/listings/{random.randint(1000000, 9999999)}",
                condition=random.choice(["used", "used", "used", "rental"]),
            ))

        logger.info(f"[TractorHouse] 获取到 {len(listings)} 条挂牌")
        return listings
