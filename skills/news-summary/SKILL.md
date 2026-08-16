---
name: news-summary
description: 每日新闻简报全自动管线（抓料→生成→排版→推送公众号）。一条命令出早/午/晚报；也可单跑抓料、单出 Markdown。开箱即用。
---

# News Summary

## Overview
每日新闻简报工具，自动完成：抓 RSS → LLM 生成双语简报 → 微信排版 → 推送公众号。
脚本已随 skill 打包（scripts/ 下），绝对路径已写死，开箱即用，无需额外配置。

## 一键生成并推送

### 推送整份简报（公众号图文）
```bash
python3 /home/pi/.config/opencode/skills/news-summary/scripts/news_brief.py 早
python3 /home/pi/.config/opencode/skills/news-summary/scripts/news_brief.py 午
python3 /home/pi/.config/opencode/skills/news-summary/scripts/news_brief.py 晚
```

### 只生成不推送（预览）
```bash
python3 /home/pi/.config/opencode/skills/news-summary/scripts/news_brief.py 早 --dry
# 产物: /tmp/brief_final.html（浏览器直接打开预览）
```

### 只抓材料（不做简报）
```bash
python3 /home/pi/.config/opencode/skills/news-summary/scripts/parse_rss.py
# 材料打印到 stdout，同时归档到底稿目录
```

### 定时任务（cron 已配）
```
0 8   * * * 早报   0 12 * * * 午报   30 20 * * * 晚报   0 2 * * * git 备份
```

## 管线说明（一键做了什么）

```
news_brief.py
 ├─ parse_rss.py         抓 8 源 RSS（BBC/NPR/AlJazeera + 华尔街见闻 API + RSSHub）
 ├─ fetch_extra_sources  直连补抓财经源（Wallstreetcn API + RSSHub 三实例容灾）
 ├─ opencode run --agent brief   LLM 按模板生成双语 Markdown
 ├─ format.py            微信排版（xiaohu-wechat-format skill，主题 wjbrief）
 ├─ clean_brief.py       后处理清洗（URL 13px / 英文副标题 17px / 去字面标记）
 └─ push.py              封面生成 + 图文群发公众号
```

## Standard Output Format（简报内容标准）

📰 Daily Briefing | [YYYY-MM-DD] [早/午/晚报]
1. [中文标题] `源标签`
   English subtitle
   🄲 中文摘要（2-3句）
   🄴 English summary (2-3 sentences)
   URL https://link

- 分区：核心要闻 / 国际风云 / 财经速递 / 科技前沿 / 国内要闻（5 区）
- 编号 1-12 连续，共 10-12 条
- 每条：`**N. 中文标题**` + `` `源标签` `` + 英文副标题 + 引用块（🄲🄴 URL 三行）
- 标题/分区不加 emoji；优先 [⭐高相关]（匹配 user_prefs.json 关键词）

## 用户偏好
`~/agent-workspace/user_prefs.json`：
- `focus_keywords`：高相关标记（如 AI/OpenAI/苹果/半导体/美联储/降息）
- `ignore_keywords`：跳过（体育/娱乐/车祸/八卦）
- 编辑即生效，下次运行自动重读

## 关键文件
| 文件 | 职责 |
|------|------|
| scripts/news_brief.py | 主流程（一键管线） |
| scripts/parse_rss.py | 抓料 |
| scripts/clean_brief.py | HTML 后处理 |
| ~/wechat-agent/jobs/ | cron 执行入口（软链指向本 skill scripts） |
| ~/.config/opencode/skills/xiaohu-wechat-format/ | 微信排版引擎 |
| ~/wechat-agent/docs/brief-format.md | 格式规范详版 |

## 备注
- 旧版"手动抓料→人工总结"流程已废弃，被全自动管线取代。
- 推送走测试号图文，封面为风景图+日期时段（covers/ 下早/午/晚各一张）。
