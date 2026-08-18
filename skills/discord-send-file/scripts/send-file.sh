#!/bin/bash
# 把 Pi 本地文件作为附件发送到 Discord 桥频道
# 用法: send-file.sh <文件路径> [附带消息]
set -euo pipefail

FILE="$1"
MSG="${2:-📎 附件}"
CHANNEL="1483731735131848747"
CONFIG="$HOME/.config/opencode/discord-channel.json"

if [ ! -f "$CONFIG" ]; then echo "错误: 配置文件 $CONFIG 不存在"; exit 1; fi
if [ ! -f "$FILE" ]; then echo "错误: 文件不存在: $FILE"; exit 1; fi

SIZE=$(stat -c%s "$FILE")
if [ "$SIZE" -gt 8388608 ]; then echo "错误: 文件超过 8MB (实际 ${SIZE} 字节)"; exit 1; fi

TOKEN=$(jq -r .botToken "$CONFIG")
if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then echo "错误: 无法读取 botToken"; exit 1; fi

RESP=$(curl -s -X POST "https://discord.com/api/v10/channels/$CHANNEL/messages"   -H "Authorization: Bot $TOKEN"   -F "file=@$FILE"   -F "content=$MSG")

URL=$(echo "$RESP" | jq -r '.attachments[0].url // empty' 2>/dev/null)
if [ -n "$URL" ]; then
  echo "✅ 已发送: $(basename "$FILE") (${SIZE} 字节)"
  echo "$URL"
else
  echo "❌ 发送失败: $(echo "$RESP" | jq -r '.message // "未知错误"' 2>/dev/null)"
  exit 1
fi
