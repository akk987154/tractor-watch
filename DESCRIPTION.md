# TractorWatch

TractorWatch 是一个二手拖拉机价格追踪器，用于抓取挂牌信息、监测价格变化并发送提醒。

## 核心内容

- 多平台挂牌抓取与监控
- 价格异动检测和通知推送
- 价格历史曲线可视化
- 提供 FastAPI REST API
- 支持 CLI 操作和 Docker 部署

## 技术栈

- Python 3.11+
- FastAPI
- Plotly
- Rich
- SQLite

## 运行方式

```bash
pip install -e .
tractor-watch track --once
```

## 适合上传到 GitHub 的描述

一个用于二手拖拉机挂牌监控、价格追踪和通知提醒的 Python 工具。