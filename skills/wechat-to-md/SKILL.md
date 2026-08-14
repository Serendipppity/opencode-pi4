---
name: wechat_to_md
description: 将微信公众号文章链接转换为 Markdown 全文。
---
# Wechat to Markdown 技能

## 概述
此技能通过无头浏览器渲染微信公众号网页，并提取正文内容转换为 Markdown 格式，方便 Agent 阅读和处理。

## 依赖
- **Python 解释器**: #!python3
- **库**: playwright, html2text
## 使用示例
```bash
exec /workspace/skills/WechattoMD_wjw/wechat_to_md.py "https://mp.weixin.qq.com/s/xxxx"
````
