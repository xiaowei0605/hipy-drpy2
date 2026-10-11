#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SuperPorn · https://cn.superporn.ws
按 rou123.py 风格：分类列表 + 详情直出 mp4
"""
import re
import json
import html as html_lib
import urllib.request
import urllib.parse
from http.cookiejar import CookieJar
import gzip
import zlib
import ssl

try:
    from base.spider import Spider as SpiderBase
except ImportError:
    class SpiderBase(object):
        def getProxyUrl(self):
            return ""


class Spider(SpiderBase):
    def __init__(self):
        try:
            super(Spider, self).__init__()
        except Exception:
            pass
        self.siteUrl = "https://cn.superporn.ws"
        self._ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        self.options = {}
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE
        self.cj = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=self.ctx),
        )

    def init(self, extend=""):
        if isinstance(extend, dict):
            self.options = extend
        elif extend:
            try:
                self.options = json.loads(extend)
            except Exception:
                self.options = {}
        host = str(self.options.get("host", "")).strip().rstrip("/")
        if host:
            self.siteUrl = host
        return True

    def getName(self):
        return "SuperPorn"

    def isVideoFormat(self, url):
        if not url:
            return False
        low = url.lower()
        return any(k in low for k in (".m3u8", ".mp4", ".flv", ".ts"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self.options = {}

    def _clean_text(self, text):
        clean = re.sub(r"<[^>]+>", "", text or "")
        clean = html_lib.unescape(clean).replace("\xa0", " ")
        return re.sub(r"[\r\n\t\s]+", " ", clean).strip()

    def _abs(self, u):
        if not u:
            return ""
        u = str(u).strip()
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("http"):
            return u
        if u.startswith("/"):
            return self.siteUrl + u
        return self.siteUrl + "/" + u

    def _fetch(self, target_url, referer=""):
        if not target_url:
            return {"code": 0, "text": "", "err": ""}
        if target_url.startswith("//"):
            target_url = "https:" + target_url
        elif target_url.startswith("/"):
            target_url = self.siteUrl + target_url
        headers = {
            "User-Agent": self._ua,
            "Referer": referer or (self.siteUrl + "/"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate",
        }
        try:
            req = urllib.request.Request(target_url, headers=headers)
            with self.opener.open(req, timeout=15) as resp:
                raw = resp.read()
                enc = resp.headers.get("Content-Encoding", "")
                if raw[:2] == b"\x1f\x8b" or enc == "gzip":
                    raw = gzip.decompress(raw)
                elif enc == "deflate":
                    try:
                        raw = zlib.decompress(raw)
                    except Exception:
                        raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                try:
                    text = raw.decode("utf-8")
                except Exception:
                    text = raw.decode("latin1", errors="ignore")
                return {"code": resp.getcode(), "text": text, "err": ""}
        except Exception as e:
            return {"code": -1, "text": "", "err": str(e)}

    def _parse_cards(self, html):
        vod_list = []
        seen = set()
        if not html:
            return vod_list
        pattern = re.compile(
            r'href=["\']([^"\']*/video/[^"\']+)["\'][\s\S]{0,500}?'
            r'<img[^>]+alt=["\']([^"\']*)["\'][^>]*(?:data-src|src)=["\']([^"\']+)["\']'
            r'[\s\S]{0,400}?duracion[^>]*>\s*([^<]*)<',
            re.I,
        )
        for m in pattern.finditer(html):
            href = self._abs(m.group(1).split("#")[0])
            if href in seen:
                continue
            seen.add(href)
            pic = m.group(3)
            if pic.startswith("data:image"):
                block = html[m.start() : m.start() + 600]
                ds = re.search(r'data-src=["\']([^"\']+)["\']', block, re.I)
                if ds:
                    pic = ds.group(1)
            vod_list.append(
                {
                    "vod_id": href,
                    "vod_name": self._clean_text(m.group(2)) or "视频",
                    "vod_pic": self._abs(pic),
                    "vod_remarks": self._clean_text(m.group(4)),
                    "style": {"type": "rect", "ratio": 1.78},
                }
            )
        if vod_list:
            return vod_list
        pattern2 = re.compile(
            r'href=["\']([^"\']*/video/[^"\']+)["\'][\s\S]{0,400}?alt=["\']([^"\']+)["\']',
            re.I,
        )
        for m in pattern2.finditer(html):
            href = self._abs(m.group(1).split("#")[0])
            if href in seen:
                continue
            seen.add(href)
            block = html[m.start() : m.start() + 500]
            img = re.search(r'data-src=["\']([^"\']+)["\']', block, re.I) or re.search(
                r'src=["\'](https?://[^"\']+)["\']', block, re.I
            )
            dur = re.search(r"duracion[^>]*>\s*([^<]*)<", block, re.I)
            vod_list.append(
                {
                    "vod_id": href,
                    "vod_name": self._clean_text(m.group(2)) or "视频",
                    "vod_pic": self._abs(img.group(1)) if img else "",
                    "vod_remarks": self._clean_text(dur.group(1)) if dur else "",
                    "style": {"type": "rect", "ratio": 1.78},
                }
            )
        return vod_list

    def _extract_play(self, html):
        if not html:
            return ""
        m = re.search(r'<source[^>]+src=["\']([^"\']+\.mp4[^"\']*)["\']', html, re.I)
        if m:
            return self._abs(m.group(1).replace("&amp;", "&"))
        m = re.search(r"(https?://[^\"'\s]+/jmpres/[^\"'\s]+\.mp4[^\"'\s]*)", html, re.I)
        if m:
            return m.group(1).replace("&amp;", "&")
        m = re.search(r"(https?://[^\"'\s]+\.m3u8[^\"'\s]*)", html, re.I)
        if m:
            return m.group(1).replace("&amp;", "&")
        return ""

    def homeContent(self, filter):
        classes = [
            {"type_name": "亚洲", "type_id": "asian"},
            {"type_name": "日本", "type_id": "japanese"},
            {"type_name": "业余", "type_id": "amateur"},
            {"type_name": "MILF", "type_id": "milf"},
            {"type_name": "青春", "type_id": "teen"},
            {"type_name": "肛交", "type_id": "anal"},
            {"type_name": "巨乳", "type_id": "big-tits"},
            {"type_name": "丰臀", "type_id": "big-ass"},
            {"type_name": "黑人", "type_id": "ebony"},
            {"type_name": "女同", "type_id": "lesbian"},
            {"type_name": "3P", "type_id": "threesome"},
            {"type_name": "POV", "type_id": "pov"},
            {"type_name": "动漫", "type_id": "hentai"},
            {"type_name": "恋物", "type_id": "fetish"},
            {"type_name": "公开", "type_id": "public"},
            {"type_name": "潮吹", "type_id": "squirting"},
        ]
        return {"class": classes}

    def homeVideoContent(self):
        res = self._fetch(self.siteUrl + "/")
        return {"list": self._parse_cards(res.get("text", ""))[:24]}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg or 1)
        tid = str(tid or "asian").strip().lstrip("/")
        target = self.siteUrl + "/" + tid
        if page > 1:
            target += "/%d" % page
        res = self._fetch(target)
        vod_list = self._parse_cards(res.get("text", ""))
        return {
            "page": page,
            "pagecount": page + 1 if len(vod_list) >= 20 else page,
            "limit": 24,
            "total": 9999,
            "list": vod_list,
        }

    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) else str(ids)
        target = raw_id if str(raw_id).startswith("http") else self._abs(raw_id)
        res = self._fetch(target)
        html = res.get("text", "")
        title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I)
        name = self._clean_text(title_m.group(1).split("|")[0].split("-")[0]) if title_m else "视频"
        pic = ""
        pm = re.search(r'thumbnailUrl["\']?\s*:\s*["\']([^"\']+)["\']', html, re.I) or re.search(
            r'property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I
        )
        if pm:
            pic = self._abs(pm.group(1))
        play = self._extract_play(html)
        return {
            "list": [
                {
                    "vod_id": raw_id,
                    "vod_name": name,
                    "vod_pic": pic,
                    "vod_content": "",
                    "vod_remarks": "",
                    "vod_play_from": "在线播放",
                    "vod_play_url": "正片$%s" % (play or target),
                }
            ]
        }

    def playerContent(self, flag, id, vipFlags):
        headers = {
            "User-Agent": self._ua,
            "Referer": self.siteUrl + "/",
            "Accept": "*/*",
        }
        raw = str(id or "").strip()
        if "$" in raw:
            raw = raw.split("$")[-1].strip()
        if raw.startswith("http") and (".mp4" in raw.lower() or ".m3u8" in raw.lower()):
            return {"parse": 0, "jx": 0, "url": raw, "header": headers}
        target = raw if raw.startswith("http") else self._abs(raw)
        res = self._fetch(target)
        play = self._extract_play(res.get("text", ""))
        if play:
            return {"parse": 0, "jx": 0, "url": play, "header": headers}
        return {"parse": 0, "jx": 0, "url": "", "header": headers}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg or 1)
        key = str(key or "").strip()
        if not key:
            return {"list": []}
        path = "/search?q=%s" % urllib.parse.quote(key)
        if page > 1:
            path += "&page=%d" % page
        res = self._fetch(self.siteUrl + path)
        vod_list = self._parse_cards(res.get("text", ""))
        return {
            "page": page,
            "pagecount": page + 1 if len(vod_list) >= 20 else page,
            "limit": 24,
            "total": 9999,
            "list": vod_list,
        }

    def localProxy(self, params):
        return [404, "text/plain", b"Not Found"]
