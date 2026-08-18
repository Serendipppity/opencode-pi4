---
name: discord-send-file
description: 把 Pi 本地文件作为附件发送到当前 Discord 频道。用户要求发文件/发附件/把 X 发给我时使用。走 Discord REST API 直发，绕过插件不支持附件的限制。
---

# Discord Send File

把 Pi 上的文件作为 Discord 附件直接发给用户（opencode-discord-channel 插件只转发文本，本 skill 用 Discord REST API 直发附件）。

## 用法

执行脚本，第一个参数为文件绝对路径，第二个参数可选附带消息：

~/.config/opencode/skills/discord-send-file/scripts/send-file.sh [FILE_PATH] [附带消息]

- FILE_PATH：文件绝对路径（必须存在）
- 附带消息（可选）：默认 "📎 附件"
- 输出：成功显示 ✅ + 附件 URL；失败显示错误原因

## 限制

- 单文件不超过 8MB（Discord bot 上传上限）
- 发送目标是桥频道 1483731735131848747
- 大文件/多文件：先压缩（tar.gz）再发，或告知用户文件太大

## 流程

1. 确认文件存在且路径正确
2. 运行脚本
3. 成功则简短确认（附文件名）；失败则读错误信息并修正
