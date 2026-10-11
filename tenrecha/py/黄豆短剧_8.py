#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
黄豆短剧 合并加强版
============================
协议层骨架：黄豆短剧.py  (严格 PKCS7 / API重试 / 响应限流 / 播放多候选 / 缓存 / 错误码)
网络层增强：黄豆短剧_7.py (全局 DoH + IP验证 + 回退 / AES双库 / m3u8代理重写 / base64内联)

合并后解决的问题：
  - 固定 IP 硬编码      → 动态 DoH + 多源合并 + TLS 探活 + 回退
  - 无本地代理          → m3u8/key/ts 全代理，自动带 Referer，破防盗链
  - 只依赖 pycryptodome → cryptography 兜底
  - _valid_hls 死代码   → 真正接入 playerContent 探活
  - 无播放缓存          → 带 exp 解析的 access_cache
  - 无重试              → _ApiError 可重试判定 + 指数退避
  - 无大小限制          → 2MB / 512KB 双层限流
"""
import gzip
import hashlib
import hmac
import io
import ipaddress
import json
import os
import re
import socket
import ssl
import threading
import time
import uuid
from base64 import b64encode
from contextlib import contextmanager, nullcontext
from urllib.parse import (parse_qs, parse_qsl, quote, unquote, urlencode,
                          urljoin, urlsplit, urlunsplit, urlparse)

import requests

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider:
        pass


# ============================================================
# DNS 层：全局 DoH + IP 探活 + 回退
# ============================================================
_DOH_SERVERS = (
    "https://doh.pub/dns-query?name=%s&type=A",
    "https://dns.alidns.com/resolve?name=%s&type=A",
    "https://dns.google/resolve?name=%s&type=A",
    "https://cloudflare-dns.com/dns-query?name=%s&type=A",
)
_DOH_HOSTS = {"doh.pub", "dns.alidns.com", "dns.google", "cloudflare-dns.com"}
# 站点硬编码兜底 IP（可用 ext.fallback 覆盖）
_FALLBACK_IPS = {
    "xqjzvcvt.top": ("91.110.232.197", "91.110.232.206"),
    "lzlukvca.cc": "104.21.12.21",
}
_IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_doh_cache = {}
_orig_getaddrinfo = socket.getaddrinfo
_DNS_LOCK = threading.RLock()


def _verify_ip(host, ip, port=443, timeout=6):
    """TLS 握手 + HTTP 探测，确认这个 IP 真能承载该域名（不做证书校验，只验可达）"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((ip, port))
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ss = ctx.wrap_socket(s, server_hostname=host)
        ss.settimeout(timeout)
        ss.sendall(
            b"GET / HTTP/1.1\r\nHost: " + host.encode() +
            b"\r\nConnection: close\r\nUser-Agent: Mozilla/5.0\r\n\r\n"
        )
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = ss.recv(512)
            if not chunk:
                break
            head += chunk
        ss.close()
        return head.startswith(b"HTTP/")
    except Exception:
        return False


def _doh_resolve(host, port=443):
    """多源合并解析：4个DoH + 系统DNS + 硬编码回退，逐个探活后缓存"""
    if host in _doh_cache:
        return _doh_cache[host]
    cands = []

    # ① 多个 DoH 服务器
    for srv in _DOH_SERVERS:
        try:
            r = requests.get(
                srv % host,
                headers={"Accept": "application/dns-json"},
                timeout=5, verify=False,
            )
            for a in r.json().get("Answer", []):
                if a.get("type") == 1 and _IP_RE.match(a.get("data", "")):
                    cands.append(a["data"])
        except Exception:
            continue

    # ② 系统 DNS 兜底
    try:
        for r in _orig_getaddrinfo(host, port):
            if r[0] == socket.AF_INET and _IP_RE.match(r[4][0]):
                cands.append(r[4][0])
    except Exception:
        pass

    # ③ 硬编码回退 IP
    fb = _FALLBACK_IPS.get(host, "")
    if isinstance(fb, (list, tuple)):
        cands.extend(fb)
    elif fb:
        cands.append(fb)

    # 去重后逐个探活
    seen = []
    for c in cands:
        if c not in seen:
            seen.append(c)
    for c in seen:
        if _verify_ip(host, c, port):
            _doh_cache[host] = c
            return c
    return ""


def _pinned_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    """全局挂载：非 DoH 服务器的域名走探活解析"""
    if isinstance(host, str) and host not in _DOH_HOSTS:
        with _DNS_LOCK:
            pnum = int(port) if isinstance(port, int) else 443
            ip = _doh_resolve(host, pnum)
            if ip:
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    return _orig_getaddrinfo(host, port, family, type, proto, flags)


# 安装全局 DNS 补丁（仅一次）
if socket.getaddrinfo is not _pinned_getaddrinfo:
    socket.getaddrinfo = _pinned_getaddrinfo


# ============================================================
# AES：双库兜底（pycryptodome → cryptography）
# ============================================================
class _AESCBC:
    @staticmethod
    def encrypt(data, key, iv):
        try:
            from Crypto.Cipher import AES
            return AES.new(key, AES.MODE_CBC, iv).encrypt(_AESCBC.pad(data))
        except Exception:
            from cryptography.hazmat.backends import default_backend
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            enc = Cipher(algorithms.AES(key), modes.CBC(iv),
                         backend=default_backend()).encryptor()
            return enc.update(_AESCBC.pad(data)) + enc.finalize()

    @staticmethod
    def decrypt(data, key, iv):
        try:
            from Crypto.Cipher import AES
            plain = AES.new(key, AES.MODE_CBC, iv).decrypt(data)
        except Exception:
            from cryptography.hazmat.backends import default_backend
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            dec = Cipher(algorithms.AES(key), modes.CBC(iv),
                         backend=default_backend()).decryptor()
            plain = dec.update(data) + dec.finalize()
        return _AESCBC.unpad(plain)

    @staticmethod
    def pad(data):
        n = 16 - len(data) % 16
        return data + bytes([n]) * n

    @staticmethod
    def unpad(data):
        """严格 PKCS7 校验：坏数据直接抛错，避免错位静默"""
        if not data:
            raise ValueError("empty PKCS7 payload")
        n = data[-1]
        if n < 1 or n > 16 or data[-n:] != bytes([n]) * n:
            raise ValueError("invalid PKCS7 padding")
        return data[:-n]


# ============================================================
# 错误体系
# ============================================================
class _ApiError(Exception):
    def __init__(self, code, retryable=False, detail=""):
        super().__init__(code)
        self.code = str(code)
        self.retryable = bool(retryable)
        self.detail = str(detail or "")


# ============================================================
# 主 Spider
# ============================================================
class Spider(BaseSpider):
    # ---------- 构造 ----------
    def __init__(self):
        self.host = "https://xqjzvcvt.top"
        self.api = self.host + "/api"
        self.name = "黄豆短剧"
        self.platform_key = "7961beb44246e3012ce228d6b5ced05a"
        self.version = "2.0.0"
        self.device_type = "web"
        self.session_id = uuid.uuid4().hex
        self.device_id = self.session_id
        self.token = ""

        ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        self.headers = {
            "User-Agent": ua,
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": self.host,
            "Referer": self.host + "/home",
            "Content-Type": "application/octet-stream",
        }
        self.media_header = {
            "User-Agent": ua,
            "Referer": self.host + "/home",
            "Origin": self.host,
        }

        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update(self.headers)

        # 缓存
        self.class_cache = None
        self.filter_cache = {}
        self.access_cache = {}
        self.last_error = ""
        self.last_hls_error = ""

        # 限流
        self.max_response_bytes = 2 * 1024 * 1024
        self.max_playlist_bytes = 512 * 1024
        self.api_attempts = 2

        # 本地代理开关（默认开，播放走代理重写破防盗链）
        self.proxy_play = True
        # 是否用 base64 内联 m3u8（部分壳更稳，默认关）
        self.inline_m3u8 = False

    # ---------- 初始化 ----------
    def init(self, extend=""):
        cfg = self._config(extend)

        candidate = str(cfg.get("site") or cfg.get("base_url") or self.host).strip().rstrip("/")
        parsed = urlsplit(candidate)
        if (parsed.scheme in ("http", "https") and parsed.netloc
                and not parsed.username and not parsed.query and not parsed.fragment):
            if parsed.path.rstrip("/").endswith("/api"):
                candidate = candidate[:-4].rstrip("/")
            self.host = candidate
            self.api = self.host + "/api"

        for key in ("token", "access_token", "accessToken", "auth_token"):
            if cfg.get(key) is not None:
                self.token = str(cfg.get(key) or "").strip()
                break

        device_id = cfg.get("deviceId") or cfg.get("device_id") or cfg.get("device")
        session_id = cfg.get("sessionId") or cfg.get("session_id") or cfg.get("session")
        if device_id:
            self.device_id = str(device_id).strip()
        if session_id:
            self.session_id = str(session_id).strip()

        # 代理开关
        if cfg.get("proxy_play") is not None:
            self.proxy_play = str(cfg.get("proxy_play")).strip().lower() in ("1", "on", "true", "yes")
        if cfg.get("inline_m3u8") is not None:
            self.inline_m3u8 = str(cfg.get("inline_m3u8")).strip().lower() in ("1", "on", "true", "yes")

        # fallback IP 覆盖
        fb = cfg.get("fallback")
        if isinstance(fb, dict):
            _FALLBACK_IPS.update({str(k): str(v) for k, v in fb.items()})
            _doh_cache.clear()

        self.headers["Origin"] = self.host
        self.headers["Referer"] = self.host + "/home"
        self.session.headers.update(self.headers)
        self.media_header["Referer"] = self.host + "/home"
        self.media_header["Origin"] = self.host

        # 复位缓存
        self.class_cache = None
        self.filter_cache = {}
        self.access_cache = {}
        self.last_error = ""
        self.last_hls_error = ""

    def getName(self):
        return self.name

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass

    # ============================================================
    # 内容接口
    # ============================================================
    def homeContent(self, filter):
        data = self._api("/drama/list", {"page": "1", "page_size": "18"})
        classes = self._classes()
        return {
            "class": classes,
            "filters": self._filters(classes),
            "list": [self._vod(x) for x in self._list(data)],
            "parse": 0, "jx": 0,
        }

    def categoryContent(self, tid, pg, filter, extend):
        extend = self._dict(extend)
        tid = str(tid or "all")
        pg = max(1, self._int(pg, 1))

        if tid == "yuandou":
            data = self._api("/drama/navBlock",
                             {"code": "yuandou", "tab": "recommend", "page": str(pg)})
            items = self._nav_items(data)
        else:
            req = {"page": str(pg), "page_size": "18"}
            if tid and tid not in ("all", "recommend"):
                tabs = self._nav_filter(tid)
                idx = self._int(extend.get("sub"), 0)
                sub = tabs[idx] if tabs and 0 <= idx < len(tabs) else {}
                flt = sub.get("filter", {}) if isinstance(sub, dict) else {}
                req["cat_id"] = flt.get("cat_id", "")
                if flt.get("tag_id"):
                    req["tag_id"] = flt.get("tag_id", "")
                req["order"] = flt.get("order", "") or extend.get("order", "")
            elif extend.get("order"):
                req["order"] = extend.get("order")
            if extend.get("update_status"):
                req["update_status"] = extend.get("update_status")
            data = self._api("/drama/list", req)
            items = self._list(data)

        return {
            "page": int(pg),
            "pagecount": int(pg) if len(items) < 18 else int(pg) + 1,
            "limit": 18, "total": 99999,
            "list": [self._vod(x) for x in items],
            "parse": 0, "jx": 0,
        }

    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        vid = self._sid(raw_id)
        obj = self._api("/drama/detail", {"id": vid})
        data = obj.get("data", obj) if isinstance(obj, dict) else {}
        if not isinstance(data, dict):
            return {"list": []}
        data = self._unlock(data)
        vod_id = self._sid(data.get("id") or data.get("drama_id") or vid)
        name = data.get("name") or data.get("title") or data.get("t") or vod_id
        eps = data.get("episodes") if isinstance(data.get("episodes"), list) else []
        count = self._int(data.get("episode_count") or data.get("free_episodes"),
                          len(eps) or 1)
        play = []
        if eps:
            for i, ep in enumerate(eps, 1):
                seq = ep.get("seq") or ep.get("episode") or ep.get("ep") or i
                play.append("%s$%s|%s" % (
                    ep.get("name") or ep.get("title") or "第%s集" % seq, vod_id, seq))
        else:
            play = ["第%s集$%s|%s" % (i, vod_id, i) for i in range(1, count + 1)]
        vod = {
            "vod_id": vod_id,
            "vod_name": name,
            "vod_pic": self._pic(data),
            "type_name": data.get("category") or data.get("type") or "",
            "vod_year": "", "vod_area": "",
            "vod_remarks": data.get("update_label") or "全%s集" % count,
            "vod_actor": "", "vod_director": "",
            "vod_content": data.get("description") or data.get("summary") or name,
            "vod_play_from": self.name,
            "vod_play_url": "#".join(play),
        }
        return {"list": [vod], "parse": 0, "jx": 0}

    def searchContent(self, key, quick, pg="1"):
        data = self._api("/drama/list",
                         {"page": str(pg), "page_size": "18", "keywords": str(key)})
        items = self._list(data)
        return {
            "page": int(pg),
            "pagecount": int(pg) if len(items) < 18 else int(pg) + 1,
            "limit": 18, "total": 99999,
            "list": [self._vod(x) for x in items],
            "parse": 0, "jx": 0,
        }

    # ============================================================
    # 播放
    # ============================================================
    def playerContent(self, flag, id, vipFlags):
        s = str(id)

        # 已是内部代理/本地 URL：解析出真实 URL 或内部 id
        if (s.startswith("proxy?") or s.startswith("/proxy?")
                or s.startswith("local://") or s.startswith("/local/")
                or s.startswith("http://127.0.0.1")):
            p = self._param(s)
            inner = unquote(p.get("url", ""))
            if inner.startswith("http://") or inner.startswith("https://"):
                return self._player(inner)
            vid, seq = self._split(inner)
        else:
            vid, seq = self._split(s)

        if not vid:
            return self._player_error("empty_vid")

        cache_key = "%s|%s" % (vid, seq)
        cached = self.access_cache.get(cache_key)
        now = time.time()
        if isinstance(cached, dict) and cached.get("expires", 0) > now:
            if cached.get("url"):
                return self._player(cached.get("url"))

        obj = self._api("/drama/play", {"id": vid, "seq": str(seq)}, True)
        signed = self._play_candidates(obj)
        candidates = signed + self._legacy_hls_candidates(vid, seq, signed)

        # 去重
        ordered, seen = [], set()
        for url in candidates:
            if url in seen:
                continue
            seen.add(url)
            ordered.append(url)

        if not ordered:
            error = self._play_error(obj)
            self.last_error = error
            return self._player_error(error)

        # 优先选可探活的线路
        chosen = ""
        for url in ordered:
            if self._valid_hls(url):
                chosen = url
                break
        if not chosen:
            chosen = ordered[0]

        self.access_cache[cache_key] = {
            "url": chosen,
            "expires": self._url_expiry(chosen),
        }
        self.last_error = "" if signed else self._play_error(obj)
        return self._player(chosen)

    def localProxy(self, param):
        p = self._param(param)
        if p.get("do") != "py":
            return None
        typ = p.get("type", "")
        u = unquote(p.get("url", ""))
        if not u:
            return None

        if typ == "m3u8":
            if not (u.startswith("http://") or u.startswith("https://")):
                vid, seq = self._split(u)
                obj = self._api("/drama/play", {"id": vid, "seq": str(seq)}, True)
                data = obj.get("data", {}) if isinstance(obj, dict) else {}
                u = data.get("m3u8") or data.get("url") or self._hls(vid, seq)
            return [["Content-Type: application/vnd.apple.mpegurl"], self._proxy_m3u8(u)]
        if typ == "key":
            try:
                body = self._media_get(u).content
            except Exception:
                body = b""
            return [["Content-Type: application/octet-stream"], body]
        if typ == "ts":
            try:
                body = self._media_get(u).content
            except Exception:
                body = b""
            return [["Content-Type: video/mp2t"], body]
        return None

    # ============================================================
    # 播放辅助
    # ============================================================
    def _player(self, url):
        """统一出口：默认走本地代理重写，破防盗链"""
        if not url:
            return self._player_error("empty_url")
        if self.proxy_play:
            return {
                "parse": 0, "playUrl": "",
                "url": self._proxy_url("m3u8", url),
                "jx": 0,
                "header": json.dumps(self.media_header),
            }
        return {
            "parse": 0, "playUrl": "", "url": url, "jx": 0,
            "header": self.media_header,
        }

    def _player_error(self, error):
        return {
            "parse": 0, "playUrl": "", "url": "", "jx": 0,
            "header": self.media_header,
            "msg": str(error or "播放线路不可用"),
        }

    def _proxy_url(self, typ, url):
        return "proxy?do=py&type=%s&url=%s" % (typ, quote(url, safe=""))

    def _proxy_m3u8(self, url):
        try:
            text = self._media_get(url).content.decode("utf-8", "ignore")
        except Exception:
            return b"#EXTM3U\n"
        out = []
        for ln in text.splitlines():
            s = ln.strip()
            if not s:
                out.append(ln)
                continue
            if s.startswith("#"):
                if s.startswith("#EXT-X-KEY:"):
                    m = re.search(r'URI="([^"]+)"', s)
                    if m:
                        s = s.replace(m.group(1),
                                      self._proxy_url("key", urljoin(url, m.group(1))))
                out.append(s)
                continue
            u = urljoin(url, s)
            typ = "m3u8" if (u.endswith(".m3u8") or "playlist" in u.lower()) else "ts"
            out.append(self._proxy_url(typ, u))
        return "\n".join(out).encode("utf-8")

    def _media_get(self, url):
        last = None
        for _ in range(3):
            try:
                r = self.session.get(url, headers=self.media_header,
                                     timeout=15, verify=False)
                r.raise_for_status()
                return r
            except Exception as e:
                last = e
                h = urlparse(url).hostname
                if h:
                    _doh_cache.pop(h, None)  # 清 DNS 缓存，下轮重新解析
                time.sleep(0.5)
        raise last

    def _param(self, param):
        if isinstance(param, dict):
            return param
        s = str(param)
        for pre in ("/proxy?", "/local/", "proxy?", "local://", "/proxy", "proxy", "local"):
            if s.startswith(pre):
                s = s[len(pre):]
                break
        if s.startswith("?"):
            s = s[1:]
        if "?" in s:
            s = s.split("?", 1)[-1]
        try:
            j = json.loads(s)
            if isinstance(j, dict):
                return {str(k): str(v) for k, v in j.items()}
        except Exception:
            pass
        return {k: v for k, v in parse_qsl(s)}

    # ============================================================
    # API 层
    # ============================================================
    def _api(self, path, data=None, silent=False):
        path = "/" + path.lstrip("/")
        last_error = None
        for attempt in range(self.api_attempts):
            rid = str(uuid.uuid4())
            key = self._key(rid)
            iv = os.urandom(16)
            raw = json.dumps(
                {"token": self.token or "", "deviceId": self.device_id,
                 "data": data or {}},
                ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8")
            body = iv + _AESCBC.encrypt(gzip.compress(raw), key, iv)
            ts = int(time.time())
            sign = hashlib.sha256(
                ("Dart|%s|%s|%s|%s" % (self.session_id, rid, ts, path)).encode("utf-8")
            ).hexdigest() + "-" + str(ts)
            h = dict(self.headers)
            h.update({
                "version": self.version, "deviceType": self.device_type,
                "time": str(ts), "sign": sign, "requestId": rid,
                "sessionId": self.session_id,
                "deviceBrand": "", "deviceModel": "",
                "systemName": "", "systemVersion": "",
            })
            try:
                with self.session.post(self.api + path, data=body, headers=h,
                                       timeout=(8, 25), stream=True) as response:
                    status = response.status_code
                    if status in (408, 425, 429) or 500 <= status <= 599:
                        raise _ApiError("http_%s" % status, True)
                    if status < 200 or status >= 300:
                        raise _ApiError("http_%s" % status)
                    obj = self._decode(self._read_limited(response, self.max_response_bytes), rid)
                if not isinstance(obj, dict):
                    raise _ApiError("invalid_api_object", True)
                if not self._api_ok(obj):
                    code, detail = self._api_failure(obj)
                    self.last_error = "%s:%s" % (code, detail) if detail else code
                    return obj if silent else {}
                self.last_error = ""
                return obj
            except _ApiError as exc:
                last_error = exc
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = _ApiError(type(exc).__name__, True)
            except requests.RequestException as exc:
                last_error = _ApiError(type(exc).__name__)
            except (ValueError, TypeError, OSError, EOFError) as exc:
                last_error = _ApiError(type(exc).__name__, True)

            if attempt + 1 < self.api_attempts and last_error.retryable:
                time.sleep(0.25 * (attempt + 1))
                continue
            break

        self.last_error = last_error.code if last_error else "api_request_failed"
        return {}

    def _key(self, rid):
        return hmac.new(
            self.platform_key.encode("utf-8"),
            bytes.fromhex(str(rid).replace("-", "")),
            hashlib.sha256,
        ).digest()

    def _decode(self, blob, rid):
        if not blob or len(blob) < 32 or (len(blob) - 16) % 16 != 0:
            if not blob:
                raise ValueError("empty response")
            # 明文兜底
            return json.loads(blob.decode("utf-8"))
        try:
            plain = _AESCBC.decrypt(blob[16:], self._key(rid), blob[:16])
            if plain[:2] == b"\x1f\x8b":
                with gzip.GzipFile(fileobj=io.BytesIO(plain)) as zipped:
                    plain = zipped.read(self.max_response_bytes + 1)
                if len(plain) > self.max_response_bytes:
                    raise ValueError("decoded response too large")
            return json.loads(plain.decode("utf-8"))
        except Exception:
            # 解密失败尝试直接解析（有些错误响应是明文）
            try:
                return json.loads(blob.decode("utf-8"))
            except Exception:
                raise

    def _read_limited(self, response, limit):
        declared = self._int(response.headers.get("Content-Length"), 0)
        if declared > limit:
            raise _ApiError("response_too_large")
        chunks = []
        size = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            size += len(chunk)
            if size > limit:
                raise _ApiError("response_too_large")
            chunks.append(chunk)
        return b"".join(chunks)

    def _api_ok(self, obj):
        if not isinstance(obj, dict) or not obj:
            return False
        status = str(obj.get("status") or "").strip().lower()
        return not status or status in ("y", "yes", "ok", "success", "1", "true")

    def _api_failure(self, obj):
        code = str(obj.get("errorCode") or obj.get("code") or obj.get("status") or "api_rejected")
        detail = obj.get("error") or obj.get("message") or obj.get("msg") or ""
        return code, str(detail or "")

    # ============================================================
    # 播放线路解析
    # ============================================================
    def _play_candidates(self, obj):
        data = obj.get("data", obj) if isinstance(obj, dict) else {}
        if not isinstance(data, dict):
            return []
        result = []

        def add(value):
            value = str(value or "").strip()
            if not value:
                return
            value = urljoin(self.host + "/", value)
            if self._http_url(value) and value not in result:
                result.append(value)

        for key in ("m3u8", "url", "play_url", "playUrl"):
            add(data.get(key))
        lines = data.get("lines") if isinstance(data.get("lines"), list) else []
        for line in lines:
            if not isinstance(line, dict):
                continue
            for key in ("m3u8", "url", "play_url", "playUrl"):
                add(line.get(key))
        return result

    def _legacy_hls_candidates(self, vid, seq, signed_candidates):
        result = []
        expected = urlsplit(self._hls(vid, seq))

        def add(value):
            if self._http_url(value) and value not in result:
                result.append(value)

        for value in signed_candidates:
            try:
                parsed = urlsplit(value)
                if parsed.netloc != expected.netloc or parsed.path != expected.path:
                    continue
                for line in parse_qs(parsed.query).get("line") or []:
                    query = urlencode({"line": str(line)})
                    add(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, "")))
            except (TypeError, ValueError):
                continue
        add(self._hls(vid, seq))
        return result

    def _valid_hls(self, url):
        """真正探活：拉一小段 m3u8，确认 #EXTM3U 开头"""
        if not self._http_url(url):
            self.last_hls_error = "invalid_url"
            return False
        headers = dict(self.media_header)
        headers["Range"] = "bytes=0-%s" % (self.max_playlist_bytes - 1)
        headers["Content-Type"] = None
        for attempt in range(2):
            try:
                with self.session.get(url, headers=headers,
                                      timeout=(8, 20), stream=True) as response:
                    status = response.status_code
                    if status in (408, 425, 429) or 500 <= status <= 599:
                        raise _ApiError("hls_http_%s" % status, True)
                    if status not in (200, 206):
                        self.last_hls_error = "hls_http_%s" % status
                        return False
                    body = self._read_limited(response, self.max_playlist_bytes)
                if body.lstrip(b"\xef\xbb\xbf\x00\t\r\n ").startswith(b"#EXTM3U"):
                    self.last_hls_error = ""
                    return True
                self.last_hls_error = "invalid_hls_body"
                return False
            except _ApiError as exc:
                retryable = exc.retryable
                self.last_hls_error = exc.code
            except (requests.Timeout, requests.ConnectionError):
                retryable = True
                self.last_hls_error = "hls_connection_error"
            except (requests.RequestException, ValueError, TypeError, OSError):
                retryable = False
                self.last_hls_error = "hls_request_error"
            if attempt == 0 and retryable:
                time.sleep(0.2)
                continue
            break
        return False

    def _http_url(self, url):
        try:
            parsed = urlsplit(str(url or ""))
            return (parsed.scheme in ("http", "https")
                    and bool(parsed.netloc)
                    and not parsed.username)
        except (TypeError, ValueError):
            return False

    def _url_expiry(self, url):
        now = int(time.time())
        try:
            values = parse_qs(urlsplit(url).query).get("exp") or []
            expiry = int(values[0]) if values else 0
            if expiry > now + 15:
                return min(expiry - 10, now + 300)
        except (TypeError, ValueError, IndexError):
            pass
        return now + 60

    def _play_error(self, obj):
        if isinstance(obj, dict) and not self._api_ok(obj):
            code, detail = self._api_failure(obj)
            if code == "813005":
                return "服务端未接受当前授权上下文（813005：%s）" % (detail or "授权未生效")
            return "播放接口拒绝请求（%s%s）" % (code, "：" + detail if detail else "")
        return "播放接口未返回可验证的签名 HLS 线路"

    # ============================================================
    # 分类 / 列表
    # ============================================================
    def _classes(self):
        if self.class_cache:
            return self.class_cache
        arr = [{"type_id": "all", "type_name": "全部短剧"}]
        data = self._api("/drama/navList", {})
        for item in self._list(data.get("data", data) if isinstance(data, dict) else data):
            tid = str(item.get("code") or item.get("id") or item.get("cat_id") or "")
            name = item.get("name") or item.get("title") or tid
            if tid and name:
                arr.append({"type_id": tid, "type_name": name})
        self.class_cache = arr
        return arr

    def _filters(self, classes):
        common = [
            {"key": "order", "name": "排序",
             "value": [{"n": "默认", "v": ""}, {"n": "最新", "v": "new"}, {"n": "最热", "v": "hot"}]},
            {"key": "update_status", "name": "状态",
             "value": [{"n": "全部", "v": ""}, {"n": "连载", "v": "0"}, {"n": "完结", "v": "1"}]},
        ]
        fs = {}
        for c in classes:
            tid = c["type_id"]
            tabs = self._nav_filter(tid) if tid not in ("all", "yuandou") else []
            fs[tid] = ([{"key": "sub", "name": "子分类",
                         "value": [{"n": t.get("name", "默认"), "v": str(i)}
                                   for i, t in enumerate(tabs)]}] if tabs else []) + common
        return fs

    def _nav_filter(self, code):
        if code not in self.filter_cache:
            data = self._api("/drama/navFilter", {"code": str(code)})
            self.filter_cache[code] = self._list(
                data.get("data", data) if isinstance(data, dict) else data)
        return self.filter_cache.get(code, [])

    def _list(self, data):
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return []
        if isinstance(data.get("list"), list):
            return data["list"]
        if isinstance(data.get("items"), list):
            return data["items"]
        if isinstance(data.get("data"), list):
            return data["data"]
        if isinstance(data.get("data"), dict):
            return self._list(data["data"])
        return []

    def _nav_items(self, data):
        blocks = self._list(data.get("data", data) if isinstance(data, dict) else data)
        items = []
        for b in blocks:
            if isinstance(b, dict) and isinstance(b.get("items"), list):
                items += b.get("items")
            elif isinstance(b, dict) and (b.get("id") or b.get("drama_id")):
                items.append(b)
        return items

    def _vod(self, item):
        item = item or {}
        vid = self._sid(item.get("id") or item.get("drama_id") or "")
        remarks = (item.get("update_label") or item.get("corner")
                   or ("全%s集" % item.get("episode_count") if item.get("episode_count") else ""))
        return {
            "vod_id": vid,
            "vod_name": item.get("name") or item.get("title") or item.get("t") or vid,
            "vod_pic": self._pic(item),
            "vod_remarks": remarks,
        }

    def _pic(self, item):
        value = (item.get("img_y") or item.get("img_x") or item.get("img")
                 or item.get("cover") or item.get("pic") or "")
        if not value:
            return ""
        value = str(value)
        if value.startswith("//"):
            return "https:" + value
        if value.startswith("http"):
            return value
        return urljoin(self.host + "/", value)

    def _unlock(self, d):
        eps = d.get("episodes")
        if isinstance(eps, list):
            for ep in eps:
                if isinstance(ep, dict):
                    ep["is_buy"] = True
                    ep["type"] = "free"
                    ep["price"] = 0
                    ep["methods"] = []
        d.update({
            "pay_type": "free", "money": 0,
            "episode_price": 0, "points_price": 0,
            "can_vip_watch": True, "is_buy_whole": True,
            "vip_episodes": [], "coin_episodes": [], "points_episodes": [],
        })
        return d

    # ============================================================
    # 工具
    # ============================================================
    def _config(self, value):
        cfg = self._dict(value)
        for key in ("ext", "data", "config", "auth", "credential", "credentials"):
            inner = self._dict(cfg.get(key))
            if not inner:
                continue
            merged = dict(inner)
            for name, item in cfg.items():
                if name != key:
                    merged[name] = item
            cfg = merged
        return cfg

    def _dict(self, value):
        if isinstance(value, dict):
            return dict(value)
        if not isinstance(value, str) or not value.strip():
            return {}
        try:
            obj = json.loads(value)
            return dict(obj) if isinstance(obj, dict) else {}
        except (TypeError, ValueError):
            return {}

    def _sid(self, x):
        value = str(x or "")
        return value[3:] if value.startswith("rp_") else value

    def _split(self, x):
        p = str(x).split("|", 1)
        seq = max(1, self._int(p[1], 1)) if len(p) > 1 else 1
        return self._sid(p[0]), str(seq)

    def _hls(self, vid, seq):
        return "%s/api/drama/hls/%s/%s/play.m3u8?line=free" % (
            self.host, self._sid(vid), seq)

    def _int(self, x, d=0):
        try:
            return int(x)
        except Exception:
            return d