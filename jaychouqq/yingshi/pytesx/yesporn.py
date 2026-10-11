#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YesPorn · https://cn.yesporn.ws
修复：分类标题 + 通过 view_video_download 直出真实 MP4
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
        self.siteUrl = "https://cn.yesporn.ws"
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
        return "YesPorn"

    def isVideoFormat(self, url):
        if not url:
            return False
        low = url.lower()
        return any(k in low for k in (".m3u8", ".mp4", "get_file", "download=true", ".flv", ".ts"))

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
        u = str(u).strip().replace("&amp;", "&")
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
            with self.opener.open(req, timeout=18) as resp:
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
            r'<a[^>]+href=["\']([^"\']*/video/\d+/[^"\']*)["\'][^>]*title=["\']([^"\']+)["\'][^>]*>',
            re.I,
        )
        for m in pattern.finditer(html):
            href = self._abs(m.group(1).split("#")[0])
            if href in seen:
                continue
            seen.add(href)
            block = html[m.start() : m.start() + 900]
            img = re.search(r'data-original=["\']([^"\']+)["\']', block, re.I) or re.search(
                r'data-webp=["\']([^"\']+)["\']', block, re.I
            )
            dur = re.search(r"item-time[^>]*>([^<]*)<", block, re.I)
            vod_list.append(
                {
                    "vod_id": href,
                    "vod_name": self._clean_text(m.group(2)) or "视频",
                    "vod_pic": self._abs(img.group(1)) if img else "",
                    "vod_remarks": self._clean_text(dur.group(1)) if dur else "",
                    "style": {"type": "rect", "ratio": 1.78},
                }
            )
        if vod_list:
            return vod_list
        pattern2 = re.compile(
            r'<a[^>]+title=["\']([^"\']+)["\'][^>]+href=["\']([^"\']*/video/\d+/[^"\']*)["\'][^>]*>',
            re.I,
        )
        for m in pattern2.finditer(html):
            href = self._abs(m.group(2).split("#")[0])
            if href in seen:
                continue
            seen.add(href)
            block = html[m.start() : m.start() + 900]
            img = re.search(r'data-original=["\']([^"\']+)["\']', block, re.I)
            vod_list.append(
                {
                    "vod_id": href,
                    "vod_name": self._clean_text(m.group(1)) or "视频",
                    "vod_pic": self._abs(img.group(1)) if img else "",
                    "vod_remarks": "",
                    "style": {"type": "rect", "ratio": 1.78},
                }
            )
        return vod_list

    def _video_id(self, url):
        m = re.search(r"/video/(\d+)", str(url or ""))
        return m.group(1) if m else ""

    def _resolve_download(self, vid, fmt):
        if not vid:
            return ""
        page = "%s/view_video_download.php?id=%s&format=%s" % (self.siteUrl, vid, fmt)
        res = self._fetch(page, self.siteUrl + "/video/%s/" % vid)
        html = res.get("text", "")
        if not html:
            return ""
        m = re.search(
            r"https?://[^\"'\\\s]+get_file/[^\"'\\\s]+\.mp4/\?[^\"'\\\s]*download=true[^\"'\\\s]*",
            html,
            re.I,
        )
        if m:
            return self._abs(m.group(0))
        m2 = re.search(r"https?://[^\"'\\\s]+get_file/[^\"'\\\s]+\.mp4[^\"'\\\s]*", html, re.I)
        return self._abs(m2.group(0)) if m2 else ""

    def _extract_qualities(self, html, page_url):
        out = []
        seen = set()
        vid = self._video_id(page_url)
        formats = []
        for m in re.finditer(
            r'href=["\']([^"\']*view_video_download\.php\?id=\d+&(?:amp;)?format=(\d+))["\']',
            html or "",
            re.I,
        ):
            fmt = m.group(2)
            if fmt not in seen:
                seen.add(fmt)
                formats.append(fmt)
        if not formats:
            formats = ["1080", "720", "480"]
        formats.sort(key=lambda x: int(x), reverse=True)
        for fmt in formats:
            if not vid:
                break
            url = self._resolve_download(vid, fmt)
            if url:
                out.append({"name": fmt + "p", "url": url})
        return out

    def homeContent(self, filter):
        classes = [
            {"type_name": "最新", "type_id": "latest-updates"},
            {"type_name": "高分", "type_id": "top-rated"},
            {"type_name": "热门", "type_id": "most-popular"},
            {"type_name": "MILF", "type_id": "categories/milf"},
            {"type_name": "肛交", "type_id": "categories/anal"},
            {"type_name": "丰臀", "type_id": "categories/big-ass"},
            {"type_name": "巨乳", "type_id": "categories/big-tits"},
            {"type_name": "成熟", "type_id": "categories/mature"},
            {"type_name": "拉丁", "type_id": "categories/latina"},
            {"type_name": "BBW", "type_id": "categories/bbw"},
            {"type_name": "亚洲", "type_id": "categories/asian"},
            {"type_name": "女同", "type_id": "categories/lesbian"},
            {"type_name": "青春", "type_id": "categories/teen"},
            {"type_name": "金发", "type_id": "categories/blonde"},
        ]
        return {"class": classes}

    def homeVideoContent(self):
        res = self._fetch(self.siteUrl + "/latest-updates/")
        return {"list": self._parse_cards(res.get("text", ""))[:24]}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg or 1)
        tid = str(tid or "latest-updates").strip().strip("/")
        if page > 1:
            target = "%s/%s/%d/" % (self.siteUrl, tid, page)
        else:
            target = "%s/%s/" % (self.siteUrl, tid)
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
        name = self._clean_text(title_m.group(1).split("|")[0].split("-")[0]) if title_m else "视频"
        pic = ""
        pm = re.search(r'property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I) or re.search(
            r"preview_url:\s*'([^']+)'", html
        )
        if pm:
            pic = self._abs(pm.group(1))
        quals = self._extract_qualities(html, target)
        if quals:
            play_from = [q["name"] for q in quals]
            play_url = ["正片$%s" % q["url"] for q in quals]
        else:
            vid = self._video_id(target)
            play_from = ["720p", "1080p", "480p"]
            play_url = ["正片$dl:%s:720" % vid, "正片$dl:%s:1080" % vid, "正片$dl:%s:480" % vid]
        return {
            "list": [
                {
                    "vod_id": raw_id,
                    "vod_name": name,
                    "vod_pic": pic,
                    "vod_content": "",
                    "vod_remarks": "",
                    "vod_play_from": "$$$".join(play_from),
                    "vod_play_url": "$$$".join(play_url),
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
        if re.match(r"^dl:\d+:\d+$", raw, re.I):
            parts = raw.split(":")
            url = self._resolve_download(parts[1], parts[2])
            return {"parse": 0, "jx": 0, "url": url or "", "header": headers}
        if raw.startswith("http") and ("get_file" in raw or ".mp4" in raw.lower() or ".m3u8" in raw.lower()):
            return {"parse": 0, "jx": 0, "url": raw, "header": headers}
        target = raw if raw.startswith("http") else self._abs(raw)
        res = self._fetch(target)
        quals = self._extract_qualities(res.get("text", ""), target)
        if quals:
            chosen = quals[0]["url"]
            if flag:
                for q in quals:
                    if str(flag) in q["name"] or q["name"] in str(flag):
                        chosen = q["url"]
                        break
            return {"parse": 0, "jx": 0, "url": chosen, "header": headers}
        vid = self._video_id(target)
        if vid:
            url = self._resolve_download(vid, "720")
            if url:
                return {"parse": 0, "jx": 0, "url": url, "header": headers}
        return {"parse": 0, "jx": 0, "url": "", "header": headers}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg or 1)
        key = str(key or "").strip()
        if not key:
            return {"list": []}
        if page > 1:
            path = "/search/%d/?q=%s" % (page, urllib.parse.quote(key))
        else:
            path = "/search/?q=%s" % urllib.parse.quote(key)
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
