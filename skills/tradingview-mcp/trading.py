#!/usr/bin/env python3
"""
CLI wrapper for tradingview-mcp — called by OpenClaw agent via bash.
"""
import sys
import json
import os
import glob
from datetime import datetime, timezone

# 动态挂载环境变量
USER_HOME = os.path.expanduser("~")
search_path = f"{USER_HOME}/.local/share/uv/tools/tradingview-mcp-server/lib/python*/site-packages"
candidates = glob.glob(search_path)
if candidates:
    sys.path.insert(0, candidates[0])
else:
    print(json.dumps({"error": f"Could not find tradingview-mcp-server"}))
    sys.exit(1)

# 导入我们刚刚测试成功的 yfinance
import yfinance as yf

try:
    # 丢弃坏掉的yahoo服务，只导入回测和情绪分析
    from tradingview_mcp.core.services.backtest_service import run_backtest, compare_strategies, walk_forward_backtest
    from tradingview_mcp.core.services.sentiment_service import analyze_sentiment
except ImportError as e:
    print(json.dumps({"error": str(e)}))
    sys.exit(1)

# ==========================================
# 🚀 yfinance 强力接管函数 (彻底绕过原作者的 403 BUG)
# ==========================================
def safe_get_price(symbol):
    try:
        t = yf.Ticker(symbol)
        price = t.fast_info['lastPrice']
        prev = t.fast_info['previousClose']
        change = price - prev
        pct = (change / prev) * 100
        return {
            "symbol": symbol,
            "price": round(price, 4),
            "change": round(change, 4),
            "change_percent": round(pct, 2),
            "source": "yfinance bypass"
        }
    except Exception as e:
        return {"error": str(e), "symbol": symbol}

def safe_get_snapshot():
    assets = {
        "indices": [("^GSPC", "S&P 500"), ("^IXIC", "NASDAQ"), ("^VIX", "VIX")],
        "crypto": [("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum")],
        "fx": [("EURUSD=X", "EUR/USD")],
        "etfs": [("SPY", "SPDR S&P 500"), ("GLD", "Gold")]
    }
    res = {"indices": [], "crypto": [], "fx": [], "etfs": [], "timestamp": datetime.now(timezone.utc).isoformat()}
    for category, items in assets.items():
        for sym, name in items:
            try:
                t = yf.Ticker(sym)
                p = t.fast_info['lastPrice']
                prev = t.fast_info['previousClose']
                res[category].append({
                    "symbol": sym,
                    "name": name,
                    "price": round(p, 4),
                    "change_percent": round(((p - prev) / prev) * 100, 2)
                })
            except:
                pass
    return res
# ==========================================

cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
args = sys.argv[2:]

try:
    if cmd == "price":
        # 被我们接管
        print(json.dumps(safe_get_price(args[0]), indent=2))

    elif cmd == "snapshot":
        # 被我们接管
        print(json.dumps(safe_get_snapshot(), indent=2))

    elif cmd == "backtest":
        symbol   = args[0]
        strategy = args[1] if len(args) > 1 else "rsi"
        period   = args[2] if len(args) > 2 else "1y"
        interval = args[3] if len(args) > 3 else "1d"
        print(json.dumps(run_backtest(symbol, strategy, period, interval=interval), indent=2))

    elif cmd == "compare":
        symbol = args[0]
        period = args[1] if len(args) > 1 else "1y"
        print(json.dumps(compare_strategies(symbol, period), indent=2))

    elif cmd == "walkforward":
        symbol   = args[0]
        strategy = args[1] if len(args) > 1 else "rsi"
        period   = args[2] if len(args) > 2 else "2y"
        print(json.dumps(walk_forward_backtest(symbol, strategy, period), indent=2))

    elif cmd == "sentiment":
        print(json.dumps(analyze_sentiment(args[0]), indent=2))

    elif cmd == "help":
        print("Commands: price <sym> | snapshot | backtest <sym> <strategy> <period> [interval] | compare <sym> [period] | walkforward <sym> [strategy] [period] | sentiment <sym>")
        print("Strategies: rsi | bollinger | macd | ema_cross | supertrend | donchian")

    else:
        print(json.dumps({"error": f"Unknown command: {cmd}"}))

except Exception as e:
    print(json.dumps({"error": str(e)}))
