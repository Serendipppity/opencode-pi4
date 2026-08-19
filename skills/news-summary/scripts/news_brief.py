#!/home/pi/agent-venv/bin/python3
"""新闻简报 v4：RSS(capture) + 直连财经源 → opencode brief agent → xiaohu format.py → 图文推送"""
import subprocess, sys, os, datetime, re, json, urllib.request, urllib.parse, html as _html, time
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
SEEN_FILE = '/home/pi/agent-workspace/seen_links.json'

def _load_seen():
    """已推送成功链接集合（跨天累积）"""
    try:
        data = json.load(open(SEEN_FILE))
        return {l.strip() for links in data.values() for l in links}
    except Exception:
        return set()

def _save_seen(new_links, date):
    """推送成功后追加当天链接，保留近 7 天。失败不调用——保证补发不丢内容"""
    try:
        data = json.load(open(SEEN_FILE))
    except Exception:
        data = {}
    data.setdefault(date, [])
    cur = set(data[date])
    for l in new_links:
        if l and l not in cur:
            data[date].append(l)
            cur.add(l)
    # 清理 7 天前
    try:
        from datetime import timedelta
        cutoff = (datetime.datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        for d in [k for k in data if k < cutoff]:
            del data[d]
    except Exception:
        pass
    json.dump(data, open(SEEN_FILE, 'w'), ensure_ascii=False, indent=1)

import socket as _socket
_ORIG_GETADDRINFO = _socket.getaddrinfo

def _ipv4_only(host, port, *a, **k):
    k.pop('family', None)
    try:
        return _ORIG_GETADDRINFO(host, port, _socket.AF_INET, *a, **k)
    except _socket.gaierror:
        return _ORIG_GETADDRINFO(host, port, *a, **k)

def _fetch(url, timeout=5):
    _socket.setdefaulttimeout(timeout)
    _socket.getaddrinfo = _ipv4_only
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode('utf-8', 'ignore')
    except Exception:
        return ''

def _clean(raw):
    return re.sub(r'<[^>]+>', '', _html.unescape(raw or '')).strip()

def fetch_extra_sources():
    """直连补抓财经源：Wallstreetcn API + RSSHub。返回与 parse_rss 同格式文本"""
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

    # b. RSSHub 直连 4 源（cups.moe 主，rssforever/woodland 备）—— 全局 30s 超时兜底
    _RH = ['https://rsshub.cups.moe', 'https://rsshub.rssforever.com', 'https://rsshub.woodland.cafe']
    rssites = [
        ('Bloomberg', '/bloomberg'),
        ('Zaobao China', '/zaobao/realtime/china'),
        ('Zaobao World', '/zaobao/realtime/world'),
        ('Caixin China', '/caixin/latest'),
    ]
    _rss_start = time.time()
    for name, path in rssites:
        if time.time() - _rss_start > 30:
            print(f'[!] RSSHub 已超 30s，跳过剩余源')
            break
        for inst in _RH:
            root = None
            try:
                root = ET.fromstring(_fetch(inst + path).lstrip('\ufeff'))
            except Exception:
                root = None
            if root is not None and len(root.findall('.//item')) > 0:
                for item in root.findall('.//item')[:15]:
                    t = item.find('title'); l = item.find('link'); d = item.find('description')
                    title = t.text if t is not None and t.text else '无标题'
                    link = l.text if l is not None else ''
                    desc = _clean(d.text) if d is not None else ''
                    entries.append((name, title, desc, link))
                break  # 该源成功即换下一个

    lines = []
    seen_links = _load_seen()
    for name, title, desc, link in entries:
        cs = title + desc
        if any(w in cs for w in ignore):
            continue
        if link and link.strip() in seen_links:
            continue
        is_focus = any(w in cs for w in focus)
        prefix = '[⭐高相关] ' if is_focus else ''
        lines.append(f'[{name}] {prefix}{title}\n描述: {desc}\n链接: {link}\n')
    return '\n'.join(lines), len(entries)

# 1. 直连补抓财经源（Wallstreetcn API + RSSHub 3 镜像，快且有 fallback）
extra, extra_n = fetch_extra_sources()
if extra:
    print(f'[+] 直连补抓财经源: {extra_n} 条 (Wallstreetcn API + RSSHub)')

# 2. 抓 RSS（capture 材料）—— 跳过已由 fetch_extra_sources 覆盖的源
p1 = subprocess.run(['python3', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'parse_rss.py'),
    '--skip-sources', 'Bloomberg,Zaobao China,Zaobao World,Caixin China,Wallstreetcn'],
    cwd='/home/pi/agent-workspace', capture_output=True, text=True, timeout=120, env=env)
material = (p1.stdout or '')
if extra:
    material += '\n' + extra

# 2. opencode 生成 Markdown（SKILL 标准格式）
TPL = '/home/pi/wechat-agent/templates/brief.md'
tpl = open(TPL).read().format(date=date, label=label)
EXAMPLE = ('**1. 中文标题** `源标签`\n'
           'English subtitle here.\n\n'
           '> 🄲 中文摘要。\n'
           '> 🄴 English summary.\n'
           '> https://example.com')

def _build_prompt(extra_feedback=''):
    prompt = (f'不要执行任何 bash 命令、不调用工具、不联网，材料已附在下方，直接按模板生成。\n'
              f'规则（必须全部满足）：\n'
              f'1. 完整保留模板里全部 5 个 ## 分区标题（## 核心要闻 / ## 国际风云 / ## 财经速递 / ## 科技前沿 / ## 国内要闻），顺序不变、文字不改，各新闻分入对应分区；\n'
              f'2. 编号1-12全程连续共10-12条，跨分区不中断；`源标签`取材料中的来源名（早报/财新/华尔街见闻/BBC/NPR/联合早报/Al Jazeera）；\n'
              f'3. 每条 = **编号. 中文标题** `源标签` + 副标题行 + > 引用块（🄲 中文摘要 / 🄴 English summary / URL 链接，无图标）；\n'
              f'4. 副标题行必须为纯英文（English），禁止写中文，禁止粘贴材料里的描述文字；\n'
              f'5. 引用块内 🄲 🄴 URL 三行缺一不可；标题和分区名不加任何 emoji 图标；\n'
              f'6. 只输出简报正文，不得输出"来源：xxx"汇总行、不得输出任何模板说明或多余文字。\n\n'
              f'每条格式示例（副标题必须是英文）：\n{EXAMPLE}\n\n'
              f'模板如下，严格按分区结构输出：\n{tpl}')
    if extra_feedback:
        prompt += f'\n\n!!! 上次生成未通过自检，问题：{extra_feedback}。请逐条对照规则重写，5 个 ## 分区和英文副标题一项都不能少。'
    prompt += f'\n\n--- 以下为今日新闻材料 ---\n{material}'
    return prompt

def _run_brief(prompt_text):
    # prompt 按 30KB 分块传 argv（aarch64 单参数上限 32KB，超限报 Argument list too long）
    _parts = [prompt_text[i:i+30000] for i in range(0, len(prompt_text), 30000)] if len(prompt_text) > 30000 else [prompt_text]
    p = subprocess.run(['/home/pi/.opencode/bin/opencode', 'run', '--agent', 'brief', *_parts],
        cwd='/home/pi/agent-workspace', capture_output=True, text=True, timeout=600, env=env)
    md = (p.stdout or '').strip()
    # 清洗：剥代码块标记 + 结尾话术
    if md.startswith('```'):
        md = md.strip('`').strip()
    md = re.sub(u'，?底稿已存.*$', '', md, flags=re.S)
    md = re.sub(u'🄻\\s*', '', md)  # 去 🄻 图标（LLM 偶尔会带）
    # 标题补粗：无 ** 包裹的 "N. 标题 `源标签`" 行统一加粗（LLM 偶会丢 **）
    md = re.sub(r'^(?!(?:\*\*|#|>|\d+\.\s*$))(\d+\.\s+\S.*?)\s+(?=`[^`]+`\s*$)(.+)$',
        lambda m: '**' + m.group(1).rstrip() + '** ' + m.group(2), md, flags=re.M)
    return md

def _check_brief(md):
    """自检：5 个分区标题齐全 + 每条副标题为英文。返回问题列表（空=通过）"""
    problems = []
    for sec in ['核心要闻', '国际风云', '财经速递', '科技前沿', '国内要闻']:
        if f'## {sec}' not in md:
            problems.append(f'缺分区 ## {sec}')
    title_re = re.compile(r'^\*{0,2}\d+\.\s+\S.*?\*{0,2}\s+`[^`]+`\s*$')
    lines = md.splitlines()
    for i, l in enumerate(lines):
        if title_re.match(l.strip()):
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j >= len(lines):
                problems.append('某条缺副标题行')
                continue
            nxt = lines[j].strip()
            if nxt.startswith(('>', '#')):
                problems.append('某条缺副标题行')
            elif re.search(r'[\u4e00-\u9fff]', nxt):
                problems.append('某条副标题非英文')
    return problems

md = _run_brief(_build_prompt())
problems = _check_brief(md)
if problems:
    print('[!] 自检未通过:', '; '.join(problems), '→ 重试一次')
    md = _run_brief(_build_prompt('；'.join(problems)))
    problems = _check_brief(md)
    if problems:
        print('[!] 重试后仍有问题:', '; '.join(problems))
if len(md) < 100:
    md = f'# {label}报生成失败\n\n{md[:300]}'
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

# 后处理清洗：读取 article.html 后统一处理（URL 13px + 英文副标题 17px）
html = ''
for _root, _dirs, _files in os.walk(outdir) if os.path.isdir(outdir) else []:
    if 'article.html' in _files:
        html = open(os.path.join(_root, 'article.html')).read()
        break
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from clean_brief import clean_html
html = clean_html(html)

if not html:
    html = md
print('HTML_LEN:', len(html))
open('/tmp/brief_final.html', 'w').write(html)

# 4b. 最终版留底（md + html），与 raw_rss 同目录归档
import shutil
ARCHIVE_DIR = '/home/pi/agent-workspace/outbox_obsidian/news_archives'
os.makedirs(ARCHIVE_DIR, exist_ok=True)
stamp = datetime.datetime.now().strftime('%Y-%m-%d_%H%M')
for src, ext in [('/tmp/brief.md', 'md'), ('/tmp/brief_final.html', 'html')]:
    try:
        shutil.copy2(src, f'{ARCHIVE_DIR}/brief_final_{stamp}_{label}.{ext}')
    except Exception as e:
        print(f'[!] 留底失败 {ext}: {e}')
print(f'[+] 最终版留底: {ARCHIVE_DIR}/brief_final_{stamp}_{label}.{{md,html}}')
if dry:
    print('=== DRY RUN，跳过推送 ===')
    sys.exit(0)

# 5. 图文推送
sys.path.insert(0, '/home/pi/wechat-agent')
from push import push_mass_news
r = push_mass_news(f'{date} {label}报', html, digest=f'{label}报 · {date}')
print('push wechat:', r)
# 推送成功才记账（errcode 0 即 r==0），失败不记——补发时该批新闻仍可再推
if r == 0:
    links = re.findall(r'https?://[^\s"<>)\]]+', html)
    _save_seen([l.rstrip('.,;、。') for l in links], date)
    print(f'[+] 已推送去重记账: {len(links)} 条链接')
else:
    print('[!] 推送失败，不记账，下次补发可重推')

# 6. Discord 推送
try:
    from push_discord import push_to_discord as _discord_push
    dr = _discord_push('/tmp/brief.md')
    print('push discord:', dr)
except Exception as e:
    print(f'[!] Discord 推送异常: {e}')
