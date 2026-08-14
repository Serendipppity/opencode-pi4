#!/home/pi/agent-venv/bin/python3
"""每日聚合备份：workspace + skills + 画像 + soul + wechat-agent（密钥排除）"""
import subprocess, os, datetime, shutil, re

HOME = '/home/pi'
DATE = datetime.datetime.now().strftime('%Y-%m-%d')
BK = f'{HOME}/agent-backup'
SRC = [
    (f'{HOME}/agent-workspace', 'workspace'),
    (f'{HOME}/.config/opencode/skills', 'skills'),
    (f'{HOME}/.config/opencode/AGENTS.md', 'AGENTS.md'),
]
SOUL_FILES = ['SOUL.md', 'IDENTITY.md', 'MEMORY.md', 'USER.md', 'HEARTBEAT.md']
SKIP_WE = ['config.json', '__pycache__', '.git']

def rsync(src, dst, exclude=()):
    ex = sum([['--exclude', e] for e in exclude], [])
    subprocess.run(['rsync', '-a', '--delete', *ex, src + '/', dst + '/'], capture_output=True)

# 聚合
for src, dst in SRC:
    if os.path.isdir(src):
        rsync(src, f'{BK}/{dst}')
    elif os.path.isfile(src):
        os.makedirs(BK, exist_ok=True)
        shutil.copy2(src, f'{BK}/{dst}')
os.makedirs(f'{BK}/soul', exist_ok=True)
for f in SOUL_FILES:
    p = f'{HOME}/.openclaw/workspace/{f}'
    if os.path.isfile(p):
        shutil.copy2(p, f'{BK}/soul/{f}')
rsync(f'{HOME}/wechat-agent', f'{BK}/wechat-agent', SKIP_WE)
# 密钥脱敏占位
cfg = f'{HOME}/wechat-agent/config.json'
if os.path.isfile(cfg):
    s = re.sub(r'("[^"]*secret"\s*:\s*")[^"]+', r'\1***', open(cfg).read())
    open(f'{BK}/wechat-agent/config.json.sample', 'w').write(s)

# git
if not os.path.isdir(f'{BK}/.git'):
    subprocess.run(['git', 'init'], cwd=BK, capture_output=True)
subprocess.run(['git', 'add', '-A'], cwd=BK, capture_output=True)
r = subprocess.run(['git', 'commit', '-m', f'Auto-backup: {DATE}', '--allow-empty'], cwd=BK, capture_output=True, text=True)
print('backup:', (r.stdout or r.stderr).strip()[:100])
