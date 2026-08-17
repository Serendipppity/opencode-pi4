#!/home/pi/agent-venv/bin/python3
"""简报 HTML 后处理清洗：URL 13px + 英文副标题 17px 左对齐。
从 news_brief.py 抽出，集中管理格式规则，避免与 format.py 双轨制。
"""
import re


def clean_html(html):
    """对 format.py 输出的 article.html 做统一后处理：
    1. blockquote 内 URL 统一 13px 浅灰，去 URL/🄻 字面标记，保留换行
    2. 英文副标题行 17px 左对齐（防 justify 拉伸单词间距）
    返回清洗后的 HTML。
    """
    def _wrap(m):
        blk = m.group(0)
        # 0. 无条件删 "URL" 字面标记（独立行 <br />URL<br /> 或同行 URL https 前缀）
        blk = re.sub(r'<br\s*/?>\s*\n?URL\s*<br\s*/?>', '<br />', blk, flags=re.I)
        blk = re.sub(r'<br\s*/?>\s*URL\s*(?=<br|</p>|https?://)', '<br />', blk, flags=re.I)
        blk = re.sub(r'^\s*URL\s*(?=<br|</p>|https?://)', '', blk, flags=re.I)
        blk = re.sub(r'\s+URL\s+(?=https?://)', ' ', blk, flags=re.I)
        # 1. 删 🄻 前缀 + 链接 13px（场景 A：独立行）
        blk = re.sub(r'🄻\s*(?:<br\s*/?>\s*)?(https?://[^\s<"]+)',
            lambda u: '<span style="font-size:13px !important;color:#BBBBBB !important;word-break:break-all;">' + u.group(1) + '</span>', blk, flags=re.I)
        # 2. <br /> 后的裸链接 13px（场景 B/C）
        blk = re.sub(r'(<br\s*/?>\s*)(https?://[^\s<"]+)',
            lambda u: u.group(1) + '<span style="font-size:13px !important;color:#BBBBBB !important;word-break:break-all;">' + u.group(2) + '</span>', blk, flags=re.I)
        # 3. 行首裸 URL 兜底
        blk = re.sub(r'^\s*https?://[^\s<"]+',
            lambda u: '<span style="font-size:13px !important;color:#BBBBBB !important;word-break:break-all;">' + u.group(0) + '</span>', blk, flags=re.I)
        return blk

    html = re.sub(r'<section data-role="blockquote"[^>]*>.*?</section>', _wrap, html, flags=re.S)

    # 引用块内容 p 显式左对齐（微信编辑器默认 justify 会把英文拉伸出多余空格）
    html = re.sub(
        r'(<section data-role="blockquote"[^>]*>\s*<p style=")([^"]*)(")',
        lambda m: m.group(1) + 'text-align:left !important;' + m.group(2) + m.group(3),
        html)

    # 英文副标题行（</code><br /> 后紧跟英文字母文本）17px 左对齐（加 display:block 使 text-align:left 生效，防止微信 justify 拉伸英文单词间距）
    html = re.sub(
        r'(</code>\s*<br\s*/?>\s*)(?=[A-Za-z])',
        lambda u: u.group(1) + '<span style="display:block !important;font-size:17px !important;color:#555555 !important;text-align:left !important;margin-top:4px !important;">',
        html)
    # 关闭上面打开的 span：英文副标题行到 <br 或 </p> 结束
    html = re.sub(
        r'(<span style="display:block !important;font-size:17px !important;color:#555555 !important;text-align:left !important;margin-top:4px !important;">[^<]{2,200}?)(?=<br|</p>)',
        lambda u: u.group(1) + '</span>', html)

    return html
