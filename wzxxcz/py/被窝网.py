# coding=utf-8
"""
被窝网 beiwowang.com | TVBox Python 爬虫
MacCMS V10 + 如意播放器 (ruyi)
关键:
  - 列表卡片 div.grid-carditem, 图片取 img.lazyload[data-original]
  - 详情页只拿元数据, 集数列表需在播放页 /wa/{id}-{line}-{n}/ 抓
  - 播放: player_aaaa.url -> {如意CDN}/share/xxx -> var main = "/xxx.m3u8?sign=xxx"
  - 如意 CDN 域名不固定 (cdn.ryplay11.com / svip.ryiplay18.com 等), 从 share_url 动态取
  - var main 里的 \/ 必须还原成 /, 否则 CDN 会 403
  - master m3u8 内是 #EXT-X-STREAM-INF + 子 m3u8 相对路径,
    在 Python 侧拼好子 m3u8 绝对 URL (含 ?sign=) 再返回
  - 播放 header 的 Referer 用如意 CDN 的域名根 (参照豆花可用写法)
"""
import re
import sys
import json
import time
import urllib.parse
from urllib.parse import urlparse

sys.path.append('..')

try:
    from base.spider import Spider
except ImportError:
    import requests as _rq
    try:
        import urllib3
        urllib3.disable_warnings()
    except Exception:
        pass

    class _BaseSpider:
        def __init__(self):
            self._session = None

        @property
        def _sess(self):
            if self._session is None:
                self._session = _rq.Session()
                self._session.verify = False
                adapter = _rq.adapters.HTTPAdapter(
                    pool_connections=10, pool_maxsize=10, max_retries=0)
                self._session.mount('https://', adapter)
                self._session.mount('http://', adapter)
            return self._session

        def fetch(self, url, headers=None, **kw):
            timeout = kw.pop('timeout', 15)
            r = self._sess.get(url, headers=headers, timeout=timeout, **kw)
            r.encoding = 'utf-8'
            return r

        def log(self, *a, **kw):
            try:
                print("[beiwo]", *a)
            except Exception:
                pass

    Spider = _BaseSpider


HOST = "https://www.beiwowang.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
DEFAULT_PIC = HOST + "/template/default/images/logo.png"

# ===== 分类 =====
CLASSES = [
    {"type_id": "dianying",  "type_name": "电影"},
    {"type_id": "lianxuju",  "type_name": "电视剧"},
    {"type_id": "zongyi",    "type_name": "综艺"},
    {"type_id": "dongman",   "type_name": "动漫"},
    {"type_id": "duanju",    "type_name": "短剧"},
]

_SORTS = [
    {"n": "最新", "v": "time"},
    {"n": "人气", "v": "hits"},
    {"n": "评分", "v": "score"},
]
_YEARS = [{"n": "全部", "v": ""}] + \
         [{"n": str(y), "v": str(y)} for y in range(2026, 1999, -1)]
_AREAS = [
    {"n": "全部", "v": ""},
    {"n": "中国大陆", "v": "中国大陆"},
    {"n": "美国", "v": "美国"},
    {"n": "日本", "v": "日本"},
    {"n": "韩国", "v": "韩国"},
    {"n": "英国", "v": "英国"},
    {"n": "法国", "v": "法国"},
    {"n": "中国香港", "v": "中国香港"},
    {"n": "中国台湾", "v": "中国台湾"},
    {"n": "泰国", "v": "泰国"},
    {"n": "印度", "v": "印度"},
]

FILTERS = {}
for c in CLASSES:
    tid = c["type_id"]
    FILTERS[tid] = [
        {"key": "area", "name": "地区", "value": _AREAS},
        {"key": "year", "name": "年份", "value": _YEARS},
        {"key": "sort", "name": "排序", "value": _SORTS},
    ]

# ===== 正则 =====
_RE_CARD = re.compile(
    r'<div[^>]*class="[^"]*grid-carditem[^"]*"[^>]*>([\s\S]*?)</div>\s*</div>',
    re.I)
_RE_A_LINK = re.compile(
    r'<a[^>]*class="[^"]*link[^"]*"[^>]*href="([^"]+)"[^>]*title="([^"]*)"',
    re.I)
_RE_A_LINK2 = re.compile(
    r'<a[^>]*href="([^"]+)"[^>]*class="[^"]*link[^"]*"[^>]*title="([^"]*)"',
    re.I)
_RE_IMG_LAZY = re.compile(
    r'<img[^>]*class="[^"]*lazyload[^"]*"[^>]*data-original="([^"]+)"',
    re.I)
_RE_TAG1 = re.compile(
    r'<div[^>]*class="[^"]*tag1[^"]*"[^>]*>([\s\S]*?)</div>', re.I)
_RE_TAG2 = re.compile(
    r'<p[^>]*class="[^"]*tag2[^"]*"[^>]*>([\s\S]*?)</p>', re.I)
_RE_H3 = re.compile(r'<h3[^>]*>([\s\S]*?)</h3>', re.I)

# 详情页
_RE_DETAIL_TITLE = re.compile(r'<h1[^>]*>([\s\S]*?)</h1>', re.I)
_RE_DETAIL_PIC = re.compile(
    r'<img[^>]*class="[^"]*lazyload[^"]*"[^>]*data-original="([^"]+)"', re.I)
_RE_DETAIL_PIC2 = re.compile(
    r'<img[^>]*data-original="([^"]+)"[^>]*class="[^"]*lazyload[^"]*"', re.I)
_RE_DETAIL_DESC = re.compile(
    r'<div[^>]*class="[^"]*(?:desc|content|detail-content|vod_content)[^"]*"'
    r'[^>]*>([\s\S]*?)</div>', re.I)
_RE_META_DESC = re.compile(
    r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)["\']', re.I)
_RE_DETAIL_DIR = re.compile(
    r'(?:导演|导演:)\s*[:：]?\s*</?[^>]*>?\s*([^<\n]+)', re.I)
_RE_DETAIL_ACT = re.compile(
    r'(?:主演|演员)\s*[:：]?\s*</?[^>]*>?\s*([^<\n]+)', re.I)
_RE_DETAIL_YEAR = re.compile(r'(\d{4})\s*年?')
_RE_DETAIL_AREA = re.compile(
    r'<span[^>]*>(中国大陆|美国|日本|韩国|英国|法国|中国香港|中国台湾|泰国|印度|'
    r'香港|台湾|加拿大|德国|意大利|西班牙|澳大利亚|俄罗斯|其他)</span>', re.I)
_RE_DETAIL_REMARK = re.compile(
    r'<span[^>]*class="[^"]*(?:remarks|note|state)[^"]*"[^>]*>([\s\S]*?)</span>', re.I)

# 播放页: player_aaaa 结尾可能是 ";" 或 "</script>", 都要兼容
_RE_PLAYER_AAAA = re.compile(
    r'var\s+player_aaaa\s*=\s*(\{[\s\S]*?\})\s*(?:;|</script>|$)', re.I)
_RE_EP_A = re.compile(
    r'<a\s+href="([^"]+/wa/[^"]+)"([^>]*)>([\s\S]*?)</a>', re.I)
_RE_EP_TITLE = re.compile(r'title="([^"]*)"', re.I)

# 中转页
_RE_MAIN = re.compile(r'var\s+main\s*=\s*"([^"]+)"', re.I)


class Spider(Spider):

    def getName(self):
        return "被窝网"

    def init(self, extend=""):
        try:
            self.extend = json.loads(extend) if extend else {}
        except Exception:
            self.extend = {}
        self.site_url = (self.extend.get("site") or HOST).rstrip("/")
        self.headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                      "image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": self.site_url + "/",
        }
        self.default_pic = DEFAULT_PIC
        self._play_cache = {}
        self.log("init: site=%s" % self.site_url)

    # ---------- 基础 ----------
    def _fetch(self, url, timeout=20, headers=None, allow_redirects=True):
        try:
            h = dict(self.headers)
            if headers:
                h.update(headers)
            rsp = self.fetch(url, headers=h, timeout=timeout,
                             allow_redirects=allow_redirects)
            if hasattr(rsp, "text"):
                return rsp.text or ""
            if hasattr(rsp, "content"):
                return rsp.content.decode("utf-8", "ignore")
            return str(rsp)
        except Exception as e:
            self.log("fetch FAIL %s -> %s" % (url, e))
            return ""

    def _fix_url(self, url):
        if not url:
            return ""
        url = url.strip()
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("http"):
            return url
        if url.startswith("/"):
            return self.site_url + url
        return urllib.parse.urljoin(self.site_url + "/", url)

    def _clean(self, s):
        if not s:
            return ""
        s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
        s = re.sub(r"<[^>]+>", "", s)
        s = (s.replace("&nbsp;", " ").replace("\xa0", " ")
              .replace("&amp;", "&").replace("&quot;", '"')
              .replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">"))
        s = re.sub(r"[ \t\r\f\v]+", " ", s)
        s = re.sub(r"\n{2,}", "\n", s)
        return s.strip()

    # ---------- 列表解析 ----------
    def _extract_videos(self, html):
        videos = []
        seen = set()
        if not html:
            return videos

        blocks = _RE_CARD.findall(html)
        if not blocks:
            blocks = re.findall(
                r'<div[^>]*class="[^"]*grid-carditem[^"]*"[^>]*>([\s\S]*?)'
                r'(?=<div[^>]*class="[^"]*grid-carditem|</section|</main)',
                html, re.I)

        self.log("  卡片块: %d" % len(blocks))

        for blk in blocks:
            m = _RE_A_LINK.search(blk) or _RE_A_LINK2.search(blk)
            href, title = ("", "")
            if m:
                href, title = m.group(1), m.group(2)
            if not href:
                continue
            if href in seen:
                continue
            seen.add(href)

            pic = ""
            mp = _RE_IMG_LAZY.search(blk)
            if mp:
                pic = mp.group(1)

            tag1 = ""
            mt = _RE_TAG1.search(blk)
            if mt:
                tag1 = self._clean(mt.group(1))

            tag2 = ""
            mt2 = _RE_TAG2.search(blk)
            if mt2:
                tag2 = self._clean(mt2.group(1))

            if not title:
                mh = _RE_H3.search(blk)
                if mh:
                    title = self._clean(mh.group(1))

            videos.append({
                "vod_id":      href,
                "vod_name":    title or href,
                "vod_pic":     self._fix_url(pic) or self.default_pic,
                "vod_remarks": tag1,
                "vod_year":    tag2,
            })
        return videos

    def _page_count(self, html):
        if not html:
            return 1
        pages = re.findall(r'[?&/]page[/=](\d+)', html)
        if pages:
            try:
                return max(int(p) for p in pages)
            except Exception:
                pass
        m = re.findall(r'<a[^>]*href="[^"]*?(\d+)[^"]*?"[^>]*>\s*\d+\s*</a>', html)
        if m:
            try:
                return max(int(x) for x in m)
            except Exception:
                pass
        return 1

    # ---------- TVBox 接口 ----------
    def homeContent(self, filter=False):
        return {"class": CLASSES, "filters": FILTERS}

    def homeVideoContent(self):
        html = self._fetch(self.site_url + "/")
        self.log("home HTML 长度: %d" % len(html))
        return {"list": self._extract_videos(html)}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        if isinstance(extend, str):
            try:
                extend = json.loads(extend)
            except Exception:
                extend = {}
        if not extend:
            extend = {}
        for k in list(extend.keys()):
            if extend[k] in ("", None, "全部"):
                del extend[k]

        area = extend.get("area", "")
        year = extend.get("year", "")
        sort = extend.get("sort", "time")

        path = "%s--------%d---/" % (tid, page)
        url = "%s/vodshow/%s" % (self.site_url, path)
        params = {}
        if area:
            params["area"] = area
        if year:
            params["year"] = year
        if sort and sort != "time":
            params["order"] = sort
        if params:
            url += "?" + urllib.parse.urlencode(params)

        self.log("category: %s" % url)
        html = self._fetch(url)
        self.log("  HTML 长度: %d" % len(html))
        videos = self._extract_videos(html)
        pagecount = self._page_count(html)
        self.log("  结果: %d 条, 页数: %d" % (len(videos), pagecount))
        return {
            "list": videos, "page": page, "pagecount": pagecount,
            "limit": 24, "total": pagecount * 24,
        }

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        url = "%s/vodsearch/-------------/?wd=%s&page=%d" % (
            self.site_url, urllib.parse.quote(key), page)
        self.log("search: %s" % url)
        html = self._fetch(url)
        self.log("  HTML 长度: %d" % len(html))
        return {
            "list": self._extract_videos(html),
            "page": page,
            "pagecount": self._page_count(html),
            "limit": 24, "total": 999,
        }

    def searchContentPage(self, key, quick, pg="1"):
        return self.searchContent(key, quick, pg)

    # ---------- 详情 ----------
    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vod_id = str(ids[0])
        url = vod_id if vod_id.startswith("http") else self._fix_url(vod_id)
        self.log("detail: %s" % url)
        html = self._fetch(url)
        self.log("  HTML 长度: %d" % len(html))
        if not html:
            return {"list": []}

        name = ""
        m = _RE_DETAIL_TITLE.search(html)
        if m:
            name = self._clean(m.group(1))
        if not name:
            m = re.search(r"<title>(.*?)</title>", html, re.S)
            if m:
                name = self._clean(m.group(1).split("_")[0].split("-")[0])
        name = re.sub(r"\s*\(\d{4}\)\s*$", "", name).strip() or vod_id

        pic = self.default_pic
        mp = _RE_DETAIL_PIC.search(html) or _RE_DETAIL_PIC2.search(html)
        if mp:
            pic = self._fix_url(mp.group(1))

        content = ""
        m = _RE_DETAIL_DESC.search(html)
        if m:
            content = self._clean(m.group(1))
        if not content:
            m = _RE_META_DESC.search(html)
            if m:
                content = self._clean(m.group(1))

        director = ""
        m = _RE_DETAIL_DIR.search(html)
        if m:
            director = self._clean(m.group(1))

        actor = ""
        m = _RE_DETAIL_ACT.search(html)
        if m:
            actor = self._clean(m.group(1))

        year = ""
        m = _RE_DETAIL_YEAR.search(html)
        if m:
            year = m.group(1)

        area = ""
        m = _RE_DETAIL_AREA.search(html)
        if m:
            area = self._clean(m.group(1))

        remarks = ""
        m = _RE_DETAIL_REMARK.search(html)
        if m:
            remarks = self._clean(m.group(1))

        play_url = ""
        mp = re.search(r'href="([^"]*/wa/[^"]+)"', html, re.I)
        if mp:
            play_url = self._fix_url(mp.group(1))

        play_from = []
        play_urls = []

        if play_url:
            ph = self._fetch(play_url)
            eps = self._extract_episodes_from_play(ph, play_url)
            if eps:
                play_from.append("如意")
                play_urls.append("#".join(eps))

        if not play_from:
            return {"list": []}

        return {"list": [{
            "vod_id":       vod_id,
            "vod_name":     name,
            "vod_pic":      pic,
            "vod_content":  content,
            "vod_actor":    actor,
            "vod_director": director,
            "vod_year":     year,
            "vod_area":     area,
            "vod_remarks":  remarks or ("%d集" % len(play_urls[0].split("#"))),
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url":  "$$$".join(play_urls),
        }]}

    def _extract_episodes_from_play(self, html, base_url):
        if not html:
            return []
        eps = []
        seen = set()
        for m in _RE_EP_A.finditer(html):
            href = m.group(1)
            attrs = m.group(2)
            inner = m.group(3)
            if not href:
                continue
            if not re.search(r"/wa/[^/]+-\d+-\d+/?$", href):
                continue
            full = self._fix_url(href)
            if full in seen:
                continue
            seen.add(full)

            ep_name = ""
            mt = _RE_EP_TITLE.search(attrs)
            if mt:
                ep_name = self._clean(mt.group(1))
            if not ep_name:
                ep_name = self._clean(inner)
            if not ep_name:
                mm = re.search(r"-(\d+)/?$", href)
                ep_name = "第%s集" % (mm.group(1) if mm else len(eps) + 1)

            eps.append("%s$%s" % (ep_name, full))

        def _key(item):
            u = item.split("$", 1)[-1]
            mm = re.search(r"-(\d+)/?$", u)
            return int(mm.group(1)) if mm else 0
        eps.sort(key=_key)
        self.log("  剧集: %d" % len(eps))
        return eps

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags):
        play_page = id if id.startswith("http") else self._fix_url(id)
        self.log("player: %s" % play_page)

        now = int(time.time())
        if play_page in self._play_cache:
            ts, res = self._play_cache[play_page]
            if now - ts < 300:
                return res

        html = self._fetch(play_page)
        share_url = self._extract_share_url(html)
        self.log("  share_url: %s" % share_url)

        if not share_url:
            res = {"parse": 1, "playUrl": "", "url": play_page,
                   "header": {"User-Agent": UA, "Referer": self.site_url + "/"}}
            self._play_cache[play_page] = (now, res)
            return res

        real = self._resolve_m3u8(share_url)
        if real:
            # 参照豆花可用写法: Referer 用如意 CDN 的域名根, 不用完整 share 页
            pu = urlparse(share_url)
            ry_root = "%s://%s/" % (pu.scheme, pu.netloc)
            res = {
                "parse": 0,
                "playUrl": "",
                "url": real,
                "header": {
                    "User-Agent": UA,
                    "Referer": ry_root,
                },
            }
            self._play_cache[play_page] = (now, res)
            self.log("  => m3u8: %s" % real[:160])
            self.log("  => Referer: %s" % ry_root)
            return res

        res = {"parse": 1, "playUrl": "", "url": play_page,
               "header": {"User-Agent": UA, "Referer": self.site_url + "/"}}
        self._play_cache[play_page] = (now, res)
        return res

    def _extract_share_url(self, html):
        if not html:
            return ""
        m = _RE_PLAYER_AAAA.search(html)
        if not m:
            m2 = re.search(r'"url"\s*:\s*"([^"]+)"', html)
            if m2:
                return m2.group(1).replace("\\/", "/")
            return ""
        raw = m.group(1)
        try:
            data = json.loads(raw)
            u = data.get("url", "")
            return u.replace("\\/", "/")
        except Exception:
            m2 = re.search(r'"url"\s*:\s*"([^"]+)"', raw)
            if m2:
                return m2.group(1).replace("\\/", "/")
        return ""

    def _resolve_m3u8(self, share_url):
        pu = urlparse(share_url)
        base_ry = "%s://%s" % (pu.scheme, pu.netloc)

        html = self._fetch(share_url, headers={
            "User-Agent": UA,
            "Referer": base_ry + "/",
            "Accept": "text/html,application/xhtml+xml,*/*",
        })
        if not html:
            self.log("  share 页为空")
            return ""

        m = _RE_MAIN.search(html)
        if not m:
            self.log("  share 页未找到 var main")
            return ""

        main_path = m.group(1).replace("\\/", "/")

        if main_path.startswith("http"):
            master_url = main_path
        elif main_path.startswith("/"):
            master_url = base_ry + main_path
        else:
            master_url = base_ry + "/" + main_path
        self.log("  master: %s" % master_url[:160])

        master = self._fetch(master_url, headers={
            "User-Agent": UA,
            "Referer": share_url,
            "Accept": "*/*",
        })
        if not master or "#EXTM3U" not in master:
            self.log("  master 非 m3u8, 直接返回 master_url")
            return master_url

        lines = [ln.strip() for ln in master.split("\n") if ln.strip()]
        for i, ln in enumerate(lines):
            if ln.startswith("#EXT-X-STREAM-INF"):
                if i + 1 < len(lines):
                    sub = lines[i + 1].strip()
                    if sub.startswith("http"):
                        sub_full = sub
                    elif sub.startswith("/"):
                        sub_full = base_ry + sub
                    else:
                        sub_full = urllib.parse.urljoin(master_url, sub)
                        if "?sign=" in master_url and "?sign=" not in sub_full:
                            q = master_url.split("?", 1)[1]
                            sub_full = sub_full + "?" + q
                    self.log("  子 m3u8: %s" % sub_full[:160])
                    return sub_full

        self.log("  master 里无 #EXT-X-STREAM-INF, 返回 master")
        return master_url

    # ---------- 其他 ----------
    def localProxy(self, param):
        try:
            url = ""
            if isinstance(param, dict):
                url = param.get("url", "")
            else:
                for pair in str(param).split("&"):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        if k == "url":
                            url = v
            if not url:
                return [200, "image/jpeg", b"", ""]
            url = urllib.parse.unquote(url) if "%" in url else url
            url = self._fix_url(url)
            rsp = self.fetch(url, headers={
                "User-Agent": UA, "Referer": self.site_url + "/"}, timeout=15)
            content = rsp.content
            ctype = rsp.headers.get("Content-Type", "image/jpeg")
            if not ctype.startswith("image/"):
                ctype = "image/jpeg"
            return [200, ctype, content, ""]
        except Exception:
            return [200, "image/jpeg", b"", ""]

    def isVideoFormat(self, url):
        return ".m3u8" in url or ".mp4" in url or url.startswith("http")

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def close(self):
        self.destroy()
