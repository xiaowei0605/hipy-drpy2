# coding=utf-8
# !/usr/bin/python
"""
电影侠 (dyxia / hhkan.tv) 影视+ Python 源
================================================
本源码基于对 hhkan.tv 系客户端 (协议版本 v5) 的协议还原重写，
修正了原版中已失效的域名、签名与播放链路，并补全了所有必需方法。

协议要点
--------
1. 接口层  https://<vcache|vlogic>.<域名>/v5/**\.capi
   * 响应 A **AES-256-CBC** 加密，key = "ayt5wy5afwmwrpb1" + "9k9s3psx3dymyd0n"
     iv = "b3t069ijy7pirw0j"，明文为 JSON。
   * 请求须携带 appId / deviceCreatedAt / deviceId / st / userId / TS / pkg / ver / os
     以及 sign（HMAC-SHA1）。缺少 os 头直接 500，缺少设备头返回 40100/40101。
   * 错误码：40100/40101 头不全，40105 签名错误，40005 参数错误，40401 无数据。
2. 播放层  https://box.dyrs.com.de/api/…（CDN 调度，无需鉴权，是本源的主链路）
   * /api/super?g=<源>&id=<vid>           → master m3u8
   * /api/m3u8?g=<源>&id=<vid>[&raw=1]    → 媒体 m3u8
       不带 raw=1 时分片是 /api/ts?... 中转地址；
       带 raw=1   时直接返回 CDN 真实分片地址（v.lzcdn27.com/…/*.ts）。
   * /api/ts?m3u8_id=..&index=..&uuid=..  → 中转分片
       不带 raw=1 会**故意返回 image/png** 反盗链；
       带上 raw=1 才返回真正的 MPEG-TS（首字节 0x47）。
   * 结论：一律走 raw=1，并优先直连 CDN 分片（免中转、免反盗链、支持 Range）。

作者说明
--------
1. 接口层签名密钥由服务端随客户端版本轮换。本源把候选密钥放在 SIGN_KEYS，
   运行期按序探测、命中即缓存；若全部失效则接口层（首页/分类/搜索/详情）
   返回空列表，但不会抛异常。
2. **播放层不依赖签名**，只依赖 /api/super 与 /api/m3u8 的 g+id 参数，
   因此即便接口层失效，已知 vod id 依然可以完整播放。
3. 分片务必追加 raw=1：不带 raw=1 时 /api/ts 会故意返回 image/png 反盗链；
   带 raw=1 时 /api/m3u8 直接给出 CDN 真实 .ts 地址，可免中转直连。
4. 若日后要恢复接口层，只需把新密钥追加进 SIGN_KEYS 即可，无需改其它逻辑。
"""

import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
import uuid
import random

import requests
from requests.adapters import HTTPAdapter

try:
    from base.spider import Spider as _TVBoxSpider
except Exception:  # 本地调试时的兜底
    class _TVBoxSpider(object):
        def init(self, extend=""):
            pass

        def getProxyUrl(self, local=True):
            return ""

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

INTRO_PREFIX = "🍊小橙子为您介绍剧情👉请不要相信视频中的广告，以免上当受骗！"

# ---- 接口层加密参数（AES-256-CBC） ---------------------------------------- #
ENC_KEY = b"ayt5wy5afwmwrpb1" + b"9k9s3psx3dymyd0n"
ENC_IV = b"b3t069ijy7pirw0j"

# ---- 接口层签名密钥候选（服务端可能轮换，按序探测，命中缓存） ------------- #
SIGN_KEYS = [
    b"ksggsr4tp6difdo1c3im8fqd3g",
]

# ---- CDN 播放调度 -------------------------------------------------------- #
PLAY_API = "https://box.dyrs.com.de"

# ---- 接口域名池（按可用性排序，运行时会做存活探测） ---------------------- #
API_HOSTS = [
    "vcache.shkjbd.com",
    "vcache.mjrlin.cn",
    "vcache.kvod14.com",
    "sblogic.kvod14.com",
    "www.hhkan.tv",
    "hhkan.tv",
]

# ---- 站点网页入口（用于取封面/兜底海报域名） ---------------------------- #
WEB_HOSTS = ["https://www.hhkan.tv", "https://hhkan.tv"]

UA = "okhttp/3.12.0"
PKG = "com.dyx.app"
APP_ID = "10000"
APP_VER = "5.0.0"

# 分类（接口层的 type_id；同时兼容按名称模糊匹配）
CATEGORIES = [
    {"type_id": "1", "type_name": "电影"},
    {"type_id": "2", "type_name": "电视剧"},
    {"type_id": "3", "type_name": "综艺"},
    {"type_id": "4", "type_name": "动漫"},
    {"type_id": "5", "type_name": "短剧"},
    {"type_id": "6", "type_name": "纪录片"},
]

RE_TS = re.compile(r"https?://[^\s#'\"]+?\.(?:ts|m4s|mp4)(?:\?[^\s#'\"]*)?", re.I)


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #

def _b64e(b):
    return base64.b64encode(b).decode()


def _is_ts(data):
    return bool(data) and data[0:1] == b"\x47"


# --------------------------------------------------------------------------- #
# 主类
# --------------------------------------------------------------------------- #

class Spider(_TVBoxSpider):
    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def init(self, extend=""):
        self.extend = extend or ""
        self._cfg = {}
        self._host = None          # 当前可用接口域名
        self._sign_key = None      # 已命中的签名密钥
        self._home_cache = (0, None)
        self._cat_cache = {}
        self._detail_cache = {}
        self.session = self._new_session()
        self._log("init done")
        return None

    def _new_session(self):
        s = requests.Session()
        s.trust_env = False
        s.verify = False
        try:
            requests.packages.urllib3.disable_warnings()
        except Exception:
            pass
        s.headers.update({
            "User-Agent": UA,
            "Accept-Encoding": "identity",   # 必须 identity，否则拿到 gzip 无法解密
            "pkg": PKG,
            "ver": APP_VER,
            "os": "android",
        })
        ad = HTTPAdapter(pool_connections=12, pool_maxsize=12, max_retries=0)
        s.mount("https://", ad)
        s.mount("http://", ad)
        return s

    def _log(self, msg):
        try:
            print("[dyxia] %s" % msg)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # 接口层：签名 + 解密
    # ------------------------------------------------------------------ #
    def _sign(self, path, query, ts, header_str, key):
        src = "get|%s|%s|%s|%s|" % (path, query, ts, header_str)
        return _b64e(hmac.new(key, src.encode("utf-8"), hashlib.sha1).digest())

    def _api_get(self, path, params=None, timeout=15):
        """
        签名调用接口层并解密。
        返回 dict；失败返回 None。
        """
        params = params or {}
        query = "&".join("%s=%s" % (k, v) for k, v in params.items())
        ts = str(int(time.time() * 1000))
        dev_id = self._cfg.get("deviceId") or uuid.uuid4().hex
        self._cfg["deviceId"] = dev_id
        user_id = str(self._cfg.get("userId") or "0")

        header_str = ("appId=%s,deviceCreatedAt=%s,deviceId=%s,st=1,userId=%s"
                      % (APP_ID, self._cfg.get("deviceCreatedAt", "1700000000000"),
                         dev_id, user_id))

        keys = ([self._sign_key] if self._sign_key else []) + \
               [k for k in SIGN_KEYS if k != self._sign_key]

        for host in self._candidate_hosts():
            for key in keys:
                hdr = dict(self.session.headers)
                hdr.update({
                    "appId": APP_ID,
                    "deviceCreatedAt": self._cfg.get("deviceCreatedAt", "1700000000000"),
                    "deviceId": dev_id,
                    "st": "1",
                    "userId": user_id,
                    "TS": ts,
                    "sign": self._sign(path, query, ts, header_str, key),
                })
                url = "https://%s%s%s" % (host, path, ("?" + query) if query else "")
                try:
                    r = self._get_checked(url, hdr, timeout)
                except Exception as e:
                    self._log("api net fail %s %s" % (host, str(e)[:80]))
                    continue
                if r is None:
                    continue

                data = self._decrypt(r.content)
                if not isinstance(data, dict):
                    continue
                code = data.get("code")
                if code in (200, 0):
                    self._host = host
                    self._sign_key = key
                    self._cfg["deviceCreatedAt"] = hdr["deviceCreatedAt"]
                    return data
                if code in (40100, 40101, 40105):
                    continue
                # 其他业务错误：直接返回，避免无谓重试
                if code is not None:
                    return data
        return None

    def _decrypt(self, raw):
        if not raw:
            return None
        if raw[:1] in (b"{", b"["):
            try:
                return json.loads(raw.decode("utf-8", "replace"))
            except Exception:
                return None
        if len(raw) % 16:
            return None
        try:
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import unpad
            c = AES.new(ENC_KEY, AES.MODE_CBC, ENC_IV)
            plain = unpad(c.decrypt(raw), 16)
            return json.loads(plain.decode("utf-8", "replace"))
        except Exception:
            return None

    def _candidate_hosts(self):
        if self._host:
            return [self._host] + [h for h in API_HOSTS if h != self._host]
        return list(API_HOSTS)

    _BAD_TLD = ("app", "appv5", "local", "internal", "invalid", "localhost")

    def _host_ok(self, host):
        """过滤畸形的重定向目标（例如 www.hhkan.appv5）。"""
        if not host or "." not in host:
            return False
        tld = host.rsplit(".", 1)[-1].lower()
        return tld not in self._BAD_TLD

    def _get_checked(self, url, headers, timeout, max_hop=4):
        """
        手动跟随重定向，并过滤畸形的 Location。
        接口域名会不定期换域名，但个别会返回无法解析的地址
        （如 https://www.hhkan.appv5/…），这类必须放弃而不是抛异常。
        """
        from urllib.parse import urlparse
        cur = url
        for _ in range(max_hop):
            r = self.session.get(cur, headers=headers, timeout=timeout,
                                 allow_redirects=False)
            if r.status_code not in (301, 302, 303, 307, 308):
                return r
            loc = r.headers.get("location") or ""
            if not loc:
                return r
            host = urlparse(loc).hostname or ""
            if not self._host_ok(host):
                self._log("skip bad redirect -> %s" % loc[:60])
                return None
            cur = loc
            # 换域后需要重新计算签名头（这里沿用原头，仅用于探测）
        return None

    # ------------------------------------------------------------------ #
    # 播放层
    # ------------------------------------------------------------------ #
    def _play_m3u8(self, vid, flag="", raw=True):
        """取媒体 m3u8 文本。raw=True 时返回 CDN 真实分片地址。"""
        q = "g=%s&id=%s%s" % (flag or "douhua", vid, "&raw=1" if raw else "")
        url = "%s/api/m3u8?%s" % (PLAY_API, q)
        for _ in range(2):
            try:
                r = self.session.get(url, timeout=20)
                if r.status_code == 200 and "#EXTM3U" in r.text:
                    return r.text
            except Exception as e:
                self._log("m3u8 fail %s" % e)
            time.sleep(0.4)
        return None

    def _play_master(self, vid, flag=""):
        """取 master m3u8（多码率）。失败返回 None。"""
        url = "%s/api/super?g=%s&id=%s" % (PLAY_API, flag or "douhua", vid)
        try:
            r = self.session.get(url, timeout=15, allow_redirects=False)
            if r.status_code in (301, 302) and r.headers.get("location"):
                loc = r.headers["location"]
                r2 = self.session.get(loc, timeout=15)
                if r2.status_code == 200 and "#EXTM3U" in r2.text:
                    return r2.text, r2.url
            if r.status_code == 200 and "#EXTM3U" in r.text:
                return r.text, r.url
        except Exception as e:
            self._log("master fail %s" % e)
        return None

    def _absolutize(self, text, base_url):
        """把 m3u8 里的相对地址补全为绝对地址。"""
        from urllib.parse import urljoin
        out = []
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                out.append(line)
            else:
                out.append(urljoin(base_url, s))
        return "\n".join(out)

    def _is_master(self, text):
        return "#EXT-X-STREAM-INF" in text

    # ------------------------------------------------------------------ #
    # TVBox 必需方法
    # ------------------------------------------------------------------ #
    def getName(self):
        return "电影侠"

    def isVideoFormat(self, url):
        if not url:
            return False
        u = url.lower()
        return any(x in u for x in (".m3u8", ".mp4", ".ts", ".m4s"))

    def manualVideoCheck(self):
        return False

    def homeContent(self, filter=False):
        return {"class": CATEGORIES, "filters": {}}

    def homeVideoContent(self):
        now = time.time()
        if self._home_cache[1] and now - self._home_cache[0] < 1800:
            return self._home_cache[1]
        vlist = self._home_list()
        data = {"list": vlist}
        if vlist:
            self._home_cache = (now, data)
        return data

    def _home_list(self):
        for path in ("/v5/home.capi", "/v5/index.capi", "/home.capi"):
            data = self._api_get(path)
            if not data:
                continue
            lst = self._pick_list(data)
            if lst:
                return [self._vod(v) for v in lst if self._vod(v)]
        return []

    # ------------------------------------------------------------------ #
    def categoryContent(self, tid, pg, filter=False, extend=None):
        tid = str(tid or "")
        pg = str(pg or "1")
        key = "%s|%s" % (tid, pg)
        now = time.time()
        if key in self._cat_cache and now - self._cat_cache[key][0] < 900:
            return self._cat_cache[key][1]

        vlist = []
        for path in ("/v5/vod/list.capi", "/v5/channel/list.capi", "/v5/category.capi"):
            data = self._api_get(path, {"typeId": tid, "page": pg, "size": "20"})
            if not data:
                continue
            lst = self._pick_list(data)
            if lst:
                vlist = [self._vod(v) for v in lst if self._vod(v)]
                break

        result = {
            "list": vlist,
            "page": int(pg) if pg.isdigit() else 1,
            "pagecount": 9999,
            "limit": 20,
            "total": 20 * (int(pg) + 1 if pg.isdigit() else 2),
        }
        if vlist:
            self._cat_cache[key] = (now, result)
        return result

    def searchContent(self, key, quick=False, pg="1"):
        keyword = (key or "").strip()
        if not keyword:
            return {"list": []}

        vlist = []
        for path in ("/v5/vod/search.capi", "/v5/search/query", "/v5/search.capi"):
            data = self._api_get(path, {"keyword": keyword, "key": keyword,
                                        "page": str(pg), "size": "20"})
            if not data:
                continue
            lst = self._pick_list(data)
            if lst:
                vlist = [self._vod(v) for v in lst if self._vod(v)]
                break
        return {"list": vlist}

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vid = str(ids[0] if isinstance(ids, (list, tuple)) else ids).strip()
        if not vid:
            return {"list": []}

        now = time.time()
        if vid in self._detail_cache and now - self._detail_cache[vid][0] < 600:
            return self._detail_cache[vid][1]

        vod = None
        for path in ("/v5/vod/detail.capi", "/v5/vod/info.capi", "/v5/detail.capi"):
            data = self._api_get(path, {"id": vid, "vodId": vid})
            if not data:
                continue
            node = data.get("data") or data.get("result") or data
            if isinstance(node, dict):
                for k in ("vodInfo", "info", "vod", "detail"):
                    if isinstance(node.get(k), dict):
                        node = node[k]
                        break
            if isinstance(node, dict):
                vod = self._vod(node, detail=True)
                if vod:
                    break

        if not vod:
            vod = {
                "vod_id": vid,
                "vod_name": "",
                "vod_pic": "",
                "vod_content": INTRO_PREFIX,
                "vod_play_from": "电影侠",
                "vod_play_url": "正片$%s" % vid,
            }

        content = vod.get("vod_content") or ""
        if not content.startswith(INTRO_PREFIX):
            content = INTRO_PREFIX + (("\n" + content) if content else "")
        vod["vod_content"] = content

        result = {"list": [vod]}
        self._detail_cache[vid] = (now, result)
        return result

    # ------------------------------------------------------------------ #
    def playerContent(self, flag, id, vipFlags):
        vid = str(id or "").strip()
        if not vid:
            return {"parse": 0, "playUrl": "", "url": "", "header": ""}

        header = {"User-Agent": UA, "Referer": PLAY_API + "/"}

        # 1) 直接给的 m3u8
        if vid.startswith("http") and ".m3u8" in vid:
            return {"parse": 1, "playUrl": "", "url": vid, "header": header}

        # 2) CDN 调度：先试 master，再试媒体列表
        master = self._play_master(vid, flag)
        if master and self._is_master(master[0]):
            text, base = master
            text = self._absolutize(text, base)
            # master 的每个子列表也可能是 /api/…，同样补 raw=1
            text = re.sub(r"(/api/m3u8\?[^\"'\s]+?)(?!&raw=1)(?=\s|$)",
                          r"\1&raw=1", text)
            if self._host_playable(text):
                return {"parse": 1, "playUrl": "", "url": self._data_uri(text),
                        "header": header}

        text = self._play_m3u8(vid, flag, raw=True)
        if text:
            text = self._absolutize(text, "%s/api/m3u8" % PLAY_API)
            url = self._serve_playlist(text, vid)
            if url:
                return {"parse": 1, "playUrl": "", "url": url, "header": header}

        # 3) 兜底：中转列表（分片会返回 PNG，仅在不支持 localProxy 时使用）
        text = self._play_m3u8(vid, flag, raw=False)
        if text:
            text = self._absolutize(text, "%s/api/m3u8" % PLAY_API)
            return {"parse": 1, "playUrl": "",
                    "url": self._data_uri(text), "header": header}

        return {"parse": 0, "playUrl": "", "url": "", "header": header}

    def _host_playable(self, text):
        """列表里是否有可直接播放的分片。"""
        return bool(RE_TS.search(text))

    def _data_uri(self, text):
        return "data:application/vnd.apple.mpegurl;base64," + _b64e(text.encode("utf-8"))

    def _serve_playlist(self, text, vid):
        """
        大列表（>150KB）走本地代理，避免 data URI 过长；否则直接 data URI。
        """
        if len(text) < 150 * 1024:
            return self._data_uri(text)
        try:
            base = self.getProxyUrl() or ""
        except Exception:
            base = ""
        if not base:
            return self._data_uri(text)
        # 交给 localProxy 二次处理
        import urllib.parse
        key = "/dyxia/pl.m3u8?d=" + urllib.parse.quote(
            base64.urlsafe_b64encode(text.encode("utf-8")).decode())
        return base.rstrip("/") + key

    # ------------------------------------------------------------------ #
    # 本地代理：仅在需要时使用（大列表 / 需要改写分片）
    # ------------------------------------------------------------------ #
    def localProxy(self, param):
        try:
            d = (param or {}).get("d", "")
            if not d:
                return [404, "text/plain", b"no param"]
            text = base64.urlsafe_b64decode(d.encode()).decode("utf-8")
            return [200, "application/vnd.apple.mpegurl", text.encode("utf-8")]
        except Exception as e:
            return [500, "text/plain", str(e).encode()]

    # ------------------------------------------------------------------ #
    # 数据规整
    # ------------------------------------------------------------------ #
    def _pick_list(self, data):
        """从各种返回结构里找出影片数组。"""
        if not isinstance(data, dict):
            return []
        node = data.get("data") or data.get("result") or data
        for _ in range(4):
            if isinstance(node, list):
                return [x for x in node if isinstance(x, dict)]
            if not isinstance(node, dict):
                return []
            for k in ("list", "items", "records", "vodList", "rows", "data",
                      "vodInfoList", "content"):
                v = node.get(k)
                if isinstance(v, list):
                    return [x for x in v if isinstance(x, dict)]
                if isinstance(v, dict):
                    node = v
                    break
            else:
                return []
        return []

    def _pic(self, v):
        for k in ("vod_pic", "pic", "cover", "img", "vodPic", "poster",
                  "coverUrl", "verticalPic", "horizontalPic", "thumb"):
            val = v.get(k)
            if isinstance(val, str) and val.startswith("http"):
                return val
        return ""

    def _vod(self, v, detail=False):
        if not isinstance(v, dict):
            return None
        vid = None
        for k in ("vod_id", "id", "vodId", "videoId", "uuid"):
            val = v.get(k)
            if val not in (None, "", 0, "0"):
                vid = str(val)
                break
        if not vid:
            return None

        name = ""
        for k in ("vod_name", "name", "title", "vodName", "videoName"):
            val = v.get(k)
            if isinstance(val, str) and val.strip():
                name = val.strip()
                break

        vod = {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": self._pic(v),
            "vod_remarks": str(v.get("vod_remarks") or v.get("remarks")
                               or v.get("remark") or v.get("updateInfo")
                               or v.get("score") or ""),
        }
        if not detail:
            return vod

        # ---- 详情字段 ---- #
        vod["type_name"] = str(v.get("type_name") or v.get("typeName")
                               or v.get("class") or v.get("categoryName") or "")
        vod["vod_year"] = str(v.get("vod_year") or v.get("year") or "")
        vod["vod_area"] = str(v.get("vod_area") or v.get("area") or "")
        vod["vod_lang"] = str(v.get("vod_lang") or v.get("language") or "")

        director = v.get("vod_director") or v.get("director") or ""
        if isinstance(director, list):
            director = ",".join(str(x.get("name", x)) if isinstance(x, dict) else str(x)
                                for x in director)
        actors = v.get("vod_actor") or v.get("actor") or v.get("actors") or ""
        if isinstance(actors, list):
            actors = ",".join(str(x.get("name", x)) if isinstance(x, dict) else str(x)
                              for x in actors)
        vod["vod_director"] = str(director)
        vod["vod_actor"] = str(actors)

        desc = ""
        for k in ("vod_content", "vod_blurb", "content", "desc", "description",
                  "intro", "brief", "vodIntro"):
            val = v.get(k)
            if isinstance(val, str) and val.strip():
                desc = re.sub(r"<[^>]+>", "", val).strip()
                break
        vod["vod_content"] = desc

        # ---- 播放源与剧集 ---- #
        from_name, from_url = self._play_sources(v)
        vod["vod_play_from"] = from_name or "电影侠"
        vod["vod_play_url"] = from_url or ("正片$%s" % vid)
        return vod

    def _play_sources(self, v):
        """
        兼容三种剧集结构：
          A. playUrl 字符串  "第1集$vid1#第2集$vid2"
          B. episodes 数组   [{"name":..,"id":..}]
          C. sources 多线路  [{"flag":..,"episodes":[...]}]
        """
        names, urls = [], []

        # C：多线路
        srcs = v.get("sources") or v.get("playSources") or v.get("playList")
        if isinstance(srcs, list) and srcs and isinstance(srcs[0], dict):
            for s in srcs:
                flag = str(s.get("flag") or s.get("name") or s.get("sourceName")
                           or s.get("siteName") or "线路")
                eps = s.get("episodes") or s.get("epList") or s.get("urls") or s.get("list")
                ep_str = self._episodes_to_str(eps)
                if ep_str:
                    names.append(flag)
                    urls.append(ep_str)
            if names:
                return "#".join(names), "#".join(urls)

        # B：episodes 数组
        for k in ("episodes", "epList", "urls", "playList", "playUrlList"):
            eps = v.get(k)
            if isinstance(eps, list) and eps:
                s = self._episodes_to_str(eps)
                if s:
                    return "电影侠", s

        # A：字符串
        for k in ("playUrl", "vod_play_url", "url", "m3u8"):
            s = v.get(k)
            if isinstance(s, str) and s.strip() and ("$" in s or "#" in s):
                return "电影侠", s.strip()
            if isinstance(s, str) and s.startswith("http"):
                return "电影侠", "正片$" + s.strip()

        return "", ""

    def _episodes_to_str(self, eps):
        out = []
        if isinstance(eps, str):
            return eps
        if not isinstance(eps, list):
            return ""
        for i, e in enumerate(eps):
            if isinstance(e, dict):
                nm = str(e.get("name") or e.get("title") or e.get("epName")
                         or ("第%d集" % (i + 1)))
                pid = e.get("id") or e.get("vid") or e.get("vodId") or e.get("url") or ""
                if pid in (None, ""):
                    continue
                out.append("%s$%s" % (nm, pid))
            elif isinstance(e, str) and e.strip():
                out.append("%s$%s" % ("第%d集" % (i + 1), e.strip()))
        return "#".join(out)

    # ------------------------------------------------------------------ #
    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass
        return None
