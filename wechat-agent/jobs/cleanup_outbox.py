#!/usr/bin/env python3
"""清理 outbox 中已同步到 Mac 的旧文件（>24h 且同步完成）"""
import os, time, glob, json, urllib.request, urllib.parse

OUTBOX = os.path.expanduser('~/agent-workspace/outbox_obsidian/news_archives')
MAX_AGE = 86400  # 24小时
API_KEY = 'A4dMaY3GkFzsh6KgXRQYeVrMnQYg3JQM'
API_URL = 'http://localhost:8384'

def check_sync_complete():
    """检查是否所有文件已送达 Mac"""
    try:
        url = f'{API_URL}/rest/db/status?folder=pi-outbox'
        req = urllib.request.Request(url, headers={'X-API-Key': API_KEY})
        with urllib.request.urlopen(req, timeout=5) as resp:
            d = json.loads(resp.read())
            need = d.get('needFiles', 0) + d.get('needBytes', 0)
            state = d.get('state', '?')
            return need == 0 and state == 'idle'
    except Exception:
        return False  # API 不可用时跳过清理，安全优先

def cleanup():
    if not check_sync_complete():
        print('同步未完成，跳过清理')
        return

    now = time.time()
    count = 0
    for f in glob.glob(os.path.join(OUTBOX, '*')):
        if os.path.isfile(f) and not f.endswith('.stfolder') and now - os.path.getmtime(f) > MAX_AGE:
            os.remove(f)
            count += 1
    if count:
        print(f'清理 {count} 个旧文件')
    else:
        print('无过期文件')

cleanup()
