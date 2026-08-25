---
name: kindle-push
description: MUST USE when user wants to 推送电子书/传书/发书到 Kindle，如「把 X 推送到 kindle」「发到 kindle」「传书」「send to kindle」。从本地目录或 Google Drive 检索 epub/pdf 电子书，经 gog 邮件发送到 Kindle 邮箱。直接用 skill 工具加载本 skill 执行 scripts/kindle_push.py，禁止用 glob/find 搜索 skill 文件或自己拼 gog 命令。
---

# kindle-push

将本地或 Google Drive 上的电子书（epub/pdf）通过 Send-to-Kindle 邮箱推送到 Kindle。

## 用法（直接跑脚本，无需读源码）

```bash
python3 ~/.config/opencode/skills/kindle-push/scripts/kindle_push.py "书名"
```

- 按书名模糊匹配，本地与 Google Drive 并行检索
- 多候选时输出编号列表并退出（exit code 2）——**非交互场景**（Discord/微信 agent）转述列表让用户选，然后带 `--select <序号>` 重跑；或 `--auto` 直接选第一个
- 仅支持 `.epub` / `.pdf`，且 ≤25MB；mobi 会报错提示先转 epub
- `--no-drive` 跳过 Drive 搜索；Drive 文件自动下载并在发送后清理

## Agent 调用规范

1. **必须直接执行上述命令**，不要 glob/find 查找脚本位置，不要读 config.json 和源码
2. 用户给的是明确文件路径时直接传路径
3. exit code 含义：0 成功 / 1 失败（stderr 有原因）/ 2 多候选待选
4. gog 路径已内置探测（~/bin/gog 等），无需设置 PATH

## 前置配置（已完成）

- gog 已授权 `woeragent@gmail.com`（gmail + drive），keyring 密码在 config.json
- Kindle 邮箱：`writetowjw_QXMfhS@kindle.com`（config.json 可改）
- 亚马逊白名单需含 `woeragent@gmail.com`，否则亚马逊静默丢信（Kindle 收不到且无任何通知）
