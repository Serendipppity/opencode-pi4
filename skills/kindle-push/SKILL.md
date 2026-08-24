---
name: kindle-push
description: 推送电子书到 Kindle。当用户说「推送到 kindle」「发到 kindle」「把 X 推到 kindle」「把 X 发到 kindle」时使用。从本地目录或 Google Drive 检索电子书，通过 gog 邮件发送到 Kindle 邮箱。
---

# kindle-push

将本地或 Google Drive 上的电子书（epub/pdf）通过 Send-to-Kindle 邮箱推送到 Kindle。

## 前置配置（一次性）

1. **gog 已授权**：`GOG_KEYRING_PASSWORD` 能解锁 keyring，账号含 gmail + drive 服务。
2. **config.json**：`~/.config/opencode/skills/kindle-push/config.json`
   - `kindle_email`：你的 Kindle 邮箱（当前 `writetowjw_QXMfhS@kindle.com`）
   - `account`：gog 账号（`woeragent@gmail.com`）
   - `keyring_password`：gog keyring 密码（必须填，否则脚本报错）
   - `local_dirs`：本地搜索目录
3. **亚马逊白名单**：`woeragent@gmail.com` 已加入「个人文档设置」已认可发件人列表。

## 用法

```
python3 scripts/kindle_push.py "三体"
```

- 按书名模糊匹配，本地与 Drive 并行检索。
- 多个结果列出供选择（`序号. [来源] 文件名`）。
- 仅支持 `.epub` / `.pdf`，且 ≤25MB。
- `--no-drive` 跳过 Drive 搜索，只搜本地。
- Drive 文件下载到临时目录，发送后自动清理。

## 依赖

- `gog` CLI（`~/bin/gog`）
- Python 标准库（无第三方包）
