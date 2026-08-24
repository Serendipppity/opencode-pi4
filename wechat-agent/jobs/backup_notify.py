#!/home/pi/agent-venv/bin/python3
# -*- coding: utf-8 -*-
"""每日备份合并通知：读 02:00 git_backup 状态文件 + 接收 03:00 数据快照状态，合成一条 Discord 消息

用法: backup_notify.py [committed yes|no] [pushed yes|no] [commit_short] [--dry]
  --dry 只打印消息不发送
"""
import json
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STATUS_FILE = os.path.expanduser('~/.cache/backup_status/git_backup.json')


def git_part(today):
    try:
        with open(STATUS_FILE, encoding='utf-8') as f:
            d = json.load(f)
    except Exception:
        return '⚠️ Git 文件备份(02:00): 无记录（任务可能未运行）'
    if d.get('date') != today:
        return f"⚠️ Git 文件备份(02:00): 记录过期({d.get('date')})"
    mark = '✅' if d.get('push_ok') else '❌'
    note = '' if d.get('push_ok') else ' push 失败'
    return f"{mark} Git 文件备份(02:00): commit={d.get('commit', '?')}{note}"


def data_part(committed, pushed, short=''):
    c_mark = '✅' if committed else '➖'
    c_note = f'commit={short}' if committed and short else ('committed' if committed else '无变更')
    p_mark = '✅' if pushed else '❌'
    p_note = 'pushed' if pushed else 'push 失败'
    return f'{c_mark} 数据快照(03:00): {c_note}, {p_mark}{p_note}'


def main():
    args = [a for a in sys.argv[1:] if a != '--dry']
    dry = '--dry' in sys.argv
    committed = len(args) > 0 and args[0].lower() == 'yes'
    pushed = len(args) > 1 and args[1].lower() == 'yes'
    short = args[2] if len(args) > 2 else ''
    today = datetime.datetime.now().strftime('%Y-%m-%d')

    content = (f"📦 每日备份汇总 {today}\n"
               f"{git_part(today)}\n"
               f"{data_part(committed, pushed, short)}")
    print(content)
    if dry:
        print('[dry] 未发送')
        return 0

    from notify_discord import send_notification
    return send_notification(content)


if __name__ == '__main__':
    sys.exit(main())
