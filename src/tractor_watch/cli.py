import asyncio
import json
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from .database import Database
from .tracker import Tracker
from .config import settings

console = Console()

def create_app():
    import argparse
    parser = argparse.ArgumentParser(description="TractorWatch - 二手拖拉机价格追踪器")
    sub = parser.add_subparsers(dest="command")

    track = sub.add_parser("track", help="持续监控价格变化")
    track.add_argument("--once", action="store_true", help="只运行一次")

    sub.add_parser("list", help="查看追踪列表")
    sub.add_parser("alerts", help="查看价格异动记录")

    chart = sub.add_parser("chart", help="生成价格历史图表")
    chart.add_argument("id", type=int, help="挂牌ID")
    chart.add_argument("--output", "-o", default="price_chart.html", help="输出文件")

    return parser

async def cmd_track(once: bool = False):
    tracker = Tracker()
    if once:
        stats = await tracker.run_once()
        console.print(f"[green]✅ 检查完成: 新增 {stats['new']}, 更新 {stats['updated']}, 异动 {stats['alerts']}[/green]")
    else:
        await tracker.watch()

def cmd_list():
    db = Database(settings.database_url.replace("sqlite:///", ""))
    listings = db.get_all_listings()

    table = Table(title="🚜 追踪拖拉机列表")
    table.add_column("ID", style="dim")
    table.add_column("品牌", style="bold")
    table.add_column("型号")
    table.add_column("年份")
    table.add_column("小时数")
    table.add_column("当前价格", style="green")
    table.add_column("位置")
    table.add_column("来源")

    for l in listings:
        price = f"¥{l['price']:,.0f}" if l["price"] else "N/A"
        price_color = "white"
        if l.get("price_history"):
            history = json.loads(l["price_history"])
            if history:
                last_change = history[-1]
                if last_change["change_percent"] < 0:
                    price_color = "red"
                elif last_change["change_percent"] > 0:
                    price_color = "yellow"

        table.add_row(
            str(l["id"]), l["brand"], l["model"], str(l["year"] or ""),
            f"{l['hours']:,}" if l["hours"] else "",
            Text(price, style=price_color),
            l["location"] or "", l["source"],
        )

    console.print(table)

def cmd_alerts():
    db = Database(settings.database_url.replace("sqlite:///", ""))
    alerts = db.get_alerts()

    table = Table(title="🚨 价格异动记录")
    table.add_column("ID")
    table.add_column("品牌/型号", style="bold")
    table.add_column("原价")
    table.add_column("现价")
    table.add_column("变化%")
    table.add_column("时间")

    for a in alerts:
        color = "red" if a["change_percent"] < 0 else "yellow"
        table.add_row(
            str(a["id"]),
            f"{a['brand']} {a['model']} ({a['year']})",
            f"¥{a['old_price']:,.0f}",
            f"¥{a['new_price']:,.0f}",
            Text(f"{a['change_percent']:+.1f}%", style=color),
            a["notified_at"][:19] if a["notified_at"] else "",
        )

    console.print(table)

def cmd_chart(listing_id: int, output: str):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    db = Database(settings.database_url.replace("sqlite:///", ""))
    listing = db.get_listing(listing_id)
    if not listing:
        console.print(f"[red]未找到 ID={listing_id} 的挂牌[/red]")
        return

    history = db.get_price_history(listing_id)
    if not history:
        console.print("[yellow]该挂牌暂无价格历史[/yellow]")
        return

    dates = [h["date"][:10] for h in history]
    prices = [h["price"] for h in history]
    changes = [h["change_percent"] for h in history]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3],
                        subplot_titles=(f"{listing['brand']} {listing['model']} 价格走势", "价格变化百分比"))

    fig.add_trace(go.Scatter(x=dates, y=prices, mode="lines+markers",
                             name="价格", line=dict(color="green", width=2),
                             marker=dict(size=8)), row=1, col=1)

    colors = ["red" if c < 0 else "green" for c in changes]
    fig.add_trace(go.Bar(x=dates, y=changes, name="变化%", marker_color=colors), row=2, col=1)

    fig.update_layout(height=600, template="plotly_white",
                      title=f"{listing['brand']} {listing['model']} ({listing['year']}) - 价格历史")
    fig.update_yaxes(title_text="价格 (¥)", row=1, col=1)
    fig.update_yaxes(title_text="变化 (%)", row=2, col=1)

    fig.write_html(output)
    console.print(f"[green]✅ 图表已保存到 {output}[/green]")

async def main():
    parser = create_app()
    args = parser.parse_args()

    if args.command == "track":
        await cmd_track(once=getattr(args, "once", False))
    elif args.command == "list":
        cmd_list()
    elif args.command == "alerts":
        cmd_alerts()
    elif args.command == "chart":
        cmd_chart(args.id, args.output)
    else:
        parser.print_help()

def app():
    asyncio.run(main())

if __name__ == "__main__":
    app()
