# coding=utf-8
"""
韩小圈 jennyhow.com | TVBox Python 爬虫 
关键:
  - module-item 卡片解析 (首页/分类/搜索通用)
  - nav-tabs 多线路剧集，兼容相对路径 / data-target
  - 播放页三重解析: var now= / player_aaaa / iframe 跟进
  - 简介添加指定前缀
  - _fetch 内置重试 (MAX_RETRY=2，共 3 次)
"""
import re
import sys
import json
import time
import html as html_lib
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
                print("[jenny]", *a)
            except Exception:
                pass

    Spider = _BaseSpider

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


HOST = "https://www.jennyhow.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
DEFAULT_PIC = HOST + "/static/images/loading.png"

INTRO_PREFIX = "🍊小橙子为您介绍剧情👉请不要相信视频中的广告，以免上当受骗！"

MAX_RETRY = 2  # 总请求次数 = MAX_RETRY + 1 = 3，抖动容错最优值

CLASSES = [
    {"type_id": "/hxq/1.html", "type_name": "最新韩剧"},
    {"type_id": "/hxq/2.html", "type_name": "韩国电影"},
    {"type_id": "/hxq/3.html", "type_name": "韩国综艺"},
    {"type_id": "/hxq/4.html", "type_name": "韩国动漫"},
]

TID_ALIAS = {
    "20": "/hxq/1.html", "1": "/hxq/1.html",
    "21": "/hxq/2.html", "2": "/hxq/2.html",
    "22": "/hxq/3.html", "3": "/hxq/3.html",
    "23": "/hxq/4.html", "4": "/hxq/4.html",
}


# ===================== 正则 =====================
_RE_H1 = re.compile(r'<h1[^>]*>([\s\S]*?)</h1>', re.I)
_RE_TITLE = re.compile(r'<title>(.*?)</title>', re.S | re.I)
_RE_NOW = re.compile(r'var\s+now\s*=\s*[\'"](.*?)[\'"]\s*;', re.S | re.I)
_RE_PLAYER_AA = re.compile(r'player_aaaa\s*=\s*(\{[^}]+\})', re.S)
_RE_IFRAME = re.compile(r'<iframe[^>]+src=[\'"]([^\'"]+)[\'"]', re.I)
_RE_M3U8_JSON = re.compile(
    r'["\']url["\']\s*:\s*["\'](https?://[^"\']+\.(?:m3u8|mp4)[^"\']*)["\']', re.I)
_RE_NEXT_PAGE = re.compile(r'下一页|下页')


class Spider(Spider):

    def getName(self):
        return "韩小圈"

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
        self._play_cache = {}
        self.log("init: site=%s" % self.site_url)

    # ---------- 网络 ----------
    def _fetch(self, url, timeout=15, headers=None):
        h = dict(self.headers)
        if headers:
            h.update(headers)
        last_err = ""
        for attempt in range(MAX_RETRY + 1):
            try:
                rsp = self.fetch(url, headers=h, timeout=timeout)
                text = ""
                if hasattr(rsp, "text"):
                    text = rsp.text or ""
                elif hasattr(rsp, "content"):
                    text = rsp.content.decode("utf-8", "ignore")
                else:
                    text = str(rsp)
                if text:
                    return text
                last_err = "空响应"
            except Exception as e:
                last_err = str(e)
                self.log("fetch#%d FAIL %s -> %s" % (attempt + 1, url, e))
        self.log("fetch 最终失败 %s -> %s" % (url, last_err))
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
        s = html_lib.unescape(s)
        s = s.replace("\xa0", " ")
        s = re.sub(r"[ \t\r\f\v]+", " ", s)
        s = re.sub(r"\n{2,}", "\n", s)
        return s.strip()

    def _clean_title(self, title):
        if not title:
            return title
        title = self._clean(title)
        return re.sub(r'\s*[-|_]\s*(韩小圈|JennyHow|韩剧TV).*$', '', title,
                      flags=re.I).strip()

    def _pick_img(self, img_tag):
        if not img_tag:
            return ""
        for attr in ('data-src', 'data-original', 'data-echo',
                     'data-lazyload', 'data-lazy', 'data-url', 'src'):
            v = img_tag.get(attr)
            if v and not v.startswith('data:image'):
                return v.strip()
        srcset = img_tag.get('srcset') or img_tag.get('data-srcset')
        if srcset:
            return srcset.split(',')[0].strip().split(' ')[0]
        return ""

    # ---------- 列表解析 ----------
    def _extract_videos(self, html):
        videos = []
        seen = set()
        if not html or BeautifulSoup is None:
            return videos
        soup = BeautifulSoup(html, 'html.parser')
        items = soup.find_all('div', class_='module-item')
        for item in items:
            a_tag = (item.find('a', class_='module-item-pic')
                     or item.find('a', class_='module-item-title')
                     or item.find('a'))
            if not a_tag:
                continue
            href = a_tag.get('href', '')
            if not href or href in seen:
                continue
            seen.add(href)

            img_tag = item.find('img')
            name = a_tag.get('title') \
                or (img_tag.get('alt') if img_tag else "") \
                or a_tag.get_text(strip=True)
            pic = self._pick_img(img_tag)
            remarks_tag = (item.find(class_='module-item-text')
                           or item.find(class_='module-item-note'))
            remarks = remarks_tag.get_text(strip=True) if remarks_tag else ""

            videos.append({
                "vod_id":      href,
                "vod_name":    self._clean_title(name)[:100],
                "vod_pic":     self._fix_url(pic) or self.default_pic,
                "vod_remarks": remarks,
            })
        return videos

    def _page_count(self, html, page):
        if not html or BeautifulSoup is None:
            return page
        try:
            soup = BeautifulSoup(html, 'html.parser')
            has_next = bool(soup.find('a', string=_RE_NEXT_PAGE))
            if not has_next:
                has_next = bool(soup.select_one('.page a[href*="-%d"]' % (page + 1)))
            return page + 1 if has_next else page
        except Exception:
            return page

    # ---------- 首页 ----------
    # ⭐ 修复：去掉 filters 字段，避免空 filters 导致分类不显示
    def homeContent(self, filter=False):
        return {"class": CLASSES}

    def homeVideoContent(self):
        html = self._fetch(self.site_url + "/")
        self.log("home HTML 长度: %d" % len(html))
        return {"list": self._extract_videos(html)}

    # ---------- 分类 ----------
    # ⭐ 修复：加默认值，兼容只传部分参数的前端
    def categoryContent(self, tid, pg=1, filter=False, extend=None):
        page = int(pg) if pg else 1
        tid = TID_ALIAS.get(str(tid), str(tid))

        url = tid
        if page > 1 and url.endswith('.html'):
            url = url.replace('.html', '-%d.html' % page)
        url = self._fix_url(url)

        self.log("category: %s" % url)
        html = self._fetch(url)
        self.log("  HTML 长度: %d" % len(html))

        videos = self._extract_videos(html)
        pagecount = self._page_count(html, page)
        self.log("  最终: %d 条, 总页数: %d" % (len(videos), pagecount))

        return {
            "list": videos, "page": page, "pagecount": pagecount,
            "limit": 24, "total": pagecount * 24,
        }

    # ---------- 搜索 ----------
    # ⭐ 修复：加默认值
    def searchContent(self, key, quick=False, pg=1):
        page = int(pg) if pg else 1
        kw = urllib.parse.quote(key, safe='')
        url = "%s/vodsearch/%s----------%d---.html" % (self.site_url, kw, page)
        self.log("search: %s" % url)
        html = self._fetch(url)
        self.log("  HTML 长度: %d" % len(html))

        videos = self._extract_videos(html)
        pagecount = self._page_count(html, page)
        return {
            "list": videos, "page": page, "pagecount": pagecount,
            "limit": 24, "total": pagecount * 24,
        }

    def searchContentPage(self, key, quick=False, pg=1):
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
        if not html or BeautifulSoup is None:
            return {"list": []}

        soup = BeautifulSoup(html, 'html.parser')

        # 标题
        name = ""
        m = _RE_H1.search(html)
        if m:
            name = self._clean(m.group(1))
        if not name:
            m = _RE_TITLE.search(html)
            if m:
                name = self._clean(m.group(1).split("_")[0].split("-")[0])
        name = self._clean_title(name) or vod_id

        # 封面
        pic_tag = (soup.find('img', class_='lazyload')
                   or soup.find('img', class_='lazy')
                   or soup.find('img'))
        pic = self._fix_url(self._pick_img(pic_tag)) or self.default_pic

        # 简介 + 元信息
        director, actor, year, content = "", "", "", ""
        for tag in soup.find_all(string=re.compile(r'导演|主演|上映|年份|剧情|简介')):
            text_str = tag.strip()
            parent = tag.parent
            if parent is None or parent.name in ['title', 'meta', 'script', 'style']:
                continue
            container = parent.parent if parent.name in ['span', 'strong', 'b', 'font'] else parent
            full_text = container.get_text(separator=' ', strip=True)

            if '导演' in text_str and not director:
                director = re.sub(r'.*?导演[：:]?\s*', '', full_text).strip()
            elif '主演' in text_str and not actor:
                actor = re.sub(r'.*?主演[：:]?\s*', '', full_text).strip()
            elif ('上映' in text_str or '年份' in text_str) and not year:
                year = re.sub(r'.*?(上映|年份)[：:]?\s*', '', full_text).strip()
            elif ('剧情' in text_str or '简介' in text_str) and not content:
                content = re.sub(r'.*?(剧情|简介)[：:]?\s*', '', full_text).strip()

        if not content:
            intro_tag = (soup.find(class_='module-info-introduction-content')
                         or soup.find(class_='module-info-introduction'))
            if intro_tag:
                content = intro_tag.get_text(strip=True)

        content = self._clean(content)
        content = INTRO_PREFIX + ("\n" + content if content else "")

        # 播放列表
        groups = {}
        tabs_ul = (soup.find('ul', class_='nav-tabs')
                   or soup.find('ul', class_='nav nav-tabs'))
        if tabs_ul:
            for li in tabs_ul.find_all('li'):
                a_tag = li.find('a')
                if not a_tag:
                    continue
                line_name = a_tag.get_text(strip=True)
                target_id = a_tag.get('href', '').replace('#', '')
                playlist_div = soup.find('div', id=target_id)
                if not playlist_div:
                    t2 = a_tag.get('data-target', '').replace('#', '')
                    if t2:
                        playlist_div = soup.find('div', id=t2)
                if not playlist_div:
                    continue

                seen = set()
                eps = []
                for ep in playlist_div.find_all('a'):
                    ep_name = ep.get('title') or ep.get_text(strip=True)
                    ep_href = ep.get('href', '')
                    if not ep_href or ep_href in seen:
                        continue
                    seen.add(ep_href)
                    if not ep_href.startswith('http') and not ep_href.startswith('/'):
                        ep_href = '/' + ep_href
                    eps.append((self._clean(ep_name) or ("第%d集" % (len(eps) + 1)),
                                ep_href))
                if eps:
                    groups[line_name] = eps

        self.log("  剧集: %s" % {k: len(v) for k, v in groups.items()})

        if not groups:
            return {"list": []}

        play_from = list(groups.keys())
        play_url = ["#".join("%s$%s" % (n, h) for n, h in groups[k]) for k in play_from]

        return {"list": [{
            "vod_id": vod_id,
            "vod_name": name,
            "vod_pic": pic,
            "vod_content": content,
            "vod_actor": actor,
            "vod_director": director,
            "vod_year": year,
            "vod_remarks": "%d条线路" % len(groups),
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

        result = None
        if html:
            # ① var now='xxx'
            m = _RE_NOW.search(html)
            if m:
                result = {
                    "parse": 0,
                    "playUrl": "",
                    "url": m.group(1),
                    "header": {"User-Agent": UA, "Referer": play_page},
                }

            # ② player_aaaa = {...}
            if not result:
                m = _RE_PLAYER_AA.search(html)
                if m:
                    try:
                        data = json.loads(m.group(1))
                        u = data.get("url", "")
                        if u:
                            result = {
                                "parse": 0,
                                "playUrl": "",
                                "url": u,
                                "header": {"User-Agent": UA, "Referer": play_page},
                            }
                    except Exception:
                        pass

            # ③ iframe 播放页，跟进去再找
            if not result:
                m_iframe = _RE_IFRAME.search(html)
                if m_iframe:
                    inner = self._fix_url(m_iframe.group(1))
                    self.log("  iframe: %s" % inner[:160])
                    inner_html = self._fetch(inner)
                    m2 = _RE_NOW.search(inner_html)
                    if not m2:
                        m2 = _RE_M3U8_JSON.search(inner_html)
                    if m2:
                        result = {
                            "parse": 0, "playUrl": "",
                            "url": m2.group(1),
                            "header": {"User-Agent": UA, "Referer": inner},
                        }

        # 兜底：交给 TVBox 嗅探
        if not result:
            result = {
                "parse": 1, "playUrl": "", "url": play_page,
                "header": {"User-Agent": UA, "Referer": self.site_url + "/"},
            }

        self._play_cache[play_page] = (now, result)
        return result

    def localProxy(self, param):
        return None

    def isVideoFormat(self, url):
        return ".m3u8" in url or ".mp4" in url

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def close(self):
        self.destroy()
