#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rouAV 肉视频 · https://rou123.ws
按 hsex.py 风格：MacCMS 列表 + player_aaaa base64 → /api/v/ → m3u8 直出
"""
import re
import json
import base64
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
        self.siteUrl = "https://rou123.ws"
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
        return "rouAV肉视频"

    def isVideoFormat(self, url):
        if not url:
            return False
        low = url.lower()
        return any(k in low for k in (".m3u8", ".mp4", "/api/hls/", ".flv", ".ts"))

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
        parts = re.split(r'class="movie-item', html, flags=re.I)
        for block in parts[1:]:
            block = block[:1500]
            hm = re.search(r'href=["\']([^"\']*vodplay/\d+[^"\']*)["\']', block, re.I)
            if not hm:
                continue
            href = hm.group(1)
            if href in seen:
                continue
            seen.add(href)
            title = ""
            alt = re.search(r'alt=["\']([^"\']+)["\']', block, re.I)
            h3 = re.search(r"<h3[^>]*>[\s\S]*?<a[^>]*>([\s\S]*?)</a>", block, re.I) or re.search(
                r"<h3[^>]*>([\s\S]*?)</h3>", block, re.I
            )
            if alt:
                title = self._clean_text(alt.group(1))
            elif h3:
                title = self._clean_text(h3.group(1))
            pic = ""
            img = re.search(r'<img[^>]+(?:src|data-src)=["\']([^"\']+)["\']', block, re.I)
            if img:
                pic = self._abs(img.group(1))
            dur = ""
            dm = re.search(r'movie-duration-span[^>]*>([^<]+)<', block, re.I) or re.search(
                r"(\d{1,2}:\d{2}(?::\d{2})?)", block
            )
            if dm:
                dur = self._clean_text(dm.group(1))
            vod_list.append(
                {
                    "vod_id": self._abs(href),
                    "vod_name": title or "视频",
                    "vod_pic": pic,
                    "vod_remarks": dur,
                    "style": {"type": "rect", "ratio": 1.78},
                }
            )
        return vod_list

    def _resolve_m3u8(self, page_url):
        res = self._fetch(page_url)
        html = res.get("text", "")
        if not html:
            return ""
        url_field = ""
        pm = re.search(r"var\s+player_[a-zA-Z0-9_]+\s*=\s*(\{[\s\S]*?\})\s*;", html)
        if pm:
            try:
                obj = json.loads(pm.group(1))
                url_field = obj.get("url") or ""
            except Exception:
                pass
        if not url_field:
            m2 = re.search(r'"url"\s*:\s*"(eyJ[^"]+)"', html)
            if m2:
                url_field = m2.group(1)
        if not url_field:
            return ""
        api_path = ""
        try:
            raw = url_field
            if re.match(r"^[A-Za-z0-9+/=]{20,}$", url_field):
                raw = base64.b64decode(url_field).decode("utf-8", "ignore")
            j = json.loads(raw)
            if isinstance(j, dict):
                ss = j.get("ss")
                if ss and isinstance(ss, list) and ss[0]:
                    api_path = ss[0][1] if isinstance(ss[0], (list, tuple)) else str(ss[0])
                elif j.get("url"):
                    api_path = j.get("url")
        except Exception:
            if url_field.startswith("/api/"):
                api_path = url_field
        if not api_path:
            return ""
        api_url = self._abs(api_path)
        api_res = self._fetch(api_url, page_url)
        body = api_res.get("text", "")
        if not body:
            return ""
        try:
            j2 = json.loads(body)
            vu = ""
            if isinstance(j2.get("video"), dict):
                vu = j2["video"].get("videoUrl") or ""
            vu = vu or j2.get("videoUrl") or j2.get("url") or ""
            if vu:
                return self._abs(vu)
        except Exception:
            m3 = re.search(r"(https?://[^\"'\s]+\.m3u8[^\"'\s]*)", body, re.I)
            if m3:
                return m3.group(1)
        return ""

    def homeContent(self, filter):
        classes = [
            {"type_name": "国产AV", "type_id": "7"},
            {"type_name": "日本", "type_id": "3"},
            {"type_name": "自拍流出", "type_id": "6"},
            {"type_name": "探花", "type_id": "5"},
            {"type_name": "OnlyFans", "type_id": "4"},
            {"type_name": "其他", "type_id": "1"},
        ]
        return {"class": classes}

    def homeVideoContent(self):
        res = self._fetch(self.siteUrl + "/vodtype/7.html")
        return {"list": self._parse_cards(res.get("text", ""))[:20]}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg or 1)
        tid = str(tid or "7").strip()
        if page == 1:
            target = self.siteUrl + "/vodtype/%s.html" % urllib.parse.quote(tid)
        else:
            target = self.siteUrl + "/vod/show/id/%s/page/%d.html" % (
                urllib.parse.quote(tid),
                page,
            )
        res = self._fetch(target)
        vod_list = self._parse_cards(res.get("text", ""))
        if not vod_list and page == 1:
            target = self.siteUrl + "/vod/show/id/%s/page/1.html" % urllib.parse.quote(tid)
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
        name = self._clean_text(title_m.group(1).split("_")[0].split("-")[0]) if title_m else "视频"
        pic = ""
        pm = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.I)
        if pm:
            pic = self._abs(pm.group(1))
        m3u8 = self._resolve_m3u8(target)
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
        if raw.startswith("http") and (
            ".m3u8" in raw.lower() or "/api/hls/" in raw.lower() or ".mp4" in raw.lower()
        ):
            return {"parse": 0, "jx": 0, "url": raw, "header": headers}
        target = raw if raw.startswith("http") else self._abs(raw)
        m3u8 = self._resolve_m3u8(target)
        if m3u8:
            return {"parse": 0, "jx": 0, "url": m3u8, "header": headers}
        return {"parse": 0, "jx": 0, "url": "", "header": headers}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg or 1)
        key = str(key or "").strip()
        if not key:
            return {"list": []}
        path = "/vod/search.html?wd=%s" % urllib.parse.quote(key)
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
