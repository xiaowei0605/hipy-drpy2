# coding=utf-8
"""
飘花播播 7itv.com | TVBox Python 爬虫
结构依据：MacCMS + mxtheme 模板
- 分类页 /vodshow/{class}-{?}-{order}-{?}-{letter}-{?}-{?}-{?}-{page}-{?}-{?}-{year}.html
  实际字段：0=class, 2=order, 4=letter, 8=page, 11=year
- 详情页 /voddetail/{id}.html
- 播放页 /vodplay/{id}-{sid}-{nid}.html
- 搜索 /vodsearch/{wd}-------------.html
"""
import re
import sys
import json
import time
import base64
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
                a = _rq.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=0)
                self._session.mount('https://', a)
                self._session.mount('http://', a)
            return self._session

        def fetch(self, url, headers=None, **kw):
            timeout = kw.pop('timeout', 15)
            r = self._sess.get(url, headers=headers, timeout=timeout, **kw)
            r.encoding = 'utf-8'
            return r

        def log(self, *a, **kw):
            try:
                print("[7itv]", *a)
            except Exception:
                pass

    Spider = _BaseSpider


HOST = "https://www.7itv.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
DEFAULT_PIC = HOST + "/mxtheme/images/logo.png"

INTRO_PREFIX = "🍊小橙子为您介绍剧情👉请不要相信视频中的广告，以免上当受骗！"

CLASSES = [
    {"type_id": "1", "type_name": "电影"},
    {"type_id": "2", "type_name": "剧集"},
    {"type_id": "3", "type_name": "综艺"},
    {"type_id": "4", "type_name": "动漫"},
    {"type_id": "5", "type_name": "短剧"},
]

_SUB_CLASS = {
    "1": [("动作片", "6"), ("喜剧片", "7"), ("爱情片", "8"), ("科幻片", "9"),
          ("恐怖片", "10"), ("剧情片", "11"), ("战争片", "12"),
          ("纪录片", "21"), ("其他片", "22")],
    "2": [("国产剧", "13"), ("港台剧", "14"), ("日韩剧", "15"),
          ("欧美剧", "16"), ("海外剧", "20")],
    "3": [],
    "4": [],
    "5": [],
}

_NAME2ID = {
    "动作片": "6", "喜剧片": "7", "爱情片": "8", "科幻片": "9",
    "恐怖片": "10", "剧情片": "11", "战争片": "12", "纪录片": "21", "其他片": "22",
    "国产剧": "13", "港台剧": "14", "日韩剧": "15", "欧美剧": "16", "海外剧": "20",
    "电影": "1", "剧集": "2", "综艺": "3", "动漫": "4", "短剧": "5",
}

_YEARS = [{"n": "全部", "v": ""}] + \
         [{"n": str(y), "v": str(y)} for y in range(2026, 2009, -1)]

_LETTERS = [{"n": "全部", "v": ""}] + \
           [{"n": x, "v": x} for x in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"] + \
           [{"n": "0-9", "v": "0-9"}]

_SORTS = [
    {"n": "时间", "v": "time"},
    {"n": "人气", "v": "hits"},
    {"n": "评分", "v": "score"},
]

FILTERS = {}
for c in CLASSES:
    tid = c["type_id"]
    subs = _SUB_CLASS.get(tid, [])

    if subs:
        class_vals = [{"n": "全部", "v": ""}] + [{"n": n, "v": sid} for n, sid in subs]
        FILTERS[tid] = [
            {"key": "class",  "name": "类型", "value": class_vals},
            {"key": "year",   "name": "年份", "value": _YEARS},
            {"key": "letter", "name": "字母", "value": _LETTERS},
            {"key": "sort",   "name": "排序", "value": _SORTS},
        ]
    else:
        FILTERS[tid] = [
            {"key": "year",   "name": "年份", "value": _YEARS},
            {"key": "letter", "name": "字母", "value": _LETTERS},
            {"key": "sort",   "name": "排序", "value": _SORTS},
        ]


_LINE_ALIAS = {
    "lzm3u8": "量子云", "wjm3u8": "无尽云", "snm3u8": "索尼", "ffm3u8": "非凡云",
}


# ============ 正则 ============
_RE_CARD_BLOCK = re.compile(
    r'<a\s+href="(/voddetail/\d+\.html)"[^>]*?title="([^"]*)"[^>]*?class="[^"]*module-poster-item[^"]*"'
    r'[\s\S]*?</a>',
    re.S | re.I)
_RE_CARD_PIC  = re.compile(r'<img[^>]*?(?:data-original|src)="([^"]*)"', re.I)
_RE_CARD_NOTE = re.compile(r'<div class="module-item-note">([^<]*)</div>', re.I)

_RE_H1 = re.compile(r'<h1[^>]*>([\s\S]*?)</h1>', re.I)
_RE_PIC = re.compile(r'data-original="(/upload/vod/[^"]+)"', re.I)
_RE_INTRO = re.compile(
    r'<div class="module-info-introduction-content">([\s\S]*?)</div>',
    re.S | re.I)

_RE_DIRECTOR = re.compile(
    r'<span class="module-info-item-title">导演：</span>\s*<div[^>]*>([\s\S]*?)</div>',
    re.S | re.I)
_RE_WRITER = re.compile(
    r'<span class="module-info-item-title">编剧：</span>\s*<div[^>]*>([\s\S]*?)</div>',
    re.S | re.I)
_RE_ACTOR = re.compile(
    r'<span class="module-info-item-title">主演：</span>\s*<div[^>]*>([\s\S]*?)</div>',
    re.S | re.I)
_RE_DURATION = re.compile(
    r'<span class="module-info-item-title">片长：</span>\s*<div[^>]*>([^<]*)</div>',
    re.I)
_RE_UPDATE = re.compile(
    r'<span class="module-info-item-title">更新：</span>\s*<div[^>]*>([^<]*)</div>',
    re.I)
_RE_EPISODE_CNT = re.compile(
    r'<span class="module-info-item-title">集数：</span>\s*<div[^>]*>([^<]*)</div>',
    re.I)

# 标签块 + 所有 <a>
_RE_TAG_BLOCK = re.compile(
    r'<div class="module-info-tag">([\s\S]*?)</div>\s*</div>',
    re.S | re.I)
_RE_TAG_A = re.compile(r'<a[^>]*>([^<]+)</a>', re.I)

_RE_A_TAG = re.compile(r'<a[^>]*>([^<]*)</a>', re.I)

_RE_TAB = re.compile(
    r'<div class="module-tab-item tab-item"[^>]*data-dropdown-value="([^"]+)"[^>]*>'
    r'\s*<span>([^<]+)</span>',
    re.I)

_RE_EP_BLOCK = re.compile(
    r'<a\s+class="module-play-list-link[^"]*"\s+([^>]*?)>(.*?)</a>',
    re.S | re.I)
_RE_EP_HREF  = re.compile(r'href="(/vodplay/(\d+)-(\d+)-(\d+)\.html)"', re.I)
_RE_EP_TITLE = re.compile(r'title="([^"]*)"', re.I)
_RE_EP_SPAN  = re.compile(r'<span>([^<]*)</span>', re.I)

_RE_PLAYER = re.compile(r'var\s+player_aaaa\s*=\s*(\{[\s\S]*?\})\s*</script>', re.S)

_RE_PAGE_NUM = re.compile(r'/vodshow/[^"\']*?-(\d+)---[^"\']*?\.html', re.I)
_RE_PAGE_TAIL = re.compile(r'尾页[^/]*href="[^"]*?-(\d+)---', re.I)


class Spider(Spider):

    def getName(self):
        return "飘花播播"

    def init(self, extend=""):
        try:
            self.extend = json.loads(extend) if extend else {}
        except Exception:
            self.extend = {}

        self.site_url = (self.extend.get("site") or HOST).rstrip("/")
        self.headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": self.site_url + "/",
            "Upgrade-Insecure-Requests": "1",
        }
        self.default_pic = DEFAULT_PIC
        self._last_search_ts = 0
        self._play_cache = {}
        self.log("init: site=%s" % self.site_url)

    # ---------- 基础 ----------
    def _fetch(self, url, timeout=20, headers=None):
        h = dict(self.headers)
        if headers:
            h.update(headers)
        try:
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
              .replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">")
              .replace("&hellip;", "…"))
        s = re.sub(r"[ \t\r\f\v]+", " ", s)
        s = re.sub(r"\n{2,}", "\n", s)
        return s.strip()

    def _extract_videos(self, html):
        videos, seen = [], set()
        if not html:
            return videos

        for mb in _RE_CARD_BLOCK.finditer(html):
            href = mb.group(1)
            title = mb.group(2)
            block = mb.group(0)

            if href in seen:
                continue
            seen.add(href)

            pic = ""
            mp = _RE_CARD_PIC.search(block)
            if mp:
                pic = mp.group(1)

            note = ""
            mn = _RE_CARD_NOTE.search(block)
            if mn:
                note = mn.group(1)

            videos.append({
                "vod_id": href,
                "vod_name": self._clean(title)[:100],
                "vod_pic": self._fix_url(pic) or self.default_pic,
                "vod_remarks": self._clean(note),
            })

        return videos

    def _page_count(self, html, cur=1):
        if not html:
            return cur
        nums = []
        for m in _RE_PAGE_NUM.finditer(html):
            try:
                nums.append(int(m.group(1)))
            except Exception:
                pass
        for m in _RE_PAGE_TAIL.finditer(html):
            try:
                nums.append(int(m.group(1)))
            except Exception:
                pass
        return max(nums) if nums else cur

    def _extract_names(self, html_block):
        if not html_block:
            return ""
        names = []
        for m in _RE_A_TAG.finditer(html_block):
            n = self._clean(m.group(1))
            if n:
                names.append(n)
        return ", ".join(names)

    # ---------- TVBox 接口 ----------
    def homeContent(self, filter=False):
        return {"class": CLASSES, "filters": FILTERS}

    def homeVideoContent(self):
        html = self._fetch(self.site_url + "/")
        return {"list": self._extract_videos(html)}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        if isinstance(extend, str):
            try:
                extend = json.loads(extend)
            except Exception:
                extend = {}
        if not isinstance(extend, dict):
            extend = {}

        def _pick(k):
            v = extend.get(k, "")
            if isinstance(v, list):
                v = v[0] if v else ""
            return str(v or "").strip()

        class_id = _pick("class") or str(tid)
        if class_id in _NAME2ID:
            class_id = _NAME2ID[class_id]
        if not class_id.isdigit():
            class_id = str(tid)

        letter = _pick("letter")
        order  = _pick("sort")
        year   = _pick("year")

        # MacCMS 12 段：0=class 2=order 4=letter 8=page 11=year
        segs = [""] * 12
        segs[0]  = class_id
        segs[2]  = order
        segs[4]  = letter
        segs[8]  = "" if page <= 1 else str(page)
        segs[11] = year

        path = "-".join(segs)
        url = "%s/vodshow/%s.html" % (self.site_url, path)

        html = self._fetch(url)
        videos = self._extract_videos(html)
        self.log("category: %s | html=%d videos=%d" % (url, len(html), len(videos)))

        if not videos:
            fb = "%s/vodtype/%s.html" % (self.site_url, tid)
            if page > 1:
                fb = "%s/vodtype/%s/page/%d.html" % (self.site_url, tid, page)
            html2 = self._fetch(fb)
            videos2 = self._extract_videos(html2)
            self.log("fallback: %s | html=%d videos=%d" % (fb, len(html2), len(videos2)))
            if videos2:
                html = html2
                videos = videos2

        pc = self._page_count(html, page)
        return {"list": videos, "page": page, "pagecount": pc,
                "limit": 24, "total": pc * 24}

    def searchContent(self, key, quick, pg="1"):
        now = time.time()
        wait = 5 - (now - self._last_search_ts)
        if wait > 0:
            time.sleep(wait)
        self._last_search_ts = time.time()

        page = int(pg) if pg else 1
        wd = urllib.parse.quote(key)
        url = "%s/vodsearch/%s-------------.html" % (self.site_url, wd)
        if page > 1:
            url = url.replace(".html", "/page/%d.html" % page)
        self.log("search: %s" % url)
        html = self._fetch(url)

        if "请勿频繁操作" in html or "系统提示" in html:
            self.log("search 被限频拦截")
            return {"list": [], "page": page, "pagecount": 1,
                    "limit": 24, "total": 0}

        videos = self._extract_videos(html)
        return {"list": videos, "page": page,
                "pagecount": self._page_count(html, page),
                "limit": 24, "total": 999}

    def searchContentPage(self, key, quick, pg="1"):
        return self.searchContent(key, quick, pg)

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vod_id = str(ids[0])
        url = vod_id if vod_id.startswith("http") else self._fix_url(vod_id)
        html = self._fetch(url)
        if not html:
            return {"list": []}

        name = ""
        m = _RE_H1.search(html)
        if m:
            name = self._clean(m.group(1))
        if not name:
            m = re.search(r"<title>(.*?)</title>", html, re.S)
            if m:
                name = self._clean(m.group(1).split("_")[0])
        name = re.sub(r"\s*\(\d{4}\)\s*$", "", name).strip() or vod_id

        pic = self.default_pic
        m = _RE_PIC.search(html)
        if m:
            pic = self._fix_url(m.group(1))

        content = ""
        m = _RE_INTRO.search(html)
        if m:
            content = self._clean(m.group(1))
        content = (INTRO_PREFIX + "\n" + content) if content else INTRO_PREFIX

        director = ""
        m = _RE_DIRECTOR.search(html)
        if m:
            director = self._extract_names(m.group(1))

        writer = ""
        m = _RE_WRITER.search(html)
        if m:
            writer = self._extract_names(m.group(1))

        actor = ""
        m = _RE_ACTOR.search(html)
        if m:
            actor = self._extract_names(m.group(1))

        # ---------- 片长（去重"分钟分钟"） ----------
        duration = ""
        m = _RE_DURATION.search(html)
        if m:
            duration = self._clean(m.group(1))
            duration = re.sub(r'分钟+$', '分钟', duration)

        update = ""
        m = _RE_UPDATE.search(html)
        if m:
            update = self._clean(m.group(1))

        ep_cnt = ""
        m = _RE_EPISODE_CNT.search(html)
        if m:
            ep_cnt = self._clean(m.group(1))

        # ---------- 标签：从 module-info-tag 整块里抓所有 <a> ----------
        tags = []
        mtb = _RE_TAG_BLOCK.search(html)
        if mtb:
            for am in _RE_TAG_A.finditer(mtb.group(1)):
                t = self._clean(am.group(1))
                if t and t not in tags:
                    tags.append(t)

        # ---------- 组装 ----------
        dir_parts = []
        if director:
            dir_parts.append(director)
        if writer:
            dir_parts.append("编剧:" + writer)
        vod_director = " / ".join(dir_parts) if dir_parts else ""

        remark_parts = []
        if tags:
            remark_parts.append(" / ".join(tags))
        if duration:
            remark_parts.append("片长:" + duration)
        if ep_cnt:
            remark_parts.append(ep_cnt)
        elif update:
            remark_parts.append("更新:" + update)
        vod_remarks = " · ".join(remark_parts) if remark_parts else ""

        # 播放源
        tab_names = []
        for m in _RE_TAB.finditer(html):
            tn = self._clean(m.group(2))
            if tn:
                tab_names.append(tn)

        groups = {}
        sid_order = []
        for mb in _RE_EP_BLOCK.finditer(html):
            attrs = mb.group(1)
            inner = mb.group(2)

            mh = _RE_EP_HREF.search(attrs)
            if not mh:
                continue
            href = mh.group(1)
            sid = mh.group(3)
            nid = mh.group(4)

            ep_name = ""
            ms = _RE_EP_SPAN.search(inner)
            if ms:
                ep_name = self._clean(ms.group(1))
            if not ep_name:
                mt = _RE_EP_TITLE.search(attrs)
                if mt:
                    ep_name = self._clean(mt.group(1))
            if not ep_name:
                ep_name = "第%s集" % nid
            ep_name = re.sub(r'^播放.*?(第\s*\d+\s*集.*)$', r'\1', ep_name).strip()
            ep_name = re.sub(r'^播放', '', ep_name).strip()
            if not ep_name:
                ep_name = "第%s集" % nid

            full = self._fix_url(href)
            if sid not in groups:
                groups[sid] = []
                sid_order.append(sid)
            if any(u == full for _, u in groups[sid]):
                continue
            groups[sid].append((ep_name, full))

        if not groups:
            return {"list": []}

        play_from, play_url = [], []
        for i, sid in enumerate(sid_order):
            eps = groups[sid]
            if not eps:
                continue
            alias = tab_names[i] if i < len(tab_names) else ""
            if not alias:
                alias = _LINE_ALIAS.get(sid, "线路%s" % (i + 1))
            play_from.append(alias)
            play_url.append("#".join("%s$%s" % (n, u) for n, u in eps))

        return {"list": [{
            "vod_id": vod_id,
            "vod_name": name,
            "vod_pic": pic,
            "vod_content": content,
            "vod_actor": actor,
            "vod_director": vod_director,
            "vod_remarks": vod_remarks or ("%d条线路" % len(play_from)),
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
        }]}

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags):
        play_page = id if id.startswith("http") else self._fix_url(id)
        now = int(time.time())
        if play_page in self._play_cache:
            ts, res = self._play_cache[play_page]
            if now - ts < 600:
                return res

        html = self._fetch(play_page)
        real_url = ""
        header_ref = self.site_url + "/"

        m = _RE_PLAYER.search(html)
        if m:
            raw = m.group(1)
            try:
                data = json.loads(raw)
            except Exception:
                data = {}
            enc = data.get("url") or ""
            if enc:
                real_url = self._decode_player_url(enc)
            if not real_url and isinstance(enc, str) and enc.startswith("http"):
                real_url = enc

        if real_url:
            res = {
                "parse": 0,
                "playUrl": "",
                "url": real_url,
                "header": {
                    "User-Agent": UA,
                    "Referer": header_ref,
                },
            }
            self._play_cache[play_page] = (now, res)
            self.log("=> m3u8: %s" % real_url[:160])
            return res

        res = {"parse": 1, "playUrl": "", "url": play_page,
               "header": {"User-Agent": UA, "Referer": header_ref}}
        self._play_cache[play_page] = (now, res)
        return res

    def _decode_player_url(self, enc):
        if not enc:
            return ""
        try:
            s = urllib.parse.unquote(enc)
        except Exception:
            s = enc
        pad = len(s) % 4
        if pad:
            s += "=" * (4 - pad)
        try:
            raw = base64.b64decode(s).decode("utf-8", "ignore")
        except Exception:
            return ""
        try:
            if "%" in raw:
                raw = urllib.parse.unquote(raw)
        except Exception:
            pass
        raw = raw.replace("\\/", "/").replace("&amp;", "&")
        return raw if raw.startswith("http") else ""

    # ---------- 杂项 ----------
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
