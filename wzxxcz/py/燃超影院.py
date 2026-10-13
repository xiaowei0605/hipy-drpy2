# coding=utf-8
"""
燃超影院 aarnadhya.com | TVBox Python 爬虫 (curl_cffi 版)
- 用 curl_cffi 模拟 Chrome TLS 指纹，绕过 Cloudflare Bot Fight
- DOM 解析卡片、剧集、播放
"""
import re
import sys
import json
import time
import urllib.parse

sys.path.append('..')

# ============ 网络层：curl_cffi 优先 ============
try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except ImportError:
    HAS_CFFI = False

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
                print("[rancho]", *a)
            except Exception:
                pass

    Spider = _BaseSpider


HOST = "https://www.aarnadhya.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
DEFAULT_PIC = HOST + "/template/m4-drama/images/favicon.svg"

# ============ 顶级分类 ============
CLASSES = [
    {"type_id": "1",  "type_name": "电影"},
    {"type_id": "2",  "type_name": "电视剧"},
    {"type_id": "3",  "type_name": "短剧"},
    {"type_id": "4",  "type_name": "动漫"},
    {"type_id": "5",  "type_name": "综艺"},
    {"type_id": "48", "type_name": "网飞新剧"},
    {"type_id": "47", "type_name": "AI漫剧"},
]

_GENRE_MAP = {
    "1":  ["剧情", "喜剧", "动作", "恐怖", "爱情", "科幻", "惊悚",
           "战争", "犯罪", "悬疑", "奇幻"],
    "2":  ["喜剧", "爱情", "悬疑", "古装", "剧情", "武侠", "都市",
           "仙侠", "谍战", "战争", "奇幻", "冒险"],
    "3":  ["现代都市", "女频恋爱", "古装仙侠", "反转爽剧", "穿越", "逆袭",
           "脑洞悬疑", "甜宠", "重生", "虐恋", "现代言情", "神豪", "悬疑"],
    "4":  ["剧情", "奇幻", "犯罪", "悬疑", "惊悚", "喜剧", "古装",
           "爱情", "科幻", "动作"],
    "5":  ["古装", "剧情", "喜剧", "动作", "都市", "爱情", "穿越", "科幻",
           "逆袭", "惊悚", "悬疑", "犯罪", "武侠", "谍战", "冒险"],
    "48": ["古装", "剧情", "喜剧", "动作", "都市", "爱情", "穿越", "科幻",
           "逆袭", "惊悚", "悬疑", "犯罪", "武侠", "谍战", "冒险"],
    "47": ["剧情", "奇幻", "犯罪", "悬疑", "惊悚", "喜剧", "古装",
           "爱情", "科幻", "动作"],
}

_AREAS = ["大陆", "香港", "台湾", "美国", "韩国", "日本", "欧美", "英国",
          "法国", "泰国", "印度", "加拿大", "西班牙", "德国", "俄罗斯", "新加坡"]
_YEARS = [str(y) for y in range(2026, 2011, -1)]
_SORTS = [("time", "最近更新"), ("hits", "最多播放"), ("score", "最高评分")]


def _mk(vals):
    out = [{"n": "全部", "v": ""}]
    for v in vals:
        out.append({"n": v, "v": v})
    return out


FILTERS = {}
for c in CLASSES:
    tid = c["type_id"]
    FILTERS[tid] = [
        {"key": "class", "name": "剧情",
         "value": _mk(_GENRE_MAP.get(tid, []))},
        {"key": "area", "name": "地区", "value": _mk(_AREAS)},
        {"key": "year", "name": "年份", "value": _mk(_YEARS)},
        {"key": "by",   "name": "排序",
         "value": [{"n": n, "v": v} for v, n in _SORTS]},
    ]


# ============ 正则 ============
_RE_CARD = re.compile(
    r'<a\s+href="(/video/[^"]+\.html)"\s+class="zj-item"[^>]*?title="([^"]*)"[^>]*>'
    r'([\s\S]*?)</a>',
    re.S | re.I)
_RE_BANNER = re.compile(
    r'<a\s+href="(/video/[^"]+\.html)"\s+class="zj-banner"[^>]*?title="([^"]*)"[^>]*>'
    r'([\s\S]*?)</a>',
    re.S | re.I)

_RE_CARD_IMG = re.compile(r'<img[^>]*?src="([^"]*)"', re.I)
_RE_CARD_CORNER = re.compile(r'<div\s+class="zj-corner[^"]*"[^>]*title="([^"]*)"', re.I)
_RE_CARD_TITLE = re.compile(r'<div\s+class="zj-item-title[^"]*"[^>]*>([\s\S]*?)</div>', re.I)
_RE_BANNER_TAGS = re.compile(r'<span>([^<]*)</span>', re.I)

_RE_H1 = re.compile(r'<h1[^>]*>([\s\S]*?)<small', re.I)
_RE_DETAIL_COVER = re.compile(r'<div\s+class="zj-detail-cover">\s*<img[^>]*?src="([^"]*)"', re.S | re.I)
_RE_DIRECTOR = re.compile(r'导演：<b>([^<]*)</b>', re.I)
_RE_ACTOR = re.compile(r'主演：<b>([^<]*)</b>', re.I)
_RE_SCORE = re.compile(r'<span\s+class="zj-rating-num">([\d.]+)</span>', re.I)
_RE_DESC = re.compile(r'<p\s+class="zj-desc[^"]*">([\s\S]*?)</p>', re.S | re.I)

_RE_LINE_BTN = re.compile(
    r'<button\s+class="zj-line-btn[^"]*"\s+type="button"\s+data-sid="(\d+)"[^>]*>([^<]*)</button>',
    re.I)
_RE_EPS_PANEL = re.compile(
    r'<div\s+class="zj-eps\s+zj-eps-panel[^"]*"\s+data-sid="(\d+)"[^>]*>([\s\S]*?)</div>',
    re.S | re.I)
_RE_EP = re.compile(
    r'<a\s+href="(/play/[^"]+\.html)"\s+class="zj-ep[^"]*"\s+title="([^"]*)"[^>]*>([^<]*)</a>',
    re.I)
_RE_LAST_PAGE = re.compile(r'href="/tv/\d+/[^"]*?page/(\d+)', re.I)

_RE_PLAYER = re.compile(r'var\s+player_aaaa\s*=\s*(\{[\s\S]*?\})\s*</script>', re.I)
_RE_PLAYER_URL = re.compile(r'"url"\s*:\s*"([^"]+)"', re.I)
_RE_PLAYER_FROM = re.compile(r'"from"\s*:\s*"([^"]*)"', re.I)


class Spider(Spider):

    def getName(self):
        return "燃超影院"

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
            "Accept-Encoding": "gzip, deflate",
            "Referer": self.site_url + "/",
        }
        self.default_pic = DEFAULT_PIC
        self._play_cache = {}
        self.log("init: site=%s cffi=%s" % (self.site_url, HAS_CFFI))

    # ---------- 网络 ----------
    def _fetch(self, url, timeout=25, headers=None):
        h = dict(self.headers)
        h["Referer"] = url
        if headers:
            h.update(headers)
        try:
            if HAS_CFFI:
                # 关键：impersonate 模拟 Chrome TLS 指纹，过 Cloudflare
                rsp = cffi_requests.get(url, headers=h, timeout=timeout,
                                        impersonate="chrome120", verify=False)
                return rsp.text or ""
            else:
                # 兜底：原生 requests（会被 Cloudflare 拦，仅防完全跑不起来）
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
        s = (s.replace("&nbsp;", " ").replace("\xa0", " ")
              .replace("&amp;", "&").replace("&quot;", '"')
              .replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">"))
        return re.sub(r"\s+", " ", s).strip()

    # ---------- 卡片解析 ----------
    def _extract_videos(self, html):
        videos = []
        seen = set()
        if not html:
            return videos

        for m in _RE_CARD.finditer(html):
            href, a_title, inner = m.group(1), m.group(2), m.group(3)
            if href in seen:
                continue
            seen.add(href)

            name = self._clean(a_title)
            if not name:
                tm = _RE_CARD_TITLE.search(inner)
                if tm:
                    name = self._clean(tm.group(1))
            if not name:
                name = href.rsplit("/", 1)[-1].replace(".html", "")

            pic = ""
            im = _RE_CARD_IMG.search(inner)
            if im:
                pic = self._fix_url(im.group(1))
            if not pic:
                pic = self.default_pic

            remark = ""
            cm = _RE_CARD_CORNER.search(inner)
            if cm:
                remark = self._clean(cm.group(1))

            videos.append({
                "vod_id":      href,
                "vod_name":    name[:100],
                "vod_pic":     pic,
                "vod_remarks": remark,
            })

        if not videos:
            for m in _RE_BANNER.finditer(html):
                href, a_title, inner = m.group(1), m.group(2), m.group(3)
                if href in seen:
                    continue
                seen.add(href)

                name = self._clean(a_title)
                if not name:
                    tm = re.search(r'<div\s+class="zj-banner-title[^"]*"[^>]*>([\s\S]*?)</div>', inner, re.I)
                    if tm:
                        name = self._clean(tm.group(1))

                pic = ""
                im = _RE_CARD_IMG.search(inner)
                if im:
                    pic = self._fix_url(im.group(1))
                if not pic:
                    pic = self.default_pic

                remark = ""
                tags = _RE_BANNER_TAGS.findall(inner)
                if tags:
                    remark = self._clean(tags[-1])

                videos.append({
                    "vod_id":      href,
                    "vod_name":    name[:100],
                    "vod_pic":     pic,
                    "vod_remarks": remark,
                })

        return videos

    def _page_count(self, html, current_page=1):
        if not html:
            return current_page
        nums = _RE_LAST_PAGE.findall(html)
        if nums:
            try:
                return max(int(x) for x in nums)
            except Exception:
                pass
        m = re.search(r'<span>\d+/(\d+)</span>', html)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
        return current_page

    # ---------- TVBox 接口 ----------
    def homeContent(self, filter=False):
        return {"class": CLASSES, "filters": FILTERS}

    def homeVideoContent(self):
        html = self._fetch(self.site_url + "/")
        return {"list": self._extract_videos(html)}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg) if pg else 1
        except Exception:
            page = 1

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

        # 站点真实拼接顺序：class → area → lang → page → year → by
        seg = []
        if extend.get("class"):
            seg.append("class/%s" % urllib.parse.quote(extend["class"]))
        if extend.get("area"):
            seg.append("area/%s" % urllib.parse.quote(extend["area"]))
        if extend.get("lang"):
            seg.append("lang/%s" % urllib.parse.quote(extend["lang"]))
        if page > 1:
            seg.append("page/%d" % page)
        if extend.get("year"):
            seg.append("year/%s" % extend["year"])
        if extend.get("by"):
            seg.append("by/%s" % extend["by"])

        if seg:
            url = "%s/tv/%s/%s.html" % (self.site_url, tid, "/".join(seg))
        else:
            url = "%s/tv/%s.html" % (self.site_url, tid)

        self.log("category: %s" % url)
        html = self._fetch(url)
        self.log("  html len=%d" % len(html))
        videos = self._extract_videos(html)
        pc = self._page_count(html, page)
        self.log("  -> %d 条, 共 %d 页" % (len(videos), pc))

        return {
            "list": videos, "page": page, "pagecount": pc,
            "limit": 36, "total": pc * 36,
        }

    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg) if pg else 1
        except Exception:
            page = 1
        url = "%s/search.html?wd=%s" % (self.site_url, urllib.parse.quote(key))
        if page > 1:
            url += "&page=%d" % page
        self.log("search: %s" % url)
        html = self._fetch(url)
        videos = self._extract_videos(html)
        return {
            "list": videos, "page": page,
            "pagecount": self._page_count(html, page),
            "limit": 36, "total": 999,
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
        if not html:
            return {"list": []}

        name = ""
        m = _RE_H1.search(html)
        if m:
            name = self._clean(m.group(1))
        if not name:
            m = re.search(r"<title>(.*?)</title>", html, re.S)
            if m:
                name = self._clean(m.group(1).split("_")[0].split("-")[0])
        name = name or vod_id

        pic = self.default_pic
        m = _RE_DETAIL_COVER.search(html)
        if m:
            pic = self._fix_url(m.group(1))

        director, actor = "", ""
        m = _RE_DIRECTOR.search(html)
        if m:
            director = self._clean(m.group(1))
        m = _RE_ACTOR.search(html)
        if m:
            actor = self._clean(m.group(1))

        score = ""
        m = _RE_SCORE.search(html)
        if m:
            score = m.group(1)

        content = ""
        m = _RE_DESC.search(html)
        if m:
            content = self._clean(m.group(1))
        if not content:
            m = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]*)"', html, re.I)
            if m:
                content = self._clean(m.group(1))
        content = ("🍊小橙子提醒您：请勿相信视频中的广告！\n" + content) if content \
            else "🍊小橙子提醒您：请勿相信视频中的广告！"

        line_names = {}
        for m in _RE_LINE_BTN.finditer(html):
            line_names[m.group(1)] = self._clean(m.group(2)) or ("线路%s" % m.group(1))

        groups = {}
        for pm in _RE_EPS_PANEL.finditer(html):
            sid = pm.group(1)
            block = pm.group(2)
            eps = []
            for em in _RE_EP.finditer(block):
                href = em.group(1)
                title = self._clean(em.group(2)) or self._clean(em.group(3))
                if href.startswith("/"):
                    href = self.site_url + href
                eps.append((title or ("第%d集" % (len(eps) + 1)), href))
            if eps:
                groups[sid] = eps

        self.log("  剧集线路: %s" % {k: len(v) for k, v in groups.items()})
        if not groups:
            return {"list": []}

        order = list(line_names.keys())
        for sid in groups.keys():
            if sid not in order:
                order.append(sid)

        play_from, play_url = [], []
        for sid in order:
            if sid not in groups:
                continue
            eps = groups[sid]
            play_from.append(line_names.get(sid, "线路%s" % sid))
            play_url.append("#".join("%s$%s" % (n, h) for n, h in eps))

        return {"list": [{
            "vod_id":       vod_id,
            "vod_name":     name,
            "vod_pic":      pic,
            "vod_content":  content,
            "vod_actor":    actor,
            "vod_director": director,
            "vod_score":    score,
            "vod_remarks":  "%d条线路" % len(play_from),
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url":  "$$$".join(play_url),
        }]}

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags):
        play_page = id if id.startswith("http") else self._fix_url(id)
        self.log("player: %s" % play_page)

        now = int(time.time())
        if play_page in self._play_cache:
            ts, res = self._play_cache[play_page]
            if now - ts < 600:
                return res

        html = self._fetch(play_page)
        real_url = ""
        from_flag = ""

        if html:
            pm = _RE_PLAYER.search(html)
            if pm:
                obj_text = pm.group(1)
                um = _RE_PLAYER_URL.search(obj_text)
                if um:
                    real_url = um.group(1)
                    real_url = (real_url.replace("\\/", "/")
                                .replace("&amp;", "&"))
                fm = _RE_PLAYER_FROM.search(obj_text)
                if fm:
                    from_flag = fm.group(1)

        if real_url:
            self.log("  player url: %s (from=%s)" % (real_url[:160], from_flag))
            res = {
                "parse": 0,
                "playUrl": "",
                "url": real_url,
                "header": {
                    "User-Agent": UA,
                    "Referer": self.site_url + "/",
                },
            }
            self._play_cache[play_page] = (now, res)
            return res

        self.log("  未找到 player_aaaa，交给 TVBox 嗅探")
        res = {"parse": 1, "playUrl": "", "url": play_page,
               "header": {"User-Agent": UA, "Referer": self.site_url + "/"}}
        self._play_cache[play_page] = (now, res)
        return res

    def isVideoFormat(self, url):
        return ".m3u8" in url or ".mp4" in url

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def close(self):
        self.destroy()
