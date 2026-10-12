# coding=utf-8
"""
晴天影视 gsjsylgs.com | TVBox Python 爬虫 (纯净简介版)
- 删除了简介里拼接的元数据（分类、地区等），只保留剧情正文
- 简介开头加上指定的“小橙子”前缀
- 保留：更新卡片过滤逻辑 (未动)
- 保留：标题过滤“详细介绍” (未动)
- 保留：正确的简介提取逻辑 (未动)
"""
import re
import sys
import json
import time
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
                ad = _rq.adapters.HTTPAdapter(
                    pool_connections=10, pool_maxsize=10, max_retries=0)
                self._session.mount('https://', ad)
                self._session.mount('http://', ad)
            return self._session

        def fetch(self, url, headers=None, **kw):
            timeout = kw.pop('timeout', 15)
            r = self._sess.get(url, headers=headers, timeout=timeout, **kw)
            r.encoding = 'utf-8'
            return r

        def log(self, *a, **kw):
            try:
                print("[qingtian]", *a)
            except Exception:
                pass

    Spider = _BaseSpider

HOST = "https://www.gsjsylgs.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

INTRO_PREFIX = "🍊小橙子为您介绍剧情👉请不要相信视频中的广告，以免上当受骗！"

_CLASSES_TID = [
    ("1",  "电影"),
    ("2",  "电视剧"),
    ("3",  "综艺"),
    ("4",  "动漫"),
    ("44", "短剧"),
]

_FILTERS_MAP = {
    "1":  ["全部", "动作片", "爱情片", "科幻片", "恐怖片", "战争片", "喜剧片",
           "纪录片", "剧情片", "悬疑片", "犯罪片", "奇幻片", "动画片", "原创电影"],
    "2":  ["全部", "大陆剧", "港台剧", "欧美剧", "韩国剧", "日本剧", "泰国剧", "海外剧"],
    "3":  ["全部", "内地综艺", "港台综艺", "日韩综艺", "欧美综艺"],
    "4":  ["全部", "国产动漫", "日韩动漫", "欧美动漫"],
    "44": ["全部", "脑洞短剧", "爱情短剧", "逆袭短剧", "都市短剧", "穿越短剧", "古装短剧"],
}

_YEARS = [{"n": "全部", "v": ""}] + \
         [{"n": str(y), "v": str(y)} for y in range(2026, 1999, -1)]
_AREAS = [
    {"n": "全部", "v": ""}, {"n": "中国大陆", "v": "中国大陆"},
    {"n": "美国", "v": "美国"}, {"n": "日本", "v": "日本"},
    {"n": "韩国", "v": "韩国"}, {"n": "中国香港", "v": "中国香港"},
    {"n": "中国台湾", "v": "中国台湾"}, {"n": "英国", "v": "英国"},
    {"n": "法国", "v": "法国"}, {"n": "泰国", "v": "泰国"},
]

FILTERS = {}
for _tid, _ in _CLASSES_TID:
    FILTERS[_tid] = [
        {"key": "class", "name": "类型",
         "value": [{"n": x, "v": "" if x == "全部" else x}
                   for x in _FILTERS_MAP.get(_tid, ["全部"])]},
        {"key": "area", "name": "地区", "value": _AREAS},
        {"key": "year", "name": "年份", "value": _YEARS},
    ]

# ========== 正则 ==========
_RE_LI = re.compile(r'<li[^>]*>([\s\S]*?)</li>', re.I)
_RE_LINK = re.compile(r'<a[^>]*?href="(/[A-Za-z0-9]{4,16}/\d+\.html)"[^>]*?>', re.I)
_RE_TITLE_ATTR = re.compile(r'title="([^"]*)"', re.I)
_RE_DATA_ORIG = re.compile(r'data-original="([^"]*)"', re.I)
_RE_BG_IMG = re.compile(r"background-image:\s*url\((['\"]?)([^)'\"]+)\1\)", re.I)
_RE_NAME_DIV = re.compile(r'<div\s+class="name[^"]*"[^>]*>([^<]+)</div>', re.I)
_RE_STATUS = re.compile(r'<p\s+class="item-status[^"]*"[^>]*>([^<]*)</p>', re.I)

_RE_NAV_CAT = re.compile(
    r'<a[^>]*?class="[^"]*swiper-slide[^"]*"[^>]*?href="(/[A-Za-z0-9]+/\d+\.html)"[^>]*>([^<]+)</a>',
    re.I)
_RE_SEARCH_FORM = re.compile(
    r'<form[^>]*?class="[^"]*search[^"]*"[^>]*?action="(/[A-Za-z0-9]+/-+\.html)"',
    re.I)

_RE_TITLE_LINK = re.compile(
    r'<h3[^>]*>\s*<a[^>]*?href="/[A-Za-z0-9]+/\d+\.html"[^>]*>([\s\S]*?)</a>', re.I)

_RE_PIC = re.compile(
    r'<div\s+class="pic[^"]*"[^>]*>\s*'
    r'<img[^>]*?(?:data-original|src)="([^"]*)"', re.I)
_RE_META_DESC = re.compile(
    r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)["\']', re.I)

_RE_INTRO_BLOCK = re.compile(
    r'<h2[^>]*>\s*剧情简介\s*</h2>[\s\S]*?<p[^>]*?>([\s\S]*?)</p>', re.I)

# 元数据正则（保留正则，但不塞进简介里了）
_RE_META_CLASS = re.compile(r'分类：([\s\S]*?)</span>', re.I)
_RE_META_AREA = re.compile(r'地区：<a[^>]*>([^<]+)</a>', re.I)
_RE_META_YEAR = re.compile(r'年份：<a[^>]*>([^<]+)</a>', re.I)
_RE_META_DIRECTOR = re.compile(r'导演：([\s\S]*?)</span>', re.I)
_RE_META_ACTOR = re.compile(r'主演：([\s\S]*?)</span>', re.I)
_RE_META_REMARKS = re.compile(r'状态：([^<]+)', re.I)

_RE_TAB = re.compile(
    r'<li[^>]*class="[^"]*ewave-tab[^"]*"[^>]*?data-target="#(ewave-playlist-\d+)"'
    r'[^>]*>([^<]+)<', re.I)
_RE_PLAYLIST = re.compile(
    r'<ul[^>]*id="(ewave-playlist-\d+)"[^>]*>([\s\S]*?)</ul>', re.I)
_RE_EP = re.compile(
    r'<a[^>]*href="(/[A-Za-z0-9]+/\d+-\d+-\d+\.html)"[^>]*>([^<]+)</a>', re.I)

_RE_PLAYER = re.compile(r'var\s+player_aaaa\s*=\s*(\{[\s\S]*?\});', re.S)


class Spider(Spider):

    def getName(self):
        return "晴天影视"

    def init(self, extend=""):
        try:
            self.extend = json.loads(extend) if extend else {}
        except Exception:
            self.extend = {}
        self.site_url = (self.extend.get("site") or HOST).rstrip("/")
        self.headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": self.site_url + "/",
        }
        self._prefix_cat = ""
        self._prefix_search = ""
        self._warmed = False
        self._play_cache = {}

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

    def _warm_up(self):
        if self._warmed:
            return
        html = self._fetch(self.site_url + "/")
        if html:
            m = _RE_NAV_CAT.search(html)
            if m:
                m2 = re.match(r'/([A-Za-z0-9]+)/\d+\.html', m.group(1))
                if m2:
                    self._prefix_cat = m2.group(1)
            m = _RE_SEARCH_FORM.search(html)
            if m:
                m2 = re.match(r'/([A-Za-z0-9]+)/', m.group(1))
                if m2:
                    self._prefix_search = m2.group(1)
        if not self._prefix_cat:
            self._prefix_cat = "xphjTV7"
        if not self._prefix_search:
            self._prefix_search = "oLKx9cg"
        self._warmed = True
        self.log("warm_up: cat=%s search=%s" % (self._prefix_cat, self._prefix_search))

    def _parse_videos(self, html):
        videos = []
        seen = set()
        if not html:
            return videos
        for li_m in _RE_LI.finditer(html):
            block = li_m.group(1)
            link_m = _RE_LINK.search(block)
            if not link_m:
                continue
            href = link_m.group(1).replace("&amp;", "&")
            
            # 【保留】忽略导航栏的“更新”、“排行榜”、“留言”等链接，坚决不删
            if any(x in href for x in ["/label/", "/gbook", "/artsearch/"]):
                continue
                
            if href in seen:
                continue
            
            pic = ""
            pm = _RE_DATA_ORIG.search(block)
            if pm:
                pic = pm.group(1)
            else:
                bm = _RE_BG_IMG.search(block)
                if bm:
                    pic = bm.group(2)
            if not pic:
                continue
                
            name = ""
            tm = _RE_TITLE_ATTR.search(block)
            if tm:
                name = tm.group(1)
            if not name:
                nm = _RE_NAME_DIV.search(block)
                if nm:
                    name = nm.group(1).strip()
                    
            # 【保留】过滤名叫“更新”、“排行榜”的卡片
            if name in ("更新", "排行榜", "留言", "首页"):
                continue

            remarks = ""
            sm = _RE_STATUS.search(block)
            if sm:
                remarks = sm.group(1).strip()

            seen.add(href)
            videos.append({
                "vod_id":      href,
                "vod_name":    self._clean(name) or href,
                "vod_pic":     self._fix_url(pic),
                "vod_remarks": remarks,
            })
        return videos

    # ========== TVBox 接口 ==========
    def homeContent(self, filter=False):
        self._warm_up()
        classes = [{"type_id": tid, "type_name": name} for tid, name in _CLASSES_TID]
        return {"class": classes, "filters": FILTERS}

    def homeVideoContent(self):
        self._warm_up()
        html = self._fetch(self.site_url + "/")
        return {"list": self._parse_videos(html)}

    def categoryContent(self, tid, pg, filter, extend):
        self._warm_up()
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

        base = "%s/%s/%s.html" % (self.site_url, self._prefix_cat, tid)
        params = {}
        if page > 1:
            params["page"] = page
        if extend.get("class"):
            params["class"] = extend["class"]
        if extend.get("area"):
            params["area"] = extend["area"]
        if extend.get("year"):
            params["year"] = extend["year"]
        if params:
            base += "?" + urllib.parse.urlencode(params)

        self.log("category: %s" % base)
        html = self._fetch(base)
        videos = self._parse_videos(html)
        self.log("  videos: %d" % len(videos))
        return {
            "list": videos, "page": page,
            "pagecount": 9999, "limit": 20, "total": 9999,
        }

    def searchContent(self, key, quick, pg="1"):
        self._warm_up()
        page = int(pg) if pg else 1
        kw = urllib.parse.quote(key)
        url = "%s/%s/-------------.html?wd=%s" % (
            self.site_url, self._prefix_search, kw)
        if page > 1:
            url += "&page=%d" % page
        self.log("search: %s" % url)
        html = self._fetch(url)
        videos = self._parse_videos(html)
        self.log("  videos: %d" % len(videos))
        return {
            "list": videos, "page": page,
            "pagecount": 9999, "limit": 20, "total": 9999,
        }

    def searchContentPage(self, key, quick, pg="1"):
        return self.searchContent(key, quick, pg)

    # ========== 详情页 ==========
    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vod_id = str(ids[0])
        url = vod_id if vod_id.startswith("http") else self._fix_url(vod_id)
        self.log("detail: %s" % url)
        html = self._fetch(url)
        if not html:
            return {"list": []}

        # 1. 标题提取
        name = ""
        m = _RE_TITLE_LINK.search(html)
        if m:
            name = self._clean(m.group(1))
        if not name:
            m = re.search(r"<title>(.*?)</title>", html, re.S)
            if m:
                t = m.group(1)
                t = re.sub(r"\s*[-|_]\s*晴天影视.*$", "", t)
                t = re.sub(r"^[^-|_]*[-|_]", "", t)
                name = self._clean(t)
                
        # 【保留】强制去掉“详细介绍”和“详细内容”四个字
        name = name.replace("详细介绍", "").replace("详细内容", "")
        name = re.sub(r"\s*\(\d{4}\)\s*$", "", name).strip() or vod_id

        # 2. 封面
        pic = ""
        m = _RE_PIC.search(html)
        if m:
            pic = self._fix_url(m.group(1))

        # 3. 简介 (原有正确逻辑，未动)
        content = ""
        intro_m = _RE_INTRO_BLOCK.search(html)
        if intro_m:
            content = self._clean(intro_m.group(1))
            content = re.sub(r'[ \t]+', ' ', content)
            content = re.sub(r'\n\s*\n', '\n', content).strip()
        if not content:
            m = _RE_META_DESC.search(html)
            if m:
                content = self._clean(m.group(1))

        # 【核心修改】直接在简介前面加上指定的前缀
        if content:
            content = INTRO_PREFIX + "\n" + content
        else:
            content = INTRO_PREFIX

        # 4. 提取元数据 (保留字段给TVBox，但绝对不拼进简介里)
        actor = ""
        director = ""
        year = ""
        area = ""
        remarks = ""
        try:
            m = _RE_META_AREA.search(html)
            if m: area = m.group(1).strip()
            m = _RE_META_YEAR.search(html)
            if m: year = m.group(1).strip()
            m = _RE_META_DIRECTOR.search(html)
            if m: director = "".join(re.findall(r'>([^<]+)<', m.group(1))) or m.group(1).strip()
            m = _RE_META_ACTOR.search(html)
            if m: actor = ",".join(re.findall(r'>([^<]+)<', m.group(1)))
            m = _RE_META_REMARKS.search(html)
            if m: remarks = m.group(1).strip()
        except Exception as e:
            self.log("  meta parse fail: %s" % e)

        # 5. 剧集列表
        tabs = _RE_TAB.findall(html)
        playlists = dict(_RE_PLAYLIST.findall(html))
        self.log("  tabs=%d playlists=%d" % (len(tabs), len(playlists)))

        play_from = []
        play_url = []
        for ul_id, tab_name in tabs:
            block = playlists.get(ul_id, "")
            eps = _RE_EP.findall(block)
            if not eps:
                continue
            line_name = self._clean(tab_name).strip()
            ep_list = []
            for ep_href, ep_name in eps:
                ep_list.append("%s$%s" % (
                    self._clean(ep_name), self._fix_url(ep_href)))
            play_from.append(line_name)
            play_url.append("#".join(ep_list))

        if not play_from:
            return {"list": []}

        return {"list": [{
            "vod_id":         vod_id,
            "vod_name":       name,
            "vod_pic":        pic,
            "vod_content":    content,     # 只有前缀 + 纯净简介
            "vod_actor":      actor,       # TVBox 标准字段（若TVBox UI自带展示则展示，爬虫不拼进去）
            "vod_director":   director,
            "vod_year":       year,
            "vod_area":       area,
            "vod_remarks":    remarks,
            "vod_play_from":  "$$$".join(play_from),
            "vod_play_url":   "$$$".join(play_url),
        }]}

    # ========== 播放页 ==========
    def playerContent(self, flag, id, vipFlags):
        play_page = id if id.startswith("http") else self._fix_url(id)
        self.log("player: %s" % play_page)

        now = int(time.time())
        if play_page in self._play_cache:
            ts, res = self._play_cache[play_page]
            if now - ts < 600:
                return res

        html = self._fetch(play_page, headers={"Referer": self.site_url + "/"})
        real_url = ""
        if html:
            m = _RE_PLAYER.search(html)
            if m:
                try:
                    data = json.loads(m.group(1))
                    real_url = data.get("url", "") or ""
                except Exception as e:
                    self.log("player json fail: %s" % e)

        if real_url:
            if real_url.startswith("//"):
                real_url = "https:" + real_url
            proxy_url = self.site_url + "/m3u8/?url=" + \
                        urllib.parse.quote(real_url, safe="")
            res = {
                "parse": 0,
                "playUrl": "",
                "url": proxy_url,
                "header": {
                    "User-Agent": UA,
                    "Referer": self.site_url + "/",
                },
            }
            self._play_cache[play_page] = (now, res)
            self.log("  playUrl: %s" % proxy_url[:200])
            return res

        res = {
            "parse": 1, "playUrl": "",
            "url": play_page,
            "header": {"User-Agent": UA, "Referer": self.site_url + "/"},
        }
        self._play_cache[play_page] = (now, res)
        return res

    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]

    def isVideoFormat(self, url):
        return ".m3u8" in url or ".mp4" in url or url.startswith("http")

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def close(self):
        self.destroy()
