#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OKXXX · https://okxxxx.net
按 rou123.py 风格：列表 + source 多清晰度直出
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
        self.siteUrl = "https://okxxxx.net"
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
        return "OKXXX"

    def isVideoFormat(self, url):
        if not url:
            return False
        low = url.lower()
        return any(k in low for k in (".m3u8", ".mp4", "get_file", ".flv", ".ts"))

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
            r'href=["\']([^"\']*/video/\d+/?)["\'][^>]*title=["\']([^"\']*)["\']'
            r'[\s\S]{0,800}?data-original=["\']([^"\']+)["\']',
            re.I,
        )
        for m in pattern.finditer(html):
            href = self._abs(m.group(1))
            if href in seen:
                continue
            seen.add(href)
            vod_list.append(
                {
                    "vod_id": href,
                    "vod_name": self._clean_text(m.group(2)) or "视频",
                    "vod_pic": self._abs(m.group(3)),
                    "vod_remarks": "",
                    "style": {"type": "rect", "ratio": 1.78},
                }
            )
        if vod_list:
            return vod_list
        pattern2 = re.compile(
            r'href=["\']([^"\']*/video/\d+/?)["\'][\s\S]{0,500}?alt=["\']([^"\']+)["\']'
            r'[\s\S]{0,200}?data-original=["\']([^"\']+)["\']',
            re.I,
        )
        for m in pattern2.finditer(html):
            href = self._abs(m.group(1))
            if href in seen:
                continue
            seen.add(href)
            vod_list.append(
                {
                    "vod_id": href,
                    "vod_name": self._clean_text(m.group(2)) or "视频",
                    "vod_pic": self._abs(m.group(3)),
                    "vod_remarks": "",
                    "style": {"type": "rect", "ratio": 1.78},
                }
            )
        return vod_list

    def _extract_qualities(self, html):
        out = []
        seen = set()
        if not html:
            return out
        for m in re.finditer(
            r'<source[^>]+src=["\']([^"\']+)["\'][^>]*(?:title|label)=["\']([^"\']+)["\']',
            html,
            re.I,
        ):
            name = self._clean_text(m.group(2))
            if not name or re.search(r"auto", name, re.I) or name in seen:
                continue
            if re.search(r"preview", m.group(1), re.I):
                continue
            seen.add(name)
            out.append({"name": name, "url": self._abs(m.group(1).replace("&amp;", "&"))})
        for m in re.finditer(
            r'<source[^>]*(?:title|label)=["\']([^"\']+)["\'][^>]+src=["\']([^"\']+)["\']',
            html,
            re.I,
        ):
            name = self._clean_text(m.group(1))
            if not name or re.search(r"auto", name, re.I) or name in seen:
                continue
            if re.search(r"preview", m.group(2), re.I):
                continue
            seen.add(name)
            out.append({"name": name, "url": self._abs(m.group(2).replace("&amp;", "&"))})
        if not out:
            names = ["720p", "480p", "360p"]
            i = 0
            for m in re.finditer(r"https?://[^\"'\s]+get_file/[^\"'\s]+\.mp4/?", html, re.I):
                u = m.group(0)
                if re.search(r"preview", u, re.I) or u in seen:
                    continue
                seen.add(u)
                out.append({"name": names[i] if i < len(names) else "线路%d" % (i + 1), "url": u})
                i += 1

        def score(n):
            if "1080" in n:
                return 4
            if "720" in n:
                return 3
            if "480" in n:
                return 2
            if "360" in n:
                return 1
            return 0

        out.sort(key=lambda x: score(x["name"]), reverse=True)
        return out

    def homeContent(self, filter):
        classes = [
            {"type_name": "最新", "type_id": ""},
            {"type_name": "热门", "type_id": "popular"},
            {"type_name": "趋势", "type_id": "trending"},
            {"type_name": "Brazzers", "type_id": "sites/brazzers"},
            {"type_name": "Naughty America", "type_id": "sites/naughty-america"},
            {"type_name": "RealityKings", "type_id": "sites/realitykings"},
            {"type_name": "BangBros", "type_id": "sites/bangbros"},
            {"type_name": "Blacked", "type_id": "sites/blacked-com"},
            {"type_name": "TeamSkeet", "type_id": "sites/teamskeet"},
            {"type_name": "Nubiles", "type_id": "sites/nubiles-porn"},
            {"type_name": "Bang", "type_id": "sites/bang"},
            {"type_name": "Scoreland", "type_id": "sites/scoreland"},
        ]
        return {"class": classes}

    def homeVideoContent(self):
        res = self._fetch(self.siteUrl + "/enter")
        return {"list": self._parse_cards(res.get("text", ""))[:24]}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg or 1)
        tid = str(tid or "").strip().strip("/")
        if not tid:
            target = self.siteUrl + ("/%d/" % page if page > 1 else "/enter")
        else:
            target = self.siteUrl + "/" + tid + "/"
            if page > 1:
                target = self.siteUrl + "/" + tid + "/%d/" % page
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
        name = "视频"
        if title_m:
            name = self._clean_text(title_m.group(1).replace("🌶️", "").split("-")[0].split("|")[0])
        pic = ""
        pm = re.search(r'property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I) or re.search(
            r'data-original=["\']([^"\']+)["\']', html, re.I
        )
        if pm:
            pic = self._abs(pm.group(1))
        quals = self._extract_qualities(html)
        if quals:
            play_from = [q["name"] for q in quals]
            play_url = ["正片$%s" % q["url"] for q in quals]
        else:
            play_from = ["在线播放"]
            play_url = ["正片$%s" % target]
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
        if raw.startswith("http") and ("get_file" in raw or ".mp4" in raw.lower() or ".m3u8" in raw.lower()):
            return {"parse": 0, "jx": 0, "url": raw, "header": headers}
        target = raw if raw.startswith("http") else self._abs(raw)
        res = self._fetch(target)
        quals = self._extract_qualities(res.get("text", ""))
        if quals:
            chosen = quals[0]["url"]
            if flag:
                for q in quals:
                    if str(flag) in q["name"] or q["name"] in str(flag):
                        chosen = q["url"]
                        break
            return {"parse": 0, "jx": 0, "url": chosen, "header": headers}
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
            "pagecount": page + 1 if len(vod_list) >= 20 else page,
            "limit": 24,
            "total": 9999,
            "list": vod_list,
        }

    def localProxy(self, params):
        return [404, "text/plain", b"Not Found"]
