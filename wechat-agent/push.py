#!/usr/bin/env python3
"""测试号模板消息推送（三字段：first/keyword1/remark）"""
import json, urllib.request, os, sys

CFG = json.load(open(os.path.expanduser('~/wechat-agent/config.json')))

def get_token():
    url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={CFG['test_appid']}&secret={CFG['test_appsecret']}"
    r = json.load(urllib.request.urlopen(url, timeout=15))
    return r.get('access_token')

def get_openid(at):
    u = json.load(urllib.request.urlopen(f'https://api.weixin.qq.com/cgi-bin/user/get?access_token={at}', timeout=15))
    return (u.get('data') or {}).get('openid', [])

def send_template(at, openid, first, body, remark=''):
    payload = {'touser': openid, 'template_id': CFG['test_template_id'],
               'data': {'first': {'value': first[:30]},
                        'keyword1': {'value': body[:450]},
                        'remark': {'value': remark[:60]}}}
    req = urllib.request.Request(f'https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={at}',
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=15))

def push(text):
    at = get_token()
    if not at:
        print('token fail'); return 1
    openids = get_openid(at)
    if not openids:
        print('NO_FOLLOWER'); return 1
    # 文本 -> 三字段：首行=标题，中间=正文，末行=备注
    lines = [l for l in text.split('\n') if l.strip()]
    first = lines[0] if lines else '通知'
    body = '\n'.join(lines[1:]) if len(lines) > 1 else ''
    remark = ''
    for oid in openids:
        r = send_template(at, oid, first, body or first, remark)
        print(oid[:10], r)
    return 0

def push_mass(text):
    """群发通道（文本直发，不走模板渲染）"""
    at = get_token()
    if not at:
        print('token fail'); return 1
    content = text
    while len(content.encode('utf-8')) > 2000:
        content = content[:-1]
    payload = {'filter': {'is_to_all': True}, 'msgtype': 'text',
               'text': {'content': content}}
    req = urllib.request.Request(f'https://api.weixin.qq.com/cgi-bin/message/mass/sendall?access_token={at}',
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json'})
    r = json.load(urllib.request.urlopen(req, timeout=15))
    print('mass:', r)
    return 0 if r.get('errcode') == 0 else 1

if __name__ == '__main__':
    sys.exit(push_mass(sys.argv[1] if len(sys.argv) > 1 else '（空消息）'))

def push_mass_news(title, html, digest='', source_url=''):
    """图文群发：PIL 封面 + uploadnews + sendall"""
    from PIL import Image, ImageDraw, ImageFont
    import datetime
    at = get_token()
    if not at:
        print('token fail'); return 1
    # 封面：风景图 + 日期 + 星期 + 时段
    now = datetime.datetime.now()
    today = now.strftime('%m-%d')
    weekday_cn = ['一','二','三','四','五','六','日'][now.weekday()]
    # 标题含 早/午/晚 报，选对应风景图
    label = '早报' if '早' in title else ('晚报' if '晚' in title else '午报')
    cover_map = {'早报': 'morning.jpg', '午报': 'noon.jpg', '晚报': 'evening.jpg'}
    cover_path = os.path.expanduser(f'~/wechat-agent/covers/{cover_map[label]}')
    base = Image.open(cover_path).convert('RGB')
    img = base.resize((900, 500), Image.LANCZOS)
    # 半透明遮罩（底部渐变，保证文字可读）
    overlay = Image.new('RGBA', (900, 500), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for i in range(500):
        alpha = int(120 * (i / 500) ** 1.5)
        od.line([(0, i), (900, i)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
    d = ImageDraw.Draw(img)
    try:
        f_date = ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc', 48)
        f_week = ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc', 36)
        f_label = ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc', 38)
    except Exception:
        f_date = f_week = f_label = ImageFont.load_default()
    d.text((450, 205), today, fill=(255, 255, 255), font=f_date, anchor='mm')
    line2 = f'星期{weekday_cn} {label}'
    d.text((450, 255), line2, fill=(255, 255, 255), font=f_label, anchor='mm')
    img.save('/tmp/kf_cover.jpg', 'JPEG', quality=90)
    # 上传图片
    boundary = '----WXKFCOVER9xZ'
    body = b''
    body += ('--' + boundary + '\r\n').encode()
    body += 'Content-Disposition: form-data; name="media"; filename="cover.jpg"\r\n'.encode()
    body += 'Content-Type: image/jpeg\r\n\r\n'.encode()
    body += open('/tmp/kf_cover.jpg', 'rb').read() + b'\r\n'
    body += ('--' + boundary + '--\r\n').encode()
    req = urllib.request.Request(f'https://api.weixin.qq.com/cgi-bin/media/upload?access_token={at}&type=image',
        data=body, headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    thumb = json.load(urllib.request.urlopen(req, timeout=20))['media_id']
    # 图文素材
    article = {'articles': [{'title': title, 'author': '虾条', 'digest': digest,
        'content': html, 'content_source_url': source_url, 'thumb_media_id': thumb,
        'need_open_comment': 0}]}
    req = urllib.request.Request(f'https://api.weixin.qq.com/cgi-bin/media/uploadnews?access_token={at}',
        data=json.dumps(article, ensure_ascii=False).encode('utf-8'), headers={'Content-Type': 'application/json'})
    media_id = json.load(urllib.request.urlopen(req, timeout=20))['media_id']
    # 群发
    payload = {'filter': {'is_to_all': True}, 'msgtype': 'mpnews', 'mpnews': {'media_id': media_id}}
    req = urllib.request.Request(f'https://api.weixin.qq.com/cgi-bin/message/mass/sendall?access_token={at}',
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'), headers={'Content-Type': 'application/json'})
    r = json.load(urllib.request.urlopen(req, timeout=20))
    print('news:', r)
    return 0 if r.get('errcode') == 0 else 1
