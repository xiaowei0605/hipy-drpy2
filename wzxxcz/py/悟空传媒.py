# -*- coding: utf-8 -*-
# 悟空传媒 - FongMi / Pyramid / TVBox Python 源
# 修复：分类空列表、推荐播放无线路/暂无播放数据
#
# 配置示例:
# {
#   "key": "py_wukong",
#   "name": "悟空传媒",
#   "type": 3,
#   "api": "py_悟空传媒",
#   "searchable": 1,
#   "quickSearch": 1,
#   "filterable": 0,
#   "ext": "https://www.wukong123.vip"
# }

import re
import sys
import json
import time

sys.path.append("..")
try:
    from base.spider import Spider as BaseSpider
except Exception:
    try:
        from spider import Spider as BaseSpider
    except Exception:
        class BaseSpider(object):
            def __init__(self):
                self.extend = ""


class Spider(BaseSpider):
    def __init__(self):
        self.extend = ""
        self.host = "https://www.wukong123.vip"
        self.hosts = [
            "https://www.wukong123.vip",
            "https://wt2fo21t.yydswwuk183.lol",
            "https://www.yydswwuk183.lol",
        ]
        self.host_idx = 0
        self.host_ts = 0
        self.ttl = 15
        self.ua = (
            "Mozilla/5.0 (Linux; Android 13; Mobile) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Mobile Safari/537.36"
        )
        # type_id 与站内一致
        self.classes = [
            {"type_id": "1", "type_name": "国产"},
            {"type_id": "6", "type_name": "自拍"},
            {"type_id": "7", "type_name": "乱伦毁三观"},
            {"type_id": "8", "type_name": "强奸"},
            {"type_id": "9", "type_name": "传媒"},
            {"type_id": "10", "type_name": "反差婊"},
            {"type_id": "11", "type_name": "网爆门"},
            {"type_id": "12", "type_name": "偷拍"},
            {"type_id": "30", "type_name": "兄弟姐妹"},
            {"type_id": "31", "type_name": "禁忌母子"},
            {"type_id": "32", "type_name": "狂操小姨"},
            {"type_id": "33", "type_name": "猛干嫂子"},
            {"type_id": "34", "type_name": "野外车震"},
            {"type_id": "35", "type_name": "夫妻交换"},
            {"type_id": "36", "type_name": "淫荡儿媳"},
            {"type_id": "37", "type_name": "学生下海"},
            {"type_id": "2", "type_name": "网红"},
            {"type_id": "3", "type_name": "萝莉"},
            {"type_id": "13", "type_name": "福利姬"},
            {"type_id": "14", "type_name": "吃瓜"},
            {"type_id": "15", "type_name": "大学生"},
            {"type_id": "16", "type_name": "人兽"},
            {"type_id": "5", "type_name": "探花"},
            {"type_id": "4", "type_name": "大秀"},
            {"type_id": "38", "type_name": "瑜伽裤"},
            {"type_id": "39", "type_name": "兽耳系列"},
            {"type_id": "40", "type_name": "多人群P"},
            {"type_id": "41", "type_name": "Cosplay"},
            {"type_id": "17", "type_name": "人妖"},
            {"type_id": "18", "type_name": "OnlyFans"},
            {"type_id": "20", "type_name": "喷水"},
            {"type_id": "21", "type_name": "裸贷"},
            {"type_id": "22", "type_name": "性虐"},
            {"type_id": "23", "type_name": "AI换脸"},
            {"type_id": "24", "type_name": "无码"},
            {"type_id": "25", "type_name": "中文字幕"},
            {"type_id": "26", "type_name": "欧美"},
            {"type_id": "27", "type_name": "动漫"},
            {"type_id": "28", "type_name": "三级片"},
            {"type_id": "29", "type_name": "AV解说"},
        ]

    def init(self, extend=""):
        self.extend = (extend or "").strip()
        if self.extend.startswith("http"):
            h = self.extend.rstrip("/")
            self.host = h
            if h not in self.hosts:
                self.hosts.insert(0, h)
        else:
            self.host = self.hosts[0]
        self.host_ts = time.time()

    def getName(self):
        return "悟空传媒"

    def isVideoFormat(self, url):
        return bool(re.search(r"\.(m3u8|mp4|flv)(\?|$)", str(url or ""), re.I))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ---------------- HTTP ----------------
    def _hdr(self, host=None):
        h = host or self.host
        return {
            "User-Agent": self.ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": h.rstrip("/") + "/",
            "Origin": h.rstrip("/"),
            "Cache-Control": "no-cache",
        }

    def _ok(self, html):
        if not html or len(html) < 200:
            return False
        head = html[:1200].lower()
        if "just a moment" in head or "cf-browser-verification" in head:
            return False
        if "access denied" in head or "403 forbidden" in head:
            return False
        return True

    def _resp_text(self, r):
        if r is None:
            return ""
        if isinstance(r, str):
            return r
        if isinstance(r, bytes):
            return r.decode("utf-8", "ignore")
        if isinstance(r, dict):
            for k in ("content", "body", "data", "text", "result"):
                if k in r and r[k]:
                    v = r[k]
                    return v.decode("utf-8", "ignore") if isinstance(v, bytes) else str(v)
            return ""
        # requests / FongMi Response
        for attr in ("text", "content", "body"):
            if hasattr(r, attr):
                v = getattr(r, attr)
                if callable(v):
                    continue
                if isinstance(v, bytes):
                    return v.decode("utf-8", "ignore")
                if v:
                    return str(v)
        return str(r)

    def _raw_get(self, url, headers):
        # 1) FongMi / Pyramid self.fetch
        if hasattr(self, "fetch"):
            try:
                try:
                    r = self.fetch(url, headers=headers, timeout=30)
                except TypeError:
                    try:
                        r = self.fetch(url, headers)
                    except TypeError:
                        r = self.fetch(url)
                t = self._resp_text(r)
                if t:
                    return t
            except Exception:
                pass
        # 2) requests
        try:
            import requests
            r = requests.get(url, headers=headers, timeout=25, verify=False)
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except Exception:
            pass
        # 3) urllib
        import urllib.request
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.read().decode("utf-8", "ignore")

    def getHtml(self, path):
        """取页面，失败自动换域名"""
        path = path or "/"
        is_abs = path.startswith("http")
        last = ""
        n = len(self.hosts)
        start = self.host_idx
        # 超时轮换
        if time.time() - self.host_ts >= self.ttl:
            start = (self.host_idx + 1) % n
        for k in range(n):
            i = (start + k) % n
            host = self.hosts[i]
            url = path if is_abs else (host.rstrip("/") + (path if path.startswith("/") else "/" + path))
            try:
                html = self._raw_get(url, self._hdr(host))
                if self._ok(html):
                    self.host = host
                    self.host_idx = i
                    self.host_ts = time.time()
                    # 有列表或播放数据才算成功；首页例外
                    if (
                        "class=\"card\"" in html
                        or "player_data" in html
                        or path in ("/", "")
                        or "最新发布" in html
                    ):
                        return html
                    last = html
            except Exception:
                continue
        return last

    def _abs(self, u):
        if not u:
            return ""
        u = str(u).replace("&amp;", "&").strip().strip("'\"")
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("http"):
            return u
        return self.host.rstrip("/") + (u if u.startswith("/") else "/" + u)

    def _clean(self, t):
        if not t:
            return ""
        t = re.sub(r"<[^>]+>", "", str(t))
        t = (
            t.replace("&amp;", "&")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
            .replace("&nbsp;", " ")
        )
        return re.sub(r"\s+", " ", t).strip()

    # ---------------- 列表 ----------------
    def parseList(self, html):
        res, seen = [], set()
        if not html:
            return res
        # /play/ID.html 或 /index.php/play/ID.html
        pat = re.compile(
            r'class="card"[\s\S]{0,80}?'
            r'href="((?:/index\.php)?/play/(\d+)\.html)"[^>]*'
            r'title="([^"]*)"[^>]*'
            r'style="[^"]*url\(([^)]+)\)"',
            re.I,
        )
        for m in pat.finditer(html):
            vid = m.group(2)
            if vid in seen:
                continue
            seen.add(vid)
            # 附近取评分
            start = max(0, m.start() - 20)
            chunk = html[start: m.end() + 280]
            score = ""
            sm = re.search(r'badge-score">([^<]+)', chunk)
            if sm:
                score = self._clean(sm.group(1))
            badge = ""
            bm = re.search(r'class="badge"[^>]*>([^<]+)', chunk)
            if bm:
                badge = self._clean(bm.group(1))
            res.append(
                {
                    "vod_id": vid,
                    "vod_name": self._clean(m.group(3)),
                    "vod_pic": self._abs(m.group(4)),
                    "vod_remarks": score or badge or "",
                }
            )
        if res:
            return res
        # 再宽松
        pat2 = re.compile(
            r'href="((?:/index\.php)?/play/(\d+)\.html)"[^>]*title="([^"]+)"',
            re.I,
        )
        for m in pat2.finditer(html):
            vid = m.group(2)
            if vid in seen:
                continue
            seen.add(vid)
            res.append(
                {
                    "vod_id": vid,
                    "vod_name": self._clean(m.group(3)),
                    "vod_pic": "",
                    "vod_remarks": "",
                }
            )
        return res

    def parsePlayer(self, html):
        info = {"url": "", "from": "ytm3u8", "title": "", "pic": "", "tags": [], "desc": ""}
        if not html:
            return info
        m = re.search(r"player_data\s*=\s*(\{[^;]*\})", html)
        if m:
            raw = m.group(1).replace("\\/", "/").replace("\\u002F", "/")
            try:
                obj = json.loads(raw)
                info["url"] = (obj.get("url") or "").strip()
                info["from"] = (obj.get("from") or "ytm3u8").strip()
            except Exception:
                um = re.search(r'"url"\s*:\s*"([^"]+)"', raw)
                if um:
                    info["url"] = um.group(1).replace("\\/", "/")
                fm = re.search(r'"from"\s*:\s*"([^"]+)"', raw)
                if fm:
                    info["from"] = fm.group(1)
        if not info["url"]:
            m = re.search(r'(https?://[^\s"\'<>\\]+\\.m3u8[^\s"\'<>\\]*)', html, re.I)
            if m:
                info["url"] = m.group(1).replace("\\/", "/")
        m = re.search(r"<h1[^>]*>([^<]+)</h1>", html, re.I)
        if m:
            info["title"] = self._clean(m.group(1))
        if not info["title"]:
            m = re.search(r"<title>([^<_<]+)", html, re.I)
            if m:
                info["title"] = self._clean(m.group(1))
        m = re.search(r'data-pic="([^"]+)"', html)
        if m:
            info["pic"] = self._abs(m.group(1))
        m = re.search(r'name="keywords"\s+content="([^"]+)"', html, re.I)
        if m:
            for t in re.split(r"[,，]", m.group(1)):
                t = self._clean(t)
                if t and len(t) < 24 and t not in info["tags"]:
                    info["tags"].append(t)
        m = re.search(r'name="description"\s+content="([^"]+)"', html, re.I)
        if m:
            info["desc"] = self._clean(m.group(1))
        return info

    # ---------------- 接口 ----------------
    def homeContent(self, filter):
        return {"class": self.classes, "list": []}

    def homeVideoContent(self):
        try:
            html = self.getHtml("/")
            return {"list": self.parseList(html)}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        result = {
            "list": [],
            "page": int(pg or 1),
            "pagecount": 9999,
            "limit": 24,
            "total": 999999,
        }
        try:
            tid = str(tid).strip()
            pg = str(pg or "1").strip()
            # 兼容 tid 误传成中文名
            for c in self.classes:
                if c["type_name"] == tid:
                    tid = c["type_id"]
                    break
            paths = []
            if pg in ("1", "0", ""):
                paths = [
                    "/vod/{}.html".format(tid),
                    "/vod/{}-1.html".format(tid),
                    "/index.php/vod/type/id/{}.html".format(tid),
                ]
            else:
                paths = [
                    "/vod/{}-{}.html".format(tid, pg),
                    "/vod/show/id/{}/page/{}.html".format(tid, pg),
                    "/index.php/vod/type/id/{}/page/{}.html".format(tid, pg),
                ]
            videos = []
            for p in paths:
                html = self.getHtml(p)
                videos = self.parseList(html)
                if videos:
                    break
            result["list"] = videos
            result["page"] = int(pg or 1)
            if not videos:
                result["pagecount"] = result["page"]
        except Exception:
            pass
        return result

    def detailContent(self, ids):
        """关键：必须带出 vod_play_from / vod_play_url，否则显示「暂无播放数据」"""
        try:
            vid = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
            vid = vid.strip().split("_")[0]
            html = ""
            for p in [
                "/v-p/{}-1-1.html".format(vid),
                "/index.php/v-p/{}-1-1.html".format(vid),
                "/play/{}.html".format(vid),
                "/index.php/play/{}.html".format(vid),
            ]:
                html = self.getHtml(p)
                if html and "player_data" in html:
                    break
            # 详情页没有 player_data 时跟一次真正播放页
            if html and "player_data" not in html:
                m = re.search(r'href="((?:/index\.php)?/v-p/\d+-\d+-\d+\.html)"', html)
                if m:
                    html = self.getHtml(m.group(1))
            if not html or "player_data" not in html:
                html = self.getHtml("/v-p/{}-1-1.html".format(vid))

            info = self.parsePlayer(html)
            title = info["title"] or ("视频" + vid)
            pic = info["pic"] or ""
            tags = info["tags"]
            desc = info["desc"] or title
            line = info["from"] or "ytm3u8"
            url = (info["url"] or "").strip()

            # 没有直链就让 playerContent 再解，但线路名必须有
            if url:
                play_url = "正片$" + url
            else:
                play_url = "正片$" + vid

            vod = {
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": pic,
                "type_name": tags[0] if tags else "",
                "vod_year": "",
                "vod_area": "",
                "vod_remarks": " / ".join(tags[:6]),
                "vod_actor": "",
                "vod_director": "",
                "vod_content": desc,
                "vod_play_from": line,
                "vod_play_url": play_url,
            }
            return {"list": [vod]}
        except Exception:
            # 保底：至少返回可点的壳，避免「暂无播放数据」
            vid = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
            return {
                "list": [
                    {
                        "vod_id": vid,
                        "vod_name": "视频" + vid,
                        "vod_pic": "",
                        "vod_content": "",
                        "vod_play_from": "ytm3u8",
                        "vod_play_url": "正片$" + vid,
                    }
                ]
            }

    def searchContent(self, key, quick, pg="1"):
        try:
            key = str(key).strip()
            pg = str(pg or "1")
            if pg == "1":
                paths = [
                    "/sou/{}-.html".format(key),
                    "/sou/-.html?wd={}".format(key),
                    "/index.php/vod/search.html?wd={}".format(key),
                ]
            else:
                paths = ["/sou/{}-{}.html".format(key, pg)]
            videos = []
            for p in paths:
                html = self.getHtml(p)
                videos = self.parseList(html)
                if videos:
                    break
            return {"list": videos, "page": int(pg)}
        except Exception:
            return {"list": []}

    def playerContent(self, flag, id, vipFlags):
        headers = {
            "User-Agent": self.ua,
            "Referer": self.host.rstrip("/") + "/",
            "Origin": self.host.rstrip("/"),
        }
        result = {"parse": 0, "jx": 0, "url": "", "header": headers}
        try:
            raw = str(id or "").strip()
            # 详情已写入完整 m3u8
            if self.isVideoFormat(raw):
                result["url"] = raw
                return result
            if "$" in raw:
                raw = raw.split("$")[-1].strip()
                if self.isVideoFormat(raw):
                    result["url"] = raw
                    return result

            vid = raw
            html = self.getHtml("/v-p/{}-1-1.html".format(vid))
            if "player_data" not in (html or ""):
                html = self.getHtml("/index.php/v-p/{}-1-1.html".format(vid))
            info = self.parsePlayer(html or "")
            if not info["url"]:
                d = self.getHtml("/play/{}.html".format(vid))
                m = re.search(r'href="((?:/index\.php)?/v-p/\d+-\d+-\d+\.html)"', d or "")
                if m:
                    info = self.parsePlayer(self.getHtml(m.group(1)))
            url = (info.get("url") or "").strip()
            result["url"] = url
            result["parse"] = 0 if url else 1
            if url and "://" in url:
                try:
                    from urllib.parse import urlparse

                    p = urlparse(url)
                    headers["Referer"] = p.scheme + "://" + p.netloc + "/"
                    result["header"] = headers
                except Exception:
                    pass
        except Exception:
            result["parse"] = 1
        return result


if __name__ == "__main__":
    s = Spider()
    s.init("https://www.wukong123.vip")
    print("classes", len(s.homeContent(False)["class"]))
    h = s.homeVideoContent()["list"]
    print("home", len(h), h[0]["vod_name"][:30] if h else None)
    c = s.categoryContent("1", "1", False, {})["list"]
    print("国产", len(c), c[0]["vod_name"][:30] if c else None)
    c2 = s.categoryContent("35", "1", False, {})["list"]
    print("夫妻", len(c2))
    if h:
        d = s.detailContent([h[0]["vod_id"]])["list"][0]
        print("detail from", d.get("vod_play_from"), "url", (d.get("vod_play_url") or "")[:90])
        p = s.playerContent(d["vod_play_from"], d["vod_play_url"].split("$")[-1], [])
        print("play", (p.get("url") or "")[:90], "parse", p.get("parse"))
