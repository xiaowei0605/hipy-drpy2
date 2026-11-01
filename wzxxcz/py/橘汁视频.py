# -*- coding: utf-8 -*-
"""
橘汁视频 juziapp.hzhcbkj.cn | TVBox Python 爬虫 

为什么原版一片空白(实测结论):
  1) /api/proto/v5/* 全部要求二次签名 sig, 而签名公钥由 /api/v5/find/app/zone 下发;
     现在该接口返回 code=100016「二级公钥为空,请配置」→ 加密通道整体废掉,
     _list / detail / search / videoUsableUrl 一定拿不到数据(空列表根因)。
  2) 网页路由 /index.php/vod/* 全部 302 到 /user/login.html — 站点已关前台。
  3) 全站仅剩的明文可用接口: /api/v3/drama/getCategory (分类+原生筛选),
     /api/ex/v3/user/history (公共观看记录, 带可回放的 videoUrl),
     /api/ex/v3/drama/list (线路 → 解析源配置)。

本版策略:
  ★ 自动嗅探: 每次启动先探测 zone, 一旦站点恢复加密通道, 自动切回 protobuf 通道(全量列表)
  ★ 内容源: 公共观看记录(真人看过的整剧) + 播放线路解析源 -> 详情/分集/直链
  ★ 分类筛选沿用站点 converUrl 原生面板(类型/地区/语言/年份/主演/导演/状态/版本/排序)
  ★ 简介统一加 INTRO_PREFIX; 集名 "第01集"→"01"; 线路 超高清>蓝光>其余 排序
"""
import re
import sys
import json
import time
import base64
import string
import random
import hashlib
import urllib.parse

sys.path.append('..')

try:
    from base.spider import Spider as _Base
except ImportError:
    import ssl
    import urllib.request as _ur

    class _Base:
        def _http(self, url, data=None, headers=None):
            req = _ur.Request(url, data=data, headers=headers or {})
            ctx = ssl._create_unverified_context()
            return _ur.urlopen(req, timeout=25, context=ctx).read()

        def log(self, *a, **kw):
            try:
                print("[juzhi]", *a)
            except Exception:
                pass


# ===================== 常量 =====================
HOST = 'https://juziapp.hzhcbkj.cn'
UA = 'okhttp/3.12.1'
WEB_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
VC = '3024'
VNAME = '3.0.2.4'
PKG = 'com.mxj.wylcjbxyx'
PUBLIC_USER = 'fzcrym'          # 站点公共观看记录账号

INTRO_PREFIX = "🍊小橙子为您介绍剧情👉请不要相信视频中的广告，以免上当受骗！"

PUB1_B64 = ('MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCr8SzZhjYy+rsya1K09t8d2K50pWFo'
            'BkgUqMpKOiW+3IEVKd4eTdvg9RSOjQ82kypL6R9BnsmrS1V8s4PVDwjQbUtYhTPPC9Hz'
            '16qY7rpD6m0d2vr09/UpWQ5uOy9PR0QTrsioveZ+DIe9jc3C+zBCu/kZSY/R8stwJoiit'
            'ki3gwIDAQAB')
NATIVE_K = b'ed5fdsgucxumegqa'
SAFE = b'OC1A06E197EF10CF3F6058CA7A803B5E'
PW_SAFE = b'11GK2we32144LO&hilUITB)FMd1khdaF'
CERT_MD5 = '090DA8F91D3F60CC6CB250D86F06FE12'
CERT_SHA1 = '3DADB42485B7F864E766479ADA6B1176D81D8D73'


def _mk_safecode():
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import pad
        _e = base64.b64encode(AES.new(PW_SAFE, AES.MODE_ECB).encrypt(pad(
            (CERT_MD5 + '######' + CERT_SHA1 + '~~~~~~' + PKG + '>>>+++' +
             VC).encode(), 16))).decode()
        _e2 = base64.b64encode(_e.encode()).decode()
        return (_e2[:16] + _e2[-16:]).upper()
    except Exception:
        return ''


SAFECODE = _mk_safecode()

# ===================== 正则 =====================
_RE_TAG = re.compile(r'<[^>]+>')
_RE_EP_NUM = re.compile(r'^第?0*(\d{1,4})[集话期](?:完结)?$')
_RE_MEDIA = re.compile(
    r'(?i)^https?://[^\s]+?\.(mp4|m3u8|flv|mkv|avi|ts|mov|mpd|m4a|wmv)(\?.*)?$')
_RE_URL_IN_TEXT = re.compile(
    r'https?://[\x21-\x7e]+?\.(?:m3u8|mp4)(?:\?[\x21-\x7e]*)?', re.I)
_RE_EPMARK = re.compile(
    r'(更新至第?\s*0*\d{1,4}\s*[集话期]|全\s*0*\d{1,4}\s*[集话期]|'
    r'第?\s*0*\d{1,4}\s*[集话期]\s*[完结局]?|完结|连载中)')

_SORT_MAP = {'最新': 'time', '最热': 'hits', '好评': 'score'}
_DEF_FILTERS = {
    '20': ['喜剧', '爱情', '恐怖', '动作', '科幻', '剧情', '战争', '警匪',
           '犯罪', '动画', '奇幻', '武侠', '冒险', '枪战', '悬疑', '惊悚',
           '经典', '青春', '文艺', '微电影', '古装', '历史', '运动', '农村',
           '儿童', '网络电影'],
    '21': ['古装', '战争', '青春', '偶像', '喜剧', '家庭', '犯罪', '动作',
           '奇幻', '剧情', '历史', '经典', '乡村', '情景', '商战', '网剧', '其他'],
    '22': ['真人秀', '脱口秀', '访谈', '选秀', '情感', '旅游', '音乐', '美食',
           '竞技', '益智', '晚会', '游戏'],
    '23': ['冒险', '热血', '奇幻', '恋爱', '搞笑', '治愈', '机战', '校园',
           '运动', '悬疑', '推理', '日常'],
    '24': ['霸总', '逆袭', '甜宠', '穿越', '重生', '复仇', '战神', '萌宝',
           '古装', '都市'],
    '25': ['卫视', '央视', '体育', '影视', '少儿', '纪录', '音乐', '戏曲'],
    '26': ['玄幻', '热血', '恋爱', '搞笑', '冒险', '古风'],
    '27': ['影评', '资讯', '榜单', '花絮'],
}
_CAT_CACHE = {'ts': 0, 'data': None}
_HIST_CACHE = {'ts': 0, 'data': []}


# ===================== 工具函数 =====================
def _clean(s):
    if not s:
        return ''
    s = re.sub(r'<br\s*/?>', '\n', s, flags=re.I)
    s = _RE_TAG.sub('', s)
    s = (s.replace('&nbsp;', ' ').replace('\xa0', ' ')
          .replace('&amp;', '&').replace('&quot;', '"')
          .replace('&#39;', "'").replace('&lt;', '<').replace('&gt;', '>'))
    s = re.sub(r'[ \t\r\f\v]+', ' ', s)
    s = re.sub(r'\n{2,}', '\n', s)
    return s.strip()


def _norm_ep(title):
    if not title:
        return ''
    m = _RE_EP_NUM.match(str(title).strip())
    return m.group(1) if m else str(title).strip()


def _split_list(s):
    if not s:
        return []
    if isinstance(s, (list, tuple)):
        return [str(x).strip() for x in s if str(x).strip()]
    return [x.strip() for x in re.split(r'[,，/|]', str(s)) if x.strip()]


def _varint(n):
    b = b''
    while True:
        x = n & 0x7f
        n >>= 7
        if n:
            b += bytes([x | 0x80])
        else:
            return b + bytes([x])


def _f(num, wire, payload):
    t = _varint((num << 3) | wire)
    if wire == 2:
        return t + _varint(len(payload)) + payload
    return t + payload


def _pb(buf):
    out = []
    i = 0
    n = len(buf)
    while i < n:
        b = buf[i]
        fn, wt = b >> 3, b & 7
        i += 1
        if wt == 0:
            v = 0
            sh = 0
            while i < n:
                x = buf[i]
                i += 1
                v |= (x & 0x7f) << sh
                sh += 7
                if not x & 0x80:
                    break
            out.append((fn, wt, v))
        elif wt == 2:
            ln = 0
            sh = 0
            while i < n:
                x = buf[i]
                i += 1
                ln |= (x & 0x7f) << sh
                sh += 7
                if not x & 0x80:
                    break
            out.append((fn, wt, buf[i:i + ln]))
            i += ln
        elif wt == 5:
            out.append((fn, wt, buf[i:i + 4]))
            i += 4
        elif wt == 1:
            out.append((fn, wt, buf[i:i + 8]))
            i += 8
        else:
            i += 1
    return out


def _pic_pick(v):
    cands = [x.decode('utf-8', 'replace')
             for _, w, x in _pb(v) if w == 2 and x.startswith(b'http')]
    if cands:
        return next((u for u in cands if u.startswith('https')), cands[0])
    return ''


def _rnd(k):
    CH = string.ascii_letters + string.digits
    return ''.join(random.sample(list(CH), k - 1)) + '='


class Spider(_Base):
    HOST_NAME = '橘汁视频'

    _cur_id = ''

    # ---------- 生命周期 ----------
    def getName(self):
        return '橘汁视频'

    def init(self, extend=''):
        try:
            self.extend = json.loads(extend) if extend else {}
        except Exception:
            self.extend = {}
        self.site_url = (self.extend.get('site') or HOST).rstrip('/')
        self.udid = hashlib.md5(
            str(time.time()).encode()).hexdigest()[:16].upper()
        self._token = ''
        self._rsa1 = None
        self._rsa2 = None
        self._lines = []
        self._play_cache = {}
        self._login()
        self._zone()
        self._load_lines()
        self.log('init: site=%s udid=%s token=%s proto=%s lines=%d' % (
            self.site_url, self.udid, '有' if self._token else '无',
            '可用' if self._rsa2 else '不可用', len(self._lines)))

    def destroy(self):
        pass

    def close(self):
        self.destroy()

    def isVideoFormat(self, url):
        return True

    def isTextFormat(self, url):
        return False

    # ---------- 网络 ----------
    def _http(self, url, data=None, headers=None):
        import ssl
        import urllib.request
        req = urllib.request.Request(url, data=data, headers=headers or {})
        ctx = ssl._create_unverified_context()
        return urllib.request.urlopen(req, timeout=25, context=ctx).read()

    def _json(self, url, headers=None):
        try:
            h = {'User-Agent': UA, 'Accept': 'application/json'}
            if headers:
                h.update(headers)
            return json.loads(self._http(url, None, h))
        except Exception as e:
            self.log('JSON FAIL %s -> %s' % (url, e))
            return {}

    # ---------- 登录 / 通道探测 ----------
    def _login(self):
        try:
            body = json.dumps({
                'username': 'tv_%s' % self.udid[:10].lower(),
                'password': hashlib.md5(('tv' + self.udid).encode()).hexdigest(),
                'udid': self.udid}).encode()
            try:
                self._http(self.site_url + '/api/ex/v3/user/register', body, {
                    'User-Agent': UA, 'Content-Type': 'application/json'})
            except Exception:
                pass
            d = self._http(self.site_url + '/api/ex/v3/user/login', body, {
                'User-Agent': UA, 'Content-Type': 'application/json'})
            data = json.loads(d).get('data') or {}
            self._token = (data.get('token') or
                           (data.get('user') or {}).get('token') or '')
        except Exception as e:
            self.log('登录失败: %s' % e)
            self._token = ''

    def _zone(self):
        self._rsa2 = None
        try:
            from Crypto.PublicKey import RSA
            from Crypto.Cipher import PKCS1_v1_5
            self._rsa1 = PKCS1_v1_5.new(
                RSA.import_key(base64.b64decode(PUB1_B64)))
            ts = int(time.time() * 1000)
            rnd = _rnd(16)
            sign = base64.b64encode(
                self._rsa1.encrypt((str(ts) + rnd).encode())).decode()
            body = (_f(1, 0, _varint(ts)) + _f(2, 2, sign.encode()) +
                    _f(3, 2, rnd.encode()) + _f(4, 2, rnd.encode()) +
                    _f(5, 2, rnd.encode()))
            P = {'plat': 'android', 'vOs': '16', '_vOsCode': '36',
                 'vApp': VC, 'vName': VNAME, 'pkg': PKG,
                 'appName': '%E6%A9%98%E6%B1%81', 'udid': self.udid,
                 'uuid': self.udid, 'chid': '10000',
                 'androidID': self.udid, 'net': '1', 'young': 0,
                 'tenantId': '*', 'v': 1, 'device': 0, 'lang': 'zh',
                 'country': 'CN', 'cpu': 'arm64-v8a'}
            d = self._http(self.site_url + '/api/v5/find/app/zone', body, {
                'User-Agent': UA, 'Content-Type': 'application/x-protobuf',
                'Accept': 'application/x-protobuf',
                'Cache-Control': 'no-cache',
                'publicParams': json.dumps(P, separators=(',', ':'))})
            top = _pb(d)
            code = [v for fn, wt, v in top if fn == 1 and wt == 0]
            inners = [v for fn, wt, v in top if fn == 3 and wt == 2]
            c = code[0] if code else 0
            if c != 200 or not inners:
                msg = [v for fn, wt, v in top if fn == 2 and wt == 2]
                self.log('zone 不可用(code=%s msg=%s) -> 明文通道' % (
                    c, msg[0].decode('utf-8', 'replace') if msg else ''))
                return
            strs = {fn: v for fn, wt, v in _pb(inners[0]) if wt == 2}
            self._rsa2 = PKCS1_v1_5.new(RSA.import_key(base64.b64decode(
                strs[2] + strs[3] + strs[4] + strs[5])))
            self.log('zone: 加密通道可用')
        except Exception as e:
            self.log('zone 跳过: %s' % e)
            self._rsa2 = None

    def _hdr(self):
        ts = int(time.time() * 1000)
        rnd = _rnd(16)
        sig = ''
        if self._rsa2:
            try:
                sig = base64.b64encode(
                    self._rsa2.encrypt((str(ts) + rnd + VC).encode())).decode()
            except Exception:
                sig = ''
        try:
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import pad
            ao = base64.b64encode(AES.new(SAFE, AES.MODE_ECB).encrypt(
                pad((str(ts) + rnd).encode(), 16))).decode()
        except Exception:
            ao = ''
        J = {'country': 'CN', 'vName': VNAME, 'cpuId': '', 'young': 0,
             'facturer': 'OnePlus', 'pkg': PKG, 'uuid': self.udid,
             'resolution': '1080x2256',
             'mac': '02%3A00%3A00%3A00%3A00%3A00', 'sig': sig, 'abid': '7470',
             'model': 'PJX110', 'plat': 'android', 'udid': self.udid,
             'dpi': '480', 'net': '1', 'lang': 'zh', 'random_str': rnd,
             'brand': 'OnePlus', 'timestamp': ts, 'density': '3.0',
             'appName': '%E6%A9%98%E6%B1%81', 'cpu': 'arm64-v8a',
             'chid': '10000', 'carrier': '%E8%81%94%E9%80%9A',
             'sig2': ao[:8], 'v': 1, 'sig3': ao[8:], 'tenantId': '*',
             '_vOsCode': '36', 'vOs': '16', 'vApp': VC, 'device': 0,
             'androidID': self.udid}
        blob = json.dumps(J, separators=(',', ':'),
                          ensure_ascii=False).encode()
        try:
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import pad
            pd_hex = AES.new(NATIVE_K, AES.MODE_CBC, NATIVE_K).encrypt(
                pad(blob, 16)).hex()
        except Exception:
            pd_hex = ''
        h = {'User-Agent': UA, 'Accept': 'application/json',
             'Cache-Control': 'no-cache',
             'publicParams': json.dumps({'paramsData': pd_hex},
                                        separators=(',', ':'))}
        if self._token:
            h['token'] = self._token
        return h

    def _secure(self, qs):
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import pad
        ts = int(time.time() * 1000)
        rnd8 = _rnd(8)
        ct = AES.new(SAFECODE.encode(), AES.MODE_ECB).encrypt(
            pad((qs + str(ts)).encode(), 16))
        b64 = base64.b64encode(ct).decode()
        return (_f(1, 2, (rnd8 + b64[:12]).encode()) +
                _f(2, 2, b64[12:].encode()) +
                _f(3, 2, _rnd(20).encode()) +
                _f(4, 0, _varint(ts)) +
                _f(5, 2, rnd8.encode()))

    def _proto(self, path, qs):
        """加密通道请求; 通道不可用直接返回 (0, b'')"""
        if not self._rsa2:
            return 0, b''
        try:
            hh = self._hdr()
            hh['Content-Type'] = 'application/x-protobuf'
            hh['Accept'] = 'application/x-protobuf'
            d = self._http(self.site_url + path, self._secure(qs), hh)
            top = _pb(d)
            code = [v for fn, wt, v in top if fn == 1 and wt == 0]
            datas = [v for fn, wt, v in top if fn == 3 and wt == 2]
            return ((code[0] if code else 0), datas[0] if datas else b'')
        except Exception as e:
            self.log('proto FAIL %s -> %s' % (path, e))
            return 0, b''

    # ---------- 播放线路(解析源) ----------
    def _load_lines(self):
        """从 /api/ex/v3/drama/list 拿每条线路的解析接口"""
        self._lines = []
        j = self._json(self.site_url + '/api/ex/v3/drama/list')
        for it in (j.get('data') or []):
            name = it.get('playerName') or it.get('key') or ''
            cfgs = []
            try:
                cfgs = json.loads(it.get('config') or '[]')
            except Exception:
                cfgs = []
            for c in cfgs:
                u = c.get('url') or ''
                if u.startswith('http'):
                    cfgs = cfgs  # keep
            urls = [c.get('url') for c in cfgs
                    if isinstance(c, dict) and str(c.get('url') or '').startswith('http')]
            if urls:
                self._lines.append({'key': it.get('key') or '',
                                    'name': name,
                                    'apis': urls})
                self.log('  线路: %s -> %s' % (name, urls[0][:60]))
        if not self._lines:
            self.log('  线路表为空, 使用内置解析源')
            self._lines = [
                {'key': 'zijianm3u8', 'name': '自建4K-2',
                 'apis': ['https://vip1.hzhcbkj.cn/api/?key='
                          '4d003bfa320423f6a5bf432a59e1f329&url=']},
                {'key': 'NB4K', 'name': '自建4K',
                 'apis': ['http://jzjxbk.hzhcbkj.cn/KZNBJX.php?url=']},
            ]
        return self._lines

    def _parse_play(self, line, vid):
        """调用线路解析源把 videoUrl 换成真实 m3u8/mp4"""
        for api in (line.get('apis') or []):
            for q in ('%s|%s' % (vid, line.get('name') or ''),
                      vid,
                      '%s|%s' % (line.get('name') or '', vid)):
                url = api + urllib.parse.quote(q, safe='')
                try:
                    d = self._http(url, None, {'User-Agent': UA})
                    txt = d.decode('utf-8', 'ignore')
                except Exception as e:
                    self.log('    解析源失败: %s' % e)
                    continue
                try:
                    j = json.loads(txt)
                except Exception:
                    j = {}
                if j:
                    for k in ('url', 'data', 'playUrl', 'm3u8'):
                        v = j.get(k)
                        if isinstance(v, str) and v.startswith('http'):
                            return v
                        if isinstance(v, dict):
                            for kk in ('url', 'playUrl', 'm3u8'):
                                vv = v.get(kk)
                                if isinstance(vv, str) and vv.startswith('http'):
                                    return vv
                    if j.get('code') not in (200,):
                        self.log('    解析返回: %s' % (j.get('msg') or '')[:40])
                m = _RE_URL_IN_TEXT.search(txt)
                if m:
                    return m.group(0)
        return ''

    # ---------- 分类 / 筛选 ----------
    def _load_cats(self):
        now = time.time()
        if _CAT_CACHE['data'] and now - _CAT_CACHE['ts'] < 3600:
            return _CAT_CACHE['data']
        cats = []
        j = self._json(self.site_url +
                       '/api/v3/drama/getCategory?orderBy=type_id')
        for c in (j.get('data') or []):
            tid = str(c.get('id') or '')
            if not tid or tid == '29':
                continue
            raw = c.get('converUrl') or ''
            filt = {}
            if raw:
                try:
                    filt = json.loads(raw)
                    if isinstance(filt, str):
                        filt = json.loads(filt)
                except Exception:
                    filt = {}
            cats.append({'type_id': tid,
                         'type_name': c.get('name') or tid,
                         'filter': filt or {}})
        if not cats:
            cats = [{'type_id': t, 'type_name': n, 'filter': {}}
                    for t, n in [('20', '电影'), ('21', '剧集'), ('22', '综艺'),
                                 ('23', '动漫'), ('24', '短剧'), ('25', '直播'),
                                 ('26', '漫剧'), ('27', '文章')]]
        _CAT_CACHE['data'] = cats
        _CAT_CACHE['ts'] = now
        return cats

    def _build_filters(self, filt, tid):
        out = []
        spec = [('class', '类型'), ('area', '地区'), ('lang', '语言'),
                ('year', '年份'), ('star', '主演'), ('director', '导演'),
                ('state', '状态'), ('version', '版本')]
        for key, name in spec:
            vals = _split_list(filt.get(key))
            if not vals and key == 'class':
                vals = _DEF_FILTERS.get(tid) or []
            if not vals:
                continue
            out.append({'key': key, 'name': name,
                        'value': [{'n': '全部', 'v': ''}] +
                                 [{'n': x, 'v': x} for x in vals]})
        sorts = _split_list(filt.get('extend_sort')) or ['最新', '最热', '好评']
        out.append({'key': 'sort', 'name': '排序',
                    'value': [{'n': s, 'v': _SORT_MAP.get(s, s)}
                              for s in sorts]})
        return out

    def homeContent(self, filter=False):
        cats = self._load_cats()
        classes = [{'type_id': c['type_id'], 'type_name': c['type_name']}
                   for c in cats]
        classes.append({'type_id': 'history', 'type_name': '最近在看'})
        filters = {c['type_id']: self._build_filters(c['filter'], c['type_id'])
                   for c in cats}
        self.log('首页分类: %s' % [c['type_name'] for c in classes])
        return {'class': classes, 'filters': filters}

    def homeVideoContent(self):
        vids = self._probe_list() or self._history_list()
        self.log('首页推荐: %d 条' % len(vids))
        return {'list': vids}

    # ---------- 观看记录(主内容源) ----------
    def _history_raw(self):
        now = time.time()
        if _HIST_CACHE['data'] and now - _HIST_CACHE['ts'] < 180:
            return _HIST_CACHE['data']
        j = self._json('%s/api/ex/v3/user/history?username=%s' % (
            self.site_url, PUBLIC_USER))
        data = j.get('data') or []
        _HIST_CACHE['data'] = data
        _HIST_CACHE['ts'] = now
        return data

    def _history_list(self):
        out = []
        for it in self._history_raw():
            name = it.get('videoName') or ''
            if not name:
                continue
            frm = (it.get('videoId') or '').split('|')[0] or '正片'
            ep = it.get('videoPart') or ''
            vid = it.get('videoUrl') or ''
            did = it.get('videoDramaId') or 0
            out.append({
                'vod_id': 'h$%s$%s$%s$%s' % (did, frm, ep, vid),
                'vod_name': name,
                'vod_pic': it.get('videoCover') or '',
                'vod_remarks': ('%s·第%s集' % (frm, ep)) if ep else frm,
            })
        self.log('最近在看: %d 条' % len(out))
        return out

    # ---------- 加密通道列表(站点恢复后自动启用) ----------
    def _probe_list(self):
        if not self._rsa2:
            return []
        out = self._list_proto('page=1&pagesize=24')
        return out

    def _list_proto(self, qs):
        out = []
        code, data = self._proto('/api/proto/v5/drama/category', qs)
        if code != 200 or not data:
            return out
        for fn, wt, v in _pb(data):
            if fn != 1 or wt != 2:
                continue
            info = {'vod_id': '', 'vod_name': '', 'vod_pic': '',
                    'vod_remarks': ''}
            for f2, w2, v2 in _pb(v):
                if f2 == 3 and w2 == 0:
                    info['vod_id'] = str(v2)
                elif f2 == 5 and w2 == 2:
                    info['vod_name'] = v2.decode('utf-8', 'replace')
                elif f2 == 2 and w2 == 2:
                    info['vod_pic'] = _pic_pick(v2)
                elif f2 == 13 and w2 == 2:
                    info['vod_remarks'] = v2.decode('utf-8', 'replace')
            if info['vod_id'] and info['vod_name']:
                out.append(info)
        return out

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        if isinstance(extend, str):
            try:
                extend = json.loads(extend)
            except Exception:
                extend = {}
        extend = extend or {}
        self.log('category: tid=%s pg=%s ext=%s' % (tid, pg, extend))

        if tid == 'history':
            vids = self._history_list()
            return {'list': vids, 'page': 1,
                    'pagecount': 1, 'limit': len(vids) or 40,
                    'total': len(vids)}

        for k in list(extend.keys()):
            if extend[k] in ('', None, '全部'):
                del extend[k]

        parts = ['page=%d' % page, 'pagesize=24', 'typeId1=%s' % tid]
        for k in ('class', 'area', 'lang', 'year', 'star', 'director',
                  'state', 'version'):
            if extend.get(k):
                parts.append('%s=%s' % (k, urllib.parse.quote(extend[k])))
        if extend.get('sort'):
            parts.append('orderBy=%s' % extend['sort'])
        qs = '&'.join(parts)

        vids = self._list_proto(qs)
        if not vids and not self._rsa2:
            # 加密通道不可用: 用观看记录兜底(至少不让页面全空)
            vids = self._history_list()
            self.log('  通道不可用, 记录兜底: %d 条' % len(vids))
            return {'list': vids, 'page': 1, 'pagecount': 1,
                    'limit': len(vids) or 24, 'total': len(vids)}
        return {'list': vids, 'page': page, 'pagecount': 9999,
                'limit': 24, 'total': 99999}

    # ---------- 搜索 ----------
    def searchContent(self, key, quick, pg='1'):
        page = int(pg) if pg else 1
        self.log('search: %s pg=%s' % (key, pg))
        out = []
        if self._rsa2:
            qs = 'page=%d&pagesize=24&searchKeys=%s' % (
                page, urllib.parse.quote(key))
            code, datas = self._proto('/api/proto/v5/drama/search', qs)
            if code == 200 and datas:
                for fn, wt, v in _pb(datas):
                    if wt != 2 or fn == 0 or fn > 100:
                        continue
                    item = {'vod_id': '', 'vod_name': '', 'vod_pic': '',
                            'vod_remarks': ''}
                    for f3, w3, v3 in _pb(v):
                        if w3 == 0 and f3 == 3:
                            item['vod_id'] = str(v3)
                        elif w3 == 2 and f3 == 5:
                            item['vod_name'] = v3.decode('utf-8', 'replace')
                        elif w3 == 2 and f3 == 2:
                            item['vod_pic'] = _pic_pick(v3)
                        elif w3 == 2 and f3 == 13:
                            item['vod_remarks'] = v3.decode('utf-8', 'replace')
                    if item['vod_id'] and item['vod_name']:
                        out.append(item)
        if not out:
            for v in self._history_list():
                if key in v['vod_name']:
                    out.append(v)
            self.log('  本地搜索: %d 条' % len(out))
        return {'list': out, 'page': page, 'pagecount': 1,
                'limit': 24, 'total': len(out)}

    def searchContentPage(self, key, quick, pg='1'):
        return self.searchContent(key, quick, pg)

    # ---------- 详情 ----------
    def detailContent(self, ids):
        if not ids:
            return {'list': []}
        vod_id = str(ids[0])
        self.log('detail: %s' % vod_id)

        # 观看记录条目: 标题/副标题/简介前缀/直链回放
        if vod_id.startswith('h$'):
            p = vod_id.split('$')
            did = p[1] if len(p) > 1 else ''
            frm = p[2] if len(p) > 2 else '正片'
            ep = p[3] if len(p) > 3 else ''
            vid = p[4] if len(p) > 4 else ''
            name, pic = '继续观看', ''
            for it in self._history_raw():
                if str(it.get('videoUrl') or '') == vid and \
                        (it.get('videoName') or ''):
                    name = it['videoName']
                    pic = it.get('videoCover') or ''
                    break
            else:
                for v in self._history_list():
                    if v['vod_id'] == vod_id:
                        name, pic = v['vod_name'], v['vod_pic']
                        break

            # 找该剧在记录里的全部条目 -> 组成线路
            lines = {}
            order = []
            for it in self._history_raw():
                if str(it.get('videoUrl') or '') != vid:
                    continue
                ln = (it.get('videoId') or '').split('|')[0] or '正片'
                if ln not in lines:
                    lines[ln] = []
                    order.append(ln)
                lines[ln].append('%s$%s' % (it.get('videoPart') or '正片',
                                            it.get('videoUrl') or ''))
            if not lines:
                lines = {frm or '正片': ['%s$%s' % (ep or '正片', vid)]}
                order = [frm or '正片']

            # 尝试用线路解析源换直链
            best = ''
            for ln in order:
                for l in self._lines:
                    if l['name'] == ln or l['key'] == ln:
                        best = self._parse_play(l, vid)
                        if best:
                            break
                if best:
                    break

            now_line = []
            for ln in order:
                items = []
                for it in lines[ln]:
                    t, u = it.split('$', 1)
                    items.append('%s$%s' % (_norm_ep(t), best or u))
                now_line.append((ln, '#'.join(items)))

            first = now_line[0][1].split('#')[0].split('$', 1)
            remarks = '第%s集' % ep if ep else '正片'
            content = INTRO_PREFIX + '\n'
            content += '线路: %s｜当前: 第%s集｜剧集ID: %s' % (
                frm, ep or '-', did or '-')
            if best:
                content += '\n已解析直链: %s' % best[:120]
            else:
                content += '\n（该条目为第三方线路码，需由播放器自动解析）'
            return {'list': [{
                'vod_id': vod_id, 'vod_name': name, 'vod_pic': pic,
                'vod_remarks': remarks,
                'vod_year': '', 'vod_area': '', 'vod_director': '',
                'vod_actor': '', 'vod_content': content,
                'vod_play_from': '$$$'.join(x[0] for x in now_line),
                'vod_play_url': '$$$'.join(x[1] for x in now_line)}]}

        # 普通 id: 走加密详情
        out = {'vod_id': vod_id}
        code, data = self._proto('/api/proto/v5/drama/getDetail', 'id=' + vod_id)
        eps = []
        if code == 200 and data:
            eps, out = self._parse_detail_proto(data, out)
        content = _clean(out.get('vod_content', ''))
        out['vod_content'] = (INTRO_PREFIX + '\n' + content) if content \
            else INTRO_PREFIX
        if eps:
            lines, order = {}, []
            for line, t, u in eps:
                if line not in lines:
                    lines[line] = []
                    order.append(line)
                lines[line].append('%s$%s' % (_norm_ep(t) or '正片', u))

            def _rank(nm):
                if '超高清' in nm or '4K' in nm.upper():
                    return 0
                if '蓝光' in nm:
                    return 1
                return 2
            order.sort(key=lambda x: (_rank(x), x))
            out['vod_play_from'] = '$$$'.join(order)
            out['vod_play_url'] = '$$$'.join('#'.join(lines[l]) for l in order)
            out['vod_remarks'] = out.get('vod_remarks') or ('共%d集' % len(eps))
        else:
            out.setdefault('vod_play_from', '橘汁')
            out.setdefault('vod_play_url', '暂无片源$http://')
            out.setdefault('vod_remarks', '暂无片源')
        for k in ('vod_name', 'vod_pic', 'vod_remarks', 'vod_director',
                  'vod_actor', 'vod_area', 'vod_year'):
            out.setdefault(k, '')
        self.log('  详情: %s | %s | %d 集' %
                 (out.get('vod_name'), out.get('vod_remarks'), len(eps)))
        return {'list': [out]}

    def _parse_detail_proto(self, data, out):
        dd = _pb(data)
        for fn, wt, v in dd:
            if fn == 0 or fn > 100:
                break
            if fn == 9 and wt == 2 and 'vod_name' not in out:
                out['vod_name'] = v.decode('utf-8', 'replace')
            elif fn == 1 and wt == 2 and 'vod_area' not in out:
                out['vod_area'] = v.decode('utf-8', 'replace')
            elif fn == 12 and wt == 2 and 'vod_director' not in out:
                out['vod_director'] = _clean(v.decode('utf-8', 'replace'))
            elif fn == 16 and wt == 2 and 'vod_actor' not in out:
                out['vod_actor'] = _clean(
                    v.decode('utf-8', 'replace')).lstrip(' ,')
            elif fn == 25 and wt == 2 and 'vod_actor' not in out:
                out['vod_actor'] = _clean(v.decode('utf-8', 'replace'))
            elif fn == 6 and wt == 2 and 'vod_content' not in out:
                out['vod_content'] = _clean(v.decode('utf-8', 'replace'))
            elif fn == 2 and wt == 2 and 'vod_pic' not in out:
                out['vod_pic'] = _pic_pick(v)

        eps = []
        pos = 0
        n = len(data)
        while True:
            j = data.find(b'\xea\x01', pos)
            if j < 0:
                break
            k = j + 2
            ln = 0
            sh = 0
            while k < n and data[k] & 0x80:
                ln |= (data[k] & 0x7f) << sh
                sh += 7
                k += 1
            if k >= n:
                break
            ln |= (data[k] & 0x7f) << sh
            k += 1
            if ln <= 0 or k + ln > n:
                pos = j + 1
                continue
            entry = data[k:k + ln]
            pos = k + ln
            title = pth = src = src_cn = ''
            for f3, w3, v3 in _pb(entry):
                if w3 != 2:
                    continue
                if f3 in (2, 3) and not title:
                    title = v3.decode('utf-8', 'replace')
                elif f3 == 4:
                    pth = v3.decode('utf-8', 'replace')
                elif f3 == 9:
                    src = v3.decode('utf-8', 'replace')
                elif f3 == 10:
                    src_cn = v3.decode('utf-8', 'replace')
            if not pth:
                continue
            if _RE_MEDIA.match(pth):
                ep_url = pth
            else:
                ep_url = base64.b64encode(json.dumps(
                    {'vodPlayFrom': src, 'playUrl': pth},
                    separators=(',', ':')).encode()).decode()
            eps.append((src_cn or src or '正片', title, ep_url))
        return eps, out

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags):
        self.log('player: flag=%s id=%s' % (flag, str(id)[:70]))
        if id and _RE_MEDIA.match(id):
            return {'parse': 0, 'playUrl': '', 'url': id,
                    'header': {'User-Agent': UA,
                               'Referer': self.site_url + '/'}}

        now = int(time.time())
        if id in self._play_cache:
            ts, res = self._play_cache[id]
            if now - ts < 600:
                self.log('  命中缓存')
                return res

        url, parse = '', 1
        # base64 封装的 {vodPlayFrom, playUrl} -> videoUsableUrl
        try:
            if id and not id.startswith('http') and '|' not in id:
                jm = json.loads(base64.b64decode(id))
                pf, pu = jm.get('vodPlayFrom', ''), jm.get('playUrl', '')
                qs = 'vodPlayFrom=%s&playUrl=%s' % (
                    urllib.parse.quote(pf), urllib.parse.quote(pu, safe=''))
                code, data = self._proto('/api/proto/v5/videoUsableUrl', qs)
                if code == 200 and data:
                    m = _RE_URL_IN_TEXT.search(data.decode('utf-8', 'replace'))
                    if m:
                        url = m.group(0)
        except Exception:
            pass

        # 第三方线路码(jd/v0/qq...) -> 走线路解析源
        if not url and id and '|' not in id and not id.startswith('http'):
            for l in self._lines:
                url = self._parse_play(l, id)
                if url:
                    break
        if not url:
            url = id or 'http://'
        parse = 0 if _RE_MEDIA.match(url) else 1
        res = {'parse': parse, 'playUrl': '', 'url': url,
               'header': {'User-Agent': UA,
                          'Referer': self.site_url + '/'}}
        self._play_cache[id] = (now, res)
        self.log('  => %s (parse=%d)' % (url[:120], parse))
        return res

    # ---------- 图片代理 ----------
    def localProxy(self, param):
        try:
            url = ''
            if isinstance(param, dict):
                url = param.get('url', '')
            else:
                for pair in str(param).split('&'):
                    if '=' in pair:
                        k, v = pair.split('=', 1)
                        if k == 'url':
                            url = v
            if not url:
                return [200, 'image/jpeg', b'', '']
            if '%' in url:
                url = urllib.parse.unquote(url)
            if url.startswith('//'):
                url = 'https:' + url
            rsp = self._http(url, None,
                             {'User-Agent': UA,
                              'Referer': self.site_url + '/'})
            return [200, 'image/jpeg', rsp, '']
        except Exception:
            return [200, 'image/jpeg', b'', '']
