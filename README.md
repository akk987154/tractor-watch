# 🚜 TractorWatch — 二手拖拉机价格追踪器

**TractorWatch** is a price tracker for used tractor listings. It scrapes listings, detects price changes, and sends alerts via Telegram/Discord.

---

## 中文

### 功能

- 🔍 多平台价格抓取（模拟 TractorHouse / Machinio）
- 📉 自动检测价格异动并发送 Telegram/Discord 通知
- 📊 Plotly 价格历史曲线可视化
- 🌐 内置 FastAPI REST API
- 💻 Rich CLI 界面
- 🐳 Docker 支持

### 安装

```bash
pip install -e .
```

### 配置

复制 `.env.example` 为 `.env`：

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
DISCORD_WEBHOOK_URL=your_webhook_url
DATABASE_URL=sqlite:///tractor_watch.db
CHECK_INTERVAL_HOURS=6
```

### 使用

```bash
tractor-watch track             # 持续监控
tractor-watch track --once      # 单次检查
tractor-watch list              # 查看追踪列表
tractor-watch alerts            # 查看价格异动
tractor-watch chart 1 -o c.html # 生成价格图表
```

### API 服务

```bash
uvicorn tractor_watch.web:app --reload
```

| 端点 | 说明 |
|------|------|
| GET /api/listings | 挂牌列表 |
| GET /api/listings/{id} | 挂牌详情 |
| GET /api/listings/{id}/history | 价格历史 |
| GET /api/alerts | 价格异动 |
| GET /api/chart/{id} | 价格图表 (HTML) |

---

## English

### Features

- 🔍 Multi-platform price scraping (simulated TractorHouse / Machinio)
- 📉 Automatic price change detection with Telegram/Discord alerts
- 📊 Plotly price history charts
- 🌐 FastAPI REST API
- 💻 Rich CLI interface
- 🐳 Docker support

### Quick Start

```bash
pip install -e .
cp .env.example .env  # Edit with your credentials
tractor-watch track --once   # Single run
tractor-watch list           # View tracked listings
```

### API

```bash
uvicorn tractor_watch.web:app --reload
# Then visit http://localhost:8000/docs for Swagger UI
```

### Docker

```bash
docker-compose up -d
```

### Tech Stack

Python 3.11+ · httpx · FastAPI · Plotly · Rich · SQLite · Pydantic
