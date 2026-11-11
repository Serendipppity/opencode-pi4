#!/home/pi/agent-venv/bin/python3
# -*- coding: utf-8 -*-
"""wechat_to_md.py — 微信公众号文章 → Markdown（图片本地化归档）

输出格式对齐 fetch_cicc_reports.py（中金研报归档）：
    # 标题
    > **原文链接**：https://mp.weixin.qq.com/s?...
    - **公众号** / **作者** / **发布时间** / **抓取时间** / **正文长度 + 图片数**
    ---
    正文（图片改写为本地相对路径 images/<文章key>/figNN.jpg）

用法：
    python3 wechat_to_md.py "https://mp.weixin.qq.com/s/xxx"
    python3 wechat_to_md.py "URL" -o 输出.md
    python3 wechat_to_md.py "URL" --out-dir ./某目录
    python3 wechat_to_md.py "URL" --no-images      # 只取正文，图片保留原链
    python3 wechat_to_md.py "URL" --stdout         # 打到标准输出，不落盘

抓取优先级：
    1) Playwright 直连微信页面（可拿到完整元数据）
    2) 直连被验证码拦截时，回退到 Wechat2RSS 订阅源（feeds.json）按 mid/sn 匹配正文
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

try:
    import html2text
except ImportError:
    sys.exit("缺少依赖 html2text：/home/pi/agent-venv/bin/pip install html2text")

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT_DIR = os.path.expanduser("~/agent-workspace/outbox_obsidian/articles_微信")
FEEDS_FILE = os.path.join(SKILL_DIR, "feeds.json")
CST = timezone(timedelta(hours=8))
UA_PC = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
UA_MOBILE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
REFERER = "https://mp.weixin.qq.com/"
FETCH_TIMEOUT = 30
MAX_IMG_WORKERS = 3
IMG_EXT = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
           "image/gif": ".gif", "image/webp": ".webp", "image/bmp": ".bmp"}


def now_s():
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def slugify(title, limit=60):
    s = re.sub(r"[^\w一-鿿]+", "-", title or "").strip("-")
    return s[:limit].strip("-") or "untitled"


def parse_pub(raw):
    """统一发布时间：RFC2822 / ISO / 中文格式 → (完整时间, YYYY-MM-DD)"""
    raw = (raw or "").strip()
    if not raw:
        return "", ""
    dt = None
    try:
        dt = parsedate_to_datetime(raw)
    except Exception:
        pass
    if dt is None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y年%m月%d日"):
            try:
                dt = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        m = re.search(r"(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?", raw)
        if m:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                          int(m.group(4) or 0), int(m.group(5) or 0))
    if dt is None:
        return raw, ""
    if dt.tzinfo:
        dt = dt.astimezone(CST)
    return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.strftime("%Y-%m-%d")


def http_get(url, headers=None, timeout=FETCH_TIMEOUT):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA_PC})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), resp.headers.get("Content-Type", "")


# ---------------------------------------------------------------- 直连抓取
def fetch_via_browser(url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox",
                                                         "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA_PC, locale="zh-CN", viewport={"width": 1280, "height": 900},
                                  extra_http_headers={"Referer": REFERER})
        page = ctx.new_page()
        page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_selector("#js_content", timeout=15000)
            except Exception:
                pass
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)

            if "wappoc_appmsgcaptcha" in page.url or page.locator("#js_content").count() == 0:
                raise RuntimeError(f"页面被拦截（{page.title() or '空页面'}）")

            meta = page.evaluate("""() => {
              const q = s => { const e = document.querySelector(s); return e ? (e.innerText || '').trim() : ''; };
              const m = n => { const e = document.querySelector(`meta[property="${n}"]`)
                                   || document.querySelector(`meta[name="${n}"]`); return e ? (e.content || '').trim() : ''; };
              const body = document.querySelector('#js_content');
              return {
                title: q('#activity-name') || m('og:title') || document.title,
                account: q('#js_name') || m('og:site_name'),
                author: q('#js_author_name') || m('author'),
                pub: q('#publish_time') || m('og:release_date') || m('article:published_time'),
                desc: m('og:description'),
                body: body ? body.innerHTML : ''
              };
            }""")
            if not meta.get("body"):
                raise RuntimeError("正文为空")
            return meta
        finally:
            browser.close()


# ---------------------------------------------------------------- Wechat2RSS 回退
def load_feeds():
    if not os.path.exists(FEEDS_FILE):
        return {}
    try:
        return json.load(open(FEEDS_FILE, encoding="utf-8"))
    except Exception as e:
        log(f"WARN feeds.json 解析失败：{e}")
        return {}


def parse_rss_items(raw):
    items = []
    for chunk in re.findall(r"<item>(.*?)</item>", raw, re.S):
        def pick(tag):
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", chunk, re.S)
            if not m:
                return ""
            v = m.group(1)
            if v.startswith("<![CDATA["):
                v = v[9:-3] if v.endswith("]]>") else v[9:]
            return v.strip()
        items.append({
            "title": html.unescape(pick("title")),
            "link": html.unescape(pick("link")),
            "pub": pick("pubDate"),
            "body": pick("content:encoded"),
        })
    return items


def url_keys(url):
    """提取 (__biz, mid, idx, sn)，用于跨域名匹配同一篇文章"""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    g = lambda k: (q.get(k) or [""])[0]
    return g("__biz"), g("mid"), g("idx"), g("sn")


def fetch_via_rss(url):
    feeds = load_feeds()
    if not feeds:
        raise RuntimeError("未配置 feeds.json，无法走 Wechat2RSS 回退")
    biz, mid, idx, sn = url_keys(url)

    def load(item):
        name, fid = item
        try:
            raw, _ = http_get(f"https://wechat2rss.bestblogs.dev/feed/{fid}.xml")
            return name, parse_rss_items(raw.decode("utf-8", "ignore"))
        except Exception as e:
            log(f"WARN 拉取订阅源 {name} 失败：{e}")
            return name, []

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(load, feeds.items()))

    for name, items in results:
        for it in items:
            b2, m2, i2, s2 = url_keys(it["link"])
            hit = (sn and sn == s2) or (mid and mid == m2 and (not idx or idx == i2))
            if hit:
                log(f"命中订阅源：{name}")
                return {
                    "title": it["title"],
                    "account": name,
                    "author": "",
                    "pub": it["pub"],
                    "desc": "",
                    "body": it["body"],
                    "source": "rss",
                }
    raise RuntimeError("Wechat2RSS 订阅源中未找到该文章（仅覆盖已订阅公众号近 10 篇）")


# ---------------------------------------------------------------- 图片本地化
IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
SRC_RE = re.compile(r"\s(?:data-src|src)\s*=\s*[\"']([^\"']+)[\"']", re.I)


def normalize_body(body_html):
    """统一 img：data-src → src，去掉懒加载/统计属性，保留 alt"""
    def fix(m):
        tag = m.group(0)
        src = (re.search(r"\sdata-src\s*=\s*[\"']([^\"']+)[\"']", tag, re.I)
               or SRC_RE.search(tag))
        if not src:
            return ""
        alt = re.search(r"\salt\s*=\s*[\"']([^\"']*)[\"']", tag)
        src_u = html.unescape(src.group(1))
        return f'<img src="{html.escape(src_u, quote=True)}" alt="{html.escape(alt.group(1) if alt else "", quote=True)}">'
    return IMG_RE.sub(fix, body_html)


def resolve_img_url(url):
    """Wechat2RSS 的 img-proxy 不稳定，直接取它包裹的原始 mmbiz 地址"""
    while "&amp;" in url:
        url = html.unescape(url)
    if "img-proxy" in url:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        if q.get("u"):
            return urllib.parse.unquote(q["u"][0])
    return url


def rewrite_img_urls(body_html):
    """不下载图片时，把 img-proxy 包裹地址还原成原始 mmbiz 直链"""
    def fix(m):
        src = SRC_RE.search(m.group(0))
        if not src:
            return ""
        return f'<img src="{html.escape(resolve_img_url(src.group(1)), quote=True)}" alt="">'
    return IMG_RE.sub(fix, body_html)


def localize_images(body_html, art_key, out_dir):
    """下载图片到 images/<art_key>/figNN.ext，返回 (新 html, 图片列表)"""
    tags = list(IMG_RE.finditer(body_html))
    if not tags:
        return body_html, []
    dst_dir = os.path.join(out_dir, "images", art_key)
    os.makedirs(dst_dir, exist_ok=True)

    def dl(pair):
        idx, url = pair
        last_err = None
        for attempt in range(3):
            try:
                data, ctype = http_get(url, headers={"User-Agent": UA_PC, "Referer": REFERER}, timeout=40)
                if len(data) < 512:
                    raise ValueError("内容过小，疑似防盗链占位图")
                ext = IMG_EXT.get((ctype or "").split(";")[0].strip().lower(), ".jpg")
                fn = f"fig{idx:02d}{ext}"
                with open(os.path.join(dst_dir, fn), "wb") as f:
                    f.write(data)
                return idx, f"images/{art_key}/{fn}"
            except Exception as e:
                last_err = e
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
        log(f"WARN 图片 {idx:02d} 下载失败（保留原链）：{last_err}")
        return idx, None

    urls = []
    for i, m in enumerate(tags):
        s = SRC_RE.search(m.group(0))
        urls.append((i + 1, resolve_img_url(s.group(1)) if s else ""))
    with ThreadPoolExecutor(max_workers=MAX_IMG_WORKERS) as ex:
        results = dict(ex.map(dl, urls))

    out, last, saved = [], 0, []
    for i, m in enumerate(tags):
        out.append(body_html[last:m.start()])
        out.append(m.group(0).replace(m.group(0), f'<img src="{results.get(i + 1) or urls[i][1]}" alt="">'))
        last = m.end()
        if results.get(i + 1):
            saved.append(results[i + 1])
    out.append(body_html[last:])
    return "".join(out), saved


# ---------------------------------------------------------------- HTML → Markdown
def html_to_md(body_html):
    h = html2text.HTML2Text()
    h.body_width = 0
    h.ignore_links = False
    h.ignore_images = False
    h.ignore_emphasis = False
    h.protect_links = False
    h.unicode_snob = True
    h.escape_snob = False
    h.single_line_break = False
    md = h.handle(body_html)
    md = md.replace("\u00a0", " ").replace("\u200b", "")
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def build_md(meta, url, images, body_md):
    lines = [f"# {meta['title']}", ""]
    lines += [f"> **原文链接**：{url}", ""]
    if meta.get("account"):
        lines.append(f"- **公众号**：{meta['account']}")
    if meta.get("author"):
        lines.append(f"- **作者**：{meta['author']}")
    if meta.get("pub"):
        lines.append(f"- **发布时间**：{meta['pub']}")
    lines.append(f"- **抓取时间**：{now_s()}")
    lines.append(f"- **正文长度**：{len(body_md)} 字 | **图片**：{len(images)} 张"
                 f"{'（已本地化）' if images else ''}")
    lines += ["", "---", "", body_md, ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- 主流程
def convert(url, out_dir, out_file, want_images):
    meta = None
    try:
        meta = fetch_via_browser(url)
        log("抓取方式：Playwright 直连")
    except Exception as e:
        log(f"直连失败：{e}，尝试 Wechat2RSS 回退…")
        meta = fetch_via_rss(url)
        log("抓取方式：Wechat2RSS 订阅源")

    title = (meta.get("title") or "未命名文章").strip()
    pub_str, date_s = parse_pub(meta.get("pub"))
    date_s = date_s or datetime.now(CST).strftime("%Y-%m-%d")
    meta["pub"] = pub_str
    art_key = f"{date_s}_{slugify(title)}"

    body_html = normalize_body(meta.get("body") or "")
    images = []
    if want_images:
        body_html, images = localize_images(body_html, art_key, out_dir)
    else:
        body_html = rewrite_img_urls(body_html)
    body_md = html_to_md(body_html)

    md = build_md(meta, url, images, body_md)
    if not out_file:
        out_file = os.path.join(out_dir, art_key + ".md")
    if out_file != os.devnull:
        os.makedirs(os.path.dirname(os.path.abspath(out_file)) or ".", exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(md)
    return md, out_file, len(images)


def main():
    ap = argparse.ArgumentParser(description="微信公众号文章 → Markdown（图片本地化）")
    ap.add_argument("url", help="mp.weixin.qq.com 文章链接")
    ap.add_argument("-o", "--output", help="输出 md 路径")
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR,
                    help=f"输出目录（默认 {DEFAULT_OUT_DIR}）")
    ap.add_argument("--no-images", action="store_true", help="不下载图片，保留原始链接")
    ap.add_argument("--stdout", action="store_true", help="输出到标准输出，不写文件")
    args = ap.parse_args()

    if args.stdout:
        args.output = os.devnull
    md, out_file, n_img = convert(args.url, os.path.abspath(args.out_dir),
                                  os.path.abspath(args.output) if args.output else None,
                                  not args.no_images)
    if args.stdout:
        sys.stdout.write(md)
        return
    log(f"完成：{out_file}（{len(md)} 字，{n_img} 张图片）")
    print(out_file)


if __name__ == "__main__":
    main()
