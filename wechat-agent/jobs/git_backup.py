#!/home/pi/agent-venv/bin/python3
"""每日聚合备份：workspace + skills + 画像 + soul + wechat-agent（密钥排除）"""
import subprocess, os, datetime, shutil, re, sys

HOME = '/home/pi'
DATE = datetime.datetime.now().strftime('%Y-%m-%d')
BK = f'{HOME}/agent-backup'
SRC = [
    (f'{HOME}/agent-workspace', 'workspace'),
    (f'{HOME}/.config/opencode/skills', 'skills'),
    (f'{HOME}/.config/opencode/AGENTS.md', 'AGENTS.md'),
    (f'{HOME}/.config/opencode/agents', 'agents'),
    # opencode 配置文件（无明文机密，可安全备份）
    (f'{HOME}/.config/opencode/opencode.json', 'opencode.json'),
    (f'{HOME}/.config/opencode/opencode.jsonc', 'opencode.jsonc'),
    (f'{HOME}/.config/opencode/opencode-mem.jsonc', 'opencode-mem.jsonc'),
    (f'{HOME}/.config/opencode/tui.json', 'tui.json'),
    # discord token（git-crypt 自动加密后入库）
    (f'{HOME}/.config/opencode/discord-channel.json', 'discord-channel.json'),
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
    subprocess.run(['git', 'remote', 'add', 'origin', 'git@github.com:Serendipppity/opencode-pi4.git'], cwd=BK, capture_output=True)
# 确保远程指向 opencode-pi4（单仓库统一备份）
remotes = subprocess.run(['git', 'remote', 'get-url', 'origin'], cwd=BK, capture_output=True, text=True).stdout.strip()
if remotes != 'git@github.com:Serendipppity/opencode-pi4.git':
    subprocess.run(['git', 'remote', 'set-url', 'origin', 'git@github.com:Serendipppity/opencode-pi4.git'], cwd=BK, capture_output=True)
subprocess.run(['git', 'add', '-A'], cwd=BK, capture_output=True)
r = subprocess.run(['git', 'commit', '-m', f'Auto-backup: {DATE}', '--allow-empty'], cwd=BK, capture_output=True, text=True)
result = (r.stdout or r.stderr).strip()[:100]
print('backup:', result)
# 推送异地（git-crypt 加密文件随密文推送）
push = subprocess.run(['git', 'push', 'origin', 'HEAD:main'], cwd=BK, capture_output=True, text=True)
print('push:', (push.stdout or push.stderr).strip()[:80])

# Discord 通知
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from notify_discord import send_notification
    short = subprocess.run(['git', '-C', BK, 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
    send_notification(f'✅ 每日 Git 备份完成 {DATE} commit={short} ({result})')
except Exception as e:
    print('[!] Discord 通知失败:', e)
