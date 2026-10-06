# coding=utf-8
"""
Hypera 直播 · 韩国电视直播
站点 https://hypera.live/channel/{slug}
播放 https://hypera.live/api/delivery/stream/{slug}/playlist.m3u8?token=&auth=
按 SOOP直播.py 结构
注意: 站点有 IP/地区限制，机房 IP 常返回 Unauthorized
"""
import re
import sys
import json
import time
from urllib.parse import quote

import requests

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

sys.path.append("..")
try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider(object):
        def getProxyUrl(self, *a, **k):
            return "http://127.0.0.1:9978/proxy?do=py"


CHANNELS = [
    ("kbs1", "KBS1", "public"),
    ("kbs2", "KBS2", "public"),
    ("kbsi", "KBS World", "public"),
    ("mbc", "MBC", "public"),
    ("sbs", "SBS", "public"),
    ("mnet", "Mnet", "cable"),
    ("tvn", "tvN", "cable"),
    ("jtbc", "JTBC", "cable"),
    ("ocn", "OCN", "cable"),
    ("ena", "ENA", "cable"),
    ("ytn", "YTN", "news"),
    ("arirang", "Arirang", "news"),
    ("sbsplus", "SBS Plus", "cable"),
    ("mbcevery1", "MBC every1", "cable"),
    ("kbsjoy", "KBS Joy", "cable"),
    ("channela", "Channel A", "cable"),
    ("mbn", "MBN", "cable"),
    ("tvchosun", "TV Chosun", "cable")
]

CATS = [
    ("all", "全部频道"),
    ("public", "无线台"),
    ("cable", "有线/综合"),
    ("news", "新闻"),
]


class Spider(BaseSpider):
    def init(self, extend="{}"):
        self.host = "https://hypera.live"
        self.ua = (
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36"
        )
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": self.host + "/",
        })
        self.session.verify = False
        self._auth_cache = {}  # slug -> (ts, token, auth)

    def getName(self):
        return "Hypera直播"

    def isVideoFormat(self, url):
        u = str(url or "").lower()
        return any(x in u for x in (".m3u8", ".mp4", ".flv"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def _get(self, url, timeout=12):
        try:
            r = self.session.get(url, timeout=timeout)
            if r is not None and r.status_code == 200:
                return r.text or ""
        except Exception:
            pass
        return ""

    def _logo(self, slug):
        return "%s/images/channels/%s.png" % (self.host, slug)

    def _card(self, slug, name, cate=""):
        return {
            "vod_id": slug,
            "vod_name": name,
            "vod_pic": self._logo(slug),
            "vod_remarks": "🔴 LIVE",
            "style": {"type": "rect", "ratio": 1.78},
        }

    def homeContent(self, filter):
        classes = [{"type_id": tid, "type_name": name} for tid, name in CATS]
        return {"class": classes, "filters": {}}

    def homeVideoContent(self):
        return {
            "list": [self._card(s, n, c) for s, n, c in CHANNELS[:12]]
        }

    def categoryContent(self, tid, pg, filter, extend):
        tid = str(tid or "all")
        videos = []
        for slug, name, cate in CHANNELS:
            if tid == "all" or cate == tid:
                videos.append(self._card(slug, name, cate))
        return {
            "list": videos,
            "page": 1,
            "pagecount": 1,
            "limit": len(videos),
            "total": len(videos),
        }

    def searchContent(self, key, quick, pg="1"):
        key = str(key or "").strip().lower()
        videos = []
        if key:
            for slug, name, cate in CHANNELS:
                if key in slug.lower() or key in name.lower():
                    videos.append(self._card(slug, name, cate))
        return {
            "list": videos,
            "page": 1,
            "pagecount": 1,
            "limit": len(videos),
            "total": len(videos),
        }

    def _extract_auth(self, html, slug):
        """从频道页提取 token / auth JWT"""
        token, auth = "", ""
        if not html:
            return token, auth
        # auth=eyJ... JWT
        m = re.search(r'(?:auth|jwt|ads_jwt)["\s:=]+["\']?(eyJ[A-Za-z0-9_\-\.]+)', html)
        if m:
            auth = m.group(1)
        # token=xxx 短 token
        m2 = re.search(r'(?:[?&]token=|token["\s:=]+)["\']?([A-Za-z0-9_\-]{4,32})', html)
        if m2:
            token = m2.group(1)
        # playlist 完整 URL
        m3 = re.search(
            r'(/api/delivery/stream/[^"\'\s]+playlist\.m3u8[^"\'\s]*)',
            html,
            re.I,
        )
        if m3:
            full = m3.group(1)
            tm = re.search(r'[?&]token=([^&"\']+)', full)
            am = re.search(r'[?&]auth=([^&"\']+)', full)
            if tm:
                token = tm.group(1)
            if am:
                auth = am.group(1)
        return token, auth

    def _resolve(self, slug):
        now = time.time()
        hit = self._auth_cache.get(slug)
        if hit and now - hit[0] < 90:
            token, auth = hit[1], hit[2]
            if token or auth:
                q = []
                if token:
                    q.append("token=" + quote(token))
                if auth:
                    q.append("auth=" + quote(auth))
                return "%s/api/delivery/stream/%s/playlist.m3u8?%s" % (
                    self.host, slug, "&".join(q)
                )

        page = "%s/channel/%s" % (self.host, slug)
        html = self._get(page)
        if "Unauthorized" in (html or "")[:500]:
            # 地区/IP 拦截
            return ""

        token, auth = self._extract_auth(html, slug)
        self._auth_cache[slug] = (now, token, auth)

        if not token and not auth:
            # 兜底：无参尝试（部分边缘节点可能放行）
            return "%s/api/delivery/stream/%s/playlist.m3u8" % (self.host, slug)

        q = []
        if token:
            q.append("token=" + quote(token))
        if auth:
            q.append("auth=" + quote(auth))
        return "%s/api/delivery/stream/%s/playlist.m3u8?%s" % (
            self.host, slug, "&".join(q)
        )

    def detailContent(self, ids):
        slug = ""
        if isinstance(ids, (list, tuple)):
            slug = str(ids[0] if ids else "").strip()
        else:
            slug = str(ids or "").strip()
        name = slug
        for s, n, c in CHANNELS:
            if s == slug:
                name = n
                break
        return {
            "list": [{
                "vod_id": slug,
                "vod_name": name,
                "vod_pic": self._logo(slug),
                "vod_remarks": "🔴 LIVE · Hypera",
                "vod_content": "韩国电视直播 %s\nhttps://hypera.live/channel/%s" % (name, slug),
                "vod_play_from": "Hypera",
                "vod_play_url": "直播$%s" % slug,
                "style": {"type": "rect", "ratio": 1.78},
            }]
        }

    def playerContent(self, flag, id, vipFlags=None):
        headers = {
            "User-Agent": self.ua,
            "Referer": self.host + "/",
            "Origin": self.host,
            "Accept": "*/*",
        }
        raw = str(id or "").strip()
        if "$" in raw:
            raw = raw.split("$")[-1].strip()
        if raw.startswith("http") and self.isVideoFormat(raw):
            return {"parse": 0, "jx": 0, "url": raw, "header": headers}

        slug = raw
        try:
            url = self._resolve(slug)
            if url:
                return {"parse": 0, "jx": 0, "url": url, "header": headers}
        except Exception as e:
            print("hypera play err", e)

        # 回退频道页（壳子嗅探）
        page = "%s/channel/%s" % (self.host, slug)
        return {"parse": 1, "jx": 0, "url": page, "header": headers}

    def localProxy(self, param):
        return None


if __name__ == "__main__":
    sp = Spider()
    sp.init()
    print("home", [c["type_name"] for c in sp.homeContent(False)["class"]])
    r = sp.categoryContent("all", 1, False, {})
    print("cat", len(r.get("list") or []))
    if r.get("list"):
        print(" first", r["list"][0]["vod_name"], r["list"][0]["vod_id"])
        d = sp.detailContent([r["list"][0]["vod_id"]])
        main = d["list"][0]
        print("detail", main.get("vod_name"), main.get("vod_play_from"))
        p = sp.playerContent("Hypera", main["vod_play_url"].split("$")[-1], [])
        print("play", p.get("parse"), str(p.get("url"))[:120])
