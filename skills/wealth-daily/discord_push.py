#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Discord 理财收益日报推送脚本 (支持直连或通过树莓派代理/转发)
"""

import os
import sys
import argparse
from datetime import datetime
from typing import Optional, Dict, Any, List
import requests

# 引入持仓管理核心引擎
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from portfolio_manager import PortfolioManager, str_width


def build_discord_payload(holdings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """构建 Discord 富文本 Embed 卡片消息"""
    if not holdings:
        return {
            "username": "银行理财资产助手",
            "content": "当前数据库中暂无持仓理财产品。"
        }

    tot_invested = sum(h.get('buy_amount', 0.0) for h in holdings)
    tot_redeemed = sum(h.get('redeem_amount', 0.0) for h in holdings)
    tot_cur_val = sum(h.get('current_value', 0.0) for h in holdings)
    tot_profit = sum(h.get('total_profit', 0.0) for h in holdings)
    overall_ret = (tot_profit / tot_invested * 100.0) if tot_invested > 0 else 0.0

    today_str = datetime.now().strftime("%Y-%m-%d")
    color = 0x2ECC71 if tot_profit >= 0 else 0xE74C3C  # 绿色盈利，红色亏损

    # 汇总大盘字段
    fields = [
        {
            "name": "💰 累计投入本金",
            "value": f"¥{tot_invested:,.2f}",
            "inline": True
        },
        {
            "name": "🏦 当前持仓市值",
            "value": f"¥{tot_cur_val:,.2f}",
            "inline": True
        },
        {
            "name": "📈 累计总收益",
            "value": f"**¥{tot_profit:+,.2f}** ({overall_ret:+.2f}%)",
            "inline": True
        }
    ]

    # 添加各产品明细
    for idx, h in enumerate(holdings, 1):
        code = h.get('product_code', '')
        name = h.get('product_name', '')
        # 简化名称
        for pfx in ["中银理财-", "中银理财", "招银理财", "兴银理财"]:
            name = name.replace(pfx, "")
        name = name.replace("最短持有期日开", "持有期").replace("固定收益类理财计划", "").replace("固收类理财产品", "")

        buy_d = h.get('buy_date', '')
        earliest_d = h.get('earliest_redeem_date', '随时')
        c_val = h.get('current_value', 0.0)
        p_amt = h.get('total_profit', 0.0)
        ret_rate = h.get('return_rate', 0.0)
        ann_rate = h.get('annualized_rate', 0.0)
        latest_nav = h.get('latest_nav', 1.0)
        latest_d = h.get('latest_date', '')

        # 赎回状态指示
        if "随时" in earliest_d:
            redeem_status = "🟢 随时可赎"
        elif "锁" in earliest_d:
            redeem_status = f"🔒 锁定中 (最早 {earliest_d.replace('(锁)', '')} 可赎)"
        else:
            redeem_status = f"✅ 已过锁定期 (开放赎回中，最早可赎日 {earliest_d})"

        item_desc = (
            f"• **当前市值**: ¥{c_val:,.2f} (净值 `{latest_nav}` | 披露日 {latest_d})\n"
            f"• **累计收益**: **¥{p_amt:+,.2f}** (`{ret_rate:+.2f}%`) | 年化: `{ann_rate:.2f}%`\n"
            f"• **赎回状态**: {redeem_status}"
        )

        fields.append({
            "name": f"{idx}. {name} ({code})",
            "value": item_desc,
            "inline": False
        })

    embed = {
        "title": f"📊 银行理财持仓与收益日报 ({today_str})",
        "description": f"已自动联网拉取各大银行最新官方净值核算完成：",
        "color": color,
        "fields": fields,
        "footer": {
            "text": "数据源：中银理财 / 招银理财 / 兴银理财官方披露"
        },
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }

    return {
        "username": "理财资产管家",
        "avatar_url": "https://img.icons8.com/color/96/bank-building.png",
        "embeds": [embed]
    }


def send_to_discord(webhook_url: str, proxy: Optional[str] = None) -> bool:
    """拉取最新持仓收益并推送到 Discord"""
    mgr = PortfolioManager()
    print("正在拉取最新持仓与净值数据...")
    holdings = mgr.list_all_holdings()

    payload = build_discord_payload(holdings)
    proxies = {"http": proxy, "https": proxy} if proxy else None

    print(f"正在发送至 Discord Webhook...")
    try:
        resp = requests.post(webhook_url, json=payload, proxies=proxies, timeout=15)
        if resp.status_code in [200, 204]:
            print("✅ Discord 推送成功！已在手机端弹窗显示。")
            return True
        else:
            print(f"❌ 推送失败，HTTP 状态码: {resp.status_code}, 响应: {resp.text}")
            return False
    except Exception as e:
        print(f"❌ 网络请求异常: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Discord 理财日报推送工具")
    parser.add_argument("--url", default=os.environ.get("DISCORD_WEBHOOK_URL"), help="Discord Webhook URL (也可设置环境变量 DISCORD_WEBHOOK_URL)")
    parser.add_argument("--proxy", default=os.environ.get("HTTP_PROXY"), help="网络代理 (如 http://192.168.1.100:7890，适合树莓派代理)")

    args = parser.parse_args()

    if not args.url:
        print("\n请提供 Discord Webhook URL！")
        print("用法示例:")
        print("  python3 discord_push.py --url 'https://discord.com/api/webhooks/xxx/yyy'")
        print("  或者设置环境变量: export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/xxx/yyy'\n")
        return

    send_to_discord(args.url, args.proxy)


if __name__ == "__main__":
    main()
