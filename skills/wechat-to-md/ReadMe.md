# Wechat to Markdown Skill

## 功能
- 微信公众号文章 → Markdown 全文
- 图片本地化：`images/<文章key>/figNN.jpg`，正文用相对路径引用
- 文首写原文链接，元信息块对齐中金研报归档格式
- 直连被验证码拦截时回退 Wechat2RSS 订阅源

## 安装
```bash
/home/pi/agent-venv/bin/pip install playwright html2text
/home/pi/agent-venv/bin/playwright install chromium
chmod +x ~/.config/opencode/skills/wechat-to-md/wechat_to_md.py
```

## 文件
| 文件 | 作用 |
|------|------|
| `wechat_to_md.py` | 主脚本 |
| `feeds.json` | Wechat2RSS 回退源：`公众号名 → feed id` |

## 用法
```bash
python3 wechat_to_md.py "https://mp.weixin.qq.com/s/xxx" [--out-dir DIR] [-o FILE] [--no-images] [--stdout]
```

## 说明
- 微信对数据中心 IP 有验证码风控，直连失败属预期，脚本会自动回退
- 回退只覆盖 `feeds.json` 中已订阅公众号的最近 10 篇
- 图片下载 3 次重试，失败保留原链
- 默认输出到 `~/agent-workspace/outbox_obsidian/articles_微信/`
