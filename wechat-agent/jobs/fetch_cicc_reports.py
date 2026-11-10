#!/home/pi/agent-venv/bin/python3
# -*- coding: utf-8 -*-
"""研究源（8 源）归档 + 清单推送（cron 每天 08:30 / 20:30）

数据源（Wechat2RSS 公共实例 BestBlogs）：
    中金点睛            mode=keyword  标题命中关键词 → 自动抓全文归档
    远川研究所/饭统戴老板/CF40/晚点对话/晚点再听LaterCast/硅谷科技评论/硅基观察Pro
                        mode=manual   不自动归档，只进清单；回「下载 N」才抓全文
产出：  ~/agent-workspace/outbox_obsidian/reports_中金/
        articles/<公众号>/YYYY-MM-DD_标题.md   归档正文（中金关键词命中 / 手动下载）
        images/<公众号>/YYYY-MM-DD_标题/figNN.jpg 归档图片
        index.md                              全部清单条目（新→旧，公众号+日期+标题+链接）
        .state/keywords.txt                   中金关键词表（仅对中金生效）
        .state/seen_ids.txt                   已归档文章 id（按 公众号:id 去重）
        .state/last_list.json                 最近一次合并清单（序号→公众号/标题/链接…）
推送：  每轮只把「本轮新增」条目清单发到 Discord research 窗口；无新增不推送。

命令行（Discord 回复「下载 3」「加南向」等由 agent 调用本脚本）：
    fetch_cicc_reports.py                 cron 主流程：拉 8 源 → 中金自动归档 → 推新增清单
    fetch_cicc_reports.py list            重发当前全量清单到 Discord
    fetch_cicc_reports.py dl <序号>       下载清单里第 N 篇（跨源连续编号）
    fetch_cicc_reports.py dl <关键词>      下载标题含该关键词的全部文章
    fetch_cicc_reports.py kw              查看中金关键词
    fetch_cicc_reports.py kw +<词>        加中金关键词
    fetch_cicc_reports.py kw -<词>        减中金关键词
"""
import fcntl
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

FEED_BASE = "https://wechat2rss.bestblogs.dev/feed/"
# 8 个研究源；mode=keyword 仅中金（关键词自动归档），mode=manual 仅进清单、手动下载
FEEDS = {
    "中金点睛":            {"id": "5d4eef298108dd63ce77f40257436e0585bab425", "mode": "keyword"},
    "远川研究所":          {"id": "fae262a71b2c0f867011d3c40e02bff3272d90df", "mode": "manual"},
    "饭统戴老板":          {"id": "5f4c620560bd63023df9fb7d330aeee524e41676", "mode": "manual"},
    "中国金融四十人论坛":  {"id": "effdfffc5993e7260f3766aaafafc5536b685a54", "mode": "manual"},
    "晚点对话":            {"id": "7d94425ba74a9342a26b19cade3dcf4208038a43", "mode": "manual"},
    "晚点再听LaterCast":   {"id": "1193affe8f8ed7a64281054cb022a7176054fa38", "mode": "manual"},
    "硅谷科技评论":        {"id": "4515ee058133ff68570ad586abdd81f54f2b6ee3", "mode": "manual"},
    "硅基观察Pro":         {"id": "f21c3e34df9b5fecfda57e2e53512864255ed4cd", "mode": "manual"},
}

BASE_DIR = os.path.expanduser("~/agent-workspace/outbox_obsidian/reports_中金")
ART_DIR = os.path.join(BASE_DIR, "articles")
IMG_DIR = os.path.join(BASE_DIR, "images")
INDEX_FILE = os.path.join(BASE_DIR, "index.md")
STATE_DIR = os.path.join(BASE_DIR, ".state")
KEYWORDS_FILE = os.path.join(STATE_DIR, "keywords.txt")
SEEN_FILE = os.path.join(STATE_DIR, "seen_ids.txt")
LIST_FILE = os.path.join(STATE_DIR, "last_list.json")
LOCK_PATH = os.path.expanduser("~/.tmp/cicc_fetch.lock")
DISCORD_CONFIG = os.path.expanduser("~/.config/opencode/discord-channel.json")
# 推送频道：默认 research（kimaki 已接管，回复可回到 agent）；可用环境变量覆盖
DISCORD_CHANNEL = os.environ.get("CICC_DISCORD_CHANNEL", "1484391479479898122")

# 关键词仅对中金生效
DEFAULT_KEYWORDS = ["资金流", "EPFR", "外资", "港股", "筹码", "南向"]
TAG_KEYWORDS = ["陆股通", "北向", "ETF", "降息", "南向资金"]

UA = "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "*/*"}
CST = timezone(timedelta(hours=8))
MAX_IMG_WORKERS = 4
FETCH_TIMEOUT = 30
FETCH_RETRY = 3
DISCORD_CHUNK = 1800


def log(msg):
    print(f"[{datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- 状态读写
def load_keywords():
    if os.path.exists(KEYWORDS_FILE):
        kws = [l.strip() for l in open(KEYWORDS_FILE, encoding="utf-8") if l.strip()]
        if kws:
            return kws
    return list(DEFAULT_KEYWORDS)


def save_keywords(kws):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(KEYWORDS_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(kws) + "\n")


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return set()
    return {l.strip() for l in open(SEEN_FILE, encoding="utf-8") if l.strip()}


def add_seen(feed_name, aid):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(SEEN_FILE, "a", encoding="utf-8") as f:
        f.write(f"{feed_name}:{aid}\n")


def is_seen(seen, feed_name, aid):
    # 兼容旧版无前缀的中金 id
    return f"{feed_name}:{aid}" in seen or aid in seen


# ---------------------------------------------------------------- 网络
def fetch(url, timeout=FETCH_TIMEOUT, retries=FETCH_RETRY):
    last_err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), r.headers.get("Content-Type", "")
        except Exception as e:
            last_err = e
            if i < retries - 1:
                wait = 3 * (i + 1)
                log(f"WARN 请求失败({e})，{wait}s 后重试 {i+2}/{retries}")
                time.sleep(wait)
    raise last_err


def push_discord(text):
    """推送到 Discord 桥频道；超长自动分段"""
    cfg = json.load(open(DISCORD_CONFIG, encoding="utf-8"))
    token = cfg["botToken"]
    url = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL}/messages"
    chunks = []
    while text:
        if len(text) <= DISCORD_CHUNK:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, DISCORD_CHUNK)
        if cut < 200:
            cut = DISCORD_CHUNK
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    for c in chunks:
        payload = json.dumps({"content": c}).encode("utf-8")
        for attempt in range(5):
            try:
                req = urllib.request.Request(url, data=payload, headers={
                    "Authorization": f"Bot {token}", "Content-Type": "application/json",
                    "User-Agent": "DiscordBot (https://opencode.ai, 1.0)"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    r.read()
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(float(json.loads(e.read()).get("retry_after", 5)))
                    continue
                log(f"WARN Discord 推送失败 {e}")
                time.sleep(2 ** attempt)
            except Exception as e:
                log(f"WARN Discord 推送失败 {e}")
                time.sleep(2 ** attempt)
    return len(chunks)


# ---------------------------------------------------------------- 解析
def parse_feed(raw):
    xml = raw.decode("utf-8", "ignore")
    ch = re.search(r"<channel>(.*?)</channel>", xml, re.S)
    ch = ch.group(1) if ch else xml
    lb = re.search(r"<lastBuildDate>(.*?)</lastBuildDate>", ch)
    ft = re.search(r"<title>(.*?)</title>", ch)
    items = []
    for it in re.findall(r"<item>(.*?)</item>", ch, re.S):
        t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, re.S)
        d = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S)
        l = re.search(r"<link>(.*?)</link>", it, re.S)
        c = re.search(r"<content:encoded>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</content:encoded>", it, re.S)
        if not (t and d and l):
            continue
        body = html.unescape(c.group(1)) if c else ""
        text = body_to_text(body)
        items.append({
            "title": html.unescape(re.sub(r"<[^>]+>", "", t.group(1))).strip(),
            "pub_raw": d.group(1).strip(),
            "url": html.unescape(l.group(1).strip()),
            "body": body,
            "text": text,
            "chars": len(text),
            "img_count": len(img_tags(body)),
        })
    return {
        "feed_title": html.unescape(re.sub(r"<[^>]+>", "", ft.group(1))).strip() if ft else "",
        "last_build_date": lb.group(1).strip() if lb else None,
        "items": items,
    }


def pub_dt(pub_raw):
    try:
        dt = parsedate_to_datetime(pub_raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CST)
        return dt.astimezone(CST)
    except Exception:
        return datetime.now(CST)


def article_id(url):
    q = re.search(r"[?&]mid=(\d+).*?[?&]idx=(\d+)", url)
    if q:
        return f"{q.group(1)}_{q.group(2)}"
    q = re.search(r"[?&]mid=(\d+)", url)
    if q:
        return q.group(1)
    m = re.search(r"sn=([0-9a-f]+)", url)
    return m.group(1) if m else url


def slugify(title, limit=60):
    s = re.sub(r"[^\w一-鿿]+", "-", title).strip("-")
    return s[:limit].strip("-") or "untitled"


def body_to_text(body_html):
    s = re.sub(r"<img[^>]*\ssrc=\"([^\"]+)\"[^>]*>", r"![](\1)", body_html)
    s = re.sub(r"<script.*?</script>", " ", s, flags=re.S)
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.S)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(p|div|section|li|h[1-6])>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def img_tags(body_html):
    return list(re.finditer(r'(<img[^>]*\ssrc=")([^"]+)"', body_html))


# ---------------------------------------------------------------- 归档
def localize_images(body_html, feed_name, art_key):
    tags = img_tags(body_html)
    if not tags:
        return body_html, []
    dst_dir = os.path.join(IMG_DIR, feed_name, art_key)
    os.makedirs(dst_dir, exist_ok=True)

    def dl(pair):
        idx, url = pair
        try:
            data, ctype = fetch(url, timeout=40)
            ext = {"image/jpeg": ".jpg", "image/gif": ".gif", "image/png": ".png",
                   "image/webp": ".webp"}.get((ctype or "").split(";")[0].strip().lower(), ".jpg")
            fn = f"fig{idx:02d}{ext}"
            with open(os.path.join(dst_dir, fn), "wb") as f:
                f.write(data)
            return idx, fn, len(data)
        except Exception as e:
            return idx, None, str(e)

    with ThreadPoolExecutor(max_workers=MAX_IMG_WORKERS) as ex:
        results = list(ex.map(dl, [(i + 1, m.group(2)) for i, m in enumerate(tags)]))
    mapping, saved = {}, []
    for idx, fn, info in results:
        if fn:
            mapping[idx] = f"images/{feed_name}/{art_key}/{fn}"
            saved.append(mapping[idx])
        else:
            log(f"WARN 图片下载失败 fig{idx:02d}: {info}")
    out, last = [], 0
    for i, m in enumerate(tags):
        out.append(body_html[last:m.start()])
        out.append(f'{m.group(1)}{mapping.get(i + 1, m.group(2))}"')
        last = m.end()
    out.append(body_html[last:])
    return "".join(out), saved


def art_exists(feed_name, date_s, title):
    name = f"{date_s}_{slugify(title)}.md"
    return (os.path.exists(os.path.join(ART_DIR, feed_name, name))
            or os.path.exists(os.path.join(ART_DIR, name)))


def archive_article(item, feed_name):
    """下载并归档单篇，返回 (md路径, 图片数, 命中关键词)"""
    dt = pub_dt(item["pub_raw"])
    date_s = dt.strftime("%Y-%m-%d")
    art_key = f"{date_s}_{slugify(item['title'])}"
    body_html, images = localize_images(item["body"], feed_name, art_key)
    text = body_to_text(body_html)
    kws = [k for k in TAG_KEYWORDS if k.lower() in (item["title"] + text).lower()]
    md = [
        f"# {item['title']}", "",
        f"- **公众号**: {feed_name}",
        f"- **发布时间**: {dt.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **原文链接**: {item['url']}",
        f"- **抓取时间**: {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **正文长度**: {len(text)} 字 | **图片**: {len(images)} 张（已本地化）",
        f"- **关键词命中**: {'、'.join(kws) if kws else '无'}",
        "", "---", "", text, "",
    ]
    dst_dir = os.path.join(ART_DIR, feed_name)
    os.makedirs(dst_dir, exist_ok=True)
    md_path = os.path.join(dst_dir, art_key + ".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    add_seen(feed_name, article_id(item["url"]))
    return md_path, len(images), kws


# ---------------------------------------------------------------- 索引
_INDEX_URL_RE = re.compile(r"https?://\S+\s*$")


def read_index():
    """返回 (现有行列表, 已收录 url 集合)"""
    if not os.path.exists(INDEX_FILE):
        return [], set()
    lines = [l.rstrip("\n") for l in open(INDEX_FILE, encoding="utf-8")]
    urls = set()
    for l in lines:
        m = _INDEX_URL_RE.search(l)
        if m:
            urls.add(m.group(0).strip())
    return lines, urls


def append_index(rows):
    """把新条目按日期倒序插到索引顶部，返回新增条数（按 url 去重）"""
    lines, urls = read_index()
    new = []
    for r in sorted(rows, key=lambda x: x["date"], reverse=True):
        u = r["url"].strip()
        if not u or u in urls:
            continue
        new.append(f"- {r['date'][:10]} | {r['feed']} | {r['title']} | {u}")
        urls.add(u)
    if not new:
        return 0
    old = [l for l in lines if l.startswith("- ")]
    header = "# 研究源文章索引（新→旧）\n\n"
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(new + old) + "\n")
    return len(new)


# ---------------------------------------------------------------- 清单
def collect_feeds():
    feeds = {}
    for name, cfg in FEEDS.items():
        url = FEED_BASE + cfg["id"] + ".xml"
        try:
            raw, _ = fetch(url)
            feed = parse_feed(raw)
            feeds[name] = feed
            log(f"FETCH {name}: {len(feed['items'])} 篇")
        except Exception as e:
            log(f"WARN {name} 抓取失败: {e}")
    return feeds


def build_rows(feeds, keywords):
    rows = []
    for name, feed in feeds.items():
        mode = FEEDS[name]["mode"]
        for it in feed["items"]:
            dt = pub_dt(it["pub_raw"])
            hit = [k for k in keywords if k.lower() in it["title"].lower()] if mode == "keyword" else []
            rows.append({
                "feed": name, "mode": mode,
                "title": it["title"], "url": it["url"],
                "date": dt.strftime("%Y-%m-%d %H:%M"),
                "chars": it["chars"], "img_count": it["img_count"],
                "hit": hit, "id": article_id(it["url"]),
            })
    rows.sort(key=lambda r: r["date"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["no"] = i
    return rows


def list_text(rows, keywords, auto_archived, title="研究源 · 文章清单"):
    head = (f"📑 **{title}** {datetime.now(CST).strftime('%Y-%m-%d %H:%M')}\n"
            f"源: 中金点睛(关键词自动归档) + 7 源(手动下载) | 本轮 {len(rows)} 篇\n"
            f"中金关键词: {'、'.join(keywords)}\n")
    if auto_archived:
        head += f"✅ 中金关键词自动归档: {'、'.join(auto_archived)}\n"
    body = []
    for r in rows:
        mark = "✅" if r["hit"] else "⬜"
        kw = f" | {'、'.join(r['hit'])}" if r["hit"] else ""
        body.append(f"{mark} **{r['no']}**. [{r['feed']}] {r['title']}\n"
                    f"    {r['date']} · {r['chars']:,} 字 · {r['img_count']} 图{kw}\n"
                    f"    {r['url']}")
    foot = ("\n💡 回复即可操作：`下载 3`（按序号）｜`下载 关键词`（按标题）｜"
            "`加南向`/`减港股`（改中金关键词）｜`清单`（重发全量）")
    arch = recent_archived(5)
    if arch:
        foot += "\n\n📚 已归档（最近 %d 篇）:\n" % len(arch) + "\n".join(f"· {a}" for a in arch)
    return head + "\n" + "\n".join(body) + foot


def recent_archived(n=5):
    """已归档的最近 n 篇（标题 + 日期），用于清单附注"""
    if not os.path.isdir(ART_DIR):
        return []
    files = []
    for root, _dirs, fs in os.walk(ART_DIR):
        for f in fs:
            if f.endswith(".md"):
                files.append(os.path.join(root, f))
    files.sort(reverse=True)
    out = []
    for p in files[:n]:
        base = os.path.basename(p)[:-3]
        out.append(f"{base[:10]} {base[11:][:40]}")
    return out


# ---------------------------------------------------------------- 命令
def cmd_list():
    feeds = collect_feeds()
    kws = load_keywords()
    rows = build_rows(feeds, kws)
    save_list(rows)
    n = push_discord(list_text(rows, kws, []))
    log(f"LIST  已重发全量清单 {len(rows)} 篇（{n} 条消息）")


def cmd_dl(arg):
    arg = arg.strip()
    if not arg:
        print("用法: dl <序号|标题关键词>")
        return 1
    feeds = collect_feeds()
    kws = load_keywords()
    rows = build_rows(feeds, kws)
    save_list(rows)
    targets = []
    if arg.isdigit():
        n = int(arg)
        if 1 <= n <= len(rows):
            targets = [rows[n - 1]]
    if not targets:
        targets = [r for r in rows if arg.lower() in r["title"].lower()]
    if not targets:
        print(f"未找到: {arg}")
        return 1
    done = []
    for r in targets:
        feed = feeds.get(r["feed"])
        item = next((i for i in feed["items"] if article_id(i["url"]) == r["id"]), None) if feed else None
        if not item:
            continue
        exists = os.path.join(ART_DIR, r["feed"], f"{r['date'][:10]}_{slugify(r['title'])}.md")
        if os.path.exists(exists):
            done.append((r, "-", os.path.basename(exists)))
            continue
        md, nimg, _ = archive_article(item, r["feed"])
        done.append((r, nimg, os.path.basename(md)))
    for r, nimg, name in done:
        print(f"已归档 #{r['no']} [{r['feed']}] {r['title'][:40]} → {name}（{nimg} 图）")
    push_discord("✅ 已按要求下载:\n" + "\n".join(
        f"· **{r['no']}** [{r['feed']}] {r['title'][:36]} → `{name}`（{nimg} 图）" for r, nimg, name in done))
    return 0


def cmd_kw(arg):
    kws = load_keywords()
    arg = arg.strip()
    if not arg:
        print("当前关键词(仅中金): " + "、".join(kws))
        push_discord("当前关键词(仅中金): " + "、".join(kws))
        return 0
    op = "-" if arg[0] == "-" else "+"
    word = arg[1:].strip() if arg[0] in "+-" else arg.strip()
    if not word:
        print("用法: kw +词 / kw -词")
        return 1
    if op == "+":
        if word in kws:
            msg = f"关键词已存在: {word}"
        else:
            kws.append(word)
            save_keywords(kws)
            msg = f"✅ 已加关键词: {word}\n当前: " + "、".join(kws)
    else:
        if word not in kws:
            msg = f"关键词不存在: {word}"
        else:
            kws.remove(word)
            save_keywords(kws)
            msg = f"✅ 已减关键词: {word}\n当前: " + "、".join(kws)
    print(msg)
    push_discord(msg)
    return 0


# ---------------------------------------------------------------- 主流程
def save_list(rows):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(LIST_FILE, "w", encoding="utf-8") as f:
        json.dump({"saved_at": datetime.now(CST).isoformat(timespec="seconds"),
                   "count": len(rows), "articles": rows},
                  f, ensure_ascii=False, indent=2)


def cron():
    os.makedirs(ART_DIR, exist_ok=True)
    os.makedirs(IMG_DIR, exist_ok=True)
    os.makedirs(STATE_DIR, exist_ok=True)
    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("SKIP 已有实例在运行，本次退出")
        return 0

    keywords = load_keywords()
    if not os.path.exists(KEYWORDS_FILE):
        save_keywords(keywords)
    log(f"START 中金关键词: {'、'.join(keywords)}")

    feeds = collect_feeds()
    if not feeds:
        log("ERROR 所有源抓取失败，退出")
        return 1
    rows = build_rows(feeds, keywords)
    save_list(rows)
    _, indexed = read_index()
    new_rows = [r for r in rows if r["url"].strip() not in indexed]
    log(f"WINDOW 全量 {len(rows)} 篇，本轮新增 {len(new_rows)} 篇")

    seen = load_seen()
    auto = []
    for r in new_rows:
        if r["mode"] != "keyword" or not r["hit"]:
            continue
        if is_seen(seen, r["feed"], r["id"]) or art_exists(r["feed"], r["date"][:10], r["title"]):
            continue
        feed = feeds.get(r["feed"])
        item = next((i for i in feed["items"] if article_id(i["url"]) == r["id"]), None) if feed else None
        if not item:
            continue
        md, nimg, _ = archive_article(item, r["feed"])
        auto.append(f"#{r['no']}")
        log(f"NEW   {r['title'][:36]:<38} {r['chars']:>6} 字 图 {nimg}")

    if new_rows:
        n = push_discord(list_text(new_rows, keywords, auto))
        log(f"PUSH  新增清单 {len(new_rows)} 篇（{n} 条消息），中金自动归档 {len(auto)} 篇")
    else:
        log("SKIP  无新增，不推送")
    n_add = append_index(new_rows)
    log(f"INDEX +{n_add} 条（{INDEX_FILE}）")
    return 0


def main():
    if len(sys.argv) < 2:
        return cron()
    cmd = sys.argv[1]
    if cmd == "list":
        cmd_list()
    elif cmd == "dl":
        return cmd_dl(sys.argv[2] if len(sys.argv) > 2 else "")
    elif cmd == "kw":
        return cmd_kw(sys.argv[2] if len(sys.argv) > 2 else "")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"ERROR {type(e).__name__}: {e}")
        sys.exit(1)
