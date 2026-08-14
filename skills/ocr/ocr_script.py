#!/home/pi/openclaw_env/bin/python3
# openclaw_tools/ocr_tool.py

import pytesseract
import shutil 
from PIL import Image
import os
import argparse 
import sys

# 强制打印当前环境信息到日志，方便你通过 openclaw logs --follow 查看
print(f"DEBUG: 正在运行的 Python 解释器路径: {sys.executable}", file=sys.stderr)
print(f"DEBUG: 当前 Python 搜索路径 (sys.path): {sys.path}", file=sys.stderr)

try:
    import pytesseract
    print("DEBUG: pytesseract 导入成功！", file=sys.stderr)
except ImportError as e:
    print(f"DEBUG: pytesseract 导入失败: {e}", file=sys.stderr)
    # 尝试打印当前环境下已安装的包，看看有没有 pytesseract
    import subprocess
    print("DEBUG: 当前环境下 pip list 内容:", file=sys.stderr)
    print(subprocess.check_output([sys.executable, "-m", "pip", "list"]).decode(), file=sys.stderr)
    sys.exit(1)


# --------------------------------------------------------------------
# 可选：设置 Tesseract 可执行文件的路径
# 如果系统PATH环境变量中没有tesseract，或者OpenClaw运行环境找不到，
# 则需要手动指定。通常在树莓派上，如果通过apt安装，默认路径是 /usr/bin/tesseract
# 你可以通过在终端输入 `which tesseract` 来确认路径。
pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'
# --------------------------------------------------------------------

def perform_ocr_on_image(image_path: str, lang: str = 'chi_sim+eng') -> str:
    """
    对指定路径的图片文件执行光学字符识别（OCR），并返回提取的文本。

    Args:
        image_path (str): 图片文件的完整路径。
        lang (str): 用于OCR的语言。默认为简体中文和英文 ('chi_sim+eng')。
                    例如：'eng'（英文）, 'chi_sim'（简体中文）, 'jpn'（日文）等。
                    如果需要识别其他语言，请确保已安装对应的Tesseract语言包。

    Returns:
        str: 从图片中提取的文本内容。

    Raises:
        FileNotFoundError: 如果图片文件不存在。
        Exception: 如果OCR处理过程中发生其他错误。
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"错误：图片文件未找到，路径为：{image_path}")

    try:
        # 使用Pillow库打开图片
        img = Image.open(image_path)

        # 可以在这里添加图片预处理步骤，例如：
        # img = img.convert('L') # 转换为灰度图
        # img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS) # 放大图片

        # 执行OCR
        text = pytesseract.image_to_string(img, lang=lang)
        return text.strip() # 去除首尾空白字符
    except Exception as e:
        print(f"OCR处理过程中发生错误：{e}")
        # 可以选择重新抛出异常，或者返回一个错误信息
        raise Exception(f"OCR处理失败：{e}")

# openclaw_tools/ocr_tool.py
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="对图片文件执行光学字符识别（OCR）。")
    parser.add_argument(
        "image_path",
        type=str,
        help="要进行OCR的图片文件的完整路径。"
    )
    parser.add_argument(
        "--lang",
        type=str,
        default="chi_sim+eng",
        help="OCR使用的语言代码，例如 'eng'（英文）, 'chi_sim'（简体中文）。默认为 'chi_sim+eng'。"
    )

    args = parser.parse_args()

    # 使用命令行参数进行OCR
    if os.path.exists(args.image_path):
        try:
            print(f"正在对图片 '{args.image_path}' 执行 OCR (语言: {args.lang})...")
            extracted_text = perform_ocr_on_image(args.image_path, lang=args.lang)
            print(f"\n--- 从图片 '{args.image_path}' 中提取的文本：---\n{extracted_text}\n--------------------------------------------------")
        except Exception as e:
            print(f"测试OCR失败：{e}")
    else:
        print(f"错误：测试图片 '{args.image_path}' 未找到。请确保路径正确。")
