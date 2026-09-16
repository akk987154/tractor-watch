"""API 层测试。

最重要的回归：`limit` 参数原先没有任何边界。
`/api/alerts?limit=-1` 在 SQLite 里表示"不限制"，任何匿名调用者都能
强制全表扫描并完整序列化；而 `/api/listings` 甚至在 Python 侧做切片，
意味着 `?limit=1` 也会先把整张表读进内存。
"""

import pytest
from fastapi.testclient import TestClient

from tractor_watch.models import TractorListing
from tractor_watch.web import app, db


@pytest.fixture
def client():
    return TestClient(app)


def seed(count=3):
    for i in range(count):
        db.upsert_listing(
            TractorListing(
                source="TractorHouse",
                source_id=f"seed-{i}",
                brand="John Deere" if i % 2 == 0 else "Kubota",
                model=f"M{i}",
                year=2020,
                hours=1000,
                price=100000.0 + i,
                location="哈尔滨",
                url=f"https://example.com/{i}",
            )
        )


def test_alerts_limit_is_bounded(client):
    for bad in ("0", "-1", "100000"):
        response = client.get(f"/api/alerts?limit={bad}")
        assert response.status_code == 422, f"limit={bad} 本应被拒绝"

    assert client.get("/api/alerts?limit=10").status_code == 200


def test_listings_limit_is_bounded(client):
    for bad in ("0", "-1", "100000"):
        assert client.get(f"/api/listings?limit={bad}").status_code == 422

    assert client.get("/api/listings?limit=10").status_code == 200


def test_listings_brand_length_is_bounded(client):
    assert client.get("/api/listings?brand=" + "x" * 101).status_code == 422


def test_health_exposes_notification_backlog(client):
    """通知发不出去原先完全没有信号，只能靠翻日志"""
    payload = client.get("/health").json()

    assert payload["status"] == "ok"
    assert "alerts_pending" in payload
    assert "alerts_failed" in payload
    assert "notifications_configured" in payload


def test_listings_returns_seeded_rows(client):
    seed(3)
    rows = client.get("/api/listings?limit=500").json()
    assert len(rows) >= 3
    assert {"id", "brand", "model", "price"} <= set(rows[0])


def test_listing_detail_404(client):
    assert client.get("/api/listings/99999999").status_code == 404


def test_history_of_unknown_listing_is_empty(client):
    assert client.get("/api/listings/99999999/history").json() == []


def test_invalid_path_param_is_rejected(client):
    assert client.get("/api/listings/not-a-number").status_code == 422
