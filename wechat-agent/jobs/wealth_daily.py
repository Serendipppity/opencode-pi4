#!/home/pi/agent-venv/bin/python3
# -*- coding: utf-8 -*-
"""银行理财日报 → Discord money 频道 (cron 每天 16:00)"""
import json
import os
import sys
import time

import requests

sys.path.insert(0, "/home/pi/agent-backup/skills/银行理财产品每日查询")
from portfolio_manager import PortfolioManager

CONFIG_PATH = os.path.expanduser("~/.config/opencode/discord-channel.json")
MONEY_CHANNEL = "1559879696257253436"


def day_profit(h, mgr):
    """日收益：普通型用(最新-昨日净值)×份额精确算；现金管理类按年化估（带~）"""
    code = h.get("product_code", "")
    shares = h.get("remaining_shares", 0) or 0
    latest = h.get("latest_nav", 1.0) or 1.0
    is_cash = h.get("product_type") == "现金管理类"
    prev = None
    try:
        hist = mgr.get_nav_history(code, limit=2)
        if len(hist) >= 2 and hist[1].get("unit_nav"):
            prev = float(hist[1]["unit_nav"])
    except Exception:
        pass
    if not is_cash and prev is not None:
        return f"日{(latest - prev) * shares:+,.0f}"
    est = h.get("current_value", 0.0) * h.get("annualized_rate", 0.0) / 100.0 / 365.0
    return f"日~{est:+,.0f}"


def build_text(holdings, mgr):
    from datetime import datetime
    if not holdings:
        return "当前数据库中暂无持仓理财产品。"
    tot_in = sum(h.get("buy_amount", 0.0) for h in holdings)
    tot_val = sum(h.get("current_value", 0.0) for h in holdings)
    tot_p = sum(h.get("total_profit", 0.0) for h in holdings)
    ret = (tot_p / tot_in * 100.0) if tot_in > 0 else 0.0
    today = datetime.now().strftime("%m-%d")
    lines = [
        f"📊 银行理财日报 ({today})",
        f"💰 投入 ¥{tot_in:,.0f}｜市值 ¥{tot_val:,.0f}",
        f"📈 累计 ¥{tot_p:+,.0f} ({ret:+.2f}%)",
        "",
    ]
    for i, h in enumerate(holdings, 1):
        name = h.get("product_name", "")
        for pfx in ["中银理财-", "中银理财", "招银理财", "兴银理财"]:
            name = name.replace(pfx, "")
        early = h.get("earliest_redeem_date", "随时")
        if "随时" in early:
            status = "🟢随时可赎"
        elif "锁" in early:
            status = "🔒锁至" + early.replace("(锁)", "")
        else:
            status = "✅可赎"
        try:
            y, m, d = h.get("buy_date", "").split("-")
            md = f"{int(m)}月{int(d)}日"
        except Exception:
            md = h.get("buy_date", "")
        hold = f"自{md}·持有{h.get('holding_days', 0)}天"
        lines.append(f"{i}. {name} {status}")
        lines.append(f"{hold}｜{day_profit(h, mgr)}")
        lines.append(
            f"¥{h.get('current_value', 0.0):,.0f}｜"
            f"{h.get('total_profit', 0.0):+,.0f}({h.get('return_rate', 0.0):+.2f}%)｜"
            f"年化{h.get('annualized_rate', 0.0):.2f}%"
        )
        lines.append("")
    return "\n".join(lines).rstrip()


def post_to_channel(token, channel_id, payload):
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    for attempt in range(5):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=20)
            if r.status_code == 429:
                time.sleep(r.json().get("retry_after", 5))
                continue
            r.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            print(f"[Network Error] ({attempt+1}/5): {e}", flush=True)
            time.sleep(2 ** attempt)
    return False


def main():
    try:
        cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
    except Exception as e:
        print(f"读取配置失败: {e}", flush=True)
        return 1
    token = cfg.get("botToken")
    if not token:
        print("Discord Token 未配置！", flush=True)
        return 1

    try:
        mgr = PortfolioManager()
        print("正在拉取最新持仓与净值数据...", flush=True)
        holdings = mgr.list_all_holdings()
        payload = {"content": build_text(holdings, mgr)}
    except Exception as e:
        print(f"❌ 生成日报失败: {e}", flush=True)
        post_to_channel(token, MONEY_CHANNEL, {"content": f"❌ 理财日报生成失败：{e}"})
        return 1

    if post_to_channel(token, MONEY_CHANNEL, payload):
        print(f"✅ 理财日报已推送 money 频道（{len(holdings)} 只产品）", flush=True)
        return 0
    print("❌ 推送失败", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
