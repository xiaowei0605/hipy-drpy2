import re, json
try:
    import requests as _requests
except Exception:
    _requests = None


class Spider:
    def __init__(self):
        self.site = "https://www.ondemandchina.com"
        self.name = "ODC影视"
        self.header = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-S9080) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Referer": self.site,
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        self.s = self.session = self.sess = _requests.Session() if _requests else None
        self.gql = "https://odc-graphql.odkmedia.io/graphql"
        self.rest = "https://odkmedia.io/odc/api/v1"
        self.play = "https://odkmedia.io/odc/api/v2/playback"
        self._nav = None
        self._builtin = [
            ("drama", "电视剧", [("recently-added", "最近更新"), ("high-rated-crime", "顶流烧脑"), ("traditional-costume-pick", "精品古装"), ("family-oriented", "黄金八点"), ("novel-adapted", "小说改编"), ("classic-hk-tw", "港台精选"), ("top-jp-kr", "高分日韩"), ("idol-romance", "青春偶像"), ("spy-war-drama", "经典谍战")], [("comedy", "喜剧"), ("traditional-costume", "古装"), ("martial-arts", "武侠"), ("romance", "浪漫"), ("crime", "犯罪"), ("suspense", "悬疑"), ("spy-war", "谍战"), ("history", "历史"), ("fantasy", "奇幻"), ("city", "都市"), ("family", "家庭"), ("idol", "偶像"), ("web-drama", "网剧"), ("military", "军事"), ("sci-fi", "科幻"), ("country", "农村"), ("youth", "青春"), ("period-drama", "年代"), ("k-drama", "韩剧"), ("tw-drama", "台剧"), ("hk-drama", "港剧"), ("jp-drama", "日剧"), ("drama-genre", "剧情")]),
            ("movie", "电影", [("k-movies-top-pick", "高分韩影"), ("asian-blockbusters", "破亿票房"), ("dark-horse", "冷门佳片"), ("best-rom-com", "心动舔屏"), ("laugh-it-out", "捧腹大笑"), ("awarded-movies", "得奖好片"), ("midnight-hotline", "午夜风情"), ("en-sub-movie", "英文字幕")], [("traditional-costume", "古装"), ("comedy", "喜剧"), ("crime", "犯罪"), ("action", "动作"), ("suspense", "悬疑"), ("horror", "恐怖"), ("romance", "浪漫"), ("fantasy", "奇幻"), ("history", "历史"), ("family", "家庭"), ("war", "战争"), ("martial-arts", "武侠"), ("drama-genre", "剧情")]),
            ("variety", "综艺", [("lifestyle-show", "文化慢生活"), ("reality-show", "娱乐真人秀")], [("reality-show", "真人秀"), ("talk-show", "脱口秀"), ("talent-show", "选秀"), ("food", "美食"), ("documentary", "纪实"), ("love", "情感"), ("travel", "旅游"), ("kids", "少儿"), ("evening-event", "晚会"), ("intellgence", "益智"), ("music", "音乐"), ("game", "游戏"), ("life", "生活")]),
            ("documentary", "纪录片", [("food-docu", "美食盛宴"), ("social-humanities", "人文纪实"), ("step-into-the-world", "走遍世界")], [("character", "人物"), ("history", "历史"), ("nature", "自然"), ("adventure", "冒险"), ("science", "科技"), ("culture", "文化"), ("social", "社会"), ("reality", "真人"), ("food", "美食")]),
            ("news", "新闻", [], []),
            ("kids", "少儿", [], [("cartoon", "动画"), ("education", "教育"), ("adventure", "冒险")]),
            ("chinese-drama-engsubs", "中英字幕", [], []),
        ]

    def getDependence(self):
        return []

    def manualVideoCheck(self):
        return False

    def isVideoFormat(self, url):
        if not url:
            return False
        u = str(url).lower()
        return u.endswith((".m3u8", ".mp4", ".flv", ".mkv", ".ts", ".avi")) or "m3u8" in u

    def destroy(self):
        pass

    def action(self, action):
        return {}

    def _get(self, url, headers=None):
        h = dict(self.header)
        if headers:
            h.update(headers)
        if self.s is not None:
            try:
                r = self.s.get(url, headers=h, timeout=15, allow_redirects=True)
                if r.status_code < 400:
                    return r.text
            except Exception:
                pass
        try:
            import urllib.request
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read().decode("utf-8", "ignore")
        except Exception:
            return ""

    def _post(self, url, payload, headers=None):
        h = dict(self.header)
        h["Content-Type"] = "application/json"
        if headers:
            h.update(headers)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if self.s is not None:
            try:
                r = self.s.post(url, data=data, headers=h, timeout=15)
                if r.status_code < 400:
                    return r.text
            except Exception:
                pass
        try:
            import urllib.request
            req = urllib.request.Request(url, data=data, headers=h)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read().decode("utf-8", "ignore")
        except Exception:
            return ""

    def _u(self, u):
        if not u:
            return u
        u = u.strip()
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("http"):
            return u
        if u.startswith("/"):
            m = re.match(r"(https?://[^/]+)", self.site)
            return (m.group(1) if m else self.site) + u
        return self.site.rstrip("/") + "/" + u.lstrip("/")

    def _gql(self, query, variables):
        try:
            txt = self._post(self.gql, {"query": query, "variables": variables})
            d = json.loads(txt) if txt else {}
            return d.get("data") or {}
        except Exception:
            return {}

    def _navcats(self):
        if self._nav is not None:
            return self._nav
        cats = []
        try:
            txt = self._get(self.rest + "/navigation/")
            d = json.loads(txt) if txt else {}
            for top in (d.get("results") or [{}])[0].get("contents") or []:
                subs = []
                genres = []
                for ch in top.get("items") or []:
                    item = (ch.get("slug") or "", ch.get("title_zh_Hans") or ch.get("title_zh_hans") or ch.get("title_en") or "")
                    if not item[0] or not item[1]:
                        continue
                    if ch.get("type") == "genre":
                        genres.append(item)
                    else:
                        subs.append(item)
                if top.get("slug"):
                    cats.append((top["slug"], top.get("title_zh_Hans") or top.get("title_zh_hans") or top.get("title_en") or top["slug"], subs, genres))
        except Exception:
            cats = []
        self._nav = cats or list(self._builtin)
        return self._nav

    def _status(self, s):
        return {"on-air": "连载中", "completed": "已完结", "coming-soon": "即将上线"}.get(s or "", "")

    def _vod(self, n):
        try:
            img = (n.get("images") or {})
            pic = img.get("posterZhHans") or img.get("poster") or ""
            meta = n.get("meta") or {}
            total = meta.get("episodeTotal")
            remarks = []
            if n.get("produceYear"):
                remarks.append(str(n["produceYear"]))
            st = self._status(n.get("releaseStatus"))
            if st:
                remarks.append(st)
            if meta.get("isSeries"):
                remarks.append("共%d集" % total if total else "剧集")
            else:
                remarks.append("电影")
            le = n.get("latestEpisode") or {}
            if le.get("titleZhHans"):
                remarks.append(le["titleZhHans"])
            return {
                "vod_id": n.get("slug") or "",
                "vod_name": n.get("titleZhHans") or n.get("titleEn") or "",
                "vod_pic": self._u(pic),
                "vod_remarks": "·".join([r for r in remarks if r]),
            }
        except Exception:
            return None

    def _plist(self, category, genre, status, sortf, pg):
        q = "query ProgramList($categorySlug: String!, $releaseStatus: String, $genreSlug: String, $sortFilter: String, $page: Int) { programs(categorySlug: $categorySlug, releaseStatus: $releaseStatus, genreSlug: $genreSlug, sortFilter: $sortFilter, page: $page) { totalCount pageInfo { hasNextPage nextPage } nodes { slug titleZhHans titleEn produceYear releaseStatus images { poster posterZhHans } meta { isSeries episodeTotal produceCountries } latestEpisode { titleZhHans } } } }"
        v = {"categorySlug": category, "page": pg}
        if genre:
            v["genreSlug"] = genre
        if status:
            v["releaseStatus"] = status
        if sortf:
            v["sortFilter"] = sortf
        d = self._gql(q, v).get("programs") or {}
        nodes = d.get("nodes") or []
        out = []
        seen = set()
        for n in nodes:
            vod = self._vod(n)
            if vod and vod["vod_id"] and vod["vod_id"] not in seen:
                seen.add(vod["vod_id"])
                out.append(vod)
        total = d.get("totalCount") or 0
        pc = 1
        if nodes and total:
            pc = max(1, -(-total // len(nodes)))
        return out, pc, total

    def init(self, extend=""):
        return None

    def getName(self):
        return self.name

    def homeContent(self, filter=None):
        cats = self._navcats()
        classes = [{"type_id": c[0], "type_name": c[1]} for c in cats]
        filters = {}
        for slug, name, subs, genres in cats:
            fl = []
            if subs:
                fl.append({"key": "cate", "name": "子分类", "value": [{"n": "全部", "v": ""}] + [{"n": n, "v": s} for s, n in subs]})
            if genres:
                fl.append({"key": "genre", "name": "类型", "value": [{"n": "全部", "v": ""}] + [{"n": n, "v": s} for s, n in genres]})
            fl.append({"key": "status", "name": "状态", "value": [{"n": "全部", "v": ""}, {"n": "连载中", "v": "on-air"}, {"n": "已完结", "v": "completed"}, {"n": "即将上线", "v": "coming-soon"}]})
            fl.append({"key": "sort", "name": "排序", "value": [{"n": "默认", "v": ""}, {"n": "热门", "v": "popular-yesterday"}, {"n": "最近开播", "v": "-release_start"}, {"n": "最近更新", "v": "recent-updated"}]})
            filters[slug] = fl
        vod_list, _, _ = self._plist("drama", "", "", "", 1)
        return {"class": classes, "filters": filters, "list": vod_list}

    def homeVideoContent(self):
        vod_list, _, _ = self._plist("drama", "", "", "", 1)
        return {"list": vod_list}

    def categoryContent(self, tid, pg=1, filter=None, extend=None):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        ext = extend if isinstance(extend, dict) else {}
        cat = ext.get("cate") or tid
        vod_list, pc, total = self._plist(cat, ext.get("genre") or "", ext.get("status") or "", ext.get("sort") or "", pg)
        return {"list": vod_list, "page": pg, "pagecount": pc, "limit": 24, "total": total}

    def detailContent(self, ids):
        slug = ids[0] if isinstance(ids, (list, tuple)) else ids
        slug = str(slug or "").strip()
        if not slug:
            return {"list": []}
        q = "query Program($programSlug: String!) { program(programSlug: $programSlug) { slug titleZhHans titleEn synopsisZhHans produceYear releaseStatus meta { isSeries episodeTotal produceCountries } images { poster posterZhHans } categories { slug titleZhHans } genres { slug titleZhHans } } }"
        p = self._gql(q, {"programSlug": slug}).get("program") or {}
        if not p:
            return {"list": []}
        eps = []
        page = 1
        while page <= 20:
            try:
                txt = self._get(self.rest + "/program/" + slug + "/episodes/?page=" + str(page))
                d = json.loads(txt) if txt else {}
            except Exception:
                d = {}
            for e in d.get("results") or []:
                try:
                    num = e.get("number")
                    title = e.get("title_zh_Hans") or e.get("title_en") or ("第%d集" % num if num else "正片")
                    if not (p.get("meta") or {}).get("isSeries"):
                        title = "正片"
                    eps.append("%s$%s@%s" % (title, slug, e.get("id")))
                except Exception:
                    continue
            if not d.get("next"):
                break
            page += 1
        if not eps:
            eps = ["正片$%s@0" % slug]
        img = (p.get("images") or {})
        cats = ",".join([(c.get("titleZhHans") or "") for c in (p.get("categories") or []) if c.get("titleZhHans")])
        gens = ",".join([(g.get("titleZhHans") or "") for g in (p.get("genres") or []) if g.get("titleZhHans")])
        desc = (p.get("synopsisZhHans") or "").strip()
        if cats:
            desc = "分类：" + cats + "\n" + desc
        if gens:
            desc = "类型：" + gens + "\n" + desc
        return {"list": [{
            "vod_id": slug,
            "vod_name": p.get("titleZhHans") or p.get("titleEn") or slug,
            "vod_pic": self._u(img.get("posterZhHans") or img.get("poster") or ""),
            "vod_year": str(p.get("produceYear") or ""),
            "vod_remarks": self._status(p.get("releaseStatus")),
            "vod_content": desc,
            "vod_play_from": "ODC",
            "vod_play_url": "#".join(eps),
        }]}

    def searchContent(self, key, quick=False, pg="1"):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        q = "query Search($keyword: String, $page: Int) { search(keyword: $keyword, page: $page) { totalCount pageInfo { hasNextPage nextPage } nodes { slug titleZhHans titleEn produceYear releaseStatus images { poster posterZhHans } meta { isSeries episodeTotal produceCountries } latestEpisode { titleZhHans } } } }"
        d = self._gql(q, {"keyword": str(key), "page": pg}).get("search") or {}
        out = []
        seen = set()
        for n in d.get("nodes") or []:
            vod = self._vod(n)
            if vod and vod["vod_id"] and vod["vod_id"] not in seen:
                seen.add(vod["vod_id"])
                out.append(vod)
        return {"list": out}

    def playerContent(self, flag, ids, vipFlags=None):
        raw = ids[0] if isinstance(ids, (list, tuple)) else ids
        raw = str(raw or "").strip()
        slug = ""
        epid = raw
        if "@" in raw:
            slug, epid = raw.rsplit("@", 1)
        if not epid or epid == "0":
            return {"parse": 1, "url": self.site + "/zh-Hans/program/" + slug, "header": dict(self.header)}
        txt = self._get(self.play + "/" + epid + "/", headers={"service-name": "odc"})
        try:
            d = json.loads(txt) if txt else {}
        except Exception:
            d = {}
        srcs = d.get("sources") or []
        want = ["1080p", "720p", "480p", "360p"]
        url = ""
        for w in want:
            for s in srcs:
                if s.get("preset") == w and s.get("url"):
                    url = s["url"]
                    break
            if url:
                break
        if not url and srcs and srcs[0].get("url"):
            url = srcs[0]["url"]
        if url:
            return {"parse": 0, "url": url, "header": dict(self.header)}
        return {"parse": 1, "url": self.site + "/zh-Hans/program/" + slug, "header": dict(self.header)}

    def localProxy(self, param):
        u = param.get("url", "") if isinstance(param, dict) else ""
        if not u:
            return [403, "text/plain", b"", None]
        h = dict(self.header)
        if self.s is not None:
            try:
                r = self.s.get(u, headers=h, timeout=15)
                return [200, r.headers.get("Content-Type", "application/octet-stream"), r.content, None]
            except Exception:
                pass
        try:
            import urllib.request
            req = urllib.request.Request(u, headers=h)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return [200, resp.headers.get("Content-Type", "application/octet-stream"), resp.read(), None]
        except Exception:
            return [403, "text/plain", b"", None]
