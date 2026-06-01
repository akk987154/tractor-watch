import json
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from .database import Database
from .config import settings

app = FastAPI(title="TractorWatch API", version="0.1.0")
db = Database(settings.database_url.replace("sqlite:///", ""))

@app.get("/api/listings")
async def get_listings(brand: str = Query(""), source: str = Query(""), limit: int = Query(100)):
    listings = db.get_all_listings(brand=brand, source=source)
    return listings[:limit]

@app.get("/api/listings/{listing_id}")
async def get_listing(listing_id: int):
    listing = db.get_listing(listing_id)
    if not listing:
        return JSONResponse({"error": "not found"}, 404)
    return listing

@app.get("/api/listings/{listing_id}/history")
async def get_history(listing_id: int):
    history = db.get_price_history(listing_id)
    return history

@app.get("/api/alerts")
async def get_alerts(limit: int = Query(50)):
    return db.get_alerts(limit=limit)

@app.get("/api/chart/{listing_id}", response_class=HTMLResponse)
async def get_chart(listing_id: int):
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

    return HTMLResponse(fig.to_html(include_plotlyjs="cdn"))

@app.get("/health")
async def health():
    return {"status": "ok"}
