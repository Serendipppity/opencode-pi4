#!/home/pi/agent-venv/bin/python3
"""新闻简报 v4：RSS(capture) + 直连财经源 → opencode brief agent → xiaohu format.py → 图文推送"""
import subprocess, sys, os, datetime, re, json, urllib.request, urllib.parse, html as _html
import xml.etree.ElementTree as ET

label = sys.argv[1] if len(sys.argv) > 1 else '早'
dry = '--dry' in sys.argv
env = os.environ.copy()
env['PATH'] = '/home/pi/bin:/home/pi/.opencode/bin:' + env.get('PATH', '')
for line in open('/home/pi/.bashrc'):
    line = line.strip()
    if line.startswith('export ') and '=' in line:
        k, v = line[7:].split('=', 1)
        env.setdefault(k, v.strip('"').strip("'"))

date = datetime.datetime.now().strftime('%Y-%m-%d')
SKILL_DIR = '/home/pi/.config/opencode/skills/xiaohu-wechat-format'
PREFS = '/home/pi/agent-workspace/user_prefs.json'

def _fetch(url, timeout=15):
    import socket
    socket.setdefaulttimeout(timeout)
    _orig = socket.getaddrinfo
    def _ipv4_only(host, port, *a, **k):
        k.pop('family', None)
        try:
            return _orig(host, port, socket.AF_INET, *a, **k)
        except socket.gaierror:
            return _orig(host, port, *a, **k)
    socket.getaddrinfo = _ipv4_only
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode('utf-8', 'ignore')
    except Exception:
        return ''

def _clean(raw):
    return re.sub(r'<[^>]+>', '', _html.unescape(raw or '')).strip()

def fetch_extra_sources():
    """直连补抓 5 个财经源（弃 RSSHub）。返回与 parse_rss 同格式文本"""
    focus, ignore = [], []
    try:
        prefs = json.load(open(PREFS))
        focus = prefs.get('focus_keywords', [])
        ignore = prefs.get('ignore_keywords', [])
    except Exception:
        pass
    entries = []

    # a. 华尔街见闻 官方 JSON API
    try:
        js = json.loads(_fetch('https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=20'))
        for item in js.get('data', {}).get('items', []):
            title = item.get('title') or ''
            content = _clean(item.get('content_text') or item.get('content') or '')
            link = item.get('uri') or ''
            if link and not link.startswith('http'):
                link = 'https://wallstreetcn.com' + link
            if title:
                entries.append(('Wallstreetcn', title, content, link))
    except Exception:
        pass

    # b. Google News RSS（4 个弃 RSSHub 的源）
    gsites = {
        'Bloomberg': 'site:bloomberg.com',
        'Zaobao China': 'site:zaobao.com.sg',
        'Zaobao World': 'site:zaobao.com.sg/world',
        'Caixin China': 'site:caixin.com',
    }
    for name, q in gsites.items():
        url = 'https://news.google.com/rss/search?q=' + urllib.parse.quote(q) + '&hl=zh-CN&gl=CN&ceid=CN:zh-Hans'
        try:
            root = ET.fromstring(_fetch(url).lstrip('\ufeff'))
            for item in root.findall('.//item')[:15]:
                t = item.find('title'); l = item.find('link'); d = item.find('description')
                title = t.text if t is not None and t.text else '无标题'
                link = l.text if l is not None else ''
                desc = _clean(d.text) if d is not None else ''
                entries.append((name, title, desc, link))
        except Exception:
            pass

    lines = []
    for name, title, desc, link in entries:
        cs = title + desc
        if any(w in cs for w in ignore):
            continue
        is_focus = any(w in cs for w in focus)
        prefix = '[⭐高相关] ' if is_focus else ''
        lines.append(f'[{name}] {prefix}{title}\n描述: {desc}\n链接: {link}\n')
    return '\n'.join(lines), len(entries)

# 1. 抓 RSS（capture 材料）
p1 = subprocess.run(['python3', '/home/pi/.config/opencode/skills/news-summary/scripts/parse_rss.py'],
    cwd='/home/pi/agent-workspace', capture_output=True, text=True, timeout=300, env=env)
material = (p1.stdout or '')

# 1b. 直连补抓 5 财经源
extra, extra_n = fetch_extra_sources()
if extra:
    material += '\n' + extra
    print(f'[+] 直连补抓财经源: {extra_n} 条 (Wallstreetcn API + Google News RSS)')

# 2. opencode 生成 Markdown（SKILL 标准格式）
TPL = '/home/pi/wechat-agent/templates/brief.md'
tpl = open(TPL).read().format(date=date, label=label)
prompt = (f'不要执行任何 bash 命令、不调用工具、不联网，材料已附在下方，直接按模板生成。\n'
          f'规则：编号1-12全程连续共10-12条；`源标签`取材料中的来源名（早报/财新/华尔街见闻/BBC/NPR/联合早报/Al Jazeera）；'
          f'每条 = **编号. 中文标题** `源标签` + 英文副标题 + > 引用块（🄲 中文摘要 / 🄴 English summary / URL 链接，无图标）；'
          f'引用块内 🄲 🄴 URL 三行缺一不可；标题和分区名不加任何 emoji 图标；'
          f'只输出简报正文，不得输出"来源：xxx"汇总行、不得输出任何模板说明或多余文字。\n\n{tpl}')
prompt += f'\n\n--- 以下为今日新闻材料 ---\n{material}'
# prompt 按 30KB 分块传 argv（aarch64 单参数上限 32KB，超限报 Argument list too long）
_parts = [prompt[i:i+30000] for i in range(0, len(prompt), 30000)] if len(prompt) > 30000 else [prompt]
p = subprocess.run(['/home/pi/.opencode/bin/opencode', 'run', '--agent', 'brief', *_parts],
    cwd='/home/pi/agent-workspace', capture_output=True, text=True, timeout=600, env=env)
md = (p.stdout or '').strip()
# 清洗：剥代码块标记 + 结尾话术
md = md.strip()
if md.startswith('```'):
    md = md.strip('`').strip()
md = re.sub(u'，?底稿已存.*$', '', md, flags=re.S)
md = re.sub(u'🄻\\s*', '', md)  # 去 🄻 图标（LLM 偶尔会带）
if len(md) < 100:
    md = f'# {label}报生成失败\n\n{md[:300] or (p.stderr or "")[-200:]}'
open('/tmp/brief.md', 'w').write(md)
print('MD_LEN:', len(md))

# 3. xiaohu format.py 转微信 HTML
outdir = '/tmp/xhwf_out'
if os.path.isdir(outdir):
    subprocess.run(['rm', '-rf', outdir])
r = subprocess.run(['/home/pi/agent-venv/bin/python3', f'{SKILL_DIR}/scripts/format.py',
    '-i', '/tmp/brief.md', '-o', outdir, '--format', 'wechat', '--no-open'],
    capture_output=True, text=True, timeout=120)
print('format:', 'OK' if r.returncode == 0 else ('FAIL ' + (r.stderr or r.stdout)[-300:]))
# blockquote 内 URL 13px
import re as _re
def _wrap(m):
    blk = m.group(0)
    blk = _re.sub(r'URL\s+(https?://[^<"]+)', lambda u: '<span style="font-size:13px;color:#BBBBBB">' + u.group(1) + '</span>', blk)
    blk = _re.sub(r'<br\s*/?>\s*(https?://[^<"]+)', lambda u: '<br /><span style="font-size:13px;color:#BBBBBB">' + u.group(1) + '</span>', blk)
    return blk
for _root, _dirs, _files in os.walk(outdir) if os.path.isdir(outdir) else []:
    if 'article.html' in _files:
        html = open(os.path.join(_root, 'article.html')).read()
        break

# blockquote 内 URL 13px（必须在读取 article.html 之后）
def _wrap(m):
    blk = m.group(0)
    # 去掉 URL 字面标记，只留链接；链接统一 13px 浅灰
    pat = r'(?:🄻\s*|URL|<br\s*/?>)\s*(?:<br\s*/?>\s*)*(https?://[^\s<"]+)'
    blk = re.sub(pat,
        lambda u: '<span style="font-size:13px !important;color:#BBBBBB !important;word-break:break-all;">' + u.group(1) + '</span>', blk, flags=re.I)
    return blk
html = re.sub(r'<section data-role="blockquote"[^>]*>.*?</section>', _wrap, html, flags=re.S)

# 清除残留的 URL 字面标记（<br />URL<br />）
html = re.sub(r'<br\s*/?>\s*URL\s*(?=<br|</p>)', '<br />', html, flags=re.I)

# 英文副标题行（</code><br /> 后紧跟英文字母文本）统一 22px
html = re.sub(
    r'(</code>\s*<br\s*/?>\s*)(?=[A-Za-z])',
    lambda u: u.group(1) + '<span style="font-size:22px !important;color:#555555 !important;">',
    html)
# 关闭上面打开的 span：英文副标题行到 <br 或 </p> 结束
html = re.sub(
    r'(<span style="font-size:22px !important;color:#555555 !important;">[^<]{2,80}?)(?=<br|</p>)',
    lambda u: u.group(1) + '</span>', html)

if not html:
    html = md
print('HTML_LEN:', len(html))
open('/tmp/brief_final.html', 'w').write(html)
if dry:
    print('=== DRY RUN，跳过推送 ===')
    sys.exit(0)

# 4. 图文推送
sys.path.insert(0, '/home/pi/wechat-agent')
from push import push_mass_news
r = push_mass_news(f'{date} {label}报', html, digest=f'{label}报 · {date}')
print('push:', r)
