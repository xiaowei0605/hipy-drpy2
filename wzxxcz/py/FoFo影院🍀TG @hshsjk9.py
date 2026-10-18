# coding=utf-8
"""
FoFo影院 fofo22.com | 真实源码破局版
"""
import re
import sys
import json
import urllib.parse
import urllib.request

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
            method = kw.pop('method', 'GET').upper()
            data = kw.pop('data', None)
            if method == 'POST':
                r = self._sess.post(url, headers=headers, timeout=timeout, data=data, **kw)
            else:
                r = self._sess.get(url, headers=headers, timeout=timeout, **kw)
            r.encoding = 'utf-8'
            return r

    Spider = _BaseSpider

HOST = "https://fofo22.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
INTRO_PREFIX = "🍊小橙子为您介绍剧情👉请不要相信视频中的广告，以免上当受骗！"

class Spider(Spider):

    def init(self, extend=""):
        self.site_url = HOST
        self.headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": self.site_url + "/"
        }
        self.default_pic = "https://pic.rmb.bdstatic.com/bjh/user/default.png"

    def _fetch(self, url, headers=None, method='GET', data=None):
        h = dict(self.headers)
        if headers: h.update(headers)
        try:
            rsp = self.fetch(url, headers=h, method=method, data=data)
            if hasattr(rsp, "text"): return rsp.text
            if hasattr(rsp, "content"): return rsp.content.decode("utf-8", "ignore")
            return str(rsp)
        except Exception:
            return ""

    def _clean(self, s):
        if not s: return ""
        s = re.sub(r"<[^>]+>", "", s)
        return s.replace("&nbsp;", " ").strip()

    def homeContent(self, filter):
        categories = [
            {"type_id": "dianying", "type_name": "电影"},
            {"type_id": "dianshiju", "type_name": "电视剧"},
            {"type_id": "zongyi", "type_name": "综艺"},
            {"type_id": "dongman", "type_name": "动漫"},
        ]
        return {"class": categories, "filters": {}}

    def homeVideoContent(self):
        html = self._fetch(self.site_url + "/")
        return {"list": self._extract_videos(html)}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        
        # 完全依照源码格式拼接，默认全部为 0，第一页不带参数
        cls = extend.get("class", "0") or "0"
        area = extend.get("area", "0") or "0"
        year = extend.get("year", "0") or "0"
        sort = extend.get("sort", "0") or "0"
        
        url = f"{self.site_url}/{tid}/{cls}-{area}-{year}-{sort}"
        if page > 1:
            url += f"?page={page}"
            
        html = self._fetch(url)
        videos = self._extract_videos(html)
        
        pagecount = 1
        m = re.search(r'尾页.*?page=(\d+)', html, re.DOTALL)
        if m: pagecount = int(m.group(1))
        
        return {"list": videos, "page": page, "pagecount": pagecount, "limit": 24, "total": pagecount * 24}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        url = f"{self.site_url}/search?q={urllib.parse.quote(key)}&page={page}"
        html = self._fetch(url)
        return {"list": self._extract_videos(html), "page": page, "pagecount": 1, "limit": 24, "total": 999}

    def detailContent(self, ids):
        vod_id = str(ids[0])
        url = f"{self.site_url}/{vod_id}"
        html = self._fetch(url)
        if not html:
            return {"list": []}

        # 1. 标题
        name = vod_id
        m = re.search(r'<h1[^>]*class="product-title"[^>]*>(.*?)</h1>', html, re.DOTALL)
        if m:
            name = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            name = re.sub(r'\(\d{4}\)', '', name).strip()

        # 2. 封面
        pic = self.default_pic
        m = re.search(r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"', html)
        if m: pic = m.group(1)

        # 3. 简介
        content = INTRO_PREFIX
        m = re.search(r'<meta[^>]*property="og:description"[^>]*content="([^"]+)"', html)
        if m: content += "\n" + self._clean(m.group(1))

        # 4. 核心：真实源码中的 onclick 事件提取
        # 示例: <a href="javascript:;" onclick="play(30381732);">第01集</a>
        play_url = ""
        matches = re.findall(r'onclick="play\((\d+)\);"[^>]*>([^<]+)</a>', html)
        if matches:
            ep_list = [f"{title}${sid}" for sid, title in matches]
            play_url = "#".join(ep_list)

        if not play_url:
            return {"list": []}

        return {"list": [{
            "vod_id": vod_id,
            "vod_name": name,
            "vod_pic": pic,
            "vod_content": content,
            "vod_play_from": "FoFo专线",
            "vod_play_url": play_url
        }]}

    def playerContent(self, flag, id, vipFlags):
        # id 就是刚才提取出来的纯数字 sid，例如 30381732
        sid = str(id)
        
        api = f"{self.site_url}/source/"
        headers = {
            "User-Agent": UA,
            "Referer": self.site_url + "/",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        # POST 提交 ID，直接获取 m3u8
        m3u8 = self._fetch(api, headers=headers, method='POST', data={"id": sid})
        
        if m3u8 and m3u8.startswith("http"):
            return {
                "parse": 0,
                "playUrl": "",
                "url": m3u8.strip(),
                "header": self.headers
            }
            
        return {"parse": 1, "playUrl": "", "url": self.site_url, "header": self.headers}

    def _extract_videos(self, html):
        videos = []
        if not html: return videos
        seen = set()
        # 直接匹配列表源码中的真实结构
        pattern = re.compile(r'<a\s+href="(/[^"]+)"[^>]*class="thumbnail".*?<img.*?src="([^"]+)".*?<h2><a[^>]*>([^<]+)</a></h2>', re.DOTALL)
        for href, pic, name in pattern.findall(html):
            if href in seen: continue
            seen.add(href)
            videos.append({
                "vod_id": href.lstrip('/'),
                "vod_name": name.strip(),
                "vod_pic": pic,
                "vod_remarks": ""
            })
        return videos
