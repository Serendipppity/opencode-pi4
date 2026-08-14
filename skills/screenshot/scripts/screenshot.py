#!/home/pi/openclaw_env/bin/python3
import sys
import time
import datetime
import os
from playwright.sync_api import sync_playwright

#定义默认输出目录
DEFAULT_DIR = "/home/pi/.openclaw/workspace/outbox_obsidian"

def take_screenshot(url, output_file="screenshot.png", mode="full"):
    with sync_playwright() as p:
        # 启动浏览器
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        
        # 设置上下文，加入 Referer 绕过防盗链
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            extra_http_headers={"Referer": "https://m.maoyan.com/"}
        )
        
        page = context.new_page()
        
        # 注入伪装脚本，绕过环境检测
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        
        print(f"正在访问: {url} ...")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        
        # --- 强制加载所有图片 ---
        print("正在强制加载所有图片...")
        page.evaluate("""
            () => {
                const images = document.querySelectorAll('img');
                images.forEach(img => {
                    if (img.getAttribute('data-src')) {
                        img.setAttribute('src', img.getAttribute('data-src'));
                    }
                });
                // 滚动到底部触发剩余懒加载
                window.scrollTo(0, document.body.scrollHeight);
            }
        """)
        
        # 等待图片资源下载完成
        page.wait_for_timeout(5000) 
        
        # --- 截图 ---
        print(f"正在执行截图 (模式: {mode})...")
        if mode == "viewport":
            page.screenshot(path=output_file)
        elif mode == "element":
            # 尝试截取主体
            if page.locator("body").count() > 0:
                page.locator("body").screenshot(path=output_file)
            else:
                page.screenshot(path=output_file, full_page=True)
        else:
            page.screenshot(path=output_file, full_page=True)
            
        print(f"截图已保存至: {output_file}")
        browser.close()


if __name__ == "__main__":
    try:
        if len(sys.argv) < 2:
            print("用法: python screenshot.py <网址> [模式] [文件名/路径]")
        else:
            target_url = sys.argv[1]
            
            # 1. 默认值
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
            target_mode = "full"
            target_file = f"article_{timestamp}.png"
            
            # 2. 参数解析
            if len(sys.argv) >= 3:
                arg2 = sys.argv[2]
                if arg2 in ["full", "viewport", "element"]:
                    target_mode = arg2
                    # 如果有第4个参数，则它是完整路径或文件名
                    if len(sys.argv) >= 4:
                        target_file = sys.argv[3]
                else:
                    # 如果第2个参数不是模式，则视为文件名
                    target_file = arg2
            
            # 3. 路径处理：如果文件名不包含路径，则拼接默认目录
            if not os.path.isabs(target_file):
                if not os.path.exists(DEFAULT_DIR):
                    os.makedirs(DEFAULT_DIR)
                target_file = os.path.join(DEFAULT_DIR, target_file)
                
            take_screenshot(target_url, target_file, target_mode)
            print(f"SUCCESS: {target_file}")

    except Exception as e:
        import traceback
        print("ERROR_DETAIL:")
        traceback.print_exc()
        sys.exit(1)
