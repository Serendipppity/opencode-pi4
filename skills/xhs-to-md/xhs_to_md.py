#!/usr/bin/env python3
"""xhs_to_md.py — 小红书笔记转 Markdown，图片以 base64 内嵌。

用法:
  python3 xhs_to_md.py "链接" [-o 输出.md] [--no-images] [--bypass-jina]
"""
import argparse
import base64
import io
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone

UA_PC = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
UA_MOBILE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")
REFERER = "https://www.xiaohongshu.com/"


def http_get(url, headers, timeout=30):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def expand_short_url(url):
    if "xhslink.com" not in url and "xhslink.cn" not in url:
        return url
    req = urllib.request.Request(url, headers={"User-Agent": UA_MOBILE}, method="GET")
    with urllib.request.urlopen(req) as resp:
        return resp.geturl()


def fetch_html(url):
    headers = {"User-Agent": UA_MOBILE, "Referer": REFERER}
    try:
        return http_get(url, headers).decode("utf-8", errors="ignore")
    except Exception as e:
        return f"__ERR__{e}"


def parse_initial_state(html):
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>", html, re.S)
    if not m:
        return None
    raw = m.group(1)
    raw = re.sub(r",\s*}", "}", raw)
    raw = re.sub(r":undefined(?=[,}])", ":null", raw)
    try:
        return json.loads(raw)
    except Exception:
        return None


def extract_note(data):
    try:
        return data["noteData"]["data"]["noteData"]
    except (KeyError, TypeError):
        return None


def image_urls(note):
    urls = []
    for img in note.get("imageList", []) or []:
        u = img.get("url") or img.get("urlDefault")
        if u:
            urls.append(u.replace("http://", "https://"))
    return urls


def fetch_image_b64(url):
    headers = {"User-Agent": UA_MOBILE, "Referer": REFERER}
    try:
        content = http_get(url, headers)
        return base64.b64encode(content).decode("ascii")
    except Exception:
        return None


def fmt_ts(ms):
    try:
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ms)


def build_md(note, with_images=True):
    title = note.get("title") or ""
    desc = note.get("desc") or ""
    user = note.get("user", {}) or {}
    nickname = user.get("nickName") or ""
    note_id = note.get("noteId") or ""
    tags = [t.get("name") for t in (note.get("tagList") or []) if t.get("name")]
    likes = (note.get("interactInfo") or {}).get("likedCount") or ""
    comments = (note.get("interactInfo") or {}).get("commentCount") or ""
    cols = (note.get("interactInfo") or {}).get("collectedCount") or ""
    ts = note.get("time") or note.get("lastUpdateTime") or 0
    url = f"https://www.xiaohongshu.com/explore/{note_id}"

    lines = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- 作者: {nickname}")
    lines.append(f"- 时间: {fmt_ts(ts)}")
    lines.append(f"- 链接: {url}")
    if likes or comments or cols:
        lines.append(f"- 互动: 点赞 {likes} | 收藏 {cols} | 评论 {comments}")
    if tags:
        lines.append(f"- 标签: {' '.join('#' + t for t in tags)}")
    lines.append("")
    lines.append("---")
    lines.append("")
    if desc:
        lines.append(desc)
        lines.append("")

    if with_images:
        imgs = image_urls(note)
        if imgs:
            lines.append("## 图片")
            lines.append("")
            for i, u in enumerate(imgs, 1):
                b64 = fetch_image_b64(u)
                if b64:
                    lines.append(f"![图{i}](data:image/jpeg;base64,{b64})")
                    lines.append("")
                else:
                    lines.append(f"![图{i}]({u})")
                    lines.append("")
    return "\n".join(lines)


def safe_filename(title, note_id):
    s = re.sub(r'[\\/:*?"<>|\s]+', "_", title).strip("_") or note_id or "xhs_note"
    return s[:80]


def main():
    ap = argparse.ArgumentParser(description="小红书笔记转 Markdown（图片内嵌 base64）")
    ap.add_argument("url", help="小红书链接（支持短链）")
    ap.add_argument("-o", "--output", help="输出 md 文件路径")
    ap.add_argument("--no-images", action="store_true", help="不含图片")
    ap.add_argument("--out-dir", default=".", help="输出目录（默认当前目录）")
    args = ap.parse_args()

    final_url = expand_short_url(args.url)
    html = fetch_html(final_url)
    if html.startswith("__ERR__"):
        print(f"请求失败: {html[6:]}", file=sys.stderr)
        sys.exit(1)

    data = parse_initial_state(html)
    note = extract_note(data) if data else None
    if not note:
        print("解析失败：未找到笔记数据（可能需要登录或链接已失效）", file=sys.stderr)
        sys.exit(1)

    md = build_md(note, with_images=not args.no_images)

    out = args.output
    if not out:
        name = safe_filename(note.get("title") or "", note.get("noteId") or "")
        out = f"{args.out_dir.rstrip('/')}/{name}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"OK -> {out}")
    print(f"标题: {note.get('title')}")
    print(f"图片: {len(image_urls(note))} 张" if not args.no_images else "图片: 跳过")


if __name__ == "__main__":
    main()
