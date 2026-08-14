# Wechat to Markdown Skill

## 功能
- 自动处理微信公众号文章的动态加载（JS 渲染）。
- 绕过基础反爬虫检测。
- 将 HTML 正文转换为标准的 Markdown 格式。

## 安装步骤
1. 确保已安装依赖：
   `/home/pi/openclaw_env/bin/pip install playwright html2text`
2. 安装浏览器驱动：
   `/home/pi/openclaw_env/bin/playwright install chromium`
3. 赋予执行权限：
   `chmod +x ~/.openclaw/workspace/skills/wechat_to_md/wechat_to_md.py`
4. 在 OpenClaw 中输入 `/new` 重新加载技能。

## 注意事项
- 脚本依赖 Playwright，首次运行可能较慢。
- 若遇到微信验证码，请检查是否需要更新 User-Agent 或 Referer。

### 最后一步：部署检查
请在终端执行以下命令完成部署：
```bash
# 1. 创建目录
mkdir -p ~/.openclaw/workspace/skills/wechat_to_md/

# 2. 移动文件 (假设你已经创建好上述三个文件)
# mv wechat_to_md.py SKILL.md README.md ~/.openclaw/workspace/skills/wechat_to_md/

# 3. 赋予权限
chmod +x ~/.openclaw/workspace/skills/wechat_to_md/wechat_to_md.py

# 4. 刷新 OpenClaw
# 在聊天窗口输入 /new
```
