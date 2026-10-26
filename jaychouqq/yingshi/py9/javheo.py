# -*- coding: utf-8 -*-
import re
import json
import gzip
import ssl
import urllib.request
import urllib.parse
import http.cookiejar
from base.spider import Spider

try:
    import zlib
except Exception:
    zlib = None

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
HOST = "https://javheo.com"

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


class Spider(Spider):
    def __init__(self):
        super().__init__()
        self.host = HOST
        self.headers = {"User-Agent": UA, "Accept-Encoding": "identity"}
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=_ctx),
            urllib.request.HTTPCookieProcessor(self._jar),
        )
        self._cat_slugs = []
        self._art_cache = {}

    def getName(self):
        return "javheo"

    def init(self, extend=""):
        return True

    def _fetch(self, url, data=None, referer=None):
        try:
            headers = dict(self.headers)
            if referer:
                headers["Referer"] = referer
            if data is not None:
                body = urllib.parse.urlencode(data).encode("utf-8")
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            else:
                req = urllib.request.Request(url, headers=headers, method="GET")
            with self._opener.open(req, timeout=20) as resp:
                raw = resp.read(2 * 1024 * 1024)
                enc = resp.headers.get("Content-Encoding", "") or ""
                if "gzip" in enc:
                    raw = gzip.decompress(raw)
                elif "deflate" in enc and zlib is not None:
                    raw = zlib.decompress(raw)
                return raw.decode("utf-8", "ignore")
        except Exception:
            return None

    def _parse_cards(self, html):
        if not html:
            return []
        links = list(re.finditer(r'href="(?:https?://javheo\.com)?/watch/([A-Za-z0-9]+)"', html))
        items = []
        for i, m in enumerate(links):
            wid = m.group(1)
            start = m.start()
            end = m.end()
            next_start = links[i + 1].start() if i + 1 < len(links) else len(html)
            win_start = max(0, start - 800)
            win = html[win_start:next_start]
            win_after = html[end:next_start]
            pic = ""
            pm = re.search(r'<img[^>]+src="([^"]+)"', win_after) or re.search(r'<img[^>]+src="([^"]+)"', win)
            if pm:
                pic = pm.group(1)
                if pic.startswith("//"):
                    pic = "https:" + pic
                elif pic.startswith("/"):
                    pic = self.host + pic
            title = ""
            am = re.search(r'alt="([^"]+)"', win_after) or re.search(r'alt="([^"]+)"', win)
            if am:
                title = am.group(1)
            else:
                tm = re.search(r'>([^<>]{2,200})<', win_after)
                if tm:
                    title = tm.group(1)
            quality = ""
            best_dist = None
            for qm in re.finditer(r'(4K|1080p|720p|480p)', win, re.I):
                dist = abs((win_start + qm.start()) - start)
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    quality = qm.group(1)
            dmin = None
            best_dist = None
            for dm in re.finditer(r'(\d{1,3}):(\d{2}):(\d{2})', win):
                dist = abs((win_start + dm.start()) - start)
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    dmin = int(dm.group(1)) * 60 + int(dm.group(2))
            if dmin is None:
                for dm in re.finditer(r'(\d{1,3}):(\d{2})', win):
                    dist = abs((win_start + dm.start()) - start)
                    if best_dist is None or dist < best_dist:
                        best_dist = dist
                        dmin = int(dm.group(1))
            if dmin is None:
                mm = re.search(r'(\d+)\s*MIN', win, re.I)
                if mm:
                    dmin = int(mm.group(1))
            title = re.sub(r'(4K|1080p|720p|480p)', '', title, flags=re.I)
            title = re.sub(r'\d{1,3}:\d{2}(:\d{2})?', '', title)
            title = re.sub(r'\s+', ' ', title).strip(' |-')
            if quality and dmin is not None:
                remark = "%s·%d分" % (quality, dmin)
            elif quality:
                remark = quality
            elif dmin is not None:
                remark = "%d分" % dmin
            else:
                remark = ""
            items.append({"vod_id": wid, "vod_name": title, "vod_pic": pic, "vod_remarks": remark, "_q": quality.lower(), "_dmin": dmin})
        rank = {"4k": 3, "1080p": 2, "720p": 1, "480p": 0, "": -1}
        best = {}
        order = []
        for it in items:
            wid = it["vod_id"]
            if wid not in best:
                best[wid] = it
                order.append(wid)
            elif rank.get(it["_q"], -1) > rank.get(best[wid]["_q"], -1):
                best[wid] = it
        return [best[wid] for wid in order]

    def _clean(self, cards):
        out = []
        for c in cards:
            out.append({"vod_id": c.get("vod_id", ""), "vod_name": c.get("vod_name", ""), "vod_pic": c.get("vod_pic", ""), "vod_remarks": c.get("vod_remarks", "")})
        return out

    def _apply_filters(self, cards, extend):
        if isinstance(extend, list):
            if extend and isinstance(extend[0], dict):
                extend = extend[0]
            else:
                extend = {}
        if isinstance(extend, str):
            try:
                extend = json.loads(extend) if extend else {}
            except Exception:
                extend = {}
        if not isinstance(extend, dict):
            extend = {}
        q = str(extend.get("quality", "")).lower()
        d = str(extend.get("duration", ""))
        out = []
        for c in cards:
            if q and c.get("_q", "") != q:
                continue
            if d:
                dmin = c.get("_dmin")
                if dmin is None:
                    continue
                if d == "short" and not (dmin < 60):
                    continue
                if d == "medium" and not (60 <= dmin <= 120):
                    continue
                if d == "long" and not (dmin > 120):
                    continue
            out.append(c)
        return self._clean(out)

    def homeContent(self, filter):
        classes = [{"type_id": "recommend", "type_name": "推荐"}]
        slugs = []
        xml = self._fetch(self.host + "/sitemaps/category.xml")
        if xml:
            for loc in re.findall(r'<loc>([^<]+)</loc>', xml):
                mm = re.search(r'/porn/([a-z0-9-]+)/?$', loc.strip())
                if mm and mm.group(1) not in slugs:
                    slugs.append(mm.group(1))
        if not slugs:
            home_html = self._fetch(self.host + "/")
            if home_html:
                for s in re.findall(r'/porn/([a-z0-9-]+)/', home_html):
                    if s not in slugs:
                        slugs.append(s)
        self._cat_slugs = slugs
        for s in slugs:
            classes.append({"type_id": s, "type_name": s.replace("-", " ").title()})
        filters = {}
        for cl in classes:
            if cl["type_id"] in ("home", "recommend"):
                continue
            filters[cl["type_id"]] = [
                {"key": "quality", "name": "清晰度", "value": [{"n": "全部", "v": ""}, {"n": "4K", "v": "4k"}, {"n": "1080p", "v": "1080p"}, {"n": "720p", "v": "720p"}]},
                {"key": "duration", "name": "时长", "value": [{"n": "全部", "v": ""}, {"n": "短片<60分", "v": "short"}, {"n": "中片60-120分", "v": "medium"}, {"n": "长片>120分", "v": "long"}]},
            ]
        return {"class": classes, "filters": filters, "list": []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        if tid in ("home", "recommend"):
            if pg != 1:
                return {"page": pg, "pagecount": 1, "limit": 50, "total": 0, "list": []}
            html = self._fetch(self.host + "/")
            cards = self._parse_cards(html or "")[:50]
            filtered = self._apply_filters(cards, extend)
            return {"page": pg, "pagecount": 1, "limit": 50, "total": len(filtered), "list": filtered}
        if pg == 1:
            html = self._fetch(self.host + "/porn/" + tid + "/")
            cards = self._parse_cards(html or "")
        else:
            html = self._fetch(self.host + "/hash-javheo", data={"mix": "video-next2", "value": tid, "page": pg - 1}, referer=self.host + "/porn/" + tid + "/")
            cards = self._parse_cards(html or "")
        raw_count = len(cards)
        pagecount = pg if raw_count < 50 else 999
        return {"page": pg, "pagecount": pagecount, "limit": 50, "total": pagecount * 50, "list": self._apply_filters(cards, extend)}

    def detailContent(self, ids):
        wid = ids[0] if isinstance(ids, list) else ids
        html = self._fetch(self.host + "/watch/" + wid)
        if not html:
            return {"list": []}
        name = ""
        tm = re.search(r'<title>(.*?)</title>', html, re.S)
        if tm:
            name = re.sub(r'\s+', ' ', tm.group(1)).strip()
        pic = ""
        pm = re.search(r'property="og:image"[^>]+content="([^"]+)"', html) or re.search(r'content="([^"]+)"[^>]+property="og:image"', html)
        if pm:
            pic = pm.group(1)
            if pic.startswith("//"):
                pic = "https:" + pic
        duration_min = None
        dm = re.search(r'video:duration["\']?\s*content="(\d+)"', html)
        if dm:
            duration_min = int(dm.group(1)) // 60
        else:
            dm2 = re.search(r'video:duration[^0-9]{0,30}(\d+)', html)
            if dm2:
                duration_min = int(dm2.group(1)) // 60
        if duration_min is None:
            tm2 = re.search(r'TIME\s*(\d+)\s*MIN', html, re.I)
            if tm2:
                duration_min = int(tm2.group(1))
        tags = []
        cats = set(self._cat_slugs)
        for s in re.findall(r'href="https?://javheo\.com/porn/([a-z0-9-]+)/?"', html):
            if s not in cats and s not in tags:
                tags.append(s)
                if len(tags) >= 12:
                    break
        parts = []
        if duration_min is not None:
            parts.append("时长：%d分" % duration_min)
        if tags:
            parts.append("标签：" + " / ".join([t.replace("-", " ").title() for t in tags]))
        play_from = ["在线播放"]
        play_url = ["正片$%s" % wid]
        for tag in tags[:5]:
            rec_html = self._fetch(self.host + "/porn/" + tag + "/")
            if not rec_html or len(rec_html) < 1000:
                continue
            rec_cards = self._parse_cards(rec_html)
            rec = [c for c in rec_cards if c["vod_id"] != wid][:9]
            if rec:
                play_from.append("同标签推荐")
                play_url.append("#".join("%s$%s" % (c["vod_name"].replace("$", "").replace("#", ""), c["vod_id"]) for c in rec))
                break
        return {"list": [{"vod_id": wid, "vod_name": name, "vod_pic": pic, "vod_year": "", "vod_area": "", "vod_remarks": ("%d分" % duration_min) if duration_min is not None else "", "vod_actor": "", "vod_director": "", "vod_content": "\n".join(parts), "vod_play_from": "$$$".join(play_from), "vod_play_url": "$$$".join(play_url)}]}

    def _resolve_play(self, wid):
        if wid in self._art_cache:
            return self._art_cache[wid]
        detail_url = self.host + "/watch/" + wid
        html = self._fetch(detail_url)
        if not html:
            return None
        post = self._fetch(self.host + "/hash-javheo", data={"mix": "moviesiframe2", "num": wid}, referer=detail_url)
        if not post:
            return None
        im = re.search(r'<iframe[^>]+src="([^"]+)"', post)
        if not im:
            return None
        src2 = im.group(1)
        if src2.startswith("//"):
            src2 = "https:" + src2
        page2 = self._fetch(src2, referer=detail_url)
        if not page2:
            return None
        im2 = re.search(r'<iframe[^>]+src="([^"]+)"', page2)
        if not im2:
            return None
        src3 = im2.group(1)
        if src3.startswith("//"):
            src3 = "https:" + src3
        page3 = self._fetch(src3, referer=src2)
        if not page3:
            return None
        am = re.search(r'new Artplayer\(\{.*?url:\s*["\']([^"\']+)', page3, re.S)
        if not am:
            return None
        result = (am.group(1), src3)
        self._art_cache[wid] = result
        return result

    def playerContent(self, flag, id, vipFlags):
        if isinstance(id, str) and id.startswith("http"):
            return {"parse": 0, "url": id, "header": {"User-Agent": UA, "Referer": self.host + "/"}}
        wid = id
        res = self._resolve_play(wid)
        if res:
            return {"parse": 0, "url": res[0], "header": {"User-Agent": UA, "Referer": res[1]}}
        return {"parse": 1, "url": self.host + "/watch/" + wid}

    def searchContent(self, key, quick, pg):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        slug = re.sub(r'[^a-z0-9-]', '-', key.lower())
        slug = re.sub(r'-+', '-', slug).strip('-')
        if not slug:
            return {"page": pg, "pagecount": 1, "limit": 50, "total": 0, "list": []}
        if pg == 1:
            html = self._fetch(self.host + "/porn/" + slug + "/")
            cards = self._parse_cards(html or "")
        else:
            html = self._fetch(self.host + "/hash-javheo", data={"mix": "video-next2", "value": slug, "page": pg - 1}, referer=self.host + "/porn/" + slug + "/")
            cards = self._parse_cards(html or "")
        norm_key = re.sub(r'[^a-z0-9]', '', key.lower())
        if norm_key:
            def score(c):
                norm_name = re.sub(r'[^a-z0-9]', '', c.get("vod_name", "").lower())
                return 0 if norm_key in norm_name else 1
            cards = sorted(cards, key=score)
        raw_count = len(cards)
        pagecount = pg if raw_count < 50 else 999
        return {"page": pg, "pagecount": pagecount, "limit": 50, "total": pagecount * 50, "list": self._clean(cards)}