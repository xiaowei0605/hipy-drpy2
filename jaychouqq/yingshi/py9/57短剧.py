#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 蜂蜜影视 / Hawk Player 原生 Python 蜘蛛 - 57短剧 iOS深度调优版

import sys
import os
import re
import json
import base64
import html as html_lib
import urllib.request
import urllib.parse
from urllib.parse import urlparse, quote, unquote
import http.cookiejar
import gzip
import zlib
import ssl

try:
    from base.spider import Spider as SpiderBase
except ImportError:
    class SpiderBase(object):
        def getCache(self, key): return None
        def setCache(self, key, value): return "fail"
        def delCache(self, key): return "fail"

class Spider(SpiderBase):
    def __init__(self):
        super(Spider, self).__init__()
        self.siteUrl = "https://57duanju.org"
        self.cgUrl = "https://57cg4.com"
        self.imgReferer = "https://57cg4.com/"
        self.tgGroup = "https://t.me/tvshare23"
        self.brandActor = "🦋 TG群: @tvshare23"
        self.brandDirector = "🦋 蝴蝶影视"
        # 切换为移动端 iOS 原生 UA，减小响应体积提升解析速度
        self._ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
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
        return "57短剧"

    def isVideoFormat(self, url):
        low = (url or "").lower()
        return any(k in low for k in (".m3u8", ".mp4", ".flv", ".mkv", ".ts"))

    def manualVideoCheck(self):
        return False

    def _fetch(self, target_url, referer=""):
        if not target_url:
            return {"code": 0, "text": "", "bytes": b"", "err": "", "final_url": ""}
        if target_url.startswith("//"):
            target_url = "https:" + target_url
        elif target_url.startswith("/"):
            target_url = self.siteUrl + target_url

        headers = {
            "User-Agent": self._ua,
            "Referer": referer if referer else self.imgReferer,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive"
        }

        # iOS 严苛超时契约：将超时降至 5 秒，单次快速重试，避免整页卡死
        for attempt in range(2):
            try:
                req = urllib.request.Request(target_url, headers=headers)
                with self.opener.open(req, timeout=5) as resp:
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
            except Exception as e:
                if attempt == 0:
                    continue
                return {"code": -1, "text": "", "bytes": b"", "err": str(e), "final_url": target_url}

        return {"code": -1, "text": "", "bytes": b"", "err": "timeout", "final_url": target_url}

    # 核心修复点：彻底去除导致 iOS 海报全白的 @User-Agent=，仅保留 @Referer=
    def _wrap_pic(self, pic_url):
        if not pic_url:
            return ""
        pic = pic_url.strip()
        if pic.startswith("//"):
            pic = "https:" + pic
        elif pic.startswith("/"):
            pic = self.siteUrl + pic
        
        # 针对防盗链图床，仅拼接标准 Referer，绝不拼接 User-Agent
        if "s.chigua.media" in pic and "@Referer=" not in pic:
            return "%s@Referer=%s" % (pic, self.imgReferer)
        return pic

    def homeContent(self, filter):
        classes = [
            {"type_name": "成人AI短剧", "type_id": "cat_aichengduanju"},
            {"type_name": "热门精选", "type_id": "cat_hot"},
            {"type_name": "今日吃瓜", "type_id": "cat_jrcg"},
            {"type_name": "每日大赛", "type_id": "cat_mrds"},
            {"type_name": "网红黑料", "type_id": "cat_wanghong"},
            {"type_name": "网黄合集", "type_id": "cat_video"},
            {"type_name": "出轨劈腿", "type_id": "cat_cheating"},
            {"type_name": "直播擦边", "type_id": "cat_live"},
            {"type_name": "社会事件", "type_id": "cat_society"},
            {"type_name": "明星八卦", "type_id": "cat_star"},
            {"type_name": "全部短剧", "type_id": "cat_all"}
        ]
        
        result = {"class": classes}
        
        if filter:
            sort_filter = [
                {
                    "key": "sort",
                    "name": "排序",
                    "value": [
                        {"n": "最新发布", "v": ""},
                        {"n": "全站最热", "v": "hot"},
                        {"n": "飙升热榜", "v": "trending"}
                    ]
                }
            ]
            filters_dict = {}
            for item in classes:
                filters_dict[item["type_id"]] = sort_filter
            result["filters"] = filters_dict
            
        return result

    def homeVideoContent(self):
        res = self.categoryContent("cat_aichengduanju", 1, False, {})
        return {"list": res.get("list", [])[:12]}

    def _parse_card_list(self, html_text):
        vod_list = []
        seen_ids = set()

        pattern_events = r'<a[^>]+href=["\'](?:https?://[^/]+)?/events/(\d+)/?["\'][^>]*>([\s\S]*?)</a>'
        matches = re.findall(pattern_events, html_text)

        if not matches:
            pattern_all = r'<a[^>]+href=["\'](?:https?://[^/]+)?/(?:events/)?(\d+)/?["\'][^>]*>([\s\S]*?)</a>'
            matches = re.findall(pattern_all, html_text)

        for event_id, inner in matches:
            if event_id in seen_ids or len(event_id) < 2:
                continue
            seen_ids.add(event_id)

            m_t = re.search(r'<h[23][^>]*>([\s\S]*?)</h[23]>', inner)
            if m_t:
                name = re.sub(r'<[^>]+>', '', m_t.group(1)).strip()
            else:
                raw_txt = re.sub(r'<[^>]+>', ' ', inner).strip()
                name = raw_txt[:40] if raw_txt else ("短剧/热点 %s" % event_id)

            pic = ""
            img_matches = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', inner)
            for src_cand in img_matches:
                if not src_cand.endswith(".svg") and "logo" not in src_cand:
                    pic = src_cand.strip()
                    break

            final_pic = self._wrap_pic(pic)

            vod_list.append({
                "vod_id": event_id,
                "vod_name": name,
                "vod_pic": final_pic,
                "vod_remarks": "蝴蝶影视",
                "style": {"type": "rect", "ratio": 1.78}
            })

        return vod_list

    def categoryContent(self, tid, pg, filter, extend):
        del filter
        page = int(pg) if pg else 1
        raw_slug = str(tid).strip("/")

        slug = raw_slug.replace("cat_", "")
        sort_val = extend.get("sort") if isinstance(extend, dict) else ""

        if slug == "all":
            base = self.siteUrl
            target_url = ("%s/page/%d/" % (base, page)) if page > 1 else ("%s/" % base)
        elif slug in ("aichengduanju", "hot"):
            base = self.siteUrl
            target_url = ("%s/%s/%d/" % (base, slug, page)) if page > 1 else ("%s/%s/" % (base, slug))
        else:
            base = self.cgUrl
            target_url = ("%s/%s/%d/" % (base, slug, page)) if page > 1 else ("%s/%s/" % (base, slug))

        if sort_val:
            target_url += ("&sort=%s" if "?" in target_url else "?sort=%s") % sort_val

        res = self._fetch(target_url)
        html_text = res.get("text", "")
        vod_list = self._parse_card_list(html_text)

        # iOS 端每页适度返回不超过 20 条，保障极速渲染
        return {
            "page": page,
            "pagecount": page + 1 if len(vod_list) >= 10 else page,
            "limit": len(vod_list),
            "total": 9999,
            "list": vod_list[:20]
        }

    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) else str(ids)
        event_id = raw_id.strip("/")
        
        target_url = "%s/events/%s/" % (self.cgUrl, event_id)
        res = self._fetch(target_url)
        detail_html = res.get("text", "")
        if not detail_html or len(detail_html) < 500:
            target_url = "%s/events/%s/" % (self.siteUrl, event_id)
            res = self._fetch(target_url)
            detail_html = res.get("text", "")

        title = "AI短剧/热点 %s" % event_id
        cover = ""
        desc = "暂无详细介绍"

        m_title = re.search(r'<h1[^>]*>([\s\S]*?)</h1>', detail_html)
        if m_title:
            title = re.sub(r'<[^>]+>', '', m_title.group(1)).strip()

        m_desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']', detail_html)
        if m_desc:
            desc = m_desc.group(1).strip()

        episodes = []
        
        # 1. 扫描所有 <video> 标签 (优先 data-hls-src，其次 src)
        v_blocks = re.findall(r'<video([^>]+)>', detail_html)
        for idx, attr in enumerate(v_blocks):
            m_hls = re.search(r'data-hls-src=["\']([^"\']+)["\']', attr)
            m_src = re.search(r'src=["\']([^"\']+)["\']', attr)
            stream_url = m_hls.group(1).strip() if m_hls else (m_src.group(1).strip() if m_src else "")
            
            if not cover:
                m_post = re.search(r'poster=["\']([^"\']+)["\']', attr)
                if m_post:
                    cover = m_post.group(1).strip()

            if stream_url:
                ep_name = "片段 %02d" % (len(episodes) + 1)
                episodes.append("%s$%s" % (ep_name, stream_url))

        # 2. 从 JSON-LD 提取
        if not episodes:
            m_schema = re.findall(r'<script\s+type=["\']application/ld\+json["\']>([\s\S]*?)</script>', detail_html)
            for s in m_schema:
                if '"VideoObject"' in s:
                    try:
                        data = json.loads(s)
                        v_list = data.get("video", [])
                        if isinstance(v_list, dict):
                            v_list = [v_list]
                        for idx, v_item in enumerate(v_list):
                            c_url = v_item.get("contentUrl", "")
                            if c_url:
                                ep_name = "第 %02d 集" % (len(episodes) + 1)
                                episodes.append("%s$%s" % (ep_name, c_url))
                                if not cover:
                                    cover = v_item.get("thumbnailUrl", "")
                    except Exception:
                        pass

        # 3. 正则兜底提取页面直链流
        if not episodes:
            all_media = re.findall(r'["\'](https?://[^"\'\s]+\.(?:m3u8|mp4)[^"\'\s]*)["\']', detail_html)
            seen_streams = set()
            for m_url in all_media:
                if m_url in seen_streams:
                    continue
                seen_streams.add(m_url)
                ep_name = "播放 %02d" % (len(episodes) + 1)
                episodes.append("%s$%s" % (ep_name, m_url))

        if not cover:
            m_pic = re.search(r'<meta property=["\']og:image["\'] content=["\']([^"\']+)["\']', detail_html)
            if m_pic:
                cover = m_pic.group(1).strip()

        final_cover = self._wrap_pic(cover)

        full_desc = (
            "【🔥 官方交流群: %s】\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "本贴为您解析到【%d】个现场视频片段，点击下方片段即可起播！\n\n%s"
        ) % (self.tgGroup, len(episodes), desc)

        # 严禁假死链（http://127.0.0.1 会触发 Hawk 探活断路器覆盖全屏）
        play_url = "#".join(episodes) if episodes else ("暂无可用视频流$https://dummyimage.com/1x1/000/000.png")

        return {
            "list": [{
                "vod_id": event_id,
                "vod_name": title,
                "vod_pic": final_cover,
                # 绑定详情页顶部大背景（Backdrop）字段
                "vod_bg": final_cover,
                "vod_background": final_cover,
                "vod_banner": final_cover,
                "vod_actor": self.brandActor,
                "vod_director": self.brandDirector,
                "vod_remarks": "共 %d 个片段" % len(episodes) if len(episodes) > 1 else "蝴蝶影视",
                "vod_content": full_desc,
                "vod_play_from": "57吃瓜在线",
                "vod_play_url": play_url
            }]
        }

    def playerContent(self, flag, id, vipFlags):
        play_url = str(id).strip()
        
        # 伪扩展名注入：针对无扩展名的直链注入伪 .m3u8 扩展名，强制促使 Hawk 走 AVPlayer 硬件解码
        if ".m3u8" not in play_url.lower() and ".mp4" not in play_url.lower():
            sep = "&" if "?" in play_url else "?"
            play_url = play_url + sep + "format=.m3u8"

        # 精简请求头，剔除会导致 TS 分片拉取失败的 Origin
        headers = {
            "User-Agent": self._ua,
            "Referer": self.imgReferer
        }

        return {
            "parse": 0,
            "playUrl": "",
            "url": play_url,
            "header": headers
        }

    def searchContent(self, key, quick, pg="1"):
        del quick
        page = int(pg) if pg else 1
        search_url = "%s/search/?q=%s" % (self.siteUrl, quote(key))
        if page > 1:
            search_url += "&page=%d" % page

        res = self._fetch(search_url)
        html_text = res.get("text", "")
        vod_list = self._parse_card_list(html_text)

        return {
            "page": page,
            "pagecount": page + 1 if len(vod_list) >= 10 else page,
            "limit": len(vod_list),
            "total": 9999,
            "list": vod_list[:20]
        }

    def action(self, action):
        return {"msg": "ok"}

    def liveContent(self):
        return ""

    def localProxy(self, params):
        return [404, "text/plain; charset=utf-8", "Proxy not configured"]

    def destroy(self):
        self.options = {}