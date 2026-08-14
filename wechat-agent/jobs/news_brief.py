#!/home/pi/agent-venv/bin/python3
"""新闻简报 v3：RSS → opencode 生成 Markdown（SKILL 标准格式）→ xiaohu format.py 转微信 HTML → 图文推送"""
import subprocess, sys, os, datetime, re

label = sys.argv[1] if len(sys.argv) > 1 else '早'
dry = '--dry' in sys.argv
env = os.environ.copy()
env['PATH'] = '/home/pi/bin:/home/pi/.opencode/bin:' + env.get('PATH', '')
for line in open('/home/pi/.bashrc'):
    line = line.strip()
    if line.startswith('export ') and '=' in line:
        k, v = line[7:].split('=', 1)
        env.setdefault(k, v.strip('\"').strip("'"))

date = datetime.datetime.now().strftime('%Y-%m-%d')
SKILL_DIR = '/home/pi/.config/opencode/skills/xiaohu-wechat-format'

# 1. 抓 RSS（底稿含 URL 归档）
subprocess.run(['python3', '/home/pi/.config/opencode/skills/news-summary/scripts/parse_rss.py'],
    cwd='/home/pi/agent-workspace', timeout=300, env=env)

# 2. opencode 生成 Markdown（SKILL 标准格式）
prompt = (f'用 news-summary 技能的标准输出格式生成今日{label}报，'
          f'严格按 SKILL.md 的 Standard Output Format：'
          f'📰 Daily Briefing 标题，⭐ PERSONALLY CURATED FOR YOU 置顶（AI/OpenAI/苹果/半导体/美联储/降息），'
          f'然后 🌍 WORLD / 💼 BUSINESS / 💡 TECH / 🇨🇳 CHINA 分类，'
          f'每条：[English Headline] / [中文标题] [Source]，EN: 摘要，CN: 总结，共 10-12 条。'
          f'输出纯 Markdown 正文，不要代码块包裹，正文不含 🔗 URL 行（链接存底稿）。'
          f'标题行：📰 Daily Briefing | {date} {label}报')
p = subprocess.run(['/home/pi/.opencode/bin/opencode', 'run', prompt],
    cwd='/home/pi/agent-workspace', capture_output=True, text=True, timeout=600, env=env)
md = (p.stdout or '').strip()
# 清洗：剥代码块标记 + 结尾话术（字符串方法，避正则）
md = md.strip()
if md.startswith(''):
    md = md.rstrip()[:-3]
import re as _re
md = _re.sub(u'，?底稿已存.*$', '', md, flags=_re.S)
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
html = ''
for _root, _dirs, _files in os.walk(outdir) if os.path.isdir(outdir) else []:
    if 'article.html' in _files:
        html = open(os.path.join(_root, 'article.html')).read()
        break
if not html:
    html = md
print('HTML_LEN:', len(html))
if dry:
    print('=== DRY RUN，跳过推送 ===')
    sys.exit(0)

# 4. 图文推送
sys.path.insert(0, '/home/pi/wechat-agent')
from push import push_mass_news
r = push_mass_news(f'{date} {label}报', html, digest=f'{label}报 · {date}')
print('push:', r)
