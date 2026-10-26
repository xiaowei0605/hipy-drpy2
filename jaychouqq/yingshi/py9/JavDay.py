# -*- coding: utf-8 -*-
import re
import sys
import json
import gzip
import html as html_mod
import http.client
import http.cookiejar
import urllib.request
import urllib.parse
import urllib.error

sys.path.append('..')
try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider:
        def __init__(self):
            pass


# 站点结构（2026-10-24 实测，javday.app，自研模板站）：
# - 采集 API 已关（api.php/provide/vod 回 "closed"），走 HTML 路线
# - 分类：5 个 /category/{slug}/（有碼/新作上市/無修正流出/AI 短劇/
#   國產AV）+ 2 个 /label/{slug}/（最近更新/人氣系列，单页固定榜，
#   /page/2/ 与第 1 页内容完全相同、无真分页，pagecount=1 不伪造）
#   + 「最新」伪分类走首页。/label/groups/ 是厂商目录（外链到
#   javday.tv），不是视频卡，不收进分类
# - 列表：分类页 /category/{slug}/page/{n}/（第 1 页裸路径），每页
#   24 卡；分页器带末页号，pagecount 取同形态链接最大页码
# - 卡片：<a href="/videos/{码}/" class="videoBox">，封面在
#   videoBox-cover 的 background-image url()（img.javday.app，
#   webp/jpg），标题在 videoBox-info 的 span.title
# - 搜索：GET /search/wd/{词}/，翻页 /search/page/{n}/wd/{词}/
# - 详情：h1.video-title 为正式标题，og:image 为封面；播放地址
#   在页内播放器 JS 的 url: 'https://javday.homes/videos/{a}/{b}/
#   index.m3u8'（单线路，无线路切换）。注意：页内另有一个带
#   line= 参数的 <source> 地址实测 403，绝不能用，只取无参版
# - 播放：无参 m3u8 裸取即 200 #EXTM3U，无需 Referer；分片在
#   *.javday.homes 同域
# - v2 修正（2026-10-24，用户手机实测反馈）：
#   ① 分片无 Referer 会被断连：主清单裸取 200 但分片裸取直接断
#   连（000），带 javday.app Referer 才 200——播放器不一定把
#   header 透传给分片，故 m3u8 一律走 localProxy 重写（清单与
#   分片都由源内带 Referer 取），player 只下发代理地址
#   ② 选集串藏在 <source src> 里：多集剧的 source src 本身就是
#   TVBox 格式 Ep1$u1#Ep2$u2#...，详情直接取用当 vod_play_url；
#   其中末集常带 ?line= 参数（实测 403），逐集清洗掉 line= 再用


class Spider(BaseSpider):
    def getName(self):
        return 'JavDay'

    def init(self, extend=''):
        self.host = 'https://javday.app'
        if extend:
            try:
                cfg = json.loads(extend) if isinstance(extend, str) else extend
                if isinstance(cfg, dict) and cfg.get('host'):
                    self.host = str(cfg['host']).rstrip('/')
            except Exception:
                pass
        self.ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/126.0.0.0 Safari/537.36')
        self.headers = {'User-Agent': self.ua,
                        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'}
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj))
        self._truncated = False
        # type_id -> (路径, 是否单页榜)
        self.cats = [
            ('latest', '最新'),
            ('category/censored', '有碼'),
            ('category/new-release', '新作上市'),
            ('category/uncensored-leaked', '無修正流出'),
            ('category/aiav', 'AI 短劇'),
            ('category/chinese-av', '國產AV'),
            ('label/new', '最近更新'),
            ('label/hot', '人氣系列'),
        ]
        self.single_page = {'label/new', 'label/hot'}

    # ---------- 基础工具 ----------
    def _clean(self, s):
        s = html_mod.unescape(s or '')
        s = re.sub(r'<!--.*?-->', '', s, flags=re.S)
        s = re.sub(r'<[^>]+>', '', s)
        return re.sub(r'\s+', ' ', s).strip()

    def _fetch(self, url, referer='', timeout=30):
        # chunked 响应偶发截断（IncompleteRead）：多抓几次取最完整一份
        best = ''
        for attempt in range(3):
            text = self._fetch_once(url, referer, timeout)
            if len(text) > len(best):
                best = text
            if text and not self._truncated:
                return text
        return best

    def _fetch_once(self, url, referer='', timeout=30):
        headers = {'User-Agent': self.ua,
                   'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'}
        if referer:
            headers['Referer'] = referer
        data = b''
        self._truncated = False
        try:
            req = urllib.request.Request(url, headers=headers)
            r = self.opener.open(req, timeout=timeout)
            try:
                data = r.read()
            except http.client.IncompleteRead as e:
                data = e.partial or b''
                self._truncated = True
            finally:
                r.close()
        except urllib.error.HTTPError as e:
            try:
                data = e.read()
            except http.client.IncompleteRead as e2:
                data = e2.partial or b''
                self._truncated = True
            except Exception:
                data = b''
        except Exception:
            return ''
        try:
            if data[:2] == b'\x1f\x8b':
                data = gzip.decompress(data)
            return data.decode('utf-8', 'ignore')
        except Exception:
            return ''

    def _strip_line_param(self, url):
        """去掉 ?line= / &line= 参数（实测 403），并清掉残留 ?/&。"""
        u = re.sub(r'[?&]line=[^&#]*', '', url or '')
        if u.endswith('?') or u.endswith('&'):
            u = u[:-1]
        return u

    def _proxy_url(self, real_url, kind):
        try:
            base = self.getProxyUrl()
        except Exception:
            base = ''
        if not base:
            base = 'http://127.0.0.1:9978/proxy?do=py'
        sep = '&' if '?' in base else '?'
        return base + sep + 'type=%s&url=%s' % (
            kind, urllib.parse.quote(real_url, safe=''))

    def _fetch_bytes(self, url, referer='', timeout=30):
        """localProxy 用：带 Referer 取二进制（清单/分片/key）。"""
        try:
            headers = {'User-Agent': self.ua}
            if referer:
                headers['Referer'] = referer
            req = urllib.request.Request(url, headers=headers)
            r = self.opener.open(req, timeout=timeout)
            try:
                return r.read()
            finally:
                r.close()
        except Exception:
            return b''

    def _rewrite_m3u8(self, text, base_url):
        """#EXT 行不动；KEY URI 与分片行包 localProxy（带 Referer 取）。"""
        out = []
        for line in text.splitlines():
            s = line.strip()
            if not s:
                out.append(line)
                continue
            if s.startswith('#'):
                m = re.search(r'URI="([^"]+)"', s)
                if m:
                    absu = urllib.parse.urljoin(base_url, m.group(1))
                    s = s.replace(m.group(1),
                                  self._proxy_url(absu, 'key'))
                out.append(s)
                continue
            absu = urllib.parse.urljoin(base_url, s)
            out.append(self._proxy_url(absu, 'ts'))
        return '\n'.join(out)

    def _probe_media(self, url, referer='', timeout=12):
        """普通 GET 读头部字节判媒体：HLS 看 #EXTM3U，mp4 看 ftyp。"""
        try:
            headers = {'User-Agent': self.ua}
            if referer:
                headers['Referer'] = referer
            req = urllib.request.Request(url, headers=headers)
            r = self.opener.open(req, timeout=timeout)
            try:
                head = r.read(1024)
            finally:
                r.close()
            if head.lstrip().startswith(b'#EXTM3U'):
                return True
            return len(head) >= 8 and head[4:8] == b'ftyp'
        except Exception:
            return False

    # ---------- 卡片解析 ----------
    def _parse_cards(self, html):
        cards = []
        if not html:
            return cards
        # 搜索页锚点中间多了 target="_blank"，不要把 class 写死在 href 后
        anchors = list(re.finditer(
            r'<a href="(/videos/[^"/]+/)"[^>]*class="videoBox"', html))
        seen = set()
        for i, m in enumerate(anchors):
            vpath = m.group(1)
            if vpath in seen:
                continue
            seen.add(vpath)
            end = anchors[i + 1].start() if i + 1 < len(anchors) else len(html)
            seg = html[m.start():min(end, m.start() + 2500)]
            # 标签页封面是实体编码的引号 url(&quot;https://...)，
            # 分类页是裸 url(https://...)，两种都要认
            pm = re.search(
                r'background-image:\s*url\((?:&quot;|&#34;|["\'])?'
                r'(https?://[^)"\'\s;&]+)', seg)
            pic = html_mod.unescape(pm.group(1)) if pm else ''
            tm = re.search(r'<span class="title">([^<]+)</span>', seg)
            title = self._clean(tm.group(1)) if tm else ''
            if not title:
                continue
            vm = re.search(r'class="number">([\d,]+)<', seg)
            cards.append({
                'vod_id': vpath,
                'vod_name': title,
                'vod_pic': pic,
                'vod_remarks': vm.group(1) + '次' if vm else '',
                'style': {'type': 'rect', 'ratio': 1.78},
            })
        return cards

    def _pagecount(self, html, prefix, pg, cards, per_page=24):
        nums = [int(x) for x in re.findall(
            re.escape(prefix) + r'page/(\d+)/', html or '')]
        if nums:
            return max(nums + [pg])
        return pg + 1 if len(cards) >= per_page else pg

    # ---------- 接口 ----------
    def homeContent(self, filter):
        return {'class': [{'type_id': t, 'type_name': n}
                          for t, n in self.cats], 'filters': {}}

    def homeVideoContent(self):
        html = self._fetch(self.host + '/')
        return {'list': self._parse_cards(html)}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        tid = str(tid)
        if tid == 'latest':
            if pg > 1:
                return {'list': [], 'page': pg, 'pagecount': 1,
                        'limit': 0, 'total': 0}
            cards = self._parse_cards(self._fetch(self.host + '/'))
            return {'list': cards, 'page': 1, 'pagecount': 1,
                    'limit': len(cards), 'total': len(cards)}
        if tid in self.single_page:
            if pg > 1:
                return {'list': [], 'page': pg, 'pagecount': 1,
                        'limit': 0, 'total': 0}
            cards = self._parse_cards(
                self._fetch(self.host + '/' + tid + '/'))
            return {'list': cards, 'page': 1, 'pagecount': 1,
                    'limit': len(cards), 'total': len(cards)}
        base = self.host + '/' + tid.strip('/') + '/'
        url = base if pg == 1 else base + 'page/%d/' % pg
        html = self._fetch(url, referer=self.host + '/')
        cards = self._parse_cards(html)
        pc = self._pagecount(html, '/' + tid.strip('/') + '/', pg, cards)
        return {'list': cards, 'page': pg, 'pagecount': pc,
                'limit': len(cards), 'total': pc * max(len(cards), 1)}

    def searchContent(self, key, quick, pg='1'):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        kw = urllib.parse.quote(str(key).strip())
        if pg == 1:
            url = '%s/search/wd/%s/' % (self.host, kw)
        else:
            url = '%s/search/page/%d/wd/%s/' % (self.host, pg, kw)
        html = self._fetch(url, referer=self.host + '/')
        cards = self._parse_cards(html)
        # 搜索分页链接是 /search/page/{n}/wd/{词}/，按 /search/ 前缀取最大页
        pc = self._pagecount(html, '/search/', pg, cards, per_page=20)
        return {'list': cards, 'page': pg, 'pagecount': pc,
                'limit': len(cards), 'total': pc * max(len(cards), 1)}

    def detailContent(self, ids):
        if isinstance(ids, (list, tuple)):
            vpath = str(ids[0]) if ids else ''
        else:
            vpath = str(ids)
        if not vpath:
            return {'list': []}
        if not vpath.startswith('/'):
            vpath = '/' + vpath
        page = self.host + vpath
        html = self._fetch(page, referer=self.host + '/')
        title = ''
        pic = ''
        desc = ''
        play = ''
        play_is_eps = False
        if html:
            tm = re.search(r'<h1 class="video-title">([^<]+)</h1>', html)
            if tm:
                title = self._clean(tm.group(1))
            pm = re.search(r'property="og:image" content="([^"]+)"', html)
            if pm:
                pic = pm.group(1)
            dm = re.search(r'name="description" content="([^"]+)"', html)
            if dm:
                desc = self._clean(dm.group(1))
            # ① 先看 <source src>：多集剧的 src 本身就是 TVBox 格式
            #    Ep1$u1#Ep2$u2#...，直接取用当 vod_play_url（逐集清 line=）
            #    单集时 src 是普通 m3u8，走「正片$」分支
            sm = re.search(r"<source[^>]+src=['\"]([^'\"]+)['\"]", html)
            if sm:
                src = html_mod.unescape(sm.group(1)).strip()
                if '$' in src and '#' in src:
                    parts = []
                    for ep in src.split('#'):
                        if '$' in ep:
                            nm, u = ep.split('$', 1)
                            u = self._strip_line_param(u.strip())
                            if u:
                                parts.append('%s$%s' % (nm.strip(), u))
                    if parts:
                        play = '#'.join(parts)
                        play_is_eps = True
                elif src.endswith('.m3u8'):
                    play = self._strip_line_param(src)
            # ② 播放器 JS 的 url（无参版）；带 line= 参数的跳过（实测 403）
            if not play:
                for m in re.finditer(r"url:\s*'(https?://[^']+\.m3u8[^']*)'", html):
                    u = m.group(1)
                    if 'line=' not in u:
                        play = u
                        break
        if not title:
            slug = vpath.rstrip('/').split('/')[-1]
            title = slug.replace('-', ' ')
        vod = {
            'vod_id': vpath,
            'vod_name': title,
            'vod_pic': pic,
            'vod_content': desc,
            'vod_play_from': 'JavDay',
            'vod_play_url': (play if play_is_eps else
                             '正片$%s' % (play if play else page)),
        }
        return {'list': [vod]}

    def playerContent(self, flag, id, vipFlags):
        url = str(id)
        header = {'User-Agent': self.ua, 'Referer': self.host + '/'}
        if '.m3u8' in url:
            # 分片要 Referer 才放行、播放器未必透传 header，故一律走
            # localProxy 重写清单下发；m3u8 绝不降级成 parse=1
            return {'parse': 0, 'jx': 0,
                    'url': self._proxy_url(self._strip_line_param(url),
                                           'm3u8'),
                    'header': header}
        if '/videos/' in url:
            return {'parse': 1, 'jx': 1, 'url': url, 'header': header}
        return {'parse': 1, 'jx': 1, 'url': url, 'header': header}

    def isVideoFormat(self, url):
        u = (url or '').lower()
        return '.m3u8' in u or '.mp4' in u

    def localProxy(self, params):
        # 只返 3 段 [状态码, mime, bytes]
        try:
            if isinstance(params, dict):
                ptype = params.get('type', '')
                purl = params.get('url', '')
                if ptype == 'm3u8' and purl:
                    # 清单由源内带 Referer 取，分片行包 ts 代理
                    raw = self._fetch_bytes(purl, referer=self.host + '/')
                    if raw:
                        text = raw.decode('utf-8', 'ignore')
                        if '#EXTM3U' in text:
                            body = self._rewrite_m3u8(text, purl)
                            return [200, 'application/vnd.apple.mpegurl',
                                    body.encode('utf-8')]
                    return [404, 'text/plain', b'']
                if ptype in ('ts', 'key') and purl:
                    raw = self._fetch_bytes(purl, referer=self.host + '/')
                    if raw:
                        mime = ('video/mp2t' if ptype == 'ts'
                                else 'application/octet-stream')
                        return [200, mime, raw]
                    return [404, 'text/plain', b'']
            if isinstance(params, dict) and params.get('type') == 'pic':
                url = params.get('url', '')
                if url:
                    req = urllib.request.Request(
                        url, headers={'User-Agent': self.ua,
                                      'Referer': self.host + '/'})
                    r = self.opener.open(req, timeout=15)
                    try:
                        raw = r.read()
                    finally:
                        r.close()
                    if raw[:3] == b'\xff\xd8\xff':
                        return [200, 'image/jpeg', raw]
                    if raw[:8] == b'\x89PNG\r\n\x1a\n':
                        return [200, 'image/png', raw]
                    if raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
                        return [200, 'image/webp', raw]
        except Exception:
            pass
        return [404, 'text/plain', b'']

    def destroy(self):
        pass
