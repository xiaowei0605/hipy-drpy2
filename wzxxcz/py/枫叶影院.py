# coding=utf-8
"""
枫叶影院 926dy.com | TVBox Python 爬虫

网站结构:
  - 苹果CMS(maccms) + jufeng 模板，伪静态路由：
      首页            /
      顶级分类        /type/{tid}.html        tid: 1电影 2连续剧 3综艺 4动漫 34短剧
      子分类列表      /sort/{sid}.html
      子分类筛选      /sort/{sid}/by/{排序}/class/{类型}/area/{地区}/year/{年份}/page/{页}.html
                      （顺序取自站点自身筛选导航的真实 href）
      详情            /post/{id}.html
      播放            /watch/{id}-{sid}-{nid}.html
      搜索(列表页)    POST /search/-------------.html   (form: wd=关键词)
      搜索(分页)      /search/{关键词}----------{页}---.html
  - 列表卡片: <li class="item"> … <a href="/post/xx.html" class="thumb" title="…">
                <img class="lazyload" data-original="…" alt="…">
                <span class="state">状态</span> <span class="tip-score">评分</span>
              <h5 class="subject"><a href="/post/xx.html">名称</a></h5>
              <p class="tags">年份 / 地区</p>
  - 详情页线路: <a class="tab-nav">XX线路</a> 与 <div class="rb-item"> 是 **并列独立** 的顺序，
                线路名与实际 sid 并不对应，sid 只能从剧集链接 /watch/{id}-{sid}-{nid}.html 中取。
  - 播放页: var player_aaaa = {...,"encrypt":1,"url":"%68%74%74..."}  →  urlencode 过的 m3u8 直链
                encrypt=1 : unescape(url)
                encrypt=2 : unescape(base64decode(url))
  - m3u8 为多码率 master playlist，子列表是相对路径（2000k/hls/index.m3u8）。
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
                adapter = _rq.adapters.HTTPAdapter(
                    pool_connections=10, pool_maxsize=10, max_retries=0)
                self._session.mount('https://', adapter)
                self._session.mount('http://', adapter)
            return self._session

        def fetch(self, url, headers=None, **kw):
            timeout = kw.pop('timeout', 15)
            method = kw.pop('method', 'get')
            data = kw.pop('data', None)
            allow_redirects = kw.pop('allow_redirects', True)
            if method.lower() == 'post':
                r = self._sess.post(url, headers=headers, timeout=timeout,
                                    data=data, allow_redirects=allow_redirects, **kw)
            else:
                r = self._sess.get(url, headers=headers, timeout=timeout,
                                   allow_redirects=allow_redirects, **kw)
            r.encoding = 'utf-8'
            return r

        def log(self, *a, **kw):
            try:
                print("[fengye]", *a)
            except Exception:
                pass

    Spider = _BaseSpider


HOST = "https://www.926dy.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
DEFAULT_PIC = HOST + "/template/jufeng/img/logo_black.png"

INTRO_PREFIX = "🍊小橙子为您介绍剧情👉请不要相信视频中的广告，以免上当受骗！"

# ---- 顶级分类（取自首页导航真实链接）----
CLASSES = [
    {"type_id": "1",  "type_name": "电影"},
    {"type_id": "2",  "type_name": "连续剧"},
    {"type_id": "3",  "type_name": "综艺"},
    {"type_id": "4",  "type_name": "动漫"},
    {"type_id": "34", "type_name": "短剧"},
]

# 子分类（取自 /type/{tid}.html 页面的真实子分类列表）
SUB_CLASSES = {
    "1":  [("6", "动作片"), ("7", "喜剧片"), ("8", "爱情片"), ("9", "科幻片"),
           ("10", "恐怖片"), ("11", "剧情片"), ("12", "战争片"), ("13", "悬疑片"),
           ("14", "冒险片"), ("15", "奇幻片"), ("16", "惊悚片"), ("17", "动画片"),
           ("18", "纪录片"), ("19", "其他片")],
    "2":  [("20", "国产剧"), ("21", "港台剧"), ("22", "日韩剧"), ("23", "欧美剧"),
           ("24", "海外剧")],
    "3":  [("25", "大陆综艺"), ("26", "日韩综艺"), ("27", "港台综艺"),
           ("28", "欧美综艺"), ("29", "海外综艺")],
    "4":  [("30", "国产动漫"), ("31", "日本动漫"), ("32", "欧美动漫"),
           ("33", "海外动漫")],
    "34": [],
}

# 排序（取自列表页真实排序导航）
SORTS = [("time", "最新"), ("hits", "最热"), ("score", "评分")]

# 分类页筛选词取自各子分类页真实渲染结果；不同子分类可用项不同，
# 这里按顶级分类给出并集，站点对不存在的组合会返回空列表而不会报错。
_CLASS_WORDS = {
    "1": ["喜剧", "爱情", "恐怖", "动作", "科幻", "剧情", "战争", "警匪", "犯罪",
          "动画", "奇幻", "武侠", "冒险", "枪战", "悬疑", "惊悚", "经典", "青春",
          "文艺", "微电影", "古装", "历史", "运动", "农村", "儿童", "网络电影"],
    "2": ["古装", "战争", "青春偶像", "喜剧", "家庭", "犯罪", "动作", "奇幻", "剧情",
          "历史", "谍战", "武侠", "偶像", "悬疑", "都市", "情感", "科幻", "年代",
          "农村", "军旅"],
    "3": ["选秀", "情感", "访谈", "播报", "旅游", "音乐", "美食", "纪实", "曲艺",
          "游戏", "生活", "搞笑", "脱口秀", "真人秀"],
    "4": ["情感", "科幻", "热血", "推理", "搞笑", "冒险", "萝莉", "校园", "动作",
          "恋爱", "亲子", "治愈", "魔幻", "悬疑", "竞技", "青春"],
    "34": ["短剧", "爽文", "穿越", "都市", "古装", "逆袭", "悬疑", "甜宠"],
}

# 地区词（取自真实地区筛选导航，剧集/综艺/动漫与电影用词不同）
_AREAS = {
    "1": ["大陆", "香港", "台湾", "美国", "法国", "英国", "日本", "韩国", "德国",
          "泰国", "印度", "意大利", "西班牙", "加拿大", "其他"],
    "2": ["内地", "韩国", "香港", "台湾", "日本", "美国", "泰国", "英国", "新加坡"],
    "3": ["内地", "港台", "日韩", "欧美"],
    "4": ["国产", "日本", "欧美", "其他"],
    "34": [],
}

_YEARS = [str(y) for y in range(time.localtime().tm_year, 1999, -1)]


def _build_filters():
    filters = {}
    for c in CLASSES:
        tid = c["type_id"]
        sub = SUB_CLASSES.get(tid) or []
        f = [{
            "key": "sort_id", "name": "分类",
            "value": [{"n": "全部", "v": ""}] +
                     [{"n": n, "v": sid} for sid, n in sub],
        }]
        words = _CLASS_WORDS.get(tid) or []
        if words:
            f.append({"key": "class", "name": "类型",
                      "value": [{"n": "全部", "v": ""}] +
                               [{"n": w, "v": w} for w in words]})
        areas = _AREAS.get(tid) or []
        if areas:
            f.append({"key": "area", "name": "地区",
                      "value": [{"n": "全部", "v": ""}] +
                               [{"n": a, "v": a} for a in areas]})
        f.append({"key": "year", "name": "年份",
                  "value": [{"n": "全部", "v": ""}] +
                           [{"n": y, "v": y} for y in _YEARS]})
        f.append({"key": "by", "name": "排序",
                  "value": [{"n": n, "v": v} for v, n in SORTS]})
        filters[tid] = f
    return filters


FILTERS = _build_filters()


# ===================== 正则（全部对应真实源码） =====================
# 列表卡片
_RE_ITEM = re.compile(r'<li class="item">([\s\S]*?)</li>', re.I)
_RE_ITEM_HREF = re.compile(r'<a\s+href="(/post/\d+\.html)"[^>]*class="thumb"[^>]*>', re.I)
_RE_ITEM_TITLE = re.compile(r'class="thumb"[^>]*title="([^"]*)"', re.I)
_RE_ITEM_IMG = re.compile(r'<img[^>]*?(?:data-original|data-src|src)="([^"]+)"', re.I)
_RE_ITEM_ALT = re.compile(r'<img[^>]*?alt="([^"]*)"', re.I)
_RE_ITEM_STATE = re.compile(r'<span class="state">([^<]*)</span>', re.I)
_RE_ITEM_SCORE = re.compile(r'<span class="tip-score">([^<]*)</span>', re.I)
_RE_ITEM_TAGS = re.compile(r'<p class="tags">([^<]*)</p>', re.I)
_RE_ITEM_SUBJECT = re.compile(r'<h5 class="subject">\s*<a[^>]*>([^<]*)</a>', re.I)

# 分页
_RE_PAGE_CUR = re.compile(r'mac_page_current"\)\.text\((\d+)\)', re.I)
_RE_PAGE_TOTAL = re.compile(r'mac_page_total"\)\.text\((\d+)\)', re.I)

# 搜索关键词回显
_RE_SEARCH_ECHO = re.compile(
    r'搜索到与"<span[^>]*>([^<]*)</span>"相关的', re.I)

# 详情页
_RE_H1 = re.compile(r'<h1[^>]*class="article-subject-m"[^>]*>([\s\S]*?)</h1>', re.I)
_RE_COVER = re.compile(r'<img[^>]*id="movie_thumb"[^>]*>', re.I)
_RE_LABEL = re.compile(
    r'<p><label>([^<：:]+)[：:]</label><span>([\s\S]*?)</span></p>', re.I)
_RE_SUMMARY = re.compile(
    r'<div class="summary-con[^"]*">\s*<h2>详情介绍</h2>\s*'
    r'<div class="box">\s*<div[^>]*>([\s\S]*?)</div>\s*</div>\s*</div>', re.I)

# 线路名 + 剧集块（顺序各自独立，不能按索引配对）
_RE_LINE_NAV = re.compile(r'<a href="javascript:;" class="tab-nav">([^<]+)</a>', re.I)
_RE_RB_ITEM = re.compile(r'<div class="rb-item"[^>]*>([\s\S]*?)</ul>', re.I)
_RE_EPISODE = re.compile(
    r'<li>\s*<a\s+href="(/watch/(\d+)-(\d+)-(\d+)\.html)"[^>]*>([\s\S]*?)</a>\s*</li>', re.I)

# 播放页
_RE_PLAYER = re.compile(r'var\s+player_aaaa\s*=\s*(\{[\s\S]*?\})\s*</script>', re.I)
_RE_OG_PIC = re.compile(r'<meta\s+property="og:image"\s+content="([^"]+)"', re.I)


class Spider(Spider):

    def getName(self):
        return "枫叶影院"

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
            "Upgrade-Insecure-Requests": "1",
        }
        self.default_pic = DEFAULT_PIC
        self._play_cache = {}
        self.log("init: site=%s" % self.site_url)

    # -------------------- 基础工具 --------------------
    def _fetch(self, url, timeout=20, headers=None, method="get", data=None,
               allow_redirects=True):
        """返回 (text, ok)。ok=False 表示内核未真正执行 POST（退化成 GET）。"""
        try:
            h = dict(self.headers)
            if method.lower() == "post":
                h["Content-Type"] = "application/x-www-form-urlencoded"
                h["Origin"] = self.site_url
            if headers:
                h.update(headers)
            rsp = self.fetch(url, headers=h, timeout=timeout, method=method,
                             data=data, allow_redirects=allow_redirects)
            if hasattr(rsp, "text"):
                text = rsp.text or ""
            elif hasattr(rsp, "content"):
                text = rsp.content.decode("utf-8", "ignore")
            else:
                text = str(rsp)
            return (text or ""), True
        except TypeError:
            # 内核 fetch 不支持 method/data 参数：只能退化成 GET，
            # 但本站搜索必须用 POST，GET 会被重写到首页，需由调用方判空。
            self.log("内核不支持 POST fetch，本次请求退化为 GET: %s" % url)
            try:
                rsp = self.fetch(url, headers=headers or self.headers, timeout=timeout)
                return (getattr(rsp, "text", "") or ""), False
            except Exception as e:
                self.log("fetch#2 FAIL %s -> %s" % (url, e))
                return "", False
        except Exception as e:
            self.log("fetch FAIL %s -> %s" % (url, e))
            return "", True

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
             .replace("\u200e", "").replace("&amp;", "&")
             .replace("&quot;", '"').replace("&#39;", "'")
             .replace("&lt;", "<").replace("&gt;", ">"))
        s = re.sub(r"[ \t\r\f\v]+", " ", s)
        s = re.sub(r"\n{2,}", "\n", s)
        return s.strip()

    # -------------------- 列表解析 --------------------
    def _extract_videos(self, html):
        videos = []
        seen = set()
        if not html:
            return videos

        for m in _RE_ITEM.finditer(html):
            blk = m.group(1)

            mh = _RE_ITEM_HREF.search(blk)
            if not mh:
                continue
            href = mh.group(1)
            if href in seen:
                continue
            seen.add(href)

            name = ""
            mt = _RE_ITEM_TITLE.search(blk)
            if mt:
                name = self._clean(mt.group(1))
            if not name:
                ms = _RE_ITEM_SUBJECT.search(blk)
                if ms:
                    name = self._clean(ms.group(1))
            if not name:
                ma = _RE_ITEM_ALT.search(blk)
                if ma:
                    name = self._clean(ma.group(1))

            pic = ""
            mi = _RE_ITEM_IMG.search(blk)
            if mi:
                pic = self._fix_url(mi.group(1))

            remarks = ""
            mst = _RE_ITEM_STATE.search(blk)
            if mst:
                remarks = self._clean(mst.group(1))
            msc = _RE_ITEM_SCORE.search(blk)
            if msc:
                sc = self._clean(msc.group(1))
                remarks = (sc + "分 " + remarks).strip() if sc else remarks

            if not remarks:
                mg = _RE_ITEM_TAGS.search(blk)
                if mg:
                    remarks = self._clean(mg.group(1))

            videos.append({
                "vod_id":      href,
                "vod_name":    name or href,
                "vod_pic":     pic or self.default_pic,
                "vod_remarks": remarks,
            })
        return videos

    def _page_info(self, html, page):
        cur = page
        total = 1
        try:
            m = _RE_PAGE_CUR.search(html or "")
            if m:
                cur = int(m.group(1))
            m = _RE_PAGE_TOTAL.search(html or "")
            if m:
                total = int(m.group(1))
        except Exception:
            pass
        # 兜底：从「..123页」或末页链接里取总页数
        if total <= 1 and html:
            m = re.search(r'\.\.(\d+)页', html)
            if m:
                total = int(m.group(1))
            else:
                m = re.search(r'/page/(\d+)\.html"[^>]*title="末页"', html)
                if m:
                    total = int(m.group(1))
        return cur, max(total, 1)

    # -------------------- 首页 --------------------
    def homeContent(self, filter=False):
        return {"class": CLASSES, "filters": FILTERS}

    def homeVideoContent(self):
        html, _ = self._fetch(self.site_url + "/")
        self.log("home HTML 长度: %d" % len(html))
        videos = self._extract_videos(html)
        self.log("home 解析: %d 条" % len(videos))
        return {"list": videos}

    # -------------------- 分类 --------------------
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
        if not isinstance(extend, dict):
            extend = {}

        def val(k):
            v = extend.get(k)
            if isinstance(v, list):
                v = v[0] if v else ""
            if v in ("", None, "全部"):
                return ""
            return str(v).strip()

        sort_id = val("sort_id")
        cls = val("class")
        area = val("area")
        year = val("year")
        by = val("by") or "time"

        # 站点自身构造顺序（取自列表页筛选导航的真实链接）:
        #   /sort/{sid}/by/{sort}/class/{x}/area/{y}/year/{z}/page/{p}.html
        if sort_id and sort_id.isdigit():
            url = "%s/sort/%s" % (self.site_url, sort_id)
        elif str(tid).isdigit():
            url = "%s/sort/%s" % (self.site_url, tid)
        else:
            url = self.site_url + "/"

        if by and by != "time":
            url += "/by/" + by
        if cls:
            url += "/class/" + urllib.parse.quote(cls)
        if area:
            url += "/area/" + urllib.parse.quote(area)
        if year:
            url += "/year/" + urllib.parse.quote(year)
        if page > 1:
            url += "/page/%d" % page
        url += ".html"

        self.log("category: %s" % url)
        html, _ = self._fetch(url)
        self.log("  HTML 长度: %d" % len(html))

        videos = self._extract_videos(html)
        cur, total = self._page_info(html, page)
        self.log("  最终: %d 条, 页码 %d/%d" % (len(videos), cur, total))

        return {
            "list": videos,
            "page": cur,
            "pagecount": total,
            "limit": len(videos) if videos else 24,
            "total": total * 24,
        }

    # -------------------- 搜索 --------------------
    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg) if pg else 1
        except Exception:
            page = 1

        kw = urllib.parse.quote(key)
        if page <= 1:
            # 站点搜索表单: <form method="post" action="/search/-------------.html"><input name="wd">
            url = self.site_url + "/search/-------------.html"
            html, post_ok = self._fetch(url, method="post",
                                        data={"wd": key},
                                        headers={"Referer": self.site_url + "/"})
            # 校验：搜索成功后页面会回显关键词
            # <h4>搜索到与"<span>关键词</span>"相关的…</h4>；
            # 若内核静默吞掉 POST 参数（实际发 GET），回显为空但不是报错，
            # 此时返回的是全站内容，必须放弃，否则会把热门列表当成搜索结果。
            if not self._search_echo_ok(html, key):
                self.log("搜索关键词未被站点接收（内核可能未执行 POST），返回空结果")
                return {"list": [], "page": 1, "pagecount": 1,
                        "limit": 0, "total": 0}
        else:
            # 真实分页格式: /search/{关键词}----------{页}---.html
            url = "%s/search/%s----------%d---.html" % (self.site_url, kw, page)
            html, _ = self._fetch(url)
            if not self._search_echo_ok(html, key):
                self.log("搜索分页返回异常，返回空结果")
                return {"list": [], "page": page, "pagecount": page,
                        "limit": 0, "total": 0}

        self.log("search: %s (page=%d) HTML=%d" % (key, page, len(html)))
        videos = self._extract_videos(html)
        cur, total = self._page_info(html, page)
        if total <= 1 and page > 1:
            total = page
        return {
            "list": videos,
            "page": cur,
            "pagecount": total,
            "limit": len(videos) if videos else 24,
            "total": total * 24,
        }

    def _search_echo_ok(self, html, key):
        """检查搜索页是否回显了关键词（说明搜索条件真正生效）。
        真实源码：<h4 class="theme">搜索到与"<span>关键词</span>"相关的
                  "<span class="mac_record_total"></span>"条结果</h4>
        """
        if not html:
            return False
        m = _RE_SEARCH_ECHO.search(html)
        if not m:
            return False
        return self._clean(m.group(1)).strip() != ""

    def searchContentPage(self, key, quick, pg="1"):
        return self.searchContent(key, quick, pg)

    # -------------------- 详情 --------------------
    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vod_id = str(ids[0])
        url = vod_id if vod_id.startswith("http") else self._fix_url(vod_id)
        self.log("detail: %s" % url)

        html, _ = self._fetch(url)
        self.log("  HTML 长度: %d" % len(html))
        if not html:
            return {"list": []}

        # 名称
        name = ""
        m = _RE_H1.search(html)
        if m:
            name = self._clean(m.group(1))
        if not name:
            m = re.search(r'<meta\s+property="og:title"\s+content="《?([^》"]+)》?', html)
            if m:
                name = self._clean(m.group(1))
        if not name:
            m = re.search(r"<title>(.*?)</title>", html, re.S)
            if m:
                name = self._clean(m.group(1).split("_")[0]).strip("《》")
        name = name or vod_id

        # 封面
        pic = self.default_pic
        m = _RE_COVER.search(html)
        if m:
            mi = re.search(r'(?:data-original|data-src|src)="([^"]+)"', m.group(0))
            if mi:
                pic = self._fix_url(mi.group(1))
        if pic == self.default_pic:
            m = _RE_OG_PIC.search(html)
            if m:
                pic = self._fix_url(m.group(1))

        # 字段（类型/导演/主演/年份/地区/资源/豆瓣）
        info = {}
        for k, v in _RE_LABEL.findall(html):
            k = self._clean(k).strip("：: ")
            if k and k not in info:
                info[k] = self._clean(v)

        # 简介（<div class="summary-con clearfix detail"><h2>详情介绍</h2>
        #       <div class="box"><div style="text-indent: 28px;">正文</div></div></div>）
        content = ""
        m = _RE_SUMMARY.search(html)
        if m:
            content = self._clean(m.group(1))
        if not content:
            m = re.search(r'<div class="summary-con[^"]*">([\s\S]*?)</section>', html, re.I)
            if m:
                box = m.group(1)
                mb = re.search(r'<div class="box">([\s\S]*?)</div>\s*</div>', box, re.I)
                content = self._clean(mb.group(1) if mb else box)
        if not content:
            m = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html, re.I)
            if m:
                content = self._clean(m.group(1))
        content = (INTRO_PREFIX + "\n" + content) if content else INTRO_PREFIX

        # 线路名
        line_names = [self._clean(x) for x in _RE_LINE_NAV.findall(html)]

        # 剧集：按 sid 分组（不能依赖 rb-item 与线路名的先后顺序）
        groups = {}
        order = []
        for blk in _RE_RB_ITEM.findall(html):
            for m in _RE_EPISODE.finditer(blk):
                href, pid, sid, nid, ep = m.groups()
                ep_name = self._clean(ep) or ("第%s集" % nid)
                if sid not in groups:
                    groups[sid] = []
                    order.append(sid)
                if href in [h for _, h in groups[sid]]:
                    continue
                groups[sid].append((ep_name, self._fix_url(href)))

        self.log("  线路名: %s" % line_names)
        self.log("  剧集: %s" % {k: len(v) for k, v in groups.items()})
        if not groups:
            return {"list": []}

        def sort_key(sid):
            try:
                return int(sid)
            except Exception:
                return 999

        play_from = []
        play_url = []
        idx = 0
        for sid in sorted(groups.keys(), key=sort_key):
            eps = groups[sid]
            if not eps:
                continue
            # 优先用页面真实线路名（顺序一致时），否则用「第N线路」
            if len(line_names) == len(groups) and idx < len(line_names):
                alias = line_names[idx]
            else:
                alias = "线路%s" % sid
            if alias in play_from:
                alias = "%s-%s" % (alias, sid)
            play_from.append(alias)
            play_url.append("#".join("%s$%s" % (n, h) for n, h in eps))
            idx += 1

        year = info.get("年份", "")
        area = info.get("地区", "")
        remark_bits = [x for x in (year, area, info.get("资源", "")) if x]

        return {"list": [{
            "vod_id":       vod_id,
            "vod_name":     name,
            "vod_pic":      pic,
            "vod_content":  content,
            "vod_actor":    info.get("主演", ""),
            "vod_director": info.get("导演", ""),
            "vod_year":     year,
            "vod_area":     area,
            "vod_lang":     "",
            "vod_score":    info.get("豆瓣", ""),
            "vod_remarks":  " ".join(remark_bits) or ("%d条线路" % len(play_from)),
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url":  "$$$".join(play_url),
        }]}

    # -------------------- 播放 --------------------
    def playerContent(self, flag, id, vipFlags):
        play_page = id if str(id).startswith("http") else self._fix_url(id)
        self.log("player: %s" % play_page)

        now = int(time.time())
        if play_page in self._play_cache:
            ts, res = self._play_cache[play_page]
            if now - ts < 600:
                return res

        html, _ = self._fetch(play_page, headers={"Referer": self.site_url + "/"})
        self.log("  play HTML: %d" % len(html))

        play_url = self._parse_player_url(html)
        self.log("  play_url: %s" % (play_url[:200] if play_url else "EMPTY"))

        if play_url:
            # master playlist 有多码率子列表，直接交给播放器也可播；
            # 这里尝试解析出最高码率子列表，失败则保留 master 原地址。
            final_url = self._pick_best_variant(play_url, referer=play_page) or play_url
            origin = ""
            try:
                p = urllib.parse.urlparse(final_url)
                origin = "%s://%s/" % (p.scheme, p.netloc)
            except Exception:
                pass

            res = {
                "parse": 0,
                "playUrl": "",
                "url": final_url,
                "header": {
                    "User-Agent": UA,
                    "Referer": origin or (self.site_url + "/"),
                },
            }
            self._play_cache[play_page] = (now, res)
            self.log("  => 直链: %s" % final_url[:200])
            return res

        # 兜底：交给 TVBox 嗅探
        res = {"parse": 1, "playUrl": "", "url": play_page,
               "header": {"User-Agent": UA, "Referer": self.site_url + "/"}}
        self._play_cache[play_page] = (now, res)
        return res

    def _parse_player_url(self, html):
        """解析 var player_aaaa 中的 url。
        encrypt=1 -> unescape(url)
        encrypt=2 -> unescape(base64decode(url))
        其余       -> 原样
        """
        if not html:
            return ""
        m = _RE_PLAYER.search(html)
        if not m:
            self.log("  未找到 player_aaaa")
            return ""
        try:
            data = json.loads(m.group(1))
        except Exception:
            self.log("  player_aaaa JSON 解析失败")
            return ""

        url = str(data.get("url") or "").strip()
        if not url:
            return ""

        enc = str(data.get("encrypt", "0"))
        try:
            if enc == "1":
                url = urllib.parse.unquote(url)
            elif enc == "2":
                raw = base64.b64decode(url + "=" * (-len(url) % 4)).decode("utf-8", "ignore")
                url = urllib.parse.unquote(raw)
        except Exception as e:
            self.log("  解码失败: %s" % e)

        url = url.replace("\\/", "/").replace("&amp;", "&").strip()
        self.log("  from=%s encrypt=%s" % (data.get("from"), enc))
        return url

    def _pick_best_variant(self, m3u8_url, referer=None):
        """master playlist 取带宽最高的子列表；非 master 直接返回 None。"""
        if ".m3u8" not in m3u8_url.lower():
            return ""
        text, _ = self._fetch(m3u8_url, headers={
            "User-Agent": UA,
            "Referer": referer or (self.site_url + "/"),
            "Accept": "*/*",
        }, timeout=15)
        if "#EXTM3U" not in text or "#EXT-X-STREAM-INF" not in text:
            return ""

        lines = [ln.strip() for ln in text.split("\n")]
        best = None
        best_bw = -1
        for i, line in enumerate(lines):
            if not line.startswith("#EXT-X-STREAM-INF"):
                continue
            mb = re.search(r"BANDWIDTH=(\d+)", line)
            bw = int(mb.group(1)) if mb else 0
            nxt = ""
            for j in range(i + 1, len(lines)):
                if lines[j] and not lines[j].startswith("#"):
                    nxt = lines[j]
                    break
            if not nxt:
                continue
            full = urllib.parse.urljoin(m3u8_url, nxt)
            if bw >= best_bw:
                best_bw = bw
                best = full

        if best:
            self.log("  子 m3u8: %s" % best[:160])
            return best
        return ""

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
        u = (url or "").lower()
        return ".m3u8" in u or ".mp4" in u

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def close(self):
        self.destroy()
