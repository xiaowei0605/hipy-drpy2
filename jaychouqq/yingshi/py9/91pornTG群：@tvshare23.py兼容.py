# coding: utf-8
"""91porn TVBox 源 —— Hawk 兼容纯标准库版。

与 requests/pyquery 版的差异仅为运行时依赖：
  - HTTP：urllib.request + http.cookiejar + gzip/zlib（Hawk 的 Python 运行时不保证
    提供 requests / pyquery，故按注视影视、hanime 两个 Hawk 源的成熟模式改写）
  - 解析：正则提取（91porn 卡片结构简单稳定，真实卡片必带 view_video...viewkey= 链接，
    混淆/广告卡片没有，按链接提取天然过滤）
  - base.spider 导入失败时用本地 SpiderBase 兜底（getCache/setCache/delCache 全部空实现），
    保证在未提供 base 模块的壳里也能加载；无缓存时域名发现自动退化为每次探测。

功能逻辑（域名池 / zj.php 鉴别 / 内容校验 / 域名轮换 / strencode2 与三参 strencode
解码 / ev.php 兜底链 / 未成年人标题过滤）与修复版完全一致。
"""
import re
import sys
import time
import base64
import gzip
import zlib
import ssl
import html as html_lib
import urllib.parse
import urllib.request
import urllib.error
import http.cookiejar

try:
    from base.spider import Spider as SpiderBase
except ImportError:
    class SpiderBase(object):
        def getCache(self, key): return None
        def setCache(self, key, value): return "fail"
        def delCache(self, key): return "fail"

# ── 未成年人保护：标题命中以下关键词的条目一律过滤 ──────────────────
_TITLE_BLOCKLIST = ('萝莉', '幼女', '幼齒', '幼齿', '小学生', '初中生',
                    '中学生', '儿童', '孩童', '正太')

# 页面广告/推广关键词（标题命中即跳过）
_AD_TITLE_KEYWORDS = ('广告', 'sponsor', '推广', '赞助')


def _strencode_decode(arg0, arg1, arg2):
    """纯 Python 复刻站点 videojs/m.js 的 strencode(data, key1, key2)。

    依据 Node 插桩确定的执行顺序（2026-10 实测）：
      1. key2 末字符为 '2' 时交换 data/key1（JS 弱相等 '2'==2 成立）
      2. data = atob(交换后的 data)
      3. code[i] = data[i] ^ key[i % len(key)]（key 为交换后的另一参原文）
      4. return atob(code)  →  <source src='...mp4?secure=...,<ts>&f=...'>
    """
    if not arg0 or not arg1:
        return ''
    try:
        if len(arg2) > 0 and arg2[-1] == '2':
            data_b64, key = arg1, arg0
        else:
            data_b64, key = arg0, arg1
        data = base64.b64decode(data_b64 + '=' * (-len(data_b64) % 4))
        key_bytes = key.encode('latin-1', errors='ignore') or b'\x00'
        xored = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(data))
        return base64.b64decode(xored + b'=' * (-len(xored) % 4)).decode('utf-8', errors='replace')
    except Exception:
        return ''


def _clean_text(s):
    """去 HTML 标签 / 实体 / 首尾空白"""
    if not s:
        return ''
    s = re.sub(r'<[^>]+>', '', s)
    s = html_lib.unescape(s)
    return s.strip()


class Spider(SpiderBase):
    def __init__(self):
        self.name = '91pron'
        # 域名池：2026-10-24 实测有效域名在前，历史域名兜底。
        # 站点定期轮换发布域名，_fetch 内置内容校验 + 自动轮换，
        # init() 另有 zj.php 官方鉴别页自动发现机制（见 _probe_host）。
        self.hosts = [
            'https://716.sol148.com/',
            'https://sp2026.com/',
            'https://a.26702.app/',
            'https://9p234.com/',
            'https://btc620.com/',
            'https://91porn.fun/',
            'https://91porn.com/',
            'https://a.91kp.net/',
            'https://0708.fs708.com/'
        ]
        self.host = self.hosts[0]  # 默认使用第一个有效域名
        self.host_cache_key = '91porn_valid_host'
        self._host_checked = False  # init/_fetch 中验证过一次后置 True

        self._ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')

        # ── 纯标准库 HTTP 客户端（替代 requests.Session）──────────────────
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE
        try:
            self.ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        except Exception:
            pass
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=self.ctx)
        )
        # 预置基础 Cookie（CLIPSHARE 真实值由服务端在首个响应时下发，
        # 此处 '1' 仅为占位；实测新域名对直连直接放行并自动下发真 Cookie）
        self._seed_cookies(self.host)

    # ── 基础方法 ──────────────────────────────────────────────────────
    def getName(self):
        return self.name

    def init(self, extend=""):
        """加载时确定有效域名：缓存优先 → zj.php 官方鉴别 → 域名池遍历。
        全部失败也不阻塞（沿用 hosts[0]，_fetch 内还会继续轮换重试）。"""
        try:
            cached = self._get_cache(self.host_cache_key)
            if cached and str(cached).startswith('http'):
                cand = str(cached).strip().rstrip('/') + '/'
                if cand in self.hosts and self._probe_host(cand):
                    self._set_host(cand)
                    self._host_checked = True
                    return
        except Exception:
            pass
        try:
            self._discover_host()
        except Exception:
            pass

    def isVideoFormat(self, url):
        return any(ext in (url or '').lower() for ext in ['.m3u8', '.mp4', '.ts'])

    def manualVideoCheck(self):
        return False

    # ── 缓存读写（兼容无缓存方法的 base.spider 实现）──────────────────
    def _get_cache(self, key):
        try:
            return self.getCache(key)
        except Exception:
            return None

    def _set_cache(self, key, value):
        try:
            self.setCache(key, value)
        except Exception:
            pass

    # ── Cookie / 域名 ─────────────────────────────────────────────────
    def _seed_cookies(self, host):
        """向 CookieJar 写入基础 Cookie（域名切换后需为新域名补种）。"""
        netloc = urllib.parse.urlparse(host).netloc
        if not netloc:
            return
        for name, value in (('language', 'cn_CN'), ('over18', '1'), ('CLIPSHARE', '1')):
            try:
                self.cj.set_cookie(http.cookiejar.Cookie(
                    version=0, name=name, value=value, port=None,
                    port_specified=False, domain=netloc, domain_specified=True,
                    domain_initial_dot=False, path='/', path_specified=True,
                    secure=False, expires=int(time.time()) + 30 * 86400,
                    discard=True, comment=None, comment_url=None, rest={},
                    rfc2109=False))
            except Exception:
                pass

    def _set_host(self, host):
        self.host = host
        self._seed_cookies(host)

    def _abs_href(self, href):
        if not href:
            return ''
        href = _clean_text(href)
        if href.startswith('http'):
            return href
        if href.startswith('//'):
            return f"https:{href}"
        return f"{self.host.rstrip('/')}/{href.lstrip('/')}"

    # ── HTTP（urllib 版 _fetch，含域名轮换 + 内容校验 + 外链去重）──────
    def _req_headers(self, referer=''):
        return {
            'User-Agent': self._ua,
            'Referer': referer or self.host,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        }

    def _open_once(self, url, headers, timeout):
        """单次请求，返回 (code, text)；不抛异常。"""
        try:
            req = urllib.request.Request(url, headers=headers)
            with self.opener.open(req, timeout=timeout) as resp:
                code = resp.getcode()
                raw = resp.read()
                enc = ''
                try:
                    enc = (resp.headers.get('Content-Encoding') or '').lower()
                except Exception:
                    pass
                if raw.startswith(b'\x1f\x8b') or enc == 'gzip':
                    raw = gzip.decompress(raw)
                elif enc == 'deflate':
                    try:
                        raw = zlib.decompress(raw)
                    except Exception:
                        raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                try:
                    text = raw.decode('utf-8')
                except Exception:
                    text = raw.decode('latin1', errors='ignore')
                return code, text
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
                try:
                    return e.code, body.decode('utf-8', errors='ignore')
                except Exception:
                    return e.code, ''
            except Exception:
                return e.code, ''
        except Exception as e:
            return -1, str(e)

    def _fetch(self, url, referer='', timeout=12):
        """核心：session(CookieJar) 保持 + 响应内容校验 + 失效域名自动轮换。

        与 requests 版行为一致：
        - 200 且通过 _content_ok 才采纳（拒绝 CF 挑战页/年龄门/空页）
        - 每域名 1 次快失败，全池扫完 worst-case ~90s
        - 域名切换后同步更新并缓存新域名
        - 外链域名（如 ev.php 专用解析域 91.9p9.xyz）不在 hosts 池内，
          去重避免同一地址重复请求全池次数
        返回 (code, text)；code<=0 表示失败。
        """
        if not self._host_checked:
            try:
                self._discover_host()
            except Exception:
                pass

        headers = self._req_headers(referer)

        # 当前主机优先，其余域名兜底
        host_order = [self.host] + [h for h in self.hosts if h != self.host]
        tried_urls = set()
        for host in host_order:
            target_url = url
            replaced = False
            for old_host in self.hosts:
                if old_host in target_url:
                    target_url = target_url.replace(old_host, host)
                    replaced = True
                    break
            if not replaced and not target_url.startswith('http'):
                target_url = f"{host.rstrip('/')}/{target_url.lstrip('/')}"

            if target_url in tried_urls:
                continue
            tried_urls.add(target_url)

            code, text = self._open_once(target_url, headers, timeout)
            if code == 200 and self._content_ok(text):
                if host != self.host:
                    self._set_host(host)
                    self._set_cache(self.host_cache_key, host)
                return 200, text

        return 404, ''

    # ── 域名发现 / 验证 ──────────────────────────────────────────────
    def _probe_host(self, host):
        """用站点官方鉴别页 zj.php 验证域名真假。

        站点声明：任何真域名后面加 /zj.php 都会显示鉴别页并回显"<域名> 是真的"；
        假域名/停运域名无此页（404 / CF 挑战 / 连接失败）。
        鉴别页不可用时兜底验证首页是否含视频卡片。
        """
        base = host.rstrip('/')
        headers = self._req_headers()
        code, text = self._open_once(base + '/zj.php', headers, 8)
        if code == 200 and '鉴别网站真假' in text and '是真的' in text:
            return True
        code, text = self._open_once(base + '/index.php', headers, 8)
        if code == 200 and self._content_ok(text):
            return True
        return False

    def _discover_host(self):
        """遍历域名池，选定第一个通过验证的域名并缓存。"""
        for host in self.hosts:
            if self._probe_host(host):
                self._set_host(host)
                self._host_checked = True
                self._set_cache(self.host_cache_key, host)
                return True
        self._host_checked = True  # 标记已检查过，避免每次 _fetch 都全池重扫
        return False

    def _content_ok(self, text):
        """识别 Cloudflare 挑战页 / 年龄门 / 空页，返回是否为真实站点内容。

        修复要点：停运域名与被 CF 拦截的域名也会返回 HTTP 200（挑战页约 1.3KB、
        年龄门约 3KB），旧逻辑仅校验「200 + 非空」会把它们当成功响应，
        导致列表/详情全空却毫无报错。
        """
        if not text:
            return False
        t = text.strip()
        if len(t) < 300:
            return False
        low = t.lower()
        for bad in ('cf-browser-verification', 'challenge-platform', 'just a moment',
                    'attention required', 'cdn-cgi/l/chk_jsch'):
            if bad in low:
                return False
        if '我已年满18岁' in t or 'i am at least 18 years' in low:
            return False  # 年龄门未过
        for good in ('view_video.php', 'viewkey=', 'strencode2', 'strencode(',
                     'player_one', '是真的'):
            if good in t:
                return True
        return len(t) > 3000  # 其他长页面兜底（如 ev.php）

    # ── 列表解析（正则替代 pyquery）──────────────────────────────────
    def _parse_video_items(self, html_text):
        """解析视频卡片列表。

        真实卡片结构（2026-10 实测，普通/高清分类同构）：
            <a href=".../view_video.php?viewkey=XXX&...">
              <div class="thumb-overlay" id="playvthumb_1253819">
                <img class="img-responsive" src="https://.../thumb/1253819.jpg">
                <div class="original-text-icon">91</div>
                <span class="duration">00:04:25</span>
              </div>
              <span class="video-title title-truncate m-t-5">标题</span>
            </a>
        高清分类(hd)卡片链接是 view_video_hd.php，用 view_video 前缀同时覆盖
        （旧选择器 a[href*="view_video.php"] 漏掉 HD 全类）。
        混淆/广告卡片(col-lg-8)不含 viewkey 链接，按链接提取天然过滤；
        <a> 内无嵌套 <a>，(.*?)</a> 不会越过卡片边界。
        """
        vlist = []
        if not html_text:
            return vlist

        blocks = re.findall(
            r'<a[^>]*href=["\']([^"\']*view_video[^"\']*viewkey=[^"\']*)["\'][^>]*>(.*?)</a>',
            html_text, re.I | re.S)

        seen_ids = set()
        for href, inner in blocks:
            try:
                href = html_lib.unescape(href).strip()
                url = self._abs_href(href)

                vk_m = re.search(r'viewkey=([a-zA-Z0-9]+)', url)
                v_id = vk_m.group(1) if vk_m else url
                if v_id in seen_ids:
                    continue

                # 标题：优先 video-title 容器，回退 title/alt 属性
                title = ''
                t_m = re.search(
                    r'<span[^>]*class=["\'][^"\']*video-title[^"\']*["\'][^>]*>(.*?)</span>',
                    inner, re.I | re.S)
                if t_m:
                    title = _clean_text(t_m.group(1))
                if not title:
                    t_m = re.search(r'(?:title|alt)=["\']([^"\']+)["\']', inner, re.I)
                    if t_m:
                        title = _clean_text(t_m.group(1))
                if not title:
                    continue
                if any(kw in title.lower() for kw in _AD_TITLE_KEYWORDS):
                    continue

                # 未成年人保护：标题命中黑名单关键词的条目一律过滤
                if any(kw in title for kw in _TITLE_BLOCKLIST):
                    continue

                # 封面：data-src 优先，回退 src；过滤占位图
                pic = ''
                p_m = re.search(
                    r'<img[^>]*?\s(?:data-src|src)=["\']([^"\']+)["\']', inner, re.I)
                if p_m:
                    pic = p_m.group(1)
                if not pic:
                    p_m = re.search(r'<img[^>]*\ssrc=["\']([^"\']+)["\']', inner, re.I)
                    if p_m:
                        pic = p_m.group(1)
                if pic and any(k in pic for k in ('loading', 'blank', 'default')):
                    pic = ''
                pic = self._abs_href(pic) if pic else ''

                # 时长
                duration = '未知'
                d_m = re.search(r'<span[^>]*class=["\'][^"\']*duration[^"\']*["\'][^>]*>(.*?)</span>',
                                inner, re.I | re.S)
                if d_m:
                    duration = _clean_text(d_m.group(1)) or '未知'

                seen_ids.add(v_id)
                vlist.append({
                    'vod_id': url,
                    'vod_name': title,
                    'vod_pic': pic,
                    'vod_remarks': duration
                })
            except Exception:
                continue

        return vlist

    def _parse_pagecount(self, html_text):
        try:
            nums = [int(x) for x in re.findall(r'(?:[?&]|&amp;)page=(\d+)', html_text or '')]
            if nums:
                return max(nums)
            page_nums = [int(a) for a in re.findall(
                r'class=["\'][^"\']*(?:pagination|pagingnav)[^"\']*["\'][^>]*>.*?<a[^>]*>\s*(\d+)\s*</a>',
                html_text or '', re.I | re.S)]
            return max(page_nums) if page_nums else 1
        except Exception:
            return 1

    # ── TVBox 接口 ───────────────────────────────────────────────────
    def homeContent(self, filter):
        result = {'class': [{'type_name': k, 'type_id': v} for k, v in self.class_map.items()]}
        try:
            code, html = self._fetch(f"{self.host}index.php")
            result['list'] = self._parse_video_items(html)
        except Exception:
            result['list'] = []
        return result

    def homeVideoContent(self):
        return []

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg or 1)
        try:
            if tid == 'top_m':
                url = f"{self.host}v.php?category=top&m=-1&viewtype=basic&page={pg}"
            else:
                url = f"{self.host}v.php?category={tid}&viewtype=basic&page={pg}"

            code, html = self._fetch(url)
            return {
                'list': self._parse_video_items(html),
                'page': pg,
                'pagecount': self._parse_pagecount(html),
                'limit': 24,
                'total': 999999
            }
        except Exception:
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 0, 'total': 0}

    # ── 视频地址提取 ─────────────────────────────────────────────────
    def _extract_video_url_from_html(self, html):
        """提取视频直链。

        站点现行结构（2026-10 实测）：
          普通视频详情页：
            <script>document.write(strencode2("%3csource src='https://la.btc620.com//mp43/1254384.mp4?st=...&e=<过期时间戳>&f=...'))</script>
            strencode2 内是 URL 编码的 <source src='...'> 标签，unquote 后正则取 src。
          高清视频(view_video_hd.php 详情页无任何地址)：
            ev.php 页 <script>document.write(strencode("<data>","<key1>","<key2>"))</script>
            三参 strencode 解码后得 <source src='https://<cdn>.rsc.cdn77.org/mp43/<vid>.mp4?secure=...,<ts>&f=...'>
        签名参数 st/e/f 有时效（约 1 小时），详情页每次拉取都是新鲜的。
        """
        if not html:
            return None

        # 0. 页面内嵌 VID（兜底校验用，防止取到相关视频的地址播错片）
        # 新版详情页 VID 形如 b3db2Stxvm1XSBkEVlCLZ8W2pvN4lN7JSq0dHHaIH-MZkzi_4Q
        #（含 - _，位于 <input id="VID" value="...">）；旧版为
        # <span id="VID" style="display:none;">1253819</span> 纯数字，两种形态都兼容。
        page_vid = None
        vid_m = (re.search(r'id=["\']VID["\'][^>]*?value=["\']([a-zA-Z0-9_-]+)["\']', html)
                 or re.search(r'id=["\']VID["\'][^>]*>\s*([a-zA-Z0-9_-]+)', html))
        if vid_m:
            page_vid = vid_m.group(1)

        # 1. 精准提取 strencode2("...") 里面的字符串参数并解码
        for enc_str in re.findall(r'strencode2\((?:["\'])(.*?)(?:["\'])\)', html):
            try:
                decoded_tag = urllib.parse.unquote(enc_str)
            except Exception:
                continue
            src_m = re.search(r"src=['\"]([^'\"]+)['\"]", decoded_tag, re.I)
            if src_m:
                real_url = src_m.group(1).replace('&amp;', '&').strip()
                if self.isVideoFormat(real_url):
                    return real_url

        # 1b. ev.php 页的三参 strencode(data, key1, key2)（HD 分类的唯一地址来源）
        # 形态：document.write(strencode("<data>","<key1>","<key2>"))，
        # 参数是 base64 串且可能含 URL-safe 字符 - _，故引号内用 .*? 匹配。
        # 注意 strencode\( 不会误匹配 strencode2(（后者 '(' 前是 '2'）。
        for m in re.finditer(
                r'strencode\(\s*(["\'])(.*?)\1\s*,\s*(["\'])(.*?)\3\s*,\s*(["\'])(.*?)\5\s*\)',
                html, re.S):
            decoded = _strencode_decode(m.group(2), m.group(4), m.group(6))
            src_m = re.search(r"src=['\"]([^'\"]+)['\"]", decoded, re.I)
            if src_m and self.isVideoFormat(src_m.group(1)):
                return src_m.group(1).replace('&amp;', '&').strip()

        # 黑名单列表：过滤广告视频及相关域名
        ad_keywords = ['ad-i18n-dsp', 'kwai.net', 'googleads', 'popads', 'doubleclick',
                       'analytics', 'preview', 'cover', 'thumb', 'poster']

        # 2. 备用逻辑：直接正则寻找完整的视频播放 CDN 链接（含 HTML 注释里的备用源）
        all_urls = re.findall(r'https?://[^\s"\'<>()]+\.(?:mp4|m3u8)[^\s"\'<>]*', html, re.I)
        clean_urls = []
        for u in all_urls:
            u_clean = u.replace('&amp;', '&').strip()
            if any(ad in u_clean.lower() for ad in ad_keywords):
                continue
            clean_urls.append(u_clean)

        # 2a. 优先带签名/CDN 特征的链接（st=/secure=/token=/e=/get_file/mp43）
        for u_clean in clean_urls:
            low = u_clean.lower()
            if any(kw in low for kw in ['st=', 'secure=', 'token=', 'get_file', 'mp43']) or 'e=' in low:
                # 若页面能取到 VID，则要求链接归属本视频，避免误取相关视频地址
                if page_vid and page_vid not in u_clean:
                    continue
                return u_clean

        # 2b. 兜底：第一个非广告且归属本视频的链接
        for u_clean in clean_urls:
            if page_vid and page_vid in u_clean:
                return u_clean

        # 2c. 页面无 VID 信息时，取第一个非广告链接（旧行为兜底）
        if not page_vid and clean_urls:
            return clean_urls[0]

        return None

    def _extract_vid(self, text):
        # VID 新版含 - _（如 f2c1W4ycfwSCir1mtkuNR38yTD_m7Ylg59IMKjtCMuZGaJzjyg），
        # 旧版为纯数字；字符集统一放宽到 [a-zA-Z0-9_-]。
        patterns = [
            r'viewkey=([a-zA-Z0-9]+)',
            r'/viewvideo\.php\?.*viewkey=([a-zA-Z0-9]+)',
            r'VID["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_-]+)',
            r'/ev\.php\?VID=([a-zA-Z0-9_-]+)'
        ]
        for pattern in patterns:
            if m := re.search(pattern, text or ''):
                return m.group(1)
        return None

    def _get_ev_url(self, html, detail_url):
        # 首选 textarea 里站点官方给出的完整 ev.php 链接。
        # 注意：该链接的域名常是专用解析域（实测 91.9p9.xyz，只提供 ev.php），
        # 与主站域名不同，必须按原样抓取，不能替换成 self.host。
        if m := re.search(r'<textarea[^>]*>\s*(https?://[^<]+/ev\.php\?VID=[^<\s]+)', html, re.I):
            return m.group(1).strip()
        if matches := re.findall(r'(https?://[^"\'\s<>]+/ev\.php\?VID=[a-zA-Z0-9_-]+)', html, re.I):
            return matches[0]
        if vid := self._extract_vid(html) or self._extract_vid(detail_url):
            return f"{self.host}ev.php?VID={vid}"
        return None

    def detailContent(self, ids):
        if not ids or not ids[0]:
            return {'list': []}
        vod_id = ids[0].strip()
        detail_url = vod_id if vod_id.startswith('http') else f"{self.host.rstrip('/')}/{vod_id.lstrip('/')}"

        try:
            code, html = self._fetch(detail_url, referer=self.host)
        except Exception:
            return {'list': []}

        video_url = self._extract_video_url_from_html(html)

        # 兜底 1：ev.php 解析页。
        # 普通视频(view_video.php)详情页内嵌 strencode2 直链，上面已取到；
        # 高清分类(view_video_hd.php)详情页不含任何地址，唯一来源是 textarea 里
        # 站点官方给出的 ev.php 链接——VID 含 - _，且域名常为专用解析域
        #（实测 91.9p9.xyz，只部署 ev.php，主域访问该路径是 404），按原样抓取。
        if not video_url:
            ev_candidates = []
            ev_url = self._get_ev_url(html, detail_url)
            if ev_url:
                ev_candidates.append(ev_url)
            # textarea 链接缺失/失效时，用页面显式的 VID= 令牌在当前主域重构
            # （站点若在后续版本把 ev.php 部署到主域即生效；当前主域无此端点，
            # 404 页会被 _content_ok 挡掉，不影响结果）。
            # 只认 VID= 形态，避免误用相关视频的 viewkey 播错片。
            if vid_m := re.search(r'VID=([a-zA-Z0-9_-]+)', html):
                rebuilt = f"{self.host.rstrip('/')}/ev.php?VID={vid_m.group(1)}"
                if rebuilt not in ev_candidates:
                    ev_candidates.append(rebuilt)
            for cand in ev_candidates:
                try:
                    code, ev_html = self._fetch(cand, referer=self.host, timeout=10)
                    found = self._extract_video_url_from_html(ev_html)
                    if found:
                        video_url = found
                        break
                except Exception:
                    continue

        # 兜底 2：仍取不到则回传详情页地址，交由 TVBox/Hawk 网页解析（parse=1）
        if not video_url:
            video_url = detail_url

        # ── 元数据（正则提取，替代 pyquery）──────────────────────────
        title = '未知标题'
        t_m = re.search(r'<title>(.*?)</title>', html, re.I | re.S)
        if t_m:
            title = _clean_text(t_m.group(1)).split('- 91porn')[0].strip() or '未知标题'

        pic = ''
        p_m = (re.search(r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
               or re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']', html, re.I)
               or re.search(r'poster=["\']([^"\']+)["\']', html, re.I)
               or re.search(r'<img[^>]*class=["\'][^"\']*img-responsive[^"\']*["\'][^>]*src=["\']([^"\']+)["\']', html, re.I))
        if p_m:
            pic = self._abs_href(p_m.group(1))

        duration = '未知'
        if m_dur := re.search(r'\d{2}:\d{2}:\d{2}|\d{2}:\d{2}', html):
            duration = m_dur.group(0)

        views = '未知'
        if v_m := re.search(r'<span[^>]*class=["\']info["\'][^>]*>\s*(?:热度|观看)[^<]*</span>\s*([\d,]+)',
                            html, re.I):
            views = v_m.group(1)

        remarks = f"{duration} | 观看:{views}" if views != '未知' else duration

        return {'list': [{
            'vod_id': vod_id,
            'vod_name': title,
            'vod_pic': pic,
            'vod_play_from': '91Porn',
            'vod_play_url': f'高清${video_url}',
            'vod_director': '91',
            'vod_remarks': remarks,
            'vod_content': title
        }]}

    def searchContent(self, key, quick, pg=1):
        pg = int(pg or 1)
        if not key or not key.strip():
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 0, 'total': 0}
        try:
            encoded_key = urllib.parse.quote(key.strip())
            url = f"{self.host}search_result.php?search_id={encoded_key}&search_type=search_videos&min_duration=&page={pg}"

            code, html = self._fetch(url)
            vlist = self._parse_video_items(html)

            if not vlist:
                return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 0, 'total': 0}

            return {
                'list': vlist,
                'page': pg,
                'pagecount': self._parse_pagecount(html) or (pg + 1),
                'limit': len(vlist),
                'total': 999999
            }
        except Exception:
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 0, 'total': 0}

    def playerContent(self, flag, id, vipFlags):
        # 视频 CDN（如 la.btc620.com）校验 Referer，必须带站点来源；
        # 签名直链 st/e/f 约 1 小时有效，详情页每次拉取均为新签名。
        base = self.host.rstrip('/')
        headers = {
            'User-Agent': self._ua,
            'Referer': base + '/',
            'Origin': base
        }
        return {
            'parse': 0 if self.isVideoFormat(id) else 1,
            'url': id,
            'header': headers
        }

    def localProxy(self, param):
        return [404, 'text/plain', '']

    # ── 分类表（实例属性，供 homeContent 使用）───────────────────────
    @property
    def class_map(self):
        return {
            '最新': 'watch',
            '91原创': 'ori',
            '当前最热': 'hot',
            '本月最热': 'top',
            '10分钟以上': 'long',
            '20分钟以上': 'longer',
            '本月收藏': 'tf',
            '最近加精': 'rf',
            '高清': 'hd',
            '每月最热': 'top_m',
            '本月讨论': 'md',
            '收藏最多': 'mf'
        }
