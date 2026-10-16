# -*- coding: utf-8 -*-
import base64
import html
import http.client
import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from urllib.parse import unquote, urlparse
import hashlib

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        pass

HOST = "https://se.sweetpornos.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# 中文化分类列表
CATEGORIES = [
    {"type_id": "hd-porno", "type_name": "高清视界"},
    {"type_id": "russian", "type_name": "俄罗斯风"},
    {"type_id": "russkaya-ozvuchka", "type_name": "俄语配音"},
    {"type_id": "domashnee", "type_name": "素人自拍"},
    {"type_id": "aziatki", "type_name": "东方诱惑"},
    {"type_id": "anal", "type_name": "后庭盛宴"},
    {"type_id": "studentki", "type_name": "青春女校"},
    {"type_id": "milf", "type_name": "风韵少妇"},
    {"type_id": "zrelye-milfy", "type_name": "极品熟女"},
    {"type_id": "molodye", "type_name": "年轻女孩"},
    {"type_id": "kasting", "type_name": "名优试镜"},
    {"type_id": "grupovoe", "type_name": "多人狂欢"},
    {"type_id": "kukold", "type_name": "绿帽迷局"},
    {"type_id": "kunilingus", "type_name": "舌尖深吻"},
    {"type_id": "anilingus", "type_name": "秘境探幽"},
    {"type_id": "minet", "type_name": "深喉唇齿"},
    {"type_id": "orgazm", "type_name": "高潮绝顶"},
    {"type_id": "konchil-v-pizdu-krempay", "type_name": "内射中出"},
    {"type_id": "dvoynoe-proniknovenie", "type_name": "双管齐下"},
    {"type_id": "negry", "type_name": "巨器狂欢"},
    {"type_id": "blondinki", "type_name": "金发娇娃"},
    {"type_id": "bryunetki", "type_name": "深发尤物"},
    {"type_id": "shatenki", "type_name": "棕发丽人"},
    {"type_id": "redhead", "type_name": "红发天使"},
    {"type_id": "bolshie-siski", "type_name": "巨乳波霸"},
    {"type_id": "bolshie-jopy", "type_name": "丰臀美尻"},
    {"type_id": "fetish", "type_name": "恋物情结"},
    {"type_id": "chulki-i-kolgotki", "type_name": "丝袜美腿"},
    {"type_id": "strapon", "type_name": "假阳支配"},
    {"type_id": "dominirovanie", "type_name": "女王调教"},
    {"type_id": "jestkoe", "type_name": "硬核狂暴"},
    {"type_id": "fisting", "type_name": "深度极限"},
    {"type_id": "izmena", "type_name": "禁忌出轨"},
    {"type_id": "incest", "type_name": "家庭密事"},
    {"type_id": "medsestry", "type_name": "白衣护士"},
    {"type_id": "maid", "type_name": "贴身女仆"},
    {"type_id": "secretaries", "type_name": "职场秘恋"},
    {"type_id": "massaj", "type_name": "精油按摩"},
    {"type_id": "masturbaciya", "type_name": "独奏自慰"},
    {"type_id": "lesbiyanki", "type_name": "百合闺蜜"},
    {"type_id": "porno-podborki", "type_name": "精彩合集"},
    {"type_id": "multiki", "type_name": "动漫二次元"},
    {"type_id": "skrytaya-kamera", "type_name": "针孔偷拍"},
    {"type_id": "beautiful", "type_name": "唯美写真"},
]

# 翻译缓存
_translation_cache = {}
_translation_last_call = 0
_translation_throttle = 0.3


class Spider(BaseSpider):

    def getName(self):
        return "sweetpornos"

    def init(self, extend=""):
        self._video_cache = {}  # 视频缓存，解决seek问题
        return {}

    def _req(self, url, retry=3, timeout=12, referer=None):
        headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": referer if referer else (HOST + "/"),
        }
        for i in range(retry):
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

                req_obj = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req_obj, timeout=timeout, context=ctx) as resp:
                    data = resp.read()
                    for enc in ["utf-8", "gbk", "gb2312", "latin-1"]:
                        try:
                            return data.decode(enc)
                        except Exception:
                            continue
                    return data.decode("utf-8", errors="ignore")
            except Exception:
                if i < retry - 1:
                    time.sleep(0.3)
                else:
                    return ""
        return ""

    def _parse_items(self, html_text):
        items = []
        if not html_text:
            return items

        parts = html_text.split('<div class="col item">')
        for part in parts[1:]:
            next_idx = part.find('<div class="col item">')
            block = part[:next_idx] if next_idx > 0 else part

            for marker in [
                '</div>\n\t\t\t\t\t</div>\n\t\t\t\t</div>',
                '</div>\n\t\t\t\t\t</div>',
                '</div>\n\t\t\t</div>',
            ]:
                idx = block.find(marker)
                if idx > 0:
                    block = block[:idx]
                    break

            href_m = re.search(r'href="([^"]+)"', block)
            title_m = re.search(r'title="([^"]+)"', block)

            pic = ""
            img_candidates = re.findall(r'(?:src|data-src|data-original)="([^"]+)"', block, re.IGNORECASE)
            for cand in img_candidates:
                if "base64" in cand or cand.endswith(".gif"):
                    continue
                if re.search(r'\.(?:jpg|png|webp|jpeg)', cand, re.IGNORECASE):
                    pic = cand
                    break

            if not pic:
                fallback_m = re.search(r'https?://[^"]+\.(?:jpg|png|webp|jpeg)', block, re.IGNORECASE)
                if fallback_m:
                    pic = fallback_m.group(0)

            vals = re.findall(r'<span\s+class="value">([^<]*)</span>', block)
            dur = vals[2].strip() if len(vals) >= 3 else ""

            if not href_m or not title_m:
                continue

            v_url = href_m.group(1)
            if v_url.startswith("//"):
                v_url = "https:" + v_url
            elif v_url.startswith("/"):
                v_url = HOST + v_url

            if pic.startswith("//"):
                pic = "https:" + pic

            title = html.unescape(title_m.group(1).strip())
            remarks = ("蝴蝶影视 | %s" % dur) if dur else "蝴蝶影视"

            items.append({
                "vod_id": v_url,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": remarks,
                "vod_pic_style": "1.78",
                "vod_card_style": "rect",
                "style": {"type": "rect", "ratio": 1.78}
            })
        return items

    def _parse_duration_iso(self, iso_str):
        if not iso_str:
            return ""
        m = re.search(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', iso_str)
        if m:
            h, mi, s = m.groups()
            h = h or "0"
            mi = (mi or "0").zfill(2)
            s = (s or "0").zfill(2)
            if h != "0":
                return "%s:%s:%s" % (h, mi, s)
            return "%s:%s" % (mi, s)
        return iso_str

    def _translate(self, text, lang_from="ru", lang_to="zh-CN"):
        """翻译文本，使用MyMemory免费API"""
        if not text or len(text) < 2:
            return text
        cache_key = f"{text}|{lang_from}|{lang_to}"
        if cache_key in _translation_cache:
            return _translation_cache[cache_key]
        # 限流
        global _translation_last_call
        now = time.time()
        elapsed = now - _translation_last_call
        if elapsed < _translation_throttle:
            time.sleep(_translation_throttle - elapsed)
        _translation_last_call = time.time()
        try:
            encoded = urllib.parse.quote(text)
            url = f"https://api.mymemory.translated.net/get?q={encoded}&langpair={lang_from}|{lang_to}&de=agent@openclaw.ai"
            headers = {
                "User-Agent": "Mozilla/5.0 (Linux; Android 15; 20240618 SDK) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.171 Mobile Safari/537.36",
                "Accept": "application/json",
            }
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req_obj = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req_obj, timeout=8, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                result = data.get("responseData", {}).get("translatedText", "")
                if result:
                    _translation_cache[cache_key] = result
                    return result
        except Exception as e:
            pass
        return text

    def homeContent(self, filter):
        return {
            "class": CATEGORIES,
            "list": [],
            "class_flag": 0,
            "style": {"type": "rect", "ratio": 1.78}
        }

    def homeVideoContent(self):
        html_text = self._req("%s/" % HOST)
        return {
            "list": self._parse_items(html_text),
            "style": {"type": "rect", "ratio": 1.78}
        }

    def categoryContent(self, tid, pg="1", filter=False, extend=None):
        p = int(pg) if str(pg).isdigit() else 1
        clean_tid = tid.strip("/")

        if p > 1:
            url = "%s/categories/%s/%s/" % (HOST, clean_tid, p)
        else:
            url = "%s/categories/%s/" % (HOST, clean_tid)

        html_text = self._req(url)
        items = self._parse_items(html_text)

        if p > 1 and not items:
            alt_url = "%s/categories/%s/?from=%s" % (HOST, clean_tid, p)
            alt_html = self._req(alt_url)
            items = self._parse_items(alt_html)
            if items:
                html_text = alt_html

        pagecount = 999
        from_matches = re.findall(r'from:(\d+)', html_text)
        if from_matches:
            try:
                pagecount = max([int(x) for x in from_matches])
            except Exception:
                pagecount = 999

        return {
            "list": items,
            "page": p,
            "pagecount": pagecount,
            "limit": 24,
            "total": 9999,
            "class_flag": 0,
            "style": {"type": "rect", "ratio": 1.78}
        }

    def detailContent(self, ids):
        if not ids:
            return {"list": []}

        target_url = str(ids[0]).strip()
        if not target_url.startswith("http"):
            target_url = "%s/video/%s/" % (HOST, target_url.strip("/"))

        html_text = self._req(target_url)

        if not html_text:
            m_vid = re.search(r'/video/(\d+)/?', target_url)
            if m_vid:
                vid = m_vid.group(1)
                search_html = self._req("%s/search/%s/" % (HOST, vid))
                items = self._parse_items(search_html)
                for it in items:
                    if vid in it["vod_id"]:
                        target_url = it["vod_id"]
                        html_text = self._req(target_url)
                        break

        if not html_text:
            return {"list": []}

        title = ""
        pic = ""
        duration = ""
        desc = ""
        qualities = []

        jsonld_m = re.search(r'<script\s+type="application/ld\+json">(.*?)</script>', html_text, re.DOTALL)
        if jsonld_m:
            try:
                data = json.loads(jsonld_m.group(1))
                title = data.get("name", "")
                pic = data.get("thumbnailUrl", "")
                duration = self._parse_duration_iso(data.get("duration", ""))
                desc = data.get("description", "")
                cu = data.get("contentUrl", "").rstrip("/")
                if cu:
                    if not cu.endswith("/"):
                        cu = cu + "/"
                    qualities.append(("480P", cu))
            except Exception:
                pass

        if not title:
            t_m = re.search(r'<h1[^>]*>([^<]+)</h1>', html_text)
            if t_m:
                title = t_m.group(1).strip()

        direct_mp4s = re.findall(r'href="(https?://[^"]+/get_file/[^"]+)"', html_text)
        for link in direct_mp4s:
            q_name = "HD"
            if "720p" in link:
                q_name = "720P"
            elif "480p" in link:
                q_name = "480P"
            elif "360p" in link:
                q_name = "360P"
            elif "1080p" in link:
                q_name = "1080P"

            clean_link = link.split("?")[0].rstrip("/") + "/"
            if not any(clean_link == q[1] for q in qualities):
                qualities.append((q_name, clean_link))

        if not qualities:
            qualities.append(("默认", target_url))

        play_url = "#".join(["%s$%s" % (q[0], q[1]) for q in qualities])
        remarks = ("蝴蝶影视 | %s" % duration) if duration else "蝴蝶影视"

        # 翻译标题和描述为中文
        if title:
            title = self._translate(title)
        if desc:
            desc = self._translate(desc)

        notice_desc = "🦋 蝴蝶影视 独家呈现\n官方交流群: @tvshare23\n%s" % desc

        vod = {
            "vod_id": target_url,
            "vod_name": html.unescape(title) if title else "精彩视频",
            "vod_pic": pic,
            "vod_year": "",
            "vod_area": "",
            "vod_actor": "🦋 TG群: @tvshare23",
            "vod_director": "🦋 蝴蝶影视",
            "vod_content": notice_desc,
            "vod_remarks": remarks,
            "vod_play_from": "蝴蝶影视",
            "vod_play_url": play_url,
        }
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags):
        headers = {
            "User-Agent": UA,
            "Referer": "%s/video/" % HOST
        }
        return {
            "parse": 0,
            "playUrl": "",
            "url": id,
            "header": json.dumps(headers)
        }

    def searchContent(self, key, quick=False, pg="1"):
        p = int(pg) if str(pg).isdigit() else 1
        kw = urllib.parse.quote(key)
        if p > 1:
            url = "%s/search/%s/%s/" % (HOST, kw, p)
        else:
            url = "%s/search/%s/" % (HOST, kw)

        html_text = self._req(url)
        items = self._parse_items(html_text)
        if p > 1 and not items:
            alt_url = "%s/search/%s/?from=%s" % (HOST, kw, p)
            alt_html = self._req(alt_url)
            items = self._parse_items(alt_html)

        return {
            "list": items,
            "page": p,
            "pagecount": 999,
            "limit": 24,
            "total": 9999,
            "class_flag": 0,
            "style": {"type": "rect", "ratio": 1.78}
        }

    def localProxy(self, params):
        """视频代理：下载完整视频并缓存，支持任意seek"""
        import sys as _sys
        _sys.stderr.write(f"[sweetpornos] localProxy called: {params}\n")

        try:
            vid_url = ""
            if isinstance(params, dict):
                vid_url = params.get("url") or params.get("vid") or ""
            elif isinstance(params, str):
                vid_url = params

            if not vid_url:
                return [200, "text/plain; charset=utf-8", b"", None]

            # 去掉 function/0/ 前缀
            if vid_url.startswith("function/0/"):
                vid_url = vid_url[11:]

            # 确保有 trailing slash
            if not vid_url.endswith('/'):
                vid_url = vid_url.rstrip('/') + '/'

            # 生成缓存key
            cache_key = hashlib.md5(vid_url.encode()).hexdigest()

            # 检查缓存
            if cache_key in self._video_cache:
                body = self._video_cache[cache_key]
                _sys.stderr.write(f"[sweetpornos] localProxy cache hit: {len(body)} bytes\n")
                return [200, "video/mp4", body, None]

            # 缓存未命中，从CDN下载完整视频
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            req_headers = {
                'User-Agent': UA,
                'Referer': HOST + '/video/',
            }

            # Step 1: 获取重定向URL
            parsed = urlparse(vid_url)
            conn = http.client.HTTPSConnection(parsed.hostname, context=ctx, timeout=15)
            conn.request('GET', parsed.path, headers=req_headers)
            resp = conn.getresponse()
            loc = resp.getheader('Location')
            conn.close()

            if resp.status != 302 or not loc:
                _sys.stderr.write(f"[sweetpornos] localProxy no redirect: status={resp.status}\n")
                return [200, "text/plain; charset=utf-8", b"", None]

            # Step 2: 从CDN下载完整视频
            cdn_url = unquote(loc)
            cdn_parsed = urlparse(cdn_url)
            _sys.stderr.write(f"[sweetpornos] localProxy downloading from CDN: {cdn_parsed.netloc}{cdn_parsed.path[:50]}\n")

            conn2 = http.client.HTTPSConnection(cdn_parsed.hostname, context=ctx, timeout=300)
            conn2.request('GET', cdn_parsed.path + ('?' + cdn_parsed.query if cdn_parsed.query else ''), headers=req_headers)
            resp2 = conn2.getresponse()
            body = resp2.read()
            conn2.close()

            if not body:
                _sys.stderr.write(f"[sweetpornos] localProxy empty body from CDN\n")
                return [200, "text/plain; charset=utf-8", b"", None]

            # 存入缓存
            self._video_cache[cache_key] = body
            _sys.stderr.write(f"[sweetpornos] localProxy downloaded {len(body)} bytes, cached\n")
            return [200, "video/mp4", body, None]

        except Exception as e:
            _sys.stderr.write(f"[sweetpornos] localProxy error: {e}\n")
            return [200, "text/plain; charset=utf-8", f"Error: {e}".encode(), None]

    def action(self, action):
        return {}

    def liveContent(self):
        return {}

    def manualVideoCheck(self):
        return False

    def isVideoFormat(self, url):
        return False

    def destroy(self):
        pass
