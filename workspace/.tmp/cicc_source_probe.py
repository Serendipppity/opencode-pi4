#!/usr/bin/env python3
"""Wechat2RSS 源更新时刻探针（诊断用）：每 10 分钟记录一次 feed 指纹，跑 48h"""
import re
import time
import json
import urllib.request
from datetime import datetime

FEEDS = {
    "中金点睛": "https://wechat2rss.bestblogs.dev/feed/5d4eef298108dd63ce77f40257436e0585bab425.xml",
    "华尔街见闻": None,  # 运行时从 bb.opml 填充
}
LOG = "/home/pi/agent-workspace/.tmp/cicc_source_probe.log"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 Chrome/122.0"}


def load_feeds():
    feeds = dict(FEEDS)
    try:
        opml = open("/tmp/opencode/bb.opml", encoding="utf-8", errors="ignore").read()
        pairs = re.findall(r'title="([^"]+)"[^>]*xmlUrl="([^"]+)"', opml)
        for name in ("华尔街见闻", "财新", "36氪"):
            for t, u in pairs:
                if t == name:
                    feeds[name] = u
    except Exception as e:
        print("opml load err", e)
    return feeds


def probe(name, url):
    try:
        req = urllib.request.Request(url + ("&" if "?" in url else "?") + "cb=" + str(int(time.time())), headers=UA)
        x = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    except Exception as e:
        return {"name": name, "error": str(e)[:80]}
    lb = re.search(r"<lastBuildDate>(.*?)</lastBuildDate>", x)
    pubs = re.findall(r"<pubDate>(.*?)</pubDate>", x)
    titles = [re.sub(r"<[^>]+>", "", t) for t in re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", x, re.S)]
    return {"name": name, "lastBuildDate": lb.group(1) if lb else None,
            "items": x.count("<item>"), "newest_item": titles[1] if len(titles) > 1 else None,
            "item_dates": pubs[:4], "bytes": len(x)}


def main():
    feeds = load_feeds()
    for _ in range(288):  # 48h 后自停
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for name, url in feeds.items():
            if not url:
                continue
            r = probe(name, url)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"probe_at": now, **r}, ensure_ascii=False) + "\n")
        time.sleep(600)
    # 结束摘要
    lines = [json.loads(l) for l in open(LOG, encoding="utf-8")]
    for name in feeds:
        vals = [(x["probe_at"], x.get("lastBuildDate"), x.get("items")) for x in lines if x.get("name") == name]
        changes = [(a, b) for (t1, a, _), (t2, b, _) in zip(vals, vals[1:]) if a != b]
        with open(LOG + ".summary", "a", encoding="utf-8") as f:
            f.write(f"=== {name} 观测 {len(vals)} 次, lastBuild 变化 {len(changes)} 次 ===\n")
            for c in changes:
                f.write(f"  {c[0]} -> {c[1]}\n")


if __name__ == "__main__":
    main()
