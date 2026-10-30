# -*- coding: utf-8 -*-
"""
八戒影视 Spider（hipy / CatVod 类爬虫框架适配）
关键:
  - 通过 oss domainPath.json 动态获取站点 host
  - visitorInfo 获取游客 userId / token
  - 短剧(M16)虚拟分集 + 普通影片真实分集 双模式
本资源来源于互联网公开渠道，仅可用于个人学习爬虫技术。
严禁将其用于任何商业用途，下载后请于 24 小时内删除，
搜索结果均来自源站，作者不承担任何责任。

使用方式：
  - 作为 CatVod / hipy 爬虫模块：由框架加载 Spider 类并调用其接口。
  - 独立运行（python bajie_spider.py）：仅执行 init() 自测，验证能否
    成功拉取 domainPath、获取 visitorInfo 的 userId/token。
"""

import sys
import os
import json
import time
import concurrent.futures
from urllib.parse import quote
from typing import Dict, List, Any, Optional, Tuple

sys.path.append('..')

try:
    from base.spider import Spider as _BaseSpider
except ImportError:
    import requests as _rq
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass

    class _BaseSpider:
        """独立运行时的占位基类，仅提供 fetch/post 兜底实现。"""

        def __init__(self):
            self._session = None

        @property
        def _sess(self):
            if self._session is None:
                self._session = _rq.Session()
                self._session.verify = False
                adapter = _rq.adapters.HTTPAdapter(
                    pool_connections=10, pool_maxsize=10, max_retries=0)
                self._session.mount('https://', adapter)
                self._session.mount('http://', adapter)
            return self._session

        def fetch(self, url, headers=None, **kw):
            timeout = kw.pop('timeout', 15)
            r = self._sess.get(url, headers=headers, timeout=timeout, **kw)
            r.encoding = 'utf-8'
            return r

        def post(self, url, data=None, headers=None, **kw):
            timeout = kw.pop('timeout', 15)
            r = self._sess.post(url, data=data, headers=headers,
                                timeout=timeout, **kw)
            r.encoding = 'utf-8'
            return r

        def log(self, *a, **kw):
            try:
                print("[bajie]", *a)
            except Exception:
                pass


# ===================== 常量 =====================
DOMAIN_CFG_URL = ("http://osstexll.oss-rg-china-mainland.aliyuncs.com/"
                  "domainPath.json")

UA_APP = "okhttp/4.12.0"
UA_PLAY = ("Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) "
           "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 "
           "Mobile/15E148 Safari/604.1")

INTRO_PREFIX = "🍊小橙子为您介绍剧情👉请不要相信视频中的广告，以免上当受骗！"

# 短剧类型 / 关键词
SHORT_TYPE_ID = "M16"
SHORT_KEYWORDS = ("合集", "短剧", "RO", "分剧", "分集")
SHORT_EP_MAX = 500      # 短剧虚拟分集上限
NORMAL_EP_MAX = 200     # 普通片虚拟分集上限
SHORT_EP_THRESHOLD = 80  # 集数超过此值视为短剧

# 缓存 TTL（秒）
TTL_HOME = 600
TTL_HOME_VIDEO = 300
TTL_CATEGORY = 120
TTL_SEARCH = 60
TTL_DETAIL = 600

PAGE_SIZE = 40


class Spider(_BaseSpider):
    host: str = ""
    userid: str = ""
    _cache: Dict = {}

    headers = {
        "User-Agent": UA_APP,
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json;charset=UTF-8",
        "Cache-Control": "no-cache",
        "token": "",
        "deviceId": "",
        "client": "app",
        "deviceType": "Android",
    }

    # ---------- 辅助方法 ----------
    def _safe_get(self, data: Dict, key: str, default: Any = "") -> Any:
        """安全获取字典值，避免 KeyError"""
        if not isinstance(data, dict):
            return default
        v = data.get(key, default)
        return default if v is None else v

    def _log(self, *a):
        try:
            print("[bajie]", *a)
        except Exception:
            pass

    def _build_video_item(self, data: Dict,
                          extra_fields: Optional[List[str]] = None) -> Dict:
        """构建标准的视频项字典"""
        item = {
            "vod_id": self._safe_get(data, "id"),
            "vod_name": self._safe_get(data, "name", "未知影片"),
            "vod_pic": self._safe_get(data, "cover", ""),
            "vod_remarks": self._safe_get(data, "area", ""),
            "vod_year": self._safe_get(data, "year", ""),
        }
        if extra_fields:
            for field in extra_fields:
                item[f"vod_{field}"] = self._safe_get(data, field, "")
        return item

    def _safe_request(self, url: str, payload: Dict = None, method: str = "POST",
                      max_retries: int = 3, retry_delay: int = 1) -> Optional[Dict]:
        """安全请求：带重试 + 业务码校验"""
        for attempt in range(max_retries):
            try:
                if method.upper() == "POST":
                    resp = self.post(
                        url,
                        data=json.dumps(payload) if payload is not None else None,
                        headers=self.headers,
                    )
                else:
                    resp = self.fetch(url, headers=self.headers)

                if resp.status_code == 200:
                    result = resp.json()
                    code = result.get("code", 200)
                    if code in (200, 0):
                        return result
                    msg = result.get("msg", result.get("message", "未知错误"))
                    self._log("[API错误] code=%s, msg=%s" % (code, msg))
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    return None
                else:
                    self._log("[HTTP错误] status=%s url=%s"
                              % (resp.status_code, url))
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    return None
            except Exception as e:
                self._log("[请求失败] 尝试 %d/%d: %s"
                          % (attempt + 1, max_retries, e))
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                return None
        return None

    def _get_cache(self, key: str, ttl: int = 300) -> Optional[Any]:
        """获取缓存（带 TTL）"""
        if key in self._cache:
            cache_data, timestamp = self._cache[key]
            if time.time() - timestamp < ttl:
                return cache_data
            del self._cache[key]
        return None

    def _set_cache(self, key: str, value: Any):
        """设置缓存"""
        self._cache[key] = (value, time.time())

    # ---------- 框架接口 ----------
    def getName(self):
        return "八戒影视"

    def init(self, extend=""):
        """初始化：获取域名配置 + 游客认证信息"""
        try:
            self.extend = json.loads(extend) if extend else {}
        except Exception:
            self.extend = {}

        self._cache = {}

        self.headers["deviceId"] = "2d590b9842d064a1"

        # 1) 拉取域名路径配置（支持 BAJIE_HOST 环境变量手动指定）
        cfg_host = os.environ.get("BAJIE_HOST", "").strip()
        if cfg_host:
            self.host = cfg_host.rstrip("/")
            self._log("init: 使用环境变量指定 host: %s" % self.host)
        else:
            try:
                resp = self.fetch(DOMAIN_CFG_URL, headers={
                    "User-Agent": UA_APP,
                    "Connection": "Keep-Alive",
                    "Accept-Encoding": "gzip",
                })
                j = resp.json()
                if isinstance(j, dict) and j.get("status") in (403, 401, 400):
                    raise RuntimeError(
                        "domainPath.json 被源站拒绝访问(status=%s): %s。"
                        "可通过环境变量 BAJIE_HOST=http://xxx 手动指定 host。"
                        % (j.get("status"), j.get("detail") or j.get("title")))
                urls = j.get("url") if isinstance(j, dict) else None
                if not urls:
                    raise RuntimeError(
                        "domainPath.json 返回结构异常: " + str(j)[:200])
                self.host = str(urls[0]).rstrip("/")
                self._log("init: 远程配置 host: %s" % self.host)
            except Exception as e:
                self._log("init: 获取域名配置失败: %s" % e)
                raise

        # 2) 获取游客用户信息（userId / token）
        try:
            resp = self.fetch(
                "%s/api/v1/app/user/visitorInfo" % self.host,
                headers=self.headers)
            data = resp.json().get("data", {}) or {}
            self.userid = str(data.get("id", "") or "")
            self.headers["token"] = data.get("token", "") or ""
            self._log("init: 游客信息获取成功, userid=%s" % self.userid)
        except Exception as e:
            self._log("init: 获取游客信息失败: %s" % e)
            raise

    def homeContent(self, filter):
        """获取首页分类列表"""
        cache_key = "home_content"
        cached = self._get_cache(cache_key, ttl=TTL_HOME)
        if cached:
            return cached

        try:
            result = self._safe_request(
                "%s/api/v1/app/screen/screenType" % self.host, method="POST")
            if not result:
                return {"class": []}

            data = result.get("data", []) or []
            classes = [
                {
                    "type_id": self._safe_get(i, "id"),
                    "type_name": self._safe_get(i, "name", "未命名分类"),
                }
                for i in data if self._safe_get(i, "id")
            ]
            self._log("homeContent: %d 个分类" % len(classes))
            result_data = {"class": classes}
            self._set_cache(cache_key, result_data)
            return result_data
        except Exception as e:
            self._log("homeContent FAIL: %s" % e)
            return {"class": []}

    def homeVideoContent(self):
        """获取首页推荐内容（并发拉取各推荐板块子列表）"""
        cache_key = "home_video"
        cached = self._get_cache(cache_key, ttl=TTL_HOME_VIDEO)
        if cached:
            return cached

        try:
            result = self._safe_request(
                "%s/api/v1/app/recommend/recommendList" % self.host,
                method="POST")
            if not result:
                return {"list": []}

            data = result.get("data", []) or []
            videos = []
            seen = set()

            def _collect(item_id):
                sub = self._safe_request(
                    "%s/api/v1/app/recommend/recommendSubList" % self.host,
                    payload={"condition": item_id, "pageNum": 1,
                             "pageSize": 6},
                    method="POST")
                out = []
                if sub:
                    for v in (sub.get("data", {}) or {}).get("records", []):
                        out.append(v)
                return out

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
                futures = {
                    ex.submit(_collect, item["id"]): item["id"]
                    for item in data if self._safe_get(item, "id")
                }
                for fut in concurrent.futures.as_completed(futures):
                    try:
                        for v in fut.result():
                            vid = self._safe_get(v, "id")
                            if vid and vid not in seen:
                                seen.add(vid)
                                videos.append(self._build_video_item(v))
                    except Exception as e:
                        self._log("homeVideoContent 子板块失败: %s" % e)

            self._log("homeVideoContent: %d 个推荐视频" % len(videos))
            result_data = {"list": videos}
            self._set_cache(cache_key, result_data)
            return result_data
        except Exception as e:
            self._log("homeVideoContent FAIL: %s" % e)
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        """获取分类内容（支持筛选条件 extend）"""
        if isinstance(extend, str):
            try:
                extend = json.loads(extend) if extend else {}
            except Exception:
                extend = {}
        if not isinstance(extend, dict):
            extend = {}
        for k in list(extend.keys()):
            if extend[k] in ("", None, "全部"):
                del extend[k]

        page = int(pg) if pg else 1
        cache_key = "category_%s_%s_%s" % (tid, page, json.dumps(
            extend, sort_keys=True, ensure_ascii=False))
        cached = self._get_cache(cache_key, ttl=TTL_CATEGORY)
        if cached:
            return cached

        try:
            cond = {
                "classify": extend.get("class", ""),
                "region": extend.get("area", ""),
                "sreecnTypeEnum": extend.get("sort_field", "NEWEST"),
                "typeId": tid,
                "year": extend.get("year", ""),
            }
            payload = {"condition": cond, "pageNum": page,
                       "pageSize": PAGE_SIZE}

            result = self._safe_request(
                "%s/api/v1/app/screen/screenMovie" % self.host,
                payload=payload, method="POST")
            if not result:
                return {"list": [], "page": page, "pagecount": 1,
                        "limit": PAGE_SIZE, "total": 0}

            d = result.get("data", {}) or {}
            records = d.get("records", []) or []
            total = int(d.get("total", 0) or 0)
            pagecount = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

            videos = [self._build_video_item(i, ["area", "year"])
                      for i in records]

            self._log("category: tid=%s pg=%s -> %d 条"
                      % (tid, page, len(videos)))
            result_data = {
                "list": videos, "page": page, "pagecount": pagecount,
                "limit": PAGE_SIZE, "total": total,
            }
            self._set_cache(cache_key, result_data)
            return result_data
        except Exception as e:
            self._log("categoryContent FAIL (tid=%s pg=%s): %s"
                      % (tid, pg, e))
            return {"list": [], "page": page, "pagecount": 1,
                    "limit": PAGE_SIZE, "total": 0}

    def searchContent(self, key, quick, pg="1"):
        """搜索内容"""
        page = int(pg) if pg else 1
        cache_key = "search_%s_%s" % (key, page)
        cached = self._get_cache(cache_key, ttl=TTL_SEARCH)
        if cached:
            return cached

        try:
            payload = {"condition": {"value": key},
                       "pageNum": page, "pageSize": PAGE_SIZE}

            result = self._safe_request(
                "%s/api/v1/app/search/searchMovie" % self.host,
                payload=payload, method="POST")
            if not result:
                return {"list": [], "page": page}

            d = result.get("data", {}) or {}
            records = d.get("records", []) or []
            total = int(d.get("total", 0) or 0)
            pagecount = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

            videos = [self._build_video_item(i, ["area", "year", "desc"])
                      for i in records]

            self._log("search: key='%s' pg=%s -> %d 条"
                      % (key, page, len(videos)))
            result_data = {
                "list": videos, "page": page, "pagecount": pagecount,
                "limit": PAGE_SIZE, "total": total,
            }
            self._set_cache(cache_key, result_data)
            return result_data
        except Exception as e:
            self._log("searchContent FAIL (key='%s'): %s" % (key, e))
            return {"list": [], "page": page}

    def searchContentPage(self, key, quick, pg="1"):
        return self.searchContent(key, quick, pg)

    def detailContent(self, ids):
        """获取影片详情（含短剧特殊处理 + 简介前缀）"""
        if not ids:
            return {"list": []}
        video_id = str(ids[0])
        cache_key = "detail_%s" % video_id
        cached = self._get_cache(cache_key, ttl=TTL_DETAIL)
        if cached:
            return cached

        try:
            payload = {"id": video_id, "source": 0, "typeId": "M17",
                       "userId": self.userid}
            result = self._safe_request(
                "%s/api/v1/app/play/movieDetails" % self.host,
                payload=payload, method="POST")
            if not result:
                return {"list": []}

            data = result.get("data", {}) or {}
            if not data:
                self._log("detail: 影片 %s 无数据" % video_id)
                return {"list": []}

            # 简介独立接口，多层兜底
            desc_result = self._safe_request(
                "%s/api/v1/app/play/movieDesc" % self.host,
                payload={"id": video_id, "typeId": "M17"}, method="POST")
            d2 = (desc_result.get("data", {}) if desc_result else {}) or {}

            video_detail = self._build_detail_data(video_id, data, d2)

            self._log("detail: %s -> 播放源 %s"
                      % (video_detail.get("vod_name"),
                         video_detail.get("vod_play_from")))
            result_data = {"list": [video_detail]}
            self._set_cache(cache_key, result_data)
            return result_data
        except Exception as e:
            self._log("detailContent FAIL (ids=%s): %s" % (ids, e))
            return {"list": []}

    def _build_detail_data(self, video_id: str, data: Dict,
                           desc_data: Dict) -> Dict:
        """构建影片详情数据（短剧/普通双模式 + 简介前缀）"""
        currentplayerid = data.get("playerId", 0)
        episode_list = data.get("episodeList", []) or []
        movie_player_list = data.get("moviePlayerList", []) or []

        play_urls: List[str] = []
        show: List[str] = []

        if self._is_short_drama(data, movie_player_list):
            play_urls, show = self._build_short_drama_playlist(
                video_id, movie_player_list, currentplayerid)
        else:
            play_urls, show = self._build_normal_playlist(
                video_id, episode_list, movie_player_list, currentplayerid)

        # 兜底：至少保证有一个可点的源
        if not play_urls:
            show = ["默认源"]
            play_urls = ["第1集$1@0@%s@virtual" % video_id]

        # ===== 简介（多层兜底 + 指定前缀）=====
        content = (
            self._safe_get(desc_data, "introduce")
            or self._safe_get(data, "introduce")
            or self._safe_get(desc_data, "desc")
            or self._safe_get(data, "desc")
            or ""
        ).strip()
        content = (INTRO_PREFIX + "\n" + content) if content else INTRO_PREFIX

        video = {
            "vod_id": self._safe_get(desc_data, "id", video_id) or video_id,
            "vod_name": (self._safe_get(desc_data, "name")
                         or self._safe_get(data, "name", "未知影片")),
            "vod_pic": (self._safe_get(desc_data, "cover")
                        or self._safe_get(data, "cover", "")),
            "vod_content": content,
            "vod_year": (self._safe_get(desc_data, "year")
                         or self._safe_get(data, "year", "")),
            "vod_area": (self._safe_get(desc_data, "area")
                         or self._safe_get(data, "area", "")),
            "vod_remarks": (self._safe_get(desc_data, "score")
                            or "%d条线路" % len(show)),
            "vod_score": (self._safe_get(desc_data, "score")
                          or self._safe_get(data, "score", "")),
            "type_name": (self._safe_get(desc_data, "classify")
                          or self._safe_get(data, "classify", "")),
            "vod_director": (self._safe_get(desc_data, "director")
                             or self._safe_get(data, "director", "")),
            "vod_actor": self._safe_get(desc_data, "actor",
                                        self._safe_get(data, "actor", "")),
            "vod_play_from": "$$$".join(show),
            "vod_play_url": "$$$".join(play_urls),
        }
        return video

    def _is_short_drama(self, data: Dict, player_list: List) -> bool:
        """判断是否为短剧：类型ID / 类型名 / 播放源名 / 集数 多层兜底"""
        if self._safe_get(data, "typeId") == SHORT_TYPE_ID:
            return True

        type_name = (self._safe_get(data, "typeName")
                     or self._safe_get(data, "classify") or "")
        if "短剧" in type_name:
            return True

        for pl in player_list:
            pl_name = self._safe_get(pl, "moviePlayerName", "")
            if any(kw in pl_name for kw in SHORT_KEYWORDS):
                return True

        for pl in player_list:
            if (self._safe_get(pl, "episodeTotal", 0) or 0) \
                    > SHORT_EP_THRESHOLD:
                return True

        return False

    def _build_short_drama_playlist(self, video_id: str, player_list: List,
                                    current_id: int) -> Tuple[List[str], List[str]]:
        """构建短剧播放列表：每个播放源独立生成虚拟分集"""
        play_urls: List[str] = []
        show: List[str] = []

        for pl in player_list:
            pl_id = pl.get("id")
            episode_total = pl.get("episodeTotal")
            pl_name = self._safe_get(pl, "moviePlayerName", "未知源")

            if not episode_total or int(episode_total) <= 0:
                continue

            pu = [
                "第%d集$%d@%s@%s@virtual"
                % (ep, ep, pl_id, video_id)
                for ep in range(1, min(int(episode_total) + 1, SHORT_EP_MAX))
            ]
            if pu:
                play_urls.append("#".join(pu))
                show.append(pl_name)

        return play_urls, show

    def _build_normal_playlist(self, video_id: str, episode_list: List,
                               player_list: List,
                               current_id: int) -> Tuple[List[str], List[str]]:
        """构建普通剧集播放列表：优先真实分集，其余源虚拟分集"""
        play_urls: List[str] = []
        show: List[str] = []

        if episode_list:
            # 当前播放源名称
            current_source_name = "默认源"
            for pl in player_list:
                if pl.get("id") == current_id:
                    current_source_name = self._safe_get(
                        pl, "moviePlayerName", "默认源")
                    break

            play_url = [
                "%s$%s@%s@%s@episode"
                % (self._safe_get(ep, "episode", str(idx + 1)),
                   video_id, current_id,
                   self._safe_get(ep, "id", ""))
                for idx, ep in enumerate(episode_list)
            ]
            play_urls.append("#".join(play_url))
            show.append(current_source_name)

            # 其余播放源 → 虚拟分集
            for pl in player_list:
                pl_id = pl.get("id")
                if pl_id == current_id:
                    continue
                pl_name = self._safe_get(pl, "moviePlayerName", "未知源")
                if pl_name in show:
                    continue
                ep_total = self._safe_get(pl, "episodeTotal",
                                          len(episode_list))
                if ep_total and int(ep_total) > 0:
                    pu = [
                        "第%d集$%d@%s@%s@virtual"
                        % (ep, ep, pl_id, video_id)
                        for ep in range(1, min(int(ep_total) + 1,
                                               NORMAL_EP_MAX))
                    ]
                    if pu:
                        play_urls.append("#".join(pu))
                        show.append(pl_name)
        else:
            # 没有真实分集 → 虚拟分集（取第一个有效源）
            for pl in player_list:
                pl_id = pl.get("id")
                episode_total = pl.get("episodeTotal")
                pl_name = self._safe_get(pl, "moviePlayerName", "默认源")

                if episode_total and int(episode_total) > 0:
                    pu = [
                        "第%d集$%d@%s@%s@virtual"
                        % (ep, ep, pl_id, video_id)
                        for ep in range(1, min(int(episode_total) + 1,
                                               NORMAL_EP_MAX))
                    ]
                    if pu:
                        play_urls.append("#".join(pu))
                        show.append(pl_name)
                    break

        return play_urls, show

    def playerContent(self, flag, id, vipFlags):
        """获取播放地址：id 格式 param@playerid@param2@param3
        param3=virtual → 短剧虚拟分集(episodeIndex)；否则 episodeId"""
        try:
            parts = str(id).split("@")
            if len(parts) < 4:
                self._log("player: 无效的播放ID格式: %s" % id)
                return self._empty_play()

            param, playerid, param2, param3 = parts[0], parts[1], parts[2], parts[3]

            if param3 == "virtual":
                payload = {
                    "episodeIndex": str(max(0, int(param) - 1)),
                    "id": int(param2),
                    "playerId": playerid,
                    "source": 0,
                    "typeId": SHORT_TYPE_ID,
                    "userId": self.userid,
                }
            else:
                payload = {
                    "episodeId": param2,
                    "id": param,
                    "playerId": playerid,
                    "source": 0,
                    "typeId": SHORT_TYPE_ID,
                    "userId": self.userid,
                }

            result = self._safe_request(
                "%s/api/v1/app/play/movieDetails" % self.host,
                payload=payload, method="POST")
            if not result:
                return self._empty_play()

            data = result.get("data", {}) or {}
            parse_url = data.get("url", "")
            playerid = data.get("playerId", playerid)

            if not parse_url:
                self._log("player: 未获取到播放URL")
                return self._empty_play()

            # 二次解析真实直链
            analysis = self._safe_request(
                "%s/api/v1/app/play/analysisMovieUrl?playerUrl=%s&playerId=%s"
                % (self.host, quote(str(parse_url), safe=""), playerid),
                method="GET")
            url = (analysis.get("data", "") if analysis else "") or ""

            self._log("player: 解析成功 url=%s" % str(url)[:160])
            return {
                "jx": "0",
                "parse": "0",
                "url": url,
                "header": {"User-Agent": UA_PLAY},
            }
        except Exception as e:
            self._log("playerContent FAIL: %s" % e)
            return self._empty_play()

    def _empty_play(self):
        return {"jx": "0", "parse": "0", "url": "", "header": {}}

    # ---------- 框架预留接口 ----------
    def isVideoFormat(self, url):
        return ".m3u8" in url or ".mp4" in url or url.startswith("http")

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self._log("destroy: 爬虫已销毁")
        try:
            self._cache.clear()
        except Exception:
            pass

    def close(self):
        self.destroy()

    def localProxy(self, param):
        return [200, "image/jpeg", b"", ""]


# ---------- 独立运行自测 ----------
if __name__ == "__main__":
    print("=" * 60)
    print("八戒影视爬虫 - 独立测试")
    print("=" * 60)

    sp = Spider()

    # 1. 测试初始化
    print("\n[测试1] 初始化...")
    try:
        sp.init()
        print("✅ 初始化成功")
        print("   host    = %s" % sp.host)
        print("   userid  = %s" % sp.userid)
        print("   token   = %s..." % (sp.headers.get("token") or "")[:24])
    except Exception as e:
        print("❌ 初始化失败: %s" % e)
        sys.exit(1)

    # 2. 测试首页分类
    print("\n[测试2] 获取首页分类...")
    try:
        result = sp.homeContent(None)
        classes = result.get("class", [])
        print("✅ 获取到 %d 个分类" % len(classes))
        if classes:
            print("   前5个分类: %s"
                  % [(c["type_name"], c["type_id"]) for c in classes[:5]])
    except Exception as e:
        print("❌ 获取分类失败: %s" % e)

    # 3. 测试推荐内容
    print("\n[测试3] 获取推荐内容...")
    try:
        result = sp.homeVideoContent()
        videos = result.get("list", [])
        print("✅ 获取到 %d 个推荐视频" % len(videos))
        if videos:
            print("   首个视频: %s" % videos[0].get("vod_name", "N/A"))
    except Exception as e:
        print("❌ 获取推荐失败: %s" % e)

    # 4. 测试分类内容
    print("\n[测试4] 获取分类内容 (tid=1)...")
    try:
        result = sp.categoryContent("1", "1", None, None)
        c_videos = result.get("list", [])
        print("✅ 获取到 %d 个视频" % len(c_videos))
        if c_videos:
            sample = c_videos[0]
            print("   示例: %s (%s)"
                  % (sample.get("vod_name", "N/A"),
                     sample.get("vod_year", "未知年份")))
    except Exception as e:
        print("❌ 获取分类内容失败: %s" % e)

    # 5. 测试搜索
    videos = []
    print("\n[测试5] 搜索 '电影'...")
    try:
        result = sp.searchContent("电影", False, "1")
        videos = result.get("list", [])
        print("✅ 找到 %d 个结果" % len(videos))
        if videos:
            print("   首个结果: %s" % videos[0].get("vod_name", "N/A"))
    except Exception as e:
        print("❌ 搜索失败: %s" % e)

    # 6. 测试详情（含简介前缀校验）
    if videos:
        print("\n[测试6] 获取视频详情...")
        try:
            video_id = videos[0].get("vod_id")
            if video_id:
                result = sp.detailContent([video_id])
                detail_list = result.get("list", [])
                if detail_list:
                    detail = detail_list[0]
                    print("✅ 获取详情成功")
                    print("   名称: %s" % detail.get("vod_name", "N/A"))
                    print("   播放源: %s" % detail.get("vod_play_from", "N/A"))
                    content = detail.get("vod_content", "")
                    ok = content.startswith(INTRO_PREFIX)
                    print("   简介前缀: %s"
                          % ("✅ 已添加" if ok else "❌ 缺失"))
                    print("   简介首行: %s"
                          % content.split("\n")[1][:50] if "\n" in content
                          else content[:50])
                    play_urls = detail.get("vod_play_url", "").split("$$$")
                    print("   播放列表数: %d" % len(play_urls))
                    if play_urls:
                        print("   第一个播放列表集数: %d"
                              % len(play_urls[0].split("#")))
                else:
                    print("❌ 获取详情返回空数据")
            else:
                print("❌ 视频ID为空")
        except Exception as e:
            print("❌ 获取详情失败: %s" % e)

    print("\n" + "=" * 60)
    print("所有测试完成！")
    print("=" * 60)
