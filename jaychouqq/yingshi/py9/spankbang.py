# -*- coding: utf-8 -*-

"""
SpankBang Chaquopy Python Spider for TVBox / CatVod
遵循 Type 3 原生點播爬蟲規範 (Cloudflare Cookie 穿透與滑動視窗容錯版)
"""

import gzip
import json
import re
import ssl
import urllib.request
import urllib.parse
import urllib.error
import zlib

from base.spider import Spider as BaseSpider

class Spider(BaseSpider):
    HOST = 'https://spankbang.com'
    USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'

    def getName(self):
        return "SpankBang"

    def init(self, extend=""):
        self.site_url = self.HOST
        if isinstance(extend, str) and extend.startswith("http"):
            self.site_url = extend.rstrip('/')
        elif isinstance(extend, dict):
            url = extend.get("site_url") or extend.get("host") or extend.get("ext")
            if url and str(url).startswith("http"):
                self.site_url = str(url).rstrip('/')

    def _get_cookie_from_android(self):
        """嘗試從 Android 系統 CookieManager 讀取過盾後的 cf_clearance Cookie"""
        try:
            from android.webkit import CookieManager
            cm = CookieManager.getInstance()
            cookie_str = cm.getCookie(self.site_url)
            if cookie_str:
                return cookie_str
        except Exception:
            pass
        return ""

    def _get_headers(self):
        cookie = 'country=US; mobile=off; age_verified=1'
        android_cookie = self._get_cookie_from_android()
        if android_cookie:
            cookie = f"{cookie}; {android_cookie}"

        return {
            'User-Agent': self.USER_AGENT,
            'Referer': f"{self.site_url}/",
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cookie': cookie
        }

    def _fetch(self, url):
        """雙級 HTTP 請求引擎：Java OkHttp (帶 Cookie/代理) -> 原生 urllib"""
        headers = self._get_headers()

        # 第一順位：TVBox 內建 Java OkHttp (完美支援 Android 系統 Cookie 與代理)
        try:
            from com.github.catvod.net import OkHttp
            from java.util import HashMap
            j_headers = HashMap()
            for k, v in headers.items():
                j_headers.put(k, v)
            resp = OkHttp.string(url, j_headers)
            if resp and len(resp) > 50:
                res_str = str(resp)
                if "Just a moment..." in res_str or "Enable JavaScript" in res_str:
                    return ""
                return res_str
        except Exception:
            pass

        # 第二順位：urllib 標準庫 (設定 5 秒嚴格超時)
        try:
            req = urllib.request.Request(url, headers=headers)
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            with urllib.request.urlopen(req, timeout=5, context=ctx) as response:
                content = response.read()
                encoding = response.info().get('Content-Encoding', '').lower()

                if 'gzip' in encoding:
                    content = gzip.decompress(content)
                elif 'deflate' in encoding:
                    content = zlib.decompress(content)

                res_text = content.decode('utf-8', errors='ignore')
                if res_text and len(res_text) > 50:
                    if "Just a moment..." in res_text or "Enable JavaScript" in res_text:
                        return ""
                    return res_text
        except Exception:
            pass

        return ""

    def _parse_vod_list(self, html):
        """無盲點滑動視窗 (Chunk-Window) 影片卡片解析引擎"""
        if not html:
            return []

        list_data = []
        seen_ids = set()

        matches = list(re.finditer(r'href=["\'](?:https?://[^/]+)?/([a-zA-Z0-9]{3,12})/video(?:/([^"\']*))?["\']', html, re.I))

        for m in matches:
            vid = m.group(1)
            slug = m.group(2) or ""
            if vid in seen_ids:
                continue

            start_pos = max(0, m.start() - 300)
            end_pos = min(len(html), m.end() + 800)
            chunk = html[start_pos:end_pos]

            img = ""
            img_match = re.search(r'(?:data-src|data-thumbnail|data-original|src)=["\']([^"\']+\.(?:jpg|jpeg|png|webp)[^"\']*)["\']', chunk, re.I)
            if not img_match:
                img_match = re.search(r'(?:data-src|data-thumbnail|data-original|src)=["\']([^"\']+)["\']', chunk, re.I)
            
            if img_match:
                img = img_match.group(1)
                if img.startswith('//'):
                    img = 'https:' + img
                elif img.startswith('/'):
                    img = self.site_url + img

            title = ""
            title_match = (
                re.search(r'class=["\']title["\'][^>]*title=["\']([^"\']+)["\']', chunk, re.I) or
                re.search(r'class=["\']title["\'][^>]*>([^<]+)<', chunk, re.I) or
                re.search(r'alt=["\']([^"\']+)["\']', chunk, re.I) or
                re.search(r'title=["\']([^"\']+)["\']', chunk, re.I)
            )
            if title_match:
                title = title_match.group(1).strip()
            
            if not title or len(title) < 2 or title.lower() in ['video', 'watch', 'play']:
                if slug:
                    clean_slug = urllib.parse.unquote(slug).replace('+', ' ').replace('-', ' ').strip()
                    if clean_slug:
                        title = clean_slug.title()
                if not title:
                    title = f"Video {vid}"

            remarks = ""
            duration_match = re.search(r'class=["\'](?:l|length|duration|n)["\'][^>]*>([^<]+)<', chunk, re.I)
            if duration_match:
                remarks = duration_match.group(1).strip()
            else:
                dur_fmt = re.search(r'\b(\d{1,2}:\d{2}(?::\d{2})?)\b', chunk)
                if dur_fmt:
                    remarks = dur_fmt.group(1)

            seen_ids.add(vid)
            list_data.append({
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': img,
                'vod_remarks': remarks
            })

        return list_data

    def homeContent(self, filter=False):
        classes = [
            {'type_id': 'trending_videos', 'type_name': 'Trending'},
            {'type_id': 'most_popular', 'type_name': 'Most Popular'},
            {'type_id': 'new_videos', 'type_name': 'New Videos'},
            {'type_id': 'upcoming', 'type_name': 'Upcoming'},
            {'type_id': 'top_rated', 'type_name': 'Top Rated'}
        ]
        return {
            'class': classes,
            'filters': {}
        }

    def homeVideoContent(self):
        html = self._fetch(f"{self.site_url}/trending_videos/")
        vods = self._parse_vod_list(html)
        return {'list': vods[:12] if vods else []}

    def categoryContent(self, tid, pg=1, filter=False, extend=None):
        page = int(pg) if pg and str(pg).isdigit() else 1

        if page == 1:
            url = f"{self.site_url}/{tid}/"
        else:
            url = f"{self.site_url}/{tid}/{page}/"

        html = self._fetch(url)
        vods = self._parse_vod_list(html)

        return {
            'page': page,
            'pagecount': page + 1 if vods else page,
            'limit': len(vods),
            'total': 999,
            'list': vods
        }

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, list) else ids
        video_url = f"{self.site_url}/{vid}/video/"
        html = self._fetch(video_url)

        title_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html, re.I)
        title = title_match.group(1).strip() if title_match else vid

        img_match = (
            re.search(r'poster=["\']([^"\']+)["\']', html, re.I) or
            re.search(r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', html, re.I)
        )
        img = img_match.group(1) if img_match else ''
        if img.startswith('//'):
            img = 'https:' + img

        play_url = f"{title}${vid}"

        vod = {
            'vod_id': vid,
            'vod_name': title,
            'vod_pic': img,
            'vod_type': 'Adult',
            'vod_play_from': 'SpankBang',
            'vod_play_url': play_url
        }

        return {'list': [vod]}

    def searchContent(self, key, quick=False, pg="1"):
        page = int(pg) if pg and str(pg).isdigit() else 1
        search_url = f"{self.site_url}/s/{urllib.parse.quote(key)}/{page}/"
        html = self._fetch(search_url)
        vods = self._parse_vod_list(html)

        return {
            'page': page,
            'pagecount': page + 1 if vods else page,
            'list': vods
        }

    def playerContent(self, flag, id, vipFlags=None):
        video_url = f"{self.site_url}/{id}/video/"
        html = self._fetch(video_url)

        stream_matches = re.findall(r'var\s+stream_url_([a-zA-Z0-9]+)\s*=\s*[\'"]([^\'"]+)[\'"]', html, re.I)

        if stream_matches:
            best_stream = stream_matches[-1][1]
            return {
                'parse': 0,
                'url': best_stream,
                'header': self._get_headers()
            }

        return {
            'parse': 1,
            'url': video_url,
            'header': self._get_headers()
        }

    def manualVideoCheck(self):
        return True

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(mp4|m3u8|flv|mkv)', url, re.I))

    def destroy(self):
        pass