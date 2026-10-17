# -*- coding: utf-8 -*-
"""
黄瓜短剧 hgdju.com —— TVBox / 影视仓 / OK影视 / PickTV 源
================================================================
站点：https://hgdju.com （Nuxt.js SSR）
内容：690 部 AI短剧/漫剧/魔改/原创/真人短剧，**全免费、无需登录**

链路（全部实测通过）：
    /browse?line={cat}&page={n}  列表（SSR，30/页，共 23 页）
    /drama/{slug}                详情（剧名 / 共N集 / 剧集链接）
    /play/{slug}/{ep}            播放页，SSR 内嵌带 auth_key 的 m3u8
        → https://hls.tpbbwcc.cn/videos5/{hash}/{hash}.m3u8?auth_key=...&via=51duanju
        → 分片在 mts.hhjd.mobi，EXT-X-KEY → crypt.key（16B）
        → AES-128-CBC 解密 → MPEG-TS 0x47 ✓

站点坑点：
  * m3u8 地址在 SSR HTML 中以 \\u002F 转义形式出现，需先反转义再正则
  * auth_key 有效期约 2 小时 → 播放地址必须实时抓取，不能缓存
  * 无 Referer/UA 防盗链，但部分页面偶发 503/超时 → 需重试
  * 封面图走加密 API，SSR HTML 无封面 → 留空（不影响播放）
"""

import re
import time
import html as _html
import urllib.parse
import urllib.request
import urllib.error
import gzip
import io
from concurrent.futures import ThreadPoolExecutor

# ------------------------------------------------------------------ 常量
HOST = "https://hgdju.com"
UA = ("Mozilla/5.0 (Linux; Android 12; SM-G975F) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

# 分类（value 为空表示全部）
CATEGORIES = [
    ("", "全部"),
    ("aiduanju", "AI短剧"),
    ("manju", "漫剧"),
    ("mogai", "魔改"),
    ("yuanchuang", "原创"),
    ("zhenren", "真人短剧"),
]

# 列表页卡片：<a href="/drama/{slug}" ... aria-label="{name} 详情">
RE_CARD = re.compile(r'<a href="/drama/([a-z0-9-]+)"[^>]*aria-label="([^"]*?)\s*详情"')
# 封面（SSR 中以 \u002F 转义出现）
RE_COVER_ESC = re.compile(r'https:\\u002F\\u002F[a-z0-9.-]+(?:\\u002F[^"]{1,200}?)?\.(?:jpe?g|png|webp)')
# 详情页剧集链接（限定当前 slug，避免混入推荐位）
RE_EP = r'href="/play/%s/(\d+)"'
# 详情页标题 / 集数
RE_TITLE = re.compile(r'<title>([^<]*)</title>')
RE_TOTAL = re.compile(r'共(\d+)集')
# 播放页 m3u8（先反转义 \u002F）
RE_M3U8 = re.compile(r'(https?://[^\s"\'<>\\]{10,300}?\.m3u8[^\s"\'<>\\]*)')
RE_M3U8_ESC = re.compile(r'(https:\\u002F\\u002F[^"]{10,400}?\.m3u8[^"]*)')

# ------------------------------------------------------------------ 本地代理
# ★ 关键：不同壳的代理入口不一样（TVBox 系多为 127.0.0.1:9978/proxy，
#   影视仓/OK影视/PickTV 各不相同），硬编码或只用 proxy:// 前缀会导致封面全空。
#   优先向壳索取（getProxyUrl），拿不到再退回 TVBox 默认入口。
PROXY_FALLBACK = "http://127.0.0.1:9978/proxy"


# ------------------------------------------------------------------ 图片解密
# 站点海报是 AES-128-CBC/PKCS7 加密的（Content-Type 还错标成 octet-stream）
# key/iv 取自前端编译常量 ZE / QE（经 Lo()/Qt() 转换后即 UTF-8 字节）
IMG_KEY = b"f5d965df75336270"
IMG_IV = b"97b60394abc2fbe1"


def _decrypt_img(data):
    """解密站点海报，失败则原样返回"""
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad
        pt = AES.new(IMG_KEY, AES.MODE_CBC, IMG_IV).decrypt(data)
        pt = unpad(pt, 16)
        # 校验图片魔数
        if pt[:3] == b"\xff\xd8\xff" or pt[:4] == b"\x89PNG" or pt[:3] == b"GIF" or pt[8:12] == b"WEBP":
            return pt
    except Exception:
        pass
    return data


def _img_mime(data):
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:3] == b"GIF":
        return "image/gif"
    if data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _fetch_bytes(url, timeout=25):
    """下载二进制（不解码）"""
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "image/*,*/*",
                "Referer": HOST + "/",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception:
            time.sleep(0.5 * (i + 1))
    return b""


# ------------------------------------------------------------------ HTTP
def _fetch(url, timeout=20, retry=3, referer=None):
    """带重试的 GET，返回文本（自动解 gzip）"""
    for i in range(retry):
        try:
            headers = {
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/json,*/*",
                "Accept-Encoding": "gzip",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
            if referer:
                headers["Referer"] = referer
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                for enc in ("utf-8", "gbk", "latin-1"):
                    try:
                        return raw.decode(enc)
                    except UnicodeDecodeError:
                        continue
                return raw.decode("utf-8", "replace")
        except Exception:
            time.sleep(0.6 * (i + 1))
    return ""


def _abs(u):
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return HOST + u
    return u


# ------------------------------------------------------------------ Spider
class Spider(object):
    """黄瓜短剧"""

    def __init__(self):
        self.host = HOST
        self.ua = UA
        # True：封面内联缩略图（不依赖壳代理端口，四壳通用）
        # False：走本地代理地址（省流量，但需要壳支持 localProxy）
        self.inline_pic = True
        # 诊断模式：把封面替换成站点自带的未加密图片，用于判断
        # 「壳到底认不认 vod_pic 字段」。把 DIAG 改成 True 重新加载源即可。
        self.DIAG = False

    # ---------------- 标准接口 1/13
    def getDependence(self):
        return ["requests"]

    # ---------------- 2/13
    def init(self, extend=""):
        return

    # ---------------- 工具
    def _proxy_base(self):
        """向壳索取本地代理入口（不同壳端口不同）"""
        for getter in ("getProxyUrl", "get_proxy_url", "proxyUrl"):
            fn = getattr(self, getter, None)
            if callable(fn):
                try:
                    u = fn()
                    if u and isinstance(u, str) and u.startswith("http"):
                        return u.rstrip("&?")
                except Exception:
                    pass
        return PROXY_FALLBACK

    def _pic_url(self, u):
        """站点海报是加密的 → 经本地代理解密后再交给壳"""
        if not u:
            return ""
        base = self._proxy_base()
        sep = "&" if "?" in base else "?"
        return base + sep + "type=img&url=" + urllib.parse.quote(u, safe="")

    def _data_uri(self, u, max_w=320, quality=72):
        """抓图 → 解密 → 压成缩略图 → 内联 data URI
        ★ 不依赖壳的本地代理端口，四壳通用；压缩后体积可控（约 10~25KB）"""
        if not u:
            return ""
        try:
            data = _fetch_bytes(u, timeout=10)
            if not data:
                return ""
            data = _decrypt_img(data)
            if not (data[:3] == b"\xff\xd8\xff" or data[:4] == b"\x89PNG"
                    or data[:3] == b"GIF" or data[8:12] == b"WEBP"):
                return ""
            try:
                from PIL import Image
                import io as _io
                import base64 as _b64
                img = Image.open(_io.BytesIO(data))
                img = img.convert("RGB")
                w, h = img.size
                if w > max_w:
                    img = img.resize((max_w, max(1, int(h * max_w / float(w)))), Image.LANCZOS)
                buf = _io.BytesIO()
                img.save(buf, "JPEG", quality=quality, optimize=True)
                return "data:image/jpeg;base64," + _b64.b64encode(buf.getvalue()).decode()
            except ImportError:
                # 没有 PIL 就退回原图内联
                import base64 as _b64
                return "data:%s;base64,%s" % (_img_mime(data), _b64.b64encode(data).decode())
        except Exception:
            return ""

    @staticmethod
    def _unesc(u):
        """反转义 \\u002F → /"""
        if not u:
            return ""
        try:
            return u.encode().decode("unicode_escape").replace("\\/", "/")
        except Exception:
            return u.replace("\\u002F", "/")

    def _parse_cards(self, txt):
        """列表页 → [{vod_id, vod_name, vod_pic, vod_remarks}]"""
        out = []
        seen = set()
        for slug, name in RE_CARD.findall(txt):
            if slug in seen:
                continue
            seen.add(slug)
            name = _html.unescape(name).strip()
            out.append({
                "vod_id": slug,
                "vod_name": name,
                "vod_pic": "",
                "vod_remarks": "",
            })
        # 封面（按出现顺序对应卡片）
        # 列表页的转义图片按卡片顺序排列（每卡一张），不过滤以免错位
        covers = [Spider._unesc(x) for x in RE_COVER_ESC.findall(txt)]
        covers = [c for c in covers if c]
        if self.DIAG:
            for i in range(len(out)):
                out[i]["vod_pic"] = "https://hgdju.com/images/shared/logo.png"
            return out
        # 封面：并行抓取并压成缩略图内联（不依赖壳的代理端口）
        if covers:
            n = min(len(covers), len(out))
            if self.inline_pic:
                try:
                    with ThreadPoolExecutor(max_workers=8) as ex:
                        thumbs = list(ex.map(lambda c: self._data_uri(c, 200, 60), covers[:n]))
                except Exception:
                    thumbs = []
                for i in range(n):
                    t = thumbs[i] if i < len(thumbs) else ""
                    out[i]["vod_pic"] = t or self._pic_url(covers[i])
            else:
                for i in range(n):
                    out[i]["vod_pic"] = self._pic_url(covers[i])
        # 集数（"全N集"）按顺序回填
        totals = re.findall(r'>全(\d+)集<', txt)
        for i, t in enumerate(totals):
            if i < len(out):
                out[i]["vod_remarks"] = "全%s集" % t
        return out

    @staticmethod
    def _parse_episodes(txt, slug):
        """详情页 → 集号列表（升序去重）"""
        eps = sorted({int(x) for x in re.findall(RE_EP % re.escape(slug), txt)})
        return eps

    @staticmethod
    def _extract_m3u8(txt):
        """播放页 → m3u8 绝对地址"""
        # 1) 反转义 \u002F
        m = RE_M3U8_ESC.search(txt)
        if m:
            u = m.group(1).encode().decode("unicode_escape")
            return u.replace("\\/", "/")
        # 2) 直接形式
        m = RE_M3U8.search(txt)
        if m:
            return _html.unescape(m.group(1)).replace("\\/", "/")
        return ""

    # ---------------- 3/13 首页
    def homeContent(self, filter):
        result = {"class": [], "filters": {}}
        for tid, name in CATEGORIES:
            result["class"].append({"type_id": tid, "type_name": name})
        return result

    # ---------------- 4/13 首页推荐
    def homeVideoContent(self):
        txt = _fetch(HOST + "/", timeout=20)
        return {"list": self._parse_cards(txt)[:20]}

    # ---------------- 5/13 分类
    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        url = "%s/browse?page=%d" % (HOST, pg)
        if tid:
            url += "&line=" + urllib.parse.quote(str(tid))
        txt = _fetch(url, timeout=25)
        vlist = self._parse_cards(txt)
        return {
            "list": vlist,
            "page": pg,
            "pagecount": 23,          # /browse 固定 23 页
            "limit": 30,
            "total": 690,
        }

    # ---------------- 6/13 详情
    def detailContent(self, ids):
        if isinstance(ids, (list, tuple)):
            vod_id = ids[0] if ids else ""
        else:
            vod_id = str(ids)
        slug = str(vod_id).split("$")[0].strip()
        txt = _fetch("%s/drama/%s" % (HOST, slug), timeout=25, referer=HOST + "/")
        name = ""
        m = RE_TITLE.search(txt)
        if m:
            name = m.group(1).split("在线观看")[0].strip()
        if not name:
            name = slug
        eps = self._parse_episodes(txt, slug)
        if not eps:
            eps = [1]
        # 简介
        desc = ""
        md = re.search(r'<meta name="description" content="([^"]*)"', txt)
        if md:
            desc = _html.unescape(md.group(1))
        # 封面（详情页第一个转义图片即本剧海报）
        covers = [self._unesc(x) for x in RE_COVER_ESC.findall(txt)]
        # 详情页混有站点装饰图（/new/xiao/…）→ 只取海报目录 /upload_01/cover/
        posters = [c for c in covers if "/upload_01/cover/" in c] or covers
        # 封面优先内联 data URI（不依赖壳的代理端口，必定显示），失败退回本地代理
        pic = self._data_uri(posters[0], 320, 72) if posters else ""
        if not pic and posters:
            pic = self._pic_url(posters[0])

        play_from = "黄瓜短剧"
        play_url = "#".join("%s$%s/play/%s/%d" % ("第%d集" % e, HOST, slug, e) for e in eps)
        return {"list": [{
            "vod_id": slug,
            "vod_name": name,
            "vod_pic": pic,
            "type_name": "短剧",
            "vod_year": "",
            "vod_area": "国产",
            "vod_remarks": "共%d集" % len(eps),
            "vod_actor": "",
            "vod_director": "",
            "vod_content": desc,
            "vod_play_from": play_from,
            "vod_play_url": play_url,
        }]}

    # ---------------- 7/13 搜索
    def searchContent(self, key, quick, pg="1"):
        kw = urllib.parse.quote(str(key))
        txt = _fetch("%s/search?keyword=%s" % (HOST, kw), timeout=25)
        return {"list": self._parse_cards(txt)}

    # ---------------- 8/13 播放
    def playerContent(self, flag, id, vipFlags):
        url = str(id)
        if not url.startswith("http"):
            url = _abs(url)
        txt = _fetch(url, timeout=25, referer=HOST + "/")
        m3u8 = self._extract_m3u8(txt)
        if not m3u8:
            return {"parse": 0, "playUrl": "", "url": url,
                    "header": {"User-Agent": UA}}
        return {
            "parse": 0,
            "playUrl": "",
            "jx": 0,
            "url": m3u8,
            "header": {"User-Agent": UA},
        }

    # ---------------- 9/13 本地代理（解密海报）
    def localProxy(self, param):
        try:
            do = str(param.get("do", "")) if isinstance(param, dict) else ""
            typ = str(param.get("type", "")) if isinstance(param, dict) else ""
            url = param.get("url", "") if isinstance(param, dict) else ""
            url = urllib.parse.unquote(str(url))
            if not url:
                return None
            if not (typ == "img" or do in ("pic", "img")):
                return None
            data = _fetch_bytes(url)
            if not data:
                return None
            data = _decrypt_img(data)
            return [200, _img_mime(data), data]
        except Exception:
            return None

    # ---------------- 10/13
    def manualVideoCheck(self):
        return False

    # ---------------- 11/13
    def isVideoFormat(self, url):
        u = str(url).lower()
        return ".m3u8" in u or ".mp4" in u or ".ts" in u

    # ---------------- 12/13
    def action(self, action):
        return {}

    # ---------------- 13/13
    def destroy(self):
        return
