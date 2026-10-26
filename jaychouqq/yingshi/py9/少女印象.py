# -*- coding: utf-8 -*-
import sys
import re
import json
import base64
import urllib.request
import urllib.parse
from urllib.parse import quote, unquote
import http.cookiejar
import gzip
import zlib
import ssl

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        def getCache(self, key): return None
        def setCache(self, key, value): return "fail"
        def delCache(self, key): return "fail"

def format_remarks(brand="蝴蝶影视", meta=""):
    clean_meta = str(meta or "").strip()
    clean_meta = re.sub(r"[\r\n\t]+", " ", clean_meta).strip()
    if clean_meta:
        return "%s | %s" % (brand, clean_meta)
    return brand

class Spider(BaseSpider):
    def __init__(self):
        super(Spider, self).__init__()
        self.siteName = "少女导航"
        self.siteUrl = "https://app-1.ssnnav.cyou"
        self.tgGroup = "https://t.me/tvshare23"
        self.brandActor = "🦋 TG群: @tvshare23"
        self.brandDirector = "🦋 蝴蝶影视"
        self._ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
        self.options = {}

        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=self.ctx)
        )

    def init(self, extend=""):
        if isinstance(extend, dict):
            self.options = extend
        elif extend:
            try:
                self.options = json.loads(extend)
            except Exception:
                self.options = {}
        return True

    def getName(self):
        return self.siteName

    def isVideoFormat(self, url):
        if not url:
            return False
        low = url.lower()
        if any(bad in low for bad in ("preview.mp4", "sample.mp4", "trailer.mp4", "native-ad")):
            return False
        return any(k in low for k in (".m3u8", ".mp4", ".flv", ".ts", "index.png"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self.options = {}

    def _fetch(self, target_url, referer=""):
        if not target_url:
            return {"code": 0, "text": "", "bytes": b"", "err": "", "final_url": ""}
        if target_url.startswith("//"):
            target_url = "https:" + target_url
        elif target_url.startswith("/"):
            target_url = self.siteUrl + target_url

        headers = {
            "User-Agent": self._ua,
            "Referer": referer if referer else (self.siteUrl + "/"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive"
        }

        last_err = ""
        for attempt in range(2):
            try:
                req = urllib.request.Request(target_url, headers=headers)
                with self.opener.open(req, timeout=10) as resp:
                    code = resp.getcode()
                    final_url = resp.geturl()
                    raw = resp.read()
                    enc = getattr(resp, "headers", {}).get("Content-Encoding", "")
                    if raw.startswith(b"\x1f\x8b") or enc == "gzip":
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
                    return {"code": code, "text": text, "bytes": raw, "err": "", "final_url": final_url}
            except urllib.error.HTTPError as e:
                last_err = "HTTP %s" % e.code
                if e.code in (451, 403, 429) and attempt == 0:
                    continue
                err_raw = ""
                try:
                    err_raw = e.read().decode("utf-8", errors="ignore")
                except Exception:
                    pass
                return {"code": e.code, "text": err_raw, "bytes": b"", "err": str(e), "final_url": target_url}
            except Exception as e:
                last_err = str(e)
                if attempt == 0:
                    continue
                return {"code": -1, "text": "", "bytes": b"", "err": str(e), "final_url": target_url}

        return {"code": -1, "text": "", "bytes": b"", "err": last_err, "final_url": target_url}

    def _clean_m3u8_url(self, raw_str):
        if not raw_str:
            return ""
        m = re.search(r'(https?://(?:(?!localhost|127\.0\.0\.1)[^\s"\'\$<>])+\.m3u8[^\s"\'\$<>]*)', raw_str)
        if m:
            clean = m.group(1).replace("\\u002F", "/").replace("\\/", "")
            if ".m3u8" not in clean.lower():
                sep = "&" if "?" in clean else "?"
                clean = clean + sep + "format=.m3u8"
            return clean
        return ""

    def _parse_cards(self, html_txt):
        card_list = []
        raw_items = html_txt.split('<div class="thumb">')
        if len(raw_items) <= 1:
            return card_list

        seen_ids = set()
        for chunk in raw_items[1:]:
            href_m = re.search(r'href=["\']([^"\']*play-(\d+)-1-\.html)["\']', chunk, re.I)
            if not href_m:
                continue

            vid = href_m.group(2)
            if vid in seen_ids:
                continue
            seen_ids.add(vid)

            pic = ""
            for pat in (r'data-original=["\']([^"\']+)["\']', r'data-src=["\']([^"\']+)["\']', r'src=["\']([^"\']+)["\']'):
                p_m = re.search(pat, chunk, re.I)
                if p_m:
                    cand = p_m.group(1).strip()
                    if cand and not cand.endswith("logo.png") and not cand.endswith("favicon.ico"):
                        pic = cand
                        break

            alt_m = re.search(r'<img[^>]+alt=["\']([^"\']+)["\']', chunk, re.I)
            if alt_m and alt_m.group(1).strip():
                title = alt_m.group(1).strip()
            else:
                title_info_m = re.search(r'<div class="thumb-info">([\s\S]*?)</div>', chunk, re.I)
                title = title_info_m.group(1).strip() if title_info_m else "正片_%s" % vid
            title = re.sub(r'<[^>]+>', '', title).strip()

            dur_m = re.search(r'fa-clock[^>]*></i>&nbsp;([^<]+)</div>', chunk, re.I)
            dur = dur_m.group(1).strip() if dur_m else ""

            prev_m = re.search(r'data-preview=["\']([^"\']+)["\']', chunk, re.I)
            stream_url = self._clean_m3u8_url(prev_m.group(1).strip()) if prev_m else ""

            remarks = format_remarks("蝴蝶影视", dur if dur else "HD")

            raw_payload = "%s@@@%s@@@%s" % (vid, quote(stream_url), quote(title))

            card_list.append({
                "vod_id": raw_payload,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": remarks,
                "style": {"type": "rect", "ratio": 1.78}
            })
        return card_list

    def homeContent(self, filter):
        categories = [
            {"type_id": "fenlei/日韩无码", "type_name": "日韩无码"},
            {"type_id": "fenlei/国产精品", "type_name": "国产精品"},
            {"type_id": "fenlei/日韩精品", "type_name": "日韩精品"},
            {"type_id": "fenlei/欧美精品", "type_name": "欧美精品"},
            {"type_id": "fenlei/动漫精品", "type_name": "动漫精品"},
            {"type_id": "fenlei/中文字幕", "type_name": "中文字幕"},
            {"type_id": "fenlei/自拍", "type_name": "自拍偷拍"},
            {"type_id": "fenlei/伦理影片", "type_name": "伦理影片"},
            {"type_id": "fenlei/人妻系列", "type_name": "人妻系列"},
            {"type_id": "fenlei/制服诱惑", "type_name": "制服诱惑"},
            {"type_id": "fenlei/强奸乱伦", "type_name": "强奸乱伦"},
            {"type_id": "fenlei/AV明星", "type_name": "AV明星"},
            {"type_id": "fenlei/SM重味", "type_name": "SM重味"},
            {"type_id": "fenlei/巨乳系列", "type_name": "巨乳系列"},
            {"type_id": "fenlei/颜射系列", "type_name": "颜射系列"},
            {"type_id": "fenlei/口交视频", "type_name": "口交视频"},
            {"type_id": "fenlei/自慰系列", "type_name": "自慰系列"},
            {"type_id": "fenlei/教师学生", "type_name": "教师学生"},
            {"type_id": "fenlei/大秀视频", "type_name": "大秀视频"},
            {"type_id": "fenlei/明星换脸", "type_name": "明星换脸"},
            {"type_id": "fenlei/AV解说", "type_name": "AV解说"},
            {"type_id": "fenlei/黑料网曝", "type_name": "黑料网曝"},
            {"type_id": "fenlei/精品探花", "type_name": "精品探花"},
            {"type_id": "fenlei/精品网红", "type_name": "精品网红"},
            {"type_id": "fenlei/反差母狗", "type_name": "反差母狗"},
            {"type_id": "fenlei/颜值正义", "type_name": "颜值正义"},
            {"type_id": "fenlei/熟女少妇", "type_name": "熟女少妇"},
            {"type_id": "fenlei/人兽乱交", "type_name": "人兽乱交"},
            {"type_id": "fenlei/国产传媒", "type_name": "国产传媒"},
            {"type_id": "fenlei/撸管必看", "type_name": "撸管必看"},
            {"type_id": "fenlei/直播裸聊", "type_name": "直播裸聊"},
            {"type_id": "fenlei/国产主播", "type_name": "国产主播"},
            {"type_id": "fenlei/野战车震", "type_name": "野战车震"},
            {"type_id": "fenlei/群P换妻", "type_name": "群P换妻"},
            {"type_id": "fenlei/SM调教", "type_name": "SM调教"},
            {"type_id": "fenlei/学生空姐", "type_name": "学生空姐"},
            {"type_id": "fenlei/吃瓜黑料", "type_name": "吃瓜黑料"},
            {"type_id": "fenlei/偷情少妇", "type_name": "偷情少妇"},
            {"type_id": "fenlei/百合女同", "type_name": "百合女同"},
            {"type_id": "fenlei/三级", "type_name": "经典三级"},
            {"type_id": "fenlei/按摩", "type_name": "按摩会所"},
            {"type_id": "fenlei/肛门", "type_name": "后门肛交"},
            {"type_id": "fenlei/乳交", "type_name": "巨乳乳交"},
            {"type_id": "fenlei/高潮", "type_name": "抽搐高潮"},
            {"type_id": "fenlei/少女", "type_name": "清纯少女"},
            {"type_id": "fenlei/新人", "type_name": "下海新人"},
            {"type_id": "fenlei/妈妈", "type_name": "熟母人妻"},
            {"type_id": "fenlei/3P", "type_name": "多人3P"},
            {"type_id": "fenlei/69", "type_name": "互舐69"},
            {"type_id": "fenlei/强迫", "type_name": "迷晕强迫"},
            {"type_id": "fenlei/口活", "type_name": "深喉口活"},
            {"type_id": "fenlei/娇小", "type_name": "娇小萝莉"},
            {"type_id": "fenlei/网红", "type_name": "热播网红"},
            {"type_id": "fenlei/大屁股", "type_name": "蜜桃丰臀"},
            {"type_id": "fenlei/虐待", "type_name": "捆绑虐待"},
            {"type_id": "fenlei/3d", "type_name": "3D肉感"},
            {"type_id": "fenlei/偷窥", "type_name": "真实偷窥"},
            {"type_id": "fenlei/特写", "type_name": "器官特写"},
            {"type_id": "fenlei/视角", "type_name": "第一视角"},
            {"type_id": "fenlei/探花", "type_name": "探花实录"},
            {"type_id": "tag/初下海", "type_name": "标签·初下海"},
            {"type_id": "tag/极品", "type_name": "标签·极品尤物"},
            {"type_id": "tag/深喉", "type_name": "标签·深喉狂插"},
            {"type_id": "tag/母狗", "type_name": "标签·调教母狗"},
            {"type_id": "tag/家教", "type_name": "标签·家庭教师"},
            {"type_id": "tag/外遇", "type_name": "标签·出轨外遇"},
            {"type_id": "tag/兼职", "type_name": "标签·兼职援交"},
            {"type_id": "tag/白领", "type_name": "标签·职场白领"},
            {"type_id": "tag/黑丝", "type_name": "标签·诱惑黑丝"},
            {"type_id": "tag/白虎", "type_name": "标签·白虎无毛"},
            {"type_id": "tag/约炮", "type_name": "标签·同城约炮"},
            {"type_id": "tag/内射", "type_name": "标签·疯狂内射"},
            {"type_id": "tag/潮吹", "type_name": "标签·高潮喷水"},
            {"type_id": "tag/双飞", "type_name": "标签·姐妹双飞"},
            {"type_id": "tag/破处", "type_name": "标签·稚嫩破处"}
        ]
        result = {"class": categories}
        if filter:
            result["filters"] = {}
        return result

    def homeVideoContent(self):
        res = self._fetch(self.siteUrl + "/?video=1.html")
        return {"list": self._parse_cards(res.get("text", ""))}

    def categoryContent(self, tid, pg, filter, extend):
        del filter, extend
        page = 1
        try:
            page = int(str(pg).strip())
        except Exception:
            page = 1

        slug = str(tid).strip("/")
        param_key = "fenlei"
        param_val = slug
        if "/" in slug:
            parts = slug.split("/", 1)
            param_key = parts[0]
            param_val = parts[1]

        enc_val = quote(param_val)

        if page == 1:
            target_url = "%s/?%s=%s" % (self.siteUrl, param_key, enc_val)
        else:
            target_url = "%s/?%s=%s-%s.html" % (self.siteUrl, param_key, enc_val, page)

        res = self._fetch(target_url)
        cards = self._parse_cards(res.get("text", ""))

        card_count = len(cards)
        has_more = card_count >= 10
        total_count = int(page * card_count + 100) if has_more else int(page * card_count)

        return {
            "page": int(page),
            "pagecount": int(page + 1 if has_more else page),
            "limit": int(card_count if card_count > 0 else 20),
            "total": total_count,
            "list": cards
        }

    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) else str(ids)
        raw_str = str(raw_id).strip()

        vid = raw_str
        stream_url = ""
        vod_title = "少女导航 · 精彩正片"

        if "@@@" in raw_str:
            parts = raw_str.split("@@@")
            vid = parts[0]
            if len(parts) > 1 and parts[1]:
                stream_url = unquote(parts[1])
            if len(parts) > 2 and parts[2]:
                vod_title = unquote(parts[2])

        detail_url = "%s/?play-%s-1-.html" % (self.siteUrl, vid)
        res = self._fetch(detail_url)
        html_txt = res.get("text", "")

        if not stream_url:
            m_stream = re.search(r'data-preview=["\']([^"\']+)["\']', html_txt, re.I)
            if m_stream:
                stream_url = self._clean_m3u8_url(m_stream.group(1).strip())

        if not stream_url:
            stream_url = "%s/?play-%s-1-.html" % (self.siteUrl, vid)

        pic = ""
        for pat in (r'data-original=["\']([^"\']+)["\']', r'data-src=["\']([^"\']+)["\']', r'src=["\']([^"\']+)["\']'):
            p_m = re.search(pat, html_txt, re.I)
            if p_m:
                cand = p_m.group(1).strip()
                if cand and not cand.endswith("logo.png") and not cand.endswith("favicon.ico"):
                    pic = cand
                    break

        episodes = ["正片$%s@@@%s" % (stream_url, quote(vod_title))]

        rec_items = html_txt.split('<div class="thumb">')
        if len(rec_items) > 1:
            seen_rec = set([vid])
            rec_idx = 1
            for chunk in rec_items[1:]:
                href_m = re.search(r'href=["\']([^"\']*play-(\d+)-1-\.html)["\']', chunk, re.I)
                if not href_m:
                    continue
                rec_vid = href_m.group(2)
                if rec_vid in seen_rec:
                    continue
                seen_rec.add(rec_vid)

                rec_title = ""
                alt_m = re.search(r'<img[^>]+alt=["\']([^"\']+)["\']', chunk, re.I)
                if alt_m and alt_m.group(1).strip():
                    rec_title = alt_m.group(1).strip()
                else:
                    info_m = re.search(r'<div class="thumb-info">([\s\S]*?)</div>', chunk, re.I)
                    rec_title = info_m.group(1).strip() if info_m else "推荐%02d" % rec_idx
                rec_title = re.sub(r'[\$\#\r\n\t]+', '', rec_title).strip()[:18]

                prev_m = re.search(r'data-preview=["\']([^"\']+)["\']', chunk, re.I)
                rec_stream = self._clean_m3u8_url(prev_m.group(1).strip()) if prev_m else ""
                target_play = rec_stream if rec_stream else ("%s/?play-%s-1-.html" % (self.siteUrl, rec_vid))

                episodes.append("%02d·%s$%s@@@%s" % (rec_idx, rec_title, target_play, quote(rec_title)))
                rec_idx += 1
                if rec_idx > 24:
                    break

        content_desc = "🦋 蝴蝶影视专线直连 | %s | 官方交流群: @tvshare23" % vod_title

        vod = {
            "vod_id": raw_str,
            "vod_name": vod_title,
            "vod_pic": pic,
            "vod_bg": pic,
            "vod_background": pic,
            "vod_banner": pic,
            "vod_actor": self.brandActor,
            "vod_director": self.brandDirector,
            "vod_remarks": format_remarks("蝴蝶影视", "全%s部连播" % len(episodes)),
            "vod_content": content_desc,
            "vod_play_from": "蝴蝶专线",
            "vod_play_url": "#".join(episodes)
        }
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags):
        del flag, vipFlags
        raw_val = str(id).strip()

        target = raw_val
        desc_title = ""
        if "@@@" in raw_val:
            parts = raw_val.split("@@@", 1)
            target = parts[0]
            desc_title = unquote(parts[1])

        if ".m3u8" in target.lower():
            res = {
                "parse": 0,
                "playUrl": "",
                "url": target,
                "header": {
                    "User-Agent": self._ua,
                    "Referer": self.siteUrl + "/"
                }
            }
            if desc_title:
                res["desc"] = desc_title
            return res

        detail_res = self._fetch(target)
        detail_html = detail_res.get("text", "")
        clean_url = self._clean_m3u8_url(detail_html)

        if clean_url:
            res = {
                "parse": 0,
                "playUrl": "",
                "url": clean_url,
                "header": {
                    "User-Agent": self._ua,
                    "Referer": self.siteUrl + "/"
                }
            }
            if desc_title:
                res["desc"] = desc_title
            return res

        res = {
            "parse": 1,
            "playUrl": "",
            "url": target,
            "header": {
                "User-Agent": self._ua,
                "Referer": self.siteUrl + "/"
            }
        }
        if desc_title:
            res["desc"] = desc_title
        return res

    def searchContent(self, key, quick, pg="1"):
        page = 1
        try:
            page = int(str(pg).strip())
        except Exception:
            page = 1

        if page == 1:
            search_url = "%s/?search=%s" % (self.siteUrl, quote(key))
        else:
            search_url = "%s/?search=%s-%s.html" % (self.siteUrl, quote(key), page)

        res = self._fetch(search_url)
        cards = self._parse_cards(res.get("text", ""))

        card_count = len(cards)
        has_more = card_count >= 10
        total_count = int(page * card_count + 100) if has_more else int(page * card_count)

        return {
            "page": int(page),
            "pagecount": int(page + 1 if has_more else page),
            "limit": int(card_count if card_count > 0 else 20),
            "total": total_count,
            "list": cards
        }

    def liveContent(self):
        return ""

    def action(self, action):
        return {"msg": "ok"}

    def localProxy(self, params):
        return [404, "text/plain; charset=utf-8", "Proxy not configured"]
