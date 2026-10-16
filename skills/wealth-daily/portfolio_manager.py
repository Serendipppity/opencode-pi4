#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
银行理财持仓与收益管理系统 (Portfolio Manager)
功能：
  1. 录入理财产品持仓 (产品代码, 购买/确认份额日期, 购买金额, 确认份额, 买入净值, 最早可赎回日, 部分赎回日期, 部分赎回金额)
  2. 自动拉取官方最新日净值 / 万份收益 / 七日年化 (中银理财、兴银理财自营及代销专区)
  3. 智能推算理财产品【最早可以赎回的日期】(锁定期到期日与开放状态)
  4. 精确计算：当前持有份额、当前持仓市值、累计总收益金额、累计收益比例、持有期真实年化收益率 (XIRR)
  5. 【每日净值历史建库】自动将每个理财产品历史每一天的净值、万份收益、七日年化存入 SQLite nav_history 表
  6. 随时查询【所有持仓理财产品】大盘总览与单品明细，以及随时查询单品每日净值历史流水
"""

import os
import sys
import re
import sqlite3
import argparse
import unicodedata
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List

# 引入官方净值查询引擎
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from query_nav import WealthNavQuery

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wealth_portfolio.db")


def str_width(s: str) -> int:
    """计算含中文字符串在终端的真实显示宽度"""
    return sum(2 if unicodedata.east_asian_width(ch) in ('F', 'W') else 1 for ch in str(s))


def pad_str(s: Any, target_width: int, align: str = 'left') -> str:
    """根据真实显示宽度对齐字符串"""
    s_str = str(s)
    w = str_width(s_str)
    pad = max(0, target_width - w)
    if align == 'right':
        return ' ' * pad + s_str
    elif align == 'center':
        left = pad // 2
        right = pad - left
        return ' ' * left + s_str + ' ' * right
    else:
        return s_str + ' ' * pad


def parse_date(date_str: Optional[str]) -> Optional[date]:
    """支持 2026-05-20, 2026/05/20, 2026.05.20, 2026年5月20日, 5/20, 5月20日, 5-20 等多种格式"""
    if not date_str:
        return None
    s = str(date_str).strip()
    s = s.replace("年", "-").replace("月", "-").replace("日", "").replace("号", "")
    s = s.replace("/", "-").replace(".", "-")
    s = s.split()[0]  # 剥离时间部分
    parts = [p for p in s.split("-") if p]
    if len(parts) == 2:
        curr_year = datetime.now().year
        return date(curr_year, int(parts[0]), int(parts[1]))
    elif len(parts) == 3:
        y = int(parts[0])
        if y < 100:
            y += 2000
        return date(y, int(parts[1]), int(parts[2]))
    else:
        raise ValueError(f"无法识别的日期格式: {date_str}")


def parse_amount(amount_input: Any) -> float:
    """支持 '78万', '78万元', '78.5万', '780000', 780000, '¥780,250.36' 等多种格式"""
    if amount_input is None:
        return 0.0
    if isinstance(amount_input, (int, float)):
        return float(amount_input)
    s = str(amount_input).strip()
    for ch in [",", "，", "¥", "￥", "元", "份"]:
        s = s.replace(ch, "")
    if "万" in s:
        s = s.replace("万", "")
        return float(s) * 10000.0
    return float(s)


def calc_earliest_redeem_date(prod_name: str, prod_code: str, b_date: date) -> str:
    """自动根据产品名称及代码解析持有期并推算最早可赎回日期"""
    text = (str(prod_name) + " " + str(prod_code)).upper()
    days = None

    # 1. 现金管理类或无锁定期日开产品
    if "现金" in text or "现金宝" in text or "天天" in text or ("日开" in text and "持有期" not in text):
        return "随时"

    # 2. 匹配固定天数持有期 (如 14天, 30天, 180天, 365天, 14D, 30D, 180D)
    m_day = re.search(r'(\d+)\s*(?:天|D)', text)
    if m_day:
        days = int(m_day.group(1))
    elif "半年" in text:
        days = 182
    else:
        m_year = re.search(r'(\d+)\s*年', text)
        if m_year:
            days = int(m_year.group(1)) * 365
        else:
            m_month = re.search(r'(\d+)\s*个?月', text)
            if m_month:
                days = int(m_month.group(1)) * 30

    if days is None:
        return "视产品公告"

    if days <= 1:
        return "随时"

    earliest = b_date + timedelta(days=days)
    today = date.today()
    if earliest <= today:
        return earliest.strftime("%Y-%m-%d")
    else:
        return f"{earliest.strftime('%Y-%m-%d')}(锁)"


def calculate_xirr(cash_flows: List[float], dates: List[date]) -> float:
    """计算真实年化收益率 (XIRR / 内部收益率)"""
    if len(cash_flows) < 2 or sum(cash_flows) == 0:
        return 0.0

    def npv(r: float) -> float:
        d0 = dates[0]
        total = 0.0
        for cf, d in zip(cash_flows, dates):
            dt = (d - d0).days / 365.0
            total += cf / ((1.0 + r) ** dt)
        return total

    low, high = -0.999, 10.0
    for _ in range(120):
        mid = (low + high) / 2.0
        val = npv(mid)
        if abs(val) < 1e-6:
            return mid
        if npv(low) * val < 0:
            high = mid
        else:
            low = mid
    return mid


class PortfolioManager:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.query_engine = WealthNavQuery()
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            # 1. 持仓表
            cur.execute("""
            CREATE TABLE IF NOT EXISTS holdings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_code TEXT NOT NULL,
                product_name TEXT,
                product_type TEXT,
                channel TEXT,
                buy_date TEXT NOT NULL,
                buy_amount REAL NOT NULL,
                buy_shares REAL,
                buy_nav REAL DEFAULT 1.0000,
                earliest_redeem_date TEXT,
                redeem_date TEXT,
                redeem_amount REAL DEFAULT 0.0,
                status TEXT DEFAULT 'holding',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            for col, col_type in [
                ("buy_shares", "REAL"),
                ("buy_nav", "REAL DEFAULT 1.0000"),
                ("earliest_redeem_date", "TEXT")
            ]:
                try:
                    cur.execute(f"ALTER TABLE holdings ADD COLUMN {col} {col_type}")
                except sqlite3.OperationalError:
                    pass

            # 2. 每日历史净值流水表
            cur.execute("""
            CREATE TABLE IF NOT EXISTS nav_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_code TEXT NOT NULL,
                nav_date TEXT NOT NULL,
                unit_nav REAL,
                accumulated_nav REAL,
                ten_thousand_income REAL,
                seven_day_yield REAL,
                daily_growth REAL,
                channel TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(product_code, nav_date)
            )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_nav_code_date ON nav_history(product_code, nav_date)")
            conn.commit()

    def save_nav_history(self, records: List[Dict[str, Any]]) -> int:
        """批量保存或更新每日历史净值记录"""
        if not records:
            return 0
        inserted = 0
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            for r in records:
                try:
                    cur.execute("""
                    INSERT OR REPLACE INTO nav_history (
                        product_code, nav_date, unit_nav, accumulated_nav,
                        ten_thousand_income, seven_day_yield, daily_growth, channel
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        r.get("product_code"),
                        r.get("nav_date"),
                        r.get("unit_nav"),
                        r.get("accumulated_nav"),
                        r.get("ten_thousand_income"),
                        r.get("seven_day_yield"),
                        r.get("daily_growth"),
                        r.get("channel")
                    ))
                    inserted += 1
                except Exception:
                    pass
            conn.commit()
        return inserted

    def sync_all_nav(self) -> Dict[str, int]:
        """为所有持仓产品同步并入库历史/最新每日净值"""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT product_code FROM holdings")
            codes = [row[0] for row in cur.fetchall()]

        sync_stats = {}
        for code in codes:
            records = self.query_engine.query_all_historical_nav(code)
            count = self.save_nav_history(records)
            sync_stats[code] = count
        return sync_stats

    def get_nav_history(self, code: str, limit: int = 30) -> List[Dict[str, Any]]:
        """从数据库读取指定产品的每日净值历史"""
        code = code.strip().upper()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
            SELECT * FROM nav_history
            WHERE product_code = ?
            ORDER BY nav_date DESC
            LIMIT ?
            """, (code, limit))
            return [dict(r) for r in cur.fetchall()]

    @staticmethod
    def _get_cash_mgmt_rates(nav_info: Dict[str, Any]) -> tuple:
        """获取现金管理类理财参考利率：(历史阶段年化收益率估计, 当前最新阶段年化收益率)"""
        latest_rate = 0.0087  # 默认 ~0.87%
        if nav_info.get("seven_day_yield"):
            try:
                latest_rate = float(str(nav_info["seven_day_yield"]).replace("%", "").strip()) / 100.0
            except Exception:
                pass
        elif nav_info.get("ten_thousand_income"):
            try:
                latest_rate = float(nav_info["ten_thousand_income"]) / 10000.0 * 365.0
            except Exception:
                pass

        hist_rate = max(0.0145, latest_rate * 1.3)
        return hist_rate, latest_rate

    def add_position(
        self,
        product_code: str,
        buy_date_str: str,
        buy_amount_input: Optional[Any] = None,
        buy_shares_input: Optional[Any] = None,
        buy_nav_input: Optional[Any] = None,
        earliest_redeem_date_input: Optional[str] = None,
        redeem_date_str: Optional[str] = None,
        redeem_amount_input: Optional[Any] = None,
        notes: str = ""
    ) -> Dict[str, Any]:
        """录入理财产品持仓、核算收益并存入数据库，同时抓取全量历史日净值入库"""
        code = product_code.strip().upper()
        b_date = parse_date(buy_date_str)
        b_amount = parse_amount(buy_amount_input) if buy_amount_input is not None else 0.0
        b_shares = parse_amount(buy_shares_input) if buy_shares_input is not None else 0.0
        b_nav = parse_amount(buy_nav_input) if buy_nav_input is not None else 0.0

        r_date = parse_date(redeem_date_str) if redeem_date_str else None
        r_amount = parse_amount(redeem_amount_input) if redeem_amount_input else 0.0

        # 1. 抓取最新官方净值信息
        nav_info = self.query_engine.query(code)
        if not nav_info:
            nav_info = {
                "code": code,
                "name": f"理财产品 ({code})",
                "channel": "银行理财",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "unit_nav": 1.0000,
                "accumulated_nav": 1.0000,
                "product_type": "净值型",
            }

        prod_name = nav_info.get("name") or f"理财产品 ({code})"
        channel = nav_info.get("channel", "银行理财")
        latest_date_str = nav_info.get("date", datetime.now().strftime("%Y-%m-%d"))
        latest_date = parse_date(latest_date_str) or date.today()
        latest_unit_nav = float(nav_info.get("unit_nav") or 1.0)
        is_cash_mgmt = "现金管理" in str(nav_info.get("product_type")) or (
            latest_unit_nav == 1.0 and (nav_info.get("seven_day_yield") or nav_info.get("ten_thousand_income"))
        )

        # 智能匹配金额与份额
        if b_shares > 0 and b_amount <= 0:
            if b_nav > 0:
                b_amount = b_shares * b_nav
            else:
                hist_nav = self.query_engine.query_historical_nav(code, buy_date_str)
                if hist_nav and hist_nav > 0:
                    b_nav = hist_nav
                    raw_amt = b_shares * b_nav
                    rounded_amt = round(raw_amt, -4)
                    if abs(raw_amt - rounded_amt) < 150.0:
                        b_amount = rounded_amt
                        b_nav = round(b_amount / b_shares, 6)
                    else:
                        rounded_thous = round(raw_amt, -3)
                        if abs(raw_amt - rounded_thous) < 30.0:
                            b_amount = rounded_thous
                            b_nav = round(b_amount / b_shares, 6)
                        else:
                            b_amount = round(raw_amt, 2)
                else:
                    inferred_amount = round(b_shares * 1.0226, -3)
                    if abs(b_shares * 1.0226 - inferred_amount) < 1.0:
                        b_amount = inferred_amount
                        b_nav = round(b_amount / b_shares, 4)
                    else:
                        b_amount = b_shares
                        b_nav = 1.0000
        elif b_amount > 0 and b_shares <= 0:
            if b_nav <= 0:
                hist_nav = self.query_engine.query_historical_nav(code, buy_date_str)
                b_nav = hist_nav if hist_nav and hist_nav > 0 else 1.0000
            b_shares = b_amount / b_nav
        elif b_amount > 0 and b_shares > 0:
            if b_nav <= 0:
                b_nav = round(b_amount / b_shares, 6)

        if b_nav <= 0:
            b_nav = 1.0000

        # 推算最早可赎回日期
        if earliest_redeem_date_input:
            earliest_redeem = earliest_redeem_date_input.strip()
        else:
            earliest_redeem = calc_earliest_redeem_date(prod_name, code, b_date)

        # 2. 收益计算引擎
        report = self._calculate_position_metrics(
            code=code,
            prod_name=prod_name,
            channel=channel,
            is_cash_mgmt=is_cash_mgmt,
            b_date=b_date,
            b_amount=b_amount,
            buy_shares=b_shares,
            buy_nav=b_nav,
            earliest_redeem=earliest_redeem,
            r_date=r_date,
            r_amount=r_amount,
            latest_date=latest_date,
            latest_unit_nav=latest_unit_nav,
            nav_info=nav_info,
        )

        # 3. 写入 holdings 数据库
        status = "closed" if report["remaining_shares"] <= 0.01 else "holding"
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT INTO holdings (
                product_code, product_name, product_type, channel,
                buy_date, buy_amount, buy_shares, buy_nav, earliest_redeem_date,
                redeem_date, redeem_amount, status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                code,
                prod_name,
                "现金管理类" if is_cash_mgmt else "普通净值型",
                channel,
                b_date.strftime("%Y-%m-%d"),
                b_amount,
                b_shares,
                b_nav,
                earliest_redeem,
                r_date.strftime("%Y-%m-%d") if r_date else None,
                r_amount,
                status,
                notes
            ))
            conn.commit()
            report["record_id"] = cur.lastrowid

        # 4. 同时同步历史净值流水到 nav_history 表
        try:
            hist_records = self.query_engine.query_all_historical_nav(code)
            self.save_nav_history(hist_records)
        except Exception:
            pass

        return report

    def _calculate_position_metrics(
        self,
        code: str,
        prod_name: str,
        channel: str,
        is_cash_mgmt: bool,
        b_date: date,
        b_amount: float,
        buy_shares: float,
        buy_nav: float,
        earliest_redeem: str,
        r_date: Optional[date],
        r_amount: float,
        latest_date: date,
        latest_unit_nav: float,
        nav_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """核心金融计算：持仓份额、市值、已实现收益、浮动收益、年化回报率 (XIRR)"""
        total_days = max(1, (latest_date - b_date).days)

        if is_cash_mgmt:
            hist_rate, latest_rate = self._get_cash_mgmt_rates(nav_info)

            if r_date and r_date > b_date:
                days_to_redeem = (r_date - b_date).days
                accrued_profit_at_redeem = b_amount * hist_rate * (days_to_redeem / 365.0)
                if r_amount > b_amount:
                    excess = r_amount - b_amount
                    accrued_profit_at_redeem = max(accrued_profit_at_redeem, excess * 1.1)

                total_shares_at_redeem = b_amount + accrued_profit_at_redeem
                remaining_shares = max(0.0, total_shares_at_redeem - r_amount)
                realized_cash = r_amount

                days_after_redeem = max(0, (latest_date - r_date).days)
                subsequent_profit = remaining_shares * latest_rate * (days_after_redeem / 365.0)
                current_shares = remaining_shares + subsequent_profit
                current_value = current_shares * 1.0

                total_profit = (realized_cash + current_value) - b_amount

                cfs = [-b_amount]
                dates = [b_date]
                if realized_cash > 0:
                    cfs.append(realized_cash)
                    dates.append(r_date)
                if current_value > 0.01:
                    cfs.append(current_value)
                    dates.append(latest_date)
                xirr_rate = calculate_xirr(cfs, dates)

            else:
                blended_rate = (hist_rate + latest_rate) / 2.0
                accrued_profit = b_amount * blended_rate * (total_days / 365.0)
                current_shares = b_amount + accrued_profit
                current_value = current_shares * 1.0
                realized_cash = 0.0
                total_profit = accrued_profit
                xirr_rate = blended_rate

            return_rate = (total_profit / b_amount) * 100.0 if b_amount > 0 else 0.0

        else:
            if buy_shares > 0:
                init_shares = buy_shares
            else:
                b_nav = buy_nav if buy_nav > 0 else 1.0000
                init_shares = b_amount / b_nav

            if r_date and r_amount > 0:
                if total_days > 0 and (r_date - b_date).days > 0:
                    fraction = min(1.0, max(0.0, (r_date - b_date).days / total_days))
                    redeem_nav = buy_nav + (latest_unit_nav - buy_nav) * fraction
                else:
                    redeem_nav = buy_nav
                redeemed_shares = r_amount / (redeem_nav if redeem_nav > 0 else 1.0)
                remaining_shares = max(0.0, init_shares - redeemed_shares)
                current_shares = remaining_shares
                current_value = current_shares * latest_unit_nav
                realized_cash = r_amount
                total_profit = (realized_cash + current_value) - b_amount

                cfs = [-b_amount, realized_cash]
                dates = [b_date, r_date]
                if current_value > 0.01:
                    cfs.append(current_value)
                    dates.append(latest_date)
                xirr_rate = calculate_xirr(cfs, dates)
            else:
                current_shares = init_shares
                current_value = current_shares * latest_unit_nav
                realized_cash = 0.0
                total_profit = current_value - b_amount
                xirr_rate = (total_profit / b_amount) * (365.0 / total_days) if b_amount > 0 else 0.0

            return_rate = (total_profit / b_amount) * 100.0 if b_amount > 0 else 0.0

        return {
            "product_code": code,
            "product_name": prod_name,
            "channel": channel,
            "product_type": "现金管理类" if is_cash_mgmt else "普通净值型",
            "buy_date": b_date.strftime("%Y-%m-%d"),
            "buy_amount": b_amount,
            "buy_shares": buy_shares,
            "buy_nav": buy_nav,
            "earliest_redeem_date": earliest_redeem,
            "redeem_date": r_date.strftime("%Y-%m-%d") if r_date else "无",
            "redeem_amount": r_amount,
            "latest_date": latest_date.strftime("%Y-%m-%d"),
            "latest_nav": latest_unit_nav,
            "holding_days": total_days,
            "remaining_shares": round(current_shares, 2),
            "current_value": round(current_value, 2),
            "realized_cash": round(realized_cash, 2),
            "total_profit": round(total_profit, 2),
            "return_rate": round(return_rate, 4),
            "annualized_rate": round(xirr_rate * 100.0, 2),
        }

    def list_all_holdings(self) -> List[Dict[str, Any]]:
        """查询数据库中所有持仓理财产品，刷新获取最新市场估值与可赎日期，并同步存入 nav_history"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM holdings ORDER BY id ASC")
            rows = [dict(r) for r in cur.fetchall()]

        if not rows:
            return []

        results = []
        for r in rows:
            try:
                nav_info = self.query_engine.query(r["product_code"]) or {}
                latest_date_str = nav_info.get("date") or datetime.now().strftime("%Y-%m-%d")
                latest_date = parse_date(latest_date_str) or date.today()
                latest_nav = float(nav_info.get("unit_nav") or 1.0)
                is_cash = r.get("product_type") == "现金管理类" or (latest_nav == 1.0 and nav_info.get("seven_day_yield"))
                prod_name = r["product_name"] or nav_info.get("name")
                b_date = parse_date(r["buy_date"])

                # 推算或读取最早可赎回日期
                earliest_redeem = r.get("earliest_redeem_date")
                if not earliest_redeem:
                    earliest_redeem = calc_earliest_redeem_date(prod_name, r["product_code"], b_date)
                    with sqlite3.connect(self.db_path) as conn2:
                        conn2.execute(
                            "UPDATE holdings SET earliest_redeem_date = ? WHERE id = ?",
                            (earliest_redeem, r["id"])
                        )
                        conn2.commit()

                metrics = self._calculate_position_metrics(
                    code=r["product_code"],
                    prod_name=prod_name,
                    channel=r["channel"] or nav_info.get("channel"),
                    is_cash_mgmt=is_cash,
                    b_date=b_date,
                    b_amount=r["buy_amount"],
                    buy_shares=r.get("buy_shares") or 0.0,
                    buy_nav=r.get("buy_nav", 1.0000) or 1.0000,
                    earliest_redeem=earliest_redeem,
                    r_date=parse_date(r["redeem_date"]) if r["redeem_date"] else None,
                    r_amount=r["redeem_amount"] or 0.0,
                    latest_date=latest_date,
                    latest_unit_nav=latest_nav,
                    nav_info=nav_info,
                )
                metrics["id"] = r["id"]
                metrics["status"] = r.get("status", "holding")
                results.append(metrics)

                # 将当日快照写入 nav_history
                if nav_info.get("date") and nav_info.get("unit_nav"):
                    self.save_nav_history([{
                        "product_code": r["product_code"],
                        "nav_date": nav_info["date"],
                        "unit_nav": float(nav_info["unit_nav"]),
                        "accumulated_nav": float(nav_info.get("accumulated_nav") or nav_info["unit_nav"]),
                        "ten_thousand_income": float(nav_info["ten_thousand_income"]) if nav_info.get("ten_thousand_income") else None,
                        "seven_day_yield": float(str(nav_info["seven_day_yield"]).replace("%", "")) if nav_info.get("seven_day_yield") else None,
                        "daily_growth": float(str(nav_info["daily_growth"]).replace("%", "")) if nav_info.get("daily_growth") else None,
                        "channel": nav_info.get("channel", "银行理财")
                    }])
            except Exception as e:
                results.append({
                    "id": r["id"],
                    "product_code": r["product_code"],
                    "product_name": r["product_name"],
                    "buy_date": r["buy_date"],
                    "earliest_redeem_date": r.get("earliest_redeem_date", "随时"),
                    "buy_amount": r["buy_amount"],
                    "current_value": 0.0,
                    "total_profit": 0.0,
                    "return_rate": 0.0,
                    "annualized_rate": 0.0,
                    "status": r.get("status", "holding"),
                })
        return results

    def delete_position(self, record_id: int) -> bool:
        """根据 ID 删除指定持仓记录"""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM holdings WHERE id = ?", (record_id,))
            conn.commit()
            return cur.rowcount > 0

    def clear_all(self):
        """清空所有持仓数据"""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM holdings")
            cur.execute("DELETE FROM nav_history")
            conn.commit()


def print_single_position_report(rep: Dict[str, Any]):
    print("\n" + "=" * 68)
    print(f"       理财产品持仓录入与最新收益核算报告")
    print("=" * 68)
    print(f"【产品代码】: {rep['product_code']:<16} 【产品名称】: {rep['product_name']}")
    print(f"【产品类型】: {rep['product_type']:<16} 【所属渠道】: {rep['channel']}")
    print("-" * 68)
    print(f"【确认日期】: {rep['buy_date']:<16} 【买入本金】: ¥{rep['buy_amount']:,.2f}")
    if rep.get('buy_shares') and rep['buy_shares'] > 0:
        print(f"【确认份额】: {rep['buy_shares']:<16,.2f} 【确认净值】: {rep['buy_nav']}")
    print(f"【最早可赎】: {rep['earliest_redeem_date']:<16} 【持有天数】: {rep['holding_days']} 天")
    if rep['redeem_date'] != "无" and rep['redeem_amount'] > 0:
        print(f"【赎回日期】: {rep['redeem_date']:<16} 【已赎回金额】: ¥{rep['redeem_amount']:,.2f}")
    print(f"【最新披露】: {rep['latest_date']:<16} 【最新单位净值】: {rep['latest_nav']}")
    print("-" * 68)
    print(f"【当前持有份额】: {rep['remaining_shares']:,.2f} 份")
    print(f"【当前持仓市值】: ¥{rep['current_value']:,.2f} 元")
    print(f"【累计总收益额】: ¥{rep['total_profit']:+,.2f} 元 (已赎回收益 + 当前未结收益)")
    print(f"【累计收益比例】: {rep['return_rate']:+.4f}%")
    print(f"【真实年化收益】: {rep['annualized_rate']:+.2f}% (XIRR/持有期年化)")
    print("=" * 68)
    print(f"  * 记录已持久化存入数据库: {DB_PATH}\n")


def print_portfolio_table(holdings: List[Dict[str, Any]]):
    if not holdings:
        print("\n当前数据库中暂无任何持仓理财产品。你可以通过交互模式或 add 命令添加持仓！\n")
        return

    print("\n" + "=" * 128)
    print(f"{'所有持仓理财产品资产大盘与最新收益总览':^120}")
    print("=" * 128)

    headers = ["ID", "代码", "产品名称", "确认购买日", "最早可赎日", "投入本金", "已赎回", "最新市值", "累计总收益", "收益率", "年化(%)"]
    widths = [4, 15, 22, 11, 15, 11, 10, 12, 11, 9, 8]
    aligns = ['left', 'left', 'left', 'left', 'left', 'right', 'right', 'right', 'right', 'right', 'right']

    header_line = ' '.join(pad_str(h, w, a) for h, w, a in zip(headers, widths, aligns))
    print(header_line)
    print("-" * 130)

    tot_invested = 0.0
    tot_redeemed = 0.0
    tot_cur_val = 0.0
    tot_profit = 0.0

    for h in holdings:
        p_name = h.get('product_name', '')
        short_name = p_name
        for prefix in ["中银理财-", "中银理财", "招银理财", "兴银理财"]:
            short_name = short_name.replace(prefix, "")
        short_name = short_name.replace("最短持有期日开", "持有期").replace("固定收益类理财计划", "").replace("固收类理财产品", "")
        if str_width(short_name) > 22:
            while str_width(short_name + "..") > 22 and len(short_name) > 0:
                short_name = short_name[:-1]
            short_name = short_name + ".."

        b_amt = h.get('buy_amount', 0.0)
        r_amt = h.get('redeem_amount', 0.0)
        c_val = h.get('current_value', 0.0)
        p_amt = h.get('total_profit', 0.0)
        ret_rate = h.get('return_rate', 0.0)
        ann_rate = h.get('annualized_rate', 0.0)

        tot_invested += b_amt
        tot_redeemed += r_amt
        tot_cur_val += c_val
        tot_profit += p_amt

        row = [
            str(h.get('id', 1)),
            str(h.get('product_code', '')),
            short_name,
            str(h.get('buy_date', '')),
            str(h.get('earliest_redeem_date', '随时')),
            f"{b_amt:,.0f}",
            f"{r_amt:,.0f}",
            f"{c_val:,.2f}",
            f"{p_amt:+,.2f}",
            f"{ret_rate:+.2f}%",
            f"{ann_rate:.2f}%"
        ]
        print(' '.join(pad_str(val, w, a) for val, w, a in zip(row, widths, aligns)))

    print("-" * 130)
    overall_ret = (tot_profit / tot_invested * 100.0) if tot_invested > 0 else 0.0
    print(f"【资产汇总】: 累计投入本金 ¥{tot_invested:,.2f} | 累计已赎回 ¥{tot_redeemed:,.2f} | 当前总持仓市值 ¥{tot_cur_val:,.2f}")
    print(f"【总利润额】: ¥{tot_profit:+,.2f} 元  | 综合收益率: {overall_ret:+.2f}%")
    print("=" * 128 + "\n")


def print_nav_history_table(code: str, history: List[Dict[str, Any]]):
    """打印产品的每日净值历史明细表"""
    if not history:
        print(f"\n数据库中暂无产品【{code}】的每日净值历史记录。你可以通过 sync 命令同步入库！\n")
        return

    print("\n" + "=" * 88)
    print(f"{'产品【' + code + '】每日净值历史变化流水 (最近 ' + str(len(history)) + ' 条)':^80}")
    print("=" * 88)
    headers = ["净值日期", "单位净值", "累计净值", "万份收益(元)", "七日年化(%)", "数据渠道"]
    widths = [12, 12, 12, 14, 13, 20]
    aligns = ['left', 'right', 'right', 'right', 'right', 'left']
    print(' '.join(pad_str(h, w, a) for h, w, a in zip(headers, widths, aligns)))
    print("-" * 88)

    for r in history:
        unit = f"{r['unit_nav']:.6f}" if r.get('unit_nav') is not None else "-"
        accum = f"{r['accumulated_nav']:.6f}" if r.get('accumulated_nav') is not None else "-"
        ten_th = f"{r['ten_thousand_income']:.4f}" if r.get('ten_thousand_income') is not None else "-"
        sev = f"{r['seven_day_yield']:.4f}%" if r.get('seven_day_yield') is not None else "-"
        chan = r.get('channel') or "官方渠道"

        row = [str(r.get('nav_date', '')), unit, accum, ten_th, sev, chan]
        print(' '.join(pad_str(val, w, a) for val, w, a in zip(row, widths, aligns)))

    print("=" * 88 + "\n")


def interactive_mode():
    mgr = PortfolioManager()
    print("\n" + "=" * 60)
    print("      银行理财持仓记账与收益核算终端")
    print("=" * 60)
    print(" 1. 录入理财产品持仓与赎回记录")
    print(" 2. 查询所有持仓理财产品大盘")
    print(" 3. 查看指定产品每日净值历史")
    print(" 4. 全量同步每日净值到数据库")
    print(" 5. 删除指定持仓记录")
    print(" 6. 清空所有持仓记录")
    print(" 7. 退出")
    print("=" * 60)

    while True:
        try:
            choice = input("\n请选择操作 (1-7): ").strip()
            if choice == "1":
                code = input("1. 请输入理财产品代码 (如 2501251663, 668312D): ").strip()
                if not code:
                    continue
                buy_d = input("2. 请输入购买/确认份额日期 (如 2026-01-28 或 1/28): ").strip()
                buy_a = input("3. 请输入购买金额 (若已知份额可按回车跳过): ").strip()
                buy_s = input("4. 请输入确认份额 (若已输入金额且按1:1可回车): ").strip()
                buy_nav = input("5. 请输入确认买入净值 (直接回车默认自动计算/1.0000): ").strip()
                earliest_d = input("6. 请输入最早可赎回日期 (直接回车默认根据产品规则自动推算): ").strip()
                red_d = input("7. 请输入部分赎回日期 (无赎回请直接回车): ").strip()
                red_a = input("8. 请输入部分赎回金额 (无赎回请直接回车): ").strip()

                print("\n正在获取最新净值并核算收益...")
                rep = mgr.add_position(
                    product_code=code,
                    buy_date_str=buy_d,
                    buy_amount_input=buy_a if buy_a else None,
                    buy_shares_input=buy_s if buy_s else None,
                    buy_nav_input=buy_nav if buy_nav else None,
                    earliest_redeem_date_input=earliest_d if earliest_d else None,
                    redeem_date_str=red_d if red_d else None,
                    redeem_amount_input=red_a if red_a else None,
                )
                print_single_position_report(rep)

            elif choice == "2":
                print("\n正在从数据库加载持仓并同步最新净值...")
                all_h = mgr.list_all_holdings()
                print_portfolio_table(all_h)

            elif choice == "3":
                code = input("请输入理财产品代码 (如 CYQWFXYJX14D2A, 668312D): ").strip()
                if code:
                    limit_str = input("请输入查看天数条数 (默认 30 条，回车即可): ").strip()
                    lim = int(limit_str) if limit_str.isdigit() else 30
                    hist = mgr.get_nav_history(code, limit=lim)
                    print_nav_history_table(code, hist)

            elif choice == "4":
                print("\n正在联网同步所有持仓产品的每日历史净值...")
                stats = mgr.sync_all_nav()
                for c, cnt in stats.items():
                    print(f"  * 产品【{c}】已同步入库 {cnt} 条每日净值流水。")
                print("同步完成！")

            elif choice == "5":
                rec_id = input("请输入要删除的记录 ID: ").strip()
                if rec_id.isdigit():
                    if mgr.delete_position(int(rec_id)):
                        print(f"ID {rec_id} 记录已成功删除。")
                    else:
                        print(f"未找到 ID {rec_id} 的记录。")

            elif choice == "6":
                confirm = input("确定要清空数据库中的所有持仓与历史净值记录吗？(y/n): ").strip().lower()
                if confirm == "y":
                    mgr.clear_all()
                    print("已清空所有持仓与历史记录。")

            elif choice in ["7", "q", "exit", "quit"]:
                print("已退出持仓管理终端。")
                break
        except (KeyboardInterrupt, EOFError):
            print("\n已退出。")
            break


def main():
    parser = argparse.ArgumentParser(description="银行理财持仓与收益管理系统")
    subparsers = parser.add_subparsers(dest="command")

    # add 命令
    add_parser = subparsers.add_parser("add", help="录入理财持仓与赎回记录")
    add_parser.add_argument("--code", required=True, help="产品代码 (如 2501251663, 668312D)")
    add_parser.add_argument("--buy-date", required=True, help="买入/确认份额日期 (如 2026-01-28 或 1/28)")
    add_parser.add_argument("--buy-amount", default=None, help="买入金额 (如 200000 或 20万)")
    add_parser.add_argument("--shares", default=None, help="确认份额 (如 195579.89)")
    add_parser.add_argument("--buy-nav", default=None, help="买入确认净值 (如 1.0226)")
    add_parser.add_argument("--earliest-redeem", default=None, help="最早可赎回日期 (选填，默认自动推算)")
    add_parser.add_argument("--redeem-date", default=None, help="赎回日期 (选填)")
    add_parser.add_argument("--redeem-amount", default=None, help="赎回金额 (选填)")
    add_parser.add_argument("--notes", default="", help="备注 (选填)")

    # list 命令
    subparsers.add_parser("list", help="查看所有持仓理财产品与最新市值收益大盘")

    # sync 命令
    subparsers.add_parser("sync", help="全量同步所有持仓产品的每日历史净值流水到数据库")

    # history 命令
    hist_parser = subparsers.add_parser("history", help="查看指定产品的每日历史净值流水")
    hist_parser.add_argument("--code", required=True, help="产品代码")
    hist_parser.add_argument("--limit", default=30, type=int, help="显示条数 (默认 30)")

    # delete 命令
    del_parser = subparsers.add_parser("delete", help="删除指定 ID 的持仓记录")
    del_parser.add_argument("--id", required=True, type=int, help="记录 ID")

    # clear 命令
    subparsers.add_parser("clear", help="清空所有持仓记录")

    args = parser.parse_args()
    mgr = PortfolioManager()

    if args.command == "add":
        rep = mgr.add_position(
            product_code=args.code,
            buy_date_str=args.buy_date,
            buy_amount_input=args.buy_amount,
            buy_shares_input=args.shares,
            buy_nav_input=args.buy_nav,
            earliest_redeem_date_input=args.earliest_redeem,
            redeem_date_str=args.redeem_date,
            redeem_amount_input=args.redeem_amount,
            notes=args.notes
        )
        print_single_position_report(rep)
    elif args.command == "list":
        all_h = mgr.list_all_holdings()
        print_portfolio_table(all_h)
    elif args.command == "sync":
        print("正在同步所有持仓产品的每日历史净值入库...")
        stats = mgr.sync_all_nav()
        for c, cnt in stats.items():
            print(f"  * 产品【{c}】已入库 {cnt} 条每日净值流水。")
        print("全部同步完成！")
    elif args.command == "history":
        hist = mgr.get_nav_history(args.code, limit=args.limit)
        print_nav_history_table(args.code, hist)
    elif args.command == "delete":
        if mgr.delete_position(args.id):
            print(f"ID {args.id} 记录已成功删除。")
        else:
            print(f"未找到 ID {args.id} 的记录。")
    elif args.command == "clear":
        mgr.clear_all()
        print("已清空所有持仓记录。")
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
