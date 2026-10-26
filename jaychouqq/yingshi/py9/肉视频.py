# -*- coding: utf-8 -*-
"""
肉视频 TVBox Python 爬虫 v5（21 条线路 + 缓存首页 + 更新线路 + 综合测速）
按《TVBox 高阶爬虫全维度技能树》开发，探针已验证：
- SSR 直连；/v 全部视频(56,253)；/t/{名} 标签与分类列表(每页26条，order 分页)
- /series 剧集库(?tag= 与 ?sort=updated|hot|likes|most、?page= 均实测有效)
- /cat 一页拿全：COLLECTION 主分类、题材/属性标签云、按分类分组的片商手风琴
- 详情 JSON-LD + #标签 + 信息行(观看/发布/时长)；相关推荐为横排小卡/剧集卡
- 播放链：ev.d/k 移位解密 -> /api/hls/{id} -> 302 -> 签名 m3u8（单码率，无多分辨率）
- 规范：字典直通车、__init__+init return True、全局 SSL 免疫、双层过滤面板
"""
import base64
import gzip
import html as htmlmod
import json
import re
import ssl
import time
import urllib.parse
import urllib.request

try:
    from concurrent.futures import ThreadPoolExecutor
    _HAS_THREADS = True
except Exception:
    _HAS_THREADS = False

from base.spider import Spider

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 全局 SSL 免疫（命门 3）
_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE
_opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ctx))

# 线路池：站内优选访问 21 条（2026-10-24 浏览器逐条验证，均可打开），
# 编号沿用站内顺序；“更新线路”动作会用导航站最新表全量替换它
POOL_21 = ["https://rou07.net", "https://rou07.com", "https://rou06.net",
           "https://rou06.cc", "https://rou888.net", "https://rou1.my",
           "https://rou666.cc", "https://rou666.net", "https://rou666.com",
           "https://rou01.cc", "https://rou168.com", "https://rou1.pw",
           "https://rouav.sbs", "https://rou1.mom", "https://rou1.art",
           "https://rouxxx.net", "https://rou1.sbs", "https://rouxxx.sbs",
           "https://rouxxx.cc", "https://rou163.top", "https://rou1.men"]
HOSTS = list(POOL_21)
# 导航站（X99 资源导航）：更新线路时按顺序嗅探其服务端渲染页
NAV_URLS = ["https://9527.men/", "https://x99dh.net/", "https://x99dh.lat/",
            "https://x99dh.cc/"]
# 综合测速用固定测试视频（解析 + 首分片耗时；被删时自动改用该线首页首卡）
TEST_VIDEO_ID = "cmvkdaogp0000s65s4ypxzx8e"
FILTER_TTL = 24 * 3600      # 筛选数据缓存有效期
AUTO_TTL = 24 * 3600        # 综合测速优选结果有效期
LINE_HOSTS = {"line1": "https://rou07.net",
              "line2": "https://rou1.art",
              "line3": "https://rou666.com",
              # 旧代号兼容（壳子缓存的旧筛选值仍可解析）
              "rou07": "https://rou07.net",
              "rou1": "https://rou1.art",
              "rou666": "https://rou666.com"}
# 壳子传来的线路值可能是代号也可能是旧面板标签，做双向映射
LINE_LABELS = {"更新线路": "line1", "备用节点": "line2", "全部": ""}
FALLBACK_CLASSES = ["自拍流出", "國產AV", "探花", "日本", "麻豆傳媒", "OnlyFans"]
FALLBACK_THEME_TAGS = ["AI短劇", "中文字幕", "單體作品", "現代", "都市", "熟女",
                       "人妻", "絲襪", "後宮", "亂倫", "綠帽"]
FALLBACK_SERIES_TAGS = ["AI短劇", "現代", "都市", "熟女", "大男主", "後宮",
                        "亂倫", "綠帽"]
SORT_VALUES = [{"n": "全部", "v": ""},
               {"n": "最新发布", "v": "createdAt"},
               {"n": "最多点赞", "v": "likeCount"},
               {"n": "最多播放", "v": "viewCount"}]
SERIES_SORT_VALUES = [{"n": "最新更新", "v": ""},
                      {"n": "最热门", "v": "hot"},
                      {"n": "集数最多", "v": "most"}]
# 线路筛选现由 _line_options() 按当前池动态生成（全部 + 线路1..N +
# 更新线路 + 综合测速），不再用静态表


def _fetch(url, timeout=18, referer=""):
    headers = {"User-Agent": UA, "Accept-Encoding": "gzip",
               "Accept-Language": "zh-TW,zh;q=0.9"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with _opener.open(req, timeout=timeout) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return r.geturl(), raw.decode("utf-8", "ignore")


def _clean(text):
    text = re.sub(r"<!--.*?-->", "", text or "", flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    return htmlmod.unescape(text).strip()


def _remarks(block, kind):
    """封面备注自适应：视频=画质+时长，剧集=全X集，均控制在 10 字符内"""
    if kind == "s":
        m = re.search(r"全\s*(\d+)\s*集", block)
        if m:
            return ("全%s集" % m.group(1))[:10]
        if "已完結" in block:
            return "已完结"
        if "本週更新" in block:
            return "本周更新"
        return "劇集"
    q = re.search(r">(\d+)<!--\s*-->P<", block)
    quality = (q.group(1) + "P") if q else ""
    dur = ""
    m = re.search(r"(\d+)分(\d+)秒", block)
    if m:
        dur = "%d:%02d" % (int(m.group(1)), int(m.group(2)))
    else:
        m = re.search(r"(\d+)秒", block)
        if m:
            dur = "0:%02d" % int(m.group(1))
    if dur:
        return ((quality + " " + dur).strip() if quality else dur)[:10]
    m = re.search(r"([\d.]+)\s*萬次", block)
    return (m.group(1) + "萬次觀看")[:10] if m else quality


def _parse_cards(html, want=("v", "s")):
    """列表卡片解析：<a href="/v|/s/{id}" class="group block...">...</a>"""
    out, seen = [], set()
    pat = r'<a href="/(%s)/([a-z0-9]+)" class="group block[^"]*">(.*?)</a>' % "|".join(want)
    for kind, vid, block in re.findall(pat, html, re.S):
        if vid in seen:
            continue
        seen.add(vid)
        imgs = re.findall(r'<img src="([^"]+)"', block)
        tm = re.search(r"<h3[^>]*>(.*?)</h3>", block, re.S)
        name = _clean(tm.group(1)) if tm else ""
        if not name:
            am = re.search(r'<img[^>]+alt="([^"]+)"', block)
            name = htmlmod.unescape(am.group(1)).strip() if am else vid
        card = {
            "vod_id": ("s:" + vid) if kind == "s" else vid,
            "vod_name": name,
            "vod_pic": imgs[-1] if imgs else "",
            "vod_remarks": _remarks(block, kind),
        }
        if kind == "s":  # 剧集卡自带集数与观看数，供页内排序（_ 前缀键输出前剥离）
            em = re.search(r"全\s*(\d+)\s*集", block)
            card["_eps"] = int(em.group(1)) if em else 0
            vm = re.search(r"([\d.]+)\s*萬次觀看", _clean(block))
            card["_views"] = float(vm.group(1)) if vm else 0.0
        out.append(card)
    return out


def _pub(cards):
    """剥离内部排序键，只输出标准字段"""
    return [{k: v for k, v in c.items() if not k.startswith("_")}
            for c in cards]


def _parse_list_rows(html):
    """横排小卡（详情页相关推荐形态）：<a class="group grid ...">"""
    out, seen = [], set()
    pat = r'<a href="/v/([a-z0-9]+)" class="group grid[^"]*">(.*?)</a>'
    for vid, block in re.findall(pat, html, re.S):
        if vid in seen:
            continue
        seen.add(vid)
        tm = re.search(r"<h3[^>]*>(.*?)</h3>", block, re.S)
        name = _clean(tm.group(1)) if tm else ""
        if not name:
            continue
        imgs = re.findall(r'<img src="([^"]+)"', block)
        out.append({
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": imgs[-1] if imgs else "",
            "vod_remarks": _remarks(block, "v"),
        })
    return out


def _norm_extend(extend):
    """归一化筛选参数：不同壳子传法不一
    dict / JSON 字符串 / 列表值 / (k, v) 对列表，统一成 {str: str}"""
    if isinstance(extend, str):
        try:
            extend = json.loads(extend)
        except Exception:
            return {}
    if isinstance(extend, (list, tuple)):
        out = {}
        for item in extend:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                out[str(item[0])] = item[1]
            elif isinstance(item, dict):
                out.update(item)
        extend = out
    if not isinstance(extend, dict):
        return {}
    out = {}
    for k, v in extend.items():
        if isinstance(v, (list, tuple)):
            v = v[0] if v else ""
        if v is None:
            v = ""
        out[str(k)] = str(v)
    return out


def _resolve_line(value):
    """线路值 -> 主机地址：代号 / 面板标签 / 完整 URL 均接受，空值走自动"""
    v = (value or "").strip()
    if not v:
        return None
    if v.startswith("http"):
        return v.rstrip("/")
    code = LINE_LABELS.get(v, v)
    return LINE_HOSTS.get(code)


def _pagecount(html):
    text = re.sub(r"<!--.*?-->", "", html or "", flags=re.S).replace("&amp;", "&")
    pages = [int(x) for x in re.findall(r"[?&;]page=(\d+)", text)]
    return max(pages) if pages else 1


def _total(html, pagecount):
    text = re.sub(r"<!--.*?-->", "", html or "", flags=re.S)
    m = re.search(r"([\d,]+)\s*個結果", text)
    return int(m.group(1).replace(",", "")) if m else pagecount * 26


class Spider(Spider):
    def __init__(self):  # 命门 2：标准构造 + super()
        try:
            super().__init__()
        except Exception:
            pass
        self.hosts = list(HOSTS)
        self.host = self.hosts[0]
        self._studios = set()      # 片商全集（/cat 手风琴），详情页识别片商用
        self._theme_tags = []      # 题材/属性（全部的子标签）
        self._cat_studios = {}     # 分类 -> 子标签（片商）
        self._filter_cache = None  # 会话内缓存：筛选数据（主分类/题材/剧集标签/片商）

    def getName(self):
        return "肉视频"

    # ---------- 初始化：记住的线路优先验证，其次综合测速优选（24h 内有效），
    # 否则 /status.html 轻量并行测速选最快（不做加分减分计分） ----------
    def init(self, extend=""):
        override = None
        try:
            if isinstance(extend, str) and extend.strip().startswith("{"):
                cfg = json.loads(extend)
                if isinstance(cfg.get("hosts"), list) and cfg["hosts"]:
                    override = [str(h).rstrip("/") for h in cfg["hosts"]]
        except Exception:
            pass
        if override:
            self.hosts = override
        else:
            self.hosts = self._active_pool()
        pool = list(self.hosts)
        cands = []
        rem = self._cache_get("rou_last_line")
        if rem and rem in pool:
            cands.append(rem)
        auto = self._cache_get("rou_auto_winner")
        ats = self._cache_get("rou_auto_ts")
        try:
            ats_ok = bool(ats) and (int(time.time()) - int(ats) < AUTO_TTL)
        except Exception:
            ats_ok = False
        if auto and auto in pool and ats_ok and auto not in cands:
            cands.append(auto)
        for cand in cands:
            if self._status_ms(cand) is not None:
                self.host = cand
                return True
        site = self._status_all(pool)
        if site:
            self.host = min(site, key=site.get)
        else:
            self.host = pool[0]
        return True

    def _get(self, path, host=None, timeout=12):
        order = []
        if host:
            order.append(host)
        order.append(self.host)
        order += [h for h in self.hosts if h not in order]
        for h in order:
            try:
                _, text = _fetch(h + path, timeout=timeout, referer=h + "/")
                if "站点维护中" in text and len(text) < 6000:
                    continue
                if h != self.host:
                    self.host = h
                return text
            except Exception:
                continue
        return ""

    # ---------- 壳子缓存（持久化）：无缓存支持的壳子自动退化为现状 ----------
    def _cache_get(self, key):
        try:
            fn = getattr(self, "getCache", None)
            if fn is None:
                return None
            v = fn(key)
            return v if v else None
        except Exception:
            return None

    def _cache_set(self, key, value):
        try:
            fn = getattr(self, "setCache", None)
            if fn is not None:
                fn(key, str(value))
        except Exception:
            pass

    def _cache_del(self, key):
        try:
            fn = getattr(self, "delCache", None)
            if fn is not None:
                fn(key)
            else:
                self._cache_set(key, "")
        except Exception:
            pass

    # ---------- 线路池：缓存优先，碎片化存储（单条短键，避长度限制） ----------
    def _active_pool(self):
        try:
            count = self._cache_get("rou_pool_count")
            if count and str(count).isdigit():
                pool = []
                for i in range(int(count)):
                    v = self._cache_get("rou_pool_%d" % i)
                    if v and str(v).startswith("http"):
                        pool.append(str(v).strip().rstrip("/"))
                if pool:
                    return pool
        except Exception:
            pass
        return list(HOSTS)

    def _save_pool(self, pool):
        try:
            self._cache_set("rou_pool_count", str(len(pool)))
            for i, u in enumerate(pool):
                self._cache_set("rou_pool_%d" % i, u)
        except Exception:
            pass

    # ---------- 轻量测速：/status.html 只回 ok，毫秒级 ----------
    # 超时取 5 秒：实测 3 秒超时下并行争抢会误杀好线（21 条只剩 3 条），
    # 5 秒超时下 21 条全通（965ms～3409ms），故不用 3 秒
    def _status_ms(self, host):
        try:
            t0 = time.time()
            req = urllib.request.Request(host + "/status.html",
                                         headers={"User-Agent": UA})
            with _opener.open(req, timeout=5) as r:
                body = r.read(100)
                if r.status == 200 and b"ok" in body.lower():
                    return int((time.time() - t0) * 1000)
        except Exception:
            pass
        return None

    def _status_all(self, hosts):
        out = {}
        hosts = list(dict.fromkeys(hosts))
        if _HAS_THREADS and len(hosts) > 1:
            try:
                with ThreadPoolExecutor(max_workers=min(16, len(hosts))) as ex:
                    for h, ms in ex.map(lambda u: (u, self._status_ms(u)),
                                        hosts):
                        if ms is not None:
                            out[h] = ms
                return out
            except Exception:
                pass
        for h in hosts:
            ms = self._status_ms(h)
            if ms is not None:
                out[h] = ms
        return out

    # ---------- 筛选数据：会话缓存 -> 壳子缓存(24h) -> 拉 /cat+/series ----------
    def _filter_data(self):
        if self._filter_cache is not None:
            return self._filter_cache
        data = None
        try:
            ts = self._cache_get("rou_f_ts")
            if ts and int(time.time()) - int(ts) < FILTER_TTL:
                classes = json.loads(self._cache_get("rou_f_classes") or "[]")
                theme = json.loads(self._cache_get("rou_f_theme") or "[]")
                series_tags = json.loads(self._cache_get("rou_f_series") or "[]")
                studios = {}
                if classes and theme:
                    for c in classes:
                        raw = self._cache_get(
                            "rou_f_st_" + urllib.parse.quote(c, safe=""))
                        if raw:
                            studios[c] = json.loads(raw)
                    data = (classes, theme, series_tags, studios)
        except Exception:
            data = None
        if data is None:
            try:
                if _HAS_THREADS:
                    with ThreadPoolExecutor(max_workers=2) as ex:
                        f_cat = ex.submit(self._get, "/cat")
                        f_ser = ex.submit(self._get, "/series")
                        cat_html, ser_html = f_cat.result(), f_ser.result()
                else:
                    raise RuntimeError("no threads")
            except Exception:
                cat_html = self._get("/cat")
                ser_html = self._get("/series")
            classes_found, theme, studios_by_cat = self._parse_cat(cat_html)
            classes = classes_found or list(FALLBACK_CLASSES)
            theme = theme or list(FALLBACK_THEME_TAGS)
            series_tags = []
            if ser_html:
                for tag in re.findall(r'href="/series\?tag=([^"&]+)', ser_html):
                    name = urllib.parse.unquote(tag)
                    if name and name not in series_tags:
                        series_tags.append(name)
            if not series_tags:
                series_tags = list(FALLBACK_SERIES_TAGS)
            data = (classes, theme, series_tags, studios_by_cat)
            try:
                self._cache_set("rou_f_ts", str(int(time.time())))
                self._cache_set("rou_f_classes",
                                json.dumps(classes, ensure_ascii=False))
                self._cache_set("rou_f_theme",
                                json.dumps(theme, ensure_ascii=False))
                self._cache_set("rou_f_series",
                                json.dumps(series_tags, ensure_ascii=False))
                for c, subs in studios_by_cat.items():
                    self._cache_set(
                        "rou_f_st_" + urllib.parse.quote(c, safe=""),
                        json.dumps(subs, ensure_ascii=False))
            except Exception:
                pass
        classes, theme, series_tags, studios_by_cat = data
        self._theme_tags = theme
        self._cat_studios = studios_by_cat
        self._studios = {s for subs in studios_by_cat.values() for s in subs}
        self._filter_cache = data
        return data

    # ---------- 线路筛选选项：按池顺序编号 + 两个动作 ----------
    def _line_options(self):
        opts = [{"n": "全部", "v": ""}]
        for i, u in enumerate(self.hosts):
            mark = "★ " if u == self.host else ""
            opts.append({"n": "%s线路%d" % (mark, i + 1), "v": u})
        opts.append({"n": "🔄 更新线路", "v": "ACTION_REFRESH_LINES"})
        opts.append({"n": "🧪 综合测速", "v": "ACTION_SPEED_TEST"})
        return opts

    # ---------- 更新线路：导航站嗅探 -> 全量换新 ----------
    # 老线 survivors 保原序、新线追加在末尾；嗅探无果时绝不删池
    #（状态检查误杀率太高，失效线由 _get 用时回退）；不做加分减分计分
    def _refresh_lines(self):
        fresh = []
        for nav in NAV_URLS:
            try:
                _, html = _fetch(nav, timeout=8)
            except Exception:
                html = ""
            if not html:
                continue
            for u in re.findall(r'https?://rou[a-z0-9.\-]+', html):
                origin = u.rstrip("/")
                if origin.startswith("https://www."):
                    origin = "https://" + origin[12:]
                if origin not in fresh:
                    fresh.append(origin)
            for b in re.findall(r'["\']([A-Za-z0-9+/=]{200,})["\']', html):
                try:
                    d = base64.b64decode(b).decode("utf-8", "ignore")
                except Exception:
                    continue
                d = urllib.parse.unquote(d)
                for u in re.findall(r'https?://rou[a-z0-9.\-]+', d):
                    origin = u.rstrip("/")
                    if origin.startswith("https://www."):
                        origin = "https://" + origin[12:]
                    if origin not in fresh:
                        fresh.append(origin)
            if fresh:
                break
        old = self._active_pool()
        if fresh:
            # 导航站表即最新权威：直接全量采纳，不再用状态码二次过滤
            #（状态检查受网络波动影响大，会误杀好线；失效线由 _get 用时回退）
            vset = set(fresh)
            new_pool = [u for u in old if u in vset]
            new_pool += [u for u in fresh if u not in old]
            self._save_pool(new_pool)
            self.hosts = new_pool
            rem = self._cache_get("rou_last_line")
            if rem and rem not in new_pool:
                self._cache_del("rou_last_line")
            auto = self._cache_get("rou_auto_winner")
            if auto and auto not in new_pool:
                self._cache_del("rou_auto_winner")
                self._cache_del("rou_auto_ts")
            if self.host not in new_pool:
                self.host = new_pool[0]
            added = len([u for u in new_pool if u not in old])
            return True, new_pool, "新增 %d 条，最新共 %d 条" % (
                added, len(new_pool))
        # 无新鲜表时绝不删池：状态检查误杀率太高（实测 3 秒超时下
        # 21 条只剩 3 条，而 5 秒超时下 21 条全通），失效线由 _get 用时回退
        return False, old, "未发现新域名，线路无变化（现 %d 条）" % len(old)

    def _refresh_result(self):
        changed, pool, note = self._refresh_lines()
        title = ("✅ 线路已更新为最新 %d 条" % len(pool)) if changed \
            else "⚠️ 更新线路未成功"
        items = [{"vod_id": "info_refresh_0", "vod_name": title,
                  "vod_pic": "", "vod_remarks": note[:30]},
                 {"vod_id": "info_refresh_1",
                  "vod_name": "提示：退回上级重进后，线路列表即为最新",
                  "vod_pic": "", "vod_remarks": "线路按池顺序编号"}]
        return {"list": items, "page": 1, "pagecount": 1, "limit": 30,
                "total": len(items)}

    # ---------- 综合测速：站点延迟取前 5，再以同一视频首分片比视频速度 ----------
    # 综合 = 视频首分片 256KB 耗时 + 0.3 × 站点延迟；优选结果缓存 24h
    def _resolve_hls(self, host, vid):
        """单线解析：/api/hls/{id} 直连（播放器同款路径，无需 ev），
        返回 (m3u8地址, 文本)，失败返回 (None, "")"""
        api = "/api/hls/" + vid
        try:
            final, body = _fetch(host + api, timeout=8,
                                 referer=host + "/v/" + vid)
            if final != host + api and "EXTM3U" in body[:64]:
                return final, body
        except Exception:
            pass
        return None, ""

    def _segment_ms(self, m3u8_url, body, referer):
        """首分片 128KB 耗时：必须用硬墙钟 10 秒 bound 住——单次 recv 超时
        防不住“细水长流”式卡顿（实测一次 256KB 读了 95 秒才完成）。
        超时返回 None（该线直接出局，不进排名）。"""
        seg = None
        lines = body.splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith("#EXTINF"):
                for nxt in lines[i + 1:]:
                    nxt = nxt.strip()
                    if nxt and not nxt.startswith("#"):
                        seg = nxt
                        break
                break
        if not seg:
            return None
        if seg.startswith("/"):
            seg = m3u8_url.rsplit("/", 1)[0] + seg
        elif not seg.startswith("http"):
            seg = m3u8_url.rsplit("/", 1)[0] + "/" + seg

        def _dl():
            t0 = time.time()
            req = urllib.request.Request(seg, headers={"User-Agent": UA,
                                                       "Referer": referer})
            with _opener.open(req, timeout=8) as r:
                r.read(128 * 1024)
            return int((time.time() - t0) * 1000)

        if not _HAS_THREADS:
            try:
                return _dl()
            except Exception:
                return None
        # 单独线程 + result 超时：墙钟超时后丢弃慢线程，结果直接判负
        ex = ThreadPoolExecutor(max_workers=1)
        try:
            fut = ex.submit(_dl)
            try:
                return fut.result(timeout=10)
            except Exception:
                return None
        finally:
            ex.shutdown(wait=False)

    def _comprehensive_test(self):
        pool = list(self.hosts)
        site = self._status_all(pool)
        if not site:
            return None, "站点测速全部失败"
        top = sorted(site.items(), key=lambda x: x[1])[:5]

        def probe(item):
            host, sms = item
            final, body = self._resolve_hls(host, TEST_VIDEO_ID)
            if not final:
                try:
                    _, html = _fetch(host + "/home", timeout=8)
                    cards = _parse_cards(html) if html else []
                    tried = 0
                    for card in cards:
                        vid = card["vod_id"]
                        if vid.startswith("s:"):
                            continue
                        final, body = self._resolve_hls(host, vid)
                        tried += 1
                        if final or tried >= 1:
                            break
                except Exception:
                    pass
            if not final:
                return None
            vms = self._segment_ms(final, body, host + "/")
            if vms is None:
                return None
            return {"host": host, "site": sms, "video": vms,
                    "combined": vms + int(0.3 * sms)}

        results = []
        if _HAS_THREADS:
            try:
                with ThreadPoolExecutor(max_workers=5) as ex:
                    for r in ex.map(probe, top):
                        if r:
                            results.append(r)
            except Exception:
                results = []
        if not results:
            for item in top:
                r = probe(item)
                if r:
                    results.append(r)
        if not results:
            return None, "视频测速全部失败（解析或分片超时）"
        results.sort(key=lambda r: r["combined"])
        winner = results[0]["host"]
        self.host = winner
        self._cache_set("rou_auto_winner", winner)
        self._cache_set("rou_auto_ts", str(int(time.time())))
        return results, ""

    def _speed_result(self):
        results, err = self._comprehensive_test()
        if not results:
            items = [{"vod_id": "info_speed_0", "vod_name": "⚠️ 综合测速失败",
                      "vod_pic": "", "vod_remarks": err[:30]}]
            return {"list": items, "page": 1, "pagecount": 1, "limit": 30,
                    "total": len(items)}
        items = []
        for i, r in enumerate(results):
            n = self.hosts.index(r["host"]) + 1 if r["host"] in self.hosts else 0
            medal = ["🥇", "🥈", "🥉", "4.", "5."][i] if i < 5 else "%d." % (i + 1)
            name = "%s 线路%d" % (medal, n) if n else "%s %s" % (medal, r["host"])
            if i == 0:
                name = "✅ 最优：" + name
            items.append({"vod_id": "info_speed_%d" % i, "vod_name": name,
                          "vod_pic": "",
                          "vod_remarks": "综合%dms 站点%dms 视频%dms" % (
                              r["combined"], r["site"], r["video"])})
        items.append({"vod_id": "info_speed_9",
                      "vod_name": "提示：已切换至最优线路，退回上级重进后生效",
                      "vod_pic": "", "vod_remarks": "综合=视频+0.3×站点"})
        return {"list": items, "page": 1, "pagecount": 1, "limit": 30,
                "total": len(items)}

    # ---------- /cat 解析：主分类、题材标签、按分类片商 ----------
    def _parse_cat(self, cat_html):
        classes, theme, studios_by_cat = [], [], {}
        if not cat_html:
            return classes, theme, studios_by_cat
        for href, label in re.findall(
                r'<a href="/t/([^"]+)"[^>]*>(.*?)</a>', cat_html, re.S):
            if "COLLECTION" in _clean(label):
                name = urllib.parse.unquote(href)
                if name and name not in classes:
                    classes.append(name)
        i = cat_html.find("題材 / 屬性")
        j = cat_html.find("按主分類找片商")
        if i >= 0:
            seg = cat_html[i:(j if j > i else i + 30000)]
            for href, label in re.findall(
                    r'<a href="/t/([^"]+)"[^>]*>(.*?)</a>', seg, re.S):
                name = urllib.parse.unquote(href)
                txt = re.sub(r"[\d,]+\s*$", "", _clean(label)).strip()
                if name and (txt == name) and name not in theme:
                    theme.append(name)
        if j >= 0:
            seg = cat_html[j:]
            parts = re.split(r"<summary[^>]*>(.*?)</summary>", seg, flags=re.S)
            # parts: [前言, 标题1, 内容1, 标题2, 内容2, ...]
            for k in range(1, len(parts) - 1, 2):
                title = _clean(parts[k])
                m = re.match(r"(.+?)(\d+)\s*個片商", title)
                if not m:
                    continue
                cat_name = m.group(1).strip()
                subs = []
                for href, label in re.findall(
                        r'<a href="/t/([^"]+)"[^>]*>(.*?)</a>', parts[k + 1], re.S):
                    name = urllib.parse.unquote(href)
                    if name and name not in subs:
                        subs.append(name)
                        self._studios.add(name)
                if subs:
                    studios_by_cat[cat_name] = subs[:30]
        return classes, theme, studios_by_cat

    # ---------- 首页：推荐置顶、全部、AI短剧、六大分类 + 分层筛选 ----------
    # 筛选数据走 _filter_data()（会话缓存 -> 壳子缓存 24h -> 拉 /cat+/series），
    # 缓存命中则零网络秒开；线路选项每次现拼（池子可能被“更新线路”换新），不进缓存。
    # 首页列表故意留空 —— OK影视等壳子会根据 home 列表自动生成一个推荐分类；
    # 推荐内容改由显式推荐分类（categoryContent 的 recommend 路由）提供，
    # 避免出现两个推荐。
    def homeContent(self, filter):
        classes_found, theme, series_tags, studios_by_cat = self._filter_data()

        classes = [{"type_id": "recommend", "type_name": "推荐"},
                   {"type_id": "all", "type_name": "全部"},
                   {"type_id": "series", "type_name": "AI短剧"}]
        for n in classes_found:
            classes.append({"type_id": n, "type_name": n})

        sort_filter = {"key": "sort", "name": "排序方式",
                       "value": [dict(x) for x in SORT_VALUES]}
        line_filter = {"key": "line", "name": "切换线路",
                       "value": self._line_options()}

        def tag_filter(name, tags, first=None):
            values = []
            if first:
                values.append(first)
            values.append({"n": "全部", "v": ""})
            values += [{"n": t, "v": t} for t in tags]
            return {"key": "tag", "name": name, "value": values}

        filters = {
            # 线路切换在推荐分类
            "recommend": [line_filter],
            "all": [tag_filter("题材", theme), sort_filter],
            "series": [tag_filter("题材", series_tags),
                       {"key": "sort", "name": "排序方式",
                        "value": [dict(x) for x in SERIES_SORT_VALUES]}],
        }
        for c in classes:
            tid = c["type_id"]
            if tid in filters:
                continue
            subs = studios_by_cat.get(tid, [])
            # 子标签最前固定加本站「分類精選」（该分类按点赞排序的入口）；
            # 自拍流出站内本就没有片商分组，只有精選+全部两项
            fl = [tag_filter("子标签", subs,
                             first={"n": tid + "精選",
                                    "v": "__featured__"}),
                  sort_filter]
            filters[tid] = fl
        return {"class": classes, "list": [], "filters": filters}

    # ---------- 分类列表 ----------
    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if str(tid).startswith("ACTION"):
            return {"list": [], "page": pg, "pagecount": 1, "limit": 26, "total": 0}
        extend = _norm_extend(extend)
        host = _resolve_line(extend.get("line", ""))
        sort = extend.get("sort", "")
        tag = extend.get("tag", "")

        if tid == "recommend":
            # 推荐分类：内容即站内首页推荐（/home），线路筛选在此生效
            if pg != 1:
                return {"list": [], "page": pg, "pagecount": 1,
                        "limit": 30, "total": 0}
            line_val = extend.get("line", "")
            if line_val == "ACTION_REFRESH_LINES":
                return self._refresh_result()
            if line_val == "ACTION_SPEED_TEST":
                return self._speed_result()
            html = self._get("/home", host, timeout=8)
            videos = _parse_cards(html) if html else []
            if videos and line_val:
                # 显式选线且成功出列表：记住实际生效的线路（壳子缓存持久化）
                self._cache_set("rou_last_line", self.host)
            return {"list": _pub(videos), "page": pg, "pagecount": 1,
                    "limit": 30, "total": len(videos)}

        if tid == "series":
            # 站点 SSR 只认 tag/page，sort 为前端行为 -> 以卡片自带数据在页内重排
            params = []
            if tag:
                params.append("tag=" + urllib.parse.quote(tag))
            params.append("page=%d" % pg)
            html = self._get("/series?" + "&".join(params), host, timeout=8)
            videos = _parse_cards(html, want=("s",)) if html else []
            if sort == "most":
                videos.sort(key=lambda c: c.get("_eps", 0), reverse=True)
            elif sort == "hot":
                videos.sort(key=lambda c: c.get("_views", 0), reverse=True)
            return {"list": _pub(videos), "page": pg,
                    "pagecount": _pagecount(html), "limit": 26,
                    "total": _total(html, _pagecount(html))}

        # 精选 = 该分类按点赞排序（站内「分類精選」的定义），优先于排序筛选
        featured = (tag == "__featured__")
        if featured:
            sort = "likeCount"
            tag = ""
        params = []
        if sort:
            params.append("order=" + sort)
        params.append("page=%d" % pg)
        if tid == "all" and not tag:
            path = "/v?" + "&".join(params)
            want = ("v", "s")
        else:
            target = tag if tag else tid
            path = "/t/" + urllib.parse.quote(str(target)) + "?" + "&".join(params)
            want = ("v", "s")
        html = self._get(path, host, timeout=8)
        if not html and tid not in ("all",):  # 兜底默认路由防白板
            html = self._get("/t/" + urllib.parse.quote(FALLBACK_CLASSES[0])
                             + "?page=%d" % pg, host, timeout=8)
        videos = _parse_cards(html, want=want) if html else []
        pc = _pagecount(html)
        return {"list": _pub(videos), "page": pg, "pagecount": pc,
                "limit": 26, "total": _total(html, pc)}

    # ---------- 详情 ----------
    def detailContent(self, ids):
        vid = ids[0] if ids else ""
        if vid.startswith("info_") or vid.startswith("empty"):
            # 更新线路 / 综合测速的提示项，点开不做任何请求
            return {"list": [{"vod_id": vid, "vod_name": "提示", "vod_pic": "",
                              "vod_content": "这是一条提示信息，无需播放。",
                              "vod_play_from": "提示",
                              "vod_play_url": "知道了$http://127.0.0.1/empty.mp4"}]}
        if vid.startswith("s:"):
            return {"list": [self._series_detail(vid[2:])]}
        return {"list": [self._video_detail(vid)]}

    def _jsonld(self, html):
        m = re.search(r'<script type="application/ld\+json">(.*?)</script>',
                      html, re.S)
        if not m:
            return {}
        try:
            data = json.loads(m.group(1))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _page_title(self, html):
        m = re.search(r"<title>(.*?)</title>", html, re.S)
        t = _clean(m.group(1)) if m else ""
        return re.split(r"\s*-\s*肉視頻", t)[0].strip()

    def _detail_tags(self, html):
        tags = []
        for label in re.findall(r'<a href="/t/[^"]+"[^>]*>(.*?)</a>', html, re.S):
            t = _clean(label)
            if t.startswith("#"):
                name = t.lstrip("#").strip()
                if name and name not in tags:
                    tags.append(name)
        return tags

    def _synopsis(self, html, ld_desc):
        """简介四级兜底：1) 影片簡介区块 2) meta description 长文本（剧集页简介
        就藏在这里，正文里没有标题段落）3) 正文最长中文段落（排除选集/推荐等
        页面骨架文本）4) JSON-LD 长描述；过滤“還沒有簡介”占位"""
        i = html.find("影片簡介")
        if i >= 0:
            seg = _clean(html[i:i + 1600])
            seg = seg.replace("影片簡介", "", 1)
            seg = re.split(r"回報內容問題|相關視頻|相關推薦", seg)[0].strip()
            if seg and "還沒有簡介" not in seg:
                return seg
        mm = re.search(r'<meta name="description" content="([^"]{60,})"',
                       html or "")
        if mm:
            desc = htmlmod.unescape(mm.group(1)).strip()
            if "還沒有簡介" not in desc:
                return desc
        best = ""
        for p in re.findall(r"<p[^>]*>(.*?)</p>", html or "", re.S):
            t = _clean(p)
            if len(t) < 60 or "還沒有簡介" in t:
                continue
            if any(w in t for w in ["首頁", "探索", "sessionStorage",
                                    "JSON.parse", "function(", "選集",
                                    "你可能也喜歡", "從第 1 集開始", "倒序排列",
                                    "友情链接", "友情連結", "防失联", "防失聯"]):
                continue
            if sum("\u4e00" <= c <= "\u9fff" for c in t) < 40:
                continue
            if len(t) > len(best):
                best = t
        if best:
            return best
        if ld_desc and len(ld_desc) >= 40:
            return ld_desc
        return ""

    def _video_detail(self, vid):
        html = self._get("/v/" + vid)
        ld = self._jsonld(html)
        name = ld.get("name") or self._page_title(html) or vid
        pic = ""
        thumb = ld.get("thumbnailUrl")
        if isinstance(thumb, list) and thumb:
            pic = thumb[0]
        elif isinstance(thumb, str):
            pic = thumb
        if not pic:
            pm = re.search(r'poster="([^"]+)"', html)
            pic = pm.group(1) if pm else ""
        tags = self._detail_tags(html)
        genres = ld.get("genre") or []
        all_tags = tags or (genres if isinstance(genres, list) else [])
        studio = ""
        for t in all_tags:
            if t in self._studios:
                studio = t
                break
        info = re.search(
            r"([\d,.]+\s*萬?次觀看)·([^<·]{2,14})·(\d+分\d+秒|\d+秒)",
            re.sub(r"<!--.*?-->", "", html))
        if info:
            views = re.sub(r"\s+", "", info.group(1))
            age, dur = info.group(2).strip(), info.group(3)
        else:
            views, age, dur = "", "", ""
        lines = []
        syn = self._synopsis(html, ld.get("description") or "")
        if syn:
            lines.append(syn)
        series = ld.get("partOfSeries") or {}
        if series.get("name"):
            ep = ld.get("episodeNumber")
            lines.append("剧集：%s%s" % (series["name"],
                                         (" 第%s集" % ep) if ep else ""))
        if studio:
            lines.append("片商：" + studio)
        rest_tags = [t for t in all_tags if t != studio]
        if rest_tags:
            lines.append("标签：" + "、".join(rest_tags))
        meta = []
        if views:
            meta.append("观看 " + views)
        if age:
            meta.append("发布 " + age)
        if dur:
            meta.append("时长 " + dur)
        if meta:
            lines.append(" · ".join(meta))
        vod = {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": pic,
            "vod_year": (ld.get("uploadDate") or "")[:4],
            "vod_type": ",".join(all_tags),
            "vod_actor": "",
            "vod_director": studio,
            "vod_content": "\n".join(lines),
            "vod_remarks": dur,
            "vod_play_from": "正片",
        }
        main_line = "%s$%s" % (name, vid)
        related = _parse_cards(html, want=("v",)) + _parse_list_rows(html)
        rec, seen_ids = [], {vid}
        for card in related:
            if card["vod_id"] not in seen_ids:
                seen_ids.add(card["vod_id"])
                rec.append("%s$%s" % (card["vod_name"], card["vod_id"]))
        if rec:
            vod["vod_play_from"] = "正片$$$相关推荐"
            vod["vod_play_url"] = main_line + "$$$" + "#".join(rec[:12])
        else:
            vod["vod_play_url"] = main_line
        return vod

    def _series_detail(self, sid):
        html = self._get("/s/" + sid)
        ld = self._jsonld(html)
        name = ld.get("name") or self._page_title(html) or sid
        pic = ""
        thumb = ld.get("thumbnailUrl")
        if isinstance(thumb, list) and thumb:
            pic = thumb[0]
        elif isinstance(thumb, str):
            pic = thumb
        episodes = _parse_cards(html, want=("v",))
        plays = ["%s$%s" % (ep["vod_name"], ep["vod_id"]) for ep in episodes]
        if not plays:
            raw = list(dict.fromkeys(re.findall(r'href="/v/([a-z0-9]+)"', html)))
            plays = ["第%d集$%s" % (i + 1, x) for i, x in enumerate(raw)]
        tags = self._detail_tags(html)
        lines = []
        syn = self._synopsis(html, ld.get("description") or "")
        if syn:
            lines.append(syn)
        if plays:
            lines.append("集数：全%d集" % len(plays))
        flat = re.sub(r"<!--.*?-->", "", html)
        sm = re.search(r"<span>(已完結|連載中|更新中)</span>", flat)
        if sm:
            lines.append("状态：" + sm.group(1))
        vm = re.search(r"([\d,.]+)\s*萬?次觀看", flat)
        um = re.search(r"更新於\s*([^<]{2,14})", flat)
        meta = []
        if vm:
            meta.append("观看 " + re.sub(r"\s+", "", vm.group(0)))
        if um:
            meta.append("更新 " + um.group(1).strip())
        if meta:
            lines.append(" · ".join(meta))
        if tags:
            lines.append("标签：" + "、".join(tags))
        vod = {
            "vod_id": "s:" + sid,
            "vod_name": name,
            "vod_pic": pic,
            "vod_year": (ld.get("uploadDate") or "")[:4]
                        if isinstance(ld.get("uploadDate"), str) else "",
            "vod_type": "劇集" + (("," + ",".join(tags)) if tags else ""),
            "vod_content": "\n".join(lines),
            "vod_play_from": "正片",
            "vod_play_url": "#".join(plays),
        }
        related = _parse_cards(html, want=("s",))
        rec, seen_ids = [], {"s:" + sid}
        for card in related:
            if card["vod_id"] not in seen_ids:
                seen_ids.add(card["vod_id"])
                rec.append("%s$%s" % (card["vod_name"], card["vod_id"]))
        if rec:
            vod["vod_play_from"] = "正片$$$相关推荐"
            vod["vod_play_url"] = vod["vod_play_url"] + "$$$" + "#".join(rec[:10])
        return vod

    # ---------- 播放：/api/hls/{id} -> 302 -> 签名 m3u8 ----------
    def playerContent(self, flag, id, vipFlags):
        vid = id
        if str(id).startswith("s:"):  # 相关推荐里的剧集：解析其第一集
            html = self._get("/s/" + str(id)[2:])
            eps = _parse_cards(html, want=("v",)) if html else []
            if eps:
                vid = eps[0]["vod_id"]
            else:
                raw = re.findall(r'href="/v/([a-z0-9]+)"', html or "")
                vid = raw[0] if raw else vid
        api = "/api/hls/" + str(vid)
        header = {"User-Agent": UA, "Referer": self.host + "/v/" + str(vid)}
        for _ in range(2):
            for h in [self.host] + [x for x in self.hosts if x != self.host]:
                try:
                    final, body = _fetch(h + api, timeout=15,
                                         referer=h + "/v/" + str(vid))
                    if final != h + api and "EXTM3U" in body[:64]:
                        return {"parse": 0, "url": final, "header": header}
                except Exception:
                    continue
        return {"parse": 0, "url": self.host + api, "header": header}

    # ---------- 搜索：/search?q={wd} ----------
    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        path = "/search?q=" + urllib.parse.quote(str(key))
        if pg > 1:
            path += "&page=%d" % pg
        html = self._get(path)
        videos = _parse_cards(html) if html else []
        return {"list": _pub(videos), "page": pg,
                "pagecount": _pagecount(html), "limit": 26,
                "total": _total(html, 1)}

    def destroy(self):
        return "free"
