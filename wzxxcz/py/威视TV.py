# coding=utf-8
import base64
import json
import re
import requests
import sys
import time
from functools import wraps
from urllib.parse import quote, unquote, urljoin, urlparse

from lxml import etree

sys.path.append("..")
from base.spider import Spider as BaseSpider


LOG_TAG = "[威视TV_DEBUG]"

# 简介前缀（统一风格）
INTRO_PREFIX = "🍊小橙子为您介绍剧情👉请不要相信视频中的广告，以免上当受骗！"

# 线路优先级与别名（统一风格）
_LINE_PRIORITY = ["vip", "1080zyk", "wztv", "bfzym3u8", "dyttm3u8",
                  "ffm3u8", "lzm3u8", "modum3u8", "jsm3u8", "mtm3u8"]
_LINE_ALIAS = {
    "vip": "VIP线路", "modum3u8": "魔都M3U8", "jsm3u8": "极速M3U8",
    "mtm3u8": "茅台M3U8", "1080zyk": "1080资源", "lzm3u8": "量子M3U8",
    "bfzym3u8": "暴风资源", "dyttm3u8": "电影天堂", "ffm3u8": "非凡M3U8",
    "wztv": "王者TV",
}


def trace_interface(function):
    @wraps(function)
    def wrapper(self, *args, **kwargs):
        interface = function.__name__
        self._debug(
            "接口开始",
            interface=interface,
            arguments=self._summarize_arguments(interface, args, kwargs),
        )
        try:
            result = function(self, *args, **kwargs)
        except Exception as error:
            self._debug(
                "接口异常",
                interface=interface,
                error_type=type(error).__name__,
                error=str(error),
            )
            raise
        self._debug("接口完成", interface=interface, **self._summarize_result(interface, result))
        return result

    return wrapper


class Spider(BaseSpider):
    DEFAULT_HOST = "https://weishitv.xyz"
    UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
    CLASSES = [
        {"type_id": "1", "type_name": "电影"},
        {"type_id": "2", "type_name": "剧集"},
        {"type_id": "3", "type_name": "综艺"},
        {"type_id": "4", "type_name": "动漫"},
    ]

    # 筛选器（参照豆花电影风格）
    _SORTS = [
        {"n": "最新", "v": "time"},
        {"n": "人气", "v": "hits"},
        {"n": "评分", "v": "score"},
    ]
    _YEARS = [{"n": "全部", "v": ""}] + \
             [{"n": str(y), "v": str(y)} for y in range(2026, 1999, -1)]
    _AREAS = [
        {"n": "全部", "v": ""},
        {"n": "中国大陆", "v": "中国大陆"}, {"n": "美国", "v": "美国"},
        {"n": "日本", "v": "日本"}, {"n": "英国", "v": "英国"},
        {"n": "中国香港", "v": "中国香港"}, {"n": "法国", "v": "法国"},
        {"n": "韩国", "v": "韩国"}, {"n": "加拿大", "v": "加拿大"},
        {"n": "印度", "v": "印度"}, {"n": "德国", "v": "德国"},
        {"n": "意大利", "v": "意大利"}, {"n": "中国台湾", "v": "中国台湾"},
    ]
    _FILTERS_MAP = {
        "1": ["全部", "剧情", "喜剧", "动作", "爱情", "惊悚", "犯罪", "恐怖",
              "悬疑", "冒险", "奇幻", "科幻", "院线", "家庭", "历史", "战争",
              "纪录片", "古装", "音乐", "动画", "传记", "武侠", "运动", "西部", "短片"],
        "2": ["全部", "剧情", "喜剧", "爱情", "犯罪", "悬疑", "家庭", "古装",
              "惊悚", "动作", "奇幻", "科幻", "都市", "历史", "战争", "冒险",
              "武侠", "恐怖", "青春", "传记", "谍战", "情感", "纪录", "军旅", "时装"],
        "3": ["全部", "真人秀", "脱口秀", "国产综艺", "喜剧", "晚会", "综艺",
              "音乐", "纪录", "游戏", "生活", "港台综艺", "日韩综艺", "剧情",
              "文化", "相声", "情感", "悬疑", "欧美综艺", "美食", "竞技"],
        "4": ["全部", "动画", "冒险", "喜剧", "奇幻", "剧情", "科幻", "动作",
              "儿童", "悬疑", "都市", "家庭", "国漫", "日常", "爱情", "玄幻",
              "日漫", "音乐", "治愈", "短片", "古风", "犯罪", "武侠", "运动", "校园"],
    }

    @trace_interface
    def getName(self):
        return "威视TV"

    @trace_interface
    def init(self, extend=""):
        candidate = extend
        try:
            if isinstance(extend, str) and extend.strip().startswith("{"):
                candidate = json.loads(extend)
            if isinstance(candidate, dict):
                candidate = candidate.get("host") or candidate.get("url") or candidate.get("site") or ""
        except Exception as error:
            self._debug("配置解析失败", error_type=type(error).__name__, error=str(error))
            candidate = ""
        value = str(candidate or "").strip().rstrip("/")
        self.host = value if re.match(r"^https?://", value, re.I) else self.DEFAULT_HOST
        self.headers = {
            "User-Agent": self.UA,
            "Referer": self.host + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update(self.headers)
        # 播放缓存（参照豆花电影风格）
        self._play_cache = {}
        # 预热标记
        self._warmed = False

    def _warm_up(self):
        """预热（参照豆花电影风格）"""
        if self._warmed:
            return
        try:
            self._get(self.host + "/")
            self._warmed = True
            self._debug("预热完成")
        except Exception as error:
            self._debug("预热失败", error_type=type(error).__name__, error=str(error))

    @trace_interface
    def homeContent(self, filter):
        result = {"class": list(self.CLASSES)}
        if filter:
            filters = {}
            for c in self.CLASSES:
                tid = c["type_id"]
                filters[tid] = [
                    {"key": "class", "name": "分类",
                     "value": [{"n": x, "v": "" if x == "全部" else x}
                               for x in self._FILTERS_MAP.get(tid, ["全部"])]},
                    {"key": "area", "name": "地区", "value": self._AREAS},
                    {"key": "year", "name": "年份", "value": self._YEARS},
                    {"key": "sort_field", "name": "排序", "value": self._SORTS},
                ]
            result["filters"] = filters
        return result

    @trace_interface
    def homeVideoContent(self):
        self._warm_up()
        return {"list": self._parse_list(self._get(self.host + "/"))[:60]}

    @trace_interface
    def categoryContent(self, tid, pg, filter, extend):
        self._warm_up()
        page = self._page(pg)
        if isinstance(extend, str):
            try:
                extend = json.loads(extend)
            except Exception:
                extend = {}
        if not extend:
            extend = {}
        # 清理空值
        for k in list(extend.keys()):
            if extend[k] in ("", None, "全部"):
                del extend[k]

        # 构造 URL，兼容筛选参数
        params = []
        for key in ("class", "area", "year", "sort_field"):
            if extend.get(key):
                params.append(f"{key}={quote(str(extend[key]))}")
        suffix = ("&" + "&".join(params)) if params else ""
        url = f"{self.host}/index.php/vod/show/id/{quote(str(tid))}/page/{page}.html{suffix}"
        html = self._get(url)
        items = self._parse_list(html)
        pagecount = self._page_count(html, page + 1 if items else page)
        return {
            "list": items,
            "page": page,
            "pagecount": pagecount,
            "limit": len(items),
            "total": pagecount * max(1, len(items)),
        }

    @trace_interface
    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vod = self._parse_detail(str(ids[0]), self._get(self._absolute(ids[0])))
        return {"list": [vod] if vod else []}

    @trace_interface
    def searchContent(self, key, quick, pg="1"):
        self._warm_up()
        page = self._page(pg)
        suffix = f"&page={page}" if page > 1 else ""
        html = self._get(f"{self.host}/index.php/vod/search.html?wd={quote(str(key))}{suffix}")
        items = self._parse_list(html)
        return {
            "list": items,
            "page": page,
            "pagecount": self._page_count(html, page + 1 if items else page),
        }

    @trace_interface
    def playerContent(self, flag, id, vipFlags):
        value = str(id or "")
        # 缓存检查（参照豆花电影风格）
        now = int(time.time())
        if value in self._play_cache:
            ts, res = self._play_cache[value]
            if now - ts < 600:
                return res

        if self._is_media(value):
            res = {"parse": 0, "url": value, "header": self._player_headers()}
            self._play_cache[value] = (now, res)
            return res
        url = self._decode_player(self._get(self._absolute(value)))
        if not url:
            res = {"parse": 1, "url": "", "header": self._player_headers()}
            self._play_cache[value] = (now, res)
            return res
        res = {"parse": 0 if self._is_media(url) else 1, "url": url, "header": self._player_headers()}
        self._play_cache[value] = (now, res)
        return res

    def _get(self, url):
        self._debug("HTTP请求", method="GET", url=self._safe_url(url))
        try:
            response = self.session.get(url, timeout=15)
            response.encoding = "utf-8"
            text = response.text or ""
            status = getattr(response, "status_code", 200)
            final_url = str(getattr(response, "url", "") or url)
            response_headers = getattr(response, "headers", {}) or {}
            title = self._page_title(text)
            self._debug(
                "HTTP响应",
                status=status,
                final_url=self._safe_url(final_url),
                content_length=len(text),
                content_type=str(response_headers.get("Content-Type") or ""),
                title=title,
                page_kind=self._page_kind(text, title),
            )
            if status >= 400:
                self._debug("HTTP状态异常", status=status, url=self._safe_url(final_url))
                return ""
            return text
        except Exception as error:
            self._debug(
                "HTTP异常",
                url=self._safe_url(url),
                error_type=type(error).__name__,
                error=str(error),
            )
            return ""

    def _absolute(self, value):
        text = str(value or "").strip()
        if not text:
            return self.host + "/"
        if text.startswith("//"):
            return "https:" + text
        if re.match(r"^https?://", text, re.I):
            parsed = urlparse(text)
            if "/index.php/" in parsed.path:
                return self.host + parsed.path + (("?" + parsed.query) if parsed.query else "")
            return text
        return urljoin(self.host + "/", text)

    def _relative(self, value):
        text = str(value or "").strip()
        if not text:
            return ""
        if re.match(r"^https?://", text, re.I):
            parsed = urlparse(text)
            return parsed.path + (("?" + parsed.query) if parsed.query else "")
        return text if text.startswith("/") else "/" + text

    def _parse_list(self, html):
        doc = self._html(html)
        raw_list_markers = len(re.findall(r"public-list-box", html or "", re.I))
        raw_detail_markers = len(re.findall(r"vod/detail", html or "", re.I))
        skipped = {
            "missing_link": 0,
            "missing_id": 0,
            "missing_name": 0,
            "duplicate": 0,
            "errors": 0,
        }
        if doc is None:
            self._debug(
                "列表解析",
                html_parse_ok=False,
                raw_list_markers=raw_list_markers,
                raw_detail_markers=raw_detail_markers,
                containers=0,
                detail_links=0,
                parsed=0,
                skipped=skipped,
                samples=[],
                html_length=len(html or ""),
            )
            return []
        items = []
        seen = set()
        boxes = doc.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' public-list-box ')]")
        detail_links = len(doc.xpath("//a[contains(@href, '/index.php/vod/detail/')]"))
        for box in boxes:
            try:
                links = box.xpath(".//a[contains(concat(' ', normalize-space(@class), ' '), ' public-list-exp ') and contains(@href, '/index.php/vod/detail/')]")
                if not links:
                    skipped["missing_link"] += 1
                    continue
                link = links[0]
                vod_id = self._relative(link.get("href"))
                if not vod_id:
                    skipped["missing_id"] += 1
                    continue
                name = (link.get("title") or "").strip()
                if not name:
                    alt = link.xpath("string(.//img[1]/@alt)").strip()
                    name = re.sub(r"封面图$", "", alt).strip()
                if not name:
                    skipped["missing_name"] += 1
                    continue
                if vod_id in seen:
                    skipped["duplicate"] += 1
                    continue
                seen.add(vod_id)
                pic = link.xpath("string(.//img[1]/@data-src)") or link.xpath("string(.//img[1]/@data-original)") or link.xpath("string(.//img[1]/@src)")
                pic = "" if str(pic).startswith("data:image/") else self._absolute(pic)
                remarks = self._first_text(box, ".//*[contains(concat(' ', normalize-space(@class), ' '), ' public-list-prb ')]")
                if not remarks:
                    remarks = self._first_text(box, ".//*[contains(concat(' ', normalize-space(@class), ' '), ' public-prt ')]")
                items.append({"vod_id": vod_id, "vod_name": name, "vod_pic": pic, "vod_remarks": remarks})
            except Exception as error:
                skipped["errors"] += 1
                self._debug(
                    "列表条目解析失败",
                    error_type=type(error).__name__,
                    error=str(error),
                )
        self._debug(
            "列表解析",
            html_parse_ok=True,
            raw_list_markers=raw_list_markers,
            raw_detail_markers=raw_detail_markers,
            containers=len(boxes),
            detail_links=detail_links,
            parsed=len(items),
            skipped=skipped,
            samples=[item["vod_name"] for item in items[:3]],
            html_length=len(html or ""),
        )
        return items

    def _parse_detail(self, vod_id, html):
        doc = self._html(html)
        if doc is None:
            return None
        name = self._first_text(doc, "//*[contains(concat(' ', normalize-space(@class), ' '), ' this-desc-title ')]")
        if not name:
            return None
        style = doc.xpath("string((//*[contains(concat(' ', normalize-space(@class), ' '), ' this-pic-bj ')])[1]/@style)")
        match = re.search(r"url\(['\"]?([^'\")]+)", style or "", re.I)
        pic = self._absolute(match.group(1)) if match else ""
        info = [self._clean("".join(node.itertext())) for node in doc.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' this-desc-info ')]//span")]
        info = [item for item in info if item]
        year = next((item for item in info if re.match(r"^(19|20)\d{2}$", item)), "")
        area = next((item for item in info if item != year and not re.search(r"更新|集|完结|分$", item)), "")
        remarks = next((item for item in info if re.search(r"更新|集|完结|HD|正片", item)), "")
        type_name = " / ".join(filter(None, [self._clean("".join(node.itertext())) for node in doc.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' this-desc-tags ')]//span")]))
        director = ""
        actor = ""
        for node in doc.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' this-info ')]"):
            label = self._first_text(node, ".//strong").replace(" ", "")
            value = ",".join(filter(None, [self._clean("".join(item.itertext())) for item in node.xpath(".//a")]))
            if "导演" in label:
                director = value
            if "演员" in label or "主演" in label:
                actor = value
        content = self._first_text(doc, "//*[@id='height_limit']//*[contains(concat(' ', normalize-space(@class), ' '), ' text ')]")
        content = re.sub(r"^\s*简介[:：]?\s*", "", content).strip()
        # 简介添加前缀（统一风格）
        if content:
            content = INTRO_PREFIX + "\n" + content
        else:
            content = INTRO_PREFIX

        line_nodes = doc.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' anthology-tab ')]//*[contains(concat(' ', normalize-space(@class), ' '), ' line-btn ')]")
        blocks = doc.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' anthology-list ')]//*[contains(concat(' ', normalize-space(@class), ' '), ' anthology-list-box ')]")
        play_from = []
        play_url = []
        for index in range(min(len(line_nodes), len(blocks))):
            line_texts = line_nodes[index].xpath(".//text()[not(ancestor::span[contains(concat(' ', normalize-space(@class), ' '), ' badge ')])]")
            line_name = self._clean("".join(line_texts)) or f"线路{index + 1}"
            # 线路别名映射（统一风格）
            if line_name in _LINE_ALIAS:
                line_name = _LINE_ALIAS[line_name]
            episodes = []
            episode_nodes = blocks[index].xpath(".//a[contains(concat(' ', normalize-space(@class), ' '), ' episode-btn ') and @href]")
            for episode_index, episode in enumerate(episode_nodes):
                episode_id = self._relative(episode.get("href"))
                if episode_id:
                    episode_name = self._clean("".join(episode.itertext())) or f"第{episode_index + 1}集"
                    episodes.append(f"{episode_name}${episode_id}")
            if episodes:
                play_from.append(line_name)
                play_url.append("#".join(episodes))
        return {
            "vod_id": self._relative(vod_id),
            "vod_name": name,
            "vod_pic": pic,
            "vod_remarks": remarks,
            "vod_year": year,
            "vod_area": area,
            "type_name": type_name,
            "vod_director": director,
            "vod_actor": actor,
            "vod_content": content,
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
        }

    def _decode_player(self, html):
        match = re.search(r"var\s+player_aaaa\s*=\s*(\{[\s\S]*?\})\s*</script>", html or "", re.I)
        if not match:
            return ""
        try:
            player = json.loads(match.group(1))
            value = str(player.get("url") or "")
            encrypt = int(player.get("encrypt") or 0)
            if encrypt == 1:
                value = unquote(value)
            elif encrypt == 2:
                value = unquote(base64.b64decode(value).decode("utf-8"))
            return value if re.match(r"^https?://", value, re.I) else ""
        except Exception as error:
            self._debug("播放数据解析失败", error_type=type(error).__name__, error=str(error))
            return ""

    def _player_headers(self):
        return {"User-Agent": self.UA, "Referer": self.host + "/"}

    @staticmethod
    def _preview(value, limit=180):
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            text = str(value)
        text = re.sub(r"\s+", " ", text).strip()
        return text if len(text) <= limit else text[:limit] + "..."

    def _debug(self, event, **fields):
        try:
            payload = {"event": event}
            payload.update(fields)
            self.log(f"{LOG_TAG} {json.dumps(payload, ensure_ascii=False, default=str)}")
        except Exception:
            pass

    def _summarize_arguments(self, interface, args, kwargs):
        if interface == "playerContent":
            value = args[1] if len(args) > 1 else kwargs.get("id")
            flags = args[2] if len(args) > 2 else kwargs.get("vipFlags")
            return {
                "flag": self._preview(args[0] if args else kwargs.get("flag"), 60),
                "id": self._resource_hint(value),
                "vip_flags_count": len(flags) if isinstance(flags, (list, tuple, set)) else 0,
            }
        if interface == "isVideoFormat":
            value = args[0] if args else kwargs.get("url")
            return {"url": self._resource_hint(value)}
        if interface == "init":
            value = args[0] if args else kwargs.get("extend", "")
            return {"extend": self._preview(value, 120)}
        return self._preview({"args": args, "kwargs": kwargs})

    def _resource_hint(self, value):
        text = str(value or "").strip()
        parsed = urlparse(text)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            return {"kind": "url", "host": parsed.netloc, "media": bool(self._is_media(text))}
        return {"kind": "path", "value": self._preview(text, 120)}

    def _safe_url(self, value):
        text = str(value or "").strip()
        try:
            parsed = urlparse(text)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return self._preview(text, 180)
            if self._is_media(text):
                return f"{parsed.scheme}://{parsed.netloc}/<media>"
            query = "?<redacted>" if parsed.query else ""
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}{query}"
        except Exception:
            return "<invalid-url>"

    def _summarize_result(self, interface, result):
        summary = {"result_type": type(result).__name__}
        if not isinstance(result, dict):
            summary["result"] = self._preview(result)
            return summary
        items = result.get("list")
        classes = result.get("class")
        if isinstance(items, list):
            summary["list_count"] = len(items)
            summary["samples"] = [
                str(item.get("vod_name") or "")
                for item in items[:3]
                if isinstance(item, dict)
            ]
        if isinstance(classes, list):
            summary["class_count"] = len(classes)
        for key in ("page", "pagecount", "limit", "total", "parse"):
            if key in result:
                summary[key] = result[key]
        if interface == "playerContent":
            value = str(result.get("url") or "")
            summary["has_url"] = bool(value)
            summary["media"] = self._is_media(value)
            summary["url_host"] = urlparse(value).netloc if value else ""
        return summary

    @classmethod
    def _page_title(cls, html):
        match = re.search(r"<title[^>]*>([\s\S]*?)</title>", html or "", re.I)
        if not match:
            return ""
        return cls._clean(re.sub(r"<[^>]+>", "", match.group(1)))

    @staticmethod
    def _page_kind(html, title):
        text = f"{title}\n{str(html or '')[:50000]}".lower()
        markers = (
            "just a moment",
            "cf-chl-",
            "captcha",
            "人机验证",
            "访问验证",
            "安全验证",
        )
        if any(marker in text for marker in markers):
            return "challenge"
        return "html" if html else "empty"

    def _html(self, html):
        try:
            if not html:
                return None
            payload = html.encode("utf-8") if isinstance(html, str) else html
            parser = etree.HTMLParser(encoding="utf-8", recover=True)
            return etree.HTML(payload, parser=parser)
        except Exception as error:
            self._debug(
                "HTML解析失败",
                error_type=type(error).__name__,
                error=str(error),
                html_length=len(html or ""),
            )
            return None

    @staticmethod
    def _clean(value):
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def _first_text(self, node, xpath):
        values = node.xpath(xpath)
        if not values:
            return ""
        value = values[0]
        return self._clean("".join(value.itertext()) if hasattr(value, "itertext") else value)

    @staticmethod
    def _page(value):
        try:
            return max(1, int(value))
        except Exception:
            return 1

    @staticmethod
    def _page_count(html, fallback):
        pages = [int(value) for value in re.findall(r"/page/(\d+)\.html", html or "")]
        return max([int(fallback)] + pages)

    @staticmethod
    def _is_media(url):
        return re.match(r"^https?://", str(url or ""), re.I) is not None and re.search(r"\.(m3u8|mp4|flv|mkv|ts|mpd)(?:[?#]|$)", str(url), re.I) is not None

    @trace_interface
    def isVideoFormat(self, url):
        return False

    @trace_interface
    def manualVideoCheck(self):
        return False

    @trace_interface
    def destroy(self):
        pass

    @trace_interface
    def localProxy(self, param):
        return None
