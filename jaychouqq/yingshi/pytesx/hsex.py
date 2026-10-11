#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
片吧365 / HSEX · https://hsex01.com
按 91porna.py 风格：列表 + 直出 m3u8
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
        self.siteUrl = "https://hsex01.com"
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
        self.categoryRoutes = {
            "list": "/list-{page}.htm",
            "top7_list": "/top7_list-{page}.htm",
            "top_list": "/top_list-{page}.htm",
            "5min_list": "/5min_list-{page}.htm",
            "long_list": "/long_list-{page}.htm",
        }

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
        return "片吧365"

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
            "Referer": referer or (self.siteUrl + "/enter"),
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
            r'href=["\'](video-(\d+)\.htm)["\'][\s\S]{0,80}?'
            r"background-image:\s*url\(['\"]?([^)'\"]+)['\"]?\)"
            r'[\s\S]{0,200}?title=["\']([^"\']+)["\']'
            r'[\s\S]{0,300}?duration">\s*([^<]*)<',
            re.I,
        )
        for m in pattern.finditer(html):
            vid = m.group(2)
            if vid in seen:
                continue
            seen.add(vid)
            vod_list.append(
                {
                    "vod_id": self._abs(m.group(1)),
                    "vod_name": self._clean_text(m.group(4)) or ("视频" + vid),
                    "vod_pic": self._abs(m.group(3)),
                    "vod_remarks": self._clean_text(m.group(5)),
                    "style": {"type": "rect", "ratio": 1.78},
                }
            )
        if vod_list:
            return vod_list
        pattern2 = re.compile(
            r'href=["\'](video-(\d+)\.htm)["\'][\s\S]{0,400}?title=["\']([^"\']+)["\']',
            re.I,
        )
        for m in pattern2.finditer(html):
            vid = m.group(2)
            if vid in seen:
                continue
            seen.add(vid)
            block = html[m.start() : m.start() + 600]
            img_m = re.search(r"background-image:\s*url\(['\"]?([^)'\"]+)['\"]?\)", block, re.I)
            dur_m = re.search(r'duration">\s*([^<]*)<', block, re.I)
            vod_list.append(
                {
                    "vod_id": self._abs(m.group(1)),
                    "vod_name": self._clean_text(m.group(3)) or ("视频" + vid),
                    "vod_pic": self._abs(img_m.group(1)) if img_m else "",
                    "vod_remarks": self._clean_text(dur_m.group(1)) if dur_m else "",
                    "style": {"type": "rect", "ratio": 1.78},
                }
            )
        return vod_list

    def _extract_m3u8(self, html):
        if not html:
            return ""
        m = re.search(r"video_url=([^&\"'\s]+)", html, re.I)
        if m:
            try:
                u = urllib.parse.unquote(m.group(1)).replace("&amp;", "&").strip()
                if ".m3u8" in u.lower():
                    return self._abs(u)
            except Exception:
                pass
        m = re.search(r"(https?://[^\"'\s]+\.m3u8[^\"'\s]*)", html, re.I)
        if m:
            return m.group(1).replace("&amp;", "&")
        m = re.search(r"(/jmpres/[^\"'\s]+\.m3u8[^\"'\s]*)", html, re.I)
        if m:
            return self._abs(m.group(1))
        return ""

    def homeContent(self, filter):
        classes = [
            {"type_name": "最新", "type_id": "list"},
            {"type_name": "周榜", "type_id": "top7_list"},
            {"type_name": "月榜", "type_id": "top_list"},
            {"type_name": "5分钟+", "type_id": "5min_list"},
            {"type_name": "10分钟+", "type_id": "long_list"},
            {"type_name": "探花", "type_id": "search@探花"},
            {"type_name": "女神", "type_id": "search@女神"},
            {"type_name": "少妇", "type_id": "search@少妇"},
            {"type_name": "模特", "type_id": "search@模特"},
            {"type_name": "做爱", "type_id": "search@做爱"},
            {"type_name": "东莞", "type_id": "search@东莞"},
            {"type_name": "大奶", "type_id": "search@大奶"},
        ]
        return {"class": classes}

    def homeVideoContent(self):
        res = self._fetch(self.siteUrl + "/list-1.htm")
        return {"list": self._parse_cards(res.get("text", ""))[:20]}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg or 1)
        tid = str(tid or "list").strip()
        if tid.startswith("search@"):
            kw = tid[7:]
            path = "/search.htm?search=%s&sort=new" % urllib.parse.quote(kw)
            if page > 1:
                path += "&page=%d" % page
            target = self.siteUrl + path
        else:
            tpl = self.categoryRoutes.get(tid, "/list-{page}.htm")
            target = self.siteUrl + tpl.replace("{page}", str(page))
        res = self._fetch(target)
        vod_list = self._parse_cards(res.get("text", ""))
        return {
            "page": page,
            "pagecount": page + 1 if len(vod_list) >= 15 else page,
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
        name = self._clean_text(title_m.group(1).split("-")[0].split("_")[0]) if title_m else "视频"
        pic = ""
        pm = re.search(r"poster_url=([^&\"'\s]+)", html, re.I)
        if pm:
            try:
                pic = self._abs(urllib.parse.unquote(pm.group(1)))
            except Exception:
                pic = self._abs(pm.group(1))
        m3u8 = self._extract_m3u8(html)
        play_url = "正片$%s" % (m3u8 or target)
        return {
            "list": [
                {
                    "vod_id": raw_id,
                    "vod_name": name,
                    "vod_pic": pic,
                    "vod_content": "",
                    "vod_remarks": "",
                    "vod_play_from": "在线播放",
                    "vod_play_url": play_url,
                }
            ]
        }

    def playerContent(self, flag, id, vipFlags):
        headers = {
            "User-Agent": self._ua,
            "Referer": self.siteUrl + "/",
            "Origin": self.siteUrl,
        }
        raw = str(id or "").strip()
        if "$" in raw:
            raw = raw.split("$")[-1].strip()
        if raw.startswith("http") and (".m3u8" in raw.lower() or ".mp4" in raw.lower()):
            return {"parse": 0, "jx": 0, "url": raw, "header": headers}
        target = raw if raw.startswith("http") else self._abs(raw)
        res = self._fetch(target)
        m3u8 = self._extract_m3u8(res.get("text", ""))
        if m3u8:
            return {"parse": 0, "jx": 0, "url": m3u8, "header": headers}
        return {"parse": 0, "jx": 0, "url": "", "header": headers}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg or 1)
        key = str(key or "").strip()
        if not key:
            return {"list": []}
        path = "/search.htm?search=%s&sort=new" % urllib.parse.quote(key)
        if page > 1:
            path += "&page=%d" % page
        res = self._fetch(self.siteUrl + path)
        vod_list = self._parse_cards(res.get("text", ""))
        return {
            "page": page,
            "pagecount": page + 1 if len(vod_list) >= 15 else page,
            "limit": 24,
            "total": 9999,
            "list": vod_list,
        }

    def localProxy(self, params):
        return [404, "text/plain", b"Not Found"]
