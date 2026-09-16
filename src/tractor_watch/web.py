"""FastAPI 只读接口。

两点改动需要说明：

1. 处理函数从 `async def` 改为 `def`。
   sqlite3 是同步库，放在 `async def` 里会阻塞事件循环——所有并发请求
   都要排队等当前查询完成。声明为普通 `def` 后，FastAPI 会把它们丢到
   线程池执行，不再阻塞事件循环。

2. 所有 `limit` 参数都加了上下界。
   原实现是 `limit: int = Query(100)`，没有任何约束。`/api/alerts?limit=-1`
   在 SQLite 里表示"不限制"，因此任何匿名调用者都能强制全表扫描并完整序列化。
   另外 `/api/listings` 原先是在 Python 侧做 `listings[:limit]`，
   意味着 `?limit=1` 也会先把整张表读进内存；现在 LIMIT 下沉到 SQL。
"""

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

from .config import settings
from .database import Database

app = FastAPI(
    title="TractorWatch API",
    version="0.1.0",
    docs_url="/docs" if settings.enable_docs else None,
    redoc_url="/redoc" if settings.enable_docs else None,
    openapi_url="/openapi.json" if settings.enable_docs else None,
)

db = Database(settings.sqlite_path)


@app.get("/api/listings")
def get_listings(
    brand: str = Query("", max_length=100),
    source: str = Query("", max_length=100),
    limit: int = Query(100, ge=1, le=500),
):
    return db.get_all_listings(brand=brand, source=source, limit=limit)


@app.get("/api/listings/{listing_id}")
def get_listing(listing_id: int):
    listing = db.get_listing(listing_id)
    if not listing:
        return JSONResponse({"error": "not found"}, 404)
    return listing


@app.get("/api/listings/{listing_id}/history")
def get_history(listing_id: int):
    return db.get_price_history(listing_id)


@app.get("/api/alerts")
def get_alerts(limit: int = Query(50, ge=1, le=500)):
    return db.get_alerts(limit=limit)


@app.get("/api/chart/{listing_id}", response_class=HTMLResponse)
def get_chart(listing_id: int):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    listing = db.get_listing(listing_id)
    if not listing:
        return HTMLResponse("<h1>未找到</h1>", 404)

    history = db.get_price_history(listing_id)
    if not history:
        return HTMLResponse("<h1>暂无价格历史</h1>")

    dates = [h["date"][:10] for h in history]
    prices = [h["price"] for h in history]
    changes = [h["change_percent"] for h in history]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
    fig.add_trace(go.Scatter(x=dates, y=prices, mode="lines+markers", name="价格",
                             line=dict(color="green", width=2)), row=1, col=1)
    colors = ["red" if c < 0 else "green" for c in changes]
    fig.add_trace(go.Bar(x=dates, y=changes, name="变化%", marker_color=colors), row=2, col=1)
    fig.update_layout(height=600, template="plotly_white")
    fig.update_yaxes(title_text="价格 (¥)", row=1, col=1)
    fig.update_yaxes(title_text="变化 (%)", row=2, col=1)

    # include_plotlyjs="cdn" 会从第三方 CDN 引入脚本。
    # 若要离线可用或收紧 CSP，改为 True 把 plotly.js 内联进页面。
    return HTMLResponse(fig.to_html(include_plotlyjs="cdn"))


@app.get("/health")
def health():
    """健康检查。

    除了进程存活，还暴露通知积压情况——原先"通知发不出去"是完全没有信号的，
    只能靠人去翻日志。积压数量持续增长即说明通知通道出了问题。
    """
    max_attempts = settings.max_notify_attempts
    return {
        "status": "ok",
        "listings": db.count_listings(),
        "alerts_pending": db.count_pending_alerts(max_attempts=max_attempts),
        "alerts_failed": db.count_exhausted_alerts(max_attempts=max_attempts),
        "notifications_configured": settings.telegram_enabled or settings.discord_enabled,
    }
