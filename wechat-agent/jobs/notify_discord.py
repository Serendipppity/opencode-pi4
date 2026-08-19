#!/home/pi/agent-venv/bin/python3
# -*- coding: utf-8 -*-
"""发送文本通知到 Discord（独立于 opencode 插件，供 cron 任务调用）"""
import json
import os
import sys
import time

import requests

CONFIG_PATH = os.path.expanduser("~/.config/opencode/discord-channel.json")
DEFAULT_CHANNEL = "1483731735131848747"


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"读取配置失败: {e}")
        return None


def send_notification(content, channel_id=None):
    config = load_config()
    if not config:
        return 1
    token = config.get("botToken")
    if not token:
        print("Discord Token 未配置！")
        return 1
    channel_id = channel_id or DEFAULT_CHANNEL
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    payload = {"content": content}
    for attempt in range(5):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=20)
            if r.status_code == 429:
                time.sleep(r.json().get("retry_after", 5))
                continue
            r.raise_for_status()
            return 0
        except requests.exceptions.RequestException as e:
            print(f"[Network Error] ({attempt+1}/5): {e}")
            time.sleep(2 ** attempt)
    print("通知发送失败")
    return 1


if __name__ == "__main__":
    content = sys.argv[1] if len(sys.argv) > 1 else ""
    channel = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_CHANNEL
    sys.exit(send_notification(content, channel))