#!/usr/bin/env python3
"""微信客服 <-> opencode 薄桥：轮询拉消息，opencode run 处理，回微信"""
import json, time, urllib.request, subprocess, os, threading, sys

CFG = json.load(open(os.path.expanduser('~/wechat-agent/config.json')))
BASE = 'https://qyapi.weixin.qq.com/cgi-bin'
SEEN = set()
_lock = threading.Lock()

def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)

def api_get(at, path):
    return json.load(urllib.request.urlopen(f'{BASE}/{path}?access_token={at}', timeout=20))

def api_post(at, path, data):
    req = urllib.request.Request(f'{BASE}/{path}?access_token={at}',
        data=json.dumps(data, ensure_ascii=False).encode("utf-8"), headers={'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=20))

def get_token():
    url = f'{BASE}/gettoken?corpid={CFG["corpid"]}&corpsecret={CFG["kf_secret"]}'
    return json.load(urllib.request.urlopen(url, timeout=15))['access_token']

def send_text(at, external_userid, content):
    r = api_post(at, 'kf/send_msg', {'touser': external_userid, 'open_kfid': CFG['open_kfid'], 'msgtype': 'text',
        'text': {'content': content}})
    if r.get('errcode') != 0:
        log('send fail:', r)

def run_opencode(msg):
    """调 opencode run 生成回复（工作目录 agent-workspace，加载 AGENTS.md + skills）"""
    try:
        p = subprocess.run(['/home/pi/.opencode/bin/opencode', 'run', msg],
            cwd='/home/pi/agent-workspace', capture_output=True, text=True, timeout=600)
        out = (p.stdout or '') + ('' if p.returncode == 0 else (p.stderr or '')[-800:])
        return out.strip()[:1800] or '(opencode 无输出)'
    except subprocess.TimeoutExpired:
        return '(处理超时，10 分钟，请重试)'
    except Exception as e:
        return f'(opencode 调用失败: {e})'

def handle_msg(at, msg):
    ext = msg.get('external_userid')
    if not ext:
        return
    text = ''
    if msg.get('msgtype') == 'text':
        text = msg.get('text', {}).get('content', '')
    elif msg.get('msgtype') == 'event' and msg.get('event_type') == 'enter_session':
        text = '你好，直接发问题给我。'
    if not text:
        return
    log(f'来自 {ext[:10]}...: {text[:60]}')
    reply = run_opencode(text)
    send_text(at, ext, reply)
    log(f'已回复: {reply[:50]}...')

def main():
    log('薄桥启动，轮询微信客服...')
    cursor = ''
    try:
        cursor = json.load(open(os.path.expanduser('~/wechat-agent/cursor.json'))).get('cursor', '')
    except Exception:
        pass
    while True:
        try:
            at = get_token()
            r = sync_msg = api_post(at, 'kf/sync_msg', {'cursor': cursor, 'limit': 100})
            if r.get('errcode') != 0:
                log('sync err:', r); time.sleep(10); continue
            cursor = r.get('next_cursor', cursor)
            json.dump({'cursor': cursor}, open(os.path.expanduser('~/wechat-agent/cursor.json'), 'w'))
            for msg in r.get('msg_list', []):
                mid = msg.get('msgid')
                if mid and mid not in SEEN:
                    SEEN.add(mid)
                    threading.Thread(target=handle_msg, args=(at, msg), daemon=True).start()
            if len(SEEN) > 5000:
                SEEN.clear()
        except Exception as e:
            log('loop err:', e)
        time.sleep(15)

if __name__ == '__main__':
    main()
