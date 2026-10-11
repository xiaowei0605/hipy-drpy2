# coding=utf-8
# 一抖阁 · 修复版（基于 _3，吸收 _2 的长处，修翻页）
import re
import json
import html as htmllib
from urllib.parse import quote, unquote, urljoin

import requests
from base.spider import Spider as BaseSpider


class Spider(BaseSpider):
    def getName(self):
        return "一抖阁"

    def init(self, extend=""):
        self.host = "https://yidouge.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 Chrome/124.0.0.0 Mobile Safari/537.36",
            "Referer": self.host + "/",
            "Cookie": "gv_age_verified=1",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass

    # ─────────────────────────────────────────────────────
    # 请求层
    # ─────────────────────────────────────────────────────
    def _html(self, url):
        try:
            full = url if url.startswith("http") else self.host + url
            r = self.session.get(full, timeout=15)
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except Exception:
            return ""

    def _text(self, s):
        if not s:
            return ""
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()

    def _pic(self, url):
        if not url:
            return ""
        url = url.strip()
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith("/"):
            url = self.host + url
        if "images.weserv.nl" in url:
            return url
        if url.endswith(".webp") or "webp" in url.lower():
            return "https://images.weserv.nl/?url=" + url + "&output=jpg"
        return url

    def _href(self, h):
        return urljoin(self.host, htmllib.unescape(h or "").replace("\\/", "/"))

    # ─────────────────────────────────────────────────────
    # 列表解析（吸收 _2 的宽容匹配）
    # ─────────────────────────────────────────────────────
    def _list(self, html_text):
        out, seen = [], set()
        if not html_text:
            return out

        # ★ 宽容匹配：class 里含 video-card 就算
        blocks = re.findall(
            r'<article[^>]+class=["\'][^"\']*video-card[^"\']*["\'][^>]*>(.*?)</article>',
            html_text, re.S | re.I
        )
        if not blocks:
            # 兜底：精确匹配（_3 原版方式）
            blocks = re.findall(
                r'<article\s+class=["\']video-card["\'][^>]*>(.*?)</article>',
                html_text, re.S | re.I
            )

        for block in blocks:
            lm = re.search(r'<a[^>]+href=["\']([^"\']*(?:/video/|/creator/)[^"\']*)["\']', block, re.I)
            if not lm:
                # 退回到 _3 的原匹配
                lm = re.search(r'<a class="video-card__link" href="([^"]+)"', block, re.I)
            if not lm:
                lm = re.search(r'<a class="video-card__body-link" href="([^"]+)"', block, re.I)
            if not lm:
                lm = re.search(r'href=["\']([^"\']+)["\']', block, re.I)
            if not lm:
                continue

            href = lm.group(1)
            if href in seen:
                continue
            seen.add(href)

            # 标题：h2 → strong → img alt → 兜底
            tm = re.search(r'<h2[^>]*class="[^"]*video-card__title[^"]*"[^>]*>([^<]+)</h2>', block, re.I)
            if not tm:
                tm = re.search(r'<strong[^>]*class="[^"]*ydg-author-collection-title[^"]*"[^>]*>([^<]+)</strong>', block, re.I)
            if not tm:
                tm = re.search(r'<img[^>]+alt=["\']([^"\']+)["\']', block, re.I)
            title = self._text(tm.group(1)) if tm else ""

            # 封面
            im = re.search(r'<img[^>]+(?:data-src|data-lazy-src|src)=["\']([^"\']+)["\']', block, re.I)
            pic = self._pic(im.group(1)) if im else ""

            # 备注
            dm = re.search(r'<span[^>]*class="[^"]*video-card__duration[^"]*"[^>]*>([^<]+)</span>', block, re.I)
            remarks = self._text(dm.group(1)) if dm else ""
            nm = re.search(r'共\s*(\d+)\s*部', block)
            if nm and not remarks:
                remarks = "合集·共{}部".format(nm.group(1))

            out.append({
                "vod_id": href,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": remarks,
            })

        return out

    # ─────────────────────────────────────────────────────
    # 分类
    # ─────────────────────────────────────────────────────
    def _cats(self, html_text):
        cats, seen = [], set()
        if not html_text:
            return cats
        for m in re.finditer(
            r'<a class="category-parent-link[^"]*"\s+href="([^"]+)"[^>]*>\s*<span>([^<]+)</span>',
            html_text, re.I
        ):
            href = m.group(1)
            if href in seen:
                continue
            seen.add(href)
            cats.append({"type_name": self._text(m.group(2)), "type_id": href})
        return cats

    # ─────────────────────────────────────────────────────
    # 首页
    # ─────────────────────────────────────────────────────
    def homeContent(self, filter=None):
        html_text = self._html("/")
        cats = self._cats(html_text)
        vods = self._list(html_text)
        return {"class": cats, "list": vods}

    def homeVideoContent(self):
        html_text = self._html("/")
        return {"list": self._list(html_text)}

    # ─────────────────────────────────────────────────────
    # 分类页（★ 修翻页）
    # ─────────────────────────────────────────────────────
    def categoryContent(self, tid, pg, filter=None, extend=None):
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1

        # ★ 修：base 保底带一个 /
        base = str(tid).rstrip("/") + "/"
        path = base if pg == 1 else base + "page/{}/".format(pg)

        html_text = self._html(path)
        vods = self._list(html_text)

        # ★ 修：pagecount 给固定大值，不再 pg+1
        if not vods:
            return {
                "page": pg,
                "pagecount": pg,       # 没数据就停在当前页
                "limit": 0,
                "total": 0,
                "list": [],
            }
        return {
            "page": pg,
            "pagecount": 999,          # ★ 固定大页码
            "limit": len(vods),
            "total": 999999,
            "list": vods,
        }

    # ─────────────────────────────────────────────────────
    # 详情
    # ─────────────────────────────────────────────────────
    def detailContent(self, ids):
        vid = str(ids[0]).strip() if isinstance(ids, list) else str(ids).strip()
        if not vid.startswith("http"):
            vid = self.host + vid
        html_text = self._html(vid)
        if not html_text:
            return {"list": []}

        # ★ 吸收 _2：优先 <h1>，退回 og:title
        name = re.search(r'<h1[^>]*>(.*?)</h1>', html_text, re.I | re.S)
        if name:
            vod_name = self._text(name.group(1))
        else:
            name = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html_text, re.I)
            vod_name = self._text(name.group(1)) if name else vid

        pic = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html_text, re.I)
        vod_pic = self._pic(pic.group(1)) if pic else ""

        desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)', html_text, re.I)
        vod_content = desc.group(1).strip() if desc else ""

        # 合集页
        if "/creator/" in vid:
            episodes = self._list(html_text)
            parts = []
            for i, v in enumerate(episodes, 1):
                t = v.get("vod_name") or "第{}集".format(i)
                parts.append("{}${}".format(t, v.get("vod_id")))
            if not parts:
                parts = ["播放${}".format(vid)]
            if not vod_pic and episodes:
                vod_pic = episodes[0].get("vod_pic", "")
            return {"list": [{
                "vod_id": vid,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "type_name": "",
                "vod_year": "",
                "vod_content": vod_content,
                "vod_play_from": "合集",
                "vod_play_url": "#".join(parts),
            }]}

        return {"list": [{
            "vod_id": vid,
            "vod_name": vod_name,
            "vod_pic": vod_pic,
            "type_name": "",
            "vod_year": "",
            "vod_content": vod_content,
            "vod_play_from": "一抖阁",
            "vod_play_url": "播放${}".format(vid),
        }]}

    # ─────────────────────────────────────────────────────
    # 搜索
    # ─────────────────────────────────────────────────────
    def searchContent(self, key, quick=False, pg="1"):
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1
        wd = quote(str(key), safe="")
        path = "/?s={}&post_type=video".format(wd) if pg == 1 else "/?s={}&post_type=video&paged={}".format(wd, pg)
        vods = self._list(self._html(path))
        if not vods:
            return {"page": pg, "pagecount": pg, "limit": 0, "total": 0, "list": []}
        return {
            "page": pg,
            "pagecount": 999,       # ★ 同样固定
            "limit": len(vods),
            "total": 999999,
            "list": vods,
        }

    # ─────────────────────────────────────────────────────
    # 播放（★ 吸收 _2 的多路径提取）
    # ─────────────────────────────────────────────────────
    def playerContent(self, flag, id, vipFlags=None):
        page = str(id).strip()
        if not page.startswith("http"):
            page = self.host + page

        html_text = self._html(page)
        url = ""

        # ① ld+json contentUrl
        for m in re.finditer(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html_text, re.S | re.I):
            data = m.group(1).strip()
            cm = re.search(r'"contentUrl"\s*:\s*"([^"]+)"', data)
            if cm:
                url = cm.group(1)
                break
            em = re.search(r'"embedUrl"\s*:\s*"([^"]+)"', data)
            if em:
                url = em.group(1)
                break

        # ② data-video-url
        if not url:
            vm = re.search(r'data-video-url=["\']([^"\']+)', html_text, re.I)
            if vm:
                url = vm.group(1)

        # ③ <video src>
        if not url:
            vm = re.search(r'<video[^>]+src=["\']([^"\']+)', html_text, re.I)
            if vm:
                url = vm.group(1)

        # ④ <source src>
        if not url:
            vm = re.search(r'<source[^>]+src=["\']([^"\']+)', html_text, re.I)
            if vm:
                url = vm.group(1)

        # ⑤ 正则兜底
        if not url:
            vm = re.search(r'["\'](https?://[^"\']+\.(?:mp4|m3u8|flv)[^"\']*)["\']', html_text, re.I)
            if vm:
                url = vm.group(1)

        # ②-⑤ 拿到的相对路径 → 补全
        if url and not url.startswith("http"):
            url = self._href(url)

        # 解码转义
        if url:
            url = url.replace("\\u0026", "&").replace("\\/", "/")

        return {
            "parse": 0 if url else 1,
            "playUrl": "",
            "url": url or page,
            "header": self.headers,
        }