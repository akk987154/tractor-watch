# 🚜 TractorWatch — 二手拖拉机价格追踪器

<!--
  这个项目的骨架搭得最早，但填肉最慢——因为抓取逻辑反复纠结。
  一开始想直接用 httpx + selectolax 做真抓取，结果发现 TractorHouse 反爬太狠
  (Cloudflare + JS challenge)，Machinio 倒还好但数据结构三天两头变。
  所以目前线上跑的是模拟数据生成器，把真抓取的适配层留好了但没启用。
  价格异动的算法倒是改了好几版——从简单的"降价了通知我"到现在的百分比阈值 +
  趋势判断（是临时降还是持续降），参考了 FarmCalc 的折旧曲线做基准线。

  另一个纠结的点是数据库——刚开始用的 JSON 文件，后来换成 SQLite，现在在考虑
  要不要切到 PostgreSQL（主要是为了多实例部署时共享数据）。
-->

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776ab?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![Plotly](https://img.shields.io/badge/Plotly-charts-3f4f75?logo=plotly)](https://plotly.com)
[![Docker](https://img.shields.io/badge/Docker-compose-2496ed?logo=docker)](https://www.docker.com)

**TractorWatch** 是 [TractorTools](https://github.com/seb/tractor-tools) 生态的市场数据层。它负责盯二手拖拉机挂牌、检测价格变化、发提醒——是整个工具集的"眼睛"。如果说 [FarmCalc](../farm-calc) 告诉你"这台拖拉机理论上值多少"，那 TractorWatch 告诉你"市场上实际卖多少"。两者的折旧曲线可以互相校准。

---

## 🗺️ 项目生态

| 项目 | 定位 | 与本项目的关系 |
|------|------|---------------|
| [FarmCalc](../farm-calc) | 成本/ROI 计算 | 理论折旧 vs 实际二手价格——两条曲线的差距帮用户判断"买新还是买旧" |
| [TractorCompare](../tractor-compare) | 规格对比 | 挂牌 MSRP 参考价交叉校验；二手价格可作为对比页的"市场行情"列 |
| [TractorLog](../tractor-log) | 维护日志 PWA | 完整的维护记录 = 卖二手时的加分项，价格可上浮 |
| [TractorVIN](../tractor-vin) | 序列号解码 | 解码后精确搜索同型号的二手挂牌 |

---

## 中文

### 功能

- 🔍 **多平台价格抓取** — 支持 TractorHouse / Machinio 数据源（当前为模拟数据生成器，抓取适配层已预留）
- 📉 **价格异动检测** — 不是简单的"降价了"——区分临时降价和趋势性降价，支持百分比阈值 + 连续监测
- 📊 **Plotly 价格历史图** — 交互式 HTML 图表，价格曲线 + 涨跌幅标注
- 🔔 **多渠道提醒** — Telegram Bot + Discord Webhook 双通道
- 🌐 **FastAPI REST API** — 5 个端点，Swagger 文档自动生成
- 💻 **Rich CLI** — 彩色终端界面，表格/状态一目了然
- 🐳 **Docker Compose** — tracker + API 双服务，共享 SQLite 数据卷
- 🗄️ **SQLite + WAL** — 写入不卡读取，适合单机部署

### 安装

```bash
pip install -e .
```

### 配置

复制 `.env.example` 为 `.env`——所有字段都是可选的（不配通知渠道就只记录不提醒）：

```env
# 通知渠道（可选——不配也能正常追踪，只是不发提醒）
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
DISCORD_WEBHOOK_URL=your_webhook_url

# 数据库
DATABASE_URL=sqlite:///tractor_watch.db

# 追踪设置
CHECK_INTERVAL_HOURS=6
USER_AGENT=TractorWatch/0.4
```

### 使用

```bash
# 持续监控（按 CHECK_INTERVAL_HOURS 循环）
tractor-watch track

# 单次抓取 + 检查
tractor-watch track --once

# 查看追踪列表（Rich 表格，价格变化彩色标注）
tractor-watch list

# 查看价格异动
tractor-watch alerts

# 生成价格历史图表（Plotly HTML）
tractor-watch chart 1 -o price_history.html
```

### API 服务

```bash
uvicorn tractor_watch.web:app --reload
# 访问 http://localhost:8000/docs 查看 Swagger UI
```

| 端点 | 说明 | 与生态的集成点 |
|------|------|-------------|
| `GET /api/listings` | 挂牌列表，支持 brand/source 过滤 | TractorCompare 可请求同型号的市场行情 |
| `GET /api/listings/{id}` | 单条挂牌详情 | — |
| `GET /api/listings/{id}/history` | 价格变动历史 | FarmCalc 可用于校准折旧曲线 |
| `GET /api/alerts` | 价格异动列表 | — |
| `GET /api/chart/{id}` | Plotly 价格图表 (HTML) | — |

### 价格异动算法

这个算法迭代了好几次，现在是这样：

1. **抓取**: 爬取或生成挂牌数据（价格 + 小时数 + 位置 + 挂牌时间）
2. **Upsert**: 按 `source + source_id` 去重，新增 → 创建记录，已存在 → 比较价格
3. **价格变化判断**:
   - 降价 ≥ 5% → 通知（"值得关注"）
   - 降价 ≥ 10% → 紧急通知（"可能已售或急售"）
   - 提价 → 记录但不通知（可能是卖家改了配置或更新了信息）
4. **趋势判断**: 看历史价格序列，如果连续 2 次以上降价 → 标记为"持续降价趋势"
5. **基准线比较**（计划中，还没上线）: 对比 [FarmCalc](../farm-calc) 的理论折旧值——如果市场价低于理论账面价值 → 可能是好 deal

这个"查上次快照 → 算差值 → 跟阈值比"的模式，跟 [TractorLog](../tractor-log) 那边的维护提醒算法是同一个思路——两边不约而同用了类似的逻辑。

### 数据模型

```
TractorListing {
  id, source, source_id, url,
  brand, model, year,
  price, previous_price,
  hours, location,
  listed_date, last_seen,
  price_history: [{date, price}]  // JSON blob
}

PriceAlert {
  id, listing_id,
  old_price, new_price,
  change_pct,
  detected_at,
  notified: bool
}
```

### 关于抓取器

目前两个抓取器（`TractorHouseScraper`、`MachinioScraper`）生成的是**模拟数据**——随机的品牌、型号、年份、小时数、价格和中文城市。之所以这样做而不是直接抓取真实网站：

- TractorHouse 有 Cloudflare 反爬，需要 JS 渲染（得加 Playwright/Selenium，复杂度翻倍）
- Machinio 的 HTML 结构变动频繁，CSS selector 维护成本太高
- 模拟数据的结构和真实数据完全一致——等抓取适配层稳定了，把 `fetch_page()` 方法从 `random.randint` 换成真正的 HTTP + parse 就行，其他代码不用改

`selectolax` 已经在依赖里了（`pyproject.toml`），HTML 解析逻辑的导入路径也留好了——只是暂时没启用。

### 技术栈

Python 3.11+ · httpx · FastAPI · Plotly · Rich · SQLite (WAL) · Pydantic v2 · Pydantic-Settings · Loguru · Hatchling

选 Python 的原因：数据抓取 + 分析 + 可视化的生态最成熟。跟 [TractorVIN](../tractor-vin)（Go）形成互补——那个追求性能和部署简单，这个追求开发速度和数据分析灵活。

---

## English

### Features

- 🔍 **Multi-platform price scraping** — TractorHouse / Machinio data sources (simulated data for now, real scraping adapter ready)
- 📉 **Price change detection** — Percentage threshold + trend analysis (temporary dip vs sustained decline)
- 📊 **Plotly price history charts** — Interactive HTML with price curve + change annotations
- 🔔 **Multi-channel alerts** — Telegram Bot + Discord Webhook
- 🌐 **FastAPI REST API** — 5 endpoints with auto-generated Swagger docs
- 💻 **Rich CLI** — Color-coded terminal tables
- 🐳 **Docker Compose** — Tracker + API dual-service, shared SQLite volume
- 🗄️ **SQLite + WAL** — Non-blocking reads during writes

### Quick Start

```bash
pip install -e .
cp .env.example .env  # Edit with your credentials (optional)
tractor-watch track --once   # Single run
tractor-watch list           # View tracked listings
```

### API

```bash
uvicorn tractor_watch.web:app --reload
# Swagger UI at http://localhost:8000/docs
```

| Endpoint | Description |
|----------|-------------|
| `GET /api/listings` | Listings with brand/source filters |
| `GET /api/listings/{id}` | Single listing detail |
| `GET /api/listings/{id}/history` | Price history |
| `GET /api/alerts` | Price change alerts |
| `GET /api/chart/{id}` | Plotly chart (HTML) |

### Docker

```bash
docker-compose up -d
# tracker service + api service, shared SQLite volume
```

### Tech Stack

Python 3.11+ · httpx · FastAPI · Plotly · Rich · SQLite · Pydantic v2

---

## 📋 迭代记录

<details>
<summary>点击展开</summary>

### v0.4 — 双渠道通知 + Docker Compose (当前)
- Telegram + Discord 双通知渠道
- Docker Compose 双服务部署（tracker 循环 + API 独立）
- 价格异动算法增加趋势判断（连续降价 vs 单次降价）
- Pydantic v2 迁移（从 v1 升上来改了不少 validator 语法）

### v0.3 — Plotly 可视化 + 价格异动
- Plotly 交互式价格图表生成
- 价格异动检测（百分比阈值）
- CLI `chart` 和 `alerts` 子命令
- SQLite WAL 模式（解决"tracker 在写时 API 读不了"的问题）

### v0.2 — API 服务 + 数据库
- FastAPI 5 端点
- SQLite 替换 JSON 文件存储
- 从单一 tracker.py 拆分为 config / database / models / notifier / tracker / web
- Rich CLI 表格

### v0.1 — 初始骨架
- 单一 TractorHouse 抓取器（mock）
- JSON 文件存储
- 基础 CLI（仅 `track --once`）
- httpx + selectolax 依赖引入

</details>

## 🗓️ 路线图

- [ ] **真抓取上线** — 至少一个平台用 Playwright 真抓（TractorHouse 或 Machinio）
- [ ] 连接 [TractorVIN](../tractor-vin) API — 输入序列号直接搜同型号二手价
- [ ] 集成 [FarmCalc](../farm-calc) 折旧曲线 — 市场价格 vs 理论价值的差值分析
- [ ] [TractorCompare](../tractor-compare) 的数据面板显示"当前市场行情"列
- [ ] 邮件通知渠道（适合不每天看 Telegram/Discord 的用户）
- [ ] PostgreSQL 支持（多实例部署）
- [ ] 历史趋势分析——"这个型号最近半年跌了多少"
- [ ] Grafana 仪表盘模板
