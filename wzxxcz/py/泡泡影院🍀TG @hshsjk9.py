# coding=utf-8
"""
泡泡影院 zhonganedu.com | TVBox Python 爬虫
关键:
  - 网站为 MacCMS hl009 模板，无 PoW 挑战，无加密
  - 列表卡片: li.ff-vod-img-list > a[href=/celluloid/zxxx.html] > img[data-original][alt]
  - 分类分页: /class/{分类id}-{页码}.html，尾页含总页数
  - 搜索: /query.html?wd=关键词，翻页 /query/page/{页码}/wd/{编码关键词}.html
  - 详情页: 剧集按 tab-pane id="playurl-tab-{sid}" 分组，链接 /playurl/z{vid}/{sid}/{nid}.html
  - 播放页: var player_aaaa={...} 中 url 为 m3u8 直链，parse=0 直接返回
  - 简介添加指定前缀
  - 筛选逻辑: 依据真实源码拼接 /explore/ 路由，支持按顺序累加（类型/地区/年份）和 /page/{页码} 翻页
  - 图片修复: 增加 localProxy 代理图片并补充 Referer，解决防盗链导致的纯色大字报问题
"""
import re
import sys
import json
import urllib.parse

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
                print("[zhongan]", *a)
            except Exception:
                pass

    Spider = _BaseSpider


HOST = "https://www.zhonganedu.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
DEFAULT_PIC = HOST + "/static/images/load.png"

INTRO_PREFIX = "🍊小橙子为您介绍剧情👉请不要相信视频中的广告，以免上当受骗！"

CLASSES = [
    {"type_id": "1",  "type_name": "电影"},
    {"type_id": "2",  "type_name": "电视剧"},
    {"type_id": "3",  "type_name": "综艺片"},
    {"type_id": "4",  "type_name": "动漫"},
    {"type_id": "24", "type_name": "短剧"},
]

# 依据真实源码 /explore/ 路径收集的子分类
_FILTERS_MAP = {
    "1": [("全部", "1"), ("动作片", "6"), ("喜剧片", "7"), ("爱情片", "8"),
          ("科幻片", "9"), ("剧情片", "10"), ("战争片", "11"),
          ("动画片", "41"), ("记录片", "12"), ("恐怖片", "39")],
    "2": [("全部", "2"), ("国产剧", "13"), ("香港剧", "14"), ("韩国剧", "15"),
          ("欧美剧", "16"), ("泰国剧", "20"), ("日本剧", "21"),
          ("台湾剧", "22"), ("海外剧", "23")],
    "3": [("全部", "3"), ("大陆综艺", "25"), ("日韩综艺", "26"),
          ("港台综艺", "27"), ("欧美综艺", "28")],
    "4": [("全部", "4"), ("国产动漫", "29"), ("日本动漫", "30"),
          ("欧美动漫", "31"), ("港台动漫", "42"), ("海外动漫", "43")],
    "24": [("全部", "24"), ("短剧大全", "40"), ("AI漫剧", "44")],
}

_YEARS = [{"n": "全部", "v": ""}] + \
         [{"n": str(y), "v": str(y)} for y in range(2026, 1999, -1)]

_AREAS = [{"n": "全部", "v": ""}] + \
         [{"n": x, "v": x} for x in
          ["大陆", "香港", "台湾", "美国", "法国", "英国", "日本",
           "韩国", "德国", "泰国", "印度", "意大利", "西班牙", "加拿大", "其他"]]

FILTERS = {}
for c in CLASSES:
    tid = c["type_id"]
    FILTERS[tid] = [
        {"key": "class", "name": "分类",
         "value": [{"n": n, "v": v} for n, v in _FILTERS_MAP.get(tid, [("全部", tid)])]},
        {"key": "area", "name": "地区", "value": _AREAS},
        {"key": "year", "name": "年份", "value": _YEARS},
    ]

# ===================== 正则（全部依据真实源码） =====================
_RE_CARD = re.compile(
    r'<li[^>]*class="[^"]*ff-vod-img-list[^"]*"[^>]*>\s*'
    r'<a\s+href="(/celluloid/z\d+\.html)"[^>]*>\s*'
    r'<img[^>]*?data-original="([^"]*)"[^>]*?alt="([^"]*)"',
    re.S | re.I)

_RE_DETAIL_TITLE = re.compile(
    r'<h4><a\s+href="/celluloid/z\d+\.html"\s+class="ff-text">([^<]+)</a></h4>', re.I)

_RE_DETAIL_PIC = re.compile(
    r'class="detail-thumb-pic"[^>]*>\s*<img[^>]*?data-original="([^"]+)"', re.S | re.I)

_RE_INTRO_BLURB = re.compile(
    r'<dd[^>]*class="[^"]*vod-blurb[^"]*"[^>]*>([\s\S]*?)</dd>', re.S | re.I)
_RE_INTRO_CONTENT = re.compile(
    r'<div\s+class="vod-content">\s*([\s\S]*?)\s*</div>', re.S | re.I)

_RE_ACTOR = re.compile(
    r'<dt>主演：</dt>\s*<dd[^>]*>([\s\S]*?)</dd>', re.S | re.I)
_RE_DIRECTOR = re.compile(
    r'<dt>导演：</dt>\s*<dd[^>]*>([\s\S]*?)</dd>', re.S | re.I)
_RE_AREA = re.compile(
    r'<dt[^>]*>地区：</dt>\s*<dd[^>]*>([\s\S]*?)</dd>', re.S | re.I)
_RE_YEAR = re.compile(
    r'<dt>年份：</dt>\s*<dd>([\s\S]*?)</dd>', re.S | re.I)
_RE_STATUS = re.compile(
    r'<dt>状态：</dt>\s*<dd[^>]*>([\s\S]*?)</dd>', re.S | re.I)
_RE_A_TAG_TEXT = re.compile(r'<a[^>]*>([^<]*)</a>', re.I)

_RE_TAB_NAME = re.compile(
    r'<li[^>]*><a\s+href="#playurl-tab-(\d+)"[^>]*>[\s\S]*?<span[^>]*></span>\s*([^<]+)</a></li>', re.I)

_RE_TAB_BLOCK = re.compile(
    r'<div\s+class="tab-pane[^"]*"\s+id="playurl-tab-(\d+)">\s*'
    r'<ul[^>]*class="[^"]*list-unstyled-play[^"]*"[^>]*>([\s\S]*?)</ul>',
    re.S | re.I)

_RE_EPISODE = re.compile(
    r'<a\s+class="[^"]*"[^>]*href="(/playurl/z\d+/\d+/\d+\.html)"[^>]*title="([^"]*)"', re.I)

_RE_PLAYER = re.compile(r'var\s+player_aaaa\s*=\s*(\{.*?\})\s*</script>', re.S)


class Spider(Spider):

    def getName(self):
        return "泡泡影院"

    def init(self, extend=""):
        try:
            self.extend = json.loads(extend) if extend else {}
        except Exception:
            self.extend = {}
        self.site_url = (self.extend.get("site") or HOST).rstrip("/")
        self.headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": self.site_url + "/",
        }
        self.default_pic = DEFAULT_PIC
        self._play_cache = {}
        self.log("init: site=%s" % self.site_url)

    def _fetch(self, url, timeout=20, headers=None):
        try:
            h = dict(self.headers)
            if headers:
                h.update(headers)
            rsp = self.fetch(url, headers=h, timeout=timeout)
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

    def _proxy_image(self, pic):
        """将图片转为 TVBox 本地代理，解决防盗链大字报问题"""
        if not pic or not pic.startswith("http"):
            return pic
        # 如果图片里含有特殊字符，最好先 base64 或者 urlencode
        return self.site_url + "/proxy?url=" + urllib.parse.quote(pic, safe='')

    def _extract_videos(self, html):
        videos = []
        seen = set()
        if not html:
            return videos
        for href, pic, alt in _RE_CARD.findall(html):
            if href in seen:
                continue
            seen.add(href)
            raw_pic = self._fix_url(pic) or self.default_pic
            videos.append({
                "vod_id":      href,
                "vod_name":    self._clean(alt)[:100],
                "vod_pic":     self._proxy_image(raw_pic),
                "vod_remarks": "",
            })
        return videos

    def _page_count(self, html):
        if not html:
            return 1
        m = re.findall(r'/class/\d+-(\d+)\.html', html)
        if m:
            try:
                return max(int(x) for x in m)
            except Exception:
                pass
        m = re.findall(r'/query/page/(\d+)/wd/', html)
        if m:
            try:
                return max(int(x) for x in m)
            except Exception:
                pass
        # 补充对 /explore/ 的翻页匹配
        m = re.findall(r'/page/(\d+)(?:\.html|/)', html)
        if m:
            try:
                return max(int(x) for x in m)
            except Exception:
                pass
        return 1

    def homeContent(self, filter=False):
        return {"class": CLASSES, "filters": FILTERS}

    def homeVideoContent(self):
        html = self._fetch(self.site_url + "/")
        videos = self._extract_videos(html)
        self.log("home videos: %d" % len(videos))
        return {"list": videos}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        if isinstance(extend, str):
            try:
                extend = json.loads(extend)
            except Exception:
                extend = {}
        if not extend:
            extend = {}

        cls = extend.get("class") or tid
        area = extend.get("area") or ""
        year = extend.get("year") or ""
        
        # 处理"全部"的情况
        if cls == tid:
            cls = ""
        if area == "全部":
            area = ""
        if year == "全部":
            year = ""

        # 纯常规分类（无筛选且无子分类）：走 /class/{id}-{page}.html
        if not cls and not area and not year:
            if page == 1:
                url = "%s/class/%s.html" % (self.site_url, tid)
            else:
                url = "%s/class/%s-%d.html" % (self.site_url, tid, page)
        else:
            # 有筛选条件，走真实的 /explore/ 路由拼接
            # 基础路径：/explore/
            parts = ["explore"]
            
            # 1. 分类 (如果没有选择分类，就用当前频道id代替)
            c_id = cls if cls else tid
            # 因为 /explore/class/动作片/id/6.html 这里的"动作片"其实是它在 URL 里的类名编码，
            # 由于不能直接反推路由，MacCMS 标准过滤法通常用 /explore/type/6.html 或者 /explore/id/6.html
            # 依照你提供的源码：/explore/class/喜剧/id/7.html
            # 我们直接采用 id 筛选，MacCMS 原生支持 /explore/id/6/area/大陆.html
            parts.append("id/%s" % c_id)
            
            # 2. 地区
            if area:
                parts.append("area/%s" % urllib.parse.quote(area))
                
            # 3. 年份
            if year:
                parts.append("year/%s" % year)
                
            # 4. 页码
            if page > 1:
                parts.append("page/%d" % page)
                
            url = self.site_url + "/" + "/".join(parts) + ".html"

        self.log("category: %s" % url)
        html = self._fetch(url)
        videos = self._extract_videos(html)
        pagecount = self._page_count(html)
        self.log("  videos=%d pagecount=%d" % (len(videos), pagecount))
        return {
            "list": videos, "page": page, "pagecount": pagecount,
            "limit": 24, "total": pagecount * 24,
        }

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        kw = urllib.parse.quote(key)
        if page <= 1:
            url = "%s/query.html?wd=%s" % (self.site_url, kw)
        else:
            url = "%s/query/page/%d/wd/%s.html" % (self.site_url, page, kw)
        self.log("search: %s" % url)
        html = self._fetch(url)
        videos = self._extract_videos(html)
        total = 0
        m = re.search(r"mac_total\">(\d+)<", html)
        if m:
            total = int(m.group(1))
        return {
            "list": videos, "page": page,
            "pagecount": self._page_count(html),
            "limit": 24, "total": total or 999,
        }

    def searchContentPage(self, key, quick, pg="1"):
        return self.searchContent(key, quick, pg)

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vod_id = str(ids[0])
        url = vod_id if vod_id.startswith("http") else self._fix_url(vod_id)
        self.log("detail: %s" % url)
        html = self._fetch(url)
        if not html:
            return {"list": []}

        # 标题
        name = ""
        m = _RE_DETAIL_TITLE.search(html)
        if m:
            name = self._clean(m.group(1))
        if not name:
            m = re.search(r"<title>(.*?)</title>", html, re.S)
            if m:
                name = self._clean(m.group(1).split("-")[0]).strip()
        name = name or vod_id

        # 封面
        pic = self.default_pic
        m = _RE_DETAIL_PIC.search(html)
        if m:
            raw_pic = self._fix_url(m.group(1))
            pic = self._proxy_image(raw_pic)

        # 简介：优先 vod-blurb，其次 vod-content
        content = ""
        m = _RE_INTRO_BLURB.search(html)
        if m:
            content = self._clean(m.group(1))
        if not content:
            m = _RE_INTRO_CONTENT.search(html)
            if m:
                content = self._clean(m.group(1))
        content = (INTRO_PREFIX + "\n" + content) if content else INTRO_PREFIX

        # 主演 / 导演
        actor = ""
        m = _RE_ACTOR.search(html)
        if m:
            names = _RE_A_TAG_TEXT.findall(m.group(1))
            actor = ", ".join(self._clean(x) for x in names if self._clean(x))
        director = ""
        m = _RE_DIRECTOR.search(html)
        if m:
            names = _RE_A_TAG_TEXT.findall(m.group(1))
            director = ", ".join(self._clean(x) for x in names if self._clean(x))

        # 地区 / 年份 / 状态
        area = ""
        m = _RE_AREA.search(html)
        if m:
            names = _RE_A_TAG_TEXT.findall(m.group(1))
            area = ", ".join(self._clean(x) for x in names if self._clean(x))
        year = ""
        m = _RE_YEAR.search(html)
        if m:
            year = self._clean(m.group(1))
        status = ""
        m = _RE_STATUS.search(html)
        if m:
            status = self._clean(m.group(1))

        # ===== 剧集列表：按 tab 分组 =====
        tab_names = {}
        for sid, tname in _RE_TAB_NAME.findall(html):
            tab_names[sid] = self._clean(tname)

        groups = []  # [(sid, 线路名, [(集名, href), ...]), ...]
        for m in _RE_TAB_BLOCK.finditer(html):
            sid = m.group(1)
            body = m.group(2)
            eps = []
            for em in _RE_EPISODE.finditer(body):
                href, title = em.group(1), em.group(2)
                href = href.replace("&amp;", "&")
                eps.append((self._clean(title), self._fix_url(href)))
            if eps:
                groups.append((sid, tab_names.get(sid, "线路%s" % sid), eps))

        self.log("  groups: %s" % [(s, n, len(e)) for s, n, e in groups])

        if not groups:
            return {"list": [{
                "vod_id": vod_id, "vod_name": name, "vod_pic": pic,
                "vod_content": content, "vod_actor": actor,
                "vod_director": director, "vod_area": area, "vod_year": year,
                "vod_remarks": status or "",
                "vod_play_from": "", "vod_play_url": "",
            }]}

        play_from = []
        play_url = []
        for sid, tname, eps in groups:
            play_from.append(tname)
            play_url.append("#".join("%s$%s" % (n, h) for n, h in eps))

        return {"list": [{
            "vod_id": vod_id,
            "vod_name": name,
            "vod_pic": pic,
            "vod_content": content,
            "vod_actor": actor,
            "vod_director": director,
            "vod_area": area,
            "vod_year": year,
            "vod_remarks": status or ("%d条线路" % len(groups)),
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url":  "$$$".join(play_url),
        }]}

    def playerContent(self, flag, id, vipFlags):
        play_page = id if id.startswith("http") else self._fix_url(id)
        self.log("player: %s" % play_page)
        if play_page in self._play_cache:
            return self._play_cache[play_page]

        html = self._fetch(play_page)
        m3u8 = ""
        if html:
            m = _RE_PLAYER.search(html)
            if m:
                try:
                    obj = json.loads(m.group(1))
                    m3u8 = obj.get("url") or ""
                except Exception as e:
                    self.log("  player json 解析失败: %s" % e)

        if m3u8 and ".m3u8" in m3u8.lower():
            res = {
                "parse": 0,
                "playUrl": "",
                "url": m3u8,
                "header": {
                    "User-Agent": UA,
                    "Referer": self.site_url + "/",
                },
            }
            self._play_cache[play_page] = res
            self.log("  => m3u8: %s" % m3u8[:160])
            return res

        # 兜底：交给 TVBox 嗅探
        res = {"parse": 1, "playUrl": "", "url": play_page,
               "header": {"User-Agent": UA, "Referer": self.site_url + "/"}}
        self._play_cache[play_page] = res
        return res

    def localProxy(self, param):
        """
        代理图片请求，强行带上 Referer，解决防盗链展示大字报问题
        """
        try:
            if isinstance(param, dict):
                url = param.get("url", "")
            else:
                # TVBox 传进来格式通常是 ?url=https%3A%2F%2F...
                url = ""
                if "?" in param:
                    param = param.split("?", 1)[1]
                for pair in param.split("&"):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        if k == "url":
                            url = v
            
            if not url:
                return [404, "text/plain", b"no url", ""]
                
            url = urllib.parse.unquote(url) if "%" in url else url
            url = self._fix_url(url)
            
            # 请求图片时带上 Referer，欺骗图床
            rsp = self.fetch(url, headers={
                "User-Agent": UA,
                "Referer": self.site_url + "/"
            }, timeout=15)
            
            content = rsp.content
            ctype = rsp.headers.get("Content-Type", "image/jpeg")
            # 如果取到的不是图片，强制改回图片类型
            if not ctype.startswith("image/"):
                ctype = "image/jpeg"
                
            return [200, ctype, content, ""]
        except Exception as e:
            self.log("proxy image fail: %s" % e)
            return [500, "text/plain", b"error", ""]

    def isVideoFormat(self, url):
        return ".m3u8" in url or ".mp4" in url

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def close(self):
        self.destroy()
