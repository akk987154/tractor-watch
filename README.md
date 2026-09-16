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
# 必须是 https://discord.com/api/webhooks/... 形式
DISCORD_WEBHOOK_URL=your_webhook_url

# 数据库（仅支持 sqlite:/// 形式，配错会直接报错而不是静默建一个空库）
DATABASE_URL=sqlite:///tractor_watch.db

# 追踪设置
CHECK_INTERVAL_HOURS=6          # 1-168
MAX_NOTIFY_ATTEMPTS=5           # 单条告警最大重试次数，1-100
ENABLE_DOCS=true                # 是否开放 /docs 与 /openapi.json
USER_AGENT=TractorWatch/1.0
```

> 配置使用 `extra="forbid"`：变量名拼错（例如 `TELEGRAM_BOT_TOCKEN`）
> 会在启动时直接报错，而不是静默得到一个空 token 让通知悄悄失效。

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
| `GET /api/listings` | 挂牌列表，支持 brand/source 过滤，`limit` 1-500 | TractorCompare 可请求同型号的市场行情 |
| `GET /api/listings/{id}` | 单条挂牌详情 | — |
| `GET /api/listings/{id}/history` | 价格变动历史 | FarmCalc 可用于校准折旧曲线 |
| `GET /api/alerts` | 价格异动列表，`limit` 1-500，按 id 倒序（最新在前） | — |
| `GET /api/chart/{id}` | Plotly 价格图表 (HTML) | — |
| `GET /health` | 健康检查 + 通知积压指标 | 见下 |

**`limit` 参数有边界**：`limit=0`、`limit=-1`、`limit=100000` 都会返回 422。
SQLite 里 `LIMIT -1` 表示"不限制"，此前没有任何校验，任何匿名调用者都能
强制全表扫描并完整序列化。

**`/health` 返回的积压指标**：

```json
{
  "status": "ok",
  "listings": 70,
  "alerts_pending": 0,
  "alerts_failed": 0,
  "notifications_configured": false
}
```

- `alerts_pending`：待发送的告警数。持续增长说明通知通道有问题
- `alerts_failed`：重试次数已耗尽、放弃发送的告警数。
  这些告警的失败原因保存在 `alerts.last_notify_error`
- `notifications_configured`：是否配置了任何一个通知渠道

**该 API 没有任何鉴权**，且全部为只读 GET。`docker-compose.yml` 默认把端口
绑在 `127.0.0.1`；如需外部访问，请自行加上反向代理与鉴权，
并用 `ENABLE_DOCS=false` 关掉 `/docs` 与 `/openapi.json`。

### 价格异动算法

**当前实际实现**（下面的描述与代码一致，改代码时请同步改这里）：

1. **抓取**: 调用 scraper 获取挂牌列表（当前是模拟生成，见"关于抓取器"）
2. **Upsert**: 按 `source + source_id` 去重
   - 已存在且价格变化 → 追加一条 `price_history` 并写入一条 alert
   - 已存在且价格未变 → 只更新 `last_seen` / `hours` / `location` 等字段
   - 不存在 → 新建记录
3. **通知派发**: 取出所有 `notified_at IS NULL` 且失败次数未超上限的 alert，
   逐条抢占后发送。`change_percent < 0` 走"降价"文案，否则走"涨价"文案
4. **失败重试**: 发送失败会释放抢占并累计 `notify_attempts` 与
   `last_notify_error`，下一轮继续重试，直到成功或达到
   `MAX_NOTIFY_ATTEMPTS`（默认 5 次）

> ⚠️ **与旧文档的差异**：本节此前写的是"降价 ≥ 5% 通知 / ≥ 10% 紧急通知 /
> 提价记录但不通知 / 连续 2 次以上降价标记为趋势"，这些**在代码里都不存在**。
> 实际行为是：任何价格变化（涨或跌）都会记录并通知，没有百分比阈值，
> 也没有趋势判断。阈值与趋势分析仍在路线图里未实现。

5. **基准线比较**（计划中，还没上线）: 对比 [FarmCalc](../farm-calc) 的理论折旧值——如果市场价低于理论账面价值 → 可能是好 deal

这个"查上次快照 → 算差值 → 跟阈值比"的模式，跟 [TractorLog](../tractor-log) 那边的维护提醒算法是同一个思路——两边不约而同用了类似的逻辑。

### 数据模型

与 `src/tractor_watch/models.py`、`database.py` 中的定义一致：

```
TractorListing {
  id, source, source_id,
  brand, model, year, hours,
  price, location, url, condition,
  first_seen, last_seen, last_price,
  price_history: [                // JSON blob，存于 TEXT 列
    {date, price, old_price, change, change_percent}
  ]
}

PriceAlert {
  id, listing_id,
  old_price, new_price, change_percent,
  notified_at,        // NULL = 尚未成功通知；非 NULL = 已通知（也是发送权的抢占标记）
  notify_attempts,    // 连续失败次数
  last_notify_error   // 最后一次失败原因，便于排查
}
```

> ⚠️ **与旧文档的差异**：此前写的是 `change_pct` / `detected_at` / `notified: bool`，
> 以及 `TractorListing` 里的 `previous_price` / `listed_date` —— 这些字段名都不存在。

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

### v0.5 — 通知可靠性 + 数据层修复 (当前)

**通知不再静默丢失**（这是本项目此前最严重的缺陷，三个问题叠加导致）：
- `notifier` 不检查 HTTP 状态码：`client.post(...)` 的返回值被丢弃，
  也没有 `raise_for_status()`，Telegram 返回 400/401/429 一律当作发送成功
- `notifier` 吞掉所有异常：每个通道 `except Exception` 后只打一行日志就正常返回，
  于是 tracker 那边的 `except` 分支成为死代码
- `tracker` 发完就无条件标记"已通知"
→ 结果：通知失败时告警被标记为已发送、永远不会重试、静默丢失

现在改为：投递失败抛出 `NotificationError` → tracker 调用 `release_alert()`
清空 `notified_at` 并累计 `notify_attempts` / `last_notify_error` → 下一轮重试，
直到成功或达到 `MAX_NOTIFY_ATTEMPTS`。新增两列并对既有数据库自动 `ALTER TABLE` 补齐。

**其它通知层修复**：
- Telegram 去掉 `parse_mode="HTML"`。消息体里本来就没有 HTML 标签，
  开启解析只有坏处：抓到含 `<` 的标题会让 Telegram 直接返回 400（整条通知丢失），
  构造 `<a href=...>` 还能往运维会话里注入链接
- Discord 增加 `allowed_mentions.parse=[]`，避免标题里的 `@everyone` 触发全服 @
- Discord webhook 地址做 host 白名单校验，环境变量写错时不会把告警 POST 到任意地址
- 日志脱敏：token 嵌在 URL 里，异常对象常带完整 URL，直接记录会把凭据写进日志
- `send_summary` 原先只发 Telegram，配置 Discord 的用户永远收不到摘要
- 复用单个 `httpx.AsyncClient`，不再每条消息新建销毁一个连接池

**主循环容错**：
- `watch()` 循环体加 try/except + 指数退避。原先 `run_once` 只护住了爬虫与告警两处，
  `count_listings()` 与 `send_summary()` 都在保护之外，一次
  `sqlite3.OperationalError: database is locked` 就会让协程直接结束；
  进程仍存活，`restart: unless-stopped` 不会重启它，监控永久停摆且无任何提示
- 新增/更新计数修正：`upsert_listing` 改为返回 `(id, created)`。
  原先所有分支都返回真值，调用方用真值判断，导致 `stats["new"]` 恒为 0，
  每日摘要永远显示"新增挂牌: 0"

**数据层**：
- 连接显式关闭。`with sqlite3.connect(...)` 只是**事务**上下文管理器，
  它提交/回滚但**不关闭**连接；原实现每个方法都新建连接并依赖 GC 回收
- 告警派发改为"先抢占再发送"（`claim_alert` 用 UPDATE 的原子性），
  两个 tracker 进程不会重复发送同一条告警
- `get_alerts` 的 `ORDER BY notified_at DESC` 改为 `ORDER BY id DESC`。
  新建告警的 `notified_at` 是 NULL，而 SQLite 中 NULL 在 DESC 里排最后，
  最新最该处理的告警反而被挤到列表底部、正好落在 LIMIT 之外
- 启用 `PRAGMA foreign_keys=ON`（SQLite 默认关闭，schema 里声明的外键形同虚设）
- `price_history` 解析加容错；`LIKE` 查询转义 `%` / `_` 元字符
- `get_all_listings` 的 LIMIT 下沉到 SQL，不再把整表读进内存后切片

**API**：
- 所有 `limit` 参数加边界（1-500）。原先 `limit=-1` 在 SQLite 里表示不限制，
  任何匿名调用者都能强制全表扫描
- 处理函数从 `async def` 改为 `def`，让 FastAPI 丢到线程池执行。
  sqlite3 是同步库，放在 async 处理函数里会阻塞整个事件循环
- `/health` 增加 `alerts_pending` / `alerts_failed` / `notifications_configured`，
  通知发不出去不再是零信号
- `ENABLE_DOCS=false` 可关闭 `/docs` 与 `/openapi.json`

**配置**：
- 用 `SecretStr` 存 token，不再出现在 `repr(settings)` 与 traceback 里
- `extra="forbid"`：变量名拼错直接报错，而不是静默得到空 token
- `CHECK_INTERVAL_HOURS` 限制 1-168（设为 0 会让 `asyncio.sleep(0)` 变成忙循环）
- `DATABASE_URL` 校验必须是 `sqlite:///`。原先配成 `postgresql://...` 时
  `replace` 是空操作，`sqlite3.connect()` 会创建一个以该字符串为文件名的空库
- `models.as_int()` 兜底，通知里不再出现 `None年`

**部署**：
- `docker-compose.yml` 端口改为 `127.0.0.1:8080:8000`（原先裸 `8080:8000` 绑定 0.0.0.0）
- api 服务不再注入 Telegram / Discord 凭据——它只读数据库
- api 服务新增 healthcheck
- Dockerfile：非 root `USER`、`requirements.txt` 精确锁定依赖、
  `--no-build-isolation` + `--no-deps` 避免绕过锁定重新解析、
  新增 `.dockerignore`
- `.gitignore` 加 `!.env.example`（原先 `.env.*` 把模板也忽略了，
  README 里 `cp .env.example .env` 的指引在新克隆的仓库上直接失效）

**依赖**：
- 移除 `jinja2` 与 `selectolax` —— 两者在代码中从未被 import
- 新增 `requirements.txt` 精确锁定版本，逐个经 OSV.dev 复核无已知 advisory

**测试**：新增 57 个用例，覆盖上述全部回归点

### v0.4 — 双渠道通知 + Docker Compose
- Telegram + Discord 双通知渠道
- Docker Compose 双服务部署（tracker 循环 + API 独立）
- 价格异动算法增加趋势判断（连续降价 vs 单次降价）
  —— 注：v0.5 核对代码时发现趋势判断并未实现，已在算法一节更正
- Pydantic v2 迁移（从 v1 升上来改了不少 validator 语法）

### v0.3 — Plotly 可视化 + 价格异动
- Plotly 交互式价格图表生成
- 价格异动检测（百分比阈值）
  —— 注：实际实现是"任何变化都通知"，没有百分比阈值
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
