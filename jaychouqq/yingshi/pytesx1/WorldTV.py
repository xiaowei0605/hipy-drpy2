# -*- coding: utf-8 -*-
"""
World TV Mobile 直播
站点 https://worldstvmobile.com
API  https://api.worldstvmobile.com/
  categories / countries
  channelsbycategory?category=
  channelsbycountry?country=
  channelsbyname?filter=
  streambyid?id=
按 iptv234.py 结构
"""
import re
import json
import sys

try:
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    requests = None

sys.path.append("..")
try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider(object):
        def init(self, extend=""):
            pass

API = "https://api.worldstvmobile.com"
SITE = "https://worldstvmobile.com"
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.6 Mobile/15E148 Safari/604.1"
)

# 热门分类（其余从 API 拉）
HOT_CATS = [
    ("news", "新闻"),
    ("sports", "体育"),
    ("general", "综合"),
    ("entertainment", "娱乐"),
    ("movies", "电影"),
    ("music", "音乐"),
    ("kids", "儿童"),
    ("documentary", "纪录"),
    ("religious", "宗教"),
    ("business", "财经"),
    ("education", "教育"),
    ("culture", "文化"),
]


class Spider(BaseSpider):
    def init(self, extend=""):
        self.api = API
        self.session = None
        if requests is not None:
            self.session = requests.Session()
            self.session.headers.update({
                "User-Agent": UA,
                "Origin": SITE,
                "Referer": SITE + "/",
                "Accept": "application/json",
            })
            self.session.verify = False
        self._cats_cache = None
        self._countries_cache = None

    def getName(self):
        return "WorldTV"

    def isVideoFormat(self, url):
        u = str(url or "").lower()
        return any(x in u for x in (".m3u8", ".mp4", ".flv", ".mpd", "rtmp"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        try:
            if self.session:
                self.session.close()
        except Exception:
            pass

    def _headers(self):
        return {
            "User-Agent": UA,
            "Origin": SITE,
            "Referer": SITE + "/",
            "Accept": "application/json",
        }

    def _get_json(self, path, params=None, timeout=15):
        url = path if str(path).startswith("http") else (self.api.rstrip("/") + "/" + path.lstrip("/"))
        try:
            if self.session is not None:
                r = self.session.get(url, params=params or {}, headers=self._headers(), timeout=timeout)
                if r.status_code == 200:
                    return r.json()
            else:
                import urllib.request
                from urllib.parse import urlencode
                if params:
                    url = url + ("&" if "?" in url else "?") + urlencode(params)
                req = urllib.request.Request(url, headers=self._headers())
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8", "ignore"))
        except Exception as e:
            print("api err", path, e)
        return None

    def _pic(self, item):
        # 无稳定 logo CDN 时用占位；有 website 时可用 favicon
        web = (item or {}).get("website") or ""
        if web and web.startswith("http"):
            try:
                from urllib.parse import urlparse
                host = urlparse(web).netloc
                if host:
                    return "https://www.google.com/s2/favicons?sz=128&domain=" + host
            except Exception:
                pass
        return SITE + "/assets/watch-tv.png"

    def _map(self, item):
        if not isinstance(item, dict):
            return None
        cid = str(item.get("id") or "").strip()
        if not cid:
            return None
        name = item.get("name") or cid
        country = item.get("country") or ""
        cats = item.get("categories") or []
        remarks = country
        if cats:
            remarks = (country + " · " + cats[0]) if country else cats[0]
        return {
            "vod_id": cid,
            "vod_name": str(name)[:80],
            "vod_pic": self._pic(item),
            "vod_remarks": remarks or "LIVE",
            "style": {"type": "rect", "ratio": 1.5},
        }

    def _load_cats(self):
        if self._cats_cache is not None:
            return self._cats_cache
        data = self._get_json("categories")
        if isinstance(data, list) and data:
            self._cats_cache = [
                {"type_id": "cat_" + str(x.get("id")), "type_name": x.get("name") or x.get("id")}
                for x in data if x.get("id")
            ]
        else:
            self._cats_cache = [
                {"type_id": "cat_" + t, "type_name": n} for t, n in HOT_CATS
            ]
        return self._cats_cache

    def homeContent(self, filter=False):
        classes = [{"type_id": "hot", "type_name": "热门"}]
        classes += self._load_cats()
        # 国家入口（常用）
        for code, name in [
            ("CN", "中国"), ("HK", "香港"), ("TW", "台湾"), ("US", "美国"),
            ("JP", "日本"), ("KR", "韩国"), ("UK", "英国"), ("IN", "印度"),
        ]:
            classes.append({"type_id": "cty_" + code, "type_name": name})
        return {"class": classes, "filters": {}}

    def homeVideoContent(self):
        data = self._get_json("channelsbycategory", {"category": "news"})
        videos = []
        if isinstance(data, list):
            for it in data[:30]:
                v = self._map(it)
                if v:
                    videos.append(v)
        return {"list": videos}

    def categoryContent(self, tid, pg, filter=False, extend=None):
        tid = str(tid or "hot")
        pg = int(pg or 1)
        videos = []
        data = None
        if tid == "hot":
            data = self._get_json("channelsbycategory", {"category": "news"})
        elif tid in ("cat_xxx", "xxx"):
            # API xxx 分类为空：从综合等筛 is_nsfw + 关键词搜索
            data = []
            seen = set()
            for pool in ("general", "entertainment", "movies", "lifestyle"):
                arr = self._get_json("channelsbycategory", {"category": pool}) or []
                if not isinstance(arr, list):
                    continue
                for it in arr:
                    cid = str((it or {}).get("id") or "")
                    if not cid or cid in seen:
                        continue
                    if it.get("is_nsfw"):
                        seen.add(cid)
                        data.append(it)
            for key in ("Adult", "adult", "XXX", "Sexy", "PlutoTVAdult"):
                arr = self._get_json("channelsbyname", {"filter": key}) or []
                if not isinstance(arr, list):
                    continue
                for it in arr:
                    cid = str((it or {}).get("id") or "")
                    if not cid or cid in seen:
                        continue
                    seen.add(cid)
                    data.append(it)
        elif tid.startswith("cat_"):
            data = self._get_json("channelsbycategory", {"category": tid[4:]})
        elif tid.startswith("cty_"):
            code = tid[4:]
            if code == "GB":
                code = "UK"
            data = self._get_json("channelsbycountry", {"country": code})
        else:
            data = self._get_json("channelsbycategory", {"category": tid})

        if isinstance(data, list):
            # 简单分页：每页 50
            page_size = 50
            start = (pg - 1) * page_size
            chunk = data[start: start + page_size]
            for it in chunk:
                v = self._map(it)
                if v:
                    videos.append(v)
            total = len(data)
            pagecount = max(1, (total + page_size - 1) // page_size)
        else:
            total = 0
            pagecount = 1

        return {
            "list": videos,
            "page": pg,
            "pagecount": pagecount,
            "limit": 50,
            "total": total,
        }

    def searchContent(self, key, quick=False, pg=1):
        return self.searchContentPage(key, quick, pg)

    def searchContentPage(self, key, quick=False, pg=1):
        key = str(key or "").strip()
        if not key:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 30, "total": 0}
        data = self._get_json("channelsbyname", {"filter": key})
        videos = []
        if isinstance(data, list):
            for it in data:
                v = self._map(it)
                if v:
                    videos.append(v)
        return {
            "list": videos,
            "page": 1,
            "pagecount": 1,
            "limit": 50,
            "total": len(videos),
        }

    def detailContent(self, ids):
        raw = str((ids[0] if ids else "") or "").strip()
        if not raw:
            return {"list": []}
        # 列表项信息可能不全，用搜索补全名字
        name = raw
        pic = SITE + "/assets/watch-tv.png"
        data = self._get_json("channelsbyname", {"filter": raw.split(".")[0]})
        if isinstance(data, list):
            for it in data:
                if str(it.get("id")) == raw:
                    name = it.get("name") or name
                    pic = self._pic(it)
                    break
        stream = self._get_json("streambyid", {"id": raw})
        play_url = "直播$" + raw
        quality = ""
        if isinstance(stream, dict) and stream.get("url"):
            quality = stream.get("quality") or stream.get("feed") or ""
            play_url = (quality or "直播") + "$" + stream["url"]
        return {
            "list": [{
                "vod_id": raw,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": ("🔴 " + quality) if quality else "🔴 LIVE",
                "vod_content": name,
                "vod_play_from": "WorldTV",
                "vod_play_url": play_url,
                "style": {"type": "rect", "ratio": 1.5},
            }]
        }

    def playerContent(self, flag, id, vipFlags=None):
        head = {
            "User-Agent": UA,
            "Referer": SITE + "/",
            "Origin": SITE,
            "Accept": "*/*",
        }
        play = str(id or "").strip()
        if "$" in play:
            play = play.split("$")[-1].strip()

        if play.startswith("http"):
            return {"parse": 0, "jx": 0, "url": play, "header": head}

        # 当作 channel id
        stream = self._get_json("streambyid", {"id": play})
        if isinstance(stream, dict) and stream.get("url"):
            ua = stream.get("user_agent") or UA
            ref = stream.get("referrer") or SITE + "/"
            return {
                "parse": 0,
                "jx": 0,
                "url": stream["url"],
                "header": {
                    "User-Agent": ua,
                    "Referer": ref,
                    "Origin": SITE,
                    "Accept": "*/*",
                },
            }
        return {"parse": 0, "jx": 0, "url": "", "header": head}


if __name__ == "__main__":
    sp = Spider()
    sp.init()
    print("home", [c["type_name"] for c in sp.homeContent(False)["class"][:8]])
    r = sp.categoryContent("cat_news", 1, False, {})
    print("news", len(r.get("list") or []), r["list"][0]["vod_name"] if r.get("list") else None)
    if r.get("list"):
        d = sp.detailContent([r["list"][0]["vod_id"]])
        print("detail", d["list"][0]["vod_play_url"][:100])
        p = sp.playerContent("x", d["list"][0]["vod_play_url"].split("$")[-1], [])
        print("play", p.get("parse"), str(p.get("url"))[:100])
