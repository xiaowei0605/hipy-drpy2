from base.spider import Spider
import re
import json
import base64
import gzip
from urllib.parse import quote, unquote
import urllib.request

HOST = "https://vfbai.snnvh82.sbs"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

BLOCK_CIDS = {"953084", "961085", "971086", "976086"}
BLOCK_KW = ["小孩子", "门事件"]

CATS = [
{"type_id": "9500846", "type_name": "精品推荐"},
{"type_id": "9510846", "type_name": "国产传媒"},
{"type_id": "9520846", "type_name": "探花系列"},
{"type_id": "9530846", "type_name": "偷拍自拍"},
{"type_id": "9540846", "type_name": "熟女少妇"},
{"type_id": "9550846", "type_name": "无码专区"},
{"type_id": "9560846", "type_name": "欧美性爱"},
{"type_id": "9570846", "type_name": "颜值正义"},
{"type_id": "9600856", "type_name": "美乳巨乳"},
{"type_id": "9610856", "type_name": "网曝事件"},
{"type_id": "9620856", "type_name": "国产主播"},
{"type_id": "9630856", "type_name": "中文字幕"},
{"type_id": "9640856", "type_name": "制服丝袜"},
{"type_id": "9650856", "type_name": "口交自慰"},
{"type_id": "9660856", "type_name": "国产精品"},
{"type_id": "9670856", "type_name": "大秀视频"},
{"type_id": "9700866", "type_name": "亚洲情色"},
{"type_id": "9710866", "type_name": "强奸乱伦"},
{"type_id": "9720866", "type_name": "伦理三级"},
{"type_id": "9730866", "type_name": "女同性恋"},
{"type_id": "9740866", "type_name": "明星换脸"},
{"type_id": "9750866", "type_name": "AV解说"},
{"type_id": "9760866", "type_name": "少女萝莉"},
{"type_id": "9770866", "type_name": "角色剧情"},
{"type_id": "9800876", "type_name": "精品网红"},
{"type_id": "9810876", "type_name": "多人群交"},
{"type_id": "9820876", "type_name": "SM调教"},
{"type_id": "9830876", "type_name": "动漫卡通"},
{"type_id": "9840876", "type_name": "变性伪娘"},
{"type_id": "9850876", "type_name": "VR视角"},
{"type_id": "9860876", "type_name": "反差母狗"},
{"type_id": "9870876", "type_name": "人妻系列"},
]

def _d(b64):
    try:
        d = base64.b64decode(b64).decode("utf-8", "replace")
        d = re.sub(r"<span[^>]*>.*?</span>", "", d, flags=re.S)
        d = re.sub(r"<[^>]+>", "", d).strip()
        return d
    except Exception:
        return ""

def _blocked(title):
    t = title.lower()
    for kw in BLOCK_KW:
        if kw.lower() in t:
            return True
    return False

class Spider(Spider):
    def init(self, extend=""):
        pass

    def _fetch(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        raw = urllib.request.urlopen(req, timeout=15).read()
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
        return raw.decode("utf-8", "replace")

    def _parse_list(self, html):
        vids = []
        seen = set()
        cards = re.findall(r'href="(/video\.php\?id=(\d+))"><img class="loadi" src="([^"]+)"', html)
        for url, vid, pic in cards:
            if vid in seen:
                continue
            seen.add(vid)
            m = re.search(r'href="/video\.php\?id=' + vid + r'"><script[^>]*>document\.write\(d\(\'([A-Za-z0-9+/=]+)\'\)\);</script>', html)
            title = _d(m.group(1)) if m else vid
            if not title or _blocked(title):
                continue
            vids.append({"vod_id": vid, "vod_name": title, "vod_pic": pic, "vod_remarks": ""})
        return vids

    def _pagecount(self, html):
        pages = re.findall(r"page=(\d+)", html)
        return max([int(p) for p in pages]) if pages else 1

    def homeContent(self, filter=False):
        return {"class": CATS, "list": [], "filters": {}}

    def homeVideoContent(self):
        return self.categoryContent("9500846", 1, True, {})

    def categoryContent(self, tid, pg, filter, extend):
        if tid in BLOCK_CIDS:
            return {"list": [], "page": pg, "pagecount": 0, "limit": 20, "total": 0}
        pg = int(pg)
        html = self._fetch(f"{HOST}/list.php?id={tid}&page={pg}")
        vids = self._parse_list(html)
        return {"list": vids, "page": pg, "pagecount": self._pagecount(html), "limit": 20, "total": 999999}

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, list) else ids
        html = self._fetch(f"{HOST}/video.php?id={vid}")
        m = re.search(r"hls\.loadSource\('([^']+)'\)", html)
        url = m.group(1) if m else ""
        tm = re.search(r"<title>([^<]*)</title>", html)
        title = tm.group(1).strip() if tm else vid
        pm = re.search(r'<img class="loadi" src="([^"]+)"', html)
        pic = pm.group(1) if pm else ""
        vod = {"vod_id": vid, "vod_name": title, "vod_pic": pic, "vod_play_from": "播放", "vod_play_url": f"正片${url}"}
        return {"list": [vod]}

    def searchContent(self, key, quick=False, pg="1"):
        for kw in BLOCK_KW:
            if kw.lower() in key.lower():
                return {"list": []}
        html = self._fetch(f"{HOST}/search.php?content={quote(key)}&type=1")
        vids = self._parse_list(html)
        if not vids:
            m = re.search(r'window\.location\.replace\("(/list\.php\?id=\d+&page=1)"\)', html)
            if m:
                html = self._fetch(HOST + m.group(1))
                vids = self._parse_list(html)
        return {"list": vids}

    def playerContent(self, flag, ids, vipFlags=None):
        url = ids[0] if isinstance(ids, list) else ids
        return {"parse": 0, "url": url, "header": {"User-Agent": UA}}

    def localProxy(self, param):
        return [200, "text/plain", b""]
