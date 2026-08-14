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
    # 封面（带日期）
    today = datetime.datetime.now().strftime('%m-%d')
    img = Image.new('RGB', (900, 500), (38, 46, 68))
    d = ImageDraw.Draw(img)
    try:
        f1 = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 64)
        f2 = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 36)
    except Exception:
        f1 = f2 = ImageFont.load_default()
    d.text((450, 210), title[:12], fill=(255, 255, 255), font=f1, anchor='mm')
    d.text((450, 320), today, fill=(160, 170, 200), font=f2, anchor='mm')
    img.save('/tmp/kf_cover.jpg', 'JPEG', quality=88)
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
