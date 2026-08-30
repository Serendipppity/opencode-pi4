#!/home/pi/agent-venv/bin/python3
"""新闻简报 v6：parse_rss 统一抓 8 源全量留底 → 读底稿硬过滤 → opencode brief agent（主模型+退避+fallback）→ xiaohu format.py → 图文推送"""
import subprocess, sys, os, datetime, re, json, time

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

RAW_ARCHIVE_DIR = '/home/pi/agent-workspace/outbox_obsidian/news_archives'

def read_raw_material(path):
    """解析 raw_rss 底稿：剔除 🚫ignored/↺pushed 条目（底稿留痕不删），其余拼成 LLM 材料"""
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.read().splitlines()
    except Exception:
        return ''
    material = []
    src = ''
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('## Source: '):
            src = line[len('## Source: '):].strip()
            i += 1
        elif line.startswith('### '):
            title = line[4:].strip()
            desc = lines[i + 1].strip() if i + 1 < len(lines) else ''
            link, status = '', ''
            j = i + 2
            while j < min(i + 6, len(lines)):
                s = lines[j].strip()
                if s.startswith('🔗'):
                    link = s[1:].strip()
                elif s.startswith('STATUS:'):
                    status = s[len('STATUS:'):].strip()
                    break
                j += 1
            if title and not status.startswith(('🚫', '↺')):
                prefix = '[⭐高相关] ' if status.startswith('⭐') else ''
                material.append(f"[{src}] {prefix}{title}\n描述: {desc}\n链接: {link}\n")
            i = j + 1
        else:
            i += 1
    return '\n'.join(material)

# 1. 抓料：parse_rss 统一抓 8 源并全量留底，随后读底稿硬过滤出可推送材料
stamp = datetime.datetime.now().strftime('%Y-%m-%d_%H%M')
raw_path = f'{RAW_ARCHIVE_DIR}/raw_rss_{stamp}.md'
p1 = subprocess.run(['python3', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'parse_rss.py'),
    '--out', raw_path],
    cwd='/home/pi/agent-workspace', capture_output=True, text=True, timeout=240, env=env)
material = read_raw_material(raw_path)
if not material:
    print('[!] 材料为空，parse_rss 输出尾部:', ((p1.stderr or '') + (p1.stdout or ''))[-600:])
else:
    print(f'[+] RAW RSS 底稿: {raw_path} | LLM 材料 {len(material)} 字符')

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

def _run_brief(prompt_text, model=None):
    """调用 opencode brief agent 生成简报；model=None 用 brief.md 默认主模型"""
    # prompt 按 30KB 分块传 argv（aarch64 单参数上限 32KB，超限报 Argument list too long）
    _parts = [prompt_text[i:i+30000] for i in range(0, len(prompt_text), 30000)] if len(prompt_text) > 30000 else [prompt_text]
    cmd = ['/home/pi/.opencode/bin/opencode', 'run']
    if model:
        cmd += ['--model', model]
    cmd += ['--agent', 'brief', *_parts]
    p = subprocess.run(cmd,
        cwd='/home/pi/agent-workspace', capture_output=True, text=True, timeout=600, env=env)
    md = (p.stdout or '').strip()
    # 诊断日志：失败可回溯（此前 stdout 为空无任何线索）
    if p.returncode != 0 or len(md) < 100:
        err_tail = (p.stderr or '')[-300:].replace('\n', ' ')
        print(f'[!] opencode 诊断: model={model or "默认(brief.md)"} returncode={p.returncode} stdout_len={len(md)} stderr尾: {err_tail}', flush=True)
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

# 2. LLM 生成（三段式：主模型 → 30s 退避同模型重试 → 显式 fallback 模型）
FALLBACK_MODEL = 'opencode-go/deepseek-v4-flash'
DEFAULT_MODEL = 'google/gemini-3.5-flash'  # 与 brief.md 的 model 保持一致，用于 Discord 标注
md, problems = '', []
feedback = ''
used_model = None
for attempt, model in enumerate([None, None, FALLBACK_MODEL], 1):
    if attempt == 2:
        print('[!] 30s 退避后重试', flush=True)
        time.sleep(30)
    if attempt == 3:
        print('[!] 切换 fallback 模型:', FALLBACK_MODEL, flush=True)
    md = _run_brief(_build_prompt(feedback), model=model)
    problems = _check_brief(md)
    if len(md) >= 100 and not problems:
        used_model = model or DEFAULT_MODEL
        break
    feedback = '；'.join(problems) or '输出为空或过短'
    print(f'[!] 第{attempt}次尝试未通过: {feedback[:200]}', flush=True)
    # 记录最后一次尝试的模型（失败场景也用于告警上下文）
    used_model = model or DEFAULT_MODEL

gen_ok = len(md) >= 100 and not problems
if not gen_ok:
    md = f'# {label}报生成失败\n\n{md[:300]}'
open('/tmp/brief.md', 'w').write(md)
print('MD_LEN:', len(md), 'GEN_OK:', gen_ok, 'MODEL:', used_model)

# 生成失败：留底 + Discord 告警，严禁把失败页推给公众号
if not gen_ok and not dry:
    try:
        sys.path.insert(0, '/home/pi/wechat-agent/jobs')
        from notify_discord import send_notification
        send_notification(f'❌ {label}报生成失败 {date}（3 次尝试含 fallback 均未通过），已跳过公众号推送，原因详见 cron.log')
    except Exception as e:
        print('[!] 告警发送失败:', e)
    print('=== 生成失败，已告警并跳过推送 ===')
    sys.exit(1)

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

# 6. Discord 推送（仅 Discord 末尾追加模型标注，公众号/留底不受影响）
try:
    # 追加模型标注到 Discord 专用副本
    discord_md_path = '/tmp/brief_discord.md'
    try:
        short = (used_model or DEFAULT_MODEL).split('/')[-1]
        # 标注只给 Discord，不写入 /tmp/brief.md / html / 归档
        discord_footer = f"\n\n---\n*Model: {short}*"
        open(discord_md_path, 'w', encoding='utf-8').write(md.rstrip() + discord_footer + "\n")
    except Exception as e:
        print(f'[!] 生成 Discord 标注失败: {e}')
        discord_md_path = '/tmp/brief.md'
    from push_discord import push_to_discord as _discord_push
    dr = _discord_push(discord_md_path)
    print('push discord:', dr, 'model:', used_model)
except Exception as e:
    print(f'[!] Discord 推送异常: {e}')
