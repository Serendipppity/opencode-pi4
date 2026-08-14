from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse, base64, struct, os
from Crypto.Cipher import AES

TOKEN = 'dSO1'
AES_KEY = base64.b64decode('2HvgWIg9XFLNEStzUHLPato1rwC2DaWbo20O1QxoADa=')

def decrypt(encrypted):
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_KEY[:16])
    plain = cipher.decrypt(base64.b64decode(encrypted))
    pad = plain[-1]
    plain = plain[:-pad]
    msg_len = struct.unpack('>I', plain[16:20])[0]
    return plain[20:20+msg_len].decode('utf-8')

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        echostr = q.get('echostr', [''])[0]
        try:
            body = decrypt(echostr)
        except Exception as e:
            body = 'DECRYPT_FAIL:' + str(e)[:50]
        b = body.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def log_message(self, *a): pass

HTTPServer(('127.0.0.1', 8787), H).serve_forever()
