---
name: xhs-to-md
description: 将小红书笔记链接（含 xhslink 短链）转换为 Markdown，图片以 base64 内嵌。当用户说「小红书转 md」「把这个小红书链接转成 md」「读取小红书笔记」「xhs 转 markdown」时使用。
---

# 小红书笔记 → Markdown

## 功能
- 支持短链（xhslink.cn/xhslink.com）自动展开
- 抓取标题、正文、作者、时间、互动数据、标签
- 图片全部下载并以 base64 内嵌进 md，单文件可迁移
- 无需登录、无需 cookie、无需 API key

## 用法
```bash
python3 ~/.config/opencode/skills/xhs-to-md/xhs_to_md.py "链接"
```

### 常用参数
| 参数 | 说明 |
|------|------|
| `-o 文件.md` | 指定输出路径 |
| `--out-dir DIR` | 输出到目录（默认当前目录），文件名自动取标题 |
| `--no-images` | 不要图片，只留正文 |

## 典型流程
1. 展开短链 → 抓取页面 HTML → 解析 `__INITIAL_STATE__` JSON
2. 提取笔记字段，下载 imageList 中每张图
3. 图片 base64 编码，以 `![图N](data:image/jpeg;base64,...)` 内嵌
4. 输出 md，打印结果路径与统计

## 注意事项
- 若笔记需要登录（解析不到 noteData），尝试更换 UA 重试；仍失败则告知用户该笔记不可见
- 图片 URL 使用 https 访问，请求带 Referer `https://www.xiaohongshu.com/`
- 结果默认输出到当前目录；用户归档习惯输出到 `~/agent-workspace/outbox_obsidian/`
