# -*- coding: utf-8 -*-
"""Wangfei TVBox source with dynamic playback-line discovery .

网站结构:
  1. 筛选(filters): 分类/地区/年份/排序, 支持 MacCMS 查询参数与路径两种风格
  2. 播放线路: 详情页直取 + 线路页聚合, 多线路合并、去重, 单线兜底嗅探
  3. 详情信息: 导演/编剧/主演/首播/进度/集数时长等完整解析
  4. 简介统一添加 INTRO_PREFIX 前缀
"""

import ast
import base64
import html as html_module
import json
import re
import time
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    cffi_requests = None

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider:
        """Small fallback used by offline tests outside TVBox."""

        def __init__(self):
            pass

        def getProxyUrl(self):
            return ""


INTRO_PREFIX = "🍊小橙子为您介绍剧情👉请不要相信视频中的广告，以免上当受骗！"


class Spider(BaseSpider):
    DEFAULT_HOST = "https://www.wangfei.tv"
    DEFAULT_UA = (
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
    )
    CLASSES = [
        {"type_name": "电影", "type_id": "1"},
        {"type_name": "电视剧", "type_id": "2"},
        {"type_name": "综艺", "type_id": "3"},
        {"type_name": "动漫", "type_id": "4"},
        {"type_name": "纪录片", "type_id": "5"},
        {"type_name": "短剧", "type_id": "47"},
    ]

    # ================= 筛选配置 =================
    _SORTS = [
        {"n": "最新上架", "v": "time"},
        {"n": "最近更新", "v": "uptime"},
        {"n": "人气最高", "v": "hits"},
        {"n": "评分最高", "v": "score"},
    ]
    _YEARS = [{"n": "全部", "v": ""}] + [
        {"n": str(y), "v": str(y)} for y in range(2026, 1999, -1)
    ]
    _AREAS = [
        {"n": "全部", "v": ""},
        {"n": "中国大陆", "v": "中国大陆"},
        {"n": "中国香港", "v": "中国香港"},
        {"n": "中国台湾", "v": "中国台湾"},
        {"n": "美国", "v": "美国"},
        {"n": "韩国", "v": "韩国"},
        {"n": "日本", "v": "日本"},
        {"n": "英国", "v": "英国"},
        {"n": "法国", "v": "法国"},
        {"n": "德国", "v": "德国"},
        {"n": "泰国", "v": "泰国"},
        {"n": "印度", "v": "印度"},
        {"n": "其他", "v": "其他"},
    ]
    _CLASSES_MAP = {
        "1": ["全部", "动作", "喜剧", "爱情", "科幻", "恐怖", "剧情", "战争",
              "犯罪", "悬疑", "惊悚", "奇幻", "冒险", "动画", "武侠", "历史",
              "歌舞", "传记", "纪录", "运动", "西部", "灾难"],
        "2": ["全部", "剧情", "喜剧", "爱情", "犯罪", "悬疑", "家庭", "古装",
              "武侠", "历史", "战争", "科幻", "都市", "谍战", "军旅", "青春",
              "偶像", "奇幻", "农村", "神话"],
        "3": ["全部", "真人秀", "脱口秀", "访谈", "晚会", "音乐", "美食",
              "游戏", "情感", "亲子", "文化", "竞技", "选秀", "旅游"],
        "4": ["全部", "冒险", "搞笑", "奇幻", "热血", "恋爱", "科幻", "治愈",
              "机战", "运动", "校园", "日常", "悬疑", "神魔", "童话"],
        "5": ["全部", "历史", "自然", "科学", "人文", "军事", "探险", "美食",
              "犯罪", " wildlife", "社会", "传记"],
        "47": ["全部", "都市", "甜宠", "逆袭", "古装", "穿越", "玄幻", "爽文",
               "复仇", "言情", "战神", "萌宝"],
    }
    FILTERS = {}
    for _tid, _names in _CLASSES_MAP.items():
        FILTERS[_tid] = [
            {"key": "class", "name": "类型",
             "value": [{"n": x, "v": "" if x == "全部" else x} for x in _names]},
            {"key": "area", "name": "地区", "value": _AREAS},
            {"key": "year", "name": "年份", "value": _YEARS},
            {"key": "by", "name": "排序", "value": _SORTS},
        ]
    del _tid, _names

    MEDIA_EXTENSIONS = (
        ".m3u8", ".mp4", ".mkv", ".flv", ".ts", ".webm", ".avi", ".mov"
    )
    PLAY_PATH_RE = re.compile(
        r"/(?:vodplay|play)/[^\"'?#<>\s]+|/vod-play-[^\"'?#<>\s]+",
        re.I,
    )
    DETAIL_PATH_RE = re.compile(r"/voddetail/[^\"'?#<>\s]+\.html", re.I)
    CF_SIGNS = (
        "just a moment", "checking your browser",
        "attention required! | cloudflare",
    )
    CF_SOFT_SIGNS = ("challenge-platform", "cf-chl-", "cf_chl_")
    CONTENT_SIGNS = (
        "/voddetail/", "/vodplay/", "player_aaaa", ".m3u8",
        "module-poster", "module-info", "module-play-list",
        "anthology-list", "playlist",
    )
    AD_KEYWORDS = (
        "/ad/", "/ads/", "advert", "commercial", "promotion", "_ad_",
        "/gg/", "/gg", "-ad-", "adsegment", "adservice",
    )

    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self.host = self.DEFAULT_HOST
        self.ua = self.DEFAULT_UA
        self.cookie = ""
        self.timeout = 15
        self.use_cffi = False
        self.proxy_enabled = False
        self.session = requests.Session()
        self.headers = {}
        self._refresh_headers()

    def init(self, extend=""):
        config = self._parse_extend(extend)
        self.host = str(config.get("host") or self.DEFAULT_HOST).strip().rstrip("/")
        self.ua = str(config.get("ua") or self.DEFAULT_UA).strip()
        self.cookie = str(config.get("cookie") or "").strip()
        self.timeout = self._safe_int(config.get("timeout"), 15, 5, 60)
        self.use_cffi = self._as_bool(config.get("use_cffi"), False)
        self.proxy_enabled = self._as_bool(config.get("proxy"), False)
        self.session = requests.Session()
        self._refresh_headers()
        return True

    def getName(self):
        return "网飞TV"

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass

    @staticmethod
    def _safe_int(value, default, minimum=None, maximum=None):
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = default
        if minimum is not None:
            number = max(minimum, number)
        if maximum is not None:
            number = min(maximum, number)
        return number

    @staticmethod
    def _as_bool(value, default=False):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {
            "1", "true", "yes", "on", "y", "开启", "是"
        }

    def _parse_extend(self, extend):
        if isinstance(extend, dict):
            return dict(extend)
        if not extend:
            return {}
        text = str(extend).strip()
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else {}
        except Exception:
            pass
        try:
            parsed = parse_qs(text, keep_blank_values=True)
            return {key: values[-1] for key, values in parsed.items()}
        except Exception:
            return {}

    def _refresh_headers(self):
        self.headers = {
            "User-Agent": self.ua,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        if self.cookie:
            self.headers["Cookie"] = self.cookie
        self.session.headers.clear()
        self.session.headers.update(self.headers)

    def _request_headers(self, referer="", accept=""):
        headers = dict(self.headers)
        if referer:
            headers["Referer"] = referer
        if accept:
            headers["Accept"] = accept
        return headers

    @classmethod
    def _is_cloudflare_text(cls, text):
        lower = (text or "")[:100000].lower()
        if any(sign in lower for sign in cls.CF_SIGNS):
            return True
        if not any(sign in lower for sign in cls.CF_SOFT_SIGNS):
            return False
        return not any(sign in lower for sign in cls.CONTENT_SIGNS)

    def _blocked_response(self, response, text=""):
        if response is None:
            return True
        if getattr(response, "status_code", 0) in (401, 403, 429, 503):
            return True
        return self._is_cloudflare_text(text)

    def _request_raw(self, url, referer="", binary=False):
        if not url:
            return None
        target = self._absolute(url, referer or self.host)
        headers = self._request_headers(
            referer,
            "*/*" if binary else "text/html,application/xhtml+xml,*/*;q=0.8",
        )
        response = None
        text = ""
        for attempt in range(2):
            try:
                response = self.session.get(
                    target, headers=headers, timeout=self.timeout, allow_redirects=True
                )
                if not binary:
                    response.encoding = response.apparent_encoding or "utf-8"
                    text = response.text
                if not self._blocked_response(response, text):
                    return response
                break
            except Exception:
                response = None
                if attempt == 0:
                    time.sleep(0.25)

        if self.use_cffi and cffi_requests is not None:
            try:
                response = cffi_requests.get(
                    target,
                    headers=headers,
                    timeout=self.timeout,
                    allow_redirects=True,
                    impersonate="chrome131",
                )
                if not binary:
                    response.encoding = getattr(response, "apparent_encoding", None) or "utf-8"
                    text = response.text
                if not self._blocked_response(response, text):
                    return response
            except Exception:
                return None
        return None

    def _get_text(self, url, referer=""):
        response = self._request_raw(url, referer=referer, binary=False)
        if response is None:
            return ""
        try:
            text = response.text or ""
            return "" if self._is_cloudflare_text(text) else text
        except Exception:
            return ""

    @staticmethod
    def _absolute(url, base):
        if not url:
            return ""
        value = html_module.unescape(str(url).strip()).replace("\\/", "/")
        if value.startswith("//"):
            return (urlparse(base).scheme or "https") + ":" + value
        return urljoin(base, value)

    @staticmethod
    def _clean_text(value):
        if value is None:
            return ""
        text = html_module.unescape(str(value)).replace("\xa0", " ")
        text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip(" \t\r\n/|·")

    @staticmethod
    def _safe_label(value, fallback="线路"):
        label = Spider._clean_text(value) or fallback
        return label.replace("$", "_").replace("#", "_")[:80]

    @staticmethod
    def _attr_first(node, names):
        if node is None:
            return ""
        for name in names:
            value = node.get(name)
            if value and not str(value).lower().startswith("data:image"):
                return str(value).strip()
        return ""

    def _first_text(self, node, selectors):
        if node is None or not hasattr(node, "select_one"):
            return ""
        for selector in selectors:
            found = node.select_one(selector)
            if found:
                text = self._clean_text(found.get_text(" ", strip=True))
                if text:
                    return text
        return ""

    @staticmethod
    def _log(message):
        try:
            print(f"[网飞TV] {message}")
        except Exception:
            pass

    # ================= 首页 =================
    def homeContent(self, filter=False):
        return {"class": list(self.CLASSES), "filters": self.FILTERS}

    def homeVideoContent(self):
        source = self._get_text(self.host + "/", referer=self.host + "/")
        return {"list": self._parse_video_list(source, self.host)[:80]}

    def _parse_video_list(self, source, page_url=""):
        if not source:
            return []
        if BeautifulSoup is None:
            return self._parse_video_list_regex(source, page_url)

        soup = BeautifulSoup(source, "html.parser")
        records = {}
        order = []
        for anchor in soup.select('a[href*="/voddetail/"]'):
            href = anchor.get("href", "")
            if not self.DETAIL_PATH_RE.search(href):
                continue
            absolute = self._absolute(href, page_url or self.host)
            path_match = self.DETAIL_PATH_RE.search(urlparse(absolute).path)
            vod_id = path_match.group(0) if path_match else absolute
            image = anchor.find("img")
            title = (
                anchor.get("title")
                or self._attr_first(image, ("alt", "title"))
                or self._first_text(anchor, (
                    ".module-item-title", ".module-poster-item-title", ".video-name",
                    ".vod-name", ".title", "h3", "h4", "strong",
                ))
            )
            title = self._clean_text(title)
            if title.lower() in {"play", "detail", "more"}:
                title = ""
            pic = self._attr_first(
                image, ("data-original", "data-src", "data-lazy", "data-echo", "src")
            )
            pic = self._absolute(pic, page_url or self.host) if pic else ""

            card = anchor
            for _ in range(4):
                if card is None:
                    break
                classes = " ".join(card.get("class", [])) if hasattr(card, "get") else ""
                if re.search(r"item|card|list|module|poster|video", classes, re.I):
                    break
                card = card.parent
            remarks = self._first_text(card, (
                ".module-item-note", ".module-poster-item-info", ".pic-text",
                ".video-serial", ".remarks", ".remark", ".note", ".hdtag",
                ".text-right", ".module-item-caption", ".module-item-text",
            ))

            record = records.get(vod_id)
            if record is None:
                record = {
                    "vod_id": vod_id,
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_remarks": self._clean_text(remarks),
                }
                records[vod_id] = record
                order.append(vod_id)
            else:
                if not record["vod_name"] and title:
                    record["vod_name"] = title
                if not record["vod_pic"] and pic:
                    record["vod_pic"] = pic
                if not record["vod_remarks"] and remarks:
                    record["vod_remarks"] = self._clean_text(remarks)
        return [records[key] for key in order if records[key].get("vod_name")]

    def _parse_video_list_regex(self, source, page_url):
        records = []
        seen = set()
        pattern = re.compile(
            r"<a\b([^>]*href=[\"']([^\"']*/voddetail/[^\"']+\.html)[\"'][^>]*)>",
            re.I,
        )
        for match in pattern.finditer(source):
            href = match.group(2)
            path_match = self.DETAIL_PATH_RE.search(href)
            vod_id = path_match.group(0) if path_match else href
            if vod_id in seen:
                continue
            seen.add(vod_id)
            snippet = source[match.start():match.start() + 1600]
            title_match = re.search(r"(?:title|alt)=[\"']([^\"']+)[\"']", snippet, re.I)
            pic_match = re.search(
                r"(?:data-original|data-src|data-lazy|data-echo|src)=[\"']([^\"']+)[\"']",
                snippet,
                re.I,
            )
            title = self._clean_text(title_match.group(1) if title_match else "")
            if not title:
                continue
            records.append({
                "vod_id": vod_id,
                "vod_name": title,
                "vod_pic": self._absolute(pic_match.group(1), page_url or self.host)
                if pic_match else "",
                "vod_remarks": "",
            })
        return records

    def _parse_pagecount(self, source, current_page):
        if not source:
            return current_page
        values = [int(value) for value in re.findall(r"/page/(\d+)", source)]
        values += [int(value) for value in re.findall(r"[?&]page=(\d+)", source)]
        total_match = re.search(r"共\s*(\d+)\s*页", self._clean_text(source))
        if total_match:
            values.append(int(total_match.group(1)))
        return max(values + [current_page + 1])

    @staticmethod
    def _is_homepage_source(source):
        canonical = re.search(
            r'<link\b[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)',
            source or "",
            re.I,
        )
        if not canonical or urlparse(html_module.unescape(canonical.group(1))).path.rstrip("/"):
            return False
        title = re.search(r"<title\b[^>]*>(.*?)</title>", source or "", re.I | re.S)
        title_text = Spider._clean_text(title.group(1)) if title else ""
        return not re.search(r"搜索|search", title_text, re.I)

    def _fetch_first_list(self, paths, reject_home=False):
        last_source = ""
        for path in paths:
            url = self._absolute(path, self.host)
            source = self._get_text(url, referer=self.host + "/")
            if source:
                last_source = source
                if reject_home and self._is_homepage_source(source):
                    continue
                videos = self._parse_video_list(source, url)
                if videos:
                    return videos, source
        return [], last_source

    # ================= 分类 + 筛选 =================
    def _category_paths(self, tid, page, extend):
        """生成候选列表页地址: 查询参数风格 + MacCMS 路径风格."""
        cls = str(extend.get("class") or "").strip()
        area = str(extend.get("area") or "").strip()
        year = str(extend.get("year") or "").strip()
        by = str(extend.get("by") or "").strip()

        query = {"page": page}
        if cls:
            query["class"] = cls
        if area:
            query["area"] = area
        if year:
            query["year"] = year
        if by:
            query["by"] = by
        query_string = "&".join(
            f"{key}={quote(str(value), safe='')}"
            for key, value in query.items()
            if value != ""
        )

        paths = []
        if query_string:
            paths.append(f"/vodshow/id/{tid}.html?{query_string}")
        # 路径风格: /vodshow/class-area-year-by-tid-page.html (MacCMS 伪静态)
        parts = [cls, area, year, by]
        if any(parts):
            joined = "-".join(part for part in parts)
            paths.append(f"/vodshow/{joined}-{tid}-{page}.html")
        if page > 1:
            paths.append(f"/vodshow/id/{tid}/page/{page}.html")
        paths.append(f"/vodshow/id/{tid}.html")
        paths.append(f"/vodtype/{tid}.html" + (f"?{query_string}" if query_string else ""))
        return paths

    def categoryContent(self, tid, pg, filter=False, extend=None):
        page = self._safe_int(pg, 1, 1)
        tid = str(tid or "1")
        if isinstance(extend, str):
            extend = self._parse_extend(extend)
        extend = extend or {}
        # 清理空筛选值
        extend = {
            key: value for key, value in extend.items()
            if value not in ("", None, "全部")
        }
        paths = self._category_paths(tid, page, extend)
        videos, source = self._fetch_first_list(paths)
        pagecount = self._parse_pagecount(source, page) if videos else page
        return {
            "list": videos,
            "page": page,
            "pagecount": pagecount,
            "limit": len(videos),
            "total": pagecount * max(len(videos), 1),
        }

    # ================= 搜索 =================
    def searchContent(self, key, quick, pg="1"):
        page = self._safe_int(pg, 1, 1)
        keyword = quote(unquote(str(key or "").strip()), safe="")
        if not keyword:
            return {"list": [], "page": page, "pagecount": page, "limit": 0, "total": 0}
        current = f"/vod/search?wd={keyword}"
        if page > 1:
            current += f"&page={page}"
        rewritten = f"/vodsearch/wd/{keyword}.html"
        query_style = f"/vodsearch/-------------.html?wd={keyword}&page={page}"
        paths = [current, rewritten, query_style] if page == 1 else [current, query_style, rewritten]
        videos, source = self._fetch_first_list(paths, reject_home=True)
        pagecount = self._parse_pagecount(source, page) if videos else page
        return {
            "list": videos,
            "page": page,
            "pagecount": pagecount,
            "limit": len(videos),
            "total": pagecount * max(len(videos), 1),
        }

    # ================= 详情 =================
    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        raw_id = str(raw_id or "").strip()
        if not raw_id:
            return {"list": []}
        if raw_id.isdigit():
            raw_id = f"/voddetail/{raw_id}.html"
        detail_url = self._absolute(raw_id, self.host)
        source = self._get_text(detail_url, referer=self.host + "/")
        metadata = self._parse_detail_metadata(source, detail_url)

        lines = []
        used_labels = set()

        def _merge(groups):
            for label, episodes in groups:
                if not episodes:
                    continue
                unique = label
                suffix = 2
                while unique in used_labels:
                    unique = f"{label}-{suffix}"
                    suffix += 1
                used_labels.add(unique)
                lines.append((unique, episodes))

        # 1) 详情页内嵌的选集列表 (部分模板直接在详情页给出全部线路/剧集)
        try:
            embedded = self._parse_provider_detail("内嵌线路", detail_url, detail_url)
            # 详情页本身解析会把自己当作播放页, 需要单独提取
            embedded = self._embedded_groups(source, detail_url)
            _merge(embedded)
        except Exception as exc:
            self._log(f"embedded line parse failed: {exc}")

        # 2) 聚合所有线路入口页 (不再只取第一条成功的线路)
        line_links = self._extract_line_links(source, detail_url)
        for main_label, provider_url in line_links:
            try:
                groups = self._parse_provider_detail(main_label, provider_url, detail_url)
            except Exception:
                groups = []
            _merge(groups)
            if len(lines) >= 20:
                break

        if not lines and source:
            self._log("detail found but no provider line could be parsed")

        metadata.update({
            "vod_id": raw_id,
            "vod_play_from": "$$$".join(item[0] for item in lines),
            "vod_play_url": "$$$".join(item[1] for item in lines),
        })
        return {"list": [metadata]}

    def _embedded_groups(self, source, detail_url):
        """详情页可能直接带有 module-play-list 选集块, 按块分组."""
        if not source:
            return []
        block_re = re.compile(
            r"module-play-list|anthology-list|stui-content__playlist|"
            r"myui-content__list|episode-list",
            re.I,
        )
        has_play = self.PLAY_PATH_RE.search(source or "")
        if not has_play:
            return []
        if BeautifulSoup is None:
            episodes = self._provider_episodes_regex(source, detail_url)
            return [("线路1", "#".join(episodes))] if episodes else []

        soup = BeautifulSoup(source, "html.parser")
        blocks = []
        seen = set()
        for node in soup.find_all(class_=block_re):
            key = id(node)
            if key not in seen:
                seen.add(key)
                blocks.append(node)
        if not blocks:
            anchors = [
                a for a in soup.find_all("a", href=True)
                if self.PLAY_PATH_RE.search(a.get("href", ""))
            ]
            if not anchors:
                return []
            episodes = self._episodes_from_anchors(anchors, detail_url)
            return [("线路1", "#".join(episodes))] if episodes else []

        tab_names = self._extract_provider_tab_names(soup)
        groups = []
        for index, block in enumerate(blocks):
            anchors = [
                a for a in block.find_all("a", href=True)
                if self.PLAY_PATH_RE.search(a.get("href", ""))
            ]
            episodes = self._episodes_from_anchors(anchors, detail_url)
            if not episodes:
                continue
            sub = tab_names[index] if index < len(tab_names) else f"源{index + 1}"
            groups.append((self._safe_label(sub), "#".join(episodes)))
        if not groups:
            return []
        if len(groups) == 1:
            groups[0] = ("线路1", groups[0][1])
        return groups

    def _parse_detail_metadata(self, source, detail_url):
        result = {
            "vod_name": "未知影片",
            "vod_pic": "",
            "type_name": "",
            "vod_year": "",
            "vod_area": "",
            "vod_remarks": "",
            "vod_actor": "",
            "vod_director": "",
            "vod_content": "",
        }
        if not source:
            id_match = re.search(r"/voddetail/([^/.]+)", detail_url)
            result["vod_name"] = "影片" + (id_match.group(1) if id_match else "")
            result["vod_content"] = INTRO_PREFIX
            return result

        if BeautifulSoup is None:
            title_match = re.search(r"<h1\b[^>]*>(.*?)</h1>", source, re.I | re.S)
            if title_match:
                result["vod_name"] = self._clean_text(title_match.group(1))
            pic_match = re.search(
                r"<meta\b[^>]*(?:property|name)=[\"']og:image[\"'][^>]*content=[\"']([^\"']+)",
                source,
                re.I,
            )
            if pic_match:
                result["vod_pic"] = self._absolute(pic_match.group(1), detail_url)
            intro_match = re.search(
                r"<meta\b[^>]*name=[\"']description[\"'][^>]*content=[\"']([^\"']*)",
                source, re.I,
            )
            if intro_match:
                result["vod_content"] = INTRO_PREFIX + "\n" + self._clean_text(intro_match.group(1))
            else:
                result["vod_content"] = INTRO_PREFIX
            return result

        soup = BeautifulSoup(source, "html.parser")
        title_node = soup.select_one(
            ".module-info-heading h1, .module-info-heading h2, .detail-title h1, "
            ".vod-detail h1, h1"
        )
        if title_node:
            result["vod_name"] = self._clean_text(title_node.get_text(" ", strip=True))
        else:
            og_title = soup.select_one('meta[property="og:title"]')
            if og_title and og_title.get("content"):
                result["vod_name"] = self._clean_text(og_title.get("content"))
        # 去掉标题里的年份后缀 "伟大的长征 (2026)"
        result["vod_name"] = re.sub(r"\s*[（(]\d{4}[）)]\s*$", "", result["vod_name"]).strip()

        pic_node = soup.select_one('meta[property="og:image"]')
        pic = pic_node.get("content", "") if pic_node else ""
        if not pic:
            image = soup.select_one(
                ".module-info-poster img, .detail-pic img, .vod-detail img, "
                ".module-item-pic img, img.poster, img.cover"
            )
            pic = self._attr_first(
                image, ("data-original", "data-src", "data-lazy", "data-echo", "src")
            )
        result["vod_pic"] = self._absolute(pic, detail_url) if pic else ""

        labels = self._extract_detail_labels(soup)
        result["type_name"] = labels.get("类型", "") or labels.get("分类", "")
        result["vod_year"] = labels.get("年份", "") or labels.get("年代", "") \
            or labels.get("首播", "")
        result["vod_area"] = labels.get("地区", "") or labels.get("国家", "")
        result["vod_actor"] = labels.get("主演", "") or labels.get("演员", "")
        result["vod_director"] = labels.get("导演", "")

        # 编剧: 追加到导演信息中展示
        if labels.get("编剧"):
            result["vod_director"] = (
                (result["vod_director"] + " / 编剧: " + labels["编剧"])
                if result["vod_director"] else "编剧: " + labels["编剧"]
            )

        # 备注: 首播 / 进度 / 状态 / 集数时长
        remarks_parts = []
        for key in ("首播", "进度", "状态", "更新", "上映", "集数", "时长"):
            value = labels.get(key)
            if value and value not in remarks_parts:
                remarks_parts.append(value)
        if not remarks_parts:
            remarks_parts.append(
                labels.get("原名", "") or labels.get("别名", "")
            )
        result["vod_remarks"] = " · ".join(part for part in remarks_parts if part)

        content = self._first_text(soup, (
            ".module-info-introduction-content", ".module-info-introduction",
            ".vod_content", ".detail-content", ".detail-con", ".content-desc",
            "[class*='introduction']", "[class*='summary']",
        ))
        if not content:
            meta_desc = soup.select_one('meta[name="description"]')
            if meta_desc:
                content = self._clean_text(meta_desc.get("content", ""))
        # 简介统一加前缀
        result["vod_content"] = (INTRO_PREFIX + "\n" + content) if content else INTRO_PREFIX
        return result

    def _extract_detail_labels(self, soup):
        labels = {}
        wanted = {
            "类型", "分类", "年份", "年代", "地区", "国家", "主演", "演员",
            "导演", "编剧", "语言", "首播", "上映", "进度", "更新", "状态",
            "原名", "别名", "集数", "时长", "单集",
        }
        # 优先解析结构化的 info 条目 (span/a)
        for node in soup.select(
            ".module-info-item, .module-info-item-content, .info span, "
            ".detail-info span, .slade-info span, .video-info-item"
        ):
            text = self._clean_text(node.get_text(" ", strip=True))
            match = re.match(r"^([^：:]{1,8})[：:]\s*(.+)$", text)
            if match and match.group(1).strip() in wanted:
                key = match.group(1).strip()
                value = self._clean_text(match.group(2))
                if value and key not in labels:
                    labels[key] = value
        if len(labels) >= 4:
            # 尝试补齐缺失项 (label 与 value 分离的节点结构)
            for node in soup.select(
                ".module-info-item, .video-info-item, .detail-info span"
            ):
                text = self._clean_text(node.get_text(" ", strip=True))
                match = re.match(r"^([^：:]{1,8})[：:]\s*(.*)$", text)
                if not match:
                    continue
                key = match.group(1).strip()
                value = match.group(2)
                if key in wanted and key not in labels and not value:
                    sibling = node.find_next_sibling()
                    if sibling is not None:
                        value = self._clean_text(sibling.get_text(" ", strip=True))
                        if value and key not in labels:
                            labels[key] = value
        # 兜底: 全文扫描 "主演：" 形式
        for text in soup.stripped_strings:
            cleaned = self._clean_text(text)
            match = re.match(r"^([^：:]{1,8})[：:]\s*(.+)$", cleaned)
            if match and match.group(1).strip() in wanted:
                key = match.group(1).strip()
                value = self._clean_text(match.group(2))
                if value and key not in labels:
                    labels[key] = value
        return labels

    def _extract_line_links(self, source, detail_url):
        if not source:
            return []
        if BeautifulSoup is None:
            return self._extract_line_links_regex(source, detail_url)

        soup = BeautifulSoup(source, "html.parser")
        candidates = []
        line_pattern = re.compile(r"(?:线路|路线|在线|云播|播放源)\s*\d*")
        for anchor in soup.find_all("a", href=True):
            text = self._clean_text(anchor.get_text(" ", strip=True))
            href = anchor.get("href", "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue
            classes = " ".join(anchor.get("class", []))
            if not line_pattern.search(text) and not re.search(r"play|source|line|route", classes, re.I):
                continue
            absolute = self._absolute(href, detail_url)
            if absolute != detail_url:
                candidates.append((self._safe_label(text), absolute))

        if not candidates:
            heading = soup.find(string=re.compile(r"观看方式|在线观看|播放线路"))
            container = heading.parent if heading else None
            for _ in range(4):
                if container is None:
                    break
                anchors = container.find_all("a", href=True)
                for anchor in anchors:
                    href = anchor.get("href", "")
                    if href and not href.startswith(("#", "javascript:")):
                        candidates.append((
                            self._safe_label(anchor.get_text(" ", strip=True)),
                            self._absolute(href, detail_url),
                        ))
                if candidates:
                    break
                container = container.parent

        result = []
        seen = set()
        generic = {"在线观看", "播放", "观看方式", "线路"}
        for index, (label, url) in enumerate(candidates, 1):
            if url in seen:
                continue
            seen.add(url)
            if label in generic:
                label = "线路" + str(index)
            result.append((label, url))
        return result[:30]

    def _extract_line_links_regex(self, source, detail_url):
        result = []
        seen = set()
        line_pattern = re.compile(r"(?:线路|路线|在线|云播|播放源)\s*\d*")
        for match in re.finditer(
            r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
            source,
            re.I | re.S,
        ):
            label = self._clean_text(match.group(2))
            if not line_pattern.search(label):
                continue
            url = self._absolute(match.group(1), detail_url)
            if url in seen:
                continue
            seen.add(url)
            result.append((self._safe_label(label, "线路" + str(len(result) + 1)), url))
        return result

    def _parse_provider_detail(self, main_label, provider_url, detail_url):
        if self.PLAY_PATH_RE.search(urlparse(provider_url).path):
            return [(main_label, f"播放${provider_url}")]
        source = self._get_text(provider_url, referer=detail_url)
        if not source:
            return []
        if re.search(r"module-play-list", source, re.I):
            groups = self._provider_groups_regex(source, provider_url, main_label)
            if groups:
                return groups
        if BeautifulSoup is None:
            return self._provider_groups_regex(source, provider_url, main_label)

        soup = BeautifulSoup(source, "html.parser")
        episode_anchors = [
            anchor for anchor in soup.find_all("a", href=True)
            if self.PLAY_PATH_RE.search(anchor.get("href", ""))
        ]
        if not episode_anchors:
            return []

        playlist_anchors = [
            anchor for anchor in episode_anchors
            if not re.search(
                r"(?:^|\s)(?:main-btn|play-btn(?:-[\w-]+)?)\b",
                " ".join(anchor.get("class", [])), re.I,
            )
        ]
        episode_anchors = playlist_anchors or episode_anchors

        block_re = re.compile(
            r"module-play-list|anthology-list|playlist|play-list|"
            r"stui-content__playlist|myui-content__list|numList|episode-list",
            re.I,
        )
        block_nodes = []
        block_keys = set()
        for anchor in episode_anchors:
            block = anchor.find_parent(class_=block_re)
            if block is None:
                block = anchor.find_parent(["ul", "ol", "div"])
            key = id(block) if block is not None else 0
            if key not in block_keys:
                block_keys.add(key)
                block_nodes.append(block)

        if len(block_nodes) <= 1:
            episodes = self._episodes_from_anchors(episode_anchors, provider_url)
            return [(main_label, "#".join(episodes))] if episodes else []

        groups = []
        tab_names = self._extract_provider_tab_names(soup)
        for index, block in enumerate(block_nodes):
            anchors = block.find_all("a", href=True) if block is not None else episode_anchors
            anchors = [
                anchor for anchor in anchors
                if self.PLAY_PATH_RE.search(anchor.get("href", ""))
            ]
            episodes = self._episodes_from_anchors(anchors, provider_url)
            if not episodes:
                continue
            sub_name = tab_names[index] if index < len(tab_names) else "源" + str(index + 1)
            groups.append((self._safe_label(f"{main_label}-{sub_name}"), "#".join(episodes)))
        return groups

    def _extract_provider_tab_names(self, soup):
        selectors = (
            ".module-tab-item", ".anthology-tab a", ".anthology-tab li",
            ".play_source_tab li", ".nav-tabs li", "[data-from]",
            "[data-dropdown-value]", ".source-tab", ".playlist-tab",
        )
        names = []
        seen = set()
        for selector in selectors:
            for node in soup.select(selector):
                text = self._clean_text(node.get_text(" ", strip=True))
                if not text or len(text) > 50 or re.fullmatch(r"第?\d+[集期]?", text):
                    continue
                text = re.sub(r"\s+\d+$", "", text)
                if text not in seen:
                    seen.add(text)
                    names.append(self._safe_label(text))
            if names:
                break
        return names

    def _episodes_from_anchors(self, anchors, page_url):
        episodes = []
        seen = set()
        for anchor in anchors:
            href = anchor.get("href", "")
            if not self.PLAY_PATH_RE.search(href):
                continue
            absolute = self._absolute(href, page_url)
            if absolute in seen:
                continue
            seen.add(absolute)
            name = self._clean_text(
                anchor.get_text(" ", strip=True) or anchor.get("data-title")
                or anchor.get("title")
            )
            if not name:
                path_match = re.search(r"-(\d+)\.html", urlparse(absolute).path)
                name = ("第" + path_match.group(1) + "集") if path_match else "播放"
            name = re.sub(r"第0+(\d+)([集期])", lambda m: "第" + str(int(m.group(1))) + m.group(2), name)
            episodes.append(f"{self._safe_label(name, '播放')}${absolute}")
        return episodes

    def _provider_groups_regex(self, source, page_url, main_label):
        panel_re = re.compile(
            r'<div\b(?=[^>]*class=["\'][^"\']*\bmodule-list\b[^"\']*["\'])'
            r'(?=[^>]*\bid=["\']panel\d+["\'])[^>]*>',
            re.I,
        )
        panels = list(panel_re.finditer(source or ""))
        if panels:
            tab_re = re.compile(
                r'<div\b(?=[^>]*class=["\'][^"\']*\bmodule-tab-item\b[^"\']*["\'])'
                r'(?=[^>]*data-dropdown-value=["\']([^"\']+))[^>]*>',
                re.I,
            )
            names = [
                self._safe_label(self._clean_text(match.group(1)))
                for match in tab_re.finditer(source)
            ]
            groups = []
            for index, panel in enumerate(panels):
                end = panels[index + 1].start() if index + 1 < len(panels) else len(source)
                episodes = self._provider_episodes_regex(source[panel.start():end], page_url)
                if not episodes:
                    continue
                sub_name = names[index] if index < len(names) else "源" + str(index + 1)
                label = self._safe_label(f"{main_label}-{sub_name}")
                groups.append((label, "#".join(episodes)))
            if groups:
                return groups

        episodes = self._provider_episodes_regex(source, page_url)
        return [(main_label, "#".join(episodes))] if episodes else []

    def _provider_episodes_regex(self, source, page_url):
        episodes = []
        seen = set()
        for match in re.finditer(
            r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
            source,
            re.I | re.S,
        ):
            if not self.PLAY_PATH_RE.search(match.group(1)):
                continue
            absolute = self._absolute(match.group(1), page_url)
            if absolute in seen:
                continue
            seen.add(absolute)
            name = self._clean_text(match.group(2))
            name = re.sub(r"第0+(\d+)([集期])", lambda m: "第" + str(int(m.group(1))) + m.group(2), name)
            name = self._safe_label(name, "播放")
            episodes.append(f"{name}${absolute}")
        return episodes

    # ================= 播放 =================
    def playerContent(self, flag, id, vipFlags=None):

        play_url = self._absolute(str(id or ""), self.host)
        headers = self._play_headers(play_url)
        if self._is_media_url(play_url):
            return self._direct_result(play_url, headers)

        source = self._get_text(play_url, referer=self._origin_root(play_url))
        if not source:
            return {"parse": 1, "jx": 0, "url": play_url, "header": headers}

        config_urls = []
        for variable in ("player_aaaa", "player_data", "MacPlayer"):
            config = self._extract_js_object(source, variable)
            if not config:
                continue
            raw_url = self._find_url_in_config(config)
            decoded = self._decode_player_url(raw_url, config.get("encrypt"), play_url)
            if decoded:
                config_urls.append(decoded)
                if self._is_media_url(decoded):
                    return self._direct_result(decoded, self._play_headers(play_url))

        direct = self._extract_direct_media(source, play_url)
        if direct:
            return self._direct_result(direct, self._play_headers(play_url))

        iframe = self._extract_iframe(source, play_url)
        if iframe:
            if self._is_media_url(iframe):
                return self._direct_result(iframe, self._play_headers(play_url))
            return {"parse": 1, "jx": 0, "url": iframe, "header": headers}

        for candidate in config_urls:
            if candidate.startswith(("http://", "https://")):
                return {"parse": 1, "jx": 0, "url": candidate, "header": headers}
        return {"parse": 1, "jx": 0, "url": play_url, "header": headers}

    def _play_headers(self, referer):
        headers = {"User-Agent": self.ua, "Referer": referer}
        if self.cookie:
            headers["Cookie"] = self.cookie
        return headers

    def _direct_result(self, media_url, headers):
        final_url = media_url
        if self.proxy_enabled and ".m3u8" in media_url.lower():
            proxied = self._proxy_url(media_url, headers.get("Referer", ""), "m3u8")
            if proxied:
                final_url = proxied
                headers = {}
        return {"parse": 0, "jx": 0, "url": final_url, "header": headers}

    @classmethod
    def _is_media_url(cls, value):
        if not value:
            return False
        lower = html_module.unescape(str(value)).lower()
        return lower.startswith(("http://", "https://")) and any(
            extension in lower for extension in cls.MEDIA_EXTENSIONS
        )

    def _extract_js_object(self, source, variable):
        match = re.search(
            rf"(?:var\s+|let\s+|const\s+|window\.)?{re.escape(variable)}\s*=\s*",
            source,
            re.I,
        )
        if not match:
            return {}
        start = source.find("{", match.end())
        if start < 0:
            return {}
        depth = 0
        quote_char = ""
        escaped = False
        for index in range(start, min(len(source), start + 200000)):
            char = source[index]
            if quote_char:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote_char:
                    quote_char = ""
                continue
            if char in ("'", '"'):
                quote_char = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    text = source[start:index + 1]
                    try:
                        value = json.loads(text)
                        return value if isinstance(value, dict) else {}
                    except Exception:
                        try:
                            value = ast.literal_eval(text)
                            return value if isinstance(value, dict) else {}
                        except Exception:
                            return {}
        return {}

    def _find_url_in_config(self, config):
        for key in ("url", "play_url", "playUrl", "src", "m3u8"):
            value = config.get(key)
            if value:
                return str(value)
        for value in config.values():
            if isinstance(value, dict):
                nested = self._find_url_in_config(value)
                if nested:
                    return nested
        return ""

    def _decode_player_url(self, raw_url, encrypt, page_url):
        if raw_url is None:
            return ""
        raw = html_module.unescape(str(raw_url)).replace("\\/", "/").strip()
        candidates = [raw]
        try:
            mode = int(encrypt or 0)
        except (TypeError, ValueError):
            mode = 0
        if mode == 1:
            candidates.insert(0, unquote(raw))
        elif mode == 2:
            decoded = self._decode_base64(raw)
            if decoded:
                candidates.insert(0, unquote(decoded))
        else:
            unquoted = unquote(raw)
            if unquoted != raw:
                candidates.insert(0, unquoted)
            decoded = self._decode_base64(raw)
            if decoded:
                candidates.insert(0, unquote(decoded))
        for candidate in candidates:
            candidate = html_module.unescape(candidate).replace("\\/", "/").strip()
            if candidate.startswith(("http://", "https://", "//", "/")):
                return self._absolute(candidate, page_url)
        return ""

    @staticmethod
    def _decode_base64(value):
        text = str(value).strip()
        if not text or not re.fullmatch(r"[A-Za-z0-9_+/=-]+", text):
            return ""
        try:
            padded = text + "=" * (-len(text) % 4)
            return base64.urlsafe_b64decode(padded.encode()).decode("utf-8", "ignore")
        except Exception:
            return ""

    def _extract_direct_media(self, source, page_url):
        text = html_module.unescape(source).replace("\\/", "/")
        text = re.sub(
            r"\\u([0-9a-fA-F]{4})",
            lambda match: chr(int(match.group(1), 16)),
            text,
        )
        patterns = (
            r"https?://[^\"'<>\s]+?\.m3u8(?:\?[^\"'<>\s]*)?",
            r"https?://[^\"'<>\s]+?\.(?:mp4|flv|mkv|webm)(?:\?[^\"'<>\s]*)?",
            r"(?:src|url)\s*[:=]\s*[\"']([^\"']+?\.(?:m3u8|mp4|flv|mkv|webm)(?:\?[\"']*)?)[\"']",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                value = match.group(1) if match.lastindex else match.group(0)
                return self._absolute(value, page_url)
        return ""

    def _extract_iframe(self, source, page_url):
        match = re.search(r"<iframe\b[^>]*src=[\"']([^\"']+)[\"']", source, re.I)
        return self._absolute(match.group(1), page_url) if match else ""

    @staticmethod
    def _origin_root(url):
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else url

    # ================= 代理 =================
    def _proxy_url(self, real_url, referer, mode):
        try:
            base = self.getProxyUrl()
        except Exception:
            base = ""
        if not base:
            return ""
        separator = "&" if "?" in base else "?"
        params = {
            "mode": mode,
            "url": self._b64_encode(real_url),
            "ref": self._b64_encode(referer or real_url),
        }
        query = "&".join(f"{key}={quote(value, safe='')}" for key, value in params.items())
        return base + separator + query

    @staticmethod
    def _b64_encode(value):
        return base64.urlsafe_b64encode(str(value).encode()).decode().rstrip("=")

    @staticmethod
    def _b64_decode(value):
        try:
            text = str(value or "")
            return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)).decode()
        except Exception:
            return ""

    def localProxy(self, param):
        params = param or {}
        mode = self._param_value(params, "mode") or "segment"
        real_url = self._b64_decode(self._param_value(params, "url"))
        referer = self._b64_decode(self._param_value(params, "ref")) or real_url
        if not real_url:
            return [400, "text/plain", {}, b"missing url"]
        response = self._request_raw(real_url, referer=referer, binary=True)
        if response is None:
            return [502, "text/plain", {}, b"upstream request failed"]
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        if mode == "m3u8" or ".m3u8" in real_url.lower() or "mpegurl" in content_type.lower():
            try:
                response.encoding = response.apparent_encoding or "utf-8"
                playlist = response.text
            except Exception:
                playlist = response.content.decode("utf-8", "ignore")
            rewritten = self._rewrite_m3u8(playlist, real_url)
            return [200, "application/vnd.apple.mpegurl", {}, rewritten]
        headers = {}
        if response.headers.get("Content-Length"):
            headers["Content-Length"] = response.headers.get("Content-Length")
        return [response.status_code, content_type, headers, response.content]

    @staticmethod
    def _param_value(params, key):
        value = params.get(key, "") if isinstance(params, dict) else ""
        if isinstance(value, (list, tuple)):
            return value[-1] if value else ""
        return value

    def _rewrite_m3u8(self, playlist, playlist_url):
        output = []
        for raw_line in (playlist or "").splitlines():
            line = raw_line.strip()
            if not line:
                output.append(raw_line)
                continue
            if not line.startswith("#"):
                absolute = self._absolute(line, playlist_url)
                if self._is_ad_url(absolute):
                    while output and output[-1].strip().startswith(("#EXTINF", "#EXT-X-BYTERANGE")):
                        output.pop()
                    continue
                mode = "m3u8" if ".m3u8" in urlparse(absolute).path.lower() else "segment"
                output.append(self._proxy_url(absolute, playlist_url, mode) or absolute)
                continue
            if "URI=" in line.upper():
                line = re.sub(
                    r"URI=([\"'])(.*?)\1",
                    lambda match: self._rewrite_m3u8_uri(match, playlist_url, line),
                    line,
                    flags=re.I,
                )
            output.append(line)
        return "\n".join(output) + "\n"

    def _rewrite_m3u8_uri(self, match, playlist_url, whole_line):
        absolute = self._absolute(match.group(2), playlist_url)
        upper = whole_line.upper()
        if "#EXT-X-KEY" in upper:
            mode = "key"
        elif ".m3u8" in urlparse(absolute).path.lower():
            mode = "m3u8"
        else:
            mode = "segment"
        proxied = self._proxy_url(absolute, playlist_url, mode) or absolute
        return f'URI="{proxied}"'

    def _is_ad_url(self, url):
        lower = unquote(str(url or "")).lower()
        return any(keyword in lower for keyword in self.AD_KEYWORDS)

    def isVideoFormat(self, url):
        return self._is_media_url(url)

    def manualVideoCheck(self):
        return False


if __name__ == "__main__":
    spider = Spider()
    spider.init("")
    print(json.dumps(spider.homeContent(True), ensure_ascii=False, indent=2))
