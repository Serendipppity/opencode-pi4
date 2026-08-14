#!/usr/bin/env python3
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

RSS_FEEDS = {
    "BBC": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "Bloomberg": "https://rsshub.cups.moe/bloomberg/bbiz",
    "Zaobao China": "https://rsshub.cups.moe/zaobao/realtime/china",
    "Zaobao World": "https://rsshub.cups.moe/zaobao/znews/world",
    "Caixin China": "https://rsshub.cups.moe/caixin/latest",
    "Wallstreetcn": "https://rsshub.cups.moe/wallstreetcn/live/global/2",
    "NPR US": "https://feeds.npr.org/1001/rss.xml",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml"
}

os.makedirs(ARCHIVE_DIR, exist_ok=True)

def load_prefs():
    try:
        with open(PREFS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {"focus_keywords": [], "ignore_keywords": []}

def fetch_feed(url):
    # RSSHub等服务有时响应较慢，设置了 15 秒超时
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.read().decode('utf-8')
    except Exception as e:
        return ""

def clean_html(raw_html):
    clean = html.unescape(raw_html)
    return re.sub(r'<[^>]+>', '', clean).strip()

def process_feeds():
    prefs = load_prefs()
    focus_words = prefs.get("focus_keywords", [])
    ignore_words = prefs.get("ignore_keywords", [])
    
    today_str = datetime.now().strftime("%Y-%m-%d_%H%M")
    archive_path = os.path.join(ARCHIVE_DIR, f"raw_rss_{today_str}.md")
    
    final_output_for_llm = []
    total_feeds = len(RSS_FEEDS)
    current_feed = 0
    
    with open(archive_path, 'w', encoding='utf-8') as archive_file:
        archive_file.write(f"# RSS 全量底稿 - {today_str}\n\n")
        
        for source_name, url in RSS_FEEDS.items():
            current_feed += 1
            # 增加进度提示，并立刻刷新输出缓冲 (flush=True)
            print(f"[{current_feed}/{total_feeds}] 🔄 正在抓取: {source_name} ...", flush=True)
            
            archive_file.write(f"\n## Source: {source_name}\n")
            xml_content = fetch_feed(url)
            
            if not xml_content:
                print(f"  ❌ {source_name} 抓取失败或超时跳过。", flush=True)
                continue
                
            try:
                root = ET.fromstring(xml_content.lstrip('\ufeff'))
                items = root.findall('.//item')[:15]     #每个源最多提取15条记录
                
                for item in items:
                    title_node = item.find('title')
                    link_node = item.find('link')
                    desc_node = item.find('description')
                    
                    title = title_node.text if title_node is not None and title_node.text else "无标题"
                    link = link_node.text if link_node is not None else ""
                    desc = clean_html(desc_node.text or "") if desc_node is not None else ""
                    
                    # 1. 全量写入底稿
                    archive_file.write(f"### {title}\n{desc}\n🔗 {link}\n\n")
                    
                    # 2. 过滤逻辑
                    content_str = title + desc
                    if any(w in content_str for w in ignore_words):
                        continue 
                        
                    is_focus = any(w in content_str for w in focus_words)
                    prefix = "[⭐高相关] " if is_focus else ""
                    
                    final_output_for_llm.append(f"[{source_name}] {prefix}{title}\n描述: {desc}\n链接: {link}\n")
                
                print(f"  ✅ {source_name} 提取了 {len(items)} 条内容。", flush=True)
            except Exception as e:
                archive_file.write(f"解析失败: {e}\n")
                print(f"  ⚠️ {source_name} 解析失败: {e}", flush=True)
                
            # 休眠逻辑优化：最后一个源抓完就不需要休眠了
            if current_feed < total_feeds:
                print(f"  ⏳ 等待 1秒...\n", flush=True)
                time.sleep(1)

    print("\n" + "="*40)
    print(f"🎉 今日简报材料提取完毕！底稿已存至: \n{archive_path}")
    print("="*40 + "\n")
    
    # 最后将需要给 LLM 的正文打印出来
    print("--- 请基于以下内容生成简报，重点关注带 [⭐高相关] 标记的新闻 ---\n")
    print("\n".join(final_output_for_llm))

if __name__ == "__main__":
    # 为了保证终端输出无延迟
    sys.stdout.reconfigure(line_buffering=True)
    process_feeds()
