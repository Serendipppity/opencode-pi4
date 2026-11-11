---
name: wechat_to_md
description: 将微信公众号文章链接转换为 Markdown 全文，图片自动本地化归档。当用户说「微信转 md」「公众号文章转 markdown」「把这个微信链接转成 md」「保存这篇公众号文章」时使用。
---

# 微信公众号 → Markdown

## 功能
- 抓取标题、公众号、作者、发布时间、正文全文
- 图片自动下载到本地 `images/<文章key>/figNN.jpg`，正文改写为相对路径，单目录可整体迁移
- 文首固定写入 **原文链接**，格式与中金研报归档（`fetch_cicc_reports.py`）一致
- 直连被微信验证码拦截时，自动回退到 Wechat2RSS 订阅源取正文

## 用法
```bash
/home/pi/agent-venv/bin/python3 ~/.config/opencode/skills/wechat-to-md/wechat_to_md.py "链接"
```

### 常用参数
| 参数 | 说明 |
|------|------|
| `-o 文件.md` | 指定输出路径 |
| `--out-dir DIR` | 输出目录，默认 `~/agent-workspace/outbox_obsidian/articles_微信`；文件名自动取 `日期_标题.md` |
| `--no-images` | 不下载图片，正文保留原始直链 |
| `--stdout` | 只打印到标准输出，不落盘 |

## 输出格式
```markdown
# 标题

> **原文链接**：https://mp.weixin.qq.com/s?...

- **公众号**：xxx
- **作者**：xxx
- **发布时间**：2026-11-10 07:50:00
- **抓取时间**：2026-11-11 11:40:00
- **正文长度**：6812 字 | **图片**：26 张（已本地化）

---

正文……图片为 ![](images/2026-11-10_标题/fig01.jpg)
```

## 抓取链路
1. Playwright 直连 `mp.weixin.qq.com`（拿完整元数据）
2. 命中 `wappoc_appmsgcaptcha` 或正文为空 → 按 URL 的 `mid/sn` 在 `feeds.json` 的 Wechat2RSS 源里匹配正文
3. 图片地址若被 Wechat2RSS 包成 `img-proxy`，自动还原为原始 `mmbiz.qpic.cn` 直链再下载
4. 图片下载失败会重试 3 次，仍失败则保留原链，不中断

## 注意事项
- 依赖 `playwright` + `html2text`，解释器固定 `/home/pi/agent-venv/bin/python3`
- 微信对本机 IP 常驻验证码，直连基本必失败，实际走 Wechat2RSS 回退；回退只覆盖 `feeds.json` 里已订阅公众号的近 10 篇
- 想新增可回退的公众号：往 `feeds.json` 加 `"公众号名": "wechat2rss feed id"`
- 默认归档到 `~/agent-workspace/outbox_obsidian/articles_微信/`（正文 + `images/`），无需额外参数
