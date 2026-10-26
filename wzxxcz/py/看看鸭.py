# coding=utf-8
"""
看看鸭 kankanya.cc | TVBox Python 爬虫 
关键:
  - 破解服务端人机验证 (encrypt + robot.php 换取 Cookie)
  - 解析 player_aaaa -> POST /kkyplayer/api.php -> 自定义 Base64 解码真实直链
  - 支持 分类/筛选(地区·类型·语言·年份·排序)/搜索/多播放源
"""
import re
import sys
import json
import time
import base64
import hashlib
import random
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

        def post(self, url, data=None, headers=None, **kw):
            timeout = kw.pop('timeout', 15)
            return self._sess.post(url, data=data, headers=headers,
                                   timeout=timeout, **kw)

        def log(self, *a, **kw):
            try:
                print("[kankanya]", *a)
            except Exception:
                pass

    Spider = _BaseSpider


# 域名请根据实际情况修改，目前 HTML 里识别到的是 .cc
HOST = "https://www.kankanya.cc"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
DEFAULT_PIC = HOST + "/mxtheme/images/logo.png"

INTRO_PREFIX = "🍊小橙子为您介绍剧情👉请不要相信视频中的广告，以免上当受骗！"

CLASSES = [
    {"type_id": "dianying", "type_name": "电影"},
    {"type_id": "juji",     "type_name": "剧集"},
    {"type_id": "zongyi",   "type_name": "综艺"},
    {"type_id": "dongman",  "type_name": "动漫"},
]

_SORTS = [{"n": "最新上线", "v": "time"},
          {"n": "人气最高", "v": "hits"},
          {"n": "评分最高", "v": "score"}]
_YEARS = [{"n": "全部", "v": ""}] + \
         [{"n": str(y), "v": str(y)} for y in range(2026, 1999, -1)]
_AREAS = [
    {"n": "全部", "v": ""},
    {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"},
    {"n": "台湾", "v": "台湾"}, {"n": "美国", "v": "美国"},
    {"n": "法国", "v": "法国"}, {"n": "英国", "v": "英国"},
    {"n": "日本", "v": "日本"}, {"n": "韩国", "v": "韩国"},
    {"n": "德国", "v": "德国"}, {"n": "泰国", "v": "泰国"},
    {"n": "印度", "v": "印度"}, {"n": "意大利", "v": "意大利"},
    {"n": "西班牙", "v": "西班牙"}, {"n": "加拿大", "v": "加拿大"},
    {"n": "其他", "v": "其他"},
]
_LANGS = [{"n": "全部", "v": ""}, {"n": "国语", "v": "国语"},
          {"n": "英语", "v": "英语"}, {"n": "粤语", "v": "粤语"},
          {"n": "闽南语", "v": "闽南语"}, {"n": "韩语", "v": "韩语"},
          {"n": "日语", "v": "日语"}, {"n": "法语", "v": "法语"},
          {"n": "德语", "v": "德语"}, {"n": "其它", "v": "其它"}]

_FILTERS_MAP = {
    "dianying": ["全部", "喜剧", "爱情", "恐怖", "动作", "科幻", "剧情", "战争",
                 "警匪", "犯罪", "动画", "奇幻", "武侠", "冒险", "枪战", "恐怖",
                 "悬疑", "惊悚", "经典", "青春", "文艺", "微电影", "古装", "历史",
                 "运动", "农村", "儿童", "网络电影"],
    "juji":     ["全部", "古装", "战争", "青春", "偶像", "喜剧", "家庭", "犯罪",
                 "动作", "奇幻", "剧情", "历史", "经典", "乡村", "情景", "商战",
                 "网剧", "其他"],
    "zongyi":   ["全部", "选秀", "情感", "访谈", "播报", "旅游", "音乐", "美食",
                 "纪实", "曲艺", "生活", "游戏", "求职", "财经", "综艺"],
    "dongman":  ["全部", "情感", "科幻", "热血", "推理", "搞笑", "冒险", "萝莉",
                 "校园", "动作", "机战", "运动", "战争", "少年", "少女", "社会",
                 "原创", "亲子", "益智", "励志", "其他"],
}

FILTERS = {}
for c in CLASSES:
    tid = c["type_id"]
    FILTERS[tid] = [
        {"key": "class", "name": "类型",
         "value": [{"n": x, "v": "" if x == "全部" else x}
                   for x in _FILTERS_MAP.get(tid, ["全部"])]},
        {"key": "area", "name": "地区", "value": _AREAS},
        {"key": "lang", "name": "语言", "value": _LANGS},
        {"key": "year", "name": "年份", "value": _YEARS},
        {"key": "by", "name": "排序", "value": _SORTS},
    ]


# ===================== 正则 =====================
# 首页/分类/搜索卡片 (对结构做最大兼容，防止空白)
_RE_CARD = re.compile(
    r'<a\s+[^>]*?href="(/detail/[^"]+?\.html)"'
    r'[\s\S]{0,1000}?<img[^>]*?(?:data-original|src)="([^"]+)"'
    r'[\s\S]{0,500}?title="([^"]+)"',
    re.S | re.I)
_RE_HREF = re.compile(r'href="(/detail/[^"]+?\.html)"', re.I)
# 兜底解析: 卡片窗口内的标题 / 图片 / alt
_RE_CARD_TITLE = re.compile(r'title="([^"]+)"')
_RE_CARD_PIC = re.compile(r'data-original="([^"]+?)"')
_RE_CARD_ALT = re.compile(r'alt="([^"]{1,120})"')
_RE_IMG = re.compile(
    r'(?:data-original|src)="([^"]*(?:upload/photo|\.jpg|\.png|\.webp)[^"]*)"',
    re.I)

# 详情页
_RE_H1 = re.compile(r'<h1[^>]*>([\s\S]*?)</h1>', re.I)
_RE_TITLE_TAG = re.compile(r'<title>(.*?)</title>', re.S)
_RE_PIC = re.compile(
    r'(?:data-original|src)="(https?://[^"]*(?:upload/photo)[^"]*)"', re.I)
_RE_INTRO = re.compile(
    r'module-info-introduction-content[^>]*>\s*<p>([\s\S]*?)</p>', re.S | re.I)
_RE_INTRO_DIV = re.compile(
    r'module-info-introduction[^>]*>\s*<div[^>]*>([\s\S]*?)</div>', re.S | re.I)
_RE_META_DESC = re.compile(
    r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)["\']',
    re.I)
_RE_INFO_ITEM = re.compile(
    r'module-info-item-title">([^：<]{1,6})：</span>\s*'
    r'<div[^>]*>([\s\S]*?)</div>\s*</div>', re.S | re.I)
_RE_SCORE = re.compile(r'([0-9]\.[0-9])\s*分', re.I)
_RE_REMARK = re.compile(r'module-info-tag-link[\s\S]{0,200}?>([^<]+)<', re.I)

# 播放源标签(顺序) 与 剧集面板
_RE_SOURCE = re.compile(r'data-dropdown-value="([^"]+)"')
_RE_EPISODE = re.compile(
    r'<a\s+class="module-play-list-link"\s+href="(/play/[^"]+\.html)"'
    r'[^>]*>([\s\S]*?)</a>', re.S | re.I)
_RE_EP_SPAN = re.compile(r'<span[^>]*>([^<]*)</span>', re.I)
_RE_PLAY_SID = re.compile(r'/play/([^-]+)-(\d+)-(\d+)\.html')

# 播放页 player_aaaa
_RE_PLAYER = re.compile(r'var\s+player_aaaa\s*=\s*(\{.*?\})\s*</script>', re.S)

# 人机验证挑战页特征
_CHALLENGE_KEY = "防火墙"
_RE_TOKEN = re.compile(r'var\s+token\s*=\s*encrypt\("([^"]+)"\)')

# 自定义编码表 (与站点 JS encrypt/decrypt 一致, 62 字符)
_CODE_TABLE = "PXhw7UT1B0a9kQDKZsjIASmOezxYG4CHo5Jyfg2b8FLpEvRr3WtVnlqMidu6cN"


def _custom_encode(s):
    """复刻站点 JS encrypt(): 每字符两侧夹随机字符后整体 btoa"""
    out = ""
    for ch in s:
        i = _CODE_TABLE.find(ch)
        code = _CODE_TABLE[(i + 3) % 62] if i >= 0 else ch
        out += (_CODE_TABLE[random.randrange(62)] + code +
                _CODE_TABLE[random.randrange(62)])
    return base64.b64encode(out.encode("latin-1")).decode()


def _custom_decode(s):
    """复刻站点 Decode2: atob 后每 3 位取 1 位, 表内偏移 -3"""
    s = base64.b64decode(s + "=" * ((4 - len(s) % 4) % 4)).decode("latin-1")
    out = ""
    for i in range(1, len(s), 3):
        idx = _CODE_TABLE.find(s[i])
        out += s[i] if idx < 0 else _CODE_TABLE[(idx - 3) % 62]
    return out


def _decode1(s):
    """复刻站点 Decode1 (urlmode=1):
    b64decode -> XOR md5("test") 十六进制串 -> b64decode ->
    "字母表1b64/字母表2b64/密文b64", 每字符 char -> a1[a2.index(char)]"""
    raw = base64.b64decode(s + "=" * ((4 - len(s) % 4) % 4))
    key = hashlib.md5(b"test").hexdigest().encode()
    xor = bytes(c ^ key[i % len(key)] for i, c in enumerate(raw))
    mid = base64.b64decode(xor).decode("utf-8", "replace")
    p1, p2, p3 = mid.split("/")
    a1 = json.loads(base64.b64decode(p1 + "=" * ((4 - len(p1) % 4) % 4)))
    a2 = json.loads(base64.b64decode(p2 + "=" * ((4 - len(p2) % 4) % 4)))
    body = base64.b64decode(
        p3 + "=" * ((4 - len(p3) % 4) % 4)).decode("utf-8", "replace")
    table = {}
    for c in a2:
        if c not in table:
            table[c] = a1[a2.index(c)]
    return "".join(table.get(c, c) for c in body)


class Spider(Spider):

    def getName(self):
        return "看看鸭"

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
        self._warmed = False
        self.log("init: site=%s" % self.site_url)

    # -------- 人机验证 --------
    def _pass_challenge(self, url):
        """遇到人机验证时, 复刻 JS: encrypt(location.href) + token POST robot.php"""
        try:
            # 关键修改: 必须使用同一个 Session 去请求，这样下发的 Cookie 才能保留下来
            rsp = self._sess.get(url, headers=self.headers, timeout=20, allow_redirects=True)
            text = rsp.text or ""
            
            if _CHALLENGE_KEY not in text:
                return text
                
            self.log("⚠️ 人机验证, 正在破解...")
            for attempt in range(3):
                m = _RE_TOKEN.search(text)
                token = m.group(1) if m else str(int(time.time()))
                
                # 复用 Session 发送验证，自动接管 Cookie
                r = self._sess.post(self.site_url + "/robot.php",
                          data={"value": _custom_encode(url),
                                "token": _custom_encode(token)},
                          headers=dict(self.headers,
                                       **{"Content-Type":
                                          "application/x-www-form-urlencoded",
                                          "Referer": url}), timeout=20)
                                          
                if r.status_code == 200 and _CHALLENGE_KEY not in r.text:
                    self.log(f"✅ 验证通过, Cookie获取成功")
                    # 破解成功后，再次请求真实页面
                    rsp2 = self._sess.get(url, headers=self.headers, timeout=20, allow_redirects=True)
                    return rsp2.text or ""
                else:
                    self.log(f"⚠️ 第{attempt+1}次验证失败, 尝试重试...")
                    time.sleep(2)
            
            return text
        except Exception as e:
            self.log("fetch FAIL %s -> %s" % (url, e))
            return ""

    def _fetch(self, url, timeout=30):
        if not self._warmed:
            try:
                self._pass_challenge(self.site_url + "/")
                self._warmed = True
            except Exception:
                pass
        return self._pass_challenge(url)

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

    # -------- 列表解析 --------
    def _extract_videos(self, html):
        videos = []
        seen = set()
        if not html:
            self.log("  HTML 为空")
            return videos

        matches = _RE_CARD.findall(html)
        for href, pic, alt in matches:
            href = href.replace("&amp;", "&")
            if href in seen:
                continue
            seen.add(href)
            videos.append({
                "vod_id": href,
                "vod_name": self._clean(alt)[:100],
                "vod_pic": self._fix_url(pic) or self.default_pic,
                "vod_remarks": "",
            })
        if videos:
            return videos

        hrefs = _RE_HREF.findall(html)
        imgs = _RE_IMG.findall(html)
        for i, href in enumerate(hrefs):
            if href in seen:
                continue
            seen.add(href)
            alt, pic = "", ""
            # 在 href 位置向后的小窗口内找标题(strong)与图片
            pos = html.find('href="%s"' % href)
            if pos >= 0:
                win = html[pos:pos + 2500]
                ms = _RE_CARD_TITLE.search(win)
                if ms:
                    alt = ms.group(1)
                if not pic:
                    mp = _RE_CARD_PIC.search(win)
                    if mp:
                        pic = mp.group(1)
                if not alt:
                    ma = _RE_CARD_ALT.search(win)
                    if ma:
                        alt = ma.group(1)
            if i < len(imgs) and not pic:
                pic = imgs[i]
            videos.append({
                "vod_id": href,
                "vod_name": (href.split("/")[-1].split(".")[0]
                             if not alt else self._clean(alt)[:100]),
                "vod_pic": self._fix_url(pic) or self.default_pic,
                "vod_remarks": "",
            })
        return videos

    def _page_count(self, html):
        """匹配 /show/xxx-----N---YYYY.html 或 /show/xxx-----N---.html"""
        if not html:
            return 1
        pages = re.findall(r'/show/[^"]*?-(\d+)---\d*\.html', html)
        if pages:
            try:
                return max(int(p) for p in pages)
            except Exception:
                pass
        return 1

    # -------- TVBox 接口 --------
    def homeContent(self, filter=False):
        return {"class": CLASSES, "filters": FILTERS}

    def homeVideoContent(self):
        html = self._fetch(self.site_url + "/")
        self.log("home HTML 长度: %d" % len(html))
        return {"list": self._extract_videos(html)}

    def _build_show_url(self, tid, pg, ext):
        """
        严格硬编码替换真实格式:
        /show/{tid}-{area}-{by}-{class}-{lang}-{letter}-----{pg}---{year}.html
        """
        area = urllib.parse.quote(str(ext.get("area", ""))) if ext.get("area") else ""
        by = str(ext.get("by", "")) if ext.get("by") else ""
        cls = urllib.parse.quote(str(ext.get("class", ""))) if ext.get("class") else ""
        lang = urllib.parse.quote(str(ext.get("lang", ""))) if ext.get("lang") else ""
        letter = str(ext.get("letter", "")) if ext.get("letter") else ""
        page_str = str(pg) if pg and str(pg) != "1" else ""
        year = str(ext.get("year", "")) if ext.get("year") else ""
        
        # 注意这里不是用 join，而是完全按照 MacCMS 的空缺占位符补齐，防止长度错乱
        url = f"{self.site_url}/show/{tid}-{area}-{by}-{cls}-{lang}-{letter}-----{page_str}---{year}.html"
        return url

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
                extend.pop(k, None)

        url = self._build_show_url(tid, page, extend)
        self.log("category: %s" % url)
        html = self._fetch(url)
        self.log("  HTML 长度: %d" % len(html))

        videos = self._extract_videos(html)
        pagecount = self._page_count(html)
        self.log("  最终: %d 条, 总页数: %d" % (len(videos), pagecount))

        return {
            "list": videos, "page": page, "pagecount": pagecount,
            "limit": 24, "total": pagecount * 24,
        }

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        url = ("%s/search/-------------.html?wd=%s&page=%d"
               % (self.site_url, urllib.parse.quote(key), page))
        self.log("search: %s" % url)
        html = self._fetch(url)
        self.log("  HTML 长度: %d" % len(html))
        videos = self._extract_videos(html)
        return {
            "list": videos, "page": page,
            "pagecount": 9999 if videos else 1,
            "limit": 24, "total": 999,
        }

    def searchContentPage(self, key, quick, pg="1"):
        return self.searchContent(key, quick, pg)

    # -------- 详情 --------
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

        # 标题
        name = ""
        m = _RE_H1.search(html)
        if m:
            name = self._clean(m.group(1))
        if not name:
            m = _RE_TITLE_TAG.search(html)
            if m:
                name = self._clean(m.group(1).split("_")[0].split("-")[0])
        name = re.sub(r"\s*[(（]\d{4}[)）]\s*$", "", name).strip() or vod_id

        # 封面
        pic = self.default_pic
        m = _RE_PIC.search(html)
        if m:
            pic = self._fix_url(m.group(1))

        # 简介
        content = ""
        for rx in (_RE_INTRO, _RE_INTRO_DIV, _RE_META_DESC):
            m = rx.search(html)
            if m:
                content = self._clean(m.group(1))
                if content:
                    break
        content = (INTRO_PREFIX + "\n" + content) if content else INTRO_PREFIX

        # 元信息(导演/主演/年份/地区/类型...)
        meta = {}
        for title, body in _RE_INFO_ITEM.findall(html):
            meta[title.strip()] = self._clean(body)

        director = meta.get("导演", "")
        actor = meta.get("主演", "") or meta.get("声优", "")
        actor = re.sub(r"\s*,\s*", ", ", actor)
        area = meta.get("地区", "")
        year = meta.get("年份", "") or meta.get("上映", "")
        vtype = meta.get("类型", "")

        score = ""
        m = _RE_SCORE.search(html)
        if m:
            score = m.group(1)

        remarks = " ".join(x for x in (vtype, year, area) if x)

        # ===== 剧集提取(多播放源) =====
        sources = _RE_SOURCE.findall(html)  # data-dropdown-value 顺序即面板顺序
        panels = {}   # sid -> [(name, href)]
        panel_order = []
        for ep_href, ep_inner in _RE_EPISODE.findall(html):
            mh = _RE_PLAY_SID.search(ep_href)
            if not mh:
                continue
            sid = mh.group(2)
            if sid not in panels:
                panels[sid] = []
                panel_order.append(sid)
            mt = _RE_EP_SPAN.search(ep_inner)
            ep_name = self._clean(mt.group(1)) if mt else ""
            if not ep_name:
                ep_name = "第%s集" % (len(panels[sid]) + 1)
            panels[sid].append((ep_name, ep_href))

        # 源名与面板按顺序对齐
        play_from, play_url = [], []
        for i, sid in enumerate(panel_order):
            src = sources[i] if i < len(sources) else ("播放源%d" % (i + 1))
            play_from.append(src)
            play_url.append("#".join(
                "%s$%s" % (n, self._fix_url(h)) for n, h in panels[sid]))

        if not play_from:
            return {"list": []}

        return {"list": [{
            "vod_id": vod_id,
            "vod_name": name,
            "vod_pic": pic,
            "vod_content": content,
            "vod_actor": actor,
            "vod_director": director,
            "vod_score": score,
            "vod_type": vtype,
            "vod_area": area,
            "vod_year": year,
            "vod_remarks": remarks or ("%d条线路" % len(play_from)),
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
        }]}

    # -------- 播放 --------
    def playerContent(self, flag, id, vipFlags):
        play_page = id if id.startswith("http") else self._fix_url(id)
        self.log("player: %s" % play_page)

        now = int(time.time())
        if play_page in self._play_cache:
            ts, res = self._play_cache[play_page]
            if now - ts < 600:
                return res

        header = {"User-Agent": UA, "Referer": self.site_url + "/"}

        html = self._fetch(play_page)
        if html:
            m = _RE_PLAYER.search(html)
            if m:
                try:
                    pdata = json.loads(m.group(1))
                except Exception:
                    pdata = {}

                purl = pdata.get("url", "")

                # 情况 A: player_aaaa.url 已是明文直链
                if purl.startswith("http"):
                    res = {"parse": 0, "playUrl": "", "url": purl,
                           "header": header}
                    self._play_cache[play_page] = (now, res)
                    self.log("  => 明文直链: %s" % purl[:160])
                    return res

                # 情况 B: 加密 vid -> POST kkyplayer/api.php
                if purl:
                    try:
                        # 同样使用 _sess 保持会话上下文
                        rsp = self._sess.post(
                            self.site_url + "/kkyplayer/api.php",
                            data={"vid": purl},
                            headers=dict(
                                header,
                                **{"Referer":
                                   self.site_url + "/kkyplayer/index.php",
                                   "X-Requested-With": "XMLHttpRequest"}),
                            timeout=20)
                        j = rsp.json()
                        data = j.get("data") or {}
                        enc_url = data.get("url", "")
                        mode = data.get("urlmode", 2)
                        if enc_url:
                            # urlmode=2 -> Decode2; 其他(含 1) -> Decode1
                            if str(mode) == "2":
                                real = _custom_decode(enc_url)
                            else:
                                try:
                                    real = _decode1(enc_url)
                                except Exception:
                                    real = _custom_decode(enc_url)
                            if real.startswith("http"):
                                res = {"parse": 0, "playUrl": "", "url": real,
                                       "header": header}
                                self._play_cache[play_page] = (now, res)
                                self.log("  => 解密直链: %s" % real[:160])
                                return res
                    except Exception as e:
                        self.log("  api.php 解析失败: %s" % e)

        # 兜底: 交给 TVBox 嗅探播放页
        res = {"parse": 1, "playUrl": "", "url": play_page, "header": header}
        self._play_cache[play_page] = (now, res)
        return res

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
            # 图片同样使用带通行 Cookie 的 Session
            rsp = self._sess.get(url, headers={"User-Agent": UA,
                                           "Referer": self.site_url + "/"},
                             timeout=15)
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
