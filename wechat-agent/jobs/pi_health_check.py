#!/home/pi/agent-venv/bin/python3
# -*- coding: utf-8 -*-
"""Pi 健康巡检：每日推送运行状态 + opencode 配置快照到 Discord PMO 频道
检查项：Git 备份 / Syncthing / 系统资源与重启 / 必活服务 / 模型清单 / 三层网络 / Gemini API 连通
"""
import datetime
import glob
import json
import os
import re
import shutil
import socket
import ssl
import subprocess

# cron 环境无 XDG_RUNTIME_DIR，补上才能查询 systemd --user 单元（否则 syncthing 误报）
os.environ.setdefault('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
import sys
import time
import urllib.request

HOME = '/home/pi'
PMO_CHANNEL = '1483731735131848747'
UPTIME_CACHE = f'{HOME}/.cache/health_last_uptime.json'
BK_REPO = f'{HOME}/agent-backup'
BACKUP_STATUS = f'{HOME}/.cache/backup_status/git_backup.json'
SYNCTHING_XML = f'{HOME}/.local/state/syncthing/config.xml'
SYNCTHING_API = 'http://127.0.0.1:8384'
AUTH_JSON = f'{HOME}/.local/share/opencode/auth.json'
OPENCODE_JSONC = f'{HOME}/.config/opencode/opencode.jsonc'
AGENTS_DIR = f'{HOME}/.config/opencode/agents'
GATEWAY = '192.168.1.100'
TH_TEMP, TH_MEM_MB, TH_DISK_PCT, TH_LOAD15 = 75.0, 200, 85.0, 4.0
GEMINI_PING_MODEL = 'gemini-3.5-flash-lite'
TODAY = datetime.datetime.now().strftime('%Y-%m-%d')
NOW = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')


def _ok(flag):
    return '✅' if flag else '❌'


def _run(cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def _http(url, timeout=6, data=None, headers=None):
    """返回 (status_code, body_bytes, elapsed_ms)；失败返回 (0, b'', ms)"""
    start = time.time()
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), int((time.time() - start) * 1000)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), int((time.time() - start) * 1000)
    except Exception:
        return 0, b'', int((time.time() - start) * 1000)


# ---------- 1. Git ----------
def check_git():
    lines, bad = [], False
    try:
        d = json.load(open(BACKUP_STATUS))
        push_ok = bool(d.get('push_ok'))
        fresh = d.get('date') == TODAY
        lines.append(f"{_ok(push_ok and fresh)} 昨夜文件备份: {'push OK' if push_ok else 'push 失败'} ({d.get('date', '?')})")
        bad |= not (push_ok and fresh)
    except Exception:
        lines.append('❌ 昨夜文件备份: 无记录')
        bad = True
    r = _run(['git', '-C', BK_REPO, 'status', '--porcelain'])
    dirty = len([l for l in (r.stdout if r else '').splitlines() if l.strip()])
    r2 = _run(['git', '-C', BK_REPO, 'rev-list', '--count', 'origin/main..HEAD'])
    ahead = (r2.stdout.strip() if r2 and r2.stdout.strip().isdigit() else '?')
    unpushed = not (ahead == '0')
    lines.append(f"{_ok(not unpushed)} 未提交变更: {dirty} | 领先远程: {ahead}")
    bad |= unpushed
    return bad, '\n'.join(lines)


# ---------- 2. Syncthing ----------
def check_syncthing():
    svc = _run(['systemctl', '--user', 'is-active', 'syncthing'])
    active = (svc.stdout.strip() == 'active') if svc else False
    lines = [f"{_ok(active)} systemd --user 服务: {svc.stdout.strip() if svc else '?'}"]
    bad = not active
    try:
        key = re.search(r'<apikey>([^<]+)</apikey>', open(SYNCTHING_XML).read()).group(1)
        st, body, _ = _http(f'{SYNCTHING_API}/rest/config/folders',
                            headers={'X-API-Key': key})
        if st != 200:
            raise RuntimeError(f'REST HTTP {st}')
        for f in json.loads(body):
            fid = f['id']
            st2, body2, _ = _http(f'{SYNCTHING_API}/rest/db/status?folder={fid}',
                                  headers={'X-API-Key': key})
            if st2 != 200:
                raise RuntimeError(f'db/status HTTP {st2}')
            s = json.loads(body2)
            state = s.get('state', '?')
            need = s.get('needFiles', 0)
            healthy = state in ('idle',) and need == 0
            lines.append(f"{_ok(healthy)} folder[{fid}]: state={state} 待同步文件={need}")
            bad |= not healthy
    except Exception as e:
        lines.append(f'❌ REST API 异常: {e}')
        bad = True
    return bad, '\n'.join(lines)


# ---------- 3. 系统 ----------
def check_system():
    lines, bad = [], False
    try:
        up_sec = float(open('/proc/uptime').read().split()[0])
        prev = None
        try:
            prev = json.load(open(UPTIME_CACHE)).get('uptime')
        except Exception:
            pass
        rebooted = prev is not None and up_sec < prev - 300
        if rebooted:
            lines.append('⚠️ 检测到系统重启过（uptime 变小）')
            bad = True
        try:
            os.makedirs(os.path.dirname(UPTIME_CACHE), exist_ok=True)
            json.dump({'uptime': up_sec, 'at': NOW}, open(UPTIME_CACHE, 'w'))
        except Exception:
            pass
        days, rem = int(up_sec // 86400), int(up_sec % 86400)
        up_str = f'{days}天{rem // 3600}h{(rem % 3600) // 60}m'
        temp = int(open('/sys/class/thermal/thermal_zone0/temp').read()) / 1000.0
        meminfo = {}
        for l in open('/proc/meminfo'):
            if ':' in l:
                k, v = l.split(':', 1)
                meminfo[k] = int(v.strip().split()[0])
        mem_avail_mb = meminfo['MemAvailable'] // 1024
        du = shutil.disk_usage('/')
        disk_pct = round(du.used / du.total * 100, 1)
        load15 = os.getloadavg()[2]
        t_ok = temp <= TH_TEMP
        m_ok = mem_avail_mb >= TH_MEM_MB
        d_ok = disk_pct <= TH_DISK_PCT
        l_ok = load15 <= TH_LOAD15
        lines.append(f"{'✅' if t_ok else '❌'} 温度: {temp:.1f}°C")
        lines.append(f"{'✅' if m_ok else '❌'} 内存可用: {mem_avail_mb}MB")
        lines.append(f"{'✅' if d_ok else '❌'} 磁盘: {disk_pct}%")
        lines.append(f"{'✅' if l_ok else '❌'} load15: {load15:.2f}")
        lines.append(f"ℹ️ uptime: {up_str}")
        bad |= not (t_ok and m_ok and d_ok and l_ok)
    except Exception as e:
        lines.append(f'❌ 系统指标采集异常: {e}')
        bad = True
    return bad, '\n'.join(lines)


# ---------- 4. 必活服务 ----------
def check_services():
    checks = [
        ('syncthing', ['systemctl', '--user', 'is-active', 'syncthing'], 'active'),
        ('kimaki', ['pgrep', '-f', 'bin/kimaki'], None),
        ('cron', ['systemctl', 'is-active', 'cron'], 'active'),
    ]
    lines, bad = [], False
    for name, cmd, want in checks:
        r = _run(cmd, timeout=5)
        if r is None:
            alive, detail = False, '执行失败'
        elif want is None:
            alive, detail = r.returncode == 0, ''
        else:
            alive, detail = r.stdout.strip() == want, r.stdout.strip()
        lines.append(f"{_ok(alive)} {name}" + (f' ({detail})' if detail and not alive else ''))
        bad |= not alive
    return bad, '\n'.join(lines)


# ---------- 5. 模型清单（纯展示，不影响健康判定；同配置归并为组） ----------
def check_models():
    lines = []
    providers, default_model = [], '?'
    try:
        auth = json.load(open(AUTH_JSON))
        providers = sorted(auth.keys())
    except Exception:
        pass
    try:
        raw = open(OPENCODE_JSONC).read()
        m = re.search(r'"model"\s*:\s*"([^"]+)"', raw)
        default_model = m.group(1) if m else '?'
    except Exception:
        pass

    def short(m):
        return m.split('/', 1)[1] if '/' in m else m

    rows = []
    for md_path in sorted(glob.glob(f'{AGENTS_DIR}/*.md')):
        name = os.path.basename(md_path)[:-3]
        text = open(md_path, encoding='utf-8').read(2048)
        fm = text.split('---')[1] if text.startswith('---') and '---' in text[3:] else ''
        m_model = re.search(r'^model:\s*(\S+)', fm, re.M)
        m_fb = re.search(r'^fallback:\s*(\S+)', fm, re.M)
        rows.append((name, m_model.group(1) if m_model else '(default)',
                     m_fb.group(1) if m_fb else '-'))
    lines.append(f'providers: {", ".join(providers)} | 默认模型: {short(default_model)}')
    groups = {}
    for name, model, fb in rows:
        groups.setdefault((model, fb), []).append(name)
    for (model, fb), names in groups.items():
        line = f"- **{'、'.join(names)}**: `{short(model)}`"
        if fb != '-':
            line += f' → fb: `{short(fb)}`'
        lines.append(line)
    return False, '\n'.join(lines)


# ---------- 6. 网络 ----------
def check_network():
    import statistics
    lines, bad = [], False

    r = _run(['ping', '-c', '3', '-W', '2', GATEWAY], timeout=12)
    times = [float(m) for m in re.findall(r'time=(\d+\.?\d*) ms', r.stdout)] if r and r.returncode == 0 else []
    if times:
        avg = statistics.mean(times)
        lines.append(f'✅ 内网网关({GATEWAY}): 平均 {avg:.1f}ms')
    else:
        lines.append(f'❌ 内网网关({GATEWAY}): ping 不通')
        bad = True

    start = time.time()
    try:
        ip = socket.gethostbyname('www.baidu.com')
        ctx = ssl.create_default_context()
        with socket.create_connection((ip, 443), timeout=5) as sock:
            t0 = time.time()
            with ctx.wrap_socket(sock, server_hostname='www.baidu.com'):
                pass
        lines.append(f'✅ 国内公网(baidu.com): DNS+TLS {int((time.time() - start) * 1000)}ms')
    except Exception as e:
        lines.append(f'❌ 国内公网: {e}')
        bad = True

    st, _, ms = _http('https://www.google.com/generate_204', timeout=6)
    if st == 204:
        lines.append(f'✅ 墙外(google 204): {ms}ms')
    else:
        lines.append(f'❌ 墙外(google 204): HTTP {st or "超时"} ({ms}ms)')
        bad = True
    return bad, '\n'.join(lines)


# ---------- 7. Gemini API ----------
def check_gemini():
    try:
        key = json.load(open(AUTH_JSON)).get('google', {}).get('key', '')
        if not key:
            return True, '❌ 无 google API key'
        url = (f'https://generativelanguage.googleapis.com/v1beta/models/'
               f'{GEMINI_PING_MODEL}:generateContent?key={key}')
        body = json.dumps({
            'contents': [{'parts': [{'text': 'reply ok'}]}],
            'generationConfig': {'maxOutputTokens': 5},
        }).encode()
        st, _, ms = _http(url, timeout=15, data=body,
                          headers={'Content-Type': 'application/json'})
        if st == 200:
            return False, f'✅ {GEMINI_PING_MODEL} 连通 {ms}ms'
        tail = ''
        return True, f'❌ {GEMINI_PING_MODEL} HTTP {st or "超时"} ({ms}ms){tail}'
    except Exception as e:
        return True, f'❌ Gemini 探测异常: {e}'


def main():
    sections = []
    failed = []
    for title, fn in [('Git', check_git), ('Syncthing', check_syncthing),
                      ('系统', check_system), ('服务存活', check_services),
                      ('模型清单', check_models), ('网络', check_network),
                      ('Gemini API', check_gemini)]:
        try:
            bad, detail = fn()
        except Exception as e:
            bad, detail = True, f'检查器异常: {e}'
        icon = '✅' if not bad else '❌'
        body_lines, in_code = [], False
        for l in detail.splitlines():
            if l.startswith('```'):
                in_code = not in_code
                body_lines.append(l)
            elif in_code or l.startswith((' ', '\t')):
                body_lines.append(l)
            else:
                body_lines.append('- ' + l)
        sections.append(f'{icon} **{title}**\n' + ('\n'.join(body_lines) or '- (无内容)'))
        if bad:
            failed.append(title)

    content = f'🖥️ **Pi 健康巡检** {NOW}\n\n' + '\n\n'.join(sections)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from notify_discord import send_notification

    print(content, flush=True)
    if '--dry' in sys.argv:
        print('[dry] 未发送', flush=True)
        return 0
    r1 = send_notification(content, channel_id=PMO_CHANNEL)
    print('push discord summary:', r1, flush=True)
    if failed:
        r2 = send_notification(f'⚠️ 巡检异常项: {"、".join(failed)}（详见上方汇总）', channel_id=PMO_CHANNEL)
        print('push discord alert:', r2, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
