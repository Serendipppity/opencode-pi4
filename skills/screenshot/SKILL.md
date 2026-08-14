---
name: screenshot
description: Capture screenshots of web pages. Supports full-page, viewport-only, and element-specific captures (optimized for WeChat articles)
metadata:
  openclaw:
    requires:
      bins: ["python3"]
---

# 网页截图技能 (Screenshot Skill)

## 概述
使用Python脚本捕获网页的高保真截图。针对懒加载图片和特定元素定位进行了优化。

## 工作流
1. **目标识别**：确定用户需要全页截图、视口截图还是特定元素截图（例如微信文章的 `#js_content`）。
2. 执行：使用 python3 调用脚本。
3. 路径智能处理：脚本会自动将文件保存至 /home/pi/.config/opencode/workspace/outbox_obsidian/，无需手动指定目录。
4. 参数灵活性：如果不需要自定义文件名，只需传入 URL 和模式即可。
5. **错误处理**：
    - 如果脚本执行失败，请等待至少 30 秒后再重试。
    - **重试限制**：不要尝试重试超过 2 次。如果失败两次，请停止并向用户报告错误。
6. **输出**：提供保存的截图文件路径，并简要确认捕获区域。


## 依赖
- **Python 库**: `playwright`
- **浏览器**: Chromium 

## 截图命令
```bash
# 基础执行函数
capture_screenshot() {
  # $1: URL - 必须输入
  # $2: MODE (default/viewport/element) - 可选
  # $3: FILENAME - 可选 (默认存入 /home/pi/.config/opencode/workspace/outbox_obsidian/)
  python3 /home/pi/.config/opencode/workspace/skills/screenshot/scripts/screenshot.py "$1" "$2" "$3"
}

# 使用示例 (Usage Examples)
## 1. 自动命名，存入默认目录 (最简):
screenshot.py "https://m.maoyan.com/..."

## 2. 指定模式，自动命名:
screenshot.py  "https://m.maoyan.com/..." "viewport"

## 3. 指定模式和文件名:
screenshot.py "https://m.maoyan.com/..." "viewport" "maoyan_cinema.png"

## 4. 指定绝对路径 (覆盖默认目录):
screenshot.py "https://m.maoyan.com/..." "viewport" "/tmp/my_custom_screenshot.png"

# 输出格式示例 (Example Output Format)
## 📸 截图已捕获
URL: [URL]
模式: [default/viewport/element]
文件: [filename.png]
状态: 成功

# 最佳实践 (Best Practices)
- 速率限制保护：如果需要连续捕获多个页面，请在每次执行之间等待至少 10 秒，以避免浏览器资源耗尽。
- 重试限制：不要尝试重试失败的捕获超过 2 次。如果失败两次，请停止并向用户报告错误。
- 元素定位：捕获微信文章时，务必使用 element 模式并指定 #js_content，以获得最整洁的输出。
- 验证：在通知用户之前，请务必确认文件已存在于输出目录中。
