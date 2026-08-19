#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import json
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import os

CHANNEL_ID = "1484060949903048778"
CONFIG_PATH = os.path.expanduser("~/.config/opencode/discord-channel.json")


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"读取配置失败: {e}")
        return None


def create_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["POST"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def send_message(session, token, content):
    url = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }
    payload = {"content": content}
    max_retries = 8

    for attempt in range(max_retries):
        try:
            response = session.post(url, headers=headers, json=payload, timeout=20)

            if response.status_code == 429:
                retry_after = response.json().get("retry_after", 5)
                is_global = response.headers.get("X-RateLimit-Global", "false") == "true"
                print(f"[Rate Limit] 429 (global={is_global}), sleep {retry_after}s...")
                time.sleep(retry_after)
                continue

            response.raise_for_status()

            remaining = response.headers.get("X-RateLimit-Remaining")
            reset_after = response.headers.get("X-RateLimit-Reset-After")
            if remaining and int(remaining) == 0 and reset_after:
                print(f"[Rate Limit] 额度耗尽, sleep {reset_after}s...")
                time.sleep(float(reset_after))

            return True

        except requests.exceptions.RequestException as e:
            print(f"[Network Error] ({attempt+1}/{max_retries}): {e}")
            time.sleep(2 ** attempt)

    print("达到最大重试次数，推送失败。")
    return False


def split_text_into_chunks(text, max_len=1900):
    chunks = []
    paragraphs = text.split("\n\n")
    current_chunk = ""

    for para in paragraphs:
        if len(current_chunk) + len(para) + 2 > max_len:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = para + "\n\n"
        else:
            current_chunk += para + "\n\n"

    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks


def push_to_discord(md_path):
    config = load_config()
    if not config:
        return 1

    token = config.get("botToken")
    if not token:
        print("Discord Token 未配置！")
        return 1

    try:
        with open(md_path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        print(f"读取文件失败: {e}")
        return 1

    session = create_session()
    chunks = split_text_into_chunks(text, max_len=1900)
    total = len(chunks)
    success = 0

    for i, chunk in enumerate(chunks):
        if send_message(session, token, chunk):
            print(f"✅ Part {i+1}/{total}")
            success += 1
        else:
            print(f"❌ Part {i+1}/{total}")

        if (i + 1) % 4 == 0 and i < total - 1:
            time.sleep(5)
        elif i < total - 1:
            time.sleep(1)

    print(f"[+] 已推送 {success}/{total} 条消息到 Discord")
    return 0 if success == total else 1


if __name__ == "__main__":
    md_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/brief.md"
    sys.exit(push_to_discord(md_path))
