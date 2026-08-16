# 公众号简报格式规范（brief-format）

> 用途：固定公众号「早/午/晚报」图文格式，以后快速复用、改版。
> 链路：`news_brief.py`（材料+LLM 生成）→ `format.py`（markdown→微信 HTML）→ `clean_brief.py`（后处理清洗）→ `push.py`（封面+图文群发）

---

## 1. 字号规范表

| 元素 | 字号 | 颜色 | 说明 |
|------|------|------|------|
| 分区标题 `h2` | 28px | `#E8590C` 橙 | 核心要闻/国际风云/... 无图标无竖线 |
| 消息标题 `strong` | 22px | `#2c2c2c` | `**N. 中文标题**`，加粗 |
| 英文副标题 | 17px | `#555555` | `text-align:left` 防 justify 拉伸 |
| 摘要 `blockquote_p` | 16px | `#555555` | 🄲🄴 两段 |
| URL | 13px | `#BBBBBB` | 独立换行，`word-break:break-all` |
| 源标签 `code` | 85% | `#5E6E8C` | 灰蓝圆角标签 |

层级关系：`h2 28 > strong 22 > 英文 17 > 摘要 16 > URL 13`

### 字号在哪定义
- **视觉样式**（h2/strong/摘要/URL/code/blockquote 边框）→ `~/.config/opencode/skills/xiaohu-wechat-format/themes/wjbrief.json`（`styles` 段）
- **英文副标题 17px + 左对齐** → `~/wechat-agent/jobs/clean_brief.py`（post-process，因 markdown 解析器不产出该 span）

## 2. 模板结构（templates/brief.md）

```
# 📰 Daily Briefing | {date} {label}报

## 核心要闻

**1. 中文标题** `源标签`
English Subtitle

> 🄲 中文摘要（2-3句）。
> 🄴 English summary (2-3 sentences).
> URL
> 🄻 https://source-link.com
```

规则：
- 分区固定 5 个：核心要闻 / 国际风云 / 财经速递 / 科技前沿 / 国内要闻
- 编号 1-12 连续，共 10-12 条
- 每条 = `**编号. 标题**` + `` `源标签` `` + 英文副标题 + 引用块（🄲 🄴 URL 三行）
- 标题/分区名**不加 emoji**；引用块内 URL 行放 `> URL` 占位

## 3. 清洗规则（clean_brief.py）

`clean_html(html)` 两步：

1. **blockquote URL 处理**（三步正则）
   - 删 `URL` 字面行（含前 `<br />`，防双换行）
   - 删 `🄻` 前缀，链接包 `<span style="font-size:13px">`
   - 兜底：`<br />` 后的裸链接也 13px
2. **英文副标题 17px 左对齐**
   - `</code><br />` 后紧跟英文字母 → 包 `<span style="font-size:17px;text-align:left">`

另有 **标题补粗**（在 news_brief.py 生成后）：LLM 偶会丢 `**`，正则补 `N. 标题 `源标签`` 行的加粗。

## 4. 主题字段对照（wjbrief.json）

| 字段 | 作用 | 改哪 |
|------|------|------|
| `styles.h2` | 分区标题 | 字号/颜色/间距 |
| `styles.strong` | 消息标题 | 字号/颜色 |
| `styles.blockquote_p` | 🄲🄴 摘要 | 字号/颜色/行高 |
| `styles.blockquote` | 左侧色条卡片 | 边框色/底色/padding |
| `styles.a` | 链接 | URL 字号颜色（clean 后覆盖为 13px） |
| `styles.code` | 源标签 | 底色/字号 |
| `dark_mode` | 深色模式 | 各元素反色 |

## 5. 复用方法

改**样式**不动内容：只改 `wjbrief.json`。
改**内容格式**不动样式：改 `templates/brief.md` + prompt 规则。
改**清洗行为**：改 `clean_brief.py`。

**新格式快速起步**：
1. 复制 `templates/brief.md` 填内容
2. `format.py -i your.md -o out --format wechat --no-open`
3. `python3 -c "from clean_brief import clean_html; ..."` 清洗
4. 浏览器打开 preview.html 确认 → `push_mass_news()` 推送

## 6. 关键文件清单

| 文件 | 职责 |
|------|------|
| `~/wechat-agent/jobs/news_brief.py` | 主流程：抓料→LLM→format→clean→push |
| `~/wechat-agent/jobs/clean_brief.py` | 后处理清洗（URL/英文副标题） |
| `~/wechat-agent/push.py` | 封面生成 + 图文群发 |
| `~/wechat-agent/templates/brief.md` | 简报 markdown 模板 |
| `~/.config/opencode/skills/xiaohu-wechat-format/themes/wjbrief.json` | 视觉主题 |
| `~/.config/opencode/agents/brief.md` | LLM 简报 agent（只读） |
