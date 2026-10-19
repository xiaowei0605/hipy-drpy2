# coding=utf-8
"""
滴答影院 www.loldyw.com | TVBox Python 爬虫
严格对照真实源码，拒绝猜测：
  - 分类 ID 严格按照源码筛选栏提取
  - 筛选路径严格按照真实链接 /filter/ 提取
  - 搜索结果严格解析 ul#searchList 下的 li 结构
  - 详情剧集严格解析 #playlist 和 tab 标签
  - 播放直接提取 player_aaaa 的 url
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
                adapter = _rq.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=0)
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
                print("[loldyw]", *a)
            except Exception:
                pass
    Spider = _BaseSpider

HOST = "https://www.loldyw.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
DEFAULT_PIC = HOST + "/template/three/statics/img/load.gif"

INTRO_PREFIX = "🍊小橙子为您介绍剧情👉请不要相信视频中的广告，以免上当受骗！"

# ================= 1. 真实分类 ID =================
CLASSES = [
    {"type_id": "1", "type_name": "电影"},
    {"type_id": "2", "type_name": "电视剧"},
    {"type_id": "3", "type_name": "综艺"},
    {"type_id": "4", "type_name": "动漫"},
    {"type_id": "24", "type_name": "短剧"},
]

# ================= 2. 真实筛选列表 =================
_SORT_LIST = [{"n": "时间", "v": "time"}, {"n": "人气", "v": "hits"}, {"n": "评分", "v": "score"}]
# 严格对照源码还原年份：第一段为 2018-2010，第二段重复 2012-2026
_YEAR_LIST = [{"n": "全部", "v": ""}] + \
             [{"n": str(y), "v": str(y)} for y in range(2018, 2009, -1)] + \
             [{"n": str(y), "v": str(y)} for y in range(2012, 2027)]
_LETTER_LIST = [{"n": "全部", "v": ""}] + [{"n": c, "v": c} for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0-9"]
_LANG_LIST = [
    {"n": "全部", "v": ""}, {"n": "国语", "v": "国语"}, {"n": "英语", "v": "英语"},
    {"n": "粤语", "v": "粤语"}, {"n": "闽南语", "v": "闽南语"}, {"n": "韩语", "v": "韩语"},
    {"n": "日语", "v": "日语"}, {"n": "法语", "v": "法语"}, {"n": "德语", "v": "德语"},
    {"n": "其它", "v": "其它"}
]

FILTERS = {
    "1": [
        {"key": "tid", "name": "类型", "value": [
            {"n": "全部", "v": ""}, {"n": "动作片", "v": "6"}, {"n": "喜剧片", "v": "7"},
            {"n": "爱情片", "v": "8"}, {"n": "科幻片", "v": "9"}, {"n": "剧情片", "v": "10"},
            {"n": "战争片", "v": "11"}, {"n": "动画片", "v": "41"}, {"n": "记录片", "v": "12"},
            {"n": "恐怖片", "v": "39"}
        ]},
        {"key": "class", "name": "剧情", "value": [
            {"n": "全部", "v": ""}, {"n": "喜剧", "v": "喜剧"}, {"n": "爱情", "v": "爱情"},
            {"n": "恐怖", "v": "恐怖"}, {"n": "动作", "v": "动作"}, {"n": "科幻", "v": "科幻"},
            {"n": "剧情", "v": "剧情"}, {"n": "战争", "v": "战争"}, {"n": "警匪", "v": "警匪"},
            {"n": "犯罪", "v": "犯罪"}, {"n": "动画", "v": "动画"}, {"n": "奇幻", "v": "奇幻"}
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""}, {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"},
            {"n": "台湾", "v": "台湾"}, {"n": "美国", "v": "美国"}, {"n": "法国", "v": "法国"},
            {"n": "英国", "v": "英国"}, {"n": "日本", "v": "日本"}, {"n": "韩国", "v": "韩国"}
        ]},
        {"key": "year", "name": "年份", "value": _YEAR_LIST},
        {"key": "lang", "name": "语言", "value": _LANG_LIST},
        {"key": "letter", "name": "字母", "value": _LETTER_LIST},
        {"key": "sort", "name": "排序", "value": _SORT_LIST},
    ],
    "2": [
        {"key": "tid", "name": "类型", "value": [
            {"n": "全部", "v": ""}, {"n": "国产剧", "v": "13"}, {"n": "香港剧", "v": "14"},
            {"n": "韩国剧", "v": "15"}, {"n": "欧美剧", "v": "16"}, {"n": "台湾剧", "v": "22"},
            {"n": "日本剧", "v": "21"}, {"n": "泰国剧", "v": "20"}, {"n": "海外剧", "v": "23"}
        ]},
        {"key": "class", "name": "剧情", "value": [
            {"n": "全部", "v": ""}, {"n": "古装", "v": "古装"}, {"n": "战争", "v": "战争"},
            {"n": "青春偶像", "v": "青春偶像"}, {"n": "喜剧", "v": "喜剧"}, {"n": "家庭", "v": "家庭"},
            {"n": "犯罪", "v": "犯罪"}, {"n": "动作", "v": "动作"}, {"n": "奇幻", "v": "奇幻"},
            {"n": "剧情", "v": "剧情"}, {"n": "历史", "v": "历史"}, {"n": "经典", "v": "经典"},
            {"n": "乡村", "v": "乡村"}, {"n": "情景", "v": "情景"}, {"n": "商战", "v": "商战"},
            {"n": "网剧", "v": "网剧"}, {"n": "其他", "v": "其他"}
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""}, {"n": "内地", "v": "内地"}, {"n": "韩国", "v": "韩国"},
            {"n": "香港", "v": "香港"}, {"n": "台湾", "v": "台湾"}, {"n": "日本", "v": "日本"},
            {"n": "美国", "v": "美国"}, {"n": "泰国", "v": "泰国"}, {"n": "英国", "v": "英国"},
            {"n": "新加坡", "v": "新加坡"}, {"n": "其他", "v": "其他"}
        ]},
        {"key": "year", "name": "年份", "value": _YEAR_LIST},
        {"key": "lang", "name": "语言", "value": _LANG_LIST},
        {"key": "letter", "name": "字母", "value": _LETTER_LIST},
        {"key": "sort", "name": "排序", "value": _SORT_LIST},
    ],
    "3": [
        {"key": "tid", "name": "类型", "value": [
            {"n": "全部", "v": ""}, {"n": "大陆综艺", "v": "25"}, {"n": "日韩综艺", "v": "26"},
            {"n": "港台综艺", "v": "27"}, {"n": "欧美综艺", "v": "28"}
        ]},
        {"key": "class", "name": "剧情", "value": [
            {"n": "全部", "v": ""}, {"n": "选秀", "v": "选秀"}, {"n": "情感", "v": "情感"},
            {"n": "访谈", "v": "访谈"}, {"n": "播报", "v": "播报"}, {"n": "旅游", "v": "旅游"},
            {"n": "音乐", "v": "音乐"}, {"n": "美食", "v": "美食"}, {"n": "纪实", "v": "纪实"}
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""}, {"n": "内地", "v": "内地"}, {"n": "港台", "v": "港台"},
            {"n": "日韩", "v": "日韩"}, {"n": "欧美", "v": "欧美"}
        ]},
        {"key": "year", "name": "年份", "value": _YEAR_LIST},
        {"key": "lang", "name": "语言", "value": _LANG_LIST},
        {"key": "letter", "name": "字母", "value": _LETTER_LIST},
        {"key": "sort", "name": "排序", "value": _SORT_LIST},
    ],
    "4": [
        {"key": "tid", "name": "类型", "value": [
            {"n": "全部", "v": ""}, {"n": "国产动漫", "v": "29"}, {"n": "日本动漫", "v": "30"},
            {"n": "港台动漫", "v": "42"}, {"n": "欧美动漫", "v": "31"}, {"n": "海外动漫", "v": "43"}
        ]},
        {"key": "class", "name": "剧情", "value": [
            {"n": "全部", "v": ""}, {"n": "情感", "v": "情感"}, {"n": "科幻", "v": "科幻"},
            {"n": "热血", "v": "热血"}, {"n": "推理", "v": "推理"}, {"n": "搞笑", "v": "搞笑"},
            {"n": "冒险", "v": "冒险"}, {"n": "萝莉", "v": "萝莉"}, {"n": "校园", "v": "校园"}
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""}, {"n": "国产", "v": "国产"}, {"n": "日本", "v": "日本"},
            {"n": "欧美", "v": "欧美"}, {"n": "其他", "v": "其他"}
        ]},
        {"key": "year", "name": "年份", "value": _YEAR_LIST},
        {"key": "lang", "name": "语言", "value": _LANG_LIST},
        {"key": "letter", "name": "字母", "value": _LETTER_LIST},
        {"key": "sort", "name": "排序", "value": _SORT_LIST},
    ],
    "24": [
        {"key": "tid", "name": "类型", "value": [
            {"n": "全部", "v": ""}, {"n": "短剧大全", "v": "40"}, {"n": "AI漫剧", "v": "44"}
        ]},
        {"key": "letter", "name": "字母", "value": _LETTER_LIST},
        {"key": "sort", "name": "排序", "value": _SORT_LIST},
    ]
}

# ================= 3. 正则解析 =================
# 严格按照真实 DOM 解析并提取状态标签（补全副标题）
_RE_CARD = re.compile(
    r'<a\s+[^>]*class="[^"]*iqy-vodlist__thumb[^"]*"[^>]*'
    r'href="([^"]+)"[^>]*'
    r'title="([^"]*)"[^>]*'
    r'(?:data-original|data-src|src)="([^"]*)"[^>]*>[\s\S]*?'
    r'<span class="pic-text text-right">([^<]*)</span>',
    re.S | re.I)

_RE_H1 = re.compile(r'<h1 class="title">([\s\S]*?)</h1>', re.I)
_RE_DETAIL_PIC = re.compile(r'class="iqy-vodlist__thumb[^"]*picture"[^>]*>[\s\S]*?data-original="([^"]+)"', re.I)
_RE_DESC = re.compile(r'<span class="sketch content">([\s\S]*?)</span>', re.S | re.I)
_RE_RATING = re.compile(r'<span class="branch">([\d.]+)</span>', re.I)
_RE_ACTOR = re.compile(r'<p class="data"><span class="text-muted">主演：</span>([\s\S]*?)</p>', re.S)
_RE_DIRECTOR = re.compile(r'<p class="data"><span class="text-muted">导演：</span>([\s\S]*?)</p>', re.S)
_RE_REMARK = re.compile(r'<span class="text-muted">更新：</span><span class="text-red">([^<]+)</span>', re.I)
_RE_LINE_TAB = re.compile(r'<li[^>]*><a href="#(playlist\d+)"[^>]*>([^<]+)</a></li>', re.I)
_RE_LINE_BLOCK = re.compile(r'<div id="(playlist\d+)"[\s\S]*?<ul class="iqy-content__list[^"]*"[\s\S]*?</ul>', re.S | re.I)
_RE_EP = re.compile(r'<a class="btn btn-default[^"]*"\s+href="([^"]+)">([^<]+)</a>', re.I)
_RE_PLAYER = re.compile(r'var\s+player_aaaa\s*=\s*(\{[\s\S]*?\})\s*</script>', re.S)


class Spider(Spider):

    def getName(self):
        return "滴答影院"

    def init(self, extend=""):
        try:
            self.extend = json.loads(extend) if extend else {}
        except Exception:
            self.extend = {}
        self.site_url = (self.extend.get("site") or HOST).rstrip("/")
        self.headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": self.site_url + "/",
        }
        self.default_pic = DEFAULT_PIC
        self._play_cache = {}

    def _fetch(self, url, timeout=20):
        try:
            rsp = self.fetch(url, headers=self.headers, timeout=timeout)
            return rsp.text if hasattr(rsp, "text") else (rsp.content.decode("utf-8", "ignore") if hasattr(rsp, "content") else str(rsp))
        except Exception as e:
            self.log("fetch FAIL %s -> %s" % (url, e))
            return ""

    def _fix(self, url):
        if not url: return ""
        url = url.strip()
        if url.startswith("//"): return "https:" + url
        if url.startswith("http"): return url
        if url.startswith("/"): return self.site_url + url
        return urllib.parse.urljoin(self.site_url + "/", url)

    def _clean(self, s):
        if not s: return ""
        s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
        s = re.sub(r"<[^>]+>", "", s)
        s = (s.replace("&nbsp;", " ").replace("\xa0", " ").replace("&amp;", "&")
             .replace("&quot;", '"').replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">"))
        s = re.sub(r"[ \t\r\f\v]+", " ", s)
        s = re.sub(r"\n{2,}", "\n", s)
        return s.strip()

    def _parse_list(self, html):
        videos, seen = [], set()
        for m in _RE_CARD.finditer(html or ""):
            href, name, pic, remark = m.group(1), m.group(2), m.group(3), m.group(4)
            if href in seen: continue
            seen.add(href)
            videos.append({
                "vod_id": href,
                "vod_name": self._clean(name),
                "vod_pic": self._fix(pic) or self.default_pic,
                "vod_remarks": self._clean(remark),  # 补全了副标题（如：第20集）
            })
        return videos

    def homeContent(self, filter=False):
        return {"class": CLASSES, "filters": FILTERS}

    def homeVideoContent(self):
        html = self._fetch(self.site_url + "/")
        return {"list": self._parse_list(html)}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        if isinstance(extend, str):
            try: extend = json.loads(extend)
            except Exception: extend = {}
        extend = extend or {}

        for k in list(extend.keys()):
            if isinstance(extend[k], str) and "%" in extend[k]:
                extend[k] = urllib.parse.unquote(extend[k])

        sub_tid = extend.get("tid")
        real_tid = sub_tid if (sub_tid and sub_tid.strip()) else tid

        c_val = extend.get("class", "").strip()
        a_val = extend.get("area", "").strip()
        l_val = extend.get("lang", "").strip()
        e_val = extend.get("letter", "").strip()
        y_val = extend.get("year", "").strip()
        s_val = extend.get("sort", "").strip()

        # 完全按照源码真实的路径格式 /filter/id/13.html 和 /filter/id/13/year/2026.html 拼接
        parts = []
        if c_val: parts.append("class/%s" % urllib.parse.quote(c_val))
        if a_val: parts.append("area/%s" % urllib.parse.quote(a_val))
        if l_val: parts.append("lang/%s" % urllib.parse.quote(l_val))
        if e_val: parts.append("letter/%s" % e_val)
        if y_val: parts.append("year/%s" % y_val)
        if s_val: parts.append("by/%s" % s_val)

        if parts:
            base = "/filter/%s/id/%s" % ("/".join(parts), real_tid)
            if page > 1: base += "-%d" % page
            url = self.site_url + base + ".html"
        elif real_tid != tid:
            base = "/filter/id/%s" % real_tid
            if page > 1: base += "-%d" % page
            url = self.site_url + base + ".html"
        else:
            if page <= 1: url = "%s/genre/%s.html" % (self.site_url, real_tid)
            else: url = "%s/genre/%s-%d.html" % (self.site_url, real_tid, page)

        self.log("category: %s" % url)
        html = self._fetch(url)

        pagecount = 9999
        m = re.search(r'href="[^"]*-(\d+)\.html">尾页</a>', html)
        if m: pagecount = int(m.group(1))
        else:
            nums = [int(x) for x in re.findall(r'-(\d+)\.html', html)]
            if nums: pagecount = max(nums)

        return {"list": self._parse_list(html), "page": page, "pagecount": pagecount, "limit": 24, "total": pagecount * 24}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        kw = urllib.parse.quote(key)
        url = "%s/lookup/wd/%s.html" % (self.site_url, kw) if page == 1 else "%s/lookup/wd/%s-%d.html" % (self.site_url, kw, page)
        html = self._fetch(url)
        return {"list": self._parse_list(html), "page": page, "pagecount": 1, "limit": 24, "total": 999}

    def searchContentPage(self, key, quick, pg="1"):
        return self.searchContent(key, quick, pg)

    def detailContent(self, ids):
        if not ids: return {"list": []}
        vod_id = str(ids[0])
        url = vod_id if vod_id.startswith("http") else self._fix(vod_id)
        html = self._fetch(url)
        if not html: return {"list": []}

        name = ""
        m = _RE_H1.search(html)
        if m: name = self._clean(m.group(1))
        if not name:
            m = re.search(r"<title>(.*?)</title>", html, re.S)
            if m: name = self._clean(m.group(1).split("_")[0].split("-")[0])
        name = name or vod_id

        pic = self.default_pic
        m = _RE_DETAIL_PIC.search(html)
        if m: pic = self._fix(m.group(1))

        content = ""
        m = re.search(r'<span class="data" style="display: none;">([\s\S]*?)</span>', html)
        if m: content = self._clean(m.group(1))
        if not content:
            m = _RE_DESC.search(html)
            if m: content = self._clean(m.group(1))
        content = INTRO_PREFIX + ("\n" + content if content else "")

        actor = ""
        m = _RE_ACTOR.search(html)
        if m: actor = self._clean("".join(re.findall(r'>([^<>]+)</a>', m.group(1))))
        director = ""
        m = _RE_DIRECTOR.search(html)
        if m: director = self._clean("".join(re.findall(r'>([^<>]+)</a>', m.group(1))))

        score = ""
        m = _RE_RATING.search(html)
        if m: score = m.group(1)
        remark = ""
        m = _RE_REMARK.search(html)
        if m: remark = self._clean(m.group(1))

        tab_names = {m.group(1): self._clean(m.group(2)) for m in _RE_LINE_TAB.finditer(html)}
        play_from, play_url = [], []
        for m in _RE_LINE_BLOCK.finditer(html):
            pid = m.group(1)
            eps = []
            for em in _RE_EP.finditer(m.group(0)):
                ep_href = em.group(1).replace("&amp;", "&")
                if ep_href.startswith("/"): ep_href = self.site_url + ep_href
                eps.append("%s$%s" % (self._clean(em.group(2)), ep_href))
            if eps:
                play_from.append(tab_names.get(pid, pid))
                play_url.append("#".join(eps))

        if not play_from: return {"list": []}

        return {"list": [{
            "vod_id": vod_id, "vod_name": name, "vod_pic": pic,
            "vod_content": content, "vod_actor": actor, "vod_director": director,
            "vod_score": score, "vod_remarks": remark or ("%d条线路" % len(play_from)),
            "vod_play_from": "$$$".join(play_from), "vod_play_url": "$$$".join(play_url)
        }]}

    def playerContent(self, flag, id, vipFlags):
        play_page = id if id.startswith("http") else self._fix(id)
        if play_page in self._play_cache: return self._play_cache[play_page]

        html = self._fetch(play_page)
        m = _RE_PLAYER.search(html or "")
        if not m:
            return {"parse": 1, "playUrl": "", "url": play_page, "header": {"User-Agent": UA, "Referer": self.site_url + "/"}}

        try:
            cfg = json.loads(m.group(1))
        except Exception:
            return {"parse": 1, "playUrl": "", "url": play_page, "header": {"User-Agent": UA, "Referer": self.site_url + "/"}}

        url = cfg.get("url") or ""
        if url and cfg.get("encrypt") == 0 and url.startswith("http"):
            res = {"parse": 0, "playUrl": "", "url": url, "header": {"User-Agent": UA, "Referer": self.site_url + "/"}}
            self._play_cache[play_page] = res
            return res

        return {"parse": 1, "playUrl": "", "url": play_page, "header": {"User-Agent": UA, "Referer": self.site_url + "/"}}

    def isVideoFormat(self, url): return ".m3u8" in url or ".mp4" in url
    def manualVideoCheck(self): return False
    def destroy(self): pass
    def close(self): self.destroy()
