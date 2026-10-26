# -*- coding: utf-8 -*-
"""
ow63.com（AV Discovery）TVBox/Hawk 源 —— Hawk 兼容纯标准库版

站点特性：
  1. 首访有 JS 验证门，带 Cookie `_slide_passed=1` 可直接通过
  2. 全站页面 hex 混淆：document.write(FN1(unescape(FN2("HEX","%"))))
     Python 等价：bytes.fromhex(hex).decode('utf-8')，函数名每页随机，故用长 hex 串定位
  3. 视频地址在详情页 videoData JSON 中：
     - JAV（sourceType=missav）：m3cdn.playergo.top 的 master m3u8（多码率，分片 .jpeg 实为 TS）
     - 国产（sourceType=guochan）：v.didibo2.com 的 index.m3u8
  4. 部分 JAV 条目只有预览播放列表（单分片真 JPEG，8 秒），需过滤，见 _probe_playlist

纯标准库实现（urllib + 正则），无 requests/bs4 依赖；
接口按 Hawk（海阔视界）Python 蜘蛛规范补齐：getName / init / homeVideoContent 等核心方法。
"""

import re
import json
import ssl
import gzip
import zlib
import html as _htmlmod
import urllib.request
import urllib.parse

try:
    from base.spider import Spider
except ImportError:
    # Hawk（海阔视界）等客户端无 base 包，用同名桩类兜底，保证 class Spider(Spider) 结构不变
    class Spider(object):
        def getCache(self, key): return None
        def setCache(self, key, value): return "fail"
        def delCache(self, key): return "fail"


HOSTS = ['https://ow63.com', 'https://fagjil.asia', 'https://www.izo440.sbs']
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')
PASS_COOKIE = '_slide_passed=1'
TIMEOUT = 10

# 分类表：type_id 为站内路径（browse/<id> 或特殊页），翻页规则 /page/<n>?order=latest
CATS = [
    ('new-release', '最近更新'),
    ('trending', '热门'),
    ('browse/44041', '日本无码'),
    ('browse/44050', '日本有码'),
    ('browse/44002', '中文字幕'),
    ('browse/44006', '三级伦理'),
    ('browse/44090', '国产'),
    ('browse/44011', '麻豆传媒'),
    ('browse/44091', '主播视讯'),
    ('browse/44092', '蜜桃影像传媒'),
    ('browse/44093', '其他传媒'),
    ('browse/44094', '欧美性爱'),
    ('browse/44095', '黑料事件'),
    ('browse/44096', '91制片厂'),
    ('browse/44097', '台湾swag'),
    ('browse/44098', '精东影业'),
    ('browse/44099', '天美传媒'),
    ('browse/44100', '美女写真'),
    ('browse/44101', '糖心Vlog'),
    ('browse/44102', '星空无限传媒'),
    ('browse/44103', '葫芦影业'),
    ('browse/44104', '中字无码'),
    ('browse/44106', '中字有码'),
    ('browse/44107', '女同系列'),
    ('browse/44015', 'SM调教'),
    ('browse/43997', '卡通动漫'),
    ('browse/44300', '水果派解说'),
    ('browse/44315', '国产厂商'),
]

CARD_RE = re.compile(
    r'<a href="(/zh/screen/[^"]+)"\s+title="([^"]*)">\s*'
    r'<img src="([^"]+)"[^>]*>\s*</a>(.*?)</div>', re.S)
DURATION_RE = re.compile(r'video-duration[^>]*>\s*([^<]+?)\s*<', re.S)
HEX_BODY_RE = re.compile(r'"([0-9a-fA-F]{500,})"')


def decode_page(raw):
    """页面 hex 混淆解码；无混淆则原样返回"""
    if not raw:
        return raw or ''
    if 'videoData' in raw or '/zh/screen/' in raw:
        return raw
    m = HEX_BODY_RE.search(raw)
    if m:
        try:
            dec = bytes.fromhex(m.group(1)).decode('utf-8')
            if len(dec) > 1000:
                return dec
        except Exception:
            pass
    return raw


def extract_video_data(text):
    """从详情页提取 videoData JSON（平衡括号，兼容字符串内含括号）"""
    i = text.find('videoData')
    if i < 0:
        return None
    j = text.find('{', i)
    if j < 0:
        return None
    depth = 0
    k = j
    in_str = False
    esc = False
    n = len(text)
    while k < n:
        c = text[k]
        if esc:
            esc = False
        elif c == '\\':
            esc = True
        elif c == '"':
            in_str = not in_str
        elif not in_str:
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[j:k + 1])
                    except Exception:
                        return None
        k += 1
    return None


def _first_img(v):
    if isinstance(v, list):
        if not v:
            return ''
        v = v[0]
    if isinstance(v, dict):
        v = v.get('img') or v.get('src') or ''
    return v if isinstance(v, str) else ''


class Spider(Spider):

    def __init__(self):
        # Hawk 框架不保证调用 __init__，真正初始化放在 init()，公开方法前统一 _ensure()
        self._ready = False

    # ---------- Hawk/T4 核心方法 ----------

    def getName(self):
        return 'ow63'

    def init(self, extend=''):
        if getattr(self, '_ready', False):
            return
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE
        self._ctx.set_ciphers('DEFAULT@SECLEVEL=1')
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self._ctx))
        self._ready = True

    def _ensure(self):
        if not getattr(self, '_ready', False):
            self.init('')

    # ---------- HTTP 层 ----------

    def _fetch(self, url, referer=None, timeout=TIMEOUT, limit=None):
        """url 为站内路径时按域名池轮换；绝对 URL（CDN）直接请求。
        返回 (status_code, text)；失败返回 (None, 错误信息)"""
        if url.startswith('http'):
            candidates = [url]
            ref = referer or 'https://ow63.com/'
        else:
            candidates = [h + url for h in HOSTS]
            ref = referer or (HOSTS[0] + '/zh/')
        last_err = ''
        for u in candidates:
            try:
                req = urllib.request.Request(u, headers={
                    'User-Agent': UA,
                    'Referer': ref,
                    'Cookie': PASS_COOKIE,
                    'Accept': 'text/html,application/json,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9',
                })
                with self._opener.open(req, timeout=timeout) as r:
                    raw = r.read(limit) if limit else r.read()
                    ctype = (r.headers.get('Content-Encoding') or '').lower()
                    try:
                        if 'gzip' in ctype or raw[:2] == b'\x1f\x8b':
                            raw = gzip.decompress(raw)
                        elif 'deflate' in ctype or raw[:2] in (b'\x78\x9c', b'\x78\x01', b'\x78\xda'):
                            raw = zlib.decompress(raw)
                    except Exception:
                        pass
                    charset = None
                    ct = r.headers.get('Content-Type') or ''
                    m = re.search(r'charset=([\w-]+)', ct, re.I)
                    if m:
                        charset = m.group(1)
                    if not charset or charset.lower() in ('iso-8859-1', 'ascii', 'latin-1'):
                        charset = 'utf-8'
                    try:
                        return r.status, raw.decode(charset, errors='replace')
                    except (LookupError, UnicodeDecodeError):
                        return r.status, raw.decode('utf-8', errors='replace')
            except Exception as e:
                last_err = str(e)
        return None, last_err

    def _get_page(self, path):
        """请求站内页面并做 hex 解码，返回明文；失败返回 ''"""
        code, text = self._fetch(path)
        if code is None:
            return ''
        return decode_page(text)

    # ---------- 解析 ----------

    def _parse_cards(self, text):
        vods = []
        if not text:
            return vods
        for m in CARD_RE.finditer(text):
            href, title, pic, rest = m.groups()
            dur = DURATION_RE.search(rest)
            vods.append({
                'vod_id': href,
                'vod_name': _htmlmod.unescape(title).strip(),
                'vod_pic': pic,
                'vod_remarks': _htmlmod.unescape(dur.group(1)).strip() if dur else '',
            })
        return vods

    def _home_vods(self):
        try:
            return self._parse_cards(self._get_page('/zh/new-release'))[:20]
        except Exception:
            return []

    # ---------- Hawk/T4 接口 ----------

    def homeContent(self, filter=False):
        self._ensure()
        classes = [{'type_id': t, 'type_name': n} for t, n in CATS]
        return {'class': classes, 'list': self._home_vods()}

    def homeVideoContent(self):
        self._ensure()
        return {'list': self._home_vods()}

    def categoryContent(self, tid, pg, filter=False, extend=None):
        self._ensure()
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1
        if pg <= 1:
            path = '/zh/%s?order=latest' % tid
        else:
            path = '/zh/%s/page/%d?order=latest' % (tid, pg)
        vods = self._parse_cards(self._get_page(path))
        # 站点为无限滚动、HTML 无分页器：有内容即预告还有下一页，空页自终止
        return {
            'list': vods,
            'page': pg,
            'pagecount': pg + 1 if vods else pg,
            'limit': len(vods),
            'total': len(vods),
        }

    def searchContent(self, key, quick, pg=''):
        self._ensure()
        path = '/zh/lookup?keyword=' + urllib.parse.quote(key)
        vods = self._parse_cards(self._get_page(path))
        return {'list': vods}

    def detailContent(self, ids=''):
        self._ensure()
        vid = ids[0] if isinstance(ids, (list, tuple)) else ids
        vid = vid.strip().lstrip('/')
        if vid.startswith('zh/screen/'):
            vid = vid[len('zh/screen/'):]
        page_path = '/zh/screen/' + vid
        text = self._get_page(page_path)
        d = extract_video_data(text) if text else None
        if not d:
            return {'list': []}

        title = (d.get('title') or vid).strip()
        pic = d.get('thumbnail_loc') or d.get('preview') or d.get('images') or ''
        pic = _first_img(pic)
        duration = d.get('duration') or ''
        fanhao = d.get('fanhao') or ''
        stype = d.get('sourceType') or ''

        # 简介
        desc_lines = []
        if fanhao:
            desc_lines.append('番号：' + fanhao)
        actors = d.get('actor') or d.get('actors') or []
        if isinstance(actors, list) and actors:
            desc_lines.append('演员：' + '、'.join(str(a) for a in actors[:6]))
        maker = d.get('makers') or d.get('maker') or d.get('studio') or ''
        if maker:
            desc_lines.append('厂商：' + str(maker))
        if d.get('faxing'):
            desc_lines.append('发行：' + str(d.get('faxing')))
        if d.get('release_date'):
            desc_lines.append('发布：' + str(d.get('release_date')))
        if d.get('rating'):
            desc_lines.append('评分：' + str(d.get('rating')))
        if d.get('view_count'):
            desc_lines.append('播放：' + str(d.get('view_count')))
        tags = d.get('genres') or d.get('tag') or d.get('tags') or []
        if isinstance(tags, list) and tags:
            desc_lines.append('标签：' + '、'.join(str(t) for t in tags[:10]))
        sdesc = d.get('s_description') or ''
        if sdesc:
            desc_lines.append('简介：' + str(sdesc))
        vod_content = '<br/>'.join(desc_lines)

        # 播放线路：详情页 URL 交给 playerContent 现取（verify 签名有时效）
        vurl = d.get('video_url') or ''
        play_url = ''
        remark_tag = ''
        if vurl:
            if 'playergo.top' in vurl or stype == 'missav':
                code, txt = self._probe_playlist(vurl)
                if code == 200 and '#EXT-X-STREAM-INF' in txt:
                    play_url = page_path
                    remark_tag = '在线'
                elif code == 200:
                    remark_tag = '仅预览'
                else:
                    # 预检失败（网络问题）不阻拦，放行让播放器尝试
                    play_url = page_path
                    remark_tag = '在线'
            else:
                play_url = page_path
                remark_tag = '在线'

        remarks = ' / '.join(x for x in [duration, fanhao, remark_tag] if x)
        vod = {
            'vod_id': page_path,
            'vod_name': title,
            'vod_pic': pic,
            'vod_remarks': remarks,
            'vod_content': vod_content,
            'vod_play_from': 'ow63',
            'vod_play_url': play_url,
        }
        return {'list': [vod]}

    def playerContent(self, flag='', id='', vipFlags=None):
        self._ensure()
        url = id[0] if isinstance(id, (list, tuple)) else id
        url = (url or '').strip()
        vurl = ''
        if '/zh/screen/' in url:
            # 由详情页 URL 现取最新 video_url（verify 签名有时效性）
            path = url[url.find('/zh/screen/'):]
            text = self._get_page(path)
            d = extract_video_data(text) if text else None
            if d:
                vurl = d.get('video_url') or ''
        elif url:
            vurl = url
        if not vurl:
            return {'parse': 0, 'url': '', 'msg': '未找到播放地址'}
        if 'playergo.top' in vurl:
            code, txt = self._probe_playlist(vurl)
            if code == 200 and '#EXT-X-STREAM-INF' not in txt:
                return {'parse': 0, 'url': '', 'msg': '该条目暂无在线播放源（仅预览图）'}
        return {
            'parse': 0,
            'url': vurl,
            'header': {
                'Referer': 'https://ow63.com/',
                'User-Agent': UA,
            },
        }

    def isVideoFormat(self, url):
        """供壳判断是否为可直接播放的媒体格式"""
        return bool(re.search(r'\.(?:m3u8|mp4|ts|flv|mkv)(?:\?|$)', url or '', re.I))

    def manualVideoCheck(self):
        """不需要手动核验；预检已在 detailContent/playerContent 内完成"""
        return False

    # ---------- 客户端契约桩（TVBox v2.1 裸类契约，本源自带全字段无需依赖） ----------

    def getDependence(self):
        """无外部依赖（纯标准库）"""
        return []

    def localProxy(self, params):
        """播放地址均为直链（parse:0 + header），不走本地代理；
        真被调用时返回合规四元组，避免壳端解析崩溃"""
        return [404, 'text/plain', b'', {}]

    def action(self, action):
        return None

    def destroy(self):
        return None

    def _probe_playlist(self, vurl):
        """拉取 m3u8 前 4096 字节判断是否为真流（含 STREAM-INF）还是预览（单分片 JPEG）"""
        try:
            code, text = self._fetch(vurl, limit=4096)
        except Exception:
            return None, ''
        return code, text
