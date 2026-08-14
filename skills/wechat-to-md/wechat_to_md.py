#!/home/pi/openclaw_env/bin/python3
import sys
import html2text
from playwright.sync_api import sync_playwright

def get_wechat_md(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            extra_http_headers={"Referer": "https://mp.weixin.qq.com/"}
        )
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        
        page.goto(url, wait_until="networkidle", timeout=60000)
        
        # 滚动触发懒加载
        page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        page.wait_for_timeout(2000)
        
        # 提取正文
        content = page.locator("#js_content").inner_html()
        browser.close()
        
        # 转换为 Markdown
        h = html2text.HTML2Text()
        h.ignore_links = False
        return h.handle(content)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(get_wechat_md(sys.argv[1]))
