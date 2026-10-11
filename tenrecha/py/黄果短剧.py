# -*- coding: utf-8 -*-
# 黄果短剧 终极版
# ─────────────────────────────────────────────────────────
# 默认行为 = _2.py（动态域名 + 预热 + 本地图片代理 + videoInitialData 直取）
# 所有激进特性默认关闭，ext 里显式开启才生效：
#   doh=1           → 全局 DoH 补丁（_4 的能力）
#   proxy_play=1    → m3u8/ts/key 全代理重写（_4 的能力）
#   prefetch=1      → 后台预热备用域名（_2 默认开，这里给开关）
#   pure_aes=1      → 强制用纯 Python AES（_1 的能力，设备无 pycryptodome 时）
#   bs4=0           → 禁用 BS4，强制走正则（_1 风格）
# ─────────────────────────────────────────────────────────
import sys
import re
import json
import time
import base64
import random
import string
import socket
import threading
import html as htmllib
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        pass

try:
    import requests as rq
    rq.packages.urllib3.disable_warnings()
except Exception:
    rq = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    from Crypto.Cipher import AES
except ImportError:
    try:
        from Cryptodome.Cipher import AES
    except ImportError:
        AES = None


# ══════════════════════════════════════════════════════════
# 常量
# ══════════════════════════════════════════════════════════
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
TIMEOUT = 18
PAGE_SIZE = 24

_AES_KEY = b'f5d965df75336270'
_AES_IV = b'97b60394abc2fbe1'

_PLACEHOLDER_GIF = base64.b64decode(
    'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7')

_TAG_RE = re.compile(r'<[^>]+>')

# 动态域名生成
def _gen_random_subdomain():
    length = random.randint(3, 6)
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def _gen_backup_hosts(n=8):
    return [f"https://{_gen_random_subdomain()}.ediayikma.cc" for _ in range(n)]


# 静态域名池（_3 的列表作为基础）
_STATIC_HOSTS = [
    "https://huangguoai.com",
    "https://ttvoij.ediayikma.cc",
    "https://thu.ediayikma.cc",
    "https://pku.ediayikma.cc",
    "https://fdu.ediayikma.cc",
    "https://thu.agdkczeyx.cc",
]

HOSTS = ["https://huangguoai.com"] + _gen_backup_hosts(8)

_PROXY_PORT = [0]

# BS4 解析器探测
_BS4_PARSER = None
if BeautifulSoup is not None:
    try:
        BeautifulSoup("<a/>", "lxml")
        _BS4_PARSER = "lxml"
    except Exception:
        _BS4_PARSER = "html.parser"


def _clean(s):
    if not s:
        return ""
    s = htmllib.unescape(str(s))
    s = _TAG_RE.sub(' ', s)
    return re.sub(r'\s+', ' ', s).strip()


# ══════════════════════════════════════════════════════════
# 可选：全局 DoH 补丁（默认不装）
# ══════════════════════════════════════════════════════════
_DOH_SERVERS = (
    "https://doh.pub/dns-query",
    "https://dns.alidns.com/resolve",
    "https://dns.google/resolve",
    "https://cloudflare-dns.com/dns-query",
)
_DOH_HOSTS = {"doh.pub", "dns.alidns.com", "dns.google", "cloudflare-dns.com"}
_IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_doh_cache = {}
_doh_last = {}
_doh_resolving = False
_doh_lock = threading.Lock()
_orig_getaddrinfo = socket.getaddrinfo
_DOH_INSTALLED = False


def _doh_lookup(host, ttl=300):
    global _doh_resolving
    now = time.time()
    cached = _doh_cache.get(host)
    if cached and now - _doh_last.get(host, 0) < ttl:
        return cached
    with _doh_lock:
        if _doh_resolving:
            return _doh_cache.get(host, "")
        _doh_resolving = True
    ip = ""
    try:
        for srv in _DOH_SERVERS:
            try:
                r = rq.get(srv, params={"name": host, "type": "A"},
                           headers={"Accept": "application/dns-json"},
                           timeout=3, verify=False)
                if r.status_code == 200:
                    for ans in r.json().get("Answer", []):
                        d = ans.get("data", "")
                        if ans.get("type") == 1 and _IP_RE.match(d):
                            ip = d
                            break
                if ip:
                    break
            except Exception:
                continue
    finally:
        with _doh_lock:
            _doh_resolving = False
    if ip:
        _doh_cache[host] = ip
        _doh_last[host] = now
    return ip


def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if isinstance(host, str) and host not in _DOH_HOSTS and not _doh_resolving:
        ip = _doh_lookup(host)
        if ip:
            return _orig_getaddrinfo(ip, port, family, type, proto, flags)
    return _orig_getaddrinfo(host, port, family, type, proto, flags)


def _install_doh():
    global _DOH_INSTALLED
    if not _DOH_INSTALLED:
        socket.getaddrinfo = _patched_getaddrinfo
        _DOH_INSTALLED = True


# ══════════════════════════════════════════════════════════
# AES：优先 pycryptodome，退化到纯 Python
# ══════════════════════════════════════════════════════════
_SBOX = None
_INV_SBOX = None


def _get_sbox():
    global _SBOX, _INV_SBOX
    if _SBOX is not None:
        return _SBOX
    _SBOX = [
        0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
        0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
        0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
        0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
        0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
        0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
        0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
        0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
        0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
        0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
        0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
        0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
        0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
        0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
        0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
        0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16,
    ]
    _INV_SBOX = [0]*256
    for i in range(256):
        _INV_SBOX[_SBOX[i]] = i
    return _SBOX


def _gm(x, y):
    """GF(2^8) 乘法"""
    p = 0
    for _ in range(8):
        if y & 1:
            p ^= x
        hi = x & 0x80
        x = (x << 1) & 0xff
        if hi:
            x ^= 0x1b
        y >>= 1
    return p


def _pure_aes_cbc_decrypt(data, key, iv):
    sbox = _get_sbox()
    inv = _INV_SBOX

    # key expansion
    w = [list(key[i:i+4]) for i in range(0, 16, 4)]
    rc = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1b,0x36]
    for i in range(4, 44):
        t = list(w[i-1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [sbox[b] for b in t]
            t[0] ^= rc[i//4 - 1]
        w.append([w[i-4][j] ^ t[j] for j in range(4)])
    rk = [bytearray(w[r*4] + w[r*4+1] + w[r*4+2] + w[r*4+3]) for r in range(11)]

    prev = bytearray(iv)
    out = bytearray()
    for i in range(0, len(data), 16):
        blk = bytearray(data[i:i+16])
        if len(blk) < 16:
            blk += b'\x00' * (16 - len(blk))
        # state[row][col]
        state = [[blk[r*4+c] for c in range(4)] for r in range(4)]
        # AddRoundKey round 10
        for r in range(4):
            for c in range(4):
                state[r][c] ^= rk[10][r*4+c]
        for rnd in range(9, 0, -1):
            # InvShiftRows
            for row in range(1, 4):
                state[row] = state[row][-row:] + state[row][:-row]
            # InvSubBytes
            for r in range(4):
                for c in range(4):
                    state[r][c] = inv[state[r][c]]
            # AddRoundKey
            for r in range(4):
                for c in range(4):
                    state[r][c] ^= rk[rnd][r*4+c]
            # InvMixColumns
            for c in range(4):
                a, b, cc, d = state[0][c], state[1][c], state[2][c], state[3][c]
                state[0][c] = _gm(a,14)^_gm(b,11)^_gm(cc,13)^_gm(d,9)
                state[1][c] = _gm(a,9)^_gm(b,14)^_gm(cc,11)^_gm(d,13)
                state[2][c] = _gm(a,13)^_gm(b,9)^_gm(cc,14)^_gm(d,11)
                state[3][c] = _gm(a,11)^_gm(b,13)^_gm(cc,9)^_gm(d,14)
        # Final round
        for row in range(1, 4):
            state[row] = state[row][-row:] + state[row][:-row]
        for r in range(4):
            for c in range(4):
                state[r][c] = inv[state[r][c]]
        for r in range(4):
            for c in range(4):
                state[r][c] ^= rk[0][c*4+r]
        dec = bytearray(state[r][c] for c in range(4) for r in range(4))
        out.extend(bytes(a ^ b for a, b in zip(dec, prev)))
        prev = blk
    return bytes(out)


def _aes_decrypt(data, key, iv, force_pure=False):
    if force_pure or AES is None:
        return _pure_aes_cbc_decrypt(data, key, iv)
    return AES.new(key, AES.MODE_CBC, iv).decrypt(data)


# ══════════════════════════════════════════════════════════
# 图片解密 / MIME 探测
# ══════════════════════════════════════════════════════════
def _is_image(data):
    if not data or len(data) < 8:
        return False
    if data[:3] == b'\xff\xd8\xff':
        return True
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return True
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return True
    if data[:4] == b'RIFF' and len(data) > 12 and data[8:12] == b'WEBP':
        return True
    return False


def _detect_mime(data):
    if data[:3] == b'\xff\xd8\xff':
        return 'image/jpeg'
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif'
    if data[:4] == b'RIFF' and len(data) > 12 and data[8:12] == b'WEBP':
        return 'image/webp'
    return 'image/jpeg'


def _decrypt_img(data, force_pure=False):
    if not data:
        return data
    if _is_image(data):
        return data
    try:
        dec = _aes_decrypt(data, _AES_KEY, _AES_IV, force_pure)
        pad = dec[-1]
        if 1 <= pad <= 16 and all(b == pad for b in dec[-pad:]):
            dec = dec[:-pad]
        else:
            dec = dec.rstrip(b'\x00')
        return dec
    except Exception:
        return data


# ══════════════════════════════════════════════════════════
# 本地图片代理服务器（_2 的能力，默认开）
# ══════════════════════════════════════════════════════════
try:
    from http.server import BaseHTTPRequestHandler, HTTPServer

    def _fetch_img_raw(u, referer):
        headers = {"User-Agent": UA, "Referer": referer, "Accept": "image/*"}
        try:
            rr = rq.get(u, headers=headers, timeout=15, verify=False,
                        allow_redirects=True)
            if rr.status_code == 200 and rr.content and len(rr.content) > 50:
                return rr.content
        except Exception:
            pass
        return b''

    class _ImgHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                pr = urllib.parse.urlparse(self.path)
                if pr.path not in ('/img', '/proxy'):
                    self.send_response(404)
                    self.end_headers()
                    return
                q = urllib.parse.parse_qs(pr.query)
                u = q.get('u', q.get('url', ['']))[0]
                u = urllib.parse.unquote(u)
                if not u.startswith('http'):
                    self.send_response(400)
                    self.end_headers()
                    return
                raw = _fetch_img_raw(u, HOSTS[0] + "/")
                data = _decrypt_img(raw) if raw else b''
                if not data or len(data) < 50:
                    data, ctype = _PLACEHOLDER_GIF, 'image/gif'
                else:
                    ctype = _detect_mime(data)
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'max-age=86400')
                self.end_headers()
                self.wfile.write(data)
            except Exception:
                pass

        def log_message(self, *args):
            pass

    def _start_proxy_server():
        if _PROXY_PORT[0]:
            return _PROXY_PORT[0]
        for port in [9978] + list(range(9979, 10020)) + list(range(30261, 30281)):
            try:
                srv = HTTPServer(('127.0.0.1', port), _ImgHandler)
                _PROXY_PORT[0] = port
                threading.Thread(target=srv.serve_forever, daemon=True).start()
                return port
            except Exception:
                continue
        return 0
except Exception:
    def _start_proxy_server():
        return 0


# ══════════════════════════════════════════════════════════
# Spider 主体
# ══════════════════════════════════════════════════════════
class Spider(Spider):

    _PRIMARY_FAIL_THRESHOLD = 3

    def getName(self):
        return "黄果短剧"

    # ─────────────────────────────────────────────────────
    # 初始化
    # ─────────────────────────────────────────────────────
    def init(self, extend=""):
        cfg = self._parse_cfg(extend)

        # 域名初始化
        if cfg.get("hosts"):
            HOSTS.clear()
            HOSTS.extend([h.rstrip('/') for h in cfg["hosts"] if str(h).startswith("http")])
        primary = HOSTS[0].rstrip('/')

        self.host = primary
        self._working_backups = []
        self._primary_fails = [0]

        # 可选开关
        self._enable_prefetch = self._bool(cfg.get("prefetch"), default=True)
        self._enable_proxy_play = self._bool(cfg.get("proxy_play"), default=False)
        self._enable_pure_aes = self._bool(cfg.get("pure_aes"), default=False)
        self._enable_bs4 = self._bool(cfg.get("bs4"), default=True)
        self._doh_enabled = False

        # DoH（默认关）
        if self._bool(cfg.get("doh"), default=False):
            try:
                _install_doh()
                self._doh_enabled = True
            except Exception:
                pass

        # Session
        try:
            self.s = rq.Session()
            self.s.verify = False
            self.s.headers.update({
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": self.host + "/",
            })
            try:
                from requests.adapters import HTTPAdapter
                _adapter = HTTPAdapter(pool_connections=16, pool_maxsize=32, max_retries=0)
                self.s.mount('http://', _adapter)
                self.s.mount('https://', _adapter)
            except Exception:
                pass
        except Exception:
            self.s = None

        self._list_cache = {}
        self._access_cache = {}

        # 本地图片代理
        try:
            _start_proxy_server()
        except Exception:
            pass

        # 后台预热（默认开）
        if self._enable_prefetch:
            try:
                t = threading.Thread(target=self._prefetch_backups, daemon=True)
                t.start()
            except Exception:
                pass

    @staticmethod
    def _parse_cfg(extend):
        if isinstance(extend, dict):
            return extend
        if isinstance(extend, str) and extend.strip():
            try:
                obj = json.loads(extend)
                return obj if isinstance(obj, dict) else {}
            except Exception:
                return {}
        return {}

    @staticmethod
    def _bool(v, default=False):
        if v is None:
            return default
        return str(v).strip().lower() in ("1", "on", "true", "yes", "y")

    # ─────────────────────────────────────────────────────
    # 域名探测 / 切换
    # ─────────────────────────────────────────────────────
    @staticmethod
    def _probe_host(h):
        try:
            r = rq.get(h.rstrip('/'), headers={"User-Agent": UA}, timeout=4, verify=False)
            if r.status_code == 200 and (
                    '黄果' in r.text or 'huangguo' in r.text.lower() or len(r.text) > 2000):
                return h.rstrip('/')
        except Exception:
            pass
        return None

    def _prefetch_backups(self):
        primary = HOSTS[0].rstrip('/')
        backups = [h.rstrip('/') for h in HOSTS[1:] if h.rstrip('/') != primary]
        if not backups:
            return
        results = []
        lock = threading.Lock()

        def _do(h):
            r = self._probe_host(h)
            if r:
                with lock:
                    results.append(r)

        try:
            with ThreadPoolExecutor(max_workers=min(6, len(backups))) as ex:
                list(ex.map(_do, backups, timeout=10))
        except Exception:
            pass
        self._working_backups = results

    def _switch_host(self, new_host):
        new_host = (new_host or "").rstrip('/')
        if not new_host:
            return
        self.host = new_host
        try:
            if self.s is not None:
                self.s.headers["Referer"] = new_host + "/"
        except Exception:
            pass

    # ─────────────────────────────────────────────────────
    # 请求层
    # ─────────────────────────────────────────────────────
    def _fetch_one(self, host, path, ref, timeout):
        url = host + path
        try:
            headers = {
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": host + ref,
            }
            r = rq.get(url, timeout=timeout, verify=False, allow_redirects=True,
                       headers=headers)
            if r.status_code == 200 and r.text:
                r.encoding = 'utf-8'
                return r.text
        except Exception:
            pass
        return ""

    def _get(self, path, ref="/"):
        if not rq:
            return ""
        # 完整 URL
        if path.startswith("http"):
            try:
                headers = {"Referer": self.host.rstrip('/') + ref}
                if self.s is not None:
                    r = self.s.get(path, timeout=TIMEOUT, allow_redirects=True, headers=headers)
                else:
                    r = rq.get(path, timeout=TIMEOUT, verify=False,
                               headers={"User-Agent": UA, **headers})
                if r.status_code == 200 and r.text:
                    r.encoding = 'utf-8'
                    return r.text
            except Exception:
                pass
            return ""

        primary = HOSTS[0].rstrip('/')
        current = getattr(self, 'host', primary).rstrip('/')

        # 当前 host
        try:
            url = current + path
            headers = {"Referer": current + ref}
            if self.s is not None:
                r = self.s.get(url, timeout=8, allow_redirects=True, headers=headers)
            else:
                r = rq.get(url, timeout=8, verify=False,
                           headers={"User-Agent": UA, **headers})
            if r.status_code == 200 and r.text:
                r.encoding = 'utf-8'
                self._primary_fails[0] = 0
                return r.text
        except Exception:
            pass

        # 失败：计数
        if current == primary:
            try:
                self._primary_fails[0] += 1
                if (self._primary_fails[0] >= self._PRIMARY_FAIL_THRESHOLD
                        and getattr(self, '_working_backups', None)):
                    self._switch_host(self._working_backups[0])
            except Exception:
                pass

        # 拿预热好的备用
        known_good = list(getattr(self, '_working_backups', None) or [])
        candidates = [h for h in known_good if h != current][:4]
        if not candidates:
            all_hosts = [h.rstrip('/') for h in HOSTS if h.rstrip('/') != current]
            candidates = all_hosts[:4]
        if not candidates:
            return ""

        with ThreadPoolExecutor(max_workers=len(candidates)) as ex:
            futs = {ex.submit(self._fetch_one, h, path, ref, 6): h for h in candidates}
            try:
                for fut in as_completed(futs, timeout=8):
                    try:
                        text = fut.result()
                        if text:
                            for f in futs:
                                f.cancel()
                            won = futs[fut]
                            self._switch_host(won)
                            return text
                    except Exception:
                        continue
            except Exception:
                pass
        return ""

    def _get_cached(self, path, ref="/", ttl=60):
        try:
            cache = self._list_cache
        except AttributeError:
            cache = self._list_cache = {}
        now = time.time()
        cached = cache.get(path)
        if cached and now - cached[1] < ttl:
            return cached[0]
        text = self._get(path, ref)
        if text:
            cache[path] = (text, now)
            if len(cache) > 80:
                for k in list(cache.keys()):
                    if now - cache[k][1] > ttl:
                        cache.pop(k, None)
        return text

    # ─────────────────────────────────────────────────────
    # 图片封装
    # ─────────────────────────────────────────────────────
    def _wrap_pic(self, url):
        if not url or not str(url).startswith('http'):
            return url or ""
        if not _PROXY_PORT[0]:
            _start_proxy_server()
        if _PROXY_PORT[0]:
            return ("http://127.0.0.1:%d/proxy?url=%s"
                    % (_PROXY_PORT[0], urllib.parse.quote(url, safe='')))
        try:
            b = base64.b64encode(url.encode('utf-8')).decode('ascii')
            return f"proxy://type=pic&url={b}"
        except Exception:
            return url

    # ─────────────────────────────────────────────────────
    # 首页
    # ─────────────────────────────────────────────────────
    def homeContent(self, filter=False):
        result = {
            "class": [
                {"type_id": "ai-duanju", "type_name": "AI成人短剧"},
                {"type_id": "ai-manju", "type_name": "AI成人漫剧"},
                {"type_id": "ai-huanlian", "type_name": "AI换脸"},
                {"type_id": "ai-mogai", "type_name": "AI魔改"},
                {"type_id": "topic", "type_name": "📌专题"},
                {"type_id": "ranks", "type_name": "排行榜"},
                {"type_id": "chigua", "type_name": "黄果吃瓜"},
            ],
            "list": [],
            "filters": {
                "ranks": [{"key": "类型", "name": "类型", "value": [
                    {"n": "热播榜", "v": "hot"},
                    {"n": "推荐榜", "v": "recommend"},
                    {"n": "潜力榜", "v": "potential"},
                ]}],
                "chigua": [{"key": "类型", "name": "类型", "value": [
                    {"n": "全部", "v": "page"},
                    {"n": "热门吃瓜", "v": "remen"},
                    {"n": "AI原创", "v": "yuanchuang"},
                ]}],
                "author": [{"key": "类型", "name": "类型", "value": [
                    {"n": "黄果ai大师", "v": "156305"},
                ]}],
            }
        }
        try:
            html = self._get_cached("/")
            if html:
                result["list"] = self._parse_list(html)
        except Exception:
            pass
        return result

    def homeVideoContent(self):
        try:
            html = self._get_cached("/recommend/1/")
            if not html:
                html = self._get_cached("/")
            return {"list": self._parse_list(html)}
        except Exception:
            return {"list": []}

    # ─────────────────────────────────────────────────────
    # 分类
    # ─────────────────────────────────────────────────────
    def categoryContent(self, tid, pg=1, filter=False, extend=""):
        try:
            pg = int(str(pg or 1))
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        cid = str(tid or "").strip().strip("/")
        ext = extend if isinstance(extend, dict) else {}
        rc = ext.get("类型", cid)

        videos, pages, total = [], 9999, 0

        try:
            if cid.startswith("dir_topic_"):
                slug = cid.replace("dir_topic_", "")
                html = self._get_cached(f"/topics/{slug}/?page={pg}")
                videos = self._parse_list(html, mode="drama")
                return self._result(videos, pg, 9999)

            if cid in ("ai-duanju", "ai-manju", "ai-huanlian", "ai-mogai"):
                videos, pages, total = self._category_api(cid, pg)
                if not videos:
                    path = f"/{cid}/" if pg <= 1 else f"/{cid}/{pg}/"
                    html = self._get_cached(path)
                    videos = self._parse_list(html)
                    ps = [int(x) for x in re.findall(
                        r'/' + re.escape(cid) + r'/(\d+)/', html or "")]
                    if ps:
                        pages = max(ps)
                if len(videos) > PAGE_SIZE:
                    videos = videos[:PAGE_SIZE]
                return self._result(videos, pg, pages or 9999, total)

            if cid == "recommend":
                html = self._get_cached(f"/recommend/{pg}/")
                videos = self._parse_list(html)
            elif cid == "newest":
                html = self._get_cached(f"/newest/{pg}/")
                videos = self._parse_list(html)
            elif cid == "topic":
                html = self._get_cached("/topics/")
                videos = self._parse_list(html, mode="topic")
                pages = 1
            elif cid == "ranks":
                rtype = rc if rc in ("hot", "recommend", "potential") else "hot"
                html = self._get_cached(f"/ranks/{rtype}/")
                videos = self._parse_list(html, mode="rank")
                pages = 1
            elif cid == "chigua":
                ctype = rc if rc in ("page", "remen", "yuanchuang") else "page"
                html = self._get_cached(f"/chigua/{ctype}/{pg}/")
                videos = self._parse_list(html, mode="post")
            elif cid == "author":
                aid = rc if str(rc).isdigit() else "156291"
                html = self._get(f"/author/{aid}/video/{pg}/")
                videos = self._parse_list(html)
            else:
                path = f"/{cid}/" if pg <= 1 else f"/{cid}/{pg}/"
                html = self._get(path)
                videos = self._parse_list(html)
        except Exception:
            videos = []

        return self._result(videos, pg, pages, total)

    def _category_api(self, slug, pg):
        url = (f"/api/videos/category/{urllib.parse.quote(slug)}"
               f"?sort=hot&page={pg}&size={PAGE_SIZE}")
        text = self._get_cached(url, ref="/" + slug + "/")
        if not text:
            return [], 0, 0
        try:
            data = json.loads(text)
        except Exception:
            return [], 0, 0
        d = data.get("data") or {}
        items = d.get("items") or []
        pag = d.get("pagination") or {}
        videos = []
        for it in items:
            v = self._api_item(it)
            if v:
                videos.append(v)
        pages = total = 0
        try:
            pages = int(pag.get("pages") or 0)
        except Exception:
            pass
        try:
            total = int(pag.get("total") or 0)
        except Exception:
            pass
        return videos, pages, total

    def _api_item(self, it):
        vid = it.get("id")
        if vid is None:
            return None
        title = _clean(it.get("title"))
        if not title:
            return None
        pic = (it.get("cover") or "").strip()
        epc = it.get("episode_count")
        finished = it.get("is_finished")
        if finished:
            remark = "全%d集" % epc if epc else "全剧"
        else:
            remark = "更新至%d集" % epc if epc else "连载中"
        score = it.get("score")
        if score:
            remark = f"{score}分 " + remark
        return {
            "vod_id": str(vid),
            "vod_name": title,
            "vod_pic": self._wrap_pic(pic),
            "vod_remarks": remark or "在线观看",
        }

    def _result(self, videos, pg, pagecount=9999, total=0):
        n = len(videos)
        if total < 1:
            total = pagecount * max(n, 1) if pagecount > 1 else n
        return {
            "list": videos,
            "page": pg,
            "pagecount": pagecount,
            "limit": PAGE_SIZE,
            "total": total,
        }

    # ─────────────────────────────────────────────────────
    # 搜索
    # ─────────────────────────────────────────────────────
    def searchContent(self, key, quick=False, pg="1"):
        kw = urllib.parse.quote(str(key or "").strip())
        if not kw:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}
        try:
            p = int(pg) if pg else 1
        except Exception:
            p = 1
        html = self._get(f"/search/video/{kw}/{p}/")
        videos = self._parse_list(html, mode="search")
        has_more = len(videos) >= 18
        return {
            "page": p,
            "pagecount": p + 1 if has_more else p,
            "limit": 20,
            "total": 0,
            "list": videos,
        }

    # ─────────────────────────────────────────────────────
    # 详情
    # ─────────────────────────────────────────────────────
    def detailContent(self, ids):
        try:
            raw = ids[0] if isinstance(ids, (list, tuple)) else ids
            did = str(raw).strip()
        except Exception:
            return {"list": []}
        if not did:
            return {"list": []}

        if "/archives/" in did or (did.startswith("http") and "archives" in did):
            return self._detail_chigua(did)

        m = re.search(r'(?:detail/|/)?(\d+)/?$', did)
        vid = m.group(1) if m else (did if did.isdigit() else None)

        vhtml = ""
        if vid:
            primary = self.host.rstrip('/')
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut_video = ex.submit(self._fetch_one, primary, f"/video/{vid}/", "/", 10)
                html = self._get(f"/detail/{vid}/")
                vhtml = fut_video.result()
        else:
            html = self._get(did if did.startswith("/") else "/" + did)

        if not html:
            return {"list": []}

        title = ""
        m = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        if m:
            title = _clean(m.group(1))
        if not title:
            m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
            if m:
                title = _clean(m.group(1))
        if not title:
            m = re.search(r'<title>(.*?)</title>', html)
            if m:
                title = _clean(m.group(1).split('|')[0])
        if not title:
            return {"list": []}

        pic = ""
        m = re.search(r'<img[^>]*data-src="([^"]+)"[^>]*>', html)
        if m:
            pic = htmllib.unescape(m.group(1)).strip()
        if not pic:
            m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
            if m:
                pic = htmllib.unescape(m.group(1)).strip()

        desc = ""
        m = re.search(r'<p class="[^"]*hg-web-detail__desc[^"]*"[^>]*>(.*?)</p>', html, re.S)
        if m:
            desc = _clean(m.group(1))
        if not desc:
            m = re.search(r'<meta name="description" content="([^"]+)"', html)
            if m:
                desc = _clean(m.group(1))

        meta = ""
        m = re.search(r'class="[^"]*hg-web-detail__meta[^"]*"[^>]*>(.*?)</div>', html, re.S)
        if m:
            meta = _clean(m.group(1))
        tags = []
        for mm in re.finditer(r'class="hg-tag"[^>]*href="(/tag/[^"]+)"[^>]*>([^<]+)<', html):
            tags.append(_clean(mm.group(2)))
        remark = meta or "在线观看"

        # 剧集
        eps = []
        seen = set()
        ep_re = (r'href="(/video/' + re.escape(vid or "")
                 + r'/[^"]*?)"[^>]*>(.*?)</a>')
        _ep_num_re = re.compile(r'/(?:ep-?|episode-?|p|play-?)(\d+)/?', re.I)
        _fallback_seq = [0]

        def _label_from_path(path):
            m = _ep_num_re.search(path or "")
            if m:
                return "%02d" % int(m.group(1))
            _fallback_seq[0] += 1
            return "%02d" % _fallback_seq[0]

        if vid:
            for mm in re.finditer(ep_re, html, re.S):
                path = mm.group(1)
                if not path.startswith("/video/"):
                    continue
                if path in seen:
                    continue
                label = _label_from_path(path)
                seen.add(path)
                eps.append((label, path))
            if not eps:
                for mm in re.finditer(ep_re, vhtml or "", re.S):
                    path = mm.group(1)
                    if not path.startswith("/video/") or path in seen:
                        continue
                    label = _label_from_path(path)
                    seen.add(path)
                    eps.append((label, path))
                if not eps and vhtml:
                    for mm in re.finditer(
                            r'<a[^>]*class="hg-play__ep-item[^"]*"[^>]*href="([^"]*)"[^>]*data-ep-id="([^"]*)"[^>]*>(.*?)</a>',
                            vhtml, re.S):
                        path = mm.group(1)
                        ep_id = mm.group(2)
                        label = _label_from_path(path)
                        if ep_id and ep_id.isdigit() and label.startswith("0") and not _ep_num_re.search(path or ""):
                            label = "%02d" % int(ep_id)
                        if not path.startswith('/'):
                            path = '/' + path
                        if path not in seen:
                            seen.add(path)
                            eps.append((label, path))

        eps = sorted(eps, key=lambda x: self._ep_sort(x[1]))
        if not eps and vid:
            eps = [("01", f"/video/{vid}/")]

        play_from = ["正片"]
        play_url = ["#".join(f"{l}${p}" for l, p in eps)]

        vod = {
            "vod_id": vid or did,
            "vod_name": title,
            "vod_pic": self._wrap_pic(pic),
            "type_name": ",".join(tags) or "黄果短剧",
            "vod_remarks": remark,
            "vod_content": desc,
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
            "vod_year": "",
            "vod_area": "",
            "vod_actor": "",
            "vod_director": "",
        }
        return {"list": [vod]}

    def _detail_chigua(self, url):
        if not url.startswith("http"):
            url = self.host.rstrip('/') + (url if url.startswith('/') else '/' + url)
        try:
            html = self._get(url.replace(self.host, "")) if url.startswith(self.host) else ""
            if not html:
                r = rq.get(url, headers={"User-Agent": UA, "Referer": self.host + "/"},
                           timeout=TIMEOUT, verify=False)
                html = r.text if r.status_code == 200 else ""
        except Exception:
            return {"list": []}
        if not html:
            return {"list": []}

        title = ""
        m = re.search(r'<title>(.*?)</title>', html)
        if m:
            title = _clean(m.group(1).split('|')[0])

        players = re.findall(
            r'<div class="post-video-player"[^>]*data-player-key="([^"]*)"[^>]*data-src="([^"]*)"', html)
        if not players:
            players = re.findall(r'data-src="(https?://[^"]+\.m3u8[^"]*)"', html)
            players = [(f"线路{i+1}", u) for i, u in enumerate(players)]

        play = "#".join([f"{k}${v.replace('&amp;', '&')}" for k, v in players]) if players else ""

        video = {
            "vod_id": url,
            "vod_name": title or "吃瓜",
            "vod_pic": "",
            "vod_remarks": "",
            "vod_content": title,
            "type_name": "黄果吃瓜",
            "vod_play_from": "黄果吃瓜",
            "vod_play_url": play or f"正片${url}",
            "vod_year": "", "vod_area": "", "vod_actor": "", "vod_director": "",
        }
        return {"list": [video]}

    @staticmethod
    def _ep_sort(path):
        m = re.search(r'/(?:ep-?|episode-?|p|play-?)(\d+)/?', path or "", re.I)
        return int(m.group(1)) if m else 0

    # ─────────────────────────────────────────────────────
    # 播放
    # ─────────────────────────────────────────────────────
    def playerContent(self, flag, id, vipFlags=None, vipIds=None):
        key = str(id or "").strip()
        if not key:
            return {"parse": 0, "url": "", "header": {"User-Agent": UA}}

        def _norm(u):
            if not u:
                return ""
            u = str(u).replace("\\u0026", "&").replace("&amp;", "&").strip()
            if u.startswith("//"):
                u = "https:" + u
            return u

        def _direct(url):
            url = _norm(url)
            if not url:
                return ""
            if url.startswith("http") and self.isVideoFormat(url):
                return url
            if url.startswith("http") and any(
                    x in url for x in ['auth_key', 'playlist.m3u8', '/m3u8/', '.m3u8']):
                return url
            return ""

        if key.startswith("http"):
            u = _direct(key)
            if u:
                return self._mk_player(u)

        if flag == "黄果吃瓜" and key.startswith("http"):
            return self._mk_player(_norm(key))

        if key.isdigit():
            key = f"/video/{key}/"
        elif not key.startswith("/") and not key.startswith("http"):
            key = "/" + key

        html = self._get(key, ref="/")
        if not html:
            return {
                "parse": 1,
                "url": self.host.rstrip('/') + key,
                "header": {"User-Agent": UA, "Referer": self.host + "/"},
            }

        # 优先 videoInitialData
        m = re.search(
            r'<script id="videoInitialData" type="application/json">(.*?)</script>',
            html, re.S)
        if m:
            try:
                raw = m.group(1)
                data = None
                try:
                    data = json.loads(raw)
                except Exception:
                    for end in range(len(raw), max(0, len(raw) - 2000), -1):
                        try:
                            data = json.loads(raw[:end])
                            break
                        except Exception:
                            continue
                if data:
                    url = ""
                    for k in ("videoSrc", "videoUrl", "playUrl", "src",
                              "url", "video_src", "play_url"):
                        v = data.get(k)
                        if v and isinstance(v, str):
                            url = v
                            break
                    if not url:
                        eps = None
                        for k in ("epPlaySrcs", "episodes", "playSrcs",
                                  "ep_play_srcs", "playSources"):
                            v = data.get(k)
                            if isinstance(v, dict):
                                eps = v
                                break
                        if eps:
                            ep = data.get("ep") or data.get("episode") or data.get("currentEp")
                            pm = re.search(r'/ep-(\d+)/', key)
                            if pm and str(pm.group(1)) in eps:
                                url = eps[str(pm.group(1))]
                            elif ep is not None and str(ep) in eps:
                                url = eps[str(ep)]
                            else:
                                for ev in eps.values():
                                    if ev:
                                        url = ev
                                        break
                    url = _norm(url)
                    if url.startswith("http"):
                        return self._mk_player(url)
            except Exception:
                pass

        # data-play-src
        m = re.search(
            r'<article[^>]*class="[^"]*hg-play__slide[^"]*is-active[^"]*"[^>]*data-play-src="([^"]*)"',
            html)
        if not m:
            m = re.search(r'data-play-src="(https?://[^"]+)"', html)
        if m:
            url = _norm(m.group(1))
            if url.startswith("http"):
                return self._mk_player(url)

        return {
            "parse": 1,
            "url": self.host.rstrip('/') + key,
            "header": {"User-Agent": UA, "Referer": self.host + "/"},
        }

    def _mk_player(self, url):
        """统一播放出口：默认直链，proxy_play=1 才走 m3u8 代理重写"""
        if not url:
            return {"parse": 0, "url": "", "header": {"User-Agent": UA}}
        if self._enable_proxy_play and 'm3u8' in url.lower():
            url = self._proxy_url("m3u8", url)
        return {
            "parse": 0,
            "url": url,
            "header": {"User-Agent": UA, "Referer": self.host + "/"},
        }

    def _proxy_url(self, typ, url):
        b = f"proxy?do=py&type={typ}&url={urllib.parse.quote(url, safe='')}"
        return b

    # ─────────────────────────────────────────────────────
    # 播放代理（proxy_play=1 时启用）
    # ─────────────────────────────────────────────────────
    def _proxy_fetch(self, url, ctype):
        try:
            headers = {"User-Agent": UA, "Referer": self.host + "/"}
            r = rq.get(url, headers=headers, timeout=20, verify=False)
            if r.status_code != 200:
                return [502, "text/plain", f"err:{r.status_code}".encode()]
            return [200, ctype, r.content]
        except Exception as e:
            return [502, "text/plain", f"err:{e}".encode()]

    def _proxy_m3u8(self, url):
        try:
            headers = {"User-Agent": UA, "Referer": self.host + "/"}
            r = rq.get(url, headers=headers, timeout=20, verify=False)
            if r.status_code != 200:
                return [502, "text/plain", f"err:{r.status_code}".encode()]
            text = r.text
            host_base = re.match(r'https?://[^/]+', url)
            host_base = host_base.group(0) if host_base else ""
            path_dir = url[:url.rfind("/") + 1] if "/" in url else ""
            lines = []
            for line in text.split("\n"):
                s = line.strip()
                if not s:
                    continue
                if s.startswith("#"):
                    if 'URI="' in s:
                        mm = re.search(r'URI="([^"]*)"', s)
                        if mm:
                            u = mm.group(1)
                            if u.startswith("//"):
                                u = "https:" + u
                            elif u.startswith("/"):
                                u = host_base + u
                            elif not re.match(r'https?://', u):
                                u = path_dir + u
                            s = s[:mm.start(1)] + self._proxy_url("key", u) + s[mm.end(1):]
                    lines.append(s)
                    continue
                if re.match(r'https?://', s):
                    turl = s
                elif s.startswith("//"):
                    turl = "https:" + s
                elif s.startswith("/"):
                    turl = host_base + s
                else:
                    turl = path_dir + s
                lines.append(self._proxy_url("ts", turl))
            return [200, "application/vnd.apple.mpegurl", "\n".join(lines).encode("utf-8")]
        except Exception:
            return [502, "text/plain", b"err"]

    # ─────────────────────────────────────────────────────
    # localProxy 入口
    # ─────────────────────────────────────────────────────
    def localProxy(self, param):
        try:
            if isinstance(param, dict):
                typ = param.get("type") or ""
                url = param.get("url") or param.get("u") or ""
            else:
                typ = ""
                url = self._resolve_img_param(param)
            if not url:
                return None
            url = urllib.parse.unquote(url) if not url.startswith("http") else url
            url = self._resolve_img_param(url) or url

            if typ == "m3u8":
                return self._proxy_m3u8(url)
            if typ in ("ts", "key"):
                ct = "video/mp2t" if typ == "ts" else "application/octet-stream"
                return self._proxy_fetch(url, ct)

            # 图片
            headers = {"User-Agent": UA, "Referer": self.host + "/", "Accept": "image/*"}
            rr = rq.get(url, headers=headers, timeout=15, verify=False, allow_redirects=True)
            if rr.status_code == 200 and rr.content and len(rr.content) > 50:
                data = _decrypt_img(rr.content, self._enable_pure_aes)
                ctype = _detect_mime(data)
                return [200, ctype, data]
        except Exception:
            pass
        return None

    @staticmethod
    def _resolve_img_param(param):
        if not param:
            return ""
        p = str(param).strip()
        p = re.sub(r'^https?://127\.0\.0\.1:\d+/proxy\?', '', p)
        p = re.sub(r'^proxy\?', '', p)
        if "url=" in p:
            q = urllib.parse.parse_qs(p)
            cand = q.get("url", [""])[0]
            if cand:
                p = cand
        try:
            p = urllib.parse.unquote(p)
        except Exception:
            pass
        if not p.startswith("http"):
            try:
                dec = base64.b64decode(p + "==").decode("utf-8", "ignore")
                if dec.startswith("http"):
                    p = dec
            except Exception:
                pass
        return p if p.startswith("http") else ""

    # ─────────────────────────────────────────────────────
    # 列表解析
    # ─────────────────────────────────────────────────────
    def _parse_list(self, html, mode="drama"):
        if not html or len(html) < 150:
            return []
        if self._enable_bs4 and BeautifulSoup is not None:
            try:
                return self._parse_bs4(html, mode)
            except Exception:
                pass
        return self._parse_regex(html)

    def _parse_bs4(self, html, mode):
        videos, seen = [], set()
        doc = BeautifulSoup(html, _BS4_PARSER or "html.parser")

        if mode == "drama" or mode == "search":
            for card in doc.select("div.hg-drama-card"):
                a = card.find("a", href=True)
                if not a:
                    continue
                href = a.get("href", "")
                m = re.search(r"/detail/(\d+)", href)
                if not m:
                    continue
                vid = m.group(1)
                if vid in seen:
                    continue
                seen.add(vid)
                img = card.find("img")
                pic = ""
                if img:
                    pic = img.get("data-src") or img.get("src") or ""
                title = ""
                if img:
                    title = img.get("alt") or ""
                if not title:
                    t = card.select_one(".hg-drama-card__title a, .hg-drama-card__title, h2, h3")
                    title = t.get_text(strip=True) if t else ""
                if not title:
                    title = card.get("data-track-title") or ""
                parts = []
                for sel in [".hg-drama-card__score", ".hg-drama-card__episode",
                            ".hg-drama-card__badge"]:
                    el = card.select_one(sel)
                    if el:
                        parts.append(el.get_text(strip=True))
                remark = " ".join(parts).strip() or "在线观看"
                if title:
                    videos.append({
                        "vod_id": vid,
                        "vod_name": _clean(title),
                        "vod_pic": self._wrap_pic(pic),
                        "vod_remarks": remark,
                    })

            if mode == "search" and not videos:
                for a in doc.find_all("a", href=re.compile(r"/detail/\d+")):
                    m = re.search(r"/detail/(\d+)", a.get("href", ""))
                    if not m or m.group(1) in seen:
                        continue
                    seen.add(m.group(1))
                    img = a.find("img")
                    if not img:
                        continue
                    pic = img.get("data-src") or img.get("src") or ""
                    title = img.get("alt") or img.get("title") or a.get("title") or ""
                    if not title:
                        t = a.find(class_=re.compile("title"))
                        title = t.get_text(strip=True) if t else ""
                    remark = ""
                    for cls in ["episode", "score"]:
                        s = a.find(class_=re.compile(cls))
                        if s:
                            remark = s.get_text(strip=True)
                            break
                    if title:
                        videos.append({
                            "vod_id": m.group(1),
                            "vod_name": _clean(title),
                            "vod_pic": self._wrap_pic(pic),
                            "vod_remarks": remark or "在线观看",
                        })

        elif mode == "rank":
            for item in doc.select("div.hg-rank-item"):
                a = item.find("a", href=True, class_=re.compile("cover")) or item.find("a", href=True)
                if not a:
                    continue
                href = a.get("href", "")
                m = re.search(r"/detail/(\d+)", href)
                vid = m.group(1) if m else href
                if vid in seen:
                    continue
                seen.add(vid)
                img = item.find("img")
                pic = (img.get("data-src") or img.get("src") or "") if img else ""
                title = item.get("data-track-title") or (img.get("alt") if img else "") or ""
                if not title:
                    t = item.select_one(".hg-rank-item__title, h2")
                    title = t.get_text(strip=True) if t else ""
                heat = item.select_one(".hg-rank-item__heat-value")
                remark = ("🔥" + heat.get_text(strip=True)) if heat else ""
                if title:
                    videos.append({
                        "vod_id": vid,
                        "vod_name": _clean(title),
                        "vod_pic": self._wrap_pic(pic),
                        "vod_remarks": remark,
                    })

        elif mode == "topic":
            for card in doc.select("a.hg-topic-card"):
                href = card.get("href", "")
                slug = href.strip("/").split("/")[-1]
                img = card.find("img")
                pic = (img.get("data-src") or img.get("src") or "") if img else ""
                t = card.select_one(".hg-topic-card__title, h2")
                title = t.get_text(strip=True) if t else (img.get("alt") if img else "")
                meta = card.select_one(".hg-topic-card__meta")
                remark = meta.get_text(strip=True) if meta else ""
                if title:
                    videos.append({
                        "vod_id": "dir_topic_" + slug,
                        "vod_name": _clean(title),
                        "vod_pic": self._wrap_pic(pic),
                        "vod_remarks": remark,
                        "vod_tag": "folder",
                    })

        elif mode == "post":
            for card in doc.select("a.hg-post-card"):
                href = card.get("href", "")
                if not href:
                    continue
                img = card.find("img")
                pic = (img.get("data-src") or img.get("src") or "") if img else ""
                h3 = card.find("h3")
                title = h3.get_text(strip=True) if h3 else ""
                date = card.select_one(".hg-post-card__date")
                cat = card.select_one(".hg-post-card__cat")
                parts = [s.get_text(strip=True) for s in (date, cat) if s]
                videos.append({
                    "vod_id": href if href.startswith("http") else self.host + href,
                    "vod_name": _clean(title),
                    "vod_pic": self._wrap_pic(pic),
                    "vod_remarks": " | ".join(parts),
                })

        return videos

    def _parse_regex(self, html):
        result, seen = [], set()
        for block in re.split(r'<div class="hg-drama-card"', html)[1:]:
            m = re.search(r'href="(/detail/(\d+)/)"', block)
            if not m:
                continue
            vid = m.group(2)
            if vid in seen:
                continue
            pic = ""
            pm = re.search(r'data-src="([^"]+)"', block)
            if pm:
                pic = htmllib.unescape(pm.group(1)).strip()
            if not pic:
                pm = re.search(r'<img[^>]*src="([^"]+)"', block)
                if pm:
                    pic = htmllib.unescape(pm.group(1)).strip()
            title = ""
            tm = re.search(
                r'class="[^"]*hg-drama-card__title[^"]*"[^>]*>\s*<a[^>]*>(.*?)</a>',
                block, re.S)
            if tm:
                title = _clean(tm.group(1))
            if not title:
                tm = re.search(r'<img[^>]*alt="([^"]+)"', block)
                if tm:
                    title = _clean(tm.group(1))
            parts = []
            sm = re.search(r'class="hg-drama-card__score">([^<]+)<', block)
            if sm:
                parts.append(_clean(sm.group(1)))
            em = re.search(r'class="hg-drama-card__episode">([^<]+)<', block)
            if em:
                parts.append(_clean(em.group(1)))
            remark = " ".join(parts).strip() or "在线观看"
            if not title:
                continue
            seen.add(vid)
            result.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": self._wrap_pic(pic),
                "vod_remarks": remark,
            })
        return result

    # ─────────────────────────────────────────────────────
    def isVideoFormat(self, url):
        return any(x in (url or '') for x in ['.m3u8', '.mp4', '.flv', '.mkv', '.avi'])

    def manualVideoCheck(self):
        return False


Spider = Spider