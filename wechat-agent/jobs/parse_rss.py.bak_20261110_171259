#!/usr/bin/env python3
"""RSS 统一抓料器：8 源导入 → 偏好标记（ignore/⭐/去重）→ 全量留底 raw_rss_*.md → stdout 输出可推送材料

底稿 STATUS 标记说明（只标记不删除，全量留痕）：
  ⭐focus          命中 user_prefs focus_keywords
  ok              常规可推送
  🚫ignored(词)    命中 ignore_keywords
  ↺pushed         链接已推送过（seen_links.json）
"""
import sys
import json
import time
import os
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
import re
import html

# --- 配置区域 ---
WORKSPACE_DIR = "/home/pi/agent-workspace"
ARCHIVE_DIR = os.path.join(WORKSPACE_DIR, "outbox_obsidian/news_archives")
PREFS_FILE = os.path.join(WORKSPACE_DIR, "user_prefs.json")
SEEN_FILE = os.path.join(WORKSPACE_DIR, "seen_links.json")

# 直连官方 RSS 源
RSS_FEEDS = {
    "BBC": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "NPR US": "https://feeds.npr.org/1001/rss.xml",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
}

# RSSHub 源：3 镜像依序容灾，任一实例有内容即采用
RSSHUB_INSTANCES = [
    "https://rsshub.cups.moe",
    "https://rsshub.rssforever.com",
    "https://rsshub.woodland.cafe",
]
RSSHUB_FEEDS = [
    ("Bloomberg", "/bloomberg"),
    ("Zaobao China", "/zaobao/realtime/china"),
    ("Zaobao World", "/zaobao/realtime/world"),
    ("Caixin China", "/caixin/latest"),
]

# 华尔街见闻走官方 JSON API（不走 RSS）
WALLSTCN_API = "https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=20"

STATUS_FOCUS = "⭐focus"
STATUS_OK = "ok"

os.makedirs(ARCHIVE_DIR, exist_ok=True)

def load_prefs():
    try:
        with open(PREFS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {"focus_keywords": [], "ignore_keywords": []}

def load_seen_links():
    """已推送成功的链接集合（跨天累积）。推送成功后由 news_brief.py 写入。"""
    try:
        with open(SEEN_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return {l.strip() for links in data.values() for l in links}
    except Exception:
        return set()

def fetch_url(url, timeout=15):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode('utf-8', 'ignore')
    except Exception:
        return ""

def parse_xml(xml_content):
    if not xml_content:
        return None
    try:
        return ET.fromstring(xml_content.lstrip('\ufeff'))
    except Exception:
        return None

def fetch_rsshub(path):
    """RSSHub 多镜像依序容灾"""
    for inst in RSSHUB_INSTANCES:
        root = parse_xml(fetch_url(inst + path))
        if root is not None and len(root.findall('.//item')) > 0:
            return root
    return None

def clean_html(raw_html):
    clean = html.unescape(raw_html or "")
    return re.sub(r'<[^>]+>', '', clean).strip()

def one_line(text):
    """压平为单行，保证底稿条目块结构稳定可解析"""
    return re.sub(r'\s+', ' ', text).strip()

def extract_items(root, limit=15):
    items = []
    for item in root.findall('.//item')[:limit]:
        title_node = item.find('title')
        link_node = item.find('link')
        desc_node = item.find('description')
        title = one_line(title_node.text) if title_node is not None and title_node.text else "无标题"
        link = link_node.text.strip() if link_node is not None and link_node.text else ""
        desc = one_line(clean_html(desc_node.text)) if desc_node is not None else ""
        items.append((title, desc, link))
    return items

def fetch_wallstreetcn(limit=15):
    """华尔街见闻官方 JSON API → (title, desc, link) 列表"""
    items = []
    try:
        js = json.loads(fetch_url(WALLSTCN_API))
        for item in js.get('data', {}).get('items', [])[:limit]:
            title = one_line(item.get('title') or '')
            content = one_line(clean_html(item.get('content_text') or item.get('content') or ''))
            link = item.get('uri') or ''
            if link and not link.startswith('http'):
                link = 'https://wallstreetcn.com' + link
            if title:
                items.append((title, content, link))
    except Exception:
        pass
    return items

def collect_source(kind, locator):
    """按通道抓取单个源，返回 (title, desc, link) 列表"""
    if kind == 'rss':
        root = parse_xml(fetch_url(locator))
        return extract_items(root) if root is not None else []
    if kind == 'rsshub':
        root = fetch_rsshub(locator)
        return extract_items(root) if root is not None else []
    if kind == 'api':
        return fetch_wallstreetcn()
    return []

def classify(content_str, link, ignore_words, focus_words, seen_links):
    """返回 (是否进 LLM 材料, STATUS 标记)。只标记不删除，底稿全量留痕。"""
    hit_ignore = next((w for w in ignore_words if w in content_str), None)
    if hit_ignore:
        return False, f"🚫ignored({hit_ignore})"
    if link and link in seen_links:
        return False, "↺pushed"
    if any(w in content_str for w in focus_words):
        return True, STATUS_FOCUS
    return True, STATUS_OK

def process_feeds(archive_path, stamp):
    prefs = load_prefs()
    focus_words = prefs.get("focus_keywords", [])
    ignore_words = prefs.get("ignore_keywords", [])
    seen_links = load_seen_links()

    sources = [(name, 'rss', url) for name, url in RSS_FEEDS.items()]
    sources += [(name, 'rsshub', path) for name, path in RSSHUB_FEEDS]
    sources += [("Wallstreetcn", 'api', WALLSTCN_API)]

    total = len(sources)
    llm_material = []

    with open(archive_path, 'w', encoding='utf-8') as archive_file:
        archive_file.write(f"# RSS 全量底稿 - {stamp}\n")

        for current_feed, (source_name, kind, locator) in enumerate(sources, 1):
            print(f"[{current_feed}/{total}] 🔄 正在抓取: {source_name} ...", flush=True)
            archive_file.write(f"\n## Source: {source_name}\n")

            entries = collect_source(kind, locator)
            if not entries:
                print(f"  ❌ {source_name} 抓取失败或超时跳过。", flush=True)
                continue

            kept = 0
            for title, desc, link in entries:
                keep, status = classify(title + desc, link.strip(), ignore_words, focus_words, seen_links)
                archive_file.write(f"### {title}\n{desc}\n🔗 {link}\nSTATUS: {status}\n\n")
                if keep:
                    prefix = "[⭐高相关] " if status == STATUS_FOCUS else ""
                    llm_material.append(f"[{source_name}] {prefix}{title}\n描述: {desc}\n链接: {link}\n")
                    kept += 1

            print(f"  ✅ {source_name} 共 {len(entries)} 条，入材料 {kept} 条。", flush=True)
            if current_feed < total:
                print(f"  ⏳ 等待 1秒...\n", flush=True)
                time.sleep(1)

    print("\n" + "=" * 40)
    print(f"🎉 今日简报材料提取完毕！底稿已存至: \n{archive_path}")
    print("=" * 40 + "\n")
    print("[ARCHIVE] " + archive_path)
    print("--- 请基于以下内容生成简报，重点关注带 [⭐高相关] 标记的新闻 ---\n")
    print("\n".join(llm_material))

if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    args = sys.argv[1:]
    out_path = None
    if '--out' in args:
        idx = args.index('--out')
        if idx + 1 < len(args):
            out_path = args[idx + 1]
    if not out_path:
        out_path = os.path.join(ARCHIVE_DIR, f"raw_rss_{datetime.now().strftime('%Y-%m-%d_%H%M')}.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    process_feeds(out_path, datetime.now().strftime("%Y-%m-%d_%H%M"))
