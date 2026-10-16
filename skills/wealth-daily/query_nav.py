#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
银行理财日净值查询工具 (支持中国银行、兴业银行自营及其代销理财产品)
支持产品示例：
  - 2501251663 : 天添利现金宝97号G (中行代销 / 浦银理财发售)
  - 9K43077A   : 兴银理财稳添利月盈77号 (兴银理财自营)
  - CYQWF7D22C : 中银理财稳富7天持有期22号 (中银理财自营)
  - HXTT25D    : 中银理财惠享天天25号 (中银理财现金管理类)
"""

import sys
import os
import json
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, Any, List
import requests
from bs4 import BeautifulSoup

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
os.makedirs(CACHE_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


class WealthNavQuery:
    def __init__(self):
        self.headers = HEADERS

    # -------------------------------------------------------------------------
    # 渠道 1: 中国银行 / 中银理财自营接口
    # -------------------------------------------------------------------------
    def query_bocwm(self, code: str) -> Optional[Dict[str, Any]]:
        """从中银理财官方接口查询自营产品最新净值"""
        url = "https://www.bocwm.cn/webApi/cms/productNetWorth/getNetWorthByCode"
        params = {"productCode": code, "pageNo": 1, "pageSize": 1}
        try:
            resp = requests.get(url, params=params, headers=self.headers, timeout=5)
            res = resp.json()
            if res.get("result") and res.get("data"):
                item = res["data"][0]
                # 检查是否有实际有效日期
                if not item.get("releaseDate"):
                    return None

                unit_nav = item.get("shareNetWorth")
                accum_nav = item.get("cumulativeNetWorth")
                ten_thous = item.get("eachTenThousandProfit")
                seven_day = item.get("sevenDayAnnualization")
                reg_code = item.get("registrationCode")
                prod_type = res.get("productType", "")
                prod_name = item.get("productName")

                # 若最新一条记录的 productName 为空，从中银成立记录获取完整产品名称
                if not prod_name and res.get("total"):
                    try:
                        total_cnt = res.get("total")
                        r_name = requests.get(
                            url,
                            params={"productCode": code, "pageNo": total_cnt, "pageSize": 1},
                            headers=self.headers,
                            timeout=3
                        ).json()
                        if r_name.get("data"):
                            first_rec = r_name["data"][0]
                            prod_name = first_rec.get("productName")
                            if not reg_code:
                                reg_code = first_rec.get("registrationCode")
                    except Exception:
                        pass

                return {
                    "code": code,
                    "name": prod_name or f"中银理财产品 ({code})",
                    "channel": "中国银行 / 中银理财自营",
                    "date": item.get("releaseDate"),
                    "unit_nav": unit_nav,
                    "accumulated_nav": accum_nav,
                    "ten_thousand_income": ten_thous,
                    "seven_day_yield": f"{seven_day}%" if seven_day else None,
                    "reg_code": reg_code,
                    "product_type": prod_type,
                }
        except Exception:
            pass
        return None

    # -------------------------------------------------------------------------
    # 渠道 2: 兴业银行 / 兴银理财自营接口
    # -------------------------------------------------------------------------
    def query_cibwm(self, code: str) -> Optional[Dict[str, Any]]:
        """从兴银理财官方接口查询自营产品最新净值 (支持代销前缀如 Y05A9T32005A)"""
        codes_to_try = [code]
        if code.startswith("Y05A") and len(code) > 4:
            codes_to_try.append(code[4:])

        for c in codes_to_try:
            url = f"https://www.cibwm.com.cn/api/public/pc/productVal/netAsset/{c}/1"
            try:
                resp = requests.get(url, headers=self.headers, timeout=5)
                res = resp.json()
                if res.get("status") == 200 and res.get("data"):
                    item = res["data"][-1]  # 最后一条为最新净值
                    raw_dt = item.get("netvalDt", "")
                    nav_date = raw_dt.split(" ")[0] if raw_dt else ""

                    seven_day = item.get("sevenDayAnnualized")
                    seven_day_str = f"{seven_day:.4f}%" if seven_day and seven_day != 0 else None

                    return {
                        "code": code,
                        "name": item.get("productFullName") or f"兴银理财产品 ({code})",
                        "channel": "兴业银行 / 兴银理财自营",
                        "date": nav_date,
                        "unit_nav": f"{item.get('effIopv'):.6f}" if item.get('effIopv') is not None else None,
                        "accumulated_nav": f"{item.get('effTotNetVal'):.6f}" if item.get('effTotNetVal') is not None else None,
                        "ten_thousand_income": None,
                        "seven_day_yield": seven_day_str,
                        "reg_code": "Z7002024001490" if "9T32005" in c else None,
                        "product_type": "净值型",
                    }
            except Exception:
                pass
        return None

    def query_historical_nav(self, code: str, target_date: str) -> Optional[float]:
        """查询指定日期的历史单位净值 (自动查找等于或最接近该交易日的净值)"""
        code = code.strip().upper()
        target = target_date.strip().split()[0].replace("/", "-").replace(".", "-")

        # 1. 尝试中银理财
        url_boc = "https://www.bocwm.cn/webApi/cms/productNetWorth/getNetWorthByCode"
        params_boc = {"productCode": code, "pageNo": 1, "pageSize": 350}
        try:
            resp = requests.get(url_boc, params=params_boc, headers=self.headers, timeout=5)
            res = resp.json()
            if res.get("data"):
                exact = None
                for d in res["data"]:
                    rd = d.get("releaseDate")
                    if rd == target and d.get("shareNetWorth"):
                        return float(d["shareNetWorth"])
                    if rd and rd <= target and d.get("shareNetWorth"):
                        if exact is None or rd > exact[0]:
                            exact = (rd, float(d["shareNetWorth"]))
                if exact:
                    return exact[1]
        except Exception:
            pass

        # 2. 尝试兴银理财 (支持代销前缀如 Y05A)
        codes_to_try = [code]
        if code.startswith("Y05A") and len(code) > 4:
            codes_to_try.append(code[4:])

        for c in codes_to_try:
            url_cib = f"https://www.cibwm.com.cn/api/public/pc/productVal/netAsset/{c}/1"
            try:
                resp = requests.get(url_cib, headers=self.headers, timeout=5)
                res = resp.json()
                if res.get("status") == 200 and res.get("data"):
                    exact = None
                    for d in res["data"]:
                        rd = (d.get("netvalDt") or "").split()[0]
                        if rd == target and d.get("effIopv") is not None:
                            return float(d["effIopv"])
                        if rd and rd <= target and d.get("effIopv") is not None:
                            if exact is None or rd > exact[0]:
                                exact = (rd, float(d["effIopv"]))
                    if exact:
                        return exact[1]
            except Exception:
                pass

        return None

    def query_all_historical_nav(self, code: str) -> List[Dict[str, Any]]:
        """获取理财产品所有可获取的历史日净值时间序列"""
        code = code.strip().upper()
        results = []

        # 1. 尝试中银理财自营 (支持返回完整历史日序列)
        url_boc = "https://www.bocwm.cn/webApi/cms/productNetWorth/getNetWorthByCode"
        try:
            resp = requests.get(url_boc, params={"productCode": code, "pageNo": 1, "pageSize": 500}, headers=self.headers, timeout=8)
            res = resp.json()
            if res.get("data"):
                for d in res["data"]:
                    rd = d.get("releaseDate")
                    if rd and d.get("shareNetWorth"):
                        results.append({
                            "product_code": code,
                            "nav_date": rd,
                            "unit_nav": float(d["shareNetWorth"]),
                            "accumulated_nav": float(d["cumulativeNetWorth"]) if d.get("cumulativeNetWorth") else float(d["shareNetWorth"]),
                            "ten_thousand_income": float(d["eachTenThousandProfit"]) if d.get("eachTenThousandProfit") else None,
                            "seven_day_yield": float(str(d["sevenDayAnnualization"]).replace("%", "")) if d.get("sevenDayAnnualization") else None,
                            "daily_growth": None,
                            "channel": "中国银行 / 中银理财自营"
                        })
                if results:
                    return results
        except Exception:
            pass

        # 2. 尝试兴银理财自营 (支持代销前缀如 Y05A，返回数百天完整历史序列)
        codes_to_try = [code]
        if code.startswith("Y05A") and len(code) > 4:
            codes_to_try.append(code[4:])

        for c in codes_to_try:
            url_cib = f"https://www.cibwm.com.cn/api/public/pc/productVal/netAsset/{c}/1"
            try:
                resp = requests.get(url_cib, headers=self.headers, timeout=8)
                res = resp.json()
                if res.get("status") == 200 and res.get("data"):
                    for d in res["data"]:
                        raw_d = d.get("netvalDt") or ""
                        rd = raw_d.split()[0] if raw_d else ""
                        if rd and d.get("effIopv") is not None:
                            results.append({
                                "product_code": code,
                                "nav_date": rd,
                                "unit_nav": float(d["effIopv"]),
                                "accumulated_nav": float(d["effTotNetVal"]) if d.get("effTotNetVal") is not None else float(d["effIopv"]),
                                "ten_thousand_income": None,
                                "seven_day_yield": float(d["sevenDayAnnualized"]) if d.get("sevenDayAnnualized") else None,
                                "daily_growth": None,
                                "channel": "兴业银行 / 兴银理财自营"
                            })
                    if results:
                        return results
            except Exception:
                pass

        # 3. 兜底获取单日最新快照 (如代销专区)
        single = self.query(code)
        if single and single.get("date") and single.get("unit_nav"):
            results.append({
                "product_code": code,
                "nav_date": single["date"],
                "unit_nav": float(single["unit_nav"]),
                "accumulated_nav": float(single.get("accumulated_nav") or single["unit_nav"]),
                "ten_thousand_income": float(single["ten_thousand_income"]) if single.get("ten_thousand_income") else None,
                "seven_day_yield": float(str(single["seven_day_yield"]).replace("%", "")) if single.get("seven_day_yield") else None,
                "daily_growth": float(str(single["daily_growth"]).replace("%", "")) if single.get("daily_growth") else None,
                "channel": single.get("channel", "银行理财")
            })

        return results

    # -------------------------------------------------------------------------
    # 渠道 3: 中国银行金融市场代销理财专区
    # -------------------------------------------------------------------------
    def _get_boc_agency_cache_file(self) -> str:
        today_str = datetime.now().strftime("%Y%m%d")
        return os.path.join(CACHE_DIR, f"boc_agency_{today_str}.json")

    def _load_boc_agency_cache(self) -> Optional[Dict[str, Dict[str, Any]]]:
        cache_file = self._get_boc_agency_cache_file()
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def _save_boc_agency_cache(self, data: Dict[str, Dict[str, Any]]):
        cache_file = self._get_boc_agency_cache_file()
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def query_boc_agency(self, code: str) -> Optional[Dict[str, Any]]:
        """从中国银行代销理财产品专区查询"""
        # 1. 尝试从本地今日缓存读取
        cache = self._load_boc_agency_cache()
        if cache and code in cache:
            return cache[code]

        # 2. 若未缓存或未命中，进行并发扫描检索
        # 中国银行代销专区每页50条，约194页。
        # 很多活跃代销产品在前15页，先快速检索前 20 页；若无再检索剩余页
        found_item = self._scan_boc_agency_pages(code, max_pages=194)
        if found_item:
            # 记录到缓存
            if not cache:
                cache = {}
            cache[code] = found_item
            self._save_boc_agency_cache(cache)
            return found_item
        return None

    def _parse_boc_agency_page(self, p: int) -> list:
        url = (
            f"https://www.bankofchina.com/sourcedb/srfd6_2024/index_{p}.html"
            if p > 0
            else "https://www.bankofchina.com/sourcedb/srfd6_2024/index.html"
        )
        try:
            resp = requests.get(url, headers=self.headers, timeout=4)
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")
            table = soup.find("table")
            if not table:
                return []
            rows = table.find_all("tr")[1:]
            items = []
            for r in rows:
                cols = [td.text.strip() for td in r.find_all(["td", "th"])]
                if len(cols) >= 8:
                    items.append({
                        "code": cols[0],
                        "name": cols[1],
                        "unit_nav": cols[2],
                        "accumulated_nav": cols[3],
                        "ten_thousand_income": cols[4] if cols[4] else None,
                        "seven_day_yield": f"{cols[5]}%" if cols[5] else None,
                        "daily_growth": cols[6] if cols[6] else None,
                        "date": cols[7].split(" ")[0].replace("/", "-"),
                        "channel": "中国银行代销专区",
                    })
            return items
        except Exception:
            return []

    def _scan_boc_agency_pages(self, code: str, max_pages: int = 194) -> Optional[Dict[str, Any]]:
        # 先搜前 20 页（绝大多数热门代销产品在此区间，响应极快）
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_page = {executor.submit(self._parse_boc_agency_page, p): p for p in range(20)}
            for future in as_completed(future_to_page):
                items = future.result()
                for item in items:
                    if item["code"].upper() == code.upper():
                        return item

        # 如果前20页没有，继续搜第21页至max_pages
        with ThreadPoolExecutor(max_workers=15) as executor:
            future_to_page = {executor.submit(self._parse_boc_agency_page, p): p for p in range(20, max_pages)}
            for future in as_completed(future_to_page):
                items = future.result()
                for item in items:
                    if item["code"].upper() == code.upper():
                        return item

        return None

    # -------------------------------------------------------------------------
    # 统一调度查询
    # -------------------------------------------------------------------------
    def query(self, code: str) -> Optional[Dict[str, Any]]:
        clean_code = code.strip().upper()
        if not clean_code:
            return None

        # 1. 尝试中银理财自营
        res = self.query_bocwm(clean_code)
        if res:
            return res

        # 2. 尝试兴银理财自营
        res = self.query_cibwm(clean_code)
        if res:
            return res

        # 3. 尝试中国银行代销理财
        res = self.query_boc_agency(clean_code)
        if res:
            return res

        return None


def format_and_print_result(res: Dict[str, Any]):
    print("=" * 60)
    print(f"【产品代码】: {res.get('code')}")
    print(f"【产品名称】: {res.get('name')}")
    print(f"【数据渠道】: {res.get('channel')}")
    print(f"【最新日期】: {res.get('date')}")
    
    unit_nav = res.get('unit_nav')
    accum_nav = res.get('accumulated_nav')
    ten_thous = res.get('ten_thousand_income')
    seven_day = res.get('seven_day_yield')

    # 判断是否为现金管理类
    is_cash_mgmt = (unit_nav == "1.0000" or unit_nav == 1.0) and (ten_thous or seven_day)

    if is_cash_mgmt:
        print(f"【产品类型】: 现金管理类 (单位净值恒为 1.0000)")
        print(f"【单位净值】: {unit_nav}")
        print(f"【累计净值】: {accum_nav}")
        if ten_thous:
            print(f"【每万份收益】: {ten_thous} 元")
        if seven_day:
            print(f"【七日年化收益】: {seven_day}")
    else:
        print(f"【单位净值】: {unit_nav if unit_nav else '--'}")
        print(f"【累计净值】: {accum_nav if accum_nav else '--'}")
        if seven_day:
            print(f"【年化/增长率】: {seven_day}")
        if ten_thous:
            print(f"【每万份收益】: {ten_thous} 元")

    if res.get('reg_code'):
        print(f"【全国登记编码】: {res.get('reg_code')}")
    print("=" * 60)


def main():
    manager = WealthNavQuery()

    # 1. 命令行直接带参数：python query_nav.py 2501251663 [CYQWF7D22C ...]
    if len(sys.argv) > 1:
        codes = sys.argv[1:]
        for code in codes:
            print(f"\n正在查询理财产品代码: {code} ...")
            t0 = time.time()
            res = manager.query(code)
            elapsed = time.time() - t0
            if res:
                format_and_print_result(res)
                print(f"(查询耗时: {elapsed:.2f} 秒)\n")
            else:
                print(f"❌ 未查询到代码【{code}】的最新净值，请检查代码是否正确。\n")
        return

    # 2. 交互式查询循环
    print("\n" + "=" * 60)
    print("  银行理财日净值查询终端 (支持中行/兴业自营及代销产品)")
    print("  常用示例: 2501251663 (中行代销), 9K43077A (兴银理财), CYQWF7D22C (中银理财)")
    print("  输入 q 或 exit 退出")
    print("=" * 60 + "\n")

    while True:
        try:
            user_input = input("请输入理财产品代码: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["q", "exit", "quit"]:
                print("退出查询。")
                break

            print(f"正在查询【{user_input}】最新净值...")
            t0 = time.time()
            res = manager.query(user_input)
            elapsed = time.time() - t0

            if res:
                format_and_print_result(res)
                print(f"(查询耗时: {elapsed:.2f} 秒)\n")
            else:
                print(f"❌ 未查询到代码【{user_input}】的最新净值，请检查代码输入是否正确。\n")
        except (KeyboardInterrupt, EOFError):
            print("\n已退出。")
            break


if __name__ == "__main__":
    main()
