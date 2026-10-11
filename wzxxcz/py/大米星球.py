# coding=utf-8
"""
大米星球 dmxq40.com | TVBox Python 爬虫 (最终稳定版)
核心策略:
  - 分类页: 先请求 /vodtype/{tid}.html，从 HTML 里自动抓取 /vodshow/ 链接
  - 列表提取: 以 /voddetail/ 链接为分割点，在周围查找标题/图片
  - 网络请求: TVBox fetch → requests → http 三级回退
  - 播放页: 贪婪匹配 player_aaaa 完整 JSON
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
            try: print("[dmxq]", *a)
            except Exception: pass
    Spider = _BaseSpider

HOST = "https://dmxq40.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
DEFAULT_PIC = "https://vpic.cms.qq.com/nj_vpic/3272248629/1738572385393158887/112429678912224247"

CLASSES = [
    {"type_id": "20", "type_name": "电影"},
    {"type_id": "21", "type_name": "电视剧"},
    {"type_id": "36", "type_name": "短剧"},
    {"type_id": "22", "type_name": "动漫"},
    {"type_id": "23", "type_name": "综艺"},
]

_SORTS = [{"n": "时间", "v": "time"}, {"n": "人气", "v": "hits"}, {"n": "评分", "v": "score"}]
_YEARS = [{"n": "全部", "v": ""}] + [{"n": str(y), "v": str(y)} for y in range(2026, 1999, -1)]
_AREAS = [{"n": "全部", "v": ""}, {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"},
          {"n": "台湾", "v": "台湾"}, {"n": "美国", "v": "美国"}, {"n": "日本", "v": "日本"},
          {"n": "韩国", "v": "韩国"}, {"n": "英国", "v": "英国"}, {"n": "法国", "v": "法国"}]

_FILTERS_MAP = {
    "20": ["全部", "Netflix", "仙侠", "剧情", "科幻", "动作", "喜剧", "爱情", "冒险", "恐怖", "悬疑", "犯罪", "战争"],
    "21": ["全部", "Netflix", "短剧", "剧情", "网剧", "丧尸", "仙侠", "穿越", "惊悚", "恐怖", "言情", "科幻", "动作", "喜剧", "爱情"],
    "36": ["全部", "AI漫剧", "短剧", "剧情", "爱情", "爽文", "古装", "悬疑", "喜剧", "奇幻", "都市", "玄幻", "穿越"],
    "22": ["全部", "Netflix", "热血", "科幻", "美少女", "魔幻", "经典", "励志", "少儿", "冒险", "搞笑", "推理"],
    "23": ["全部", "脱口秀", "真人秀", "选秀", "八卦", "访谈", "情感", "生活", "晚会", "搞笑", "音乐"]
}

FILTERS = {}
for c in CLASSES:
    tid = c["type_id"]
    FILTERS[tid] = [
        {"key": "class", "name": "剧情", "value": [{"n": x, "v": "" if x == "全部" else x} for x in _FILTERS_MAP.get(tid, ["全部"])]},
        {"key": "area", "name": "地区", "value": _AREAS},
        {"key": "year", "name": "年份", "value": _YEARS},
        {"key": "sort", "name": "排序", "value": _SORTS},
    ]

class Spider(Spider):

    def getName(self):
        return "大米星球"

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
            "Referer": self.site_url + "/",
        }
        self._play_cache = {}
        self.log("init site =", self.site_url)

    # ===================== 网络请求（三级回退） =====================
    def _fetch(self, url, timeout=20, headers=None):
        h = dict(self.headers)
        if headers: h.update(headers)
        
        # 1. 尝试 TVBox 自带 fetch
        try:
            rsp = self.fetch(url, headers=h, timeout=timeout)
            text = rsp.text if hasattr(rsp, "text") else (rsp.content.decode("utf-8", "ignore") if hasattr(rsp, "content") else str(rsp))
            if text and len(text) > 100:
                return text
        except Exception as e:
            self.log("TVBox fetch FAIL: %s" % e)

        # 2. 尝试 requests（跳过 SSL 验证）
        try:
            import requests
            r = requests.get(url, headers=h, timeout=timeout, verify=False)
            r.encoding = 'utf-8'
            if r.text and len(r.text) > 100:
                return r.text
        except Exception as e:
            self.log("requests FAIL: %s" % e)

        # 3. 尝试 http 回退
        if url.startswith("https://"):
            try:
                url_http = url.replace("https://", "http://")
                import requests
                r = requests.get(url_http, headers=h, timeout=timeout, verify=False)
                r.encoding = 'utf-8'
                return r.text
            except Exception as e:
                self.log("http fallback FAIL: %s" % e)

        return ""

    def _fix_url(self, url):
        if not url: return ""
        url = url.strip().replace("&amp;", "&")
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
        return re.sub(r"\s+", " ", s).strip()

    # ===================== 列表提取（以详情链接为分割点） =====================
    def _extract_videos(self, html):
        items = []
        seen = set()
        if not html: return items

        links = list(re.finditer(r'href="(/voddetail/[^"]+?\.html)"', html))
        for i, m in enumerate(links):
            href = m.group(1)
            if href in seen: continue
            seen.add(href)

            start = m.start()
            end = links[i+1].start() if i+1 < len(links) else len(html)
            block = html[start:end]

            # 标题：尝试所有可能的结构
            title = ""
            for pat in [
                r'<div class="module-poster-item-title"[^>]*>([\s\S]*?)</div>',
                r'<strong><em>(.*?)</em></strong>',
                r'title="([^"]*)"',
                r'alt="([^"]*)"',
                r'<div class="module-card-item-title[^"]*">\s*<a[^>]*>([\s\S]*?)</a>'
            ]:
                t = re.search(pat, block, re.S | re.I)
                if t:
                    title = self._clean(t.group(1))
                    if title: break
            if not title: title = href

            # 图片
            pic = ""
            p = re.search(r'<img[^>]*?(?:data-original|src)="([^"]+)"', block, re.I)
            if p: pic = self._fix_url(p.group(1))

            # 备注
            note = ""
            n = re.search(r'<div class="module-item-note">([^<]*)</div>', block, re.I)
            if n: note = self._clean(n.group(1))

            items.append({"vod_id": href, "vod_name": title, "vod_pic": pic or DEFAULT_PIC, "vod_remarks": note})

        return items

    def _page_count(self, html):
        if not html: return 1
        m = re.search(r'title="尾页"[^>]*href="([^"]+?)"', html, re.I) or \
            re.search(r'href="([^"]+?)"[^>]*title="尾页"', html, re.I)
        if m:
            mm = re.search(r'(\d+)---', m.group(1))
            if mm:
                try: return int(mm.group(1))
                except Exception: pass
        return 9999

    # ===================== 分类 URL 自动抓取 =====================
    def _get_show_url(self, tid, pg, extend):
        """请求 /vodtype/{tid}.html，从 HTML 里自动提取正确的 /vodshow/ 链接"""
        type_url = f"{self.site_url}/vodtype/{tid}.html"
        html = self._fetch(type_url)
        if not html:
            return f"{self.site_url}/vodshow/{tid}-----------.html"

        # 如果第 1 页且无筛选，直接用默认链接
        if int(pg) == 1 and not any(extend.get(k) for k in ("area", "class", "year", "sort")):
            m = re.search(r'href="(/vodshow/[^"]+?)"[^>]*class="[^"]*active[^"]*"[^>]*>全部</a>', html)
            if m: return self._fix_url(m.group(1))
            # 兜底：直接用 /vodshow/{tid}-----------.html
            return f"{self.site_url}/vodshow/{tid}-----------.html"

        # 有筛选时，从页面筛选器链接中匹配（这里简化处理，直接按最可能的格式拼接）
        # 因为分类页的筛选器链接本身是完整的 /vodshow/ 路径
        # 实际项目中可遍历筛选器链接，按当前选中的值匹配，但这里为了稳定性，采用直接拼装
        area = urllib.parse.quote(extend.get("area", ""))
        cls = urllib.parse.quote(extend.get("class", ""))
        sort = extend.get("sort", "")
        year = extend.get("year", "")

        parts = [area, cls, sort] if (area or cls or sort) else []
        mid = "-".join(parts) if parts else ""

        if not mid:
            if int(pg) == 1:
                return f"{self.site_url}/vodshow/{tid}-----------{year}.html"
            else:
                return f"{self.site_url}/vodshow/{tid}--------{pg}---{year}.html"
        else:
            if int(pg) == 1:
                return f"{self.site_url}/vodshow/{tid}-{mid}----------{year}.html"
            else:
                return f"{self.site_url}/vodshow/{tid}-{mid}-------{pg}---{year}.html"

    # ===================== TVBox 接口 =====================
    def homeContent(self, filter=False):
        return {"class": CLASSES, "filters": FILTERS}

    def homeVideoContent(self):
        html = self._fetch(self.site_url + "/index/home.html")
        videos = self._extract_videos(html)
        self.log("home 提取: %d 条" % len(videos))
        return {"list": videos}

    def categoryContent(self, tid, pg, filter, extend):
        if isinstance(extend, str):
            try: extend = json.loads(extend)
            except Exception: extend = {}
        if not extend: extend = {}

        page = int(pg) if pg else 1
        url = self._get_show_url(tid, page, extend)
        self.log("category URL:", url)

        html = self._fetch(url)
        self.log("  HTML length:", len(html))
        videos = self._extract_videos(html)
        self.log("  提取到:", len(videos))

        return {
            "list": videos, "page": page,
            "pagecount": self._page_count(html),
            "limit": 24, "total": 999
        }

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        kw = urllib.parse.quote(key, safe="")
        if page == 1:
            url = f"{self.site_url}/vodsearch/{kw}-------------.html"
        else:
            url = f"{self.site_url}/vodsearch/{kw}----------{page}---.html"
        html = self._fetch(url)
        videos = self._extract_videos(html)
        return {"list": videos, "page": page, "pagecount": self._page_count(html), "limit": 24, "total": 999}

    def searchContentPage(self, key, quick, pg="1"):
        return self.searchContent(key, quick, pg)

    def detailContent(self, ids):
        if not ids: return {"list": []}
        vod_id = str(ids[0])
        url = vod_id if vod_id.startswith("http") else self._fix_url(vod_id)
        html = self._fetch(url)
        if not html: return {"list": []}

        # ==================== 基础信息 ====================
        name = ""
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
        if m: name = self._clean(m.group(1))
        if not name:
            m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
            if m: name = self._clean(m.group(1).split("-")[0].split("_")[0])
        if not name: name = vod_id

        pic = ""
        m = re.search(r'<div class="module-item-pic">\s*<img[^>]*?src="([^"]+)"', html, re.S | re.I) or \
            re.search(r'<img[^>]*?data-original="([^"]+)"', html, re.S | re.I)
        if m: pic = self._fix_url(m.group(1))

        content = ""
        m = re.search(r'<div class="module-info-introduction-content[^"]*"[^>]*>([\s\S]*?)</div>', html, re.S | re.I) or \
            re.search(r'<meta name="description" content="([^"]*)"', html, re.I)
        if m: content = self._clean(m.group(1))

        # ==================== 标签：年份 / 地区 / 类型 ====================
        vod_year = ""
        vod_area = ""
        vod_class = ""
        tag_block = re.search(r'<div class="module-info-tag">([\s\S]*?)</div>\s*</div>', html, re.S | re.I)
        if not tag_block:
            tag_block = re.search(r'<div class="module-info-tag">([\s\S]*?)<div class="module-mobile-play"', html, re.S | re.I)
        if tag_block:
            tag_html = tag_block.group(1)
            # 每段 tag-link 里的所有 <a> 文本
            tag_links = re.findall(r'<div class="module-info-tag-link">([\s\S]*?)</div>', tag_html, re.S | re.I)
            for i, seg in enumerate(tag_links):
                texts = [self._clean(t) for t in re.findall(r'<a[^>]*>([^<]*)</a>', seg, re.I)]
                texts = [t for t in texts if t]
                if not texts: continue
                if i == 0:
                    vod_year = texts[0]
                elif i == 1:
                    vod_area = texts[0]
                else:
                    vod_class = "/".join(texts)

        # ==================== 导演 / 编剧 / 主演 ====================
        def _extract_field(title):
            pat = r'<span class="module-info-item-title">' + title + r'[：:]\s*</span>\s*<div class="module-info-item-content">([\s\S]*?)</div>'
            mm = re.search(pat, html, re.S | re.I)
            if not mm:
                return ""
            # 收集所有 <a> 的文本，过滤空
            names = [self._clean(t) for t in re.findall(r'<a[^>]*>([^<]*)</a>', mm.group(1), re.I)]
            names = [n for n in names if n]
            if not names:
                # 兜底：直接清空 HTML
                return self._clean(mm.group(1))
            return " / ".join(names)

        vod_director = _extract_field("导演")
        vod_writer = _extract_field("编剧")
        vod_actor = _extract_field("主演")

        # ==================== 更新日期 / 备注 / 豆瓣 ====================
        vod_update = ""
        m = re.search(r'<span class="module-info-item-title">更新：</span>\s*<div class="module-info-item-content">([\s\S]*?)</div>', html, re.S | re.I)
        if m: vod_update = self._clean(m.group(1))

        vod_remarks = ""
        m = re.search(r'<span class="module-info-item-title">备注：</span>\s*<div class="module-info-item-content">([\s\S]*?)</div>', html, re.S | re.I)
        if m: vod_remarks = self._clean(m.group(1))

        vod_score = ""
        m = re.search(r'<span class="module-info-item-title">豆瓣：</span>[\s\S]*?<font[^>]*>([\d.]+)分?</font>', html, re.S | re.I)
        if m: vod_score = m.group(1)

        # ==================== 播放列表 ====================
        tabs = re.findall(r'<div class="module-tab-item tab-item[^"]*"[^>]*data-dropdown-value="([^"]+)"', html, re.I)
        panels = html.split('<div class="module-list sort-list tab-list his-tab-list" id="panel1">')[1:]

        play_from, play_url = [], []
        for i, panel in enumerate(panels):
            eps = []
            for m in re.finditer(r'href="(/vodplay/(\d+)-(\d+)-(\d+)\.html)"[^>]*?>\s*<span>([^<]+)</span>', panel, re.I):
                href, vid, sid, nid, ep = m.groups()
                eps.append((int(nid), self._clean(ep), self._fix_url(href)))
            if not eps:
                continue
            eps.sort(key=lambda x: x[0])
            alias = tabs[i] if i < len(tabs) else f"线路{i+1}"
            play_from.append(alias)
            play_url.append("#".join(f"{n}${u}" for _, n, u in eps))

        if not play_from:
            return {"list": []}

        # 剧集集数统计
        total_eps = sum(len(p.split("#")) for p in play_url)
        remarks_final = vod_remarks or f"{total_eps}集"
        if vod_update:
            remarks_final = f"{remarks_final} | 更新：{vod_update}"

        return {"list": [{
            "vod_id": vod_id,
            "vod_name": name,
            "vod_pic": pic or DEFAULT_PIC,
            "vod_content": content,
            "vod_year": vod_year,
            "vod_area": vod_area,
            "vod_class": vod_class,
            "vod_director": vod_director,
            "vod_actor": vod_actor,
            "vod_remarks": remarks_final,
            "vod_score": vod_score,
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
        }]}

    def playerContent(self, flag, id, vipFlags):
        play_page = id if id.startswith("http") else self._fix_url(id)
        now = int(time.time())
        if play_page in self._play_cache:
            ts, res = self._play_cache[play_page]
            if now - ts < 600: return res

        html = self._fetch(play_page)
        url = ""
        m = re.search(r'player_aaaa\s*=\s*({.*})\s*;?\s*</script>', html, re.S)
        if m:
            raw = m.group(1)
            try:
                data = json.loads(raw)
                url = data.get("url") or ""
            except Exception:
                mm = re.search(r'"url"\s*:\s*"([^"]+)"', raw)
                if mm: url = mm.group(1)

        if url:
            url = url.replace("\\/", "/").replace("&amp;", "&")
            if url.startswith("//"): url = "https:" + url
            res = {"parse": 0, "playUrl": "", "url": url, "header": {"User-Agent": UA, "Referer": self.site_url + "/"}}
        else:
            res = {"parse": 1, "playUrl": "", "url": play_page, "header": {"User-Agent": UA, "Referer": self.site_url + "/"}}

        self._play_cache[play_page] = (now, res)
        return res

    def localProxy(self, param):
        try:
            url = param.get("url", "") if isinstance(param, dict) else ""
            if not url: return [200, "image/jpeg", b"", ""]
            url = urllib.parse.unquote(url) if "%" in url else url
            import requests
            r = requests.get(self._fix_url(url), headers={"User-Agent": UA, "Referer": self.site_url + "/"}, timeout=15, verify=False)
            return [200, r.headers.get("Content-Type", "image/jpeg"), r.content, ""]
        except Exception:
            return [200, "image/jpeg", b"", ""]

    def isVideoFormat(self, url): return ".m3u8" in url or ".mp4" in url
    def manualVideoCheck(self): return False
    def destroy(self): pass
    def close(self): self.destroy()
