---
name: ocr
description: 提供图片文字提取服务，使用 pytesseract 库进行文字识别。用于在 OpenClaw 中将图片内容转为文字。
---

# OCR Skill

提供图片文字提取服务，使用 `pytesseract` 库进行文字识别。

## 依赖 (Dependencies)
- **Python Library**: `pytesseract`
- **System Tool**: `tesseract-ocr` (需安装)

## 用法
```bash
python3 skills/ocr/ocr_script.py <图片路径>
```

## 注意事项
该技能运行需要环境中已安装 `pytesseract` 库及 `tesseract` 二进制文件。若调用失败，请确保安装了相应依赖。
